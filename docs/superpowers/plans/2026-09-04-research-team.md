# research-team Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reusable project skill `research-team` that runs a multi-agent
research pipeline (find → independently verify → synthesize) enforcing 5 fixed rules:
uncertainty allowed, mandatory citation, chain-of-thought output order, recency
preference on conflicting claims, and independent fact-check before the final answer.

**Architecture:** Follows the existing `archon-adversarial-dev` convention in this repo:
a thin `SKILL.md` (trigger + arg parsing + Workflow-availability check) plus a
`workflow.mjs` that does all orchestration via the session's Workflow tool
(`agent`/`parallel`/`phase`). No new dependencies.

**Tech Stack:** Claude Code Workflow tool (`agent()`/`parallel()`/`phase()`), existing
`WebSearch`/`WebFetch`/`claude-in-chrome`/`Grep`/`Read`/`Bash git` tools. Plain JS
(`.mjs`), no imports, no TypeScript.

## Global Constraints

- No new dependencies, no package installs. Reuse `WebSearch`, `WebFetch`,
  `claude-in-chrome`, `Grep`, `Read`, `Bash` (for `git log`/`git show`) only.
- `workflow.mjs` has no filesystem access of its own — every file write happens
  inside an `agent()` call (Write tool), never as direct JS.
- `export const meta = {...}` must be the first thing in `workflow.mjs`, a pure
  literal (per Workflow tool spec).
- No `Date.now()`, `Math.random()`, or argless `new Date()` inside `workflow.mjs`.
- Find fan-out is fixed at 3 lanes regardless of mode.
- Verify runs one independent agent per claim — the agent that produced a claim
  never verifies its own claim.
- `UNVERIFIABLE` and `blocked` are never treated as `CONFIRMED`. Only `CONFIRMED`
  claims may reach Synthesize.
- Source access fallback order, both in Find (web lanes) and Verify: `WebFetch` →
  `claude-in-chrome` (`navigate` + `get_page_text`/`read_page`, `ToolSearch` first) →
  `blocked` (stop, do not retry the same source, move to the next). Never trigger a
  JS `alert`/`confirm`/`prompt` dialog.
- Final answer structure is fixed: **근거 (evidence) → 추론 (reasoning) → 결론
  (conclusion)**, with an optional **확인 안 됨 (unresolved)** section only when a
  gap exists. Never fill a gap with a guess.
- File locations: `.claude/skills/research-team/SKILL.md`,
  `.claude/skills/research-team/workflow.mjs`, report output at
  `nimbalyst-local/research/<slug>/report.md`.
- Source of truth for behavior: `docs/superpowers/specs/2026-09-04-research-team-design.md`.
- Deviation from spec's testing section: the design doc proposed a `node --test` suite for
  "pure helper functions." In practice every non-trivial decision here (recency comparison,
  mode classification) turned out to be agent-prompt-driven, not deterministic JS — the only
  pure functions left (`slugify`, `buildFindLanes`, `renderClaimsTable`/`renderAnswer`/
  `renderReport`) are trivial one-liners/string-joins with no branch worth a persisted test,
  matching this repo's own `archon-adversarial-dev/workflow.mjs` precedent (same shape of
  helpers, no test file). `node --check` cannot run on this file at all — the Workflow tool's
  top-level `return` contract is not valid standalone ES module syntax (same for archon's
  file). Task 1 uses a structural grep guard against the specific failure mode of "wrapping
  the body in a function to dodge that" instead; Task 3 is the real behavioral check.

---

### Task 1: workflow.mjs — orchestration script

**Files:**
- Create: `.claude/skills/research-team/workflow.mjs`

**Interfaces:**
- Consumes (Workflow tool args): `{ question: string, mode: 'web'|'code'|'both', repoPath?: string }`
- Produces (script return value, consumed by SKILL.md/orchestrator):
  `{ status: 'answered'|'no-confirmed-claims'|'no-claims-found', dir: string,
  answer: string, claimsSummary?: { total, confirmed, refuted, unverifiable } }`

