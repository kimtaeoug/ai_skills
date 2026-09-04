# 스킬 진화 메커니즘 — 자동화 확장 (Auto-Hook) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 스킬을 어느 워크스페이스에서든 호출하면, 세션이 끝날 때 그 스킬의 baseline 대비 변경 델타가 사람 개입 없이 `evolution/records/`에 자동 기록되게 한다.

**Architecture:** `bin/evolve`에 세션 스코프 추적용 서브커맨드 3개(`track`/`pending`/`clear-session`)를 추가하고, 그걸 호출하는 얇은 훅 스크립트 2개(`PostToolUse`용 `evolve-track.sh`, `Stop`용 `evolve-autorecord.sh`)를 만들어 `~/.claude/settings.json`(user-level)에 등록한다. `Stop` 훅이 델타를 감지하면 세션을 막고(`decision:"block"`) Claude에게 세션 맥락으로 record를 직접 쓰라고 지시한다.

**Tech Stack:** Bash, `jq`(훅 스크립트의 JSON 파싱 전용 — `bin/evolve` 자체는 여전히 git/diff/cp만 씀).

## Global Constraints

- `bin/evolve` 코어 로직(snapshot/diff)은 그대로 유지, 새 서브커맨드도 bash/git/diff/cp만 쓴다 — 외부 의존성 추가 금지는 CLI 코어에 한해 유지.
- 훅 스크립트(`bin/hooks/*.sh`)는 stdin JSON 파싱이 필요해 `jq`를 쓴다 — 이건 훅 스크립트 전용 예외로, 코드 리뷰에서 지적하지 말 것. `jq`가 없는 환경에서는 조용히 no-op(exit 0)한다.
- 추적 대상은 `~/.agents/skills/<name>/` 밑의, 이름에 `:`가 없는 스킬만. `plugin:skill` 형태는 훅 스크립트 단에서 걸러내고 `bin/evolve`에 전달하지 않는다.
- `evolve pending`/`evolve diff`/`evolve snapshot`은 항상 exit 0으로 끝난다(델타 유무와 무관) — 이미 있는 `evolve diff`의 계약을 그대로 따른다. 델타 유무는 stdout 출력이 비어있는지로만 판단한다.
- `evolution/lessons/`, `evolution/patterns/`로의 자동 승격은 여전히 금지 — 이 확장에서도 손대지 않는다.
- `~/.claude/settings.json`은 이 프로젝트 저장소 밖의, 이 머신의 모든 Claude Code 세션에 영향을 주는 공유 설정 파일이다. 기존에 이미 `PostToolUse`(matcher `*`)와 `Stop`(matcher 없음, 전체 매치) 훅이 등록되어 있다 — 이번 확장은 기존 훅을 대체/수정하지 않고 새 matcher 그룹을 추가하는 방식으로만 확장한다.
- Stop hook의 block 판단은 세션당 최대 1회로 제한한다 (`stop_hook_active`가 `true`면 다시 block하지 않는다) — 델타 기록은 best-effort이지 세션 종료를 볼모로 잡을 정도로 중요하지 않다.

---

### Task 1: `bin/evolve`에 `track`/`pending`/`clear-session` 서브커맨드 추가

**Files:**
- Modify: `bin/evolve`
- Modify: `tests/test-evolve.sh`

**Interfaces:**
- Produces: `evolve track <session_id> <skill-dir>` — `<skill-dir>`에 baseline 없으면 자동 snapshot(내부적으로 기존 `cmd_snapshot` 재사용), `evolution/.state/.sessions/<session_id>-touched.txt`에 `<skill-dir>`의 basename을 dedup 추가. exit 0.
- Produces: `evolve pending <session_id>` — 세션 파일에 나열된 각 스킬 이름 중, `~/.agents/skills/<name>`가 실존하고 현재 diff가 비어있지 않은 이름만 한 줄씩 stdout 출력. 파일 없거나 다 비어있으면 아무 출력 없이 exit 0.
- Produces: `evolve clear-session <session_id>` — `evolution/.state/.sessions/<session_id>-touched.txt` 삭제. 파일 없어도 에러 없이 exit 0.
- Consumes: 기존 `cmd_snapshot(skill_dir)`, `cmd_diff(skill_dir)`, `resolve_dir(dir)` (모두 `bin/evolve`에 이미 정의돼 있음, 시그니처 그대로 재사용).

- [ ] **Step 1: 현재 `bin/evolve` 확인**

```bash
cat bin/evolve
```

