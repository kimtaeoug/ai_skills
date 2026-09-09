# task-orchestrator v2 runtime

v2는 워크플로별 계약, 예산, 승인, 증거를 SQLite 상태로 묶는 opt-in 실행 런타임이다.
전역 훅이나 네이티브 모델/인간 신원 어댑터는 설치하지 않는다. 연결되지 않은 실행은 성공으로
가정하지 않고 `awaiting_data`에서 멈춘다.

## CLI

CLI는 조회와 부트스트랩만 담당한다.

```bash
python3 .claude/skills/task-orchestrator/scripts/graph_runtime.py defaults
python3 .claude/skills/task-orchestrator/scripts/graph_runtime.py init --workspace /repo --contract contract.json
python3 .claude/skills/task-orchestrator/scripts/graph_runtime.py init --workspace /repo --contract contract.json --policy policy.json
python3 .claude/skills/task-orchestrator/scripts/graph_runtime.py show --workspace /repo --workflow WF-0001
python3 .claude/skills/task-orchestrator/scripts/graph_runtime.py resume --workspace /repo --workflow WF-0001
python3 .claude/skills/task-orchestrator/scripts/graph_runtime.py report --workspace /repo --workflow WF-0001
```

`defaults`는 현재 기본 정책 JSON을 출력한다. `init --policy`는 부분 override JSON을 받는다.
실행, 승인, 정책 조정, 루프, reconcile은 CLI 명령이 아니라 trusted Python host가 `Runtime`
API로 호출한다.

## 최소 계약 작성 예

아래 Python은 스킬의 `scripts` 디렉터리를 import 경로로 설정한 trusted host에서 실행한다.
출력 JSON을 `contract.json`으로 저장하면 위 `init`으로 검증·등록할 수 있다. 승인자와 도구 ID는
실제 host에 등록한 값으로 정한다. 등록 자체는 실행 승인이 아니다.

```python
import copy
import json
from runtime_contracts import STAGE_SCHEMAS

schema = copy.deepcopy(STAGE_SCHEMAS['code_test'])
contract = {
    'title': '기존 테스트 실행',
    'approvers': ['workspace-owner'],
    'nodes': [{
        'node_id': 'TEST-01', 'kind': 'code_test',
        'actor': {'kind': 'external_system', 'principal_id': 'local-test', 'role': 'tester'},
        'input_schema': schema['input'], 'output_schema': schema['output'],
        'tool_routes': ['registered-test-runner'],
        'required_evidence': [
            {'validator': 'json_success', 'field': 'test_results_ref'},
            {'validator': 'nonempty_artifact', 'field': 'log_ref'},
            {'validator': 'equals', 'field': 'exit_code', 'value': 0},
        ],
    }],
    'edges': [],
}
print(json.dumps(contract, ensure_ascii=False, indent=2))
```

기본 stage 필수 필드·타입은 제거/약화할 수 없다. HIL 계약에서 추가 필드·검증 조건은 붙일 수 있다.
`json_success` 참조 파일은 `exit_code:0`, 양의 정수 `passed`, `failed:0`, `fatal_errors:0`인 JSON이다.
스크린샷 존재만으로 화면 검사가 통과하지 않으며, 실제 상호작용·시각 판정 결과가 필요하다.

| 노드 | 필수 증거 검사 |
| --- | --- |
| develop | `diff_ref`: nonempty_artifact |
| code_test | `test_results_ref`: json_success, `log_ref`: nonempty_artifact, `exit_code`: equals 0 |
| screen_test | `interaction_results_ref`: json_success, `screenshots_ref`와 `trace_ref`: nonempty_artifact |
| visual_review | `verdicts_ref`: json_success |
| research | `report_ref`와 `claim_verdicts_ref`: nonempty_artifact; 필수 조사 status는 answered |
| report | `report_ref`: nonempty_artifact |

