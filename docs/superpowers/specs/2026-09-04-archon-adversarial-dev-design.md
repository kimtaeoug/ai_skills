# archon-adversarial-dev 스킬 — 설계

날짜: 2026-09-04
관련: `~/.claude/commands/cc-loop.md` (기존 Claude+Codex 협업 루프, 이 스킬의 로직 기반), `coleam00/Archon` (워크플로 DAG 개념 참고 원본 — 실제 설치는 안 함), `.claude/skills/test-agent-team/SKILL.md` (이 레포의 project skill 배치 패턴), Workflow 툴(agent()/parallel()/pipeline() 오케스트레이션), `codex:codex-rescue` 서브에이전트를 통한 실제 Codex 비평(아래 "외부 참고 + Codex 비평" 반영 항목)

## 목적

`~/.claude/commands/cc-loop.md`는 Claude+Codex 협업 루프(공동계획 → Codex 구현 → Claude 리뷰 → 반복)를 이미 구현하고 있지만, 전역 슬래시 커맨드로 존재하며 단계 경계가 산문 지시문 안에만 있고, 큰 작업도 항상 통짜로(Codex 한 번 호출, 리뷰 한 번 호출) 처리한다.

이 스킬은 같은 로직을 **이 레포의 project skill**로 재구성하되:
1. Archon의 워크플로 DAG 개념(명시적으로 이름 붙은 노드, 노드마다 산출물)을 빌려 각 단계를 명시적으로 만들고,
2. 시간이 오래 걸리거나 덩치가 큰 작업은 **서브태스크로 쪼개 서브에이전트로 병렬 실행**한다(구현·리뷰 단계).

실제 Archon 툴(bun CLI, YAML 워크플로 엔진)은 설치하지 않는다 — 개념만 차용한다. 이 세션에 있는 **Workflow 툴**(`agent()`/`parallel()`/`pipeline()`)을 실행 엔진으로 쓴다 — 서브태스크 병렬 처리가 필요해진 시점에 SKILL.md 절차서 방식(순차 해석)보다 Workflow 스크립트가 자연스럽기 때문(사용자 확정, 브레인스토밍 중 방향 전환).

역할은 cc-loop과 동일하게 고정: **구현은 Codex만, 리뷰는 Claude만** 수행한다. 계획 단계에서만 Codex가 비평자로 개입한다. 두 에이전트가 서로의 구현물을 독립적으로 만들어 상호 비판하는 진짜 양방향 대립 구조는 이번 범위에 넣지 않는다(사용자 확정).

### 외부 참고 + Codex 비평 반영

secondsky/claude-skills, harness/harness-skills는 도메인 특화 스킬 모음(프론트엔드/API, Harness CI/CD)이라 이 설계와 직접 관련 없어 반영 안 함. awesome-codex-cli(서브에이전트 parallel fan-out 컨벤션)와 repository-harness(작은 수정 vs 다중세션 변경 구분)를 참고해 `codex:codex-rescue`에 직접 비평을 구했고, 아래를 반영했다(비용 대비 이득이 명확한 항목 + 사용자가 추가 승인한 두 항목):

1. **fan-out 상한**: `implement`/`review` 모두 wave/그룹당 동시 실행 최대 4개, nested 서브에이전트 delegation 금지(depth=1) — 폭주 방지.
2. **서브태스크 file ownership + contract 명시**: `dependsOn`만으로는 같은 파일/API/스키마를 건드리는 의미적 결합을 못 잡는다 — `consensus`가 서브태스크별로 이를 명시하고 겹치면 병렬 금지, 단일 태스크로 병합.
3. **wave별 validate**: 전체 끝에서만이 아니라 매 wave 완료 직후 집계 validate 실행 — 잘못된 태스크 경계를 조기 발견.
4. **다음 wave에 실제 diff 첨부**: 이전 wave agent에게는 계획 문서가 아니라 실제로 생성된 diff/변경 파일을 넘겨 최신 상태로 작업.
5. **리뷰어 독립 lens**: 같은 `plan`/`consensus` 추론에서 파생된 병렬 리뷰어들이 같은 맹점을 공유하지 않도록, 리뷰 프롬프트에 요구사항/테스트 갭·통합/회귀·보안/동시성 3개 lens를 고정 체크리스트로 명시.
6. **finding 스키마 강제**: 리뷰 finding마다 영향 코드 위치, 실패 경로/재현, severity, 필요한 테스트를 필수 필드로.
7. **baseline 캡처**(사용자 추가 승인): `preflight`에서 codex ping과 별개로 기존 빌드/테스트를 한 번 돌려 `baseline.md`로 저장 — 새 회귀와 기존 실패를 구분하는 기준선.
8. **iterate triage**(사용자 추가 승인): wave 집계 validate가 개별 서브태스크로 못 좁혀지는 통합 실패를 내면, 실패 서브태스크만 재투입하지 않고 triage로 새 서브태스크를 만들어 다음 라운드 `implement`에 추가.

