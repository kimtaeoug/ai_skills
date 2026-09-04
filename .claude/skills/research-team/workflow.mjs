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
//   4. Recency filter        -> every claim carries a `date`; Synthesize is INSTRUCTED to
//      prefer the latest on conflict (prompt-driven, no date comparator — dates may be
//      commit hashes or "unknown").
//   5. Fact-check subagent   -> Verify re-checks every claim from an independent agent
//      call before Synthesize ever sees it.

export const meta = {
  name: 'research-team',
  description:
    'Cited, fact-checked research: parallel find (web/code) -> independent per-claim verify -> evidence/reasoning/conclusion synthesis -> report',
  phases: [
    { title: 'Plan' },
    { title: 'Find' },
    { title: 'Verify' },
    { title: 'Synthesize' },
    { title: 'Report' },
  ],
}

const FIND_LANES = 3 // fixed lane count regardless of mode

// Some Workflow tool callers deliver `args` as a JSON-encoded string instead of the
// documented object (observed in practice) — parse defensively rather than trust the type.
const parsedArgs = typeof args === 'string' ? JSON.parse(args) : args

const question = parsedArgs && parsedArgs.question
const mode = (parsedArgs && parsedArgs.mode) || 'both' // 'web' | 'code' | 'both'
const repoPath = (parsedArgs && parsedArgs.repoPath) || '.'
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
  const reportWritten = await persistFile(`${dir}/report.md`, report)
  return {
    status: 'no-claims-found',
    dir,
    reportWritten,
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
const reportWritten = await persistFile(`${dir}/report.md`, report)

const synthesisAttempted = confirmed.length > 0
return {
  status: synthesis ? 'answered' : synthesisAttempted ? 'synthesis-failed' : 'no-confirmed-claims',
  dir,
  reportWritten,
  answer: synthesis
    ? renderAnswer(synthesis)
    : synthesisAttempted
    ? `${confirmed.length} claim(s) were confirmed, but the synthesis step itself failed (agent error, not a claims problem) — retry the question rather than treating this as "nothing found."`
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
          'Do not combine local and external evidence into one claim with one source. For',
          'each point, emit a separate code-side claim (citing path:line or commit) AND a',
          'separate web-side claim (citing the URL), so each has exactly one verifiable',
          'source. If you want to assert that the two agree or disagree, state that as its',
          'own claim citing whichever single source most directly supports it, or emit it',
          'as two claims (one per side).',
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
  // agent() returns null on terminal failure (e.g. rate-limited) instead of throwing,
  // so a failed write is silent unless we return the outcome. The caller surfaces it as
  // `reportWritten` so a stale report.md from a prior run isn't mistaken for this run's.
  const result = await agent(
    [
      `Write the following exact content to "${path}" using Write`,
      '(create parent directories if needed, overwrite if the file exists; do not alter the content).',
      '---BEGIN CONTENT---',
      content,
      '---END CONTENT---',
    ].join('\n'),
    { label: `persist:${path}` }
  )
  return result != null
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
    synthesis
      ? renderAnswer(synthesis)
      : claims.some((c) => c.verdict === 'CONFIRMED')
      ? '(confirmed claims existed, but the synthesis step failed — not a "no answer" case)'
      : '(no confirmed claims — no answer synthesized)',
  ].join('\n')
}
