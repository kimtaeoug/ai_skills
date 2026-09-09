# archon-adversarial-dev

복잡한 구현 작업을 공동 계획, 독립 비평, 합의, 병렬 구현, 검증, 리뷰 순으로 진행하는 개발 워크플로다. 새 기능이나 여러 파일에 걸친 버그 수정처럼, 계획과 리뷰가 구현 품질을 높이는 경우에 쓴다.

## 호출

Claude에서는 아래처럼 요청한다.

```text
adversarial dev로 구현해줘: 결제 API에 idempotency key를 추가해줘
```

Codex에서는 명시적으로 호출할 수 있다.

```text
$archon-adversarial-dev 결제 API에 idempotency key를 추가해줘
```

한국어 트리거 예시는 `codex랑 대립 개발 해줘`, `archon 스타일로 codex 협업 루프 돌려줘`다. 영어로는 `run archon-adversarial-dev` 또는 `adversarial dev loop with codex`를 쓴다.

## 입력

- 작업 설명은 필수다. 비어 있으면 한 줄로 범위를 확인한다.
- `--max-rounds N`으로 반복 상한을 바꿀 수 있으며, 기본값은 5다.
- 이전 결과를 이어받는 resume 모드는 지원하지 않는다. 호출마다 새 작업으로 시작한다.

예:

```text
$archon-adversarial-dev --max-rounds 3 OAuth 콜백의 state 검증을 추가하고 회귀 테스트를 작성해줘
```

## 실행 흐름

1. 작업 범위와 선행 조건을 확인한다.
2. 구현 계획을 만들고 독립적으로 비평한다.
3. 합의된 계획을 검증 가능한 하위 작업으로 나눈다.
4. 서로 독립적인 작업만 wave 단위로 병렬 구현한다.
5. 테스트·린트·타입검사 등 저장소의 기존 검증을 실행한다.
6. 독립 리뷰와 triage를 거쳐 통과, 반복 중단, 사용자 판단 필요, 중단 중 하나로 끝낸다.

Workflow 실행기가 없는 환경에서는 같은 단계와 병렬 상한을 Codex의 동등한 에이전트·도구로 재현하고, 폴백 사용 사실을 결과에 남긴다.

## 결과와 산출물

작업 산출물은 보통 다음 경로에 저장된다.

```text
nimbalyst-local/plans/adversarial-dev/<작업-slug>/
```

대표 파일은 `plan.md`, `critique.md`, `consensus-plan.md`, `subtasks.json`, `validation-*.md`, `review-round-*.md`, `report.md`다. 최종 상태는 `pass`, `needs-user-decision`, `iterate-stopped`, `aborted` 중 하나로 요약한다.

## 제약

- 구현은 Codex, 리뷰는 Claude 역할로 분리하는 것이 기본이다.
- 병렬 wave는 최대 4개의 독립 작업만 허용하며, 중첩 위임은 하지 않는다.
- `report.md`는 최종 오케스트레이터가 기록한다.

정확한 실행 계약은 [원본 스킬 정의](../../.claude/skills/archon-adversarial-dev/SKILL.md)와 `workflow.mjs`에 있다.
