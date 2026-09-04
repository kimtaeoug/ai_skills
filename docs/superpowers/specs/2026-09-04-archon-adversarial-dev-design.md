# archon-adversarial-dev 스킬 — 설계

날짜: 2026-09-04
관련: `~/.claude/commands/cc-loop.md` (기존 Claude+Codex 협업 루프, 이 스킬의 로직 기반), `coleam00/Archon` (워크플로 DAG 개념 참고 원본 — 실제 설치는 안 함), `.claude/skills/test-agent-team/SKILL.md` (이 레포의 project skill 배치 패턴), Workflow 툴(agent()/parallel()/pipeline() 오케스트레이션)

## 목적

`~/.claude/commands/cc-loop.md`는 Claude+Codex 협업 루프(공동계획 → Codex 구현 → Claude 리뷰 → 반복)를 이미 구현하고 있지만, 전역 슬래시 커맨드로 존재하며 단계 경계가 산문 지시문 안에만 있고, 큰 작업도 항상 통짜로(Codex 한 번 호출, 리뷰 한 번 호출) 처리한다.

이 스킬은 같은 로직을 **이 레포의 project skill**로 재구성하되:
1. Archon의 워크플로 DAG 개념(명시적으로 이름 붙은 노드, 노드마다 산출물)을 빌려 각 단계를 명시적으로 만들고,
2. 시간이 오래 걸리거나 덩치가 큰 작업은 **서브태스크로 쪼개 서브에이전트로 병렬 실행**한다(구현·리뷰 단계).

실제 Archon 툴(bun CLI, YAML 워크플로 엔진)은 설치하지 않는다 — 개념만 차용한다. 이 세션에 있는 **Workflow 툴**(`agent()`/`parallel()`/`pipeline()`)을 실행 엔진으로 쓴다 — 서브태스크 병렬 처리가 필요해진 시점에 SKILL.md 절차서 방식(순차 해석)보다 Workflow 스크립트가 자연스럽기 때문(사용자 확정, 브레인스토밍 중 방향 전환).

역할은 cc-loop과 동일하게 고정: **구현은 Codex만, 리뷰는 Claude만** 수행한다. 계획 단계에서만 Codex가 비평자로 개입한다. 두 에이전트가 서로의 구현물을 독립적으로 만들어 상호 비판하는 진짜 양방향 대립 구조는 이번 범위에 넣지 않는다(사용자 확정).

## 아키텍처

새 컴포넌트를 만들지 않고 기존 것을 재사용한다:
- `codex:codex-rescue` 서브에이전트 — Codex 호출 경로 (cc-loop과 동일한 호출 규칙, 아래 참조)
- Workflow 툴 — 병렬/파이프라인 오케스트레이션 엔진 (별도 구현 안 함, 이미 세션에 있는 도구 그대로 사용)
- `nimbalyst-local/plans/` — 산출물 저장 위치

### 배치

두 파일로 구성, `test-agent-team`과 같은 자리(project skill):

- `.claude/skills/archon-adversarial-dev/SKILL.md` — 트리거 설명 + 인자 파싱 지침만. 본체 로직은 없음. 사용자 요청에서 작업 설명과 `--max-rounds`(옵션)를 추출해 `Workflow({ scriptPath: '.claude/skills/archon-adversarial-dev/workflow.mjs', args: { task, maxRounds } })`를 호출하라고 지시.
- `.claude/skills/archon-adversarial-dev/workflow.mjs` — DAG 본체(아래 "워크플로 스크립트" 참조).

Frontmatter:
```yaml
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
```

### 페이즈 (DAG)

```
preflight → plan → critique → consensus(+subtask 분할) → implement(wave-parallel) → validate → review(parallel) → decision
                                                                  ↑                                                     │
                                                                  └───────────── iterate(실패 서브태스크만) ────────────┘
                                                                                                                        │
                                                                                                                      pass
                                                                                                                        │
                                                                                                                        ▼
                                                                                                                      report
```

| 노드 | 수행 주체 | 병렬화 | 산출물 |
|---|---|---|---|
| `preflight` | Codex(ping) | - | 없음 (실패시 안내 후 중단) |
| `plan` | 워크플로 agent (Claude 계열) | - | `plan.md` |
| `critique` | Codex agent, read-only | - | `critique.md` (충돌 크면 `critique-2.md`) |
| `consensus` | 워크플로 agent | - | `consensus-plan.md` + 서브태스크 목록(JSON, 아래 참조) |
| `implement` | Codex agent, 서브태스크당 1개 | wave 단위 `parallel()` | 서브태스크별 구현 결과(파일 목록) → `report.md`에 누적 |
| `validate` | Bash(빌드/테스트) | - | `validation-round-N.md` |
| `review` | 워크플로 agent, 서브태스크당 1개 | `parallel()` | 서브태스크별 리뷰 → `review-round-N.md`로 합산 |
| `decision` | 스크립트 제어 흐름(JS) | - | pass면 `report`, iterate면 실패 서브태스크만 `implement` 재진입 |
| `report` | 워크플로 agent | - | `report.md` 최종 |

