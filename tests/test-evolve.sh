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
  rm -f "$REPO_ROOT/evolution/.state/git-untracked-skill.txt"
  rm -f "$REPO_ROOT/evolution/.state/corrupt-skill.txt"
  rm -rf "$REPO_ROOT/evolution/.state/.sessions"
  rm -f "$HOME/.agents/skills/track-skill"
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

# --- git-mode diff surfaces untracked (new) files ---
GIT_UNTRACKED_SKILL="$TMP/git-untracked-skill"
mkdir -p "$GIT_UNTRACKED_SKILL"
git -C "$GIT_UNTRACKED_SKILL" init -q
echo "line one" > "$GIT_UNTRACKED_SKILL/SKILL.md"
git -C "$GIT_UNTRACKED_SKILL" add SKILL.md
git -C "$GIT_UNTRACKED_SKILL" -c user.email=t@t.com -c user.name=t commit -q -m init

"$EVOLVE" snapshot "$GIT_UNTRACKED_SKILL" > /dev/null
echo "new reference doc" > "$GIT_UNTRACKED_SKILL/new-reference.md"
DIFF_OUT="$("$EVOLVE" diff "$GIT_UNTRACKED_SKILL")"
echo "$DIFF_OUT" | grep -q "new-reference.md" && pass "git-mode diff surfaces new untracked file" || fail "git-mode diff missing untracked file"

# --- error case: corrupt state file ---
CORRUPT_SKILL="$TMP/corrupt-skill"
mkdir -p "$CORRUPT_SKILL"
echo "content" > "$CORRUPT_SKILL/SKILL.md"
"$EVOLVE" snapshot "$CORRUPT_SKILL" > /dev/null
: > "$REPO_ROOT/evolution/.state/corrupt-skill.txt"
if "$EVOLVE" diff "$CORRUPT_SKILL" 2>"$TMP/corrupt-err.log"; then
  fail "diff with corrupt state file should exit nonzero"
else
  grep -q "corrupt state file" "$TMP/corrupt-err.log" && pass "diff with corrupt state file errors clearly" || fail "expected 'corrupt state file' message, got: $(cat "$TMP/corrupt-err.log")"
fi

# --- track: auto-snapshots when no baseline exists ---
TRACK_SKILL="$TMP/track-skill"
mkdir -p "$TRACK_SKILL"
echo "v1" > "$TRACK_SKILL/SKILL.md"
"$EVOLVE" track "test-session-1" "$TRACK_SKILL"
if [ -f "$REPO_ROOT/evolution/.state/track-skill.txt" ]; then
  pass "track auto-snapshots a skill with no baseline"
else
  fail "track should have created a baseline state file"
fi

# --- track: dedups repeated calls in the same session ---
"$EVOLVE" track "test-session-1" "$TRACK_SKILL"
"$EVOLVE" track "test-session-1" "$TRACK_SKILL"
TOUCHED_COUNT="$(grep -c "^track-skill$" "$REPO_ROOT/evolution/.state/.sessions/test-session-1-touched.txt")"
[ "$TOUCHED_COUNT" -eq 1 ] && pass "track dedups repeated calls" || fail "track should list track-skill exactly once, got $TOUCHED_COUNT"

# --- pending: empty when no changes since track ---
PENDING_OUT="$("$EVOLVE" pending "test-session-1")"
[ -z "$PENDING_OUT" ] && pass "pending is empty with no changes" || fail "pending should be empty, got: $PENDING_OUT"

# --- pending: reports skill after a real change ---
echo "v2" >> "$TRACK_SKILL/SKILL.md"
# pending resolves skill dirs via ~/.agents/skills/<name>, so symlink the temp dir there for this test
mkdir -p "$HOME/.agents/skills"
ln -sfn "$TRACK_SKILL" "$HOME/.agents/skills/track-skill"
PENDING_OUT="$("$EVOLVE" pending "test-session-1")"
echo "$PENDING_OUT" | grep -qx "track-skill" && pass "pending reports a changed tracked skill" || fail "pending should list track-skill, got: $PENDING_OUT"
rm -f "$HOME/.agents/skills/track-skill"

# --- clear-session: removes the touched-file ---
"$EVOLVE" clear-session "test-session-1"
[ ! -f "$REPO_ROOT/evolution/.state/.sessions/test-session-1-touched.txt" ] && pass "clear-session removes the touched file" || fail "clear-session should have removed the touched file"

echo "all tests passed"
