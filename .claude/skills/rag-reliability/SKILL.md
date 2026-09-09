---
name: rag-reliability
description: Use when measuring repository RAG reliability, comparing retrieval modes, evaluating grounded answers or ontology quality, or checking regressions after indexing and source changes. Supports Claude Code and Codex.
---

# RAG reliability

Produce an auditable evaluation, not a single confidence percentage. Separate
retrieval, answer grounding, ontology semantics and freshness. Integration tests
prove operation; similarity scores and model self-confidence are not accuracy.

## Freeze the evaluation

Read target repository instructions and the installed `repo-knowledge` skill if
its store is used. Resolve its helper from that skill's actual directory.
Read [evaluation contract](references/evaluation.md) before preparing cases or scoring.
Reuse an existing benchmark; otherwise start with approximately 30 representative
questions, scaling down explicitly for a smoke test. Include direct code lookup,
Korean questions about English code, multi-file reasoning, unanswerable questions,
and known extraction errors (missing literal values and incorrect entity types).

Build expected answers from direct source and tests BEFORE inspecting RAG answers.
Record source hashes and mandatory evidence groups with acceptable alternatives.
Keep benchmark answers out of indexed inputs and the answer generator's context.
Freeze cases, k, scope, thresholds and runtime/model settings before comparing modes.
Preserve a held-out set when tuning; changes to cases create a new benchmark version.
Verify gold hashes first: changed or unchecked gold makes affected scores provisional,
not validated. Re-annotate from source without silently dropping difficult cases.
After repository sync, check gold paths and hashes again, including deleted/renamed
paths. Do not automatically replace an old gold hash or expected answer. Preserve
the old benchmark, independently re-annotate affected cases, and create a new version;
scores across changed benchmarks are not a controlled before/after comparison.

## Run and judge

For repo-knowledge, capture `status`, then run each frozen question separately:

```sh
python3 <knowledge-helper> --repo <target> query '<question>' --mode lexical --limit 5
```

Repeat with explicit `vector` and `hybrid` on the same store. Save raw JSON, errors,
elapsed time and actual retrieval mode. Do not substitute `auto` fallback for a
failed vector run. Do not rebuild or refresh the store during a comparison.
Use existing dependencies; unavailable backends remain visible as unmeasured or failed.

Score unique evidence groups using the final returned order, including graph neighbors.
Require cited ranges to support the gold fact; file-name or record-ID matches alone
are insufficient. Report any-hit AND all-required coverage, macro evidence recall,
MRR, error counts and denominators using the contract. Duplicate hits add no credit.

Generate answers from only the question and retrieved context, without gold answers.
Record generator model/settings and exact context. If the agent also explores source,
label that run assisted; do not compare it as retrieval-only. A separate judging pass
checks every atomic claim against cited source, not the generator's self-rating.
Record supported, contradicted, unsupported and unresolved claims, required-answer
coverage, unanswerable abstention and answerable over-abstention. Missing answers
cannot count as perfect grounding. Missing judging remains unmeasured.

Audit a declared sample of ontology records against source: entity types, relation
meaning, literal values, prerequisites, and observed/inferred labels. JSON Schema
validity alone earns no semantic credit. Freshness probes run only in a disposable
copy with its own DB namespace: modify/delete/rename sources, replace records, add
unindexed files and introduce code/doc contradictions. Check stale exclusion before
limit and report semantic gaps in unchanged documents. Never mutate the user's
working source or live index to manufacture test cases.

## Deliver

Write a run directory outside indexed inputs containing frozen cases, raw retrievals,
answers, judgments and a report with commands, revision/hashes, models, k, mode,
counts, per-category metrics, failed question IDs and unmeasured checks. Use small
local calculations to check arithmetic; preserve the calculation with the report.
Report repeated generation runs separately when assessing variance.

Use `pass` only for predeclared criteria with valid gold and completed required checks;
`fail` for observed criterion violations; otherwise `inconclusive`. A smoke test
does not establish repository-wide or production reliability. Stop after the scoped
evaluation and report specific failures; tuning/reindexing starts a separate run.
