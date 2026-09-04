// archon-adversarial-dev — Workflow DAG body.
//
// Executed via the session's Workflow tool:
//   Workflow({ scriptPath: ".claude/skills/archon-adversarial-dev/workflow.mjs",
//              args: { task, maxRounds } })
//
// Design doc (source of truth for behavior changes):
//   docs/superpowers/specs/2026-09-04-archon-adversarial-dev-design.md
//
// This script targets the Workflow tool's documented orchestration primitives:
//   agent(prompt, opts)      — spawn one subagent, opts.agentType selects the agent
//   parallel(fns)            — run an array of thunks concurrently, results array
//                               (failed entries resolve to null, per Workflow contract)
//   pipeline(stages)         — run stages in sequence, each stage's output feeds the next
//
// FALLBACK: if `agent`/`parallel`/`pipeline` are not available as globals when this
// script is invoked (Workflow tool absent, or agentType: "codex:codex-rescue" fails
// to resolve CLAUDE_PLUGIN_ROOT), SKILL.md instructs the orchestrator to abandon
// script execution and instead follow this file's phase structure by hand, replacing
// agent()/parallel() calls with direct `Agent` tool calls (one message, multiple tool
// uses, same fan-out cap and depth=1 rule). This spike/fallback decision must happen
// before any Codex call — see PHASE 0.
//
// Roles are fixed: Codex only implements (codex:codex-rescue), Claude only reviews.
// Codex critiques only during planning. No nested subagent delegation (depth=1).
// Fan-out cap: max 4 concurrent per wave, for both implement and review.

const CODEX_AGENT_TYPE = "codex:codex-rescue";
const MAX_CONCURRENCY = 4; // fan-out cap per wave (implement + review), hard limit
const MAX_CRITIQUE_ROUNDS = 2; // plan<->critique ping-pong cap before AskUserQuestion
const DEFAULT_MAX_ROUNDS = 5; // implement->review round cap

