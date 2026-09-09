# research-team

외부 지식, 로컬 코드, 또는 둘 모두를 조사할 때 인용·독립 팩트체크·불확실성 표기를 강제하는 조사 워크플로다. 빠른 개요보다 검증 가능한 결론이 필요한 질문에 쓴다.

## 호출

Claude에서는 자연어 요청으로 시작한다.

```text
출처 검증해서 조사해줘: OAuth 2.1의 PKCE 관련 최신 권고는 무엇이야?
```

Codex에서는 명시 호출도 가능하다.

```text
$research-team 이 저장소의 인증 구현이 최신 OAuth 권고를 따르는지 조사해줘
```

다른 트리거는 `자료조사팀 돌려줘`, `이 질문 팩트체크하면서 조사해줘`, `근거 대면서 답해줘`, `run the research team`이다.

## 조사 모드

질문에 따라 다음 모드를 고른다.

- `web`: 외부 표준, 제품 정보, 일반 지식 조사
- `code`: 특정 저장소의 코드·설정·문서 조사
- `both`: 외부 요구사항과 로컬 구현을 함께 비교

명시적으로 저장소 경로를 주지 않은 `code`·`both` 요청은 현재 작업 디렉터리를 사용한다. 모드가 애매하면 정보 누락을 줄이기 위해 `both`로 처리한다.

## 사용 예

```text
$research-team npm의 최신 trusted publishing 권고를 출처와 함께 조사해줘

$research-team /work/app의 세션 쿠키 구현을 분석하고 OWASP 권고와 비교해줘
```

## 실행 흐름

1. 질문을 최대 세 개의 겹치지 않는 조사 각도로 나눈다.
2. 각 각도에서 출처·날짜·confidence를 갖는 claim만 수집한다.
3. claim 작성자와 다른 에이전트가 원출처를 독립 재확인한다.
4. `CONFIRMED` claim만 사용해 근거 → 추론 → 결론 순으로 종합한다.
5. 확인되지 않은 내용은 추측하지 않고 미해결 항목으로 남긴다.

Workflow 실행기가 없는 환경에서는 같은 5단계를 Codex의 동등한 도구로 수행하고, 폴백 사용을 결과에 밝힌다.

## 결과와 산출물

답변은 `근거`, `추론`, `결론`, `확인 안 됨` 구조를 유지한다. 가능하면 다음 위치에 전체 claim과 검증 판정을 저장한다.

```text
nimbalyst-local/research/<질문-slug>/report.md
```

claim 판정은 `CONFIRMED`, `REFUTED`, `UNVERIFIABLE`이고, 접근 방식은 `webfetch`, `chrome`, `blocked`, `local-read`처럼 기록한다. 파일 저장이 실패하면 이전 보고서를 이번 결과로 오인하지 않도록 그 사실을 명시한다.

주요 상태는 `answered`, `no-claims-found`, `no-confirmed-claims`, `synthesis-failed`다. 마지막 세 상태는 답을 지어내지 않으며, 특히 `synthesis-failed`는 확인된 claim은 있었지만 종합 단계가 실패한 경우다.

정확한 출처 폴백 순서와 결과 계약은 [원본 스킬 정의](../../.claude/skills/research-team/SKILL.md)와 `workflow.mjs`에 있다.