파일 끝부분이 다음과 같이 끝나는 걸 확인한다 (이 정확한 텍스트를 기준으로 아래 수정을 적용한다):

```bash
case "${1:-}" in
  snapshot) shift; [ $# -eq 1 ] || usage; cmd_snapshot "$1" ;;
  diff) shift; [ $# -eq 1 ] || usage; cmd_diff "$1" ;;
  *) usage ;;
esac
```

- [ ] **Step 2: `SESSIONS_DIR` 변수와 새 함수 3개 추가**

`STATE_DIR="$EVOLUTION_DIR/.state"` 줄 바로 다음 줄에 추가:

```bash
SESSIONS_DIR="$STATE_DIR/.sessions"
```

`usage()` 함수의 메시지를 다음으로 교체:

```bash
usage() {
  echo "Usage: evolve snapshot <skill-dir> | evolve diff <skill-dir> | evolve track <session-id> <skill-dir> | evolve pending <session-id> | evolve clear-session <session-id>" >&2
  exit 1
}
```

`cmd_diff` 함수 정의가 끝나는 `}` 바로 다음(즉 `case "${1:-}" in` 이전)에 아래 세 함수를 추가:

```bash
cmd_track() {
  local session_id="$1" skill_dir skill_name touched_file state_file
  skill_dir="$(resolve_dir "$2")"
  skill_name="$(basename "$skill_dir")"
  mkdir -p "$SESSIONS_DIR"
  touched_file="$SESSIONS_DIR/${session_id}-touched.txt"
  touch "$touched_file"

  if ! grep -qxF "$skill_name" "$touched_file" 2>/dev/null; then
    echo "$skill_name" >> "$touched_file"
  fi

  state_file="$STATE_DIR/${skill_name}.txt"
  if [ ! -f "$state_file" ]; then
    cmd_snapshot "$skill_dir" > /dev/null
  fi
}

cmd_pending() {
  local session_id="$1" touched_file
  touched_file="$SESSIONS_DIR/${session_id}-touched.txt"
  [ -f "$touched_file" ] || return 0

  local skill_name dir out
  while IFS= read -r skill_name; do
    [ -n "$skill_name" ] || continue
    dir="$HOME/.agents/skills/$skill_name"
    [ -d "$dir" ] || continue
    out="$(cmd_diff "$dir" 2>/dev/null)"
    [ -n "$out" ] && echo "$skill_name"
  done < "$touched_file"
  return 0
}

cmd_clear_session() {
  local session_id="$1"
  rm -f "$SESSIONS_DIR/${session_id}-touched.txt"
}
```

`case "${1:-}" in` 블록을 다음으로 교체:

```bash
case "${1:-}" in
  snapshot) shift; [ $# -eq 1 ] || usage; cmd_snapshot "$1" ;;
  diff) shift; [ $# -eq 1 ] || usage; cmd_diff "$1" ;;
  track) shift; [ $# -eq 2 ] || usage; cmd_track "$1" "$2" ;;
  pending) shift; [ $# -eq 1 ] || usage; cmd_pending "$1" ;;
  clear-session) shift; [ $# -eq 1 ] || usage; cmd_clear_session "$1" ;;
  *) usage ;;
esac
```

- [ ] **Step 3: `.gitignore`에 세션 상태 확인** (`evolution/.state/`가 이미 통째로 ignore 대상이므로 `.sessions/`는 자동으로 커버됨 — 확인만)

```bash
cat .gitignore
```

`evolution/.state/` 줄이 있는지 확인. 있으면 이 스텝은 그대로 통과, 수정 불필요.

- [ ] **Step 4: 테스트 추가**

`tests/test-evolve.sh`의 `cleanup()` 함수에 세션 관련 정리 추가 — 기존 `cleanup()` 함수 본문 맨 끝(마지막 `rm` 줄 다음, `}` 이전)에 추가:

```bash
  rm -rf "$REPO_ROOT/evolution/.state/.sessions"
```

`echo "all tests passed"` 줄 바로 앞에 아래 테스트 케이스들을 추가:

```bash
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
```

- [ ] **Step 5: 테스트 실행해 통과 확인**

Run: `./tests/test-evolve.sh`
Expected: 11개 `PASS:` 라인 (기존 6 + 신규 5) + `all tests passed`, exit code 0.

- [ ] **Step 6: Commit**

```bash
git add bin/evolve tests/test-evolve.sh
git commit -m "feat: add evolve track/pending/clear-session subcommands for session-scoped tracking"
```