### 서브태스크 모델

`consensus` 노드가 합의 계획과 함께 서브태스크 목록을 구조화 출력(schema)한다:

```json
{
  "subtasks": [
    { "id": "t1", "description": "...", "dependsOn": [] },
    { "id": "t2", "description": "...", "dependsOn": ["t1"] }
  ]
}
```

- 안 쪼개도 되는 작은 작업이면 `subtasks`가 항목 1개짜리 리스트다 — **분기 없이 항상 같은 코드 경로**(쪼개는 경우/안 쪼개는 경우를 if로 나누지 않는다, 리스트 길이 1이면 자연히 wave도 1개·parallel도 항목 1개).
- `implement` 단계: `dependsOn`이 모두 완료된 서브태스크들을 하나의 wave로 묶어 `parallel()`로 동시 실행, 다음 wave로 진행 — 간단한 위상정렬(모든 의존이 끝난 태스크를 반복적으로 뽑아 wave 구성).
- `review` 단계: 완료된 서브태스크 각각에 대해 리뷰어를 `parallel()`로 동시 실행(tool 문서의 "dimensions" 파이프라인 패턴과 동일 모양), 결과를 severity 태그 기준으로 합산.
- `decision`에서 `iterate`가 나오면 **전체 재실행이 아니라 critical/major 걸린 서브태스크만** 골라 다음 라운드 `implement`로 다시 보낸다(분할한 이득이 여기서 남).

### Codex 호출 규칙 (cc-loop과 동일한 제약, Workflow `agent()`로 승계)

- Codex 호출은 Workflow `agent()`의 `opts.agentType: "codex:codex-rescue"`로 스폰한다. **구현 전 검증 필요**: 이 경로가 cc-loop이 요구하는 `CLAUDE_PLUGIN_ROOT` 환경을 그대로 보장하는지 미확인 — plan 단계에서 read-only ping 서브태스크 하나로 먼저 검증하고, 실패하면 Workflow 방식을 접고 SKILL.md 절차서(기존 Agent tool 직접 호출) 방식으로 폴백한다(아래 "리스크" 참조).
- 서브에이전트 기본값은 `--write`이므로, 파일 수정이 필요 없는 호출(critique/review)에는 프롬프트 첫 줄에 `read-only, research/critique only, do not edit files`를 반드시 명시한다.
- 스레드 연속성: `--fresh`(critique) / `--resume`(implement)을 프롬프트에 명시. resume은 best-effort이므로 `implement` 프롬프트에는 항상 해당 서브태스크의 설명 + 전체 합의 계획을 함께 싣는다.
- Workflow 동시성 캡(세션당 최대 16개 병렬 `agent()`)을 넘는 대량 서브태스크는 자동으로 큐잉되므로 별도 처리 불필요.

### 종료 판정 (cc-loop과 동일한 기준, 대상만 서브태스크 단위로 좁아짐)

- `pass` = 빌드/테스트 OK **그리고** 모든 서브태스크에서 critical 0.
- `iterate` = critical/major 걸린 서브태스크 목록을 다음 라운드 `implement`에 재투입(해당 서브태스크만).
- `maxRounds`(기본 5, `args.maxRounds`로 override) 초과 시 중단, `report.md`에 최종 상태·잔여 이슈·산출물 경로 기록 후 사용자에게 보고.

## 데이터 흐름

```
[archon-adversarial-dev 트리거]
        │
        ├─ nimbalyst-local/plans/adversarial-dev/<slug>/ 생성(기존 있으면 비움)
        │
        ├─ preflight: codex ping(agentType: codex:codex-rescue) ── 실패 ─→ 사용자 안내, 중단
        │        │ 성공
        │        ▼
        ├─ plan.md 작성
        │        │
        ├─ critique.md 작성(Codex read-only) ── 충돌 크면 critique-2.md
        │        │
        ├─ consensus-plan.md + subtasks[] 작성
        │        │
        │        ▼
        ┌─── implement: subtasks를 dependsOn 기준 wave로 묶어 parallel() 반복
        │        │        (wave 1 parallel → wave 2 parallel → ...)
        │        ▼
        │   validate: 빌드/테스트 → validation-round-N.md
        │        │
        │   review: 완료 서브태스크마다 parallel() 리뷰 → review-round-N.md
        │        │
        │   decision(JS): 실패 서브태스크 있음? ──Yes(iterate, 실패분만)──┐
        │        │No                                                      │
        │        ▼                                                        │
        │   report.md 최종 작성                                            │
        │                                                                  │
        └──────────────────────────────────────────────────────────────────┘
             (round > maxRounds 이면 report.md에 중단 사유 기록 후 종료)
```

