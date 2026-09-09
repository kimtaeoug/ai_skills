# task-orchestrator v2

v2는 task-orchestrator 워크플로를 계약, 예산, 승인, 증거가 있는 로컬 상태 그래프로 실행하기 위한
opt-in 런타임이다. 현재 구현은 전역 훅이나 네이티브 모델/인간 신원 어댑터를 설치하지 않는다.
지원되지 않는 실행은 성공으로 가정하지 않고 `awaiting_data`에 둔다.

상세 런타임 계약: [runtime-v2.md](../../.claude/skills/task-orchestrator/references/runtime-v2.md)

## 전역 설치

```bash
bin/install-task-orchestrator
```

`task-orchestrator`와 직접 관리하는 `research-team`, `archon-adversarial-dev`,
`test-agent-team`을 `~/.agents/skills`, `~/.claude/skills`, `~/.codex/skills`에
연결한다. 기존 파일이나 다른 대상을 가리키는 링크는 덮어쓰지 않는다.

## 빠른 사용

```bash
python3 .claude/skills/task-orchestrator/scripts/graph_runtime.py defaults
python3 .claude/skills/task-orchestrator/scripts/graph_runtime.py init --workspace /repo --contract contract.json
python3 .claude/skills/task-orchestrator/scripts/graph_runtime.py init --workspace /repo --contract contract.json --policy policy.json
python3 .claude/skills/task-orchestrator/scripts/graph_runtime.py show --workspace /repo --workflow WF-0001
python3 .claude/skills/task-orchestrator/scripts/graph_runtime.py resume --workspace /repo --workflow WF-0001
python3 .claude/skills/task-orchestrator/scripts/graph_runtime.py report --workspace /repo --workflow WF-0001
```

CLI는 `defaults`, `init`, `show`, `resume`, `report`만 지원한다. 실행, 승인, 정책 조정, loop, reconcile은
trusted Python host가 `graph_runtime.Runtime` API로 호출한다.

## 기본값과 부분 override

`defaults`로 현재 기본 정책을 확인한다. `init --policy policy.json`은 필요한 값만 담은 JSON 부분 override를
받는다.

```json
{
  "max_tokens": 200000,
  "retry": {
    "max_attempts": 2
  }
}
```

조정 가능: workflow/stage/tool/approval timeout, retry, breaker, loop 수, tool retry 수, token/cost 상한.
`unknown_usage_policy: awaiting_data`와 `approval_default: deny`는 안전 불변식이라 바꿀 수 없다. 알 수 없는
사용량은 0이 아니고, 자유문 승인이나 해시만으로 만든 승인은 유효하지 않다.

## 실행 중 튜닝

실사용 중 값 조정은 워크플로 로컬 버전 변경이다.

1. 실행 중 호출과 예약이 없는 HIL 경계에서 `Runtime.request_tuning(workflow_id, revision, patch, reason)`을 호출한다.
2. 런타임이 patch와 계약을 검증하고 `kind: policy` 승인 요청을 만든다.
3. 등록된 authority가 요청을 전달하고 `Runtime.approve(...)`에서 검증된 approver를 돌려줘야 적용된다.
4. 적용되면 `policy_version`이 증가하고 `policy_history`에 이전 값, 새 값, 이유, 승인 근거가 남는다.

이미 소비한 실행시간, 토큰, 비용, 시도, loop 카운터, 미정산 예약은 유지된다. 낮춘 한도가 누적 사용량보다
작으면 신규 실행이 차단된다. 정책 버전 변경은 기존 action approval을 무효화한다.

## HIL 대기

HIL 대기는 authority가 실제로 요청을 전달한 뒤 인간 응답만 기다리는 구간만 실행 시간에서 제외한다.
질문 작성, 응답 검토, 도구 실행, 백오프, 일반 `awaiting_data`는 제외 시간이 아니다. 카운터와 HIL 구간은
상태에 저장되어 `resume` 후에도 복원된다.

## Trusted host 계약

v2 실행은 trusted Python host가 등록한 bounded adapter와 authority만 사용한다.

Adapter 필수 성격:

- 노드와 같은 `actor`
- `tier` 1/2/3, `allowed(inputs)`, `bounded: true`, `cancellable: true`
- `max_tokens`, `max_cost_microusd`, `meter_id`, `price_version`
- `invoke(inputs, context)`와, 미확정 결과 조회가 필요하면 `reconcile(attempt, context)`
- 재시도 대상이면 `idempotent: true`

Authority 필수 성격:

- `deliver(request) -> True`로 전달된 요청만 HIL 대기 시계를 시작한다.
- `verify(proof, request) -> principal_id`가 계약의 approver에 포함되어야 승인된다.
- approval은 action digest, version binding, 만료, 단일 사용 조건에 결속된다.

Tier3 액션은 결제, 삭제, 발송, 배포, 권한 변경 같은 고위험 작업이다. 정확한 액션과 인자에 묶인 일회성
승인 없이 실행하지 않는다. 테스트용 fake authority 예시는 실제 인증이 아니다.

## 스키마와 receipt

`runtime_contracts.py`는 `COMMON_SCHEMAS`와 `STAGE_SCHEMAS`를 제공한다. 이 계약은 `graph_runtime`의 작은
closed JSON-schema vocabulary로 검증된다. unknown field나 잘못된 타입은 거절된다.

성공한 실행은 artifact, evidence, usage, actor, version binding, code fingerprint를 receipt로 커밋한다.
receipt 전 파일 저장만으로 완료가 아니다. 실패, 미확정 사용량, 예약, retry/fallback/loop 카운터는 보존된다.

## v1 위치

기존 `task_state.py` 기반 v1은 legacy/advisory다. v2 안전 계약을 집행하는 compliant enforceable mode로
주장하지 않는다. v2로 운영하려면 `graph_runtime.py` 계약, registered adapter, verified authority가 필요하다.
