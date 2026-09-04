// archon-adversarial-dev — Workflow DAG body.
//
// Executed via the session's Workflow tool:
//   Workflow({ scriptPath: ".claude/skills/archon-adversarial-dev/workflow.mjs",
//              args: { task, maxRounds } })
//
// Design doc (source of truth for behavior changes):
//   docs/superpowers/specs/2026-09-04-archon-adversarial-dev-design.md
//
// Contract this file actually targets (per the Workflow tool spec):
//   - `export const meta = {...}` must be a pure literal, first thing in the file.
//   - The script body runs directly (top-level await, top-level return) — agent()/
//     parallel()/pipeline()/phase()/log()/args/budget are AMBIENT GLOBALS, not
//     parameters. There is no exported run() function.
//   - The script itself has NO filesystem or Bash access. Every file write and every
//     Bash command runs INSIDE an agent() call (subagents have real Read/Write/Bash),
//     never in this file's own JS. Persisting an artifact = asking an agent to write it.
//   - Structured data (subtasks, findings, pass/fail) comes back via `schema` (forces
//     a StructuredOutput tool call) instead of regex-parsing free text.
//
// FALLBACK: if the Workflow tool itself is unavailable, or agentType:
// "codex:codex-rescue" fails to resolve CLAUDE_PLUGIN_ROOT, SKILL.md instructs the
// orchestrator to abandon script execution and follow this file's phase structure by
// hand instead, replacing agent()/parallel() with direct `Agent` tool calls (one
// message, multiple tool uses, same fan-out cap and depth=1 rule). That decision must
// happen before any Codex call — see PHASE 0 / preflight below.
//
// Roles are fixed: Codex only implements (codex:codex-rescue), Claude only reviews
// (default workflow agent). Codex critiques only during planning. No nested subagent
// delegation (depth=1) — codex:codex-rescue shells out to the codex CLI, which has no
// access to our Agent/Workflow tools, so this is naturally enforced.
// Fan-out cap: max 4 concurrent per wave, for both implement and review.

export const meta = {
  name: 'archon-adversarial-dev',
  description:
    'Claude+Codex adversarial dev loop: plan/critique/consensus (with subtask split) -> wave-parallel Codex implement -> per-wave validate -> 3-lens parallel Claude review -> iterate/triage -> report',
  phases: [
    { title: 'Preflight' },
    { title: 'Plan' },
    { title: 'Critique' },
    { title: 'Consensus' },
    { title: 'Implement' },
    { title: 'Validate' },
    { title: 'Review' },
    { title: 'Report' },
  ],
}

const CODEX_AGENT_TYPE = 'codex:codex-rescue'
const MAX_CONCURRENCY = 4 // fan-out cap per wave (implement + review), hard limit
const MAX_CRITIQUE_ROUNDS = 2 // plan<->critique ping-pong cap before AskUserQuestion
const DEFAULT_MAX_ROUNDS = 5 // implement->review round cap

// ponytail: defensive parse — this harness has been observed to deliver `args` as a
// JSON-encoded string instead of the object the Workflow tool docs promise. Accept
// either shape rather than trusting the docs blindly.
const resolvedArgs = typeof args === 'string' ? JSON.parse(args) : args
const task = resolvedArgs && resolvedArgs.task
const maxRounds = (resolvedArgs && resolvedArgs.maxRounds) || DEFAULT_MAX_ROUNDS
if (!task) throw new Error('archon-adversarial-dev: task description is required')

const slug = slugify(task)
const dir = `nimbalyst-local/plans/adversarial-dev/${slug}`

const SUBTASK_SCHEMA = {
  type: 'object',
  properties: {
    id: { type: 'string' },
    description: { type: 'string' },
    dependsOn: { type: 'array', items: { type: 'string' } },
    ownsFiles: { type: 'array', items: { type: 'string' } },
    touchesContracts: { type: 'array', items: { type: 'string' } },
  },
  required: ['id', 'description', 'dependsOn', 'ownsFiles', 'touchesContracts'],
}

