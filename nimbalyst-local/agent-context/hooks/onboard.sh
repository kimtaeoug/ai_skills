#!/usr/bin/env bash
set -euo pipefail

LIMIT=7999
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
CLI="$SCRIPT_DIR/../agent-context.sh"

usage() { printf 'usage: onboard.sh <claude|codex>\n' >&2; }

[ "$#" -eq 1 ] || { usage; exit 0; }
case "$1" in claude|codex) AGENT=$1 ;; *) usage; exit 0 ;; esac

ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0

if ! "$CLI" status --target "$ROOT" >/dev/null 2>&1; then
  printf '%s\n' 'agent-context is not set up; invoke the agent-context-setup skill to enable it.'
  exit 0
fi

RESUME=$("$CLI" resume "$AGENT" --target "$ROOT" 2>/dev/null) || exit 0
[ "${#RESUME}" -le "$LIMIT" ] && { printf '%s' "$RESUME"; exit 0; }

prefix='' current='' best='' kept=''
declare -a events=()
while IFS= read -r line || [ -n "$line" ]; do
  if [[ "$line" == '=== EVENT '* ]]; then
    [ -z "$current" ] || events+=("$current")
    current="$line"$'\n'
  elif [ -n "$current" ]; then
    current+="$line"$'\n'
  else
    prefix+="$line"$'\n'
  fi
done <<< "$RESUME"
[ -z "$current" ] || events+=("$current")

if [ "${#prefix}" -gt "$LIMIT" ]; then
  printf '%s\n' 'agent-context checkpoint is too large for automatic injection; run agent-context.sh resume manually.'
  exit 0
fi

for ((i=${#events[@]} - 1; i >= 0; i--)); do
  note=
  [ "$i" -eq 0 ] || note="(older events truncated, $i events omitted)"$'\n\n'
  candidate="$prefix$note${events[$i]}$kept"
  if [ "${#candidate}" -le "$LIMIT" ]; then
    best=$candidate
    kept="${events[$i]}$kept"
  fi
done

if [ -z "$best" ]; then
  printf '%s(older events truncated, %s events omitted)\n' "$prefix" "${#events[@]}"
else
  printf '%s' "$best"
fi
