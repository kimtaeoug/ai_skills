## Verified claims

- **Bash/shebang strict mode — confirmed.** `nimbalyst-local/agent-context/agent-context.sh:1-2` and `nimbalyst-local/agent-context/smoke-test.sh:1-2` are exactly `#!/usr/bin/env bash` and `set -euo pipefail`.
- **`die()` shape — confirmed as a local precedent, not a universal convention.** `nimbalyst-local/agent-context/agent-context.sh:8` is `die() { printf 'agent-context: %s\n' "$*" >&2; exit 1; }`; the plan's `<tool>` is correctly a placeholder.
- **`pass`/`fail` idiom — partly confirmed, but the stated smoke-test evidence is false.** `tests/test-evolve.sh:26-27` defines `PASS:`/`FAIL:` and lines 37/50 use the proposed `&& pass ... || fail ...` form; `tests/test-hooks.sh:20-21` does too. `nimbalyst-local/agent-context/smoke-test.sh:21-84` has no `pass()`/`fail()` and prints only `agent-context smoke test passed` at line 84.
- **Plain assertions and fail-fast behavior — confirmed.** `tests/test-evolve.sh:37,57-69` uses `grep`, `[ ]`, and `fail` (which exits 1); `nimbalyst-local/agent-context/smoke-test.sh:21-24,25-30` uses direct command checks and `test` under strict mode.
- **No tracked Makefile/package/CI runner — confirmed by repository inventory, and documented in the existing baseline.** A `git ls-files` search for `Makefile`, `package.json`, `justfile`, `Taskfile`, GitHub workflow, and GitLab CI paths returned no matches; `baseline.md:10-19` records the same result and names the direct shell tests. This does not itself establish that inline self-checks are a repo convention.
- **No existing `nimbalyst-local/tools/` directory — false.** The actual directory `nimbalyst-local/tools/` exists (empty in the inspected tree); `plan.md:21-25` is stale. Its existence does not add a naming convention, but it must not be described as newly created.
- **All tracked `.sh` files executable — confirmed from Git metadata.** `git ls-files -s -- '*.sh'` reports mode `100755` for, e.g., `nimbalyst-local/agent-context/agent-context.sh` and `tests/test-evolve.sh`; executable bits are appropriate.
- **Path correction.** The requested `nimbalyst-local/smoke-test.sh` does not exist; the actual precedent is `nimbalyst-local/agent-context/smoke-test.sh:1-84`, as `plan.md:24-25` correctly says.

## Gaps

- Define input precedence precisely: is `slugify.sh a b` slugifying one joined string (`a b`), two inputs, or an error? State whether stdin is ignored, rejected, or combined when argv is present.
- Specify normal and error exit codes, missing/unreadable-file behavior for `word-count.sh`, and whether more than one file is rejected or supported.
- Define option parsing: recognize `--self-check` only as sole first argument, support `--` for literal input/filenames beginning with `-`, and decide whether `-h`/`--help` is needed. `agent-context.sh:306-321` has explicit argument-count validation and help.
- Nail down output records: one trailing newline always; whether an empty slug is one blank line; and whether `lines` means `wc -l` newline count or human-visible final unterminated line count.
- “Strip diacritics best-effort via `tr`” is inaccurate under `LC_ALL=C`: it cannot transliterate accented UTF-8; it will discard their bytes. Specify ASCII-only filtering instead.
- Specify test cases and expected semantics for whitespace-only input, newlines/CRLF, punctuation, non-ASCII text, empty stdin, and a file without a final newline.

## Alternatives considered

- **Keep two standalone scripts (preferred) vs `tools/lib.sh`.** There is no shared helper today and only two callers; a library adds sourcing/path/error coupling. Add it only after a third tool demonstrably shares nontrivial code.
- **Inline `--self-check` vs `tests/test-tools.sh`.** Inline checks make copied scripts self-verifying, but a separate test can exercise both programs as installed executables and avoids reserving user input. Existing tests are separate scripts (`tests/test-evolve.sh:1-131`, `tests/test-hooks.sh:1-74`), so neither choice is an established repo mandate.
- **`wc` wrapper (preferred) vs `awk`.** `wc -w/-l` is smallest and matches common shell semantics. `awk` becomes warranted only if the desired word definition differs from `wc` or both counts must be produced from one read with explicitly controlled locale semantics.

## Missed risks

- **Temporary self-check fixtures can leak.** File-input checks need a temp file; both existing test scripts pair `mktemp` with `trap cleanup EXIT` (`nimbalyst-local/agent-context/smoke-test.sh:6-12`; `tests/test-evolve.sh:6-27`). The plan says nothing about cleanup.
- **Strict-mode pipeline failures can be accidentally masked or abort the check.** The smoke test deliberately guards a pipeline with `&& exit 1 || true` at `nimbalyst-local/agent-context/smoke-test.sh:44`; count extraction/self-check pipelines need equally explicit success handling under `pipefail`.
- **Argument-looking filenames and reserved test mode need an escape rule.** The existing CLI distinguishes `--target`, `--target=*`, and other arguments in `agent-context.sh:26-37`; a one-flag tool without `--` makes `word-count.sh --self-check` impossible for a real filename, not merely an acceptable theoretical collision.
- **Output must avoid `wc`'s formatting leaking into the API.** The repo consistently uses controlled `printf` records (`agent-context.sh:85-94`, `smoke-test.sh:84`); raw `wc` output has leading padding and may include a filename, so the extraction/format contract needs tests.
- **Locale affects word counting too, not only slug lowercasing.** `agent-context.sh:278` already uses a locale-sensitive character class (`tr -d '[:space:]'`); the plan fixes `LC_ALL` only for slugification while leaving the intended `wc -w` behavior on multibyte/Unicode input unspecified.

## Verdict: big disagreement?

BIG DISAGREEMENT: no. Standalone `wc`-backed tools with no shared library are the right small design; the substantive corrections are the false “new tools directory” and “smoke-test pass/fail precedent” claims, plus missing CLI and output contracts.