// ---------------------------------------------------------------------------
// PHASE 0: preflight — codex ping (spike), then dir reset + baseline capture.
// Ping first: fail fast and cheap before doing any real work.
// ---------------------------------------------------------------------------
phase('Preflight')

const ping = await agent(
  [
    '--fresh read-only, research/critique only, do not edit files.',
    'Reply with exactly one line: "codex ready".',
  ].join('\n'),
  { agentType: CODEX_AGENT_TYPE, label: 'preflight:codex-ping' }
)
if (!ping || !String(ping).toLowerCase().includes('codex ready')) {
  return {
    status: 'aborted',
    reason:
      'preflight codex ping failed — Codex not reachable via codex:codex-rescue. ' +
      'Advise the user to run /codex:setup, then stop. Do not proceed to plan.',
  }
}

// Baseline: reset the artifacts dir, detect the repo's real build/test command (same
// "reuse what the repo already runs" policy as test-agent-team), run it once, and
// write the result to disk. Failure to capture does NOT abort — conservative
// fallback: treat all later validate failures as new regressions if this failed.
const baseline = (await agent(
  [
    `1. Run Bash: rm -rf "${dir}" && mkdir -p "${dir}"`,
    `2. Detect this repo's real build/lint/typecheck/test command(s) the same way the`,
    `   test-agent-team skill does (package.json scripts, CI config, Makefile — reuse`,
    `   what the repo actually runs; do not invent new tooling or install anything).`,
    `3. Run the detected command(s) via Bash and capture the full output.`,
    `4. Write a markdown report of the full output to "${dir}/baseline.md" using Write.`,
  ].join('\n'),
  {
    label: 'preflight:baseline',
    schema: {
      type: 'object',
      properties: {
        command: { type: 'string' },
        passed: { type: 'boolean' },
        output: { type: 'string' },
        captureFailed: { type: 'boolean' },
      },
      required: ['command', 'passed', 'output', 'captureFailed'],
    },
  }
)) || { command: '', passed: false, output: '(baseline agent produced no result)', captureFailed: true }

// ---------------------------------------------------------------------------
// PHASE 1: plan (Claude) <-> critique (Codex, read-only) <-> consensus
// ---------------------------------------------------------------------------
phase('Plan')
let planText = await agent(
  [
    `Draft a concise implementation plan for: ${task}`,
    'Include: goal, key files/paths, design choices, risks. Use Glob/Grep/Read to ground',
    'the draft in the actual repo.',
    `Then write the plan to "${dir}/plan.md" using Write. Return the plan text.`,
  ].join('\n'),
  { label: 'plan:draft' }
)

phase('Critique')
let critique = ''
let bigDisagreement = false
for (let round = 1; round <= MAX_CRITIQUE_ROUNDS; round++) {
  const critiquePath = round === 1 ? `${dir}/critique.md` : `${dir}/critique-${round}.md`
  const critiqued = await agent(
    [
      '--fresh read-only, research/critique only, do not edit files.',
      `Here is a proposed implementation plan for: ${task}`,
      planText,
      'Critique it: gaps, better alternatives, missed risks, dissenting opinion.',
      'Judge whether there is a BIG disagreement (a core design decision genuinely in',
      'dispute, not a minor nitpick).',
      `Write your critique to "${critiquePath}" using Write.`,
    ].join('\n\n'),
    {
      agentType: CODEX_AGENT_TYPE,
      label: `critique:round-${round}`,
      schema: {
        type: 'object',
        properties: {
          critique: { type: 'string' },
          bigDisagreement: { type: 'boolean' },
        },
        required: ['critique', 'bigDisagreement'],
      },
    }
  )
  critique = (critiqued && critiqued.critique) || ''
  bigDisagreement = Boolean(critiqued && critiqued.bigDisagreement)

  if (round === MAX_CRITIQUE_ROUNDS || !bigDisagreement) break

  planText = await agent(
    [
      "Revise this plan given Codex's critique.",
      `Original plan:\n${planText}`,
      `Critique:\n${critique}`,
      `Then overwrite "${dir}/plan.md" with the revised plan using Write. Return the revised plan text.`,
    ].join('\n\n'),
    { label: `plan:revise-round-${round}` }
  )
}

