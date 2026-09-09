# rag-reliability verification

This is a portable Claude Code/Codex evaluation workflow, using existing retrieval
commands rather than adding an evaluation service or dependency. It does not certify
any repository's RAG merely by being installed.

## Behavioral checks

Independent baseline without the skill: three answerable cases required {A,B}, {C},
{D}; outputs contained duplicate A, C at rank 2 and a timeout. One negative question
had appropriate abstention. Gold hashes were unchecked. The baseline reported
any-hit=2/3 and micro recall=1/2, but omitted all-required coverage and did not label
the arithmetic provisional despite the unchecked gold.

With the skill, an independent agent reported all-required=1/3, macro/micro recall
=1/2, MRR=1/2, errors=1/3 and provisional metrics with an inconclusive verdict.
The duplicate earned no extra credit. Unmeasured ontology/freshness remained visible.
An all-negative suite yielded null retrieval metrics rather than perfect scores.

The forward test exposed two ambiguities, corrected in the contract: evidence groups
cannot substitute for expected-answer claims; skipped generation differs from
attempted generation failure. The follow-up correctly returned:

- No expected-claim annotations: answer coverage unmeasured.
- Two attempted negative cases, one appropriate abstention and one timeout: 1/2.
- No generation attempted: abstention unmeasured, attempted=0, skipped=2.

## Installation checks and limits

Skill-creator format validation passed. Repository and global Claude/Codex aliases
resolve the canonical skill; global reference content matched the source byte-for-byte.
No new dependencies or scoring service were introduced.

These are synthetic behavioral application checks, not an end-to-end evaluation of
a real indexed repository, a statistical model reliability study, or live tests of
both Claude and Codex discovery sessions. Actual use produces a frozen benchmark,
raw retrievals, answers, source-backed judgments and separately scoped metrics.
