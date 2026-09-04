#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
INSTALLER="$ROOT_DIR/install.sh"
BOOTSTRAP="$ROOT_DIR/bootstrap.sh"
SCRATCH=$(mktemp -d "${TMPDIR:-/tmp}/agent-context-onboarding.XXXXXX")
TARGET="$SCRATCH/dev-repo"
GLOBAL_BASE="$SCRATCH/global-base"

cleanup() { rm -rf "$SCRATCH"; }
trap cleanup EXIT

git init -q "$TARGET"
git -C "$TARGET" config user.name "Onboarding Smoke Test"
git -C "$TARGET" config user.email "onboarding@example.invalid"
printf 'seed\n' > "$TARGET/README"
git -C "$TARGET" add README
git -C "$TARGET" commit -qm seed

mkdir -p "$TARGET/.claude" "$TARGET/.codex"
printf '{"hooks":{"Stop":[{"hooks":[]}]},"keep":true}\n' > "$TARGET/.claude/settings.json"
printf '{"hooks":{"Stop":[{"hooks":[]}]},"keep":true}\n' > "$TARGET/.codex/hooks.json"
printf 'model = "test"\n\n[features]\nother = true\n' > "$TARGET/.codex/config.toml"

BEFORE=$(cd "$TARGET" && "$ROOT_DIR/hooks/onboard.sh" claude)
test "$BEFORE" = 'agent-context is not set up; invoke the agent-context-setup skill to enable it.'
test ! -e "$TARGET/.git/agent-context.git"

"$INSTALLER" "$TARGET"

test -x "$TARGET/.agent-context/agent-context.sh"
test -x "$TARGET/.agent-context/hooks/onboard.sh"
test -d "$TARGET/.git/agent-context.git"
test -f "$TARGET/.claude/settings.json"
test -f "$TARGET/.codex/hooks.json"
test ! -e "$TARGET/.claude/skills/agent-context-setup"
test ! -e "$TARGET/.codex/skills/agent-context-setup"
grep -F 'codex_hooks = true' "$TARGET/.codex/config.toml" >/dev/null
python3 - "$TARGET" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
for path, agent in ((root / '.claude/settings.json', 'claude'), (root / '.codex/hooks.json', 'codex')):
    data = json.loads(path.read_text())
    assert data['keep'] is True
    assert data['hooks']['Stop'] == [{'hooks': []}]
    session_start = data['hooks']['SessionStart']
    assert len(session_start) == 1
    assert session_start[0]['matcher'] == 'startup|resume'
    assert session_start[0]['hooks'][0]['command'].endswith(f'.agent-context/hooks/onboard.sh" {agent}')
PY

"$INSTALLER" "$TARGET"
python3 - "$TARGET" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
for path in (root / '.claude/settings.json', root / '.codex/hooks.json'):
    assert len(json.loads(path.read_text())['hooks']['SessionStart']) == 1
PY

CLI="$TARGET/.agent-context/agent-context.sh"
printf 'goal: retain the full checkpoint body\nconfirmed decisions/invariants: none\ncompleted work: none\nactive plan: add events\nnext action: resume\nopen questions: none\n' |
  "$CLI" checkpoint claude --target "$TARGET" >/dev/null
for i in $(seq 1 19); do
  printf 'event %s: %0600d\n' "$i" "$i" |
    "$CLI" append claude summary --target "$TARGET" >/dev/null
done

AFTER=$(cd "$TARGET" && ./.agent-context/hooks/onboard.sh claude)
test "${#AFTER}" -le 8000
printf '%s\n' "$AFTER" | grep -F 'goal: retain the full checkpoint body' >/dev/null
printf '%s\n' "$AFTER" | grep -F '(older events truncated,' >/dev/null
printf '%s\n' "$AFTER" | grep -F 'event 19:' >/dev/null

"$BOOTSTRAP" "$GLOBAL_BASE"
for skill in "$GLOBAL_BASE/.claude/skills/agent-context-setup" "$GLOBAL_BASE/.codex/skills/agent-context-setup"; do
  test -L "$skill"
  test -f "$skill/SKILL.md"
  test -x "$skill/install.sh"
done
"$BOOTSTRAP" "$GLOBAL_BASE" > "$SCRATCH/bootstrap-second-run"
grep -F 'exists; skipped:' "$SCRATCH/bootstrap-second-run" >/dev/null
PLACEHOLDER='/path/to/'
PLACEHOLDER+='agent-context-source-package'
grep -rF "$PLACEHOLDER" "$ROOT_DIR" >/dev/null && exit 1

printf 'agent-context onboarding smoke test passed\n'
