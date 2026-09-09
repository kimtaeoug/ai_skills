#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="$REPO_ROOT/bin/install-evolve"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail() { echo "FAIL: $1"; exit 1; }

[ -f "$REPO_ROOT/.agents/skills/evolve/SKILL.md" ] || fail "canonical evolve skill is not tracked in .agents"
[ -f "$REPO_ROOT/.claude/skills/evolve/SKILL.md" ] || fail "Claude project skill bridge is missing"
[ -f "$REPO_ROOT/.codex/skills/evolve/SKILL.md" ] || fail "Codex project skill bridge is missing"
[ -x "$INSTALLER" ] || fail "installer is missing or not executable"

TEST_HOME="$TMP/home"
mkdir -p "$TEST_HOME/.claude"
printf '%s\n' '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"keep-me"}]}]}}' > "$TEST_HOME/.claude/settings.json"

EVOLVE_INSTALL_HOME="$TEST_HOME" "$INSTALLER" >/dev/null
EVOLVE_INSTALL_HOME="$TEST_HOME" "$INSTALLER" >/dev/null

for runtime in .agents .claude .codex; do
  link="$TEST_HOME/$runtime/skills/evolve"
  [ -L "$link" ] || fail "$runtime evolve link was not installed"
  [ "$(cd "$link" && pwd -P)" = "$REPO_ROOT/.agents/skills/evolve" ] || fail "$runtime evolve link targets the wrong source"
done

FRESH_HOME="$TMP/fresh-home"
EVOLVE_INSTALL_HOME="$FRESH_HOME" "$INSTALLER" >/dev/null
[ -f "$FRESH_HOME/.claude/settings.json" ] || fail "installer did not create missing Claude settings"

python3 - "$TEST_HOME/.claude/settings.json" "$REPO_ROOT/bin/hooks/evolve-track.sh" "$REPO_ROOT/bin/hooks/evolve-autorecord.sh" <<'PY' || exit 1
import json
import sys

settings, track, stop = sys.argv[1:4]
data = json.load(open(settings))

def commands(event):
    return [
        hook.get("command")
        for item in data.get("hooks", {}).get(event, [])
        for hook in item.get("hooks", [])
    ]

assert "keep-me" in commands("Stop"), "installer removed an existing hook"
assert commands("PostToolUse").count(track) == 1, "track hook should be installed exactly once"
assert commands("Stop").count(stop) == 1, "stop hook should be installed exactly once"
PY

CONFLICT_HOME="$TMP/conflict-home"
mkdir -p "$CONFLICT_HOME/.agents/skills/evolve"
if EVOLVE_INSTALL_HOME="$CONFLICT_HOME" "$INSTALLER" >/dev/null 2>&1; then
  fail "installer should not replace an existing skill directory"
fi

echo "all evolve installation tests passed"