trivial-fix 분기(작은 변경은 계획 단계 스킵)와 scope 기반 review 스킵은 반영 안 함 — 서브태스크 리스트가 항목 1개일 때 이미 같은 코드 경로로 자연 처리되므로 별도 분기를 추가하면 오히려 지금 설계가 지키던 "분기 없음" 원칙을 깨뜨린다(과설계 방지).

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
| `preflight` | Codex(ping) + Bash(기존 빌드/테스트 1회) | - | 없음(ping 실패시 안내 후 중단) + `baseline.md`(기존 실패/통과 기준선) |
| `plan` | 워크플로 agent (Claude 계열) | - | `plan.md` |
| `critique` | Codex agent, read-only | - | `critique.md` (충돌 크면 `critique-2.md`) |
| `consensus` | 워크플로 agent | - | `consensus-plan.md` + 서브태스크 목록(JSON, file ownership/contract 포함, 아래 참조) |
| `implement` | Codex agent, 서브태스크당 1개 | wave 단위 `parallel()`, wave당 동시 최대 4개·depth=1 | 서브태스크별 구현 결과(diff) → 다음 wave/`report.md`에 누적 |
| `validate` | Bash(빌드/테스트) | - | wave마다 `validation-wave-N.md` + 최종 `validation-round-N.md`(baseline 대비 신규 회귀만 표시) |
| `review` | 워크플로 agent, 서브태스크당 1개(3-lens 체크리스트 고정) | `parallel()`, 동시 최대 4개·depth=1 | 서브태스크별 리뷰(finding 스키마: 위치·재현·severity·필요 테스트) → `review-round-N.md`로 합산 |
| `decision` | 스크립트 제어 흐름(JS) | - | pass면 `report`; 개별 서브태스크 귀책이면 해당분만, 통합 실패(triage)면 새 서브태스크 만들어 `implement` 재진입 |
| `report` | 워크플로 agent | - | `report.md` 최종 |

### 서브태스크 모델

`consensus` 노드가 합의 계획과 함께 서브태스크 목록을 구조화 출력(schema)한다:

```json
{
  "subtasks": [
    { "id": "t1", "description": "...", "dependsOn": [], "ownsFiles": ["src/foo.ts"], "touchesContracts": [] },
    { "id": "t2", "description": "...", "dependsOn": ["t1"], "ownsFiles": ["src/bar.ts"], "touchesContracts": ["FooApi"] }
  ]
}
```

- 안 쪼개도 되는 작은 작업이면 `subtasks`가 항목 1개짜리 리스트다 — **분기 없이 항상 같은 코드 경로**(쪼개는 경우/안 쪼개는 경우를 if로 나누지 않는다, 리스트 길이 1이면 자연히 wave도 1개·parallel도 항목 1개).
- **file ownership / contract 겹침 검사**: `consensus` 산출 직후, `ownsFiles`가 두 서브태스크 사이에 겹치거나 같은 `touchesContracts`(공유 API/스키마/픽스처)를 건드리면 그 서브태스크들을 하나로 병합해 순차 처리한다(둘 다 병렬 wave에 못 들어감) — `dependsOn`만으로는 못 잡는 의미적 결합을 여기서 걸러낸다.
- `implement` 단계: `dependsOn`이 모두 완료된(+ownership 겹침 병합이 끝난) 서브태스크들을 하나의 wave로 묶어 `parallel()`로 동시 실행(wave당 최대 4개, 초과분은 큐잉), 다음 wave로 진행 — 간단한 위상정렬. 각 서브태스크 agent에게는 **자신의 서브태스크 설명 + 그 서브태스크가 의존하는 이전 wave의 실제 diff**(계획 문서 재탕이 아니라)를 첨부한다.
- `validate` 단계: 매 wave 완료 직후 집계 validate 1회(`validation-wave-N.md`), 전체 wave 종료 후 최종 validate(`validation-round-N.md`) — baseline.md와 비교해 신규 회귀만 표시.
- `review` 단계: 완료된 서브태스크 각각에 대해 리뷰어를 `parallel()`로 동시 실행(최대 4개, tool 문서의 "dimensions" 파이프라인 패턴과 동일 모양). 각 리뷰 프롬프트는 요구사항/테스트 갭 · 통합/회귀 · 보안/동시성 3-lens 체크리스트를 고정으로 포함(병렬 리뷰어들이 같은 `plan`/`consensus` 추론에서 파생된 동일 맹점을 공유하지 않도록). 각 finding은 영향 코드 위치·실패 경로 또는 재현·severity·필요한 테스트를 필수 필드로 남긴다.
- `decision`에서 `iterate`가 나오면: 문제가 특정 서브태스크로 명확히 귀책되면 **그 서브태스크만** 다음 라운드 `implement`에 재투입. wave 집계 validate가 개별 서브태스크로 못 좁혀지는 통합 실패(예: 두 서브태스크의 인터페이스 불일치)면 **triage** 서브스텝이 실패 내용을 바탕으로 새 서브태스크(들)를 만들어 추가한다 — 원래 실패 서브태스크만 맹목적으로 재실행하지 않는다.

