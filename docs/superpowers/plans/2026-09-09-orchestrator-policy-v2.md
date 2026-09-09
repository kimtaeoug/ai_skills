# Orchestrator Policy v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. The user's workspace/autonomy instructions take precedence: preserve existing uncommitted work, no automatic commit/push or worktree relocation. Main integrates the tightly coupled runtime; bounded independent policy and verification slices may be delegated.

**Goal:** Enforce the approved graph contracts with tunable, versioned execution budgets and HIL wait exclusion.

**Architecture:** Keep v1 untouched. A separate v2 stdlib runtime uses one workspace SQLite transaction authority for workflows, reservations and circuit state, plus content-addressed artifacts outside graph state. Only trusted registered adapters execute; absent metering, identity or bounded execution capabilities fail closed.

**Tech Stack:** Python 3.10+, POSIX, SQLite, subprocess/process supervision; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-09-task-orchestrator-v2-hil-draft.md`

## Global Constraints

- Workflow/stage/tool defaults: 3600/900/120 seconds. Approval expiry: independent 600 seconds wall time.
- Retry defaults: 3 attempts including first, base 1, cap 30, elapsed 180 seconds. Breaker: 3 failures, 60 seconds cooldown, one half-open probe.
- Workflow caps: 10 loops, 20 additional attempts, 100000 tokens, 5000000 microusd.
- Verified human waiting is excluded only for the waiting stage; workflow stops its clock only with no other work. Tool clocks never pause.
- Unknown usage is not zero. Unknown approval identity is not approval. External effects require recorded intent; unknown outcomes never auto-repeat.
- Preserve v1 state and tests. Do not install global hooks or claim native-model enforcement without an actual adapter.

## Tasks and verification ledger

### Task 1: Tunable policy and clocks

Files: create `scripts/runtime_policy.py` beneath the canonical skill and `tests/test-runtime-policy.py`.
Interface: `DEFAULTS`; `merge_policy(current, patch) -> dict`; `new_clock(now) -> dict`; `tick(clock, now) -> None`; `set_hil(clock, now, waiting) -> None`; `remaining(clock, limit) -> float`; `retry_delay(policy, retry_index, random_value) -> float`.

- [x] Write/run failing tests for invalid config, parent/child limits, exact HIL exclusion, clock rollback, cumulative time and jitter boundaries.
- [x] Implement strict finite values, unknown-key rejection and non-resetting clocks.
- [x] Verify with `python3 tests/test-runtime-policy.py` (6 tests).

```python
c = new_clock(0)
set_hil(c, 600, True)
set_hil(c, 7800, False)
assert remaining(c, 3600) == 3000
```

### Task 2: Durable graph / execution gate

Files: create canonical `scripts/graph_runtime.py`, `tests/test-graph-runtime.py`.
Implemented interface: `Runtime(workspace, adapters=None, authority=None, now=None)`; `create(contract, policy=None)`; `show(id)`; `request_tuning(id, expected, patch, reason)` then `approve(id, expected, proof)`; `execute(id, node_id, inputs)`; `resume(id)`; `artifact(id, bytes, media_type)`. Shared stage schemas are in `scripts/runtime_contracts.py`.

- [x] Write/run failing tests for unapproved/unknown calls, missing/invalid inputs, evidence failures, receipt/resume and policy changes preserving usage.
- [x] Validate closed schema vocabulary, actors, explicit success/retry/fallback/loop edges and node evidence contracts. Persist state/breakers in a single transaction; artifacts by immutable hashes.
- [x] Run registered bounded adapter calls through `before_tool_call`: approval, arguments/risk, clocks, reservations, breaker probe, intent; settle actual metered usage and commit receipt only after evidence gate.
- [x] Implement verified HIL begin/end, authenticated one-use approvals, policy version changes, unknown-result recovery and budget-first termination.
- [x] Add CLI defaults/init/show/resume/report and importable stage schemas without a fake native adapter.
- [x] Verify runtime (36), schemas (4) and v1 (20) tests.

```python
r = Runtime(workspace)
s = r.create(contract)
assert r.execute(s['id'], 'NODE-01', {})['status'] == 'awaiting_data'
```

### Task 3: Documentation, independent verification and measurement

Files: canonical and Codex skill entrypoints, `references/runtime-v2.md`, `docs/skills/task-orchestrator.md`, new v2 report under `docs/reports/`.

- [x] Baseline skill application probe: identify unavailable usage/tuning/authentication capabilities before editing instructions.
- [x] Document defaults, API/CLI usage, per-workflow overrides, HIL tuning, recovery, supported adapter boundary and no global-hook installation.
- [x] Independent forward test on an isolated workspace plus spec/security review; seven review findings repaired, final scoped review approved.
- [x] Run v1/v2 regressions, race/reservation and crash checks, bounded load including old 300-task benchmark; record quantitative pass/fail, not invented provider results.
- [x] Final verification: syntax, whitespace, skill metadata and links; report limits explicitly.

## Self-review / handoff

Policy task produces only pure policy/clock helpers; graph runtime owns transactional state and authenticates HIL before calling them. Documentation depends on actual tested public API. v1 performance is a comparison, not a claim that v2 repairs v1. Native provider/approval integration is capability-gated; no unverifiable adapter is enabled.

Approved execution lane: direct integration with independent policy and review slices under the supplied AGENTS.md. No fresh permission handoff is needed; latest user approved implementation and tunability.

## Result — 2026-09-09

Opt-in local v2 core implemented and verified: 70 regression tests, 5/5 v2 probe groups, 6/6 v1 reliability groups. The latest same-workflow test-failure rework loop and Tier3 approval-wait path are included. Existing v1 performance passes 16/17 conditions; 300-task start p95 is 2980.84 ms against 2000 ms. Native Claude/Codex metering and authenticated approval adapters are not installed; unsupported managed execution stays `awaiting_data`. See [quantitative report](../../reports/task-orchestrator-v2-2026-09-09/report.md) and [follow-up example](../../reports/average-example-2026-09-09/report.md).