## 에러 처리

1. **preflight 실패**: 빈 응답/실패 시 진행 안 함, 안내 후 중단.
2. **슬러그 디렉터리 충돌**: 시작 시 무조건 비움 — 이전 실행 잔여물 혼입 방지.
3. **critique 무한 루프 방지**: 최대 2라운드 상한, 이후도 갈리면 `AskUserQuestion`.
4. **maxRounds 초과**: 무한 반복 방지, 중단 후 보고.
5. **Codex 직접 Bash 호출 금지**: 항상 `agentType: codex:codex-rescue` 경로로만.
6. **read-only 표기 누락 방지**: critique/review 프롬프트 첫 줄 강제.
7. **서브태스크 의존성 사이클**: `consensus` 산출물에서 `dependsOn` 사이클이 발견되면(위상정렬 도중 더 못 뽑는 wave가 남으면) 사이클에 걸린 서브태스크를 의존성 없이 단일 wave로 강등해 순차 처리 — 전체를 실패시키지 않음.
8. **부분 실패 격리**: 한 wave 안에서 일부 서브태스크만 실패해도(`parallel()`은 실패 항목을 `null`로 반환) 나머지 성공 서브태스크는 그대로 진행, 실패분만 iterate 대상에 포함.

## 리스크

- **미검증**: Workflow `agent()`의 `agentType: "codex:codex-rescue"`가 cc-loop이 요구하는 `CLAUDE_PLUGIN_ROOT` 환경을 정상 보장하는지 확인 안 됨. 구현 계획 첫 태스크로 **preflight 단독 스파이크**(ping 1회)를 두고, 실패하면 이 스킬 자체를 SKILL.md 절차서 방식(Agent tool 직접 병렬 호출, Workflow 미사용)으로 되돌린다. 이 폴백 결정 지점을 구현 계획에 명시.

## 테스트

- 실제 검증: 서브태스크 2개 이상으로 자연히 쪼개지는 실제 작업(예: 독립적인 유틸 함수 2개 추가) 하나를 골라 스킬을 실제로 트리거해서 preflight → plan → critique → consensus(서브태스크 분할 확인) → implement(wave parallel 확인) → validate → review(parallel 확인) → decision → report까지 한 사이클 실제로 돌리고, `nimbalyst-local/plans/adversarial-dev/<slug>/`에 각 파일이 기대한 이름·내용으로 생성됐는지 육안 확인.
- 단일 서브태스크 경로 확인: 안 쪼개지는 작은 작업으로 한 번 더 돌려서 `subtasks` 길이 1일 때도 동일 코드 경로로 정상 동작하는지 확인(분기 없음 검증).
- iterate 경로 확인: 서브태스크 중 하나만 critical 이슈가 나는 상황을 만들어, 실패한 서브태스크만 재실행되고 성공한 서브태스크는 재실행 안 되는지 확인.
- 이 스킬은 셸 스크립트가 아니라 SKILL.md+Workflow 스크립트 조합이므로 `smoke-test.sh` 류 자동 테스트는 없음 — 실제 실행이 검증 수단. Workflow의 `resumeFromRunId` 캐시 특성상, 스파이크 실패로 재작업할 때는 캐시된 이전 결과를 참고할 수 있음(참고용, 이 스킬 자체는 resume 기능을 노출하지 않음).

## 범위 밖

- Archon 툴 자체(bun CLI, `.archon/workflows/*.yaml`) 설치 — 안 함, 개념만 차용(사용자 확정).
- Resume(이전 라운드 아티팩트 감지해서 이어가기) — 안 함, 항상 처음부터(사용자 확정, YAGNI).
- 진짜 양방향 adversarial(Claude·Codex 각자 독립 구현 후 서로 비판) — 안 함, 구현=Codex 전담·리뷰=Claude 전담 구조 유지(사용자 확정).
- `cc-loop.md` 슬래시 커맨드 자체를 이 스킬로 대체/삭제 — 안 함, 둘 다 유지(전역 빠른 루프 vs 레포 로컬 정식 DAG+병렬).
- 서브태스크 분할 기준을 정교한 규모 추정 모델로 만드는 것 — 안 함, `consensus` 단계 agent가 자연스러운 작업 경계로 나누는 것으로 충분(과설계 방지).
