# Repository RAG incremental sync verification

Date: 2026-09-09. Baseline: `d0ca42e`. Implementation: `747adda`, `4bf4d27`; workflow documentation: `8dccf69` plus integration corrections.

## Result and scope

Implemented reviewed file baselines, read-only `sync-plan`, atomic `sync-apply`, typed one-hop impact candidates, incremental PostgreSQL vectors, explicit `index --rebuild`, and backed-up guide upgrades. Claude and Codex use the same skill and CLI. No new dependencies, watcher, service, or automatic gold-answer rewriting.

JSON is authoritative. JSON application and PostgreSQL indexing are separate transactions. Failed indexing retains the accepted JSON and the previous database rows; query fingerprint/freshness filters exclude obsolete vectors. The source snapshot is rechecked immediately before JSON save, but the CLI writer lock cannot lock a user's editor.

## Environment and runnable evidence

- Python 3.14.7 and macOS Python 3.9.6: core sync and existing CLI regressions passed on both.
- Python 3.11.15 skill venv, PostgreSQL 18.4, pgvector 0.8.2, FastEmbed 0.8.0: actual database integration passed.
- Embedding model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, 384 dimensions. Installed FastEmbed emits its known mean-pooling notice; this work keeps the pinned signature/model.
- Ollama 0.33.3 with `qwen2.5-coder:7b`: existing extraction regression and actual agent calls executed.
- Both skill metadata validators, Python compilation, and `git diff --check` passed.

Commands are in plan section 8. Main runnable checks:

```sh
python3 tests/test-repo-knowledge-sync.py
python3 tests/test-repo-knowledge.py
/usr/bin/python3 tests/test-repo-knowledge-sync.py
/usr/bin/python3 tests/test-repo-knowledge.py
~/.claude/skills/repo-knowledge/.venv/bin/python tests/test-repo-knowledge-vectors.py
python3 tests/test-repo-knowledge-ollama.py
```

| Plan cases | Evidence and boundaries |
| --- | --- |
| S01–S03, S08, S10 | Stable read-only plans, legacy metadata, new sources, typed related IDs; malformed versions including boolean/float rejected. |
| S04–S06 | Deletion removes canonical/search records; rename is a unique-content hint only, ambiguous copies are not accepted as renames. |
| S07 | A reviewed file changed to a symlink is unavailable and `source` refuses it; existing safety regression covers ignored/secret source exclusion. Not every secret filename transition is individually enumerated. |
| S09 | One changed evidence file forces replacement of a multi-file record. Live comparison summaries also require both file hashes. |
| S11–S13 | Snapshot/JSON conflicts, final pre-save source change, invalid mixed batches, locks and zero-fact file reviews preserve atomicity/advance only reviewed baselines. |
| S14–S15 | Branch-context content changes detected by hash; partial selection preserves other baselines and exposes remaining paths. No remote multi-worktree synchronization service tested or added. |
| V01–V04 | Repeated index and deletion-only use an embedder-failure sentinel and still succeed; one changed record embeds once; signature changes and actual CLI `--rebuild` rebuild all fresh rows. |
| V05–V06 | Invalid dimensions and surplus embeddings fail; rows/signature roll back. A separately accepted new JSON stays byte-identical after incremental DB failure, and stale fingerprints remain excluded before retry. |
| V07 | An independent repository cannot read the tested namespace; fixtures clean only their own namespace. |
| G01–G03 | Actual agents preserve explicit code/doc disagreement, flag frozen gold as stale without editing it; guide regression preserves customization, backs it up on explicit upgrade, refuses existing backup overwrite. |

## Actual Claude and Codex exercise

Separate temporary Git repositories started with `auth.py` limit 5 and a policy documenting 5. After initial records/index/gold, the harness changed only code to 6. Each agent read the skill, inspected plans and related facts, tried actual Ollama extraction, reviewed records, applied a batch, indexed and queried hybrid retrieval. Source and frozen gold bytes were checked independently.

| Agent | Accepted state | Index evidence |
| --- | --- | --- |
| Codex | Code 6, documented policy 5, explicit contradiction record citing both files. Three fresh records. | First update: 2 embedded, 1 unchanged. Repeated index: 0 embedded, 3 unchanged. |
| Claude | Code 6 and policy 5; comparison record finally cites both files. Two fresh records. | Initial update: 1 embedded, 1 unchanged; evidence correction reindexed the changed record. Final repeated index: 0 embedded, 2 unchanged. |

Ollama drafts were not reliable enough for automatic acceptance: duplicate IDs were rejected, and Claude rejected a draft with poor symbol typing/missing literal value. The agent authored reviewed facts from source. These trials demonstrate workflow operation, not an accuracy percentage or a claim that inexpensive models can complete every repository unattended.

The initial Claude comparison summary cited only the code even though it discussed the policy. Manual review caught this. The skill/reference now explicitly require each comparison record to cite both sources; a probe assertion failed before correction and passed afterwards. Claude reread the updated instructions, corrected evidence and passed a final check. Both agents identified the old gold hash/answer as stale and left the file unchanged. This is evaluation-skill adherence, not a new automated reliability scoring CLI.

A pre-existing global Claude Stop hook requested unrelated evolution work during the correction run. The process was stopped. Its generated evolution record was removed; the three overwritten snapshot text files were restored from the captured pre-change diff, and one disposable bytecode cache was removed. The final Claude check used invocation-local `disableAllHooks=true`, completed successfully and performed no evolution action. Global hook settings were not changed.

Raw local artifacts are retained outside Git (temporary paths may later expire):

`/var/folders/n1/lqgp64vj5rb703jk5c2_qw900000gn/T/rag-sync-live-nz6eoofz/`

- `claude.jsonl`, `claude-recheck.jsonl`, `claude-final-check.jsonl`
- `codex.log`, `codex-final.txt`
- Each agent directory contains the source, canonical records, review and frozen gold.
- `tests/probe-repo-knowledge-sync-live.py` provides isolated setup, final-state assertions and namespace-only cleanup. It does not launch agents or establish semantic truth by itself.

## Deliberate limits

Inventory still scans/hashes the eligible repository; savings apply to review/extraction scope and unchanged embeddings. Relationship impact is one hop over recorded typed entities. Unrecorded dependencies and semantically wrong but structurally valid summaries still require agent review. `AGENTS.md` and `CLAUDE.md` in the live fixtures remained disclosed coverage gaps. Existing repository guides require explicit `init --update-guide`; deployment does not overwrite them automatically.

## Delivery verification

Independent integrated review approved after a legacy evidence-only rename omission was reproduced with a failing test and fixed. Both Python versions pass the added regression. Both skills were synchronized to the global Claude canonical directory while preserving `.venv`; every shipped file matches through Claude, Codex and agents aliases. Global CLI help and both live retrieval/no-op probes passed. Only the two synthetic database namespaces were then deleted; raw artifacts remain. No unrelated task-orchestrator files were staged.
