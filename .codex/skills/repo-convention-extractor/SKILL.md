---
name: repo-convention-extractor
description: Extract a repository's code, commit, dependency, and style conventions from evidence, with scoped confidence levels and explicit evidence gaps.
---

# repo-convention-extractor

This is the Codex entrypoint for the project skill. Its canonical instructions are
maintained at `.claude/skills/repo-convention-extractor/` so Claude and Codex cannot
drift.

Before using this skill, resolve the repository root with `git rev-parse --show-toplevel`
and read `<root>/.claude/skills/repo-convention-extractor/SKILL.md` in full. Apply those
instructions. If the canonical file is absent, report that compatibility source as
missing.
