# research-team 설계

## 배경 / 목적

임의의 주제(개발/코드 관련이든 일반 도메인 지식이든)를 조사할 때, 아래 5개 규칙을 매번
수동으로 지시하지 않아도 항상 강제 적용되는 재사용 가능한 project skill을 만든다.

1. **불확실성 허용** — 모르면 "모른다"고 답할 수 있다. 추측으로 채우지 않는다.
2. **인용 의무화** — 모든 사실 주장에는 출처를 붙인다. 출처가 없으면 그 주장은 버린다.
3. **Chain-of-thought 강제** — 최종 답변은 항상 "근거 나열 → 추론 → 결론" 순서로 쓴다.
4. **날짜/최신성 필터** — 같은 주제에 대해 상충하는 정보가 있으면 더 최신 정보를 채택한다.
5. **팩트 검증 서브에이전트** — 최종 답변 확정 전에, 모든 주장의 인용구를 독립 서브에이전트가
   원출처에서 재확인한다.

## 배치 / 관행

`archon-adversarial-dev`, `test-agent-team`과 동일한 레포 관행을 따른다:

- `.claude/skills/research-team/SKILL.md` — 트리거 인지 + 인자 파싱만. 실행 로직 없음.
- `.claude/skills/research-team/workflow.mjs` — Workflow 툴(`agent`/`parallel`/`pipeline`)
  오케스트레이션 본체. 실제 단계 정의는 전부 여기.

Workflow 툴이 세션에 없거나 실행 중 치명적으로 실패하면, `workflow.mjs`를 실행 스크립트가
아니라 **절차서로 읽고** Agent tool을 한 메시지에 여러 tool call로 동시 호출하는 방식
(`superpowers:dispatching-parallel-agents` 패턴)으로 동일 단계를 손으로 재현한다. 폴백
발생 사실은 최종 보고서에 명시한다.

## 인자 파싱 (SKILL.md)

- 사용자 요청에서 **조사 질문/주제**를 추출한다. 비어 있으면 한 줄로 물은 뒤 진행.
- **모드 판단**: 질문이 특정 로컬 레포/코드베이스를 가리키면 `code` 모드, 일반 지식/외부
  스펙이면 `web` 모드, 둘 다 걸치면 `both`. 애매하면 `both`로 기본 설정(정보 누락보다
  과다 조사가 안전).
- 대상 레포 경로가 명시되지 않고 `code`/`both` 모드면, 현재 작업 디렉터리를 기본 대상으로
  한다.

## 파이프라인 (workflow.mjs)

### 1. Plan
질문을 검색 각도 2~3개로 분해한다 (예: 정의/스펙, 최신 동향, 반대 사례). 모드(web/code/both)
확정.

### 2. Find (병렬, 고정 3개 lane)
각 finder 에이전트가 서로 다른 각도로 조사한다.

- **web 모드**: `WebSearch` → 후보 URL → `WebFetch`로 본문 확보. (아래 "소스 접근 폴백"
  참고.)
- **code 모드**: `Grep`/`Read`/`git log`로 로컬 근거 확보.
- **both**: finder 하나는 web, 하나는 code, 하나는 교차 검증(코드가 web 스펙을 따르는지
  비교) 각도로 배정.

각 finder는 주장을 다음 스키마로만 반환한다 (출처 없는 주장은 애초에 생성 금지):

```json
{ "claim": "...", "source": "https://... 또는 path/to/file.ts:120",
  "date": "YYYY-MM-DD 또는 커밋 해시/날짜 또는 unknown",
  "confidence": "high|medium|low" }
```

`date`가 unknown이면 규칙 4(최신성 필터) 적용 시 최하위로 취급한다고 프롬프트에 명시.

### 3. Verify (claim 당 1개, 병렬)
독립 서브에이전트가 원출처를 **재조회**해서 인용구가 실제로 거기 있는지 확인한다 (Find와
같은 에이전트가 자기 주장을 자기가 검증하지 않음 — 확증편향 방지).

판정: `CONFIRMED / REFUTED / UNVERIFIABLE`. `REFUTED`, `UNVERIFIABLE`은 최종 답변에서
제외한다. "검증 못 함"을 `CONFIRMED`로 취급하지 않는다.