if (bigDisagreement) {
  return {
    status: 'needs-user-decision',
    reason:
      'Plan/critique disagreement persisted after 2 rounds. Orchestrator must call ' +
      'AskUserQuestion with the core disputed decision before proceeding to consensus.',
    plan: planText,
    critique,
    dir,
  }
}

// ---------------------------------------------------------------------------
// consensus: merge into final plan + structured subtask list (schema-validated,
// no regex parsing). A single small task that doesn't need splitting is still a
// subtasks array of length 1 — the agent is told not to special-case it.
// ---------------------------------------------------------------------------
phase('Consensus')
const consensus = await agent(
  [
    'Merge the plan and critique into a final consensus plan, and split the work into',
    "subtasks. A single small task that doesn't need splitting is still a subtasks",
    'array of length 1 — do not special-case it.',
    `Plan:\n${planText}`,
    `Critique:\n${critique}`,
    `Write the consensus plan text (prose, not the JSON) to "${dir}/consensus-plan.md" using Write.`,
  ].join('\n\n'),
  {
    label: 'consensus',
    schema: {
      type: 'object',
      properties: {
        consensusPlan: { type: 'string' },
        subtasks: { type: 'array', items: SUBTASK_SCHEMA },
      },
      required: ['consensusPlan', 'subtasks'],
    },
  }
)
const consensusPlan = (consensus && consensus.consensusPlan) || ''
// Ownership/contract overlap check: merge overlapping subtasks into one (dependsOn
// alone can't catch shared-file/shared-contract coupling). Safety net: even if this
// misses an overlap, per-wave validate catches it — this is an optimization, not the
// sole guard.
const subtasks = mergeOverlappingSubtasks((consensus && consensus.subtasks) || [])
await persistFile(`${dir}/subtasks.json`, JSON.stringify({ subtasks }, null, 2))

// ---------------------------------------------------------------------------
// PHASE 2..N: implement (wave-parallel) -> validate -> review -> decision.
// Loop until pass, or nothing left to retry, or maxRounds is exhausted.
// ---------------------------------------------------------------------------
let pending = subtasks // subtasks still needing (re-)implementation this round
let diffsById = {} // subtaskId -> latest known diff text
let round = 0

