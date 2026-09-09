# task_state.py event API

Use this reference when applying graph events with
`scripts/task_state.py apply --task DIR --expected REV --event FILE`. All evidence
paths must point to non-empty files under `DIR/artifacts/`. Relative evidence paths
are resolved from `DIR`; absolute paths are allowed only inside `DIR/artifacts/`.

The tool requires a POSIX environment, Python 3.10+, and `--workspace` equal to the
Git worktree root. A workspace-wide lock protects task allocation and same-workspace
development starts. The code fingerprint hashes tracked and nonignored untracked
files, excluding `nimbalyst-local/tasks/`. Ignored runtime inputs are protocol-only
and are not hashed automatically. Git submodule entries are rejected; run a separate
supported worktree without submodule entries when that code must be tracked.

## Commands

```bash
python3 <skill-source>/scripts/task_state.py init --workspace /repo --title "Task title"
python3 <skill-source>/scripts/task_state.py show --task /repo/nimbalyst-local/tasks/TASK-0001
python3 <skill-source>/scripts/task_state.py snapshot --task /repo/nimbalyst-local/tasks/TASK-0001
python3 <skill-source>/scripts/task_state.py apply --task /repo/nimbalyst-local/tasks/TASK-0001 --expected 0 --event event.json
```

`show` returns `revision`; every `apply` must pass that exact revision. On conflict,
reread state and decide whether to replay, replan, or ask for HIL. Do not blindly
rerun pending work.

Use the canonical `task` path returned by `init`. On macOS, `/tmp/...` may resolve
to `/private/tmp/...`; using the unresolved alias can fail the task path check.
During smoke tests, put event JSON and command output under `DIR/artifacts/` when
possible. Extra nonignored files outside artifacts are source inputs and change the
code fingerprint.

## Events

### `criteria`

Allowed when no work item is running. Replaces criteria, increments
`criteria_version`, clears approvals/checks, and moves to `criteria_hil`.

```json
{
  "type": "criteria",
  "items": [{"id": "AC-01", "text": "Behavior users agreed to", "checks": ["TEST-01"]}],
  "ui_required": false,
  "ui_reason": "CLI-only change",
  "budget": {"max_attempts": 6, "max_no_progress": 2}
}
```

Use `ui_required: true` for known UI impact and `null` for unknown; unknown still
requires UI verification before completion. `max_attempts` is the total development
attempt budget. `max_no_progress` is the limit for repeated evaluations with the
same problem signature after additional attempts.

### `approve`

Records an actual user decision. The tool stores the reference/message but does not
authenticate the speaker.

```json
{
  "type": "approve",
  "gate": "criteria",
  "user": {"reference": "conversation:turn-12", "message": "이 기준으로 진행"}
}
```

`gate` is one of `criteria`, `plan`, `reassess`, `final`. `reassess` may include
`route: "planning" | "triage" | "testing"` and a replacement `budget`. Use this
gate to record an explicit HIL-approved scope adjustment, including changing a
required research item to `required: false` before reapproval. `final` requires
current passing verification and records the current code fingerprint.

### `research`

Records managed `research-team` output. A required research item with a non-answered
status, stale `criteria_version`, or changed evidence hash blocks planning until
the research is rerecorded against current criteria or HIL explicitly approves a
scope adjustment that changes that research item to `required: false` before
reapproval.

```json
{
  "type": "research",
  "id": "RES-01",
  "question": "Which upstream behavior constrains AC-01?",
  "status": "answered",
  "required": true,
  "evidence": "artifacts/RES-01/attempt-1/report.md"
}
```

`status` is `answered`, `no-claims-found`, `no-confirmed-claims`, or
`synthesis-failed`. The script records the current `criteria_version`; if criteria
change later, required research becomes stale and must be rerecorded or explicitly
de-scoped through HIL.

### `plan`

Allowed after criteria approval. Replaces the implementation DAG, increments
`plan_version`, clears checks/final approval, and moves to `plan_hil`.

```json
{
  "type": "plan",
  "items": [{
    "id": "DEV-01",
    "description": "Implement AC-01 and its regression check",
    "depends_on": [],
    "owns_files": ["src/app.py"],
    "resources": [],
    "criteria_ids": ["AC-01"],
    "risk": "low",
    "complexity": "small"
  }]
}
```

