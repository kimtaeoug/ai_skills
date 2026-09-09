# Evaluation contract

Persist cases as JSON or JSONL with these fields:

- `id`, `question`, `category`, `answerable`, `expected_claims`.
- `evidence_groups`: mandatory groups; each has an `id` and `alternatives` containing
  repository-relative `path`, inclusive `start`/`end`, SHA-256 of the entire file,
  and the fact this range supports. Any one alternative satisfies its group.
- `unanswerable_reason` and searched scope for negative cases. Empty search alone
  does not establish that an answer is absent. Answerable cases need at least one group.
- Benchmark version, source revision plus working-tree hashes, scope/exclusions,
  annotation method, k and predeclared acceptance criteria belong in run metadata.

Gold must be independently source-verified, not copied from generated summaries.
An unchecked or mismatching hash is a gold-validity gap, not a retrieval miss.
Keep those cases and report invalid counts; do not publish a validated aggregate
over the full suite until repaired. Provisional arithmetic may be shown as such.

## Retrieval metrics

Let A be the number of valid answerable cases, G(q) their required groups, and H(q)
the unique groups supported by the first k returned records' evidence. Preserve raw
rank positions when duplicates occur. An error on an attempted case gives H(q)=empty
and reciprocal rank zero, and is ALSO reported as an execution error. A skipped
backend is unmeasured, not zero and not a successful fallback.

| Metric | Definition |
| --- | --- |
| Any-hit@k | Number of cases with at least one required group found / A |
| All-required@k | Number of cases with every required group found / A |
| Macro evidence recall@k | Mean over A of found required groups / required groups |
| Micro evidence recall@k | Total found required groups / total required groups |
| MRR@k | Mean over A of 1 / first relevant rank; zero for no hit |

Report macro and micro separately; MRR and any-hit do not establish multi-file
completeness. Unanswerable cases are excluded from retrieval-recall denominators.
Denominator zero yields `null`/unmeasured, never 100%. Include counts with percentages.

## Answer and ontology judgments

For each answer save its case ID, exact text, abstention flag, atomic claims and
citations. For each claim record `supported`, `contradicted`, `unsupported` or
`unresolved`, evidence and judging rationale. Support requires all cited prerequisites
and correct values; schema validity and citation existence are insufficient.

- Claim support = supported / all judged claims, with unresolved claims retained in
  the denominator. Also report each other label count and missing-answer count.
- Required-answer coverage = correctly expressed expected claims / expected claims
  across valid answerable cases, including missing answers as zero coverage.
  Expected claims must be explicitly annotated; evidence-group counts are not a
  substitute. Missing expected-claim annotations make this metric unmeasured.
- Correct abstention = appropriate abstentions / valid unanswerable cases.
- A generation stage never attempted is unmeasured. For attempted generation,
  errors or missing answers get no abstention credit and remain in denominators;
  only an explicit appropriate abstention counts. Report attempted/skipped counts.
- Over-abstention = abstentions / valid answerable cases. Mere irrelevant retrieval
  for an unanswerable question is not itself an incorrect answer.
- Ontology semantic accuracy = fully source-supported sampled records / all sampled
  records; unresolved judgments stay in the denominator. Report sampling method,
  sample size, type/relation/value errors and schema validity separately.

Automated LLM judging is provisional until independently source-reviewed. State judge
identity/method and unresolved disagreements. Tiny or curated suites measure only
their declared scope. Do not average these dimensions into a reliability percentage.

## Worked arithmetic fixture

Three answerable cases require {A,B}, {C}, {D}. Retrieval gives A twice at ranks 1/2,
C at rank 2, and a backend timeout respectively. With valid gold and k=5:
any-hit=2/3, all-required=1/3, macro recall=(1/2+1+0)/3=1/2,
micro recall=2/4, MRR=(1+1/2+0)/3=1/2, execution errors=1/3.
Two supported and one contradicted claim give support=2/3, not full correctness.
One negative question answered with appropriate abstention gives 1/1 abstention;
ontology/freshness checks not run remain unmeasured. Unchecked gold makes the
retrieval numbers provisional. None of this establishes production readiness.
