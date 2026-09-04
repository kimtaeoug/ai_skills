#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EVOLVE="$SCRIPT_DIR/../evolve"
[ -x "$EVOLVE" ] || exit 0
command -v jq >/dev/null 2>&1 || exit 0

input="$(cat)"
skill_name="$(printf '%s' "$input" | jq -r '.tool_input.skill // empty' 2>/dev/null)"
session_id="$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null)"

[ -n "$skill_name" ] && [ -n "$session_id" ] || exit 0

case "$skill_name" in
  *:*) exit 0 ;;
esac

skill_dir="$HOME/.agents/skills/$skill_name"
[ -d "$skill_dir" ] || exit 0

"$EVOLVE" track "$session_id" "$skill_dir" >/dev/null 2>&1
exit 0
