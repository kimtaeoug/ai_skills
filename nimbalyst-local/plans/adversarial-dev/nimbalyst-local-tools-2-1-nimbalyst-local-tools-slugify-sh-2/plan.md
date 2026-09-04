# Plan: add `slugify.sh` and `word-count.sh` to `nimbalyst-local/tools/`

## Goal

Add two small, independent, dependency-free shell utility scripts under a new
`nimbalyst-local/tools/` directory:

1. `slugify.sh` — turns arbitrary text into a URL/filename-safe slug.
2. `word-count.sh` — counts words (and lines) in stdin or a file argument.

Each script is self-contained, has its own inline assert-based self-check
(`--self-check` mode, no external test framework, no shared helper file), and
does not depend on the other.

## Key files/paths

- `nimbalyst-local/tools/slugify.sh` (new)
- `nimbalyst-local/tools/word-count.sh` (new)
- `nimbalyst-local/plans/adversarial-dev/nimbalyst-local-tools-2-1-nimbalyst-local-tools-slugify-sh-2/plan.md` (this file)

No existing directory `nimbalyst-local/tools/` exists yet (confirmed via
`find`/`ls`) — it will be created fresh. No `tools/`-adjacent conventions
exist to inherit; closest precedent in the repo is
`nimbalyst-local/agent-context/agent-context.sh` and
`nimbalyst-local/agent-context/smoke-test.sh`, plus `tests/test-evolve.sh`.

## Grounding in repo conventions (verified by reading actual files)

- Shebang: `#!/usr/bin/env bash`, followed by `set -euo pipefail`
  (`agent-context.sh`, `smoke-test.sh`).
- Error helper pattern: `die() { printf '<tool>: %s\n' "$*" >&2; exit 1; }`
  (`agent-context.sh`).
- Self-check/test pattern used repo-wide (`tests/test-evolve.sh`,
  `smoke-test.sh`): `pass()`/`fail()` helpers printing `PASS: <name>` /
  `FAIL: <name>`, plain `test`/`[ ]`/`grep -F` assertions, `exit 1` on first
  failure, trap-based cleanup of any temp files.
- No Makefile, package.json, or CI config anywhere in the repo (confirmed —
  this is a plain-shell-script repo per the existing baseline.md in this same
  plan directory). So there's no test runner to register these with; the
  self-check is invoked directly (`./slugify.sh --self-check`), matching how
  `tests/test-evolve.sh` and `smoke-test.sh` are run directly with `bash`.
- No existing `tools/` directory or naming convention to match beyond the two
  requested filenames.

## Design choices

- **Single-file, no shared lib.** Each script embeds its own logic and its
  own self-check function. Ladder check: two 60-80 line standalone scripts
  don't justify a shared `lib.sh` — that's speculative reuse for two call
  sites. Skip; add a shared lib only if a third tool needs the same helper.
- **Self-check via `--self-check` flag, not a separate `test-*.sh` file.**
  Keeps the "independent" requirement literal (no cross-file dependency for
  tests either) and matches the "leave one runnable check behind" rule
  without inventing a test framework. Convention borrowed directly from the
  repo's existing `pass`/`fail`/`PASS:`/`FAIL:` idiom.
- **`slugify.sh`**:
  - stdlib-only: lowercase, strip diacritics best-effort via `tr`, replace
    non-alnum runs with `-`, trim leading/trailing `-`. Pure `tr`/`sed`, no
    `iconv`/`python`/`node` dependency (rung 3: stdlib/POSIX tools do it).
  - Input: argv joined, or stdin if no argv (so it works both as
    `./slugify.sh "Hello World!"` and `echo "Hello World!" | ./slugify.sh`).
  - Empty-result edge case (e.g. input is all punctuation) prints empty line,
    not an error — documented, not silently "fixed" with a fallback that
    hides bad input.
- **`word-count.sh`**:
  - Thin, explicit wrapper: reads stdin or a file path argument, reports word
    count and line count. Considered "just call `wc -w`" (rung 3/6) — but the
    task requires a standalone script with its own self-check and slightly
    more explicit output format (`words: N`, `lines: N`), so a ~15-line
    script around `wc` is the right size, not a raw one-liner alias.
  - No word-splitting reinvention — delegate the actual counting to `wc -w` /
    `wc -l` rather than hand-rolling a tokenizer. Rung 3 wins over rung 7.
- **Assert style**: `set -euo pipefail` inside the self-check block too, each
  assertion is `[ "$actual" = "$expected" ] && pass "..." || fail "..."`,
  matching `test-evolve.sh` exactly. Self-check exits non-zero on first
  failure (`fail()` calls `exit 1`), consistent with repo precedent.
- **Executable bit**: `chmod +x` both files, matching all existing `.sh`
  scripts in the repo (all are executable, checked via the shebang-first
  pattern already in use).

## Risks

- **Locale-dependent `tr`/lowercasing** in `slugify.sh` can behave
  differently under non-C locales (e.g. Turkish `İ`/`i` mapping). Mitigate by
  forcing `LC_ALL=C` inside the script for the transliteration step —
  ponytail-tagged as a known ceiling (`# ponytail: ASCII-only slug folding,
  add real Unicode transliteration (iconv/python) if non-Latin input is a
  real requirement`), not silently glossed over.
- **`--self-check` flag colliding with real usage** if a caller's real input
  happens to be the literal string `--self-check`. Low risk for a
  personal/local tool; acceptable trade-off, not worth an extra `--` escape
  mechanism for two solo scripts.
- **No CI wiring** — since the repo has no CI config, these self-checks won't
  run automatically anywhere. Out of scope per the task (only asks for the
  two scripts); if the user wants them wired into `tests/`, that's a
  follow-up, not silently added now.
- **macOS vs GNU `tr`/`wc` flag differences** (dev machine is macOS per env
  info) — stick to POSIX-portable flags only (`tr -cd`, `tr '[:upper:]'
  '[:lower:]'`, `wc -w`, `wc -l`), avoid GNU-only extensions, so scripts work
  on both BSD and GNU userlands without a portability shim.

## Out of scope (explicitly not doing)

- No shared helper/lib file — YAGNI for 2 scripts.
- No argument-parsing framework (getopts is unnecessary for 1-2 flags each;
  plain `case`/`if` on `$1` is enough).
- No packaging, no `nimbalyst-local/tools/README.md` — not requested.
- No wiring into an existing test runner — none exists in this repo.