- [ ] **Step 1: Write the complete orchestration script**

```javascript
// research-team — Workflow DAG body.
//
// Executed via the session's Workflow tool:
//   Workflow({ scriptPath: ".claude/skills/research-team/workflow.mjs",
//              args: { question, mode, repoPath } })
//
// Design doc (source of truth for behavior changes):
//   docs/superpowers/specs/2026-09-04-research-team-design.md
//
// Contract this file targets (per the Workflow tool spec):
//   - `export const meta = {...}` must be a pure literal, first thing in the file.
//   - agent()/parallel()/pipeline()/phase()/log()/args are AMBIENT GLOBALS, not
//     parameters. There is no exported run() function.
//   - This file has NO filesystem access — every file write happens inside an
//     agent() call (persistFile pattern), never in this file's own JS.
//   - Structured data comes back via `schema` (StructuredOutput), never regex-parsed.
//
// FALLBACK: if the Workflow tool itself is unavailable, SKILL.md instructs the
// orchestrator to read this file as a procedure and reproduce the phases by hand
// with direct `Agent` tool calls (one message, multiple tool uses) instead of
// agent()/parallel(). That decision happens before Plan — see SKILL.md.
//
// 5 rules this pipeline enforces (see design doc):
//   1. Uncertainty allowed   -> Synthesize marks gaps "unresolved", never guesses.
//   2. Citation mandatory    -> Find's claim schema requires `source`; no source, no claim.
//   3. Chain-of-thought      -> Synthesize output is evidence -> reasoning -> conclusion.
//   4. Recency filter        -> claim schema requires `date`; Synthesize prefers latest.
//   5. Fact-check subagent   -> Verify re-checks every claim from an independent agent
//      call before Synthesize ever sees it.

export const meta = {
  name: 'research-team',
  description:
    'Cited, fact-checked research: parallel find (web/code) -> independent per-claim ' +
    'verify -> evidence/reasoning/conclusion synthesis -> report',
  phases: [
    { title: 'Plan' },
    { title: 'Find' },
    { title: 'Verify' },
    { title: 'Synthesize' },
    { title: 'Report' },
  ],
}

const FIND_LANES = 3 // fixed lane count regardless of mode

const question = args && args.question
const mode = (args && args.mode) || 'both' // 'web' | 'code' | 'both'
const repoPath = (args && args.repoPath) || '.'
if (!question) throw new Error('research-team: question is required')
if (!['web', 'code', 'both'].includes(mode)) {
  throw new Error(`research-team: mode must be web|code|both, got "${mode}"`)
}

const slug = slugify(question)
const dir = `nimbalyst-local/research/${slug}`

const SOURCE_FALLBACK = [
  '1. Try WebFetch first.',
  '2. If the page needs JS rendering or WebFetch cannot get real content, use',
  '   claude-in-chrome instead: ToolSearch for the chrome tools if not loaded yet, then',
  '   navigate to the URL and read it with get_page_text or read_page.',
  '3. If claude-in-chrome is also blocked (login wall, captcha, explicit block), stop —',
  '   do not retry the same source again. Record the source as blocked and move on.',
  '   Never trigger a JS alert/confirm/prompt dialog.',
].join('\n')

const CLAIM_SCHEMA = {
  type: 'object',
  properties: {
    claim: { type: 'string' },
    source: { type: 'string' },
    date: { type: 'string' },
    confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
  },
  required: ['claim', 'source', 'date', 'confidence'],
}

const FIND_SCHEMA = {
  type: 'object',
  properties: { claims: { type: 'array', items: CLAIM_SCHEMA } },
  required: ['claims'],
}

const VERIFY_SCHEMA = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['CONFIRMED', 'REFUTED', 'UNVERIFIABLE'] },
    accessPath: {
      type: 'string',
      enum: ['webfetch', 'chrome', 'blocked', 'local-read', 'not-applicable'],
    },
    note: { type: 'string' },
  },
  required: ['verdict', 'accessPath', 'note'],
}

const PLAN_SCHEMA = {
  type: 'object',
  properties: {
    angles: { type: 'array', items: { type: 'string' }, minItems: 1, maxItems: 3 },
  },
  required: ['angles'],
}

const SYNTH_SCHEMA = {
  type: 'object',
  properties: {
    evidenceMarkdown: { type: 'string' },
    reasoningMarkdown: { type: 'string' },
    conclusionMarkdown: { type: 'string' },
    unresolvedMarkdown: { type: 'string' },
  },
  required: ['evidenceMarkdown', 'reasoningMarkdown', 'conclusionMarkdown', 'unresolvedMarkdown'],
}

// ---------------------------------------------------------------------------
// PHASE 1: plan — break the question into up to 3 distinct search angles.
// ---------------------------------------------------------------------------
phase('Plan')
const planned = await agent(
  [
    `Break this research question into up to ${FIND_LANES} distinct, non-overlapping`,
    'search angles (e.g. definition/spec, latest developments, counter-evidence). Fewer',
    'than 3 is fine if the question is narrow — do not pad with redundant angles.',
    `Question: ${question}`,
  ].join('\n'),
  { label: 'plan:angles', schema: PLAN_SCHEMA }
)
const angles = (
  planned && planned.angles && planned.angles.length ? planned.angles : [question]
).slice(0, FIND_LANES)

// ---------------------------------------------------------------------------
// PHASE 2: find — one finder per lane, independent, source-tagged claims only.
// ---------------------------------------------------------------------------
phase('Find')
const lanes = buildFindLanes(mode, angles, FIND_LANES)
const findResults = await parallel(lanes.map((lane) => () => runFinder(lane, question, repoPath)))
const allClaims = findResults
  .map((r, i) => ((r && r.claims) || []).map((c) => ({ ...c, laneKind: lanes[i].kind })))
  .flat()

if (allClaims.length === 0) {
  phase('Report')
  const report = renderReport({ question, mode, claims: [], synthesis: null, dir })
  await persistFile(`${dir}/report.md`, report)
  return {
    status: 'no-claims-found',
    dir,
    answer: 'No sourced claims could be found for this question.',
  }
}

// ---------------------------------------------------------------------------
// PHASE 3: verify — independent re-check of every claim, one agent per claim.
// ---------------------------------------------------------------------------
phase('Verify')
const verifications = await parallel(allClaims.map((c) => () => verifyClaim(c)))
const verifiedClaims = allClaims.map((c, i) => ({
  ...c,
  ...(verifications[i] || {
    verdict: 'UNVERIFIABLE',
    accessPath: 'blocked',
    note: '(verify agent produced no result)',
  }),
}))
const confirmed = verifiedClaims.filter((c) => c.verdict === 'CONFIRMED')

// ---------------------------------------------------------------------------
// PHASE 4: synthesize — evidence -> reasoning -> conclusion, confirmed claims only.
// ---------------------------------------------------------------------------
phase('Synthesize')
let synthesis = null
if (confirmed.length > 0) {
  synthesis = await agent(
    [
      `Question: ${question}`,
      'Write the final answer using ONLY the confirmed claims below. Do not use any',
      'claim not listed here, and do not add outside knowledge as fact.',
      'If claims conflict on the same point, prefer the one with the more recent date',
      'and say so explicitly in the evidence section.',
      'If any part of the question cannot be answered from these claims, name that gap',
      'in unresolvedMarkdown instead of guessing.',
      `Confirmed claims:\n${JSON.stringify(confirmed, null, 2)}`,
    ].join('\n\n'),
    { label: 'synthesize', schema: SYNTH_SCHEMA }
  )
}

// ---------------------------------------------------------------------------
// PHASE 5: report — persist full record, return chat-ready answer.
// ---------------------------------------------------------------------------
phase('Report')
const report = renderReport({ question, mode, claims: verifiedClaims, synthesis, dir })
await persistFile(`${dir}/report.md`, report)

return {
  status: synthesis ? 'answered' : 'no-confirmed-claims',
  dir,
  answer: synthesis
    ? renderAnswer(synthesis)
    : 'No claim survived independent verification — nothing confirmed to answer from.',
  claimsSummary: {
    total: verifiedClaims.length,
    confirmed: confirmed.length,
    refuted: verifiedClaims.filter((c) => c.verdict === 'REFUTED').length,
    unverifiable: verifiedClaims.filter((c) => c.verdict === 'UNVERIFIABLE').length,
  },
}

// ---------------------------------------------------------------------------
// Helpers below. Pure JS ones do plain data-shaping only. Every helper that
// touches the filesystem, network, or a subagent does so via agent() — this
// script has no FS/network access of its own.
// ---------------------------------------------------------------------------

function slugify(text) {
  return String(text)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60)
}

function buildFindLanes(mode, angles, laneCount) {
  const kinds =
    mode === 'web'
      ? Array(laneCount).fill('web')
      : mode === 'code'
      ? Array(laneCount).fill('code')
      : ['web', 'code', 'cross'].slice(0, laneCount)
  return kinds.map((kind, i) => ({ kind, angle: angles[i % angles.length] }))
}

async function runFinder(lane, question, repoPath) {
  const instructions =
    lane.kind === 'web'
      ? [
          'Search the web for sourced claims answering this angle. Use WebSearch to find',
          'candidate pages, then fetch each with this fallback order:',
          SOURCE_FALLBACK,
          'Every claim must cite a real URL you actually fetched — never a search result',
          'snippet alone.',
        ].join('\n')
      : lane.kind === 'code'
      ? [
          `Investigate this angle against the local repo at "${repoPath}" using Grep, Read,`,
          'and `git log`/`git blame` via Bash. Every claim must cite `path:line` or a commit',
          'hash/date you actually read — never a guess about what the code probably does.',
        ].join('\n')
      : [
          `First gather local evidence from the repo at "${repoPath}" (Grep/Read/git log)`,
          'for how this is actually implemented. Then gather external evidence with',
          'WebSearch/WebFetch (fallback order below) for what the spec/best-practice says.',
          'Produce claims that state whether the local implementation matches the',
          'external source, citing both sides.',
          SOURCE_FALLBACK,
        ].join('\n')

  const result = await agent(
    [
      `Research angle: ${lane.angle}`,
      `Full question (context): ${question}`,
      instructions,
      'Return ONLY claims that have a real source you actually checked. If you find',
      'nothing sourced for this angle, return an empty claims array — do not invent one.',
      'Each claim needs a `date` (publish date, commit date, or "unknown" if truly',
      'undated — mark unknown dates as low confidence).',
    ].join('\n\n'),
    { label: `find:${lane.kind}:${lane.angle}`, schema: FIND_SCHEMA }
  )
  return result || { claims: [] }
}

async function verifyClaim(claim) {
  const isUrl = /^https?:\/\//.test(claim.source)
  const instructions = isUrl
    ? [
        `Re-fetch this URL yourself (do not trust the claim text alone): ${claim.source}`,
        SOURCE_FALLBACK,
        'Confirm whether the claim text is actually supported by what you find there.',
      ].join('\n')
    : [
        `Re-read this local reference yourself: ${claim.source}`,
        'Use Read (and Bash `git show`/`git log` if it looks like a commit reference) to',
        'confirm whether the claim text is actually supported by what you find there.',
      ].join('\n')

  const result = await agent(
    [
      `Claim to verify: ${claim.claim}`,
      `Cited source: ${claim.source}`,
      instructions,
      'Verdict rules: CONFIRMED only if you personally found the supporting content at',
      'the source. REFUTED if the source contradicts the claim or says something',
      'different. UNVERIFIABLE if the source is blocked/gone/inconclusive after trying',
      'the fallback order above — never guess CONFIRMED to be helpful.',
    ].join('\n\n'),
    { label: `verify:${claim.source}`, schema: VERIFY_SCHEMA }
  )
  return (
    result || {
      verdict: 'UNVERIFIABLE',
      accessPath: 'blocked',
      note: '(verify agent produced no result)',
    }
  )
}

async function persistFile(path, content) {
  await agent(
    [
      `Write the following exact content to "${path}" using Write`,
      '(create parent directories if needed, overwrite if the file exists; do not alter the content).',
      '---BEGIN CONTENT---',
      content,
      '---END CONTENT---',
    ].join('\n'),
    { label: `persist:${path}` }
  )
}

function renderAnswer(synthesis) {
  const parts = [
    '## 근거',
    synthesis.evidenceMarkdown,
    '',
    '## 추론',
    synthesis.reasoningMarkdown,
    '',
    '## 결론',
    synthesis.conclusionMarkdown,
  ]
  if (synthesis.unresolvedMarkdown && synthesis.unresolvedMarkdown.trim()) {
    parts.push('', '## 확인 안 됨', synthesis.unresolvedMarkdown)
  }
  return parts.join('\n')
}

function renderClaimsTable(claims) {
  if (claims.length === 0) return '(no claims)'
  const header = '| claim | source | date | verdict | access |\n|---|---|---|---|---|'
  const rows = claims.map(
    (c) =>
      `| ${c.claim.replace(/\|/g, '\\|')} | ${c.source} | ${c.date} | ${c.verdict} | ${c.accessPath} |`
  )
  return [header, ...rows].join('\n')
}

function renderReport({ question, mode, claims, synthesis, dir }) {
  return [
    '# research-team report',
    '',
    `Question: ${question}`,
    `Mode: ${mode}`,
    `Artifacts: ${dir}/`,
    '',
    '## Claims',
    renderClaimsTable(claims),
    '',
    '## Final answer',
    synthesis ? renderAnswer(synthesis) : '(no confirmed claims — no answer synthesized)',
  ].join('\n')
}
```

