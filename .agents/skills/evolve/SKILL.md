---
name: evolve
description: Use when the user asks to record how a skill changed after real use, capture its evolution delta, or invokes /evolve.
---

# Evolve

Record a human-confirmed delta between a skill's baseline and its current state so later skill work can reuse the lesson. Do not modify the target skill automatically.

## Workflow

1. Identify the target skill directory. Ask only when it cannot be inferred.
2. Resolve the clone root containing `bin/evolve`, then run `<repo-root>/bin/evolve diff <skill-dir>`.
   - If no baseline exists, ask before running `snapshot`. A new snapshot means there is no delta to record yet.
   - If the diff is empty, report that and stop.
3. Read the full diff and collect, one question at a time:
   - project or domain context;
   - what failed or improved, including evidence;
   - reusable lessons, if any.
4. Write `<repo-root>/evolution/records/<skill-name>/<YYYY-MM-DD>-<slug>.md`:

```md
skill: <skill-name>
baseline: <git SHA or snapshot path>
final: <current git HEAD or "working tree">
context: <context>
delta: <structural, instruction, or validation changes>
evidence: <optional evidence>
candidate_lessons: <optional reusable lessons>
promotion: pending
```

5. Ask before updating the baseline with `<repo-root>/bin/evolve snapshot <skill-dir>`.
6. Add a non-duplicate lesson to `<repo-root>/evolution/lessons/<skill-name>.md` only with explicit approval.

## Boundaries

- Baselines in `evolution/.state/` are local to the current checkout.
- Never auto-edit `SKILL.md` or promote records into `evolution/patterns/`.
- Never update a baseline or lessons file without human approval.
