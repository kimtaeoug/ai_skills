#!/usr/bin/env bash
set -euo pipefail

usage() { printf 'usage: install.sh <target-repo-path>\n' >&2; exit 1; }
[ "$#" -eq 1 ] || usage

PACKAGE_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
TARGET=$(git -C "$1" rev-parse --show-toplevel 2>/dev/null) || { printf 'agent-context: target is not a Git repository: %s\n' "$1" >&2; exit 1; }

merge_json() {
  local destination=$1 fragment=$2 temporary
  mkdir -p "$(dirname "$destination")"
  [ -f "$destination" ] || printf '{}\n' > "$destination"
  temporary=$(mktemp "${TMPDIR:-/tmp}/agent-context-json.XXXXXX")
  if command -v jq >/dev/null 2>&1; then
    jq --slurpfile addition "$fragment" '
      if type != "object" then error("configuration root must be a JSON object") else
        .hooks = ((.hooks // {}) as $base | $addition[0].hooks as $new |
          reduce ($new | to_entries[]) as $entry ($base;
            .[$entry.key] = (((.[$entry.key] // []) + $entry.value) | unique)
          ))
      end
    ' "$destination" > "$temporary"
  else
    python3 - "$destination" "$fragment" "$temporary" <<'PY'
import json
import sys

destination, fragment, temporary = map(__import__('pathlib').Path, sys.argv[1:])
current = json.loads(destination.read_text())
addition = json.loads(fragment.read_text())
if not isinstance(current, dict) or not isinstance(addition, dict):
    raise SystemExit('configuration root must be a JSON object')
hooks = current.setdefault('hooks', {})
if not isinstance(hooks, dict):
    raise SystemExit('configuration hooks must be a JSON object')
for event, entries in addition.get('hooks', {}).items():
    existing = hooks.setdefault(event, [])
    if not isinstance(existing, list):
        raise SystemExit(f'configuration hooks.{event} must be an array')
    for entry in entries:
        if entry not in existing:
            existing.append(entry)
temporary.write_text(json.dumps(current, indent=2) + '\n')
PY
  fi
  mv "$temporary" "$destination"
}

merge_codex_config() {
  local destination=$1
  mkdir -p "$(dirname "$destination")"
  [ -f "$destination" ] || : > "$destination"
  python3 - "$destination" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
lines = path.read_text().splitlines()
start = next((i for i, line in enumerate(lines) if re.match(r'^\s*\[features\]\s*(?:#.*)?$', line)), None)
keys = ('hooks', 'codex_hooks')
if start is None:
    if lines and lines[-1] != '':
        lines.append('')
    lines.extend(['[features]', 'hooks = true', 'codex_hooks = true'])
else:
    end = next((i for i in range(start + 1, len(lines)) if re.match(r'^\s*\[', lines[i])), len(lines))
    seen = set()
    for i in range(start + 1, end):
        match = re.match(r'^\s*(hooks|codex_hooks)\s*=', lines[i])
        if match:
            key = match.group(1)
            lines[i] = f'{key} = true'
            seen.add(key)
    insert_at = end
    for key in keys:
        if key not in seen:
            lines.insert(insert_at, f'{key} = true')
            insert_at += 1
path.write_text('\n'.join(lines) + '\n')
PY
}

mkdir -p "$TARGET/.agent-context/hooks"
cp "$PACKAGE_ROOT/agent-context.sh" "$TARGET/.agent-context/agent-context.sh"
cp "$PACKAGE_ROOT/hooks/onboard.sh" "$TARGET/.agent-context/hooks/onboard.sh"
chmod +x "$TARGET/.agent-context/agent-context.sh" "$TARGET/.agent-context/hooks/onboard.sh"
"$TARGET/.agent-context/agent-context.sh" init --target "$TARGET" >/dev/null

merge_json "$TARGET/.claude/settings.json" "$PACKAGE_ROOT/templates/claude-settings.hooks.json"
merge_json "$TARGET/.codex/hooks.json" "$PACKAGE_ROOT/templates/codex-hooks.json"
merge_codex_config "$TARGET/.codex/config.toml"

printf 'created or updated: %s\n' "$TARGET/.agent-context"
printf 'created or updated: %s\n' "$TARGET/.claude/settings.json"
printf 'created or updated: %s\n' "$TARGET/.codex/hooks.json"
printf 'created or updated: %s\n' "$TARGET/.codex/config.toml"
