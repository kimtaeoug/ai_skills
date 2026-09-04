# Claude/Codex agent-context git 분리 저장소 설계 (합의안)

Claude·Codex 협업 토론 결과. 참여: Claude(초안), Codex(비평/보강).

## 목표

- Claude·Codex 세션 달라도 실시간 메시지 없이 git으로 context 공유.
- 세션 끊겨도 git 상태만 읽으면 context 복원.
- 실제 개발용 git(브랜치/히스토리/원격)에는 전혀 영향 없음.
- worktree는 agent가 실제 파일 편집할 때만 쓰고, coordination 데이터와는 분리.

## 결론: Option B (별도 bare repo) 채택

Option A(커스텀 ref 네임스페이스), Option C(git notes) 기각 사유:
- A: 개발 repo의 object DB/설정/`git push --mirror` 를 그대로 공유 → 우발적 유출 위험 구조적으로 못 막음.
- C: notes는 커밋에 종속(commit-keyed), 세션 요약처럼 브랜치 독립적인 데이터엔 부적합. rebase/amend 시 `notes.rewriteRef` 안 챙기면 유실.

## 저장 위치

개발 repo와 물리적으로 분리된 bare repo:

```
<development common git dir>/agent-context.git/
<development common git dir>/agent-context-worktrees/<agent>-<session-id>/
```

- `git rev-parse --git-common-dir` 로 각 worktree에서 동일 경로 도출 가능 (linked worktree여도 위치 일관).
- 개발 repo `.git` 과 별개 object/ref/config → `git push --mirror origin` 같은 실수에도 context 데이터 안 실림 (구조적 격리, refspec 설정만으론 불충분).

## Ref 구조: 세션당 X, agent당 O (2차 개정)

**개정 사유**: 세션당 ref(`agent-context/codex/<session-uuid>`)는 새 세션이 뜰 때마다 빈 ref로 시작 → 이전 세션 이어가려면 "지난 세션 ref 찾기"를 수동/컨벤션으로 해야 함(깨지기 쉬움). Codex 재검토 결과 채택:

```
refs/heads/agent-context/claude
refs/heads/agent-context/codex
```

- agent당 **영구 ref 1개**. 세션은 ref 안 만들고, 그 ref 위에 커밋만 이어 붙임(append).
- `session:` 필드는 ref 이름이 아니라 **커밋 메타데이터**로만 기록(provenance 용도).
- 완전 정확한 "직전 세션 이어받기"(동일 스레드 계승)가 필요하면 agent 이름만으론 불충분 — 이어받을 continuation commit-OID를 명시적으로 넘겨야 함. (동시에 같은 agent 세션 2개가 겹칠 때만 해당하는 edge case, 일반적으론 tip이 곧 이어받을 지점.)

### append 프로토콜 (CAS + rebuild-retry)

`update-ref`는 원자적 포인터 교체만 보장, `<new>`가 `<old>`의 자손인지는 검증 안 함 → "fast-forward만 허용"은 프로토콜로 직접 강제해야 함:

1. 현재 tip 읽음 (`old`).
2. `old`를 parent로 이벤트 커밋 생성 (`new`).
3. `git update-ref refs/heads/agent-context/<agent> <new> <old>` (CAS).
4. 실패하면(다른 프로세스가 먼저 갱신) **같은 커밋 재사용 금지** — tip 재조회 → parent를 새 tip으로 다시 빌드 → 재시도. (동일 커밋 그대로 재시도하면 형제 커밋이 체인에서 조용히 유실될 수 있음.)
- crash 안전성: ref 갱신 전 죽으면 unreachable object만 남고 ref는 그대로. 갱신 후 죽으면 old/new 둘 중 하나로 확정, ref 자체가 깨지진 않음(단, 전원 손실 시 durability는 `core.fsync` 설정에 의존 — CAS가 이걸 보장하진 않음).

## 이벤트 커밋 포맷

커밋 1개 = 이벤트 1개 (`event.md` 등):

```
type: plan | decision | summary | checkpoint
author: claude | codex
session: <uuid>
timestamp: <UTC ISO8601>
seen: [<context-commit-id>, ...]   # 참고한 이전 이벤트
supersedes: <commit-id>            # optional
responds-to: <commit-id>           # optional
covers_through: <parent-oid>       # checkpoint 커밋 전용
```

## Checkpoint (rollup) — 무한 히스토리 재구성 방지

- 순수 raw event 커밋만 쌓이면 새 세션이 매번 전체 히스토리를 훑어야 함(무제한 성장) → checkpoint 도입.
- **추가 전용**(append-only). squash/rewrite 금지 — raw 히스토리는 parent 링크로 그대로 보존.
- 트리거: 이벤트 ~20개마다, 또는 세션 종료(clean handoff) 시.
- checkpoint 커밋 내용: `kind: checkpoint`, `covers_through: <parent-oid>`, 자기완결 요약(goal, 확정된 decision/invariant, 완료 작업, 진행 중 plan, 다음 action, 열린 질문).

