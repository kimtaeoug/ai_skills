---
name: archon-adversarial-dev
description: >
  Claude+Codex 협업 개발 루프를 Archon 스타일 DAG(공동계획→비평→합의→서브태스크 분할→
  Codex 병렬 구현→Claude 병렬 리뷰→반복)로 Workflow 툴을 통해 실행한다. 큰 작업은
  서브태스크로 쪼개 병렬 처리한다. 항상 처음부터 새로 실행(resume 없음).
  Trigger phrases — 한국어: "adversarial dev로 구현해줘", "codex랑 대립 개발 해줘",
  "archon 스타일로 codex 협업 루프 돌려줘"; English: "run archon-adversarial-dev",
  "adversarial dev loop with codex".
---

# archon-adversarial-dev

Claude+Codex 협업 루프(`~/.claude/commands/cc-loop.md`)를 Archon 스타일 명시적 DAG로
재구성한 project skill이다. 구현은 Codex만, 리뷰는 Claude만 담당한다(계획 단계에서만
Codex가 비평자로 개입). 전체 단계 정의·서브태스크 모델·wave 병렬·validate·review·
triage·종료 판정은 `workflow.mjs`에 있다 — 이 파일은 트리거 인지와 인자 파싱만 한다.

설계 근거: `docs/superpowers/specs/2026-09-04-archon-adversarial-dev-design.md`. 동작을
바꾸려면 스킬 파일이 아니라 그 설계 문서부터 갱신할 것.

## Managed mode (`task-orchestrator`)

`task-orchestrator`가 이 스킬을 호출할 때는 바깥 오케스트레이터가 루프와 상태를 소유한다.
오케스트레이터가 task root, local task id, criteria version, plan version, `DEV-##`, attempt,
artifact dir, file ownership을 제공하면 이 스킬은 한 번의 bounded 구현/리뷰 시도만 수행한다.
이 managed branch가 적용되면 결과를 반환하고 아래 standalone 실행 섹션으로 계속 진행하지 않는다.

- standalone `workflow.mjs`를 실행하지 않는다. 필요하면 절차서로 읽어 현재 `DEV-##`에 맞는
  구현/리뷰 방법만 따른다.
- task dir reset, 전체 replan, max-rounds 기반 내부 반복, nested delegation을 하지 않는다.
- 가능한 경우 구현 executor와 독립 reviewer를 분리한다. Claude/Codex 고정 역할을 실제로 사용할 수
  없으면 사용 가능한 native-role 대체를 명시하고, 실행하지 않은 cross-provider 리뷰를 했다고 쓰지
  않는다.
- child role은 리더가 직접 dispatch한다. managed mode child는 자기 하위 team/subagent를 다시
  만들지 않는다.
- 결과는 변경 파일, diff 요약, 테스트 권고, 리뷰 finding, blocker를 artifact dir에 남긴다.
- 다음 재시도/triage/완료 판단은 오케스트레이터가 한다.

## 1. 인자 파싱

- 사용자 요청 전체에서 **작업 설명**(`task`)을 추출한다. 비어 있으면 무엇을 구현할지
  한 줄로 사용자에게 물은 뒤 진행한다.
- `--max-rounds N`이 있으면 그 값을, 없으면 **기본 5**를 `maxRounds`로 쓴다.
- Resume 옵션은 없다 — 이 스킬은 트리거될 때마다 항상 처음부터 새로 실행한다
  (범위 밖: 이전 라운드 아티팩트를 감지해 이어가는 기능 없음).

## 2. Workflow 가용성 확인 (필수, 매 실행 첫 스텝)

이 스킬은 세션의 **Workflow 툴**(`agent()`/`parallel()`/`pipeline()`)을 실행 엔진으로
쓴다. 별도 구현체가 아니라 세션에 이미 있는 도구를 그대로 쓰는 것이므로, 실제로
쓸 수 있는지 매번 먼저 확인한다:

1. `Workflow`가 이 세션의 도구 목록(또는 `ToolSearch`로 지연 로드되는 도구 목록)에
   있는지 확인한다.
2. 있으면 **workflow.mjs 경로**: 아래 3번으로 진행.
3. 없거나, 스크립트 실행 중 `agentType: "codex:codex-rescue"`로 스폰한 Codex 호출이
   `CLAUDE_PLUGIN_ROOT` 미정의 등으로 실패하면 — **폴백**: Workflow를 포기하고
   `workflow.mjs`에 적힌 단계·서브태스크 모델·wave 로직을 그대로 따르되, `agent()`/
   `parallel()` 호출 대신 **`Agent` tool을 한 메시지에 여러 tool call로 동시 호출**하는
   방식으로 대체한다(`superpowers:dispatching-parallel-agents` 패턴). 두 경로 모두
   fan-out 상한(wave당 최대 4개)과 depth=1(nested delegation 금지)은 동일하게 지킨다.
   폴백이 발생했다는 사실을 최종 `report.md`와 사용자 보고에 명시한다.

## 3. 실행

Workflow가 가용하면:

```
Workflow({
  scriptPath: ".claude/skills/archon-adversarial-dev/workflow.mjs",
  args: { task: "<추출한 작업 설명>", maxRounds: <N 또는 5> }
})
```

`workflow.mjs`가 각 단계(preflight/plan/critique/consensus/implement/validate/review/
decision/report)를 순서대로 실행하고 대부분의 산출물(plan.md/critique.md/consensus-plan.md/
subtasks.json/validation-*.md/review-round-*.md)을 각 단계 서브에이전트가 직접
`nimbalyst-local/plans/adversarial-dev/<slug>/` 아래에 쓴다.

**`report.md`만은 예외**: 하네스가 "report/summary 형태 파일은 서브에이전트가 쓸 수 없음"
정책으로 서브에이전트의 Write를 막기 때문에, `workflow.mjs`는 `report.md`를 파일로 쓰지
않고 반환값의 `report` 문자열로만 돌려준다. **Workflow 호출이 끝나면 이 오케스트레이터
(나)가 직접 `Write` 툴로 그 문자열을 `<반환된 dir>/report.md`에 저장한다.**

스크립트가 반환하는 최종 상태(`pass`/`needs-user-decision`/`iterate-stopped`/`aborted`)를
사용자에게 한 줄로 요약해 보고한다 — Codex/리뷰 원시 출력을 그대로 덤프하지 않는다.

폴백 경로(2번)를 탄 경우, `workflow.mjs`를 실행 가능한 스크립트가 아니라 **절차서로
읽고** 그 안의 단계·프롬프트 템플릿·산출물 경로·병렬 규칙을 그대로 따라 손으로(Agent
tool 반복 호출로) 재현한다.