---

### Task 2: 훅 스크립트 `evolve-track.sh` / `evolve-autorecord.sh`

**Files:**
- Create: `bin/hooks/evolve-track.sh`
- Create: `bin/hooks/evolve-autorecord.sh`
- Create: `tests/test-hooks.sh`

**Interfaces:**
- Consumes: `evolve track <session_id> <skill-dir>`, `evolve pending <session_id>`, `evolve clear-session <session_id>` (Task 1) — 절대경로 `/Users/deratio/skills/bin/evolve`로 호출.
- Produces: stdin으로 Claude Code 훅 JSON을 받아 stdout으로 훅 프로토콜에 맞는 JSON을 출력하는 두 실행 가능한 스크립트. `PostToolUse`/`Stop` 훅 등록의 `command`로 그대로 쓸 수 있는 형태.

- [ ] **Step 1: Claude Code Stop hook의 정확한 block 출력 스키마 확인**

`WebFetch`로 `https://code.claude.com/docs/en/hooks`를 열어 `Stop` 이벤트의 JSON 출력 스키마를 확인해라. 확인할 것: 최상위 키가 `hookSpecificOutput`인지, 그 안에 `decision`(값 `"block"`)과 `reason`(문자열)이 있는지, `hookEventName` 같은 추가 필드가 필요한지. 아래 Step 3의 스크립트는 다음 스키마를 가정하고 작성되어 있다:

```json
{"hookSpecificOutput": {"hookEventName": "Stop", "decision": "block", "reason": "..."}}
```

문서를 확인한 결과 이 스키마가 맞으면 그대로 진행. 다르면(필드명이 다르거나 구조가 다르면) Step 3의 `evolve-autorecord.sh`에서 `jq -n` 호출부만 실제 스키마에 맞게 고쳐라 — 나머지 로직(pending 확인, block 여부 판단)은 그대로 둔다. 뭘 확인했고 어떻게 맞췄는지(또는 그대로 뒀는지) 최종 보고서에 적어라.

- [ ] **Step 2: `bin/hooks/evolve-track.sh` 작성**

```bash
mkdir -p bin/hooks
```

```bash
#!/usr/bin/env bash
set -uo pipefail

EVOLVE="/Users/deratio/skills/bin/evolve"
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
```

```bash
chmod +x bin/hooks/evolve-track.sh
```

- [ ] **Step 3: `bin/hooks/evolve-autorecord.sh` 작성**

```bash
#!/usr/bin/env bash
set -uo pipefail

EVOLVE="/Users/deratio/skills/bin/evolve"
[ -x "$EVOLVE" ] || { echo '{}'; exit 0; }
command -v jq >/dev/null 2>&1 || { echo '{}'; exit 0; }

input="$(cat)"
session_id="$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null)"
stop_hook_active="$(printf '%s' "$input" | jq -r '.stop_hook_active // false' 2>/dev/null)"

[ -n "$session_id" ] || { echo '{}'; exit 0; }

if [ "$stop_hook_active" = "true" ]; then
  pending="$("$EVOLVE" pending "$session_id" 2>/dev/null || true)"
  if [ -z "$pending" ]; then
    "$EVOLVE" clear-session "$session_id" 2>/dev/null || true
  fi
  echo '{}'
  exit 0
fi

pending="$("$EVOLVE" pending "$session_id" 2>/dev/null || true)"
[ -n "$pending" ] || { echo '{}'; exit 0; }

skill_list="$(printf '%s' "$pending" | paste -sd ', ' -)"

reason="다음 스킬(들)이 baseline 대비 변경됨: ${skill_list}

각 스킬에 대해 evolution record를 작성하라. 사람에게 아무것도 묻지 마라 (AskUserQuestion을 쓰지 마라) — 이 세션의 대화 내용에서 무엇을, 왜 바꿨는지 직접 추론해서 채워라. context/evidence를 세션에서 합리적으로 추론할 수 없으면 \"세션 로그 기반 자동 추론 실패 — 검토 필요\"라고 쓰고 넘어가라.

각 스킬마다 /Users/deratio/skills/evolution/records/<스킬명>/<YYYY-MM-DD>-<slug>.md 에 아래 스키마로 저장:

skill: <스킬 이름>
source: auto (session-end hook)
baseline: <evolution/.state/<스킬명>.txt 의 ref 값>
final: working tree
context: <세션 맥락 기반 추론>
delta: <diff 요약>
evidence: <있으면>
candidate_lessons: <있으면>
promotion: pending

record 작성 후 각 스킬에 대해 반드시 실행: /Users/deratio/skills/bin/evolve snapshot ~/.agents/skills/<스킬명>
(이걸 안 하면 다음 종료 시도에서 같은 델타가 또 감지된다.)

다 끝나면 정상적으로 응답을 마쳐라."

jq -n --arg reason "$reason" '{"hookSpecificOutput": {"hookEventName": "Stop", "decision": "block", "reason": $reason}}'
```