## 세션 프로토콜 (resume 포함)

- **시작(resume)**: common git dir 확인 → agent-context.git 열기 → (cross-clone 필요시 `agent-store` fetch) → 자기 agent ref의 first-parent 체인을 최신 `checkpoint` 커밋까지 역주행 → 그 checkpoint 로드 → checkpoint 이후(covers_through~tip) 이벤트를 오래된 순으로 replay → 다른 agent ref도 같은 방식으로 최신 상태 파악.
  - tip만 읽는 방식(X): 매 이벤트가 풀 스냅샷 아니면 정보 손실.
  - 고정 N개만 역주행(X): 필요한 context가 N보다 오래됐을 수 있음.
  - 전체 히스토리 역주행(X, checkpoint 없으면 정답이지만 무제한 growth).
- 진행 중: 중요 결정 전 자기 agent ref에 append 프로토콜로 plan/decision 이벤트 커밋.
- 종료: summary 이벤트 커밋 (필요시 바로 checkpoint로 승격) → cross-clone 필요시 자기 ref만 `agent-store`에 push.
- 데몬 불필요, 완전 비동기. 동시 세션(같은 agent) 발생 시 CAS+rebuild-retry로 처리.

## 원격 격리 (cross-clone 동기화 시)

context repo 전용 remote만 사용, 개발 remote URL과 절대 공유 금지:

```ini
[remote "agent-store"]
  fetch = +refs/heads/agent-context/*:refs/remotes/agent-store/agent-context/*
  push  = refs/heads/agent-context/*:refs/heads/agent-context/*
```

- context repo에 `pre-push` hook: 목적지가 `agent-store` 아니거나 대상 ref가 `refs/heads/agent-context/` 밖이면 거부 (defense-in-depth, 강제 아님 — hook은 우회 가능).
- 진짜 강제는 `agent-store` 쪽 서버 receive policy 뿐.

## Git 내부 관련 주의사항 체크리스트

- [ ] 진짜 orphan 커밋 만들지 말 것 — 보존할 이벤트는 반드시 named 세션 ref로 reachable하게. reflog는 임시 복구 수단일 뿐(unreachable object는 기본 2주 후 gc prune 대상, reflog는 reachable 90일/unreachable 30일 만료).
- [ ] 공유 mutable context 브랜치 쓰지 말 것 — writer/세션당 ref 1개로 race 제거.
- [ ] 동일 ref 다중 writer 시 CAS(`update-ref` old-value 체크) 필수.
- [ ] 개발 repo에는 agent-context 관련 ref/object 아예 안 둘 것 (Option A 재기각 이유).
- [ ] fetch/push refspec은 `refs/heads/agent-context/*` 로만 좁힐 것 — 넓은 매핑은 prune 대상도 넓어짐.
- [ ] linked worktree는 `refs/*` 공유하지만 `HEAD`/index/worktree 메타데이터는 worktree별 별도.
- [ ] git notes 쓰지 않기로 결정(위 사유). 혹시 나중에 쓰게 되면 `notes.rewriteRef` 명시 설정 + rebase 경로 테스트 필수.
- [ ] history rewrite/migration 도구 쓸 일 생기면 커스텀 ref/notes 보존 여부 명시적으로 검증.

## 트레이드오프 / 리스크

- bare repo 하나 더 관리해야 함 (경로: common git dir 하위, 개발자가 직접 볼 일 거의 없음).
- cross-machine 동기화하려면 `agent-store` 원격(서버) 별도 구축 필요 — 같은 클론 내에서만 쓸 거면 로컬 bare repo만으로 충분.
- append-only라 오래 쌓이면 정리(archival/squash) 정책 필요 — 이번 라운드에서 미정, 후속 이슈.

## 구현 완료: 코어 CLI

`nimbalyst-local/agent-context/agent-context.sh` — init/append/checkpoint/resume/log/status. 위 설계(bare repo 분리, agent당 영구 ref, CAS+rebuild-retry append, checkpoint/resume) 그대로 구현·검증됨. 스모크 테스트: `smoke-test.sh`.

## 3차 토론: 세션 시작 자동화 (훅/스킬 온보딩)

**요구사항**: 워크스페이스 새로 시작할 때 자동으로 (a) 이미 세팅됐으면 context 이어받기, (b) 안 됐으면 켤지 제안. 별도로 사용자가 명시 요청하면 그 워크스페이스에 세팅.

### 검증된 사실 (Codex 조사, WebFetch/WebSearch로 교차검증 — 추측 아님)