export default async function run({ task, maxRounds }, { agent, parallel }) {
  maxRounds = maxRounds || DEFAULT_MAX_ROUNDS;
  if (!task) throw new Error("archon-adversarial-dev: task description is required");

  const slug = slugify(task);
  const dir = `nimbalyst-local/plans/adversarial-dev/${slug}`;
  // Directory is always cleared at start — no resume, no stale artifacts (spec: 범위 밖).
  await bash(`rm -rf "${dir}" && mkdir -p "${dir}"`);

  // ---------------------------------------------------------------------
  // PHASE 0: preflight — codex ping (spike) + baseline capture
  // ---------------------------------------------------------------------
  const pingResult = await agent(
    [
      "--fresh read-only, research/critique only, do not edit files.",
      'Reply with exactly one line: "codex ready".',
    ].join("\n"),
    { agentType: CODEX_AGENT_TYPE }
  );
  if (!pingResult || !String(pingResult).toLowerCase().includes("codex ready")) {
    return {
      status: "aborted",
      reason:
        "preflight codex ping failed — Codex not reachable via codex:codex-rescue. " +
        "Advise the user to run /codex:setup, then stop. Do not proceed to plan.",
    };
  }

  // Baseline: existing build/test state, captured once, before anything else.
  // Failure to capture does NOT abort the skill — conservative fallback: treat
  // all validate failures as new regressions if baseline capture itself failed.
  let baseline;
  try {
    baseline = await bash(detectAndRunValidateCommand(), { timeoutMs: 10 * 60 * 1000 });
  } catch (e) {
    baseline = { failed: true, error: String(e) };
  }
  await writeFile(
    `${dir}/baseline.md`,
    baseline.failed
      ? `# Baseline\n\nCapture FAILED: ${baseline.error}\n\n` +
        `Fallback: treat all subsequent validate failures as NEW regressions ` +
        `(cannot distinguish from pre-existing failures).`
      : `# Baseline\n\n\`\`\`\n${baseline.output}\n\`\`\`\n`
  );

  // ---------------------------------------------------------------------
  // PHASE 1: plan (Claude) <-> critique (Codex, read-only) <-> consensus
  // ---------------------------------------------------------------------
  let plan = await agent(
    `Draft a concise implementation plan for: ${task}\n` +
      `Include: goal, key files/paths, design choices, risks. ` +
      `Use Glob/Grep/Read to ground the draft in the actual repo.`,
    { agentType: "claude" }
  );

  let critique;
  for (let round = 1; round <= MAX_CRITIQUE_ROUNDS; round++) {
    critique = await agent(
      [
        "--fresh read-only, research/critique only, do not edit files.",
        `Here is a proposed implementation plan for: ${task}`,
        plan,
        "Critique it: gaps, better alternatives, missed risks, dissenting opinion.",
      ].join("\n\n"),
      { agentType: CODEX_AGENT_TYPE }
    );
    await writeFile(
      `${dir}/${round === 1 ? "critique.md" : `critique-${round}.md`}`,
      critique
    );

    if (round === MAX_CRITIQUE_ROUNDS || !hasBigDisagreement(plan, critique)) break;

    // Revise the draft and re-critique (max 2 rounds total).
    plan = await agent(
      `Revise this plan given Codex's critique.\n\nOriginal plan:\n${plan}\n\n` +
        `Critique:\n${critique}`,
      { agentType: "claude" }
    );
  }
  await writeFile(`${dir}/plan.md`, plan);

  if (hasBigDisagreement(plan, critique)) {
    return {
      status: "needs-user-decision",
      reason:
        "Plan/critique disagreement persisted after 2 rounds. Orchestrator must call " +
        "AskUserQuestion with the core disputed decision before proceeding to consensus.",
      plan,
      critique,
    };
  }

  // consensus: merge into final plan + structured subtask list.
  const consensusRaw = await agent(
    "Merge the plan and critique into a final consensus plan, and split the work " +
      "into subtasks as JSON. Schema:\n" +
      `{"subtasks":[{"id":"t1","description":"...","dependsOn":[],` +
      `"ownsFiles":["src/foo.ts"],"touchesContracts":[]}]}\n` +
      "A single small task that doesn't need splitting is still a subtasks array " +
      "of length 1 — do not special-case it.\n\n" +
      `Plan:\n${plan}\n\nCritique:\n${critique}`,
    { agentType: "claude" }
  );
  const { consensusPlan, subtasks: rawSubtasks } = parseConsensus(consensusRaw);
  await writeFile(`${dir}/consensus-plan.md`, consensusPlan);

  // Ownership/contract overlap check: merge overlapping subtasks into one
  // (dependsOn alone can't catch shared-file/shared-contract coupling).
  const subtasks = mergeOverlappingSubtasks(rawSubtasks);
  await writeFile(`${dir}/subtasks.json`, JSON.stringify({ subtasks }, null, 2));

  // ---------------------------------------------------------------------
  // PHASE 2..N: implement (wave-parallel) -> validate -> review -> decision
  // Loop until pass, or a triage/iterate round exhausts maxRounds.
  // ---------------------------------------------------------------------
  let pending = subtasks; // subtasks still needing (re-)implementation this round
  let diffsById = {}; // subtaskId -> diff/changed-files text, latest known state
  let round = 0;

  while (round < maxRounds) {
    round++;
    const waves = topoSortIntoWaves(pending, subtasks);
    const roundArtifacts = { waves: [] };

    for (let w = 0; w < waves.length; w++) {
      const wave = waves[w];
      // Fan-out cap: parallel() itself should queue past MAX_CONCURRENCY, but we
      // also chunk explicitly so a single wave() call never requests more than 4.
      const results = [];
      for (const chunk of chunkBy(wave, MAX_CONCURRENCY)) {
        const chunkResults = await parallel(
          chunk.map((st) => async () => {
            const priorDiffs = (st.dependsOn || [])
              .map((depId) => diffsById[depId])
              .filter(Boolean)
              .join("\n\n");
            const out = await agent(
              [
                "--resume",
                `Subtask ${st.id}: ${st.description}`,
                `Owns files: ${(st.ownsFiles || []).join(", ") || "(none declared)"}`,
                priorDiffs
                  ? `Actual diff from subtasks this depends on (not the plan doc):\n${priorDiffs}`
                  : "",
                `Full consensus plan (context):\n${consensusPlan}`,
                "Implement this subtask directly in the working tree. Report the " +
                  "full list of changed/created file paths and the build/typecheck/" +
                  "test commands to run for verification.",
              ]
                .filter(Boolean)
                .join("\n\n"),
              { agentType: CODEX_AGENT_TYPE }
              // depth=1: do not let this agent spawn further subagents — enforced by
              // instruction text above and by not exposing Agent/Workflow to it.
            );
            return { id: st.id, output: out };
          })
        );
        results.push(...chunkResults);
      }

      for (const r of results) {
        if (r && r.output) {
          diffsById[r.id] = r.output; // null entries (failures) are left out of diffsById
        }
      }
      roundArtifacts.waves.push({ wave: w + 1, results });

      // validate after EVERY wave, not just at the end.
      const waveValidation = await runValidateAgainstBaseline(baseline);
      await writeFile(
        `${dir}/validation-wave-${round}-${w + 1}.md`,
        waveValidation.report
      );
    }

    // Final validate for this round, compared against baseline (new regressions only).
    const roundValidation = await runValidateAgainstBaseline(baseline);
    await writeFile(`${dir}/validation-round-${round}.md`, roundValidation.report);

    // ---------------------------------------------------------------------
    // review: parallel, one reviewer per completed subtask, 3 fixed lenses,
    // fixed finding schema.
    // ---------------------------------------------------------------------
    const reviewTargets = subtasks.filter((st) => diffsById[st.id]);
    const reviewResults = [];
    for (const chunk of chunkBy(reviewTargets, MAX_CONCURRENCY)) {
      const chunkResults = await parallel(
        chunk.map((st) => async () => {
          const out = await agent(reviewPrompt(st, diffsById[st.id]), {
            agentType: "claude",
          });
          return { id: st.id, findings: parseFindings(out) };
        })
      );
      reviewResults.push(...chunkResults);
    }
    await writeFile(
      `${dir}/review-round-${round}.md`,
      renderReviewReport(reviewResults)
    );

    // ---------------------------------------------------------------------
    // decision
    // ---------------------------------------------------------------------
    const newRegressions = roundValidation.newRegressions; // [] if none / baseline-failed-so-all-new
    const criticalFindings = reviewResults.flatMap((r) =>
      r.findings.filter((f) => f.severity === "critical")
    );

    if (newRegressions.length === 0 && criticalFindings.length === 0) {
      const report = renderFinalReport({
        status: "pass",
        round,
        dir,
        baseline,
        consensusPlan,
        subtasks,
      });
      await writeFile(`${dir}/report.md`, report);
      return { status: "pass", round, dir, report };
    }

    // iterate: isolate to specific subtasks where possible; unisolable
    // wave-aggregate failures go through triage instead of blind re-run.
    const { isolated, unisolable } = isolateFailures(
      newRegressions,
      criticalFindings,
      subtasks
    );

    let triageSubtasks = [];
    if (unisolable.length > 0) {
      const triageRaw = await agent(
        "The following validate/review failures could not be attributed to a single " +
          "subtask (likely an integration mismatch between subtasks). Propose new " +
          "subtask(s) (same JSON schema as before) to fix this — do not just ask to " +
          "re-run the original subtasks blindly.\n\n" +
          `Unisolable failures:\n${JSON.stringify(unisolable, null, 2)}\n\n` +
          `Consensus plan:\n${consensusPlan}`,
        { agentType: "claude" }
      );
      triageSubtasks = mergeOverlappingSubtasks(
        parseConsensus(triageRaw).subtasks || []
      );
      subtasks.push(...triageSubtasks);
    }

    pending = [
      ...subtasks.filter((st) => isolated.includes(st.id)),
      ...triageSubtasks,
    ];

    if (pending.length === 0) {
      // Shouldn't happen if newRegressions/criticalFindings is non-empty, but guard
      // against an infinite loop with nothing to retry.
      break;
    }
  }

  // maxRounds exceeded (or nothing left to retry) — stop and report.
  const report = renderFinalReport({
    status: round >= maxRounds ? "maxRounds-exceeded" : "stalled",
    round,
    dir,
    baseline,
    consensusPlan,
    subtasks,
  });
  await writeFile(`${dir}/report.md`, report);
  return { status: "iterate-stopped", round, dir, report };
}