```bash
chmod +x bin/hooks/evolve-autorecord.sh
```

- [ ] **Step 4: 훅 스크립트용 스모크 테스트 작성**

```bash
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
OUT="$(echo "{\"session_id\":\"$SESSION_ID\",\"stop_hook_active\":false}" | "$AUTORECORD_HOOK")"
echo "$OUT" | grep -q '"decision":"block"' && fail "should not block with no pending skills, got: $OUT" || pass "evolve-autorecord.sh does not block with no pending skills"

# --- evolve-autorecord.sh: pending change -> blocks with reason mentioning the skill ---
"$EVOLVE" track "$SESSION_ID" "$HOOK_SKILL" >/dev/null
echo "v2" >> "$HOOK_SKILL/SKILL.md"
OUT="$(echo "{\"session_id\":\"$SESSION_ID\",\"stop_hook_active\":false}" | "$AUTORECORD_HOOK")"
echo "$OUT" | grep -q '"decision":"block"' && echo "$OUT" | grep -q "hook-skill" && pass "evolve-autorecord.sh blocks and names the changed skill" || fail "expected a block mentioning hook-skill, got: $OUT"

# --- evolve-autorecord.sh: stop_hook_active=true does not block again ---
OUT="$(echo "{\"session_id\":\"$SESSION_ID\",\"stop_hook_active\":true}" | "$AUTORECORD_HOOK")"
echo "$OUT" | grep -q '"decision":"block"' && fail "should never block when stop_hook_active=true, got: $OUT" || pass "evolve-autorecord.sh never blocks on stop_hook_active=true"

echo "all hook tests passed"
```

```bash
chmod +x tests/test-hooks.sh
```

- [ ] **Step 5: 테스트 실행해 통과 확인**

Run: `./tests/test-hooks.sh`
Expected: 6개 `PASS:` 라인 + `all hook tests passed`, exit code 0.

- [ ] **Step 6: Commit**

```bash
git add bin/hooks/evolve-track.sh bin/hooks/evolve-autorecord.sh tests/test-hooks.sh
git commit -m "feat: add PostToolUse/Stop hook scripts for automatic skill evolution tracking"
```

---

### Task 3: `~/.claude/settings.json`에 훅 등록 + 검증

**Files:**
- Modify: `~/.claude/settings.json` (이 저장소 밖, user-level 공유 설정)

**Interfaces:**
- Consumes: `bin/hooks/evolve-track.sh` (PostToolUse), `bin/hooks/evolve-autorecord.sh` (Stop) — Task 2 산출물, 절대경로로 등록.

- [ ] **Step 1: `update-config` 스킬로 훅 등록**

`~/.claude/settings.json`은 이 저장소 밖에 있고 이 머신의 모든 Claude Code 세션에 영향을 준다. 이미 `PostToolUse`(matcher `*`)와 `Stop`(matcher 없음)에 다른 훅이 등록돼 있다 — 절대 직접 JSON을 통째로 다시 쓰지 말고, `Skill` 툴로 `update-config` 스킬을 호출해 다음 두 훅을 **기존 항목을 건드리지 않고 추가로** 등록해라:

1. `PostToolUse` 이벤트에 `matcher: "Skill"`인 새 항목 추가, command: `/Users/deratio/skills/bin/hooks/evolve-track.sh`
2. `Stop` 이벤트에 (matcher 없이, 기존 Stop 항목과 별개의 새 그룹으로) command: `/Users/deratio/skills/bin/hooks/evolve-autorecord.sh` 추가

`update-config` 스킬을 호출할 때 이 요구사항을 그대로 전달해라: "PostToolUse에 matcher Skill로 새 훅 그룹 추가, command는 /Users/deratio/skills/bin/hooks/evolve-track.sh. Stop에 새 훅 그룹 추가, command는 /Users/deratio/skills/bin/hooks/evolve-autorecord.sh. 기존 훅 항목은 절대 수정/삭제하지 말 것."

- [ ] **Step 2: JSON 유효성 및 기존 훅 보존 확인**