IDs may use `DEV-##` or `FIX-##`. `owns_files` must be workspace-relative POSIX
literal paths: no globs, no symlinks, no absolute paths, no `..`. Shared
files/resources serialize concurrent starts across the same workspace. A
human-facing `plan.md` is optional; the script plan lives in `state.json`.

### `start`

Starts one pending work item after plan approval. Creates
`artifacts/<DEV-##>/attempt-N/` and clears stale checks/final approval.

```json
{
  "type": "start",
  "id": "DEV-01",
  "model": {"tier": "cheap", "actual": "gpt-5.3-codex-spark", "reason": "Low-risk small task"}
}
```

`tier` is `cheap`, `standard`, or `high`. High-risk work cannot use `cheap`. The
script records the model route; it does not measure costs, enforce spending caps,
or call models.

### `finish`

Finishes the active attempt for a work item.

```json
{
  "type": "finish",
  "id": "DEV-01",
  "attempt": 1,
  "status": "done",
  "evidence": "artifacts/DEV-01/attempt-1/result.md",
  "usage": {"tokens": "unknown", "cost": "unknown"}
}
```

`status` is `done` or `failed`. `usage` is optional; unknown is valid when the
runtime does not expose cost/token/time. Treat usage as caller-reported evidence,
not a script-measured value.

### `check`

Records verification against the current fingerprint. Take the fingerprint
immediately before the actual test/procedure and pass that value; if code changes
during verification the event is rejected.

```json
{
  "type": "check",
  "id": "TEST-01",
  "kind": "code",
  "status": "pass",
  "command": "python3 tests/test-task-orchestrator.py",
  "fingerprint": "<snapshot value>",
  "evidence": "artifacts/TEST-01/attempt-1/output.txt"
}
```

`kind` is `code` or `ui`. `status` is `pass`, `fail`, `blocked`, `not-found`, or
`not-applicable`. UI checks must include browser interaction and visual evidence
when UI impact is true or unknown.

### `issue`

Opens or resolves an issue linked to a work item.

```json
{
  "type": "issue",
  "id": "ISSUE-01",
  "task_id": "DEV-01",
  "status": "open",
  "description": "Regression check failed for AC-01",
  "evidence": "artifacts/TEST-01/attempt-1/failure.txt"
}
```

Resolving an issue also needs `check_id` for a current passing check. Once an issue
exists, its original `task_id` and `description` are immutable; use
`issue-reassign` to set the effective repair owner.

### `issue-reassign`

Allowed in `planning` or `plan_hil`. Reassigns an open issue to a current or
upcoming `DEV-##`/`FIX-##` item and clears plan approval. The next replacement plan
must contain the effective owner for every open issue.

```json
{
  "type": "issue-reassign",
  "id": "ISSUE-01",
  "fixing_task_id": "FIX-01",
  "reason": "Repair will be handled by the new compatibility task"
}
```

### `rework`

Returns selected work items and their dependents to `pending`, clears checks/final
approval, and moves to `developing`.

```json
{
  "type": "rework",
  "ids": ["DEV-01"],
  "reason": "Final HIL requested a behavior change within current criteria"
}
```

### `evaluate`

Runs completion gates from current state. It moves to `final_hil`, `triage`,
`reassess_hil`, or stays in `reporting` when a valid final approval already matches
current criteria, plan, evidence, and fingerprint. It does not mutate code or tests.

```json
{"type": "evaluate"}
```

### `pause`

Moves to `reassess_hil` and writes `report.md` with current state.

```json
{"type": "pause", "reason": "Budget reached before passing UI verification"}
```

There is no `resume` event. To resume, run `show`, reconcile running/pending state
with actual artifacts, then record the next actual user decision with `approve`
at the `reassess` gate or apply another valid event.

### `complete`

Allowed only from `reporting` after final approval. Writes `report.md` before
claiming the terminal state.

```json
{
  "type": "complete",
  "summary": "Implemented, tested, and approved",
  "limitations": ["No ignored input files were part of the verification"]
}
```

The report includes links to evidence files, work/model routing, checks, issues,
human decisions, limitations, and `state.json`.

### `cancel`

Cancels a non-running task and writes `report.md`.

```json
{"type": "cancel", "reason": "User cancelled before implementation"}
```
