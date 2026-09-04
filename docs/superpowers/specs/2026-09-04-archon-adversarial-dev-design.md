# archon-adversarial-dev 스킬 — 설계

날짜: 2026-09-04
관련: `~/.claude/commands/cc-loop.md` (기존 Claude+Codex 협업 루프, 이 스킬의 로직 기반), `coleam00/Archon` (워크플로 DAG 개념 참고 원본 — 실제 설치는 안 함), `.claude/skills/test-agent-team/SKILL.md` (이 레포의 project skill 배치 패턴)

## 목적

`~/.claude/commands/cc-loop.md`는 Claude+Codex 협업 루프(공동계획 → Codex 구현 → Claude 리뷰 → 반복)를 이미 구현하고 있지만, 전역 슬래시 커맨드로 존재하며 단계 경계가 산문 지시문 안에 암묵적으로만 있고 중간 산출물은 최종 합의 계획 하나만 파일로 남는다.

이 스킬은 같은 로직을 **이 레포의 project skill**로 재구성하되, Archon의 워크플로 DAG 개념(명시적으로 이름 붙은 노드, 노드마다 산출물)을 빌려 각 단계를 명시적으로 이름 붙이고 단계별 산출물을 디스크에 남긴다. 실제 Archon 툴(bun CLI, YAML 워크플로 엔진)은 설치하지 않는다 — 개념만 차용한다.

역할은 cc-loop과 동일하게 고정: **구현은 Codex만, 리뷰는 Claude만** 수행한다. 계획 단계에서만 Codex가 비평자로 개입한다. 두 에이전트가 서로의 구현물을 독립적으로 만들어 상호 비판하는 진짜 양방향 대립 구조는 이번 범위에 넣지 않는다(사용자 확정).

## 아키텍처

새 컴포넌트를 만들지 않고 기존 두 가지를 재사용한다:
- `codex:codex-rescue` 서브에이전트 — Codex 호출 경로 (cc-loop과 동일한 호출 규칙, 아래 참조)
- `nimbalyst-local/plans/` — 산출물 저장 위치 (cc-loop이 쓰던 `<slug>-cc.md` 단일 파일 대신, 이 스킬은 슬러그별 디렉터리에 단계별 파일을 남긴다)

### 배치

`.claude/skills/archon-adversarial-dev/SKILL.md` — `test-agent-team`과 같은 자리, project skill.

Frontmatter:
```yaml
---
name: archon-adversarial-dev
description: >
  Claude+Codex 협업 개발 루프를 Archon 스타일 DAG(공동계획→비평→합의→Codex 구현→Claude
  리뷰→반복)로 실행한다. 각 단계 산출물을 파일로 남긴다. 항상 처음부터 새로 실행(resume 없음).
  Trigger phrases — 한국어: "adversarial dev로 구현해줘", "codex랑 대립 개발 해줘",
  "archon 스타일로 codex 협업 루프 돌려줘"; English: "run archon-adversarial-dev",
  "adversarial dev loop with codex".
---
```

### 페이즈 (DAG)

```
preflight → plan → critique → consensus → implement → validate → review → decision
                                              ↑                              │
                                              └──────────── iterate ─────────┘
                                                                              │
                                                                            pass
                                                                              │
                                                                              ▼
                                                                            report
```

| 노드 | 수행 주체 | 파일 I/O 없는 호출 표기 | 산출물 |
|---|---|---|---|
| `preflight` | Codex(ping) | read-only | 없음 (실패시 `/codex:setup` 안내 후 중단) |
| `plan` | Claude | - | `plan.md` |
| `critique` | Codex | read-only, critique only | `critique.md` (2라운드까지면 `critique-2.md` 추가) |
| `consensus` | Claude | - | `consensus-plan.md` |
| `implement` | Codex | `--write` | 코드 변경 (파일 목록은 `report.md`에 누적 기록) |
| `validate` | Claude(Bash) | - | 콘솔 출력을 `validation-round-N.md`에 기록 |
| `review` | Claude | - | `review-round-N.md` (critical/major/minor 태깅) |
| `decision` | Claude | - | 없음 — pass면 `report`로, iterate면 `implement`로 회귀 |
| `report` | Claude | - | `report.md` 최종 갱신 |

각 노드의 내부 절차·프롬프트 문구·판정 기준은 `cc-loop.md`의 A~D 섹션 로직을 그대로 가져온다 (아래 "Codex 호출 규칙" 포함). 이 스킬이 추가하는 건 (1) 노드 경계 명시, (2) 단계별 파일 산출물, (3) project skill 트리거 방식이다.

### 산출물 디렉터리

`nimbalyst-local/plans/adversarial-dev/<slug>/`

- `<slug>` = 작업 설명을 kebab-case로 축약 (cc-loop과 동일한 규칙)
- **실행 시작 시 동일 slug 디렉터리가 이미 있으면 비우고 새로 만든다** (resume 없음 — 사용자 확정. 매번 처음부터).
- 라운드가 여러 번 도는 `validation-round-N.md` / `review-round-N.md` 는 각 라운드 번호별로 별도 파일로 남긴다(덮어쓰지 않음) — 반복 이력을 남겨서 나중에 몇 라운드 만에 수렴했는지 확인 가능하게.

### Codex 호출 규칙 (cc-loop과 동일, 그대로 승계)

