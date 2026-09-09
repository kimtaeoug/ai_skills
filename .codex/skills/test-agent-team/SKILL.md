---
name: test-agent-team
description: Run a repository's existing lint, typecheck, test, build, and optional UI checks in safe dependency-aware order, without adding tools.
---

# test-agent-team

This is the Codex entrypoint for the project skill. Its canonical instructions are
maintained at `.claude/skills/test-agent-team/` so Claude and Codex cannot drift.

Before using this skill, resolve the repository root with `git rev-parse --show-toplevel`
and read `<root>/.claude/skills/test-agent-team/SKILL.md` in full. Apply those
instructions. If the canonical file is absent, report that compatibility source as
missing.