while (round < maxRounds) {
  round++
  const waves = topoSortIntoWaves(pending, subtasks)
  const failedImplementIds = new Set() // subtasks whose implement call produced no diff/files

  phase('Implement')
  for (let w = 0; w < waves.length; w++) {
    const wave = waves[w]
    for (const chunk of chunkBy(wave, MAX_CONCURRENCY)) {
      // Zip by index (not by result.id) so a hard agent() failure (parallel() resolves
      // it to null) can still be attributed to the right subtask.
      const chunkResults = await parallel(
        chunk.map((st) => () => implementSubtask(st, diffsById, consensusPlan))
      )
      chunk.forEach((st, i) => {
        const r = chunkResults[i]
        // A subtask that produced neither a diff nor a changed-files list did NOT
        // actually get implemented (e.g. a concurrent Codex thread collision) — this
        // must surface as a failure, not silently drop the subtask from review/decision.
        if (r && (r.diff || (r.filesChanged && r.filesChanged.length))) {
          diffsById[st.id] = r.diff
        } else {
          failedImplementIds.add(st.id)
        }
      })
    }

    phase('Validate')
    const waveValidation = await runValidate(
      baseline.command,
      `validate:wave-${round}-${w + 1}`,
      `${dir}/validation-wave-${round}-${w + 1}.md`
    )
    log(
      `round ${round} wave ${w + 1}/${waves.length}: ` +
        `${waveValidation.passed ? 'validate OK' : 'validate FAILED'}`
    )
    phase('Implement')
  }

  phase('Validate')
  const roundValidation = await runValidate(
    baseline.command,
    `validate:round-${round}`,
    `${dir}/validation-round-${round}.md`
  )

  // ---------------------------------------------------------------------
  // review: parallel, one reviewer per subtask with a known diff this round,
  // 3 fixed lenses, fixed finding schema.
  // ---------------------------------------------------------------------
  phase('Review')
  const reviewTargets = subtasks.filter((st) => diffsById[st.id])
  const reviewResults = []
  for (const chunk of chunkBy(reviewTargets, MAX_CONCURRENCY)) {
    const chunkResults = await parallel(
      chunk.map((st) => () => reviewSubtask(st, diffsById[st.id]))
    )
    reviewResults.push(...chunkResults)
  }
  await persistFile(`${dir}/review-round-${round}.md`, renderReviewReport(reviewResults))

  // ---------------------------------------------------------------------
  // decision
  // ---------------------------------------------------------------------
  const regressed = isNewRegression(baseline, roundValidation)
  const criticalFindings = reviewResults.flatMap((r) =>
    r.findings.filter((f) => f.severity === 'critical').map((f) => ({ ...f, subtaskId: r.id }))
  )

  if (!regressed && criticalFindings.length === 0 && failedImplementIds.size === 0) {
    phase('Report')
    const report = renderFinalReport({
      status: 'pass',
      round,
      dir,
      baseline,
      consensusPlan,
      subtasks,
    })
    // Do NOT delegate this write to an agent(): subagents are blocked from writing
    // report/summary-shaped files by harness policy. The orchestrator that invoked
    // this Workflow (which has real, unrestricted Write access) persists report.md
    // itself from this returned `report` string — see SKILL.md step 3.
    return { status: 'pass', round, dir, report }
  }

  // iterate: isolate to specific subtasks where possible; a whole-suite regression
  // that can't be pinned to one subtask's critical findings goes through triage
  // instead of blindly re-running the original subtasks. A subtask whose implement
  // call itself produced nothing (failedImplementIds) is always isolated and retried
  // directly — no need to guess why via triage, it just needs to actually run.
  const isolatedIds = [
    ...new Set([...criticalFindings.map((f) => f.subtaskId), ...failedImplementIds]),
  ]
  let triageSubtasks = []
  if (regressed && isolatedIds.length === 0) {
    const triaged = await agent(
      [
        'A validate run regressed (new failure vs baseline) but no single subtask was',
        'flagged critical by review — likely an integration mismatch between',
        'subtasks. Propose new subtask(s) to fix this. Do not just ask to re-run the',
        'original subtasks blindly.',
        `Validate output:\n${roundValidation.output}`,
        `Consensus plan:\n${consensusPlan}`,
      ].join('\n\n'),
      {
        label: `triage:round-${round}`,
        schema: {
          type: 'object',
          properties: { subtasks: { type: 'array', items: SUBTASK_SCHEMA } },
          required: ['subtasks'],
        },
      }
    )
    triageSubtasks = mergeOverlappingSubtasks((triaged && triaged.subtasks) || [])
    subtasks.push(...triageSubtasks)
  }

  pending = [...subtasks.filter((st) => isolatedIds.includes(st.id)), ...triageSubtasks]

  if (pending.length === 0) {
    // Regression/critical findings exist but nothing to retry — avoid an infinite loop.
    break
  }
}

phase('Report')
const finalReport = renderFinalReport({
  status: round >= maxRounds ? 'maxRounds-exceeded' : 'stalled',
  round,
  dir,
  baseline,
  consensusPlan,
  subtasks,
})
// See the pass-path comment above: report.md is written by the orchestrator from
// this returned string, not by an agent() call.
return { status: 'iterate-stopped', round, dir, report: finalReport }