```bash
python3 -c "
import json
with open('/Users/deratio/.claude/settings.json') as f:
    d = json.load(f)
post = d.get('hooks', {}).get('PostToolUse', [])
stop = d.get('hooks', {}).get('Stop', [])
print('PostToolUse groups:', len(post), [g.get('matcher') for g in post])
print('Stop groups:', len(stop), [g.get('matcher') for g in stop])
"
```

Expected: `PostToolUse groups`에 기존 `*` 매처와 새 `Skill` 매처가 둘 다 있어야 한다 (2개 이상). `Stop groups`에 기존 그룹 + 새 그룹이 둘 다 있어야 한다 (2개 이상). 둘 중 하나라도 기존 매처가 사라졌으면 STOP하고 BLOCKED로 보고해라 — 되돌릴 수 없이 다른 시스템의 훅을 지운 것이므로 컨트롤러의 판단이 필요하다.

- [ ] **Step 3: 새로 등록한 훅 command가 정확한 절대경로를 가리키는지 확인**

```bash
python3 -c "
import json
with open('/Users/deratio/.claude/settings.json') as f:
    d = json.load(f)
for ev, want in [('PostToolUse', 'evolve-track.sh'), ('Stop', 'evolve-autorecord.sh')]:
    groups = d.get('hooks', {}).get(ev, [])
    found = any(want in h.get('command', '') for g in groups for h in g.get('hooks', []))
    print(ev, want, 'FOUND' if found else 'MISSING')
"
```

Expected: 둘 다 `FOUND`.

- [ ] **Step 4: 훅 스크립트 자체가 실행 가능한 상태인지 마지막 확인**

```bash
ls -la /Users/deratio/skills/bin/hooks/evolve-track.sh /Users/deratio/skills/bin/hooks/evolve-autorecord.sh
```

Expected: 둘 다 `-rwxr-xr-x` (실행 비트 있음). 없으면 `chmod +x` 실행.

- [ ] **Step 5: 알려진 한계 보고**

이 등록은 **다음에 새로 시작하는 Claude Code 세션부터** 적용된다 — 지금 이 작업을 하고 있는 세션은 시작 시점에 이미 훅 설정을 로드했으므로, 이 세션 안에서는 진짜 end-to-end(실제 Skill 호출 → PostToolUse 발동 → 세션 종료 → Stop 훅 발동)를 검증할 수 없다. 보고서에 "다음 새 세션에서 아무 개인 스킬이나 하나 호출한 뒤 정상 종료를 시도하면, 델타가 있을 경우 자동으로 한 번 더 턴이 돌면서 record가 쓰여야 한다"는 사실을 명시해라. 이건 실패가 아니라 이 태스크의 정상적인 한계다.

이 태스크는 git commit이 없다 (`~/.claude/settings.json`은 이 저장소 밖에 있음).

- [ ] **Step 6: 최종 보고**

Task 2에서 확인한 Stop hook JSON 스키마와 실제 등록 결과를, 그리고 Step 5의 한계 안내를 보고서에 포함해라.

---

## Self-Review 결과

- **Spec coverage:** 훅 아키텍처 전체 흐름(track → pending → block → 자동 기록 → snapshot 리셋)이 Task 1(서브커맨드) + Task 2(훅 스크립트) + Task 3(등록)로 모두 커버됨. record 스키마의 `source` 필드는 Task 2의 `evolve-autorecord.sh`의 `reason` 텍스트에 명시. "구현 전 검증 필요" 섹션(`tool_input.skill` 필드명)은 이번 계획을 쓰기 직전 세션 트랜스크립트를 직접 읽어 `input.skill`로 확정 확인함 — Task 2/3 코드에 그대로 반영, 더 이상 불확실성 없음. Stop hook의 정확한 JSON 출력 스키마만 남은 불확실성이라 Task 2 Step 1에서 문서 확인을 명시적 단계로 뺌.
- **Placeholder scan:** TBD/TODO 없음. 모든 코드 블록은 실행 가능한 전체 내용.
- **Type/interface consistency:** `evolve track <session_id> <skill-dir>`, `evolve pending <session_id>`, `evolve clear-session <session_id>` 시그니처가 Task 1(구현)과 Task 2(훅 스크립트에서 호출)에서 동일. 훅 스크립트가 참조하는 `bin/evolve` 절대경로(`/Users/deratio/skills/bin/evolve`)와 Task 3에서 등록하는 훅 command의 절대경로가 일치.
