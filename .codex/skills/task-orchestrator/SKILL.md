---
name: task-orchestrator
description: Use when a task should be handled as a tracked graph with HIL criteria, optional research, development, testing, retries, UI verification, and a final report.
---

# task-orchestrator

This is the Codex entrypoint for the project skill. Its canonical instructions are
maintained at `.claude/skills/task-orchestrator/` so Claude and Codex stay aligned.
The canonical skill owns legacy task-local `state.json` tracking and the opt-in v2
SQLite execution authority, policy tuning and receipt gates. Read its mode routing
before using either runtime; this bridge does not install native enforcement hooks.

Before using this skill, resolve the project skill source root that contains this
bridge and read its sibling `.claude/skills/task-orchestrator/SKILL.md` in full.
Apply those instructions, adapting only unavailable tool names to equivalent Codex
capabilities. Do not resolve the state script from the target repository cwd. If
the canonical file is absent, report that compatibility source as missing.

Codex App can resume from saved task state when the user returns, but it does not
provide autonomous background scheduling by itself.