// ---------------------------------------------------------------------------
// Helpers. These are intentionally small — the orchestrating agent (Claude, in
// either the Workflow-script path or the hand-run fallback path from SKILL.md)
// is expected to perform the actual reasoning steps (plan drafting, disagreement
// judgment, failure isolation) rather than this file encoding a full parser.
// ---------------------------------------------------------------------------

function slugify(task) {
  return String(task)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
}

function detectAndRunValidateCommand() {
  // Reuse whatever the repo's own build/test scripts are (package.json scripts,
  // Makefile targets, etc.) — same "don't reinvent, detect the real command"
  // policy as test-agent-team. The orchestrator fills this in per-repo at
  // preflight time; this placeholder documents the contract.
  return "true"; // orchestrator: replace with the detected real build/test command
}

async function runValidateAgainstBaseline(baseline) {
  let result;
  try {
    result = await bash(detectAndRunValidateCommand(), { timeoutMs: 10 * 60 * 1000 });
  } catch (e) {
    result = { failed: true, error: String(e) };
  }
  const newRegressions = diffAgainstBaseline(baseline, result);
  return {
    report:
      `# Validate\n\n\`\`\`\n${result.output || result.error}\n\`\`\`\n\n` +
      `New regressions vs baseline: ${newRegressions.length}\n`,
    newRegressions,
  };
}

