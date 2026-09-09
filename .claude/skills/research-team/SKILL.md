---
name: research-team
description: >
  임의 주제(개발/코드든 일반 도메인 지식이든)를 조사할 때 5개 규칙 — 불확실성 허용, 인용
  의무화, chain-of-thought 순서(근거→추론→결론), 날짜/최신성 필터, 최종 답변 전 팩트검증
  서브에이전트 재확인 — 을 항상 강제 적용하는 멀티에이전트 조사 파이프라인. Workflow 툴로
  검색 fan-out(웹/코드) → 독립 인용구 재검증 → 종합 → 리포트를 실행한다.
  Trigger phrases — 한국어: "자료조사팀 돌려줘", "출처 검증해서 조사해줘", "이 질문
  팩트체크하면서 조사해줘", "근거 대면서 답해줘"; English: "run the research team",
  "research this with citations and fact-checking".
---

# research-team

임의 주제를 조사할 때 다음 5개 규칙을 항상 강제하는 project skill이다: 불확실성 허용,
인용 의무화, chain-of-thought 순서(근거→추론→결론), 날짜/최신성 필터, 최종 답변 전 팩트검증
서브에이전트 재확인. 실행 로직은 전부 `workflow.mjs`에 있다 — 이 파일은 트리거 인지와 인자
파싱만 한다.

설계 근거: `docs/superpowers/specs/2026-09-04-research-team-design.md`. 동작을 바꾸려면
스킬 파일이 아니라 그 설계 문서부터 갱신할 것.

## Managed mode (`task-orchestrator`)

`task-orchestrator`가 이 스킬을 호출할 때는 독립 워크플로를 끝까지 소유하지 않는다.
오케스트레이터가 task root, local task id, criteria version, research id/attempt, artifact dir,
question, mode를 제공하면 이 스킬은 조사 절차만 수행하고 결과를 해당 artifact dir에 남긴다.
이 managed branch가 적용되면 결과를 반환하고 아래 standalone 실행 섹션으로 계속 진행하지 않는다.

- completion/criteria 승인 여부는 판단하지 않는다.
- task id를 새로 만들거나 기존 task state를 직접 완료 처리하지 않는다.
- 원출처, 날짜, confidence, `CONFIRMED`/`REFUTED`/`UNVERIFIABLE` 판정은 평소와 같이 남긴다.
- Workflow 툴이 있어도 `workflow.mjs`를 실행하지 않는다. 필요하면 절차서로 읽어 동등한 조사 단계를
  수행한다.
- claim finder와 source verifier는 가능한 한 독립 에이전트/역할로 나누며, finder가 자기 claim을
  self-check한 것을 독립 검증으로 취급하지 않는다.
- child role은 리더가 직접 dispatch한다. managed mode child는 자기 하위 team/subagent를 다시
  만들지 않는다.

## 1. 인자 파싱

- 사용자 요청에서 **조사 질문**(`question`)을 추출한다. 비어 있으면 무엇을 조사할지 한 줄로
  물은 뒤 진행한다.
- **모드 판단** (`mode`): 질문이 특정 로컬 레포/코드베이스를 가리키면 `code`, 일반 지식이나
  외부 스펙이면 `web`, 둘 다 걸치면 `both`. 애매하면 `both`로 기본 설정한다(정보 누락보다
  과다 조사가 안전). 예:
  - "이 프로젝트의 인증 흐름 뭐야?" → `code`
  - "OAuth 2.1 PKCE 스펙 최신 권고안은?" → `web`
  - "우리 인증 구현이 최신 OAuth 스펙 따르나?" → `both`
- `code`/`both` 모드에서 대상 레포 경로(`repoPath`)가 명시 안 되면 현재 작업 디렉터리를
  기본값으로 쓴다.

## 2. Workflow 가용성 확인 (필수, 매 실행 첫 스텝)

이 스킬은 세션의 **Workflow 툴**(`agent()`/`parallel()`)을 실행 엔진으로 쓴다. 매번 먼저
확인한다:

1. `Workflow`가 이 세션의 도구 목록(또는 `ToolSearch`로 지연 로드되는 도구 목록)에 있는지
   확인한다.
2. 있으면 아래 3번(Workflow 경로)으로 진행.
3. 없으면 **폴백**: `workflow.mjs`를 실행 가능한 스크립트가 아니라 **절차서로 읽고**, 그
   안의 5단계(Plan/Find/Verify/Synthesize/Report)와 각 단계의 프롬프트·스키마·소스 접근
   폴백 순서(WebFetch → claude-in-chrome → blocked)를 그대로 따라 `Agent` tool을 한
   메시지에 여러 tool call로 동시 호출하는 방식(`superpowers:dispatching-parallel-agents`
   패턴)으로 재현한다. Find는 3개, Verify는 claim 수만큼(한 메시지당 최대 4개씩 나눠) 병렬
   호출한다. 폴백이 발생했다는 사실을 최종 보고에 명시한다.

## 3. 실행

Workflow가 가용하면:

```
Workflow({
  scriptPath: ".claude/skills/research-team/workflow.mjs",
  args: { question: "<추출한 질문>", mode: "<web|code|both>", repoPath: "<대상 경로 또는 생략>" }
})
```

## 4. 결과 보고

스크립트가 반환한 값을 그대로 정직하게 전달한다:

- `answer` 필드를 채팅에 그대로 출력한다(근거/추론/결론/확인 안 됨 섹션 구조를 그대로
  유지 — 재구성하거나 요약하지 않는다).
- `claimsSummary`가 있으면(전체/확인/반박/미확인 건수) 한 줄로 덧붙인다 — `no-claims-found`
  경로에는 없다.
- `dir` 경로(`nimbalyst-local/research/<slug>/report.md`)를 저장 위치로 언급한다. 단
  `reportWritten`이 `false`면(rate-limit 등으로 파일 쓰기 실패) 그 경로에 이번 결과가
  저장되지 **않았다**고 명시한다 — 이전 실행이 남긴 stale한 report.md를 이번 결과로
  오인하지 말 것.
- `status`가 `no-claims-found`/`no-confirmed-claims`/`synthesis-failed`면 그 사실을 숨기지
  않고 그대로 전달한다 — 억지로 답을 만들어내지 않는다. 특히 `synthesis-failed`는 "확인된
  claim은 있었으나 종합 단계 자체가 실패(주로 rate-limit)"라는 뜻이므로 재시도를 권한다.
- Verify 단계에서 원출처 재확인을 실제로 했다는 것(claim을 만든 에이전트가 자기 검증을 하지
  않는다는 것)을 사용자가 물으면 설명할 수 있어야 한다 — report.md의 Claims 표에 소스별
  판정(`CONFIRMED`/`REFUTED`/`UNVERIFIABLE`)과 접근 경로(`webfetch`/`chrome`/`blocked`/
  `local-read`)가 남아있다.