재조회 시 "소스 접근 폴백"(아래)을 Find와 동일하게 적용한다.

### 4. Synthesize
`CONFIRMED` claim만 가지고 최종 답변을 작성한다. 출력 구조 강제:

1. **근거** — 살아남은 claim 목록, 각각 출처 인용 포함.
2. **추론** — 근거들을 어떻게 연결해서 결론에 이르는지.
3. **결론** — 위 추론에서 자연스럽게 도출되는 답.

같은 주제에 claim이 여러 개 상충하면 `date` 비교해서 최신 채택, 그 사실을 "근거" 섹션에
명시한다. 질문의 일부라도 `CONFIRMED` claim으로 못 채우면 그 부분은 추측하지 않고 "확인
안 됨"으로 명시한다.

### 5. Report
채팅에 최종 답변 출력 + `nimbalyst-local/research/<slug>/report.md` 저장. 저장 내용:
질문, 모드, 최종 답변 전문, claim별 상태 표(`CONFIRMED`/`REFUTED`/`UNVERIFIABLE`/`blocked`),
Find/Verify 단계에서 소스 접근이 몇 단계(WebFetch/Chrome/차단)에서 끊겼는지.

## 소스 접근 폴백 (Find 웹모드 + Verify 재조회 공통)

1. `WebFetch` 먼저 시도.
2. JS 렌더링 의존 등으로 본문을 못 가져오면 → `claude-in-chrome`으로 실제 접속
   (`navigate` → `get_page_text`/`read_page`). 첫 사용 전 필요한 도구를 `ToolSearch`로
   로드.
3. Chrome으로도 막히면(로그인벽, 캡차, 명시적 차단) → 그 소스는 `blocked`로 종료하고
   **바로 다음 소스로 넘어간다**. 같은 소스에 반복 재시도하지 않는다(2-3회 초과 금지,
   `claude-in-chrome` 스킬의 무한루프 방지 원칙 그대로). alert/confirm류 다이얼로그가 뜨는
   페이지는 트리거하지 않는다.

몇 단계에서 확보/차단됐는지는 claim의 `source` 옆에 부기해서 report.md에 남긴다 (재현
가능하도록).

## 상태 taxonomy

`confirmed / refuted / unverifiable / blocked / not-found` — test-agent-team과 동일한
원칙: "못 찾음"과 "확인 안 됨"을 `confirmed`로 절대 취급하지 않는다.

## 규칙 5개 → 메커니즘 매핑

| 규칙 | 강제 지점 |
|---|---|
| 1. 불확실성 허용 | Synthesize: `CONFIRMED`로 못 채운 부분은 "확인 안 됨"으로 명시, 추측 금지 |
| 2. 인용 의무화 | Find 단계 claim 스키마에 `source` 필수 — 출처 없는 주장 자체가 생성 안 됨 |
| 3. CoT 강제 | Synthesize 출력 구조가 근거→추론→결론 순서로 고정 |
| 4. 날짜/최신성 필터 | claim마다 `date` 필드 필수, 상충 시 최신 채택 로직 (Synthesize) |
| 5. 팩트검증 서브에이전트 | Verify 단계, claim 전수 재검증, 최종 답변 확정 전 게이트 |

## 범위 밖

- 다국어 자동 번역, 요약 길이 조절 옵션 — 미지원. 필요해지면 추가.
- 조사 결과 캐싱/재사용(동일 질문 재실행 시 이전 report.md 재사용) — 미지원. 매번
  새로 조사한다.
- claude-in-chrome 확장 로그인/지갑 연동 — 이 스킬 범위 밖(test-agent-team의 지갑 테스트
  가드레일과 무관).

## 테스트 / 셀프체크

`workflow.mjs`는 에이전트 오케스트레이션 스크립트라 결정론적 유닛테스트 대상이 크지 않다.
스크립트 안에 포함되는 **순수 함수**(예: slug 생성, claim 상태 집계, 최신성 비교 로직)는
`node --test` 기반 최소 `test_research_team.mjs`로 assert 커버한다(프레임워크 없음,
`ponytail:` 코멘트로 남긴 단순화가 있으면 그 경계도 여기서 확인).
