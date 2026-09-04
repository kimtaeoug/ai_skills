#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EVOLVE="$REPO_ROOT/bin/evolve"
TMP="$(mktemp -d)"

cleanup() {
  rm -rf "$TMP"
  rm -f "$REPO_ROOT/evolution/.state/copy-skill.txt"
  rm -rf "$REPO_ROOT/evolution/.state/copy-skill.snapshot"
  rm -f "$REPO_ROOT/evolution/.state/git-skill.txt"
  rm -f "$REPO_ROOT/evolution/.state/no-baseline.txt"
  rm -f "$REPO_ROOT/evolution/.state/no-change-skill.txt"
  rm -rf "$REPO_ROOT/evolution/.state/no-change-skill.snapshot"
}
trap cleanup EXIT

pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1"; exit 1; }

# --- copy-mode (non-git dir) ---
COPY_SKILL="$TMP/copy-skill"
mkdir -p "$COPY_SKILL"
echo "line one" > "$COPY_SKILL/SKILL.md"

"$EVOLVE" snapshot "$COPY_SKILL" > /dev/null
echo "line two" >> "$COPY_SKILL/SKILL.md"
DIFF_OUT="$("$EVOLVE" diff "$COPY_SKILL")"
echo "$DIFF_OUT" | grep -q "line two" && pass "copy-mode diff captures change" || fail "copy-mode diff missing change"

# --- git-mode ---
GIT_SKILL="$TMP/git-skill"
mkdir -p "$GIT_SKILL"
git -C "$GIT_SKILL" init -q
echo "line one" > "$GIT_SKILL/SKILL.md"
git -C "$GIT_SKILL" add SKILL.md
git -C "$GIT_SKILL" -c user.email=t@t.com -c user.name=t commit -q -m init

"$EVOLVE" snapshot "$GIT_SKILL" > /dev/null
echo "line two" >> "$GIT_SKILL/SKILL.md"
DIFF_OUT="$("$EVOLVE" diff "$GIT_SKILL")"
echo "$DIFF_OUT" | grep -q "line two" && pass "git-mode diff captures change" || fail "git-mode diff missing change"

# --- no-changes case ---
NO_CHANGE_SKILL="$TMP/no-change-skill"
mkdir -p "$NO_CHANGE_SKILL"
echo "content" > "$NO_CHANGE_SKILL/SKILL.md"
"$EVOLVE" snapshot "$NO_CHANGE_SKILL" > /dev/null
if OUT="$("$EVOLVE" diff "$NO_CHANGE_SKILL")"; then
  [ -z "$OUT" ] && pass "diff with no changes is empty and exits 0" || fail "diff with no changes should be empty, got: $OUT"
else
  fail "diff with no changes should exit 0"
fi

# --- error case: diff without snapshot ---
NO_BASELINE="$TMP/no-baseline"
mkdir -p "$NO_BASELINE"
if "$EVOLVE" diff "$NO_BASELINE" 2>"$TMP/err.log"; then
  fail "diff without snapshot should exit nonzero"
else
  grep -q "no baseline found" "$TMP/err.log" && pass "diff without snapshot errors clearly" || fail "error message missing expected text"
fi

echo "all tests passed"
