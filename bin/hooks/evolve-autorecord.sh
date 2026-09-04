#!/usr/bin/env bash
set -uo pipefail

# NOTE on schema: the brief assumed a Stop-block schema of
#   {"hookSpecificOutput": {"hookEventName": "Stop", "decision": "block", "reason": "..."}}
# WebFetch verification against https://code.claude.com/docs/en/hooks (2026-09-04) showed the
# current schema uses "permissionDecision"/"permissionDecisionReason" instead of "decision"/"reason":
#   {"hookSpecificOutput": {"hookEventName": "Stop", "permissionDecision": "deny", "permissionDecisionReason": "..."}}
# It also showed the Stop input JSON has no "stop_hook_active" field (that's not part of the
# current schema), so there is no signal to detect "this is a repeat call after a block". Instead
# we rely on `evolve pending` going empty once the instructed `evolve snapshot` calls land — if
# Claude doesn't snapshot, blocking again on the next Stop is correct (the delta is still pending).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EVOLVE="$SCRIPT_DIR/../evolve"
[ -x "$EVOLVE" ] || { echo '{}'; exit 0; }
command -v jq >/dev/null 2>&1 || { echo '{}'; exit 0; }

input="$(cat)"
session_id="$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null)"

[ -n "$session_id" ] || { echo '{}'; exit 0; }

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

jq -n --arg reason "$reason" '{"hookSpecificOutput": {"hookEventName": "Stop", "permissionDecision": "deny", "permissionDecisionReason": $reason}}'
