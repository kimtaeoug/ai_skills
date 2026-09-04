# 스킬 진화 메커니즘 (Skill Evolution Mechanism) — 설계

## 배경

revfactory/harness 플러그인의 "하네스 진화 메커니즘"에서 영감을 받음: 초기 생성물과 실사용 후 최종 상태 사이의 델타를 팩토리(생성 로직)로 되먹여, 다음 생성이 더 나은 초안에서 시작하도록 하는 self-improving generator 패턴.

이 작업공간(`/Users/deratio/skills`)의 자체 제작 스킬들(`repo-convention-extractor`, `code-style-extractor`, `commit-convention-extractor`, `package-dependency-extractor` 등)에 같은 패턴을 적용하되, 특정 플러그인에 묶이지 않는 범용 독립 도구로 설계한다.

## 목표

- 스킬이 만들어진 뒤 실사용을 거치며 어떻게 바뀌었는지(무엇이 안 먹혀서 고쳤는지)를 기록으로 남긴다.
- 그 기록을 다음번 비슷한 스킬을 만들 때 참고 자료로 쓸 수 있게 한다.
- Claude Code에 종속되지 않는 CLI 코어 + Claude Code용 대화형 스킬 wrapper로 구성해, 다른 컨텍스트에서도 재사용 가능하게 한다.

## 핵심 설계 긴장

1. **원시 사례 vs 일반화된 교훈** — 한 프로젝트에서 통한 수정이 다른 도메인에도 맞는 규칙인지는 별개 문제다. 원시 diff/맥락 기록과, 사람이 승인한 일반화 교훈을 분리해야 오염을 막을 수 있다.
2. **자동 자기개선 vs 통제·재현성** — diff를 자동으로 스킬 정의에 반영하면 빠르지만 프롬프트 드리프트를 일으킨다. "후보 수집은 자동, 생성 규칙 반영은 명시적 승인"으로 긴장을 관리한다.

## 아키텍처

3계층 저장 구조 + CLI 코어 + 스킬 wrapper.

```
evolution/
  records/<skill>/<date>-<slug>.md   # 불변 원시 기록 (baseline → final 델타 + 맥락)
  lessons/<skill>.md                  # 스킬별 승인된 교훈 (사람이 record에서 뽑아 정리)
  patterns/<topic>.md                 # 스킬 횡단 일반화 교훈 (사람이 lessons에서 승격)

skills/evolve/
  SKILL.md                            # 대화형 wrapper: baseline·현재 diff 확인, 맥락/효과 질문, record 작성

bin/evolve                            # 순수 로직 CLI: snapshot / diff / record — Claude Code 밖에서도 재사용 가능
```

### 컴포넌트별 책임

- **`bin/evolve` (CLI)**: git 유무와 무관하게 동작하는 순수 로직. 서브커맨드:
  - `evolve snapshot <skill-dir>` — 현재 상태를 baseline으로 기록 (git repo면 커밋 SHA 참조, 아니면 파일 해시/카피)
  - `evolve diff <skill-dir>` — snapshot 이후 현재까지의 diff를 stdout으로 출력
  - LLM 판단이나 요약은 하지 않는다. 순수 파일/git 조작만.
- **`skills/evolve/SKILL.md` (스킬 wrapper)**: `bin/evolve diff`를 호출해 델타를 받고, 사용자에게 맥락(어느 프로젝트에 썼는지, 뭐가 안 먹혔는지, 효과가 있었는지)을 질문한 뒤 `evolution/records/`에 record를 작성한다. 필요하면 record 내용을 바탕으로 `lessons/<skill>.md`에 사람이 승인한 교훈을 append하는 것까지 이 스킬이 도와준다.
- **레코드 → 교훈 → 패턴 승격은 항상 사람이 결정한다.** 자동 승격 없음.

### 델타 판단 방식: 하이브리드 트리거

- 자동: 스킬 파일이 생성 이후 수정된 diff는 git이 이미 조용히 쌓아둔다 (별도 장치 불필요).
- 명시적: `/evolve` 호출 시점에 "지금까지의 누적 diff = 유효한 진화 사례"로 확정(승격)한다. 사람이 "이 정도면 됐다"고 판단하는 시점에만 record가 만들어진다. 자동 트리거(세션 종료 등)는 두지 않는다 — 신호 대 잡음비가 나빠지기 때문.

### 레코드 스키마

```md
skill: <스킬 이름>
baseline: <git SHA 또는 snapshot 경로>
final: <git SHA 또는 현재 경로>
context: <어느 프로젝트/도메인에 적용했는지>
delta: <구조·지침·검증 규칙에서 뭐가 바뀌었는지>
evidence: <실패/성공 사례, 사용자 피드백, 선택적 수치 — 없으면 생략 가능>
candidate_lessons: <재사용 가능하다고 추정되는 규칙>
promotion: pending | accepted | rejected
```

`evidence`는 선택 필드로 둔다 — 정량 지표를 강제하면 MVP가 무거워진다.

### 되먹임 적용 (v1 범위)

- `SKILL.md` 자동 수정 없음.
- 새 스킬을 만들 때, 관련 기존 스킬의 `lessons/<skill>.md`를 참고 자료로 명시적으로 읽으라는 지시를 생성 프롬프트에 한 줄 추가하는 정도로 그친다.
- 패턴 라이브러리 자동 참조, `SKILL.md` 자동 갱신은 v2로 미룬다 — record가 몇 개 쌓여 반복 패턴이 실제로 보일 때 다시 설계한다. 지금은 표본이 없어 일반화할 근거가 없다.

## MVP 범위

- 스킬 하나(`repo-convention-extractor`)에만 먼저 적용해 실증.
- `bin/evolve`는 `snapshot`, `diff` 두 서브커맨드만 구현.
- `skills/evolve/SKILL.md`는 diff를 받아 사용자에게 질문하고 record 하나를 `evolution/records/repo-convention-extractor/`에 쓰는 것까지만.
- lessons/patterns 계층은 파일 포맷만 정의해두고, 실제 승격은 record가 2개 이상 쌓인 뒤 수동으로 해본다.

## 에러 처리

- `evolve diff`를 baseline 없이 호출하면 명확한 에러 메시지로 `evolve snapshot`부터 하라고 안내.
- git repo가 아닌 스킬 디렉토리는 파일 mtime/해시 기반 폴백으로 동작 (git 필수 아님).

## 테스트

- `bin/evolve`: snapshot 후 파일을 고쳤을 때 diff가 정확히 잡히는지 확인하는 최소 스모크 테스트 하나.
- `skills/evolve/SKILL.md`: `repo-convention-extractor`에 실제로 한 번 돌려서 record 파일이 스키마대로 생성되는지 수동 검증.

## 범위 밖 (v2 이후)

- 자동 세션 종료 트리거
- 패턴 라이브러리 자동 참조/자동 승격
- `SKILL.md` 자동 갱신
- 정량 효과 측정(재작업률, 실패율 등)