// ---------------------------------------------------------------------------
// Helpers below. Pure JS ones (no agent()) do plain data-shaping only. Every helper
// that touches the filesystem or runs a command does so via an agent() call — this
// script has no FS/Bash access of its own.
// ---------------------------------------------------------------------------

function slugify(text) {
  return String(text)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60)
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

async function runValidate(knownCommand, label, reportPath) {
  const result = await agent(
    [
      knownCommand
        ? `Run this exact command via Bash: ${knownCommand}`
        : "Detect and run this repo's real build/lint/typecheck/test command(s), the " +
          'same way test-agent-team does (reuse what the repo actually runs).',
      `Write a markdown report of the full output to "${reportPath}" using Write.`,
    ].join('\n'),
    {
      label,
      schema: {
        type: 'object',
        properties: { passed: { type: 'boolean' }, output: { type: 'string' } },
        required: ['passed', 'output'],
      },
    }
  )
  return result || { passed: false, output: '(validate agent produced no result)' }
}

function isNewRegression(baseline, current) {
  // ponytail: boolean pass/fail comparison only, not per-test-target diffing — this
  // can't tell "different tests failing now" from "same failure as baseline". Upgrade
  // to structured test-target diffing if this repo's runner emits parseable output.
  if (baseline.captureFailed) return !current.passed
  return baseline.passed && !current.passed
}

async function implementSubtask(subtask, diffsById, consensusPlan) {
  const priorDiffs = (subtask.dependsOn || [])
    .map((depId) => diffsById[depId])
    .filter(Boolean)
    .join('\n\n')
  const result = await agent(
    [
      // --fresh, not --resume: subtasks in the same wave run concurrently via
      // parallel(), and --resume tries to continue the SAME last codex thread — two
      // concurrent --resume calls collide (one gets "task still busy" and gives up
      // with an empty diff, silently dropping that subtask). Each subtask gets its
      // own independent thread instead; full context is always passed explicitly
      // below, so there's nothing lost by not resuming a shared thread.
      '--fresh',
      `Subtask ${subtask.id}: ${subtask.description}`,
      `Owns files: ${(subtask.ownsFiles || []).join(', ') || '(none declared)'}`,
      priorDiffs
        ? `Actual diff from subtasks this depends on (not the plan doc):\n${priorDiffs}`
        : '',
      `Full consensus plan (context):\n${consensusPlan}`,
      'Implement this subtask directly in the working tree.',
      'After implementing, run `git diff -- <owned files>` via Bash to capture the actual diff.',
    ]
      .filter(Boolean)
      .join('\n\n'),
    {
      agentType: CODEX_AGENT_TYPE,
      label: `implement:${subtask.id}`,
      schema: {
        type: 'object',
        properties: {
          filesChanged: { type: 'array', items: { type: 'string' } },
          diff: { type: 'string' },
        },
        required: ['filesChanged', 'diff'],
      },
    }
  )
  return { id: subtask.id, filesChanged: (result && result.filesChanged) || [], diff: (result && result.diff) || '' }
}

async function reviewSubtask(subtask, diff) {
  const result = await agent(
    [
      '--fresh read-only, research/critique only, do not edit files.',
      `Review subtask ${subtask.id}: ${subtask.description}`,
      `Diff:\n${diff}`,
      'Use exactly these 3 fixed lenses, independently (this guards against parallel',
      'reviewers sharing the same blind spot from the earlier plan/consensus reasoning):',
      '1. Requirements/test-gap — does the diff satisfy the subtask description? What tests are missing?',
      '2. Integration/regression — does this break callers, shared contracts, or other subtasks?',
      '3. Security/concurrency — injection, auth, race conditions, unsafe concurrency.',
      'For EVERY finding, report exactly: location, failure path or repro steps, severity, needed tests.',
    ].join('\n\n'),
    {
      label: `review:${subtask.id}`,
      schema: {
        type: 'object',
        properties: {
          findings: {
            type: 'array',
            items: {
              type: 'object',
              properties: {
                location: { type: 'string' },
                failurePathOrRepro: { type: 'string' },
                severity: { type: 'string', enum: ['critical', 'major', 'minor'] },
                neededTests: { type: 'string' },
              },
              required: ['location', 'failurePathOrRepro', 'severity', 'neededTests'],
            },
          },
        },
        required: ['findings'],
      },
    }
  )
  return { id: subtask.id, findings: (result && result.findings) || [] }
}

