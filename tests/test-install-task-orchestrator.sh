#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="$REPO_ROOT/bin/install-task-orchestrator"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail() { echo "FAIL: $1"; exit 1; }

[ -x "$INSTALLER" ] || fail "installer is missing or not executable"

TEST_HOME="$TMP/home"
HOME="$TEST_HOME" "$INSTALLER" >/dev/null
HOME="$TEST_HOME" "$INSTALLER" >/dev/null

for skill in task-orchestrator research-team archon-adversarial-dev test-agent-team; do
  source="$REPO_ROOT/.claude/skills/$skill"
  for runtime in .agents .claude .codex; do
    link="$TEST_HOME/$runtime/skills/$skill"
    [ -L "$link" ] || fail "$runtime/$skill was not installed"
    [ "$(cd "$link" && pwd -P)" = "$source" ] || fail "$runtime/$skill targets the wrong source"
  done
done

CONFLICT_HOME="$TMP/conflict-home"
mkdir -p "$CONFLICT_HOME/.codex/skills/task-orchestrator"
printf 'preserve\n' > "$CONFLICT_HOME/.codex/skills/task-orchestrator/marker"
if HOME="$CONFLICT_HOME" "$INSTALLER" >"$TMP/out" 2>"$TMP/err"; then
  fail "installer should reject a conflicting directory"
fi
[ "$(cat "$CONFLICT_HOME/.codex/skills/task-orchestrator/marker")" = "preserve" ] \
  || fail "installer changed a conflicting directory"

echo "all task orchestrator installation tests passed"
