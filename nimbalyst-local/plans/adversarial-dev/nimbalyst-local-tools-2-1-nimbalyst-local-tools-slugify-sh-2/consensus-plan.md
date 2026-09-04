# Consensus Plan: add `slugify.sh` and `word-count.sh` to `nimbalyst-local/tools/`

## Goal

Add two small, independent, dependency-free shell utility scripts to the existing (currently empty) `nimbalyst-local/tools/` directory:

1. `slugify.sh` — turns arbitrary text into an ASCII-only URL/filename-safe slug.
2. `word-count.sh` — counts words and lines in stdin or a file argument, via `wc`.

Each script is self-contained, has its own inline assert-based self-check (`--self-check` mode, no external test framework, no shared helper file), and does not depend on the other.

## Key files/paths

- `nimbalyst-local/tools/slugify.sh` (new file; directory already exists, empty, untracked)
- `nimbalyst-local/tools/word-count.sh` (new file)
- `nimbalyst-local/plans/adversarial-dev/nimbalyst-local-tools-2-1-nimbalyst-local-tools-slugify-sh-2/` (plan.md, critique.md, consensus-plan.md)

**Correction from critique (verified):** `nimbalyst-local/tools/` already exists on disk (empty, untracked by git). The original plan's claim that no such directory exists yet is stale/false. This plan does not create the directory as new — it adds two files into it.

**Correction from critique (verified):** `nimbalyst-local/agent-context/smoke-test.sh` does NOT use a `pass()`/`fail()` idiom — it uses direct `test`/command checks under `set -euo pipefail` and prints a single `agent-context smoke test passed` line at the end (line 84). The `pass`/`fail`/`PASS:`/`FAIL:` idiom actually comes from `tests/test-evolve.sh:26-27,37,50` and `tests/test-hooks.sh:20-21`, not from smoke-test.sh. The plan's precedent citation is corrected accordingly.

## Grounding in repo conventions (verified)

- Shebang `#!/usr/bin/env bash` + `set -euo pipefail` — confirmed in both `agent-context.sh:1-2` and `smoke-test.sh:1-2`.
- Error helper pattern: `die() { printf '<tool>: %s\n' "$*" >&2; exit 1; }` — confirmed as local precedent in `agent-context.sh:8` (not a universal repo mandate, but reasonable to follow).
- Self-check idiom: `pass()`/`fail()` printing `PASS: <name>` / `FAIL: <name>`, plain `test`/`[ ]`/`grep -F` assertions, exit 1 on first failure — confirmed in `tests/test-evolve.sh` and `tests/test-hooks.sh` (both separate `test-*.sh` files, not inline `--self-check` flags — see Design choices below for why we deviate here).
- No tracked Makefile/package.json/CI runner anywhere in the repo — confirmed via `git ls-files` and `baseline.md:10-19`. No test-runner wiring exists to hook into.
- All tracked `.sh` files are executable (mode 100755) — confirmed via `git ls-files -s -- '*.sh'`.
- Strict-mode pipelines that may legitimately fail are explicitly guarded (e.g. `smoke-test.sh:44` uses `&& exit 1 || true` rather than letting `pipefail` abort ambiguously) — this pattern must be followed for any pipe used inside the self-checks.
- Temp fixtures use `mktemp` paired with `trap cleanup EXIT` (`smoke-test.sh:6-12`, `tests/test-evolve.sh:6-27`) — must be followed for `word-count.sh`'s file-input self-check.

## Design choices