- Codex는 항상 `codex:codex-rescue` 서브에이전트로만 호출한다(Agent tool, `subagent_type: "codex:codex-rescue"`). `codex-companion.mjs`를 Bash로 직접 호출하지 않는다(`CLAUDE_PLUGIN_ROOT` 환경 미보장).
- 서브에이전트 기본값은 `--write`(개발 모드)이므로, 파일 수정이 필요 없는 호출(비평/리뷰)에는 프롬프트 첫 줄에 `read-only, research/critique only, do not edit files`를 반드시 명시한다.
- 스레드 연속성: 계획 단계 비평 호출은 `--fresh`, 개발 단계(`implement`)는 `--resume`을 프롬프트에 명시한다.
- resume은 best-effort(비-git 워크트리에서 끊길 수 있음)이므로 `implement` 프롬프트에는 항상 합의 계획(`consensus-plan.md`) 전문을 실어 Codex가 맥락 없이도 작업 가능하게 한다.

### 종료 판정 (cc-loop과 동일)

- `pass` = 빌드/테스트 OK **그리고** critical 이슈 0.
- `iterate` = 그 외. 리뷰 지적사항을 명확한 수정 지시로 Codex에 돌려주고 `implement`부터 재진입.
- `--max-rounds`(기본 5, 인자로 override) 초과 시 더 돌리지 않고 현재 상태·통과/실패 검증·잔여 critical/major·산출물 디렉터리 경로를 정리해 사용자에게 보고 후 중단.

## 데이터 흐름

```
[archon-adversarial-dev 트리거]
        │
        ├─ nimbalyst-local/plans/adversarial-dev/<slug>/ 생성(기존 있으면 비움)
        │
        ├─ preflight: codex ping ── 실패 ─→ 사용자에 /codex:setup 안내, 중단
        │        │ 성공
        │        ▼
        ├─ plan.md 작성 (Claude)
        │        │
        ├─ critique.md 작성 (Codex read-only) ── 충돌 크면 1회 더(critique-2.md)
        │        │
        ├─ consensus-plan.md 작성 (Claude)
        │        │
        │        ▼
        ┌─── implement (Codex --write --resume, consensus-plan.md 전문 첨부)
        │        │
        │   validation-round-N.md (Claude, Bash 빌드/테스트)
        │        │
        │   review-round-N.md (Claude, severity 태깅)
        │        │
        │   decision: pass? ──No(iterate)──┐
        │        │Yes                       │
        │        ▼                          │
        │   report.md 최종 작성              │
        │                                    │
        └────────────────────────────────────┘
             (round > max-rounds 이면 report.md에 중단 사유 기록 후 종료)
```

## 에러 처리

1. **preflight 실패**: 빈 응답/실패 시 진행 안 함, `/codex:setup` 안내 후 중단(cc-loop과 동일).
2. **슬러그 디렉터리 충돌**: 시작 시 무조건 비움 — 이전 실행 잔여물이 이번 판정에 섞이지 않도록.
3. **critique 무한 루프 방지**: 계획 단계 토론은 최대 2라운드로 상한, 그 이후도 핵심 결정이 갈리면 `AskUserQuestion`으로 사용자에게 넘긴다(cc-loop과 동일).
4. **max-rounds 초과**: 무한 반복 방지, 중단 후 현재 상태 보고(cc-loop과 동일).
5. **Codex 직접 Bash 호출 금지**: 항상 서브에이전트 경로로만 — 환경변수 미정의로 인한 조용한 실패 방지.
6. **read-only 표기 누락 방지**: 비평/리뷰용 Codex 호출 프롬프트에는 매번 첫 줄에 `read-only, research/critique only, do not edit files`를 강제 — 실수로 Codex가 리뷰 단계에서 파일을 고치는 사고 방지.

## 테스트

- 실제 검증: 사소한 실제 작업(예: 이 레포 안의 작은 유틸 함수 하나) 하나를 골라 스킬을 실제로 트리거해서 preflight → plan → critique → consensus → implement → validate → review → decision → report까지 한 사이클 실제로 돌리고, `nimbalyst-local/plans/adversarial-dev/<slug>/`에 각 파일이 기대한 이름과 내용으로 생성됐는지 육안 확인.
- iterate 경로 확인: review에서 의도적으로 critical 이슈를 잡아내는 상황(또는 실제로 발생한 이슈)에서 `implement`로 정상 회귀하고 `review-round-2.md`가 새로 생기는지 확인.
- 이 스킬은 셸 스크립트가 아니라 SKILL.md 절차서이므로 `smoke-test.sh` 류 자동 테스트는 없음 — 실제 실행 1회가 검증 수단.

## 범위 밖

- Archon 툴 자체(bun CLI, `.archon/workflows/*.yaml`) 설치 — 안 함, 개념만 차용(사용자 확정).
- Resume(이전 라운드 아티팩트 감지해서 이어가기) — 안 함, 항상 처음부터(사용자 확정, YAGNI). 필요해지면 별도 확장.
- 진짜 양방향 adversarial(Claude·Codex 각자 독립 구현 후 서로 비판) — 안 함, 구현=Codex 전담·리뷰=Claude 전담 구조 유지(사용자 확정).
- 리뷰 단계를 Archon 예시처럼 error-handling/test-coverage/docs-impact 등 여러 서브 에이전트로 세분화 — 안 함, cc-loop과 동일하게 Claude 단일 리뷰 유지(과설계 방지).
- `cc-loop.md` 슬래시 커맨드 자체를 이 스킬로 대체/삭제 — 안 함, 둘 다 유지(전역 빠른 루프 vs 레포 로컬 정식 DAG).
