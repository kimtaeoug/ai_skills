#!/usr/bin/env bash
set -uo pipefail

# NOTE on schema: an earlier pass here relied on a WebFetch summary and got this wrong. It claimed
# the block schema was nested under hookSpecificOutput.permissionDecision/permissionDecisionReason
# and that stop_hook_active didn't exist. Both claims were wrong -- that WebFetch summary had
# conflated the PreToolUse "deny a tool call" example with the unrelated Stop section on the same
# long docs page. Verified directly against the raw markdown via
# `curl https://code.claude.com/docs/en/hooks.md`, reading the literal "### Stop" section:
#
#   #### Stop input
#   In addition to the common input fields, Stop hooks receive `stop_hook_active`,
#   `last_assistant_message`, `background_tasks`, and `session_crons`. The `stop_hook_active`
#   field is `true` when Claude Code is already continuing as a result of a stop hook. Check this
#   value or process the transcript to avoid blocking on a condition that will never resolve.
#   Claude Code overrides the hook and ends the turn after 8 consecutive blocks.
#
#   #### Stop decision control
#   | decision | "block" prevents Claude from stopping. Omit to allow Claude to stop |
#   | reason   | Required when decision is "block". Tells Claude why it should continue |
#
# So the correct schema is top-level {"decision": "block", "reason": "..."}, and stop_hook_active
# is real and used below to avoid re-blocking on the hook's own continuation turn.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EVOLVE="$SCRIPT_DIR/../evolve"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
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

각 스킬마다 ${REPO_ROOT}/evolution/records/<스킬명>/<YYYY-MM-DD>-<slug>.md 에 아래 스키마로 저장:

skill: <스킬 이름>
source: auto (session-end hook)
baseline: <evolution/.state/<스킬명>.txt 의 ref 값>
final: working tree
context: <세션 맥락 기반 추론>
delta: <diff 요약>
evidence: <있으면>
candidate_lessons: <있으면>
promotion: pending

record 작성 후 각 스킬에 대해 반드시 실행: ${REPO_ROOT}/bin/evolve snapshot ~/.agents/skills/<스킬명>
(이걸 안 하면 다음 종료 시도에서 같은 델타가 또 감지된다.)

다 끝나면 정상적으로 응답을 마쳐라."

jq -n --arg reason "$reason" '{"decision": "block", "reason": $reason}'