function diffAgainstBaseline(baseline, result) {
  // If baseline capture itself failed, conservatively treat all current
  // failures as new (spec error-handling rule 11).
  if (baseline.failed) {
    return result.failed ? [{ reason: "validate-failed", detail: result.error }] : [];
  }
  if (!result.failed) return [];
  // Real implementation: structured diff of failing test/build targets between
  // baseline.output and result.output. Left for the orchestrator to fill in
  // against the repo's actual test runner output format.
  return [{ reason: "validate-failed", detail: result.error || result.output }];
}

function hasBigDisagreement(plan, critique) {
  // Orchestrator judgment call, not string matching — the agent reading this
  // script performs this check itself when running the plan/critique loop.
  return false;
}

function parseConsensus(raw) {
  const match = String(raw).match(/\{[\s\S]*"subtasks"[\s\S]*\}/);
  let subtasks = [];
  if (match) {
    try {
      subtasks = JSON.parse(match[0]).subtasks || [];
    } catch {
      // Cycle/parse-failure guard (error-handling rule 7): degrade to a single
      // sequential subtask rather than failing the whole run.
      subtasks = [
        {
          id: "t1",
          description: String(raw).slice(0, 2000),
          dependsOn: [],
          ownsFiles: [],
          touchesContracts: [],
        },
      ];
    }
  }
  return { consensusPlan: raw, subtasks };
}

function mergeOverlappingSubtasks(subtasks) {
  // ownsFiles or touchesContracts overlap => merge into one sequential subtask.
  // Safety net: even if this misses an overlap, per-wave validate catches it
  // (error-handling rule 10) — this is an optimization, not the sole guard.
  const merged = [];
  const used = new Set();
  for (let i = 0; i < subtasks.length; i++) {
    if (used.has(i)) continue;
    let group = [subtasks[i]];
    for (let j = i + 1; j < subtasks.length; j++) {
      if (used.has(j)) continue;
      if (overlaps(subtasks[i], subtasks[j])) {
        group.push(subtasks[j]);
        used.add(j);
      }
    }
    if (group.length === 1) {
      merged.push(group[0]);
    } else {
      merged.push({
        id: group.map((t) => t.id).join("+"),
        description: group.map((t) => `[${t.id}] ${t.description}`).join(" THEN "),
        dependsOn: [...new Set(group.flatMap((t) => t.dependsOn || []))].filter(
          (d) => !group.some((t) => t.id === d)
        ),
        ownsFiles: [...new Set(group.flatMap((t) => t.ownsFiles || []))],
        touchesContracts: [...new Set(group.flatMap((t) => t.touchesContracts || []))],
      });
    }
  }
  return merged;
}