- **Single-file, no shared lib.** Two standalone scripts don't justify a shared `tools/lib.sh`. Add one only if a third tool needs genuinely shared logic.
- **Self-check via `--self-check` flag**, not a separate `tests/test-tools.sh` file. This is a deliberate deviation from the repo's only existing self-check precedent (which uses separate `test-*.sh` files) because it keeps each tool script literally copy-paste-portable and self-verifying with zero extra files. Trade-off (per critique's "Alternatives considered"): a separate test file could exercise the installed executables end-to-end and wouldn't need to reserve a CLI flag. Accepted trade-off for a personal/local tool of this size; revisit if these scripts are ever shared outside this repo or a real filename needs to literally be `--self-check`.
- **`--self-check` recognized only when it is the sole argument** (`argv == ("--self-check",)`), not merged into general option parsing — avoids ambiguity with `--` handling below.
- **`--` supported as an explicit end-of-options marker** so a real filename or literal string beginning with `-` (including the literal text `--self-check`) can always be passed unambiguously: `slugify.sh -- --self-check` slugifies the literal string; `word-count.sh -- -weird-filename` treats it as a filename.
- **`slugify.sh` argument precedence:** if any non-flag argv is present, all argv words are joined with a single space and slugified as one string (`slugify.sh a b` slugifies `"a b"`, not two separate outputs) and stdin is ignored. If no argv (after flag/`--` processing) is given, stdin is read and slugified as one string. This precedence is stated explicitly in the script's usage comment.
- **`slugify.sh` is ASCII-only, not "diacritic-stripping."** Corrected from the original plan's "strip diacritics best-effort via `tr`" — under `LC_ALL=C`, `tr`/`sed` cannot transliterate accented UTF-8 characters (e.g. é → e); they can only discard or mangle those bytes. The script filters to `[a-z0-9]` runs after lowercasing and `LC_ALL=C` byte-wise processing, and non-ASCII input is documented as producing degraded/dropped output, not transliteration. Tagged with `# ponytail: ASCII-only slug folding, byte-drops non-Latin input; add real Unicode transliteration (e.g. iconv -t ascii//TRANSLIT) if non-Latin input becomes a requirement`.
- **`slugify.sh` output contract:** always exactly one line to stdout, terminated by a single trailing newline. Empty/whitespace-only/all-non-alnum input yields an empty line (not an error, exit 0).
- **`word-count.sh` is a thin wrapper over `wc -w`/`wc -l`**, not hand-rolled tokenizing. Reads stdin (no args) or a single file argument (`word-count.sh <file>`). More than one file argument is rejected with a `die` usage error — no multi-file aggregation, out of scope.
- **`word-count.sh` output contract:** normalizes `wc`'s raw output (which pads with leading whitespace and may include a filename column) into controlled `printf` records: `words: N` then `lines: N`, matching the repo's `printf`-record style (`agent-context.sh:85-94`, `smoke-test.sh:84`) rather than leaking raw `wc` formatting.
- **`word-count.sh` error handling:** missing/unreadable file argument → `die "cannot read file: <path>"`, exit 1. Empty stdin/empty file → `words: 0` / `lines: 0`, exit 0 (not an error).
- **`lines` semantics:** defined as `wc -l`'s newline-count semantics (a final line with no trailing newline is not counted) — explicitly documented in the script comment as `wc -l` behavior, not "visible lines," so there is no silent surprise on files missing a final newline.
- **Locale:** `LC_ALL=C` is set in both scripts, not just `slugify.sh` — `word-count.sh`'s use of `wc -w` on multibyte/Unicode input is otherwise locale-dependent (mirrors the existing locale-sensitivity precedent already present in `agent-context.sh:278`'s `tr -d '[:space:]'`). Documented as byte/ASCII-oriented counting; not Unicode-aware word segmentation.
- **Assert style:** mirrors `tests/test-evolve.sh` — `pass()`/`fail()` helpers printing `PASS: <name>` / `FAIL: <name>`, `[ "$actual" = "$expected" ] && pass "..." || fail "..."`, exits non-zero on first failure. `word-count.sh`'s self-check uses `mktemp` + `trap cleanup EXIT` for its file-input fixture, matching the repo's existing temp-fixture-cleanup precedent.
- **Pipefail safety:** any pipeline inside the self-checks that could legitimately produce a "failure" as a valid test outcome (e.g. checking that bad input is rejected) is guarded explicitly (`... && exit 1 || true` or equivalent), not left to raw `pipefail` semantics — matching `smoke-test.sh:44`.
- Both files `chmod +x`, matching every existing tracked `.sh` in the repo.

## Test plan (self-check coverage, per critique's flagged gaps)

Each script's `--self-check` covers, at minimum:
- `slugify.sh`: normal text, whitespace-only input, leading/trailing punctuation, consecutive punctuation, non-ASCII byte input (documents degraded-but-non-crashing behavior), empty stdin, multi-arg join behavior, `--` literal-string handling.
- `word-count.sh`: normal file, empty file, file without a final trailing newline (confirms `wc -l` semantics), missing file (confirms `die` + exit 1), stdin input, multi-file-argument rejection.

## Risks

- Locale-dependent byte handling in both scripts — mitigated with `LC_ALL=C` in both; documented as ASCII-only behavior with `# ponytail:` tags naming the upgrade path, not silently "best-effort" as originally claimed.
- `--self-check` / `--` flag collisions with literal input — mitigated by the explicit `--` end-of-options rule (see Design choices), no longer just "acceptable collision."
- No CI wiring exists to run these self-checks automatically — explicitly out of scope, not silently added.
- macOS vs GNU `tr`/`wc`/`mktemp` flag differences — stick to POSIX-portable flags only (dev machine is macOS); self-checks double as the portability check.

## Out of scope

No shared lib, no getopts framework, no README, no test-runner/CI wiring, no Unicode transliteration, no multi-file support for `word-count.sh` — none requested, none justified for 2 scripts.

## Verdict on critique

No big disagreement between plan and critique. The critique's two factual corrections (tools/ directory already exists; smoke-test.sh does not use pass/fail) are adopted verbatim above. All flagged gaps (input precedence, exit codes, `--` escape rule, output record format, locale scope, diacritics accuracy, temp-fixture cleanup, pipefail guarding) are resolved into explicit design decisions in this consensus plan rather than left implicit.