### Codex 호출 규칙 (cc-loop과 동일한 제약, Workflow `agent()`로 승계)

- Codex 호출은 Workflow `agent()`의 `opts.agentType: "codex:codex-rescue"`로 스폰한다. 실제 end-to-end 실행으로 검증 완료 — `CLAUDE_PLUGIN_ROOT` 환경 문제 없음(아래 "검증 이력" 참조).
- 서브에이전트 기본값은 `--write`이므로, 파일 수정이 필요 없는 호출(critique/review)에는 프롬프트 첫 줄에 `read-only, research/critique only, do not edit files`를 반드시 명시한다.
- 스레드 연속성: `critique`는 `--fresh`. **`implement`도 항상 `--fresh`** — 처음엔 `--resume`(같은 스레드 이어가기)으로 설계했으나, 실제 실행에서 같은 wave 안의 두 서브태스크가 동시에 `--resume`으로 같은 codex 스레드를 이어받으려다 한쪽이 "task busy"로 계속 실패해 빈 diff를 반환하고 그 서브태스크가 review/decision에서 통째로 누락되는 사고가 실측됨(아래 "검증 이력"). `--resume`은 순차 루프(cc-loop) 전제였고 wave-parallel에는 안 맞음 — 대신 서브태스크마다 독립 스레드(`--fresh`)로 시작하고, 필요한 맥락(합의 계획 + 선행 wave 실제 diff)은 항상 프롬프트 텍스트로 명시 전달한다.
- Workflow 동시성 캡(세션당 최대 16개 병렬 `agent()`)을 넘는 대량 서브태스크는 자동으로 큐잉되므로 별도 처리 불필요.
- **implement 결과 검증**: `diff`도 `filesChanged`도 비어있는 서브태스크는 "구현 안 됨"으로 명시 실패 처리한다(review 대상에서 조용히 빠지도록 두지 않는다) — 아래 종료 판정 참조.

### 종료 판정 (cc-loop과 동일한 기준, 대상만 서브태스크 단위로 좁아짐)

- `pass` = 최종 validate가 baseline 대비 신규 회귀 0 **그리고** 모든 서브태스크에서 critical 0 **그리고** implement 결과가 빈 서브태스크(diff·filesChanged 둘 다 없음)가 0.
- `iterate` = 그 외. 귀책이 명확한 critical finding은 해당 서브태스크만, implement가 아예 빈 결과를 낸 서브태스크는 (원인 조사 없이) 곧바로 재투입, 통합 실패면 triage로 만든 새 서브태스크(들)까지 포함해 다음 라운드 `implement`에 재투입.
- `maxRounds`(기본 5, `args.maxRounds`로 override) 초과 시 중단, `report.md`에 최종 상태·잔여 이슈·baseline 대비 신규 회귀·산출물 경로 기록 후 사용자에게 보고.
- **`report.md`는 서브에이전트가 쓰지 않는다**: 하네스가 report/summary 형태 파일 쓰기를 서브에이전트에게 차단하는 정책이 있음이 실측으로 확인됨 — `workflow.mjs`는 report 텍스트를 반환값으로만 돌려주고, `report.md` 파일 쓰기는 Workflow를 호출한 오케스트레이터(SKILL.md를 따르는 쪽, 즉 제한 없는 Write 권한을 가진 orchestrator)가 직접 한다.

## 데이터 흐름