function overlaps(a, b) {
  const filesOverlap = (a.ownsFiles || []).some((f) => (b.ownsFiles || []).includes(f));
  const contractsOverlap = (a.touchesContracts || []).some((c) =>
    (b.touchesContracts || []).includes(c)
  );
  return filesOverlap || contractsOverlap;
}

function topoSortIntoWaves(pending, allSubtasks) {
  const byId = Object.fromEntries(allSubtasks.map((t) => [t.id, t]));
  const remaining = new Set(pending.map((t) => t.id));
  const waves = [];
  const done = new Set(allSubtasks.map((t) => t.id).filter((id) => !remaining.has(id)));

  let guard = 0;
  while (remaining.size > 0 && guard++ < 100) {
    const ready = [...remaining].filter((id) =>
      (byId[id].dependsOn || []).every((d) => done.has(d) || !remaining.has(d))
    );
    if (ready.length === 0) {
      // Dependency cycle (error-handling rule 7): demote all remaining to a
      // single sequential wave rather than failing the run.
      waves.push([...remaining].map((id) => byId[id]));
      break;
    }
    waves.push(ready.map((id) => byId[id]));
    ready.forEach((id) => {
      remaining.delete(id);
      done.add(id);
    });
  }
  return waves;
}

function chunkBy(arr, size) {
  const out = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}

function reviewPrompt(subtask, diff) {
  return [
    "--fresh read-only, research/critique only, do not edit files.",
    `Review subtask ${subtask.id}: ${subtask.description}`,
    `Diff:\n${diff}`,
    "Use exactly these 3 fixed lenses, independently:",
    "1. Requirements/test-gap — does the diff satisfy the subtask description? What tests are missing?",
    "2. Integration/regression — does this break callers, shared contracts, or other subtasks?",
    "3. Security/concurrency — injection, auth, race conditions, unsafe concurrency.",
    "For EVERY finding, report exactly these fields: location (file:line), " +
      "failure path or repro steps, severity (critical/major/minor), needed tests.",
  ].join("\n\n");
}

function parseFindings(raw) {
  // Orchestrator-side structured extraction from the review agent's prose/JSON
  // output into { location, repro, severity, neededTests } objects. Left to the
  // agent executing this step to parse against the fixed schema demanded above.
  return [];
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
                  `- **${f.severity}** ${f.location}: ${f.failurePath || f.repro}\n  needed tests: ${f.neededTests}`
              )
              .join("\n")
          : "(no findings)")
    )
    .join("\n\n");
}

function isolateFailures(newRegressions, criticalFindings, subtasks) {
  // criticalFindings already carry a subtask attribution from the review loop.
  // newRegressions from wave-aggregate validate often can't be attributed to one
  // subtask — those are unisolable and go to triage (spec: decision routing).
  const isolated = [...new Set(criticalFindings.map((f) => f.subtaskId).filter(Boolean))];
  const unisolable = [
    ...newRegressions,
    ...criticalFindings.filter((f) => !f.subtaskId),
  ];
  return { isolated, unisolable };
}

function renderFinalReport({ status, round, dir, baseline, consensusPlan, subtasks }) {
  return [
    `# archon-adversarial-dev report`,
    ``,
    `Status: ${status}`,
    `Rounds run: ${round}`,
    `Artifacts: ${dir}/`,
    baseline.failed ? `Baseline capture: FAILED (${baseline.error})` : `Baseline: captured`,
    ``,
    `## Consensus plan`,
    consensusPlan,
    ``,
    `## Subtasks`,
    JSON.stringify(subtasks, null, 2),
  ].join("\n");
}

// bash()/writeFile() are provided by the Workflow tool's script execution
// environment (fs + shell access scoped to the run). If the Workflow tool is
// not present, this whole file is not executed — see SKILL.md's fallback path.