- **Claude Code**: `.claude/settings.json`의 `SessionStart` 훅. matcher `startup|resume` (compact/clear 제외해야 재발화 방지). 훅 stdout이 세션 context로 주입되는데 **10,000자 캡** 있음 — 넘으면 파일로 spill, 인라인 주입 안 됨. 그래서 훅 출력은 반드시 유계(bounded) 요약이어야 함.
- **Codex CLI**: 마찬가지로 진짜 존재하는 `SessionStart` 훅. `.codex/hooks.json` 또는 `.codex/config.toml`의 `[hooks]` 테이블. matcher `startup|resume`. **`.codex/config.toml`에 `[features] codex_hooks = true`(및 `hooks = true`) 필요**. openai/codex GitHub 이슈로 실존 교차검증됨.
- **Codex CLI도 Skill 개념 있음**: `SKILL.md` 하나가 Claude Code와 Codex CLI 양쪽에서 그대로 동작하는 공통 포맷(OpenAI 공식 문서 확인). 전역 위치(`~/.codex/skills/<name>/`) 또는 프로젝트 위치(`.codex/skills/<name>/`)에서 탐색.

### 설계 결정

- 스킬 하나(`SKILL.md`)를 Claude/Codex 공용으로 작성 — **워크스페이스마다 복사하지 않고, 전역(`~/.claude/skills/`, `~/.codex/skills/`)에 1회만 설치**(`bootstrap.sh`가 패키지 전체를 심볼릭 링크). 그래야 어느 워크스페이스에서 처음 켤 때도 스킬을 이미 알고 있음 (세션 독립성 핵심 요구사항).
- 워크스페이스별로는 **런타임만 vendoring**: `install.sh`가 대상 repo의 `.agent-context/`에 `agent-context.sh` + `hooks/onboard.sh` 복사, store init, `.claude/settings.json`/`.codex/hooks.json`/`.codex/config.toml`에 훅 설정을 **멱등 병합**(덮어쓰기 아님 — 기존 다른 훅/설정 보존).
- 훅 진입점 `hooks/onboard.sh <agent>`: store 없으면 "설정 안 됨" 한 줄만 출력(자동 init 안 함 — 명시적 승인 필요). store 있으면 `resume` 결과를 8,000자(안전 마진) 이내로 잘라서 출력 — 자르는 순서는 checkpoint 본문은 보존, replay된 이벤트 중 오래된 것부터 버림.

### 리뷰에서 발견해 수정한 critical 이슈

1차 구현에서 `install.sh`가 `SKILL.md`만 대상 repo `.claude/skills/`, `.codex/skills/`에 복사하고 `install.sh` 자체는 안 가져감 → 설치된 SKILL.md 안에 `SOURCE_PACKAGE=/path/to/agent-context-source-package` 플레이스홀더가 그대로 남아 새 세션이 그 경로를 알 방법이 없었음(세션 독립성 요구사항 정면으로 깨짐). 수정: 패키지 전체를 평평하게(SKILL.md/install.sh를 agent-context.sh/hooks/templates와 같은 레벨로) 재구성하고, 대상 repo에는 스킬 자체를 복사하지 않는 구조로 변경(위 "설계 결정" 참고).

### 최종 패키지 구조

```
nimbalyst-local/agent-context/
├── agent-context.sh        # 코어 CLI
├── SKILL.md                # 설정 스킬(자기 옆 install.sh를 상대경로로 참조, 플레이스홀더 없음)
├── install.sh               # 대상 repo에 vendoring + store init + 훅 설정 멱등 병합
├── bootstrap.sh              # 1회성: 패키지 전체를 ~/.claude/skills, ~/.codex/skills 에 심볼릭 링크
├── hooks/onboard.sh          # SessionStart 훅 진입점
├── templates/                # claude-settings.hooks.json, codex-hooks.json, codex config.toml 조각
├── smoke-test.sh / onboarding-smoke-test.sh
└── README.md
```

### 온보딩 흐름

1. `bootstrap.sh` 1회 실행 → 스킬이 모든 워크스페이스에서 전역으로 발견됨.
2. 새 워크스페이스 세션 시작 시 훅 자동 실행 → store 있으면 context 주입, 없으면 제안만.
3. 사용자/에이전트가 스킬 실행 → `install.sh <repo>`가 해당 워크스페이스에 실제 세팅.

## 다음 단계 (미정, 사용자 결정 필요)

1. cross-machine 동기화(agent-store 서버) 당장 필요한지 여부 — 이번 구현엔 미포함.
2. 이벤트 보존 기간/정리 정책.
3. `bootstrap.sh`를 사용자의 실제 `~/.claude/skills`, `~/.codex/skills`에 실행할지 여부(전역 시스템 변경이라 별도 확인 필요).