다른 노드도 비어 있지 않은 `required_evidence`를 HIL에서 지정한다. `equals`는 신뢰된 어댑터의
구조화 결과 비교이며, 모델이 쓴 “pass” 문자열을 실제 테스트 결과로 인증하는 기능은 아니다.

## 조정 가능한 기본값

기본값은 `runtime_policy.DEFAULTS` 한 곳에 있다.

```json
{
  "workflow_timeout_s": 3600,
  "stage_timeout_s": 900,
  "tool_timeout_s": 120,
  "approval_timeout_s": 600,
  "retry": {
    "max_attempts": 3,
    "base_delay_s": 1,
    "cap_delay_s": 30,
    "max_elapsed_s": 180
  },
  "breaker": {
    "failure_threshold": 3,
    "cooldown_s": 60
  },
  "max_loop_iterations": 10,
  "max_tool_retries": 20,
  "max_tokens": 100000,
  "max_cost_microusd": 5000000,
  "unknown_usage_policy": "awaiting_data",
  "approval_default": "deny"
}
```

부분 override 예:

```json
{
  "max_tokens": 200000,
  "retry": {
    "max_attempts": 2
  }
}
```

시간, 재시도, breaker, 반복, 토큰, 비용 숫자는 조정 가능하다. 다음 안전 불변식은 조정할 수 없다.

- `unknown_usage_policy`는 항상 `awaiting_data`다. 알 수 없는 사용량은 0이 아니다.
- `approval_default`는 항상 `deny`다. 승인 누락, 만료, 위조는 승인으로 처리하지 않는다.
- `tool_timeout_s <= stage_timeout_s <= workflow_timeout_s`와 `retry.max_elapsed_s <= stage_timeout_s`를 지킨다.

## 실행 중 튜닝

워크플로 실행 중 조정은 워크플로 로컬, 버전 관리, 승인 기반이다.

1. host가 실행 중 호출과 예약이 없는 HIL 경계에서 `Runtime.request_tuning(workflow_id, revision, patch, reason)`을 호출한다.
2. 런타임은 patch를 검증하고 `kind: policy` 승인 요청을 만든다.
3. authority가 요청을 사용자에게 전달하고, `Runtime.approve(workflow_id, revision, proof)`가 검증된 principal을 돌려받아야 적용된다.
4. 적용 시 `policy_version`이 증가하고 `policy_history`에 이전 값, 새 값, 이유, 승인자를 저장한다.

이미 사용한 시간, 토큰, 비용, 시도, 반복 횟수, 미정산 예약은 초기화하지 않는다. 낮춘 한도가 누적 사용량보다
작으면 다음 검사에서 새 실행을 막거나 `budget_exhausted`로 끝난다. 정책 버전 변경은 대기 중 action approval을
무효화한다.

## HIL 시간

HIL 대기는 authority가 요청을 실제로 전달한 뒤 인간 응답만 기다리는 구간만 실행 시계에서 제외한다.
질문 작성, 응답 검토, 도구 실행, 백오프, 일반 `awaiting_data`, 도구 응답 대기는 제외 시간이 아니다.
구간은 `clock.hil_wait_intervals`와 `waiting_since`에 저장되며 재개 후에도 누적 실행시간을 복원한다.
기록 없는 중단이나 fake HIL 표식은 실행시간을 돌려주지 않는다.

예: 실행 600초 + HIL 대기 7200초이면 실행 예산은 3000초 남는다. 하지만 기본 승인 만료 600초는
별개이므로 그 승인은 거부된다. 장시간 응답이 예상되면 사전에 해당 워크플로의
`approval_timeout_s`를 충분히 늘려 승인해야 한다. HIL 면제와 승인 무기한 유효는 다르다.

## Trusted Python host API

`graph_runtime.Runtime(workspace, adapters=None, authority=None, now=None)`가 실행 권위다. JSON 입력만으로
어댑터나 신원을 등록할 수 없다. 로컬 OS 계정과 trusted host 코드가 보안 경계이며, Python sandbox가 아니다.

주요 API:

- `create(contract, policy=None)`, `show(workflow_id)`, `resume(workflow_id)`, `report(workflow_id)`
- `request_tuning(workflow_id, revision, patch, reason)`
- `approve(workflow_id, revision, proof)`, `deny(workflow_id, revision, proof)`
- `execute(workflow_id, node_id, inputs)`
- `reconcile(workflow_id, node_id)`
- `loop(workflow_id, edge_id, reason)`

승인 authority 계약:

- `deliver(request) -> True`일 때만 HIL 대기 시계를 시작할 수 있다.
- `verify(proof, request) -> principal_id`가 계약의 `approvers`에 포함되어야 승인된다.
- request의 `action_digest`, 버전 결속, 만료시간, 단일 사용 조건이 현재 상태와 맞아야 한다.

어댑터 계약:

- `actor`는 노드 actor와 같아야 한다.
- `tier`는 `1`, `2`, `3` 중 하나다. Tier3는 액션에 결속된 일회성 승인 없이는 실행되지 않는다.
- `allowed(inputs) -> True`가 필요하다. 모르는 도구나 불투명한 부작용은 자동 허용하지 않는다.
- `bounded`와 `cancellable`은 `True`여야 한다.
- `max_tokens`, `max_cost_microusd`, `meter_id`, `price_version`이 있어야 사용량을 예약한다.
- `invoke(inputs, context)`는 `{outputs, usage}` 또는 `{error, usage}` 형태의 dict를 돌려준다.
- 재시도에는 `idempotent: True`가 필요하다.
- 자동 재시도/회로 장애 집계는 등록된 일시 장애 코드 `timeout`, `service_unavailable`,
  `rate_limit`, `connection_error`에 한한다. 인증 거부나 임의 오류 문자열은 자동 재시도하지 않는다.
- 결과나 사용량이 미확정이면 optional `reconcile(attempt, context)`로 조회할 수 있다. 원래 intent를 재실행하지 않는다.

`deliver`, `verify`, `allowed`, `reconcile` 구현은 신뢰된 host 경계다. 신원·허용 범위·경로 정규화·
상한·실제 계측을 보장하는 구현만 등록한다. `reconcile`은 비청구 읽기 전용 조회여야 한다.
네트워크/모델 비용이 드는 조회를 이 콜백으로 숨길 수 없다. 어댑터는 호출 종료 후 남는
분리 프로세스를 만들지 않아야 하며, 외부 취소가 불확실하면 예약과 미확정 intent를 유지한다.

어댑터 호출은 POSIX child process에서 timeout과 최대 결과 크기로 bounded 처리된다. 이 장치는 trusted adapter를
감독하는 것이지 임의 Python 코드를 안전하게 실행하는 sandbox가 아니다.

## 상태와 증거

receipt가 커밋되기 전까지 완료로 보지 않는다. 성공한 attempt는 입력 artifact, 출력 artifact, evidence 결과,
사용량, actor, 버전 결속, code fingerprint를 receipt로 저장한다. 실패·미확정 attempt와 예약도 남긴다.
재시도, fallback, loop, resume은 기존 카운터와 증거를 보존한다.

`runtime_contracts.py`는 `COMMON_SCHEMAS`와 `STAGE_SCHEMAS`를 제공한다. 이 스키마는 `graph_runtime`의 작은
closed JSON-schema vocabulary로 검증 가능한 payload 계약이며, unknown field나 잘못된 타입을 거절한다.

## 비지원 항목

- 네이티브 모델 호출 사용량을 자동 측정하는 어댑터
- 네이티브 ChatGPT/Codex 사용자 신원을 검증하는 기본 authority
- 전역 tool hook 설치 또는 모든 대화를 v2로 강제하는 모드
- fake `usage=0`, 자유문 승인 문자열, 해시만으로 만든 승인
- 실제 결제, 삭제, 메시지 발송, 배포를 검증 없이 실행하는 예제

v1 state CLI와 문서는 legacy/advisory다. v2 안전 계약을 집행하는 compliant mode로 주장하지 않는다.