```
[archon-adversarial-dev 트리거]
        │
        ├─ nimbalyst-local/plans/adversarial-dev/<slug>/ 생성(기존 있으면 비움)
        │
        ├─ preflight: codex ping ── 실패 ─→ 사용자 안내, 중단
        │        │ 성공
        │        ├─ 기존 빌드/테스트 1회 → baseline.md
        │        ▼
        ├─ plan.md 작성
        │        │
        ├─ critique.md 작성(Codex read-only) ── 충돌 크면 critique-2.md
        │        │
        ├─ consensus-plan.md + subtasks[](ownsFiles/touchesContracts 포함) 작성
        │        │
        │        ├─ ownership/contract 겹침 검사 → 겹치면 서브태스크 병합
        │        ▼
        ┌─── implement: wave로 묶어 parallel()(wave당 최대 4개) 반복
        │        │        각 agent에 서브태스크 설명 + 선행 wave 실제 diff 첨부
        │        ▼
        │   validate: wave마다 집계(validation-wave-N.md) + 최종(validation-round-N.md, baseline 대비 신규 회귀만)
        │        │
        │   review: 완료 서브태스크마다 parallel()(최대 4개) 3-lens 리뷰 → review-round-N.md
        │        │
        │   decision(JS): 신규 회귀/critical 있음? ──Yes──┐
        │        │No                                       │  귀책 명확 → 해당 서브태스크만 재투입
        │        ▼                                          │  통합 실패 → triage로 새 서브태스크 생성 후 재투입
        │   report.md 최종 작성                              │
        │                                                    ▼
        │                                              implement로 복귀
        └────────────────────────────────────────────────────────────────
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
9. **fan-out 폭주 방지**: `implement`/`review` 모두 그룹당 동시 실행 4개 상한 고정, 초과분은 Workflow 큐잉에 맡김. 서브에이전트 내부에서 추가 서브에이전트를 스폰하는 nested delegation은 금지(depth=1) — 프롬프트에 명시.
10. **file ownership/contract 겹침 미검출 시 안전판**: `consensus`가 겹침을 놓쳐도 wave별 집계 validate가 통합 실패를 조기에 잡아내므로, ownership 검사는 최적화이지 유일한 안전장치가 아니다.
11. **baseline 캡처 실패**: preflight의 기존 빌드/테스트 실행 자체가 실패(타임아웃 등)해도 스킬을 중단하지 않는다 — `baseline.md`에 "캡처 실패, 회귀 판정 시 전체 실패를 신규로 간주"라고 명시하고 계속 진행(더 보수적인 fallback).
12. **`args`가 문자열로 도착할 수 있음**: 이 하네스에서 Workflow의 `args`가 문서 스펙(객체)과 다르게 JSON 문자열로 전달되는 경우가 실측됨(원인 불명, 플랫폼 쪽 동작) — `workflow.mjs` 최상단에서 `typeof args === 'string'`이면 `JSON.parse`로 방어적으로 풀어서 쓴다.
13. **implement가 빈 결과를 낼 수 있음**: `--fresh`로 고쳤지만, 그와 무관하게 Codex 호출이 어떤 이유로든 `diff`/`filesChanged` 둘 다 빈 채로 끝나면 해당 서브태스크를 review 대상에서 조용히 빼지 않고 명시적으로 실패 처리해 다음 라운드에 재투입한다(위 종료 판정 참조) — 원인이 무엇이든(스레드 충돌, 타임아웃, 기타) 안전판 역할.

## 검증 이력

1차 end-to-end 실행(두 독립 유틸 스크립트 추가 태스크)에서 실제로 두 가지 문제를 발견하고 고쳤다:

- **wave 내 `--resume` 충돌**: 같은 wave의 두 서브태스크가 동시에 `--resume`으로 같은 codex 스레드를 이어받으려다 하나가 계속 "task busy"를 받고 포기 → 빈 diff 반환 → 그 서브태스크가 review/decision에서 통째로 누락됐는데도 `pass`로 판정됨(다른 서브태스크만 보고 전체를 통과 처리). 원인은 `implement`가 cc-loop의 순차 루프 전제였던 `--resume`을 wave-parallel로 옮기면서 그대로 물려받은 것. `--fresh` + 에러 처리 12번(빈 결과 명시 실패 처리)으로 수정.
- **`report.md` 하네스 정책 충돌**: 서브에이전트가 report/summary 형태 파일을 못 쓰게 막는 하네스 정책에 걸림(우연히 Bash heredoc 우회로 그 실행에서는 통과했지만 안정적인 경로가 아님) — `report.md` 쓰기를 서브에이전트에서 오케스트레이터로 옮겨 근본적으로 해결(위 종료 판정 참조).
- 부수적으로, Workflow의 `args`가 이 하네스에서는 문자열로 도착하는 것도 이때 발견(에러 처리 12번).

2차 실행(같은 태스크, 수정 후)으로 재검증 완료 — `pass`, round 3, 24 agent, 76만 토큰. 흥미로운 점: `--fresh`로 고친 뒤에도 round 1에서 `word-count-sh` implement가 한 번 더 빈 결과(`filesChanged: [], diff: ""`)를 냈다 — 즉 `--resume`이 원인의 전부가 아니라, 동시에 뜬 두 codex 호출이 `codex-companion` 런타임 레벨에서 여전히 경합할 수 있다. 하지만 이번엔 에러 처리 13번(빈 결과 명시 실패 처리)이 정확히 작동해 그 서브태스크만 재시도됐고, round 2에서 성공 → round 2 리뷰가 `slugify.sh`에서 critical(다중 줄 입력 시 `sed`가 pattern space 전체에 걸려 "출력 항상 한 줄" 계약 위반)을 잡아 해당 서브태스크만 재투입 → round 3에서 수정 후 pass. 즉 **"실패를 명시적으로 잡아 재시도"가 `--fresh` 자체보다 더 근본적인 안전장치였다** — `--fresh`는 충돌 빈도를 줄였을 뿐 완전히 없애지 못했지만, 안전판 덕에 결과는 여전히 올바름(대신 라운드 수가 늘어남). 두 유틸 스크립트 모두 최종 `--self-check` 오케스트레이터가 직접 실행해 통과 확인, `report.md`도 오케스트레이터가 직접 Write로 저장 확인.

## 테스트

- 실제 검증: 서브태스크 2개 이상으로 자연히 쪼개지는 실제 작업(예: 독립적인 유틸 함수 2개 추가) 하나를 골라 스킬을 실제로 트리거해서 preflight(baseline.md 생성 확인) → plan → critique → consensus(서브태스크 분할 + ownsFiles/touchesContracts 확인) → implement(wave parallel 확인) → validate(wave별+최종) → review(parallel, 3-lens+finding 스키마 확인) → decision → report까지 한 사이클 실제로 돌리고, `nimbalyst-local/plans/adversarial-dev/<slug>/`에 각 파일이 기대한 이름·내용으로 생성됐는지 육안 확인.
- 단일 서브태스크 경로 확인: 안 쪼개지는 작은 작업으로 한 번 더 돌려서 `subtasks` 길이 1일 때도 동일 코드 경로로 정상 동작하는지 확인(분기 없음 검증).
- ownership 겹침 병합 확인: 일부러 같은 파일을 건드리는 두 서브태스크가 나오는 작업을 골라, `consensus` 직후 병합되어 같은 wave에 나란히 들어가지 않는지 확인.
- iterate 경로 확인(2가지): (a) 서브태스크 중 하나만 명확히 귀책되는 실패 — 그 서브태스크만 재실행되고 나머지는 재실행 안 되는지 확인. (b) 두 서브태스크 인터페이스 불일치로 통합 실패 — triage가 새 서브태스크를 만들어 다음 라운드에 추가하는지 확인.
- 이 스킬은 셸 스크립트가 아니라 SKILL.md+Workflow 스크립트 조합이므로 `smoke-test.sh` 류 자동 테스트는 없음 — 실제 실행이 검증 수단. Workflow의 `resumeFromRunId` 캐시 특성상, 스파이크 실패로 재작업할 때는 캐시된 이전 결과를 참고할 수 있음(참고용, 이 스킬 자체는 resume 기능을 노출하지 않음).

## 범위 밖

- Archon 툴 자체(bun CLI, `.archon/workflows/*.yaml`) 설치 — 안 함, 개념만 차용(사용자 확정).
- Resume(이전 라운드 아티팩트 감지해서 이어가기) — 안 함, 항상 처음부터(사용자 확정, YAGNI).
- 진짜 양방향 adversarial(Claude·Codex 각자 독립 구현 후 서로 비판) — 안 함, 구현=Codex 전담·리뷰=Claude 전담 구조 유지(사용자 확정).
- `cc-loop.md` 슬래시 커맨드 자체를 이 스킬로 대체/삭제 — 안 함, 둘 다 유지(전역 빠른 루프 vs 레포 로컬 정식 DAG+병렬).
- 서브태스크 분할 기준을 정교한 규모 추정 모델로 만드는 것 — 안 함, `consensus` 단계 agent가 자연스러운 작업 경계로 나누는 것으로 충분(과설계 방지).