function mergeOverlappingSubtasks(subtasks) {
  const merged = []
  const used = new Set()
  for (let i = 0; i < subtasks.length; i++) {
    if (used.has(i)) continue
    const group = [subtasks[i]]
    for (let j = i + 1; j < subtasks.length; j++) {
      if (used.has(j)) continue
      if (overlaps(subtasks[i], subtasks[j])) {
        group.push(subtasks[j])
        used.add(j)
      }
    }
    if (group.length === 1) {
      merged.push(group[0])
    } else {
      merged.push({
        id: group.map((t) => t.id).join('+'),
        description: group.map((t) => `[${t.id}] ${t.description}`).join(' THEN '),
        dependsOn: [...new Set(group.flatMap((t) => t.dependsOn || []))].filter(
          (d) => !group.some((t) => t.id === d)
        ),
        ownsFiles: [...new Set(group.flatMap((t) => t.ownsFiles || []))],
        touchesContracts: [...new Set(group.flatMap((t) => t.touchesContracts || []))],
      })
    }
  }
  return merged
}

function overlaps(a, b) {
  const filesOverlap = (a.ownsFiles || []).some((f) => (b.ownsFiles || []).includes(f))
  const contractsOverlap = (a.touchesContracts || []).some((c) =>
    (b.touchesContracts || []).includes(c)
  )
  return filesOverlap || contractsOverlap
}

function topoSortIntoWaves(pending, allSubtasks) {
  const byId = Object.fromEntries(allSubtasks.map((t) => [t.id, t]))
  const remaining = new Set(pending.map((t) => t.id))
  const done = new Set(allSubtasks.map((t) => t.id).filter((id) => !remaining.has(id)))
  const waves = []

  let guard = 0
  while (remaining.size > 0 && guard++ < 100) {
    const ready = [...remaining].filter((id) =>
      (byId[id].dependsOn || []).every((d) => done.has(d) || !remaining.has(d))
    )
    if (ready.length === 0) {
      // Dependency cycle: demote all remaining to a single sequential wave rather
      // than failing the run.
      waves.push([...remaining].map((id) => byId[id]))
      break
    }
    waves.push(ready.map((id) => byId[id]))
    ready.forEach((id) => {
      remaining.delete(id)
      done.add(id)
    })
  }
  return waves
}

function chunkBy(arr, size) {
  const out = []
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size))
  return out
}

function renderReviewReport(reviewResults) {
  return reviewResults
    .map(
      (r) =>
        `## Subtask ${r.id}\n\n` +
        (r.findings.length
          ? r.findings
              .map(
                (f) =>
                  `- **${f.severity}** ${f.location}: ${f.failurePathOrRepro}\n  needed tests: ${f.neededTests}`
              )
              .join('\n')
          : '(no findings)')
    )
    .join('\n\n')
}

function renderFinalReport({ status, round, dir, baseline, consensusPlan, subtasks }) {
  return [
    '# archon-adversarial-dev report',
    '',
    `Status: ${status}`,
    `Rounds run: ${round}`,
    `Artifacts: ${dir}/`,
    baseline.captureFailed
      ? 'Baseline capture: FAILED (all validate failures treated as new regressions)'
      : `Baseline: captured (${baseline.passed ? 'passed' : 'failed'})`,
    '',
    '## Consensus plan',
    consensusPlan,
    '',
    '## Subtasks',
    JSON.stringify(subtasks, null, 2),
  ].join('\n')
}
