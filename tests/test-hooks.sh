#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TRACK_HOOK="$REPO_ROOT/bin/hooks/evolve-track.sh"
AUTORECORD_HOOK="$REPO_ROOT/bin/hooks/evolve-autorecord.sh"
EVOLVE="$REPO_ROOT/bin/evolve"
TMP="$(mktemp -d)"
SESSION_ID="hook-test-session"

cleanup() {
  rm -rf "$TMP"
  rm -f "$REPO_ROOT/evolution/.state/.sessions/${SESSION_ID}-touched.txt"
  rm -f "$REPO_ROOT/evolution/.state/hook-skill.txt"
  rm -rf "$REPO_ROOT/evolution/.state/hook-skill.snapshot"
  rm -f "$HOME/.agents/skills/hook-skill"
}
trap cleanup EXIT

pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1"; exit 1; }

# --- evolve-track.sh: tracks a real personal skill ---
HOOK_SKILL="$TMP/hook-skill"
mkdir -p "$HOOK_SKILL"
echo "v1" > "$HOOK_SKILL/SKILL.md"
mkdir -p "$HOME/.agents/skills"
ln -sfn "$HOOK_SKILL" "$HOME/.agents/skills/hook-skill"

echo "{\"session_id\":\"$SESSION_ID\",\"tool_name\":\"Skill\",\"tool_input\":{\"skill\":\"hook-skill\"}}" | "$TRACK_HOOK"
if [ -f "$REPO_ROOT/evolution/.state/hook-skill.txt" ]; then
  pass "evolve-track.sh creates a baseline for a real personal skill"
else
  fail "evolve-track.sh should have created a baseline"
fi

# --- evolve-track.sh: skips namespaced/plugin skills ---
echo "{\"session_id\":\"$SESSION_ID\",\"tool_name\":\"Skill\",\"tool_input\":{\"skill\":\"superpowers:brainstorming\"}}" | "$TRACK_HOOK"
if [ -f "$REPO_ROOT/evolution/.state/brainstorming.txt" ]; then
  fail "evolve-track.sh should NOT track a namespaced plugin skill"
else
  pass "evolve-track.sh skips namespaced plugin skills"
fi

# --- evolve-track.sh: missing skill_name is a silent no-op ---
OUT="$(echo "{\"session_id\":\"$SESSION_ID\",\"tool_name\":\"Skill\",\"tool_input\":{}}" | "$TRACK_HOOK")"
[ -z "$OUT" ] && pass "evolve-track.sh no-ops silently on missing skill name" || fail "expected empty output, got: $OUT"

# --- evolve-autorecord.sh: no pending -> empty JSON, no block ---
"$EVOLVE" clear-session "$SESSION_ID" 2>/dev/null || true
OUT="$(echo "{\"session_id\":\"$SESSION_ID\"}" | "$AUTORECORD_HOOK")"
[ "$OUT" = "{}" ] && pass "evolve-autorecord.sh does not block with no pending skills" || fail "expected {}, got: $OUT"

# --- evolve-autorecord.sh: pending change -> blocks with reason mentioning the skill ---
"$EVOLVE" track "$SESSION_ID" "$HOOK_SKILL" >/dev/null
echo "v2" >> "$HOOK_SKILL/SKILL.md"
OUT="$(echo "{\"session_id\":\"$SESSION_ID\"}" | "$AUTORECORD_HOOK")"
echo "$OUT" | jq -e '.hookSpecificOutput.hookEventName == "Stop"' >/dev/null \
  && echo "$OUT" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null \
  && echo "$OUT" | jq -r '.hookSpecificOutput.permissionDecisionReason' | grep -q "hook-skill" \
  && pass "evolve-autorecord.sh blocks (permissionDecision=deny) and names the changed skill" \
  || fail "expected a deny block mentioning hook-skill, got: $OUT"

# --- evolve-autorecord.sh: after snapshot, pending clears and it no longer blocks ---
"$EVOLVE" snapshot "$HOOK_SKILL" >/dev/null
OUT="$(echo "{\"session_id\":\"$SESSION_ID\"}" | "$AUTORECORD_HOOK")"
[ "$OUT" = "{}" ] && pass "evolve-autorecord.sh stops blocking once the skill is re-snapshotted" || fail "expected {} after snapshot, got: $OUT"

echo "all hook tests passed"
