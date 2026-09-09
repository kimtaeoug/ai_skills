# Repo knowledge implementation plan

Goal: ship one portable Claude Code/Codex skill that builds repository ontology
and evidence records, retrieves relevant records during work, and maintains them.
The approved design is the preceding conversation: build, query, refresh, and
connect repository work instructions; current source wins over cached knowledge.

Architecture: canonical `.claude/skills/repo-knowledge/`, existing-style `.codex`
entrypoint, current Codex `.agents` discovery link. Python 3.9+ stdlib and Git only.
Agent performs semantic extraction and answer generation; a small CLI validates,
stores, retrieves and invalidates evidence. No embedding service or background hook.

- [x] Test first: temporary Git repo, evidence ingestion, relation expansion,
  dirty/deleted/new files, stale ingestion, schema/path rejection, idempotent binding.
- [x] Implement `scripts/knowledge.py` and portable `SKILL.md` plus schema reference.
- [x] Add both Codex entrypoints and Korean usage documentation.
- [x] Run CLI regression and skill validation; independent application/review pass.

Baseline independent agent (without skill): noticed dirty/deleted evidence but
invented `payments` scope for an unread `billing.py`, treated new/dirty status as
inherently untrustworthy even after review, and supplied no ontology relation
constraints. Skill must make scope evidence-based, freshness content-based, and
entity/relation validation explicit. Do not repeat approval gates already satisfied
by the user's request to implement. Preserve all pre-existing working-tree changes.

Verification: regression passed on Python 3.9.6 and 3.14.5; all three discovery
entrypoints passed skill-creator validation using the existing system Python's
PyYAML. Python 3.9 syntax, references, discovery links and whitespace checked.
Independent review found two test gaps (existing CLAUDE content and stale neighbor
only); both were added and passed. Independent forward execution used a standalone
copy outside this repository, built four records, detected an uncommitted change,
and produced five fresh records including a code/document conflict. Leader checked
the resulting hashes and both instruction bindings. The sample's optional pytest
run was unavailable; its direct behavior assertions passed.

Follow-up requested verification ran actual Claude Code and Codex CLI build and
ordinary-edit sessions. Both consulted before editing and refreshed evidence after
checks, ending with three fresh records. Fixed null rationale acceptance and stored
source symlink transitions, with failing-then-passing regressions and independent
rechecks. Details: `docs/reports/2026-09-09-repo-knowledge-verification.md`.
Instruction-based consultation is demonstrated in those sessions, not hook-enforced.