- [ ] **Step 2: Structural check — confirm the script body is NOT wrapped in an extra function**

`node --check` does **not** apply to this file: the Workflow tool contract requires genuine
top-level `return`/`await` statements (confirmed against `.claude/skills/archon-adversarial-dev/workflow.mjs`,
which also fails `node --check` for the same reason — `SyntaxError: Illegal return statement`).
Do not "fix" that by wrapping the body in `(async () => { ... })()` or any other function —
that silently breaks the Workflow tool's ability to capture the script's return value (the
IIFE's return exits the IIFE, not the script), so the tool would resolve to `undefined`
instead of `{status, dir, answer, claimsSummary}`. Verify no such wrapper was introduced:

Run: `grep -nE '^\s*\(async|^\s*\}\)\(\)\s*$' .claude/skills/research-team/workflow.mjs`
Expected: no output (no IIFE wrapper present; `return`/`await` stay genuinely top-level).

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/research-team/workflow.mjs
git commit -m "feat: add research-team workflow orchestration script"
```

---

### Task 2: SKILL.md — trigger and invocation

**Files:**
- Create: `.claude/skills/research-team/SKILL.md`

**Interfaces:**
- Consumes: user's natural-language research request (Korean or English).
- Produces: a `Workflow({ scriptPath: ".claude/skills/research-team/workflow.mjs", args: {...} })`
  call whose return value (`status`, `answer`, `dir`, `claimsSummary`) matches Task 1's contract.

- [ ] **Step 1: Write the skill file**

```markdown
---
name: research-team
description: >
  임의 주제(개발/코드든 일반 도메인 지식이든)를 조사할 때 5개 규칙 — 불확실성 허용, 인용
  의무화, chain-of-thought 순서(근거→추론→결론), 날짜/최신성 필터, 최종 답변 전 팩트검증
  서브에이전트 재확인 — 을 항상 강제 적용하는 멀티에이전트 조사 파이프라인. Workflow 툴로
  검색 fan-out(웹/코드) → 독립 인용구 재검증 → 종합 → 리포트를 실행한다.
  Trigger phrases — 한국어: "자료조사팀 돌려줘", "출처 검증해서 조사해줘", "이 질문
  팩트체크하면서 조사해줘", "근거 대면서 답해줘"; English: "run the research team",
  "research this with citations and fact-checking".
---

# research-team

임의 주제를 조사할 때 다음 5개 규칙을 항상 강제하는 project skill이다: 불확실성 허용,
인용 의무화, chain-of-thought 순서(근거→추론→결론), 날짜/최신성 필터, 최종 답변 전 팩트검증
서브에이전트 재확인. 실행 로직은 전부 `workflow.mjs`에 있다 — 이 파일은 트리거 인지와 인자
파싱만 한다.

설계 근거: `docs/superpowers/specs/2026-09-04-research-team-design.md`. 동작을 바꾸려면
스킬 파일이 아니라 그 설계 문서부터 갱신할 것.

## 1. 인자 파싱

- 사용자 요청에서 **조사 질문**(`question`)을 추출한다. 비어 있으면 무엇을 조사할지 한 줄로
  물은 뒤 진행한다.
- **모드 판단** (`mode`): 질문이 특정 로컬 레포/코드베이스를 가리키면 `code`, 일반 지식이나
  외부 스펙이면 `web`, 둘 다 걸치면 `both`. 애매하면 `both`로 기본 설정한다(정보 누락보다
  과다 조사가 안전). 예:
  - "이 프로젝트의 인증 흐름 뭐야?" → `code`
  - "OAuth 2.1 PKCE 스펙 최신 권고안은?" → `web`
  - "우리 인증 구현이 최신 OAuth 스펙 따르나?" → `both`
- `code`/`both` 모드에서 대상 레포 경로(`repoPath`)가 명시 안 되면 현재 작업 디렉터리를
  기본값으로 쓴다.

## 2. Workflow 가용성 확인 (필수, 매 실행 첫 스텝)

이 스킬은 세션의 **Workflow 툴**(`agent()`/`parallel()`)을 실행 엔진으로 쓴다. 매번 먼저
확인한다:

1. `Workflow`가 이 세션의 도구 목록(또는 `ToolSearch`로 지연 로드되는 도구 목록)에 있는지
   확인한다.
2. 있으면 아래 3번(Workflow 경로)으로 진행.
3. 없으면 **폴백**: `workflow.mjs`를 실행 가능한 스크립트가 아니라 **절차서로 읽고**, 그
   안의 5단계(Plan/Find/Verify/Synthesize/Report)와 각 단계의 프롬프트·스키마·소스 접근
   폴백 순서(WebFetch → claude-in-chrome → blocked)를 그대로 따라 `Agent` tool을 한
   메시지에 여러 tool call로 동시 호출하는 방식(`superpowers:dispatching-parallel-agents`
   패턴)으로 재현한다. Find는 3개, Verify는 claim 수만큼(한 메시지당 최대 4개씩 나눠) 병렬
   호출한다. 폴백이 발생했다는 사실을 최종 보고에 명시한다.

## 3. 실행

Workflow가 가용하면:

```
Workflow({
  scriptPath: ".claude/skills/research-team/workflow.mjs",
  args: { question: "<추출한 질문>", mode: "<web|code|both>", repoPath: "<대상 경로 또는 생략>" }
})
```

## 4. 결과 보고

스크립트가 반환한 값을 그대로 정직하게 전달한다:

- `answer` 필드를 채팅에 그대로 출력한다(근거/추론/결론/확인 안 됨 섹션 구조를 그대로
  유지 — 재구성하거나 요약하지 않는다).
- `claimsSummary`(전체/확인/반박/미확인 건수)를 한 줄로 덧붙인다.
- `dir` 경로(`nimbalyst-local/research/<slug>/report.md`)를 저장 위치로 언급한다.
- `status`가 `no-claims-found`/`no-confirmed-claims`면 그 사실을 숨기지 않고 그대로
  전달한다 — 억지로 답을 만들어내지 않는다.
- Verify 단계에서 원출처 재확인을 실제로 했다는 것(claim을 만든 에이전트가 자기 검증을 하지
  않는다는 것)을 사용자가 물으면 설명할 수 있어야 한다 — report.md의 Claims 표에 소스별
  판정(`CONFIRMED`/`REFUTED`/`UNVERIFIABLE`)과 접근 경로(`webfetch`/`chrome`/`blocked`/
  `local-read`)가 남아있다.
```

- [ ] **Step 2: Validate frontmatter is well-formed (delimiters + required keys present)**

Run: `awk '/^---$/{c++} c==2{exit} c>=1' .claude/skills/research-team/SKILL.md | grep -E '^(name|description):'`
Expected: two lines printed, `name: research-team` and a `description:` line — confirms the
YAML frontmatter block is closed and both required keys are present.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/research-team/SKILL.md
git commit -m "feat: add research-team skill trigger and invocation"
```

---

### Task 3: End-to-end smoke test

**Files:** none (verification only; fixes, if any, land back in Task 1/2's files).

**Interfaces:**
- Consumes: Task 1 + Task 2 as built.
- Produces: confirmation that the 5 rules actually hold in a real run, or a list of concrete
  fixes to apply before considering the skill done.

- [ ] **Step 1: Run a `code`-mode question against this repo**

Invoke: `Workflow({ scriptPath: ".claude/skills/research-team/workflow.mjs", args: { question: "test-agent-team 스킬은 UI 테스트를 코드 검사 병렬 그룹과 동시에 실행하나, 아니면 그 뒤에 직렬로 실행하나?", mode: "code", repoPath: "/Users/deratio/skills" } })`

Expected:
- `status: "answered"`.
- `nimbalyst-local/research/<slug>/report.md` exists, Claims table has at least one row with
  a `path:line`-style source inside `.claude/skills/test-agent-team/SKILL.md`, verdict
  `CONFIRMED`.
- `answer` states the UI test step runs serially *after* the parallel group (matches
  `.claude/skills/test-agent-team/SKILL.md` section 3: "기본값: 병렬 그룹 완료 후, 단일
  lane으로 직렬 실행한다").
- `answer` has `## 근거` / `## 추론` / `## 결론` headers in that order.

- [ ] **Step 2: Run a `web`-mode question to exercise the WebFetch/chrome fallback path**

Invoke: `Workflow({ scriptPath: ".claude/skills/research-team/workflow.mjs", args: { question: "Anthropic Claude Sonnet 5 모델 ID는 뭐야?", mode: "web" } })`

Expected:
- `status: "answered"`, with at least one `CONFIRMED` claim citing a real fetched URL (not a
  bare search snippet).
- Claims table's `access` column shows `webfetch` for at least one row (or `chrome` if a
  source needed JS rendering — either is acceptable, but `blocked`-only for every source
  means the fallback chain needs debugging).
- No claim has `verdict: CONFIRMED` with `note` admitting the content wasn't actually seen —
  spot-check one `CONFIRMED` claim's `note` field for a genuine confirmation statement.

- [ ] **Step 3: Fix any gap found in Step 1 or Step 2 directly in `workflow.mjs`, re-run only the
  failing case, and confirm it passes.**

If both steps pass with no changes needed, skip this step.

- [ ] **Step 4: If Step 3 made changes, commit**

```bash
git add .claude/skills/research-team/workflow.mjs
git commit -m "fix: correct research-team pipeline behavior found in smoke test"
```

If no changes were needed, no commit for this task.
