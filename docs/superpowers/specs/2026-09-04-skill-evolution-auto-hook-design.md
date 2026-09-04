# 스킬 진화 메커니즘 — 자동화 확장 (Auto-Hook) 설계

이 문서는 [2026-09-04-skill-evolution-mechanism-design.md](2026-09-04-skill-evolution-mechanism-design.md)(이하 "원 설계")를 전제로 한다. 원 설계는 사람이 `/evolve`를 명시적으로 호출해야만 델타를 기록했다. 이 확장은 그 트리거를 자동화한다: 어느 워크스페이스에서든 추적 대상 스킬을 호출하면, 세션이 끝날 때 그 스킬의 변경 델타가 사람 개입 없이 기록된다.

## 배경 및 동기

원 설계의 `/evolve`는 사람이 기억하고 있다가 명시적으로 불러야 동작한다. 실제로는 스킬을 여러 워크스페이스에서 계속 쓰다 보면 `/evolve`를 부르는 걸 잊는다. 이 확장은 "스킬을 쓴다"는 행위 자체가 진화 추적의 시작점이 되게 하고, 기록도 사람에게 묻지 않고 세션 맥락에서 자동으로 채운다.

## 범위

- 추적 대상: `~/.agents/skills/<name>/` 밑에 있는, 콜론(`:`)이 없는 이름의 개인 제작 스킬만. `plugin:skill` 형태(마켓플레이스/플러그인 스킬, 예: `superpowers:brainstorming`)는 제외한다 — 그건 플러그인이 버전관리하는 대상이지 사용자가 직접 고치는 대상이 아니다.
- 훅은 `~/.claude/settings.json`(user-level)에 등록해 모든 프로젝트/워크스페이스에서 동작하게 한다.
- 이 확장은 원 설계의 record 스키마, 저장 위치(`evolution/records|lessons|patterns/`), "승격은 항상 사람" 원칙을 그대로 유지한다. 바뀌는 건 트리거 방식과 record를 채우는 주체(사람 Q&A → Claude의 세션 맥락 추론)뿐이다.

## 아키텍처

```
[세션 중] Skill 툴 호출 (matcher: Skill)
    → PostToolUse hook: bin/evolve track <session_id> <skill-dir>
        - baseline 없으면 자동 snapshot (첫 사용 시점을 baseline으로)
        - evolution/.state/.sessions/<session_id>-touched.txt 에 스킬 기록 (dedup)

[세션 종료 시도] Stop hook
    → bin/evolve pending <session_id> 로 델타 있는 스킬 목록 확인
    → 없으면: 세션 목록 정리, 정상 종료
    → 있으면 (stop_hook_active=false일 때만): decision:"block" + reason으로
       Claude에게 "이 스킬들 record 써라" 지시 → 세션 계속
       (stop_hook_active=true, 즉 이미 한 번 block된 재시도라면: pending 재확인만 하고
        얼마가 남았든 더는 block하지 않고 통과시킨다 — 무한 루프 방지)

[Claude의 추가 턴]
    → 지시받은 각 스킬에 대해, 사람에게 묻지 않고 이 세션의 대화 맥락으로
      context/delta/evidence/candidate_lessons를 채워 record 작성
      (source: auto (session-end hook))
    → 각 스킬에 bin/evolve snapshot 재실행해 baseline을 지금 시점으로 리셋
      (다음 Stop 재시도에서 pending이 비도록 만드는 필수 단계)
    → 세션이 다시 Stop을 시도 → stop_hook_active=true로 재진입 → pending 비어있으면 통과
```

## `bin/evolve` 신규 서브커맨드

훅 스크립트는 이 서브커맨드들을 호출하는 얇은 wrapper로만 존재한다 — 로직은 전부 CLI에 있다 (원 설계의 "CLI는 순수 로직, 스킬/훅은 얇은 wrapper" 원칙 유지).

- `evolve track <session_id> <skill-dir>`
  - `<skill-dir>`에 baseline이 없으면 (기존 `snapshot` 로직 재사용해) 자동 생성.
  - `evolution/.state/.sessions/<session_id>-touched.txt`에 `<skill-dir>`의 basename을 한 줄로 추가한다. 이미 있으면 중복 추가하지 않는다.
- `evolve pending <session_id>`
  - `.sessions/<session_id>-touched.txt`에 나열된 각 스킬에 대해 `diff`를 돌려, 델타가 있는 스킬 이름만 한 줄씩 stdout에 출력한다. 파일이 없거나 비어 있으면 아무것도 출력하지 않는다 (exit 0).
- `evolve clear-session <session_id>`
  - `.sessions/<session_id>-touched.txt`를 삭제한다.

세 서브커맨드 모두 스킬 이름 → 디렉토리 해석은 `~/.agents/skills/<name>`로 고정한다 (원 설계에서 스킬 디렉토리를 인자로 직접 받던 것과 달리, 세션 추적용 서브커맨드들은 이름만으로 동작해야 하므로).

## 구현 전 검증 필요

`PostToolUse`가 Skill 툴 호출 시 `tool_input`에 정확히 `skill`이라는 키로 스킬 이름을 담아 넘기는지는 공식 문서에 명시돼 있지 않다 (Skill 툴 자체의 파라미터 스키마가 `skill`/`args`이므로 그럴 것이라 추정한 것). 구현 첫 단계에서 실제 `PostToolUse` 훅을 임시로 걸어 stdin JSON을 파일에 덤프해보고, 필드명을 실측으로 확정한 뒤 나머지를 진행한다. 필드명이 다르면 이 설계의 `tool_input.skill` 참조를 실측값으로 교체한다.

## 훅 스크립트

두 개의 얇은 shell 스크립트, `bin/hooks/`에 둔다:

- `bin/hooks/evolve-track.sh` — PostToolUse(matcher: Skill)용. stdin JSON에서 `tool_input.skill`을 읽어 콜론이 없으면(개인 스킬) `~/.agents/skills/<skill>`가 실존할 때만 `evolve track <session_id> <dir>` 호출.
- `bin/hooks/evolve-autorecord.sh` — Stop용. stdin JSON에서 `session_id`, `stop_hook_active`를 읽어 위 아키텍처의 분기를 수행하고, block이 필요하면 `{"decision":"block","reason":"..."}`을 stdout에 출력.

두 스크립트 모두 최상단에서 `/Users/deratio/skills/bin/evolve` 존재 여부를 확인하고, 없으면 즉시 exit 0 — 이 저장소가 없는 환경에서도 다른 훅 동작을 방해하지 않는다.

## record 스키마 변경

원 설계의 레코드 필드에 `source` 하나를 추가한다:

```md
skill: <스킬 이름>
source: manual (/evolve) | auto (session-end hook)
baseline: <git SHA 또는 snapshot 경로>
final: <git HEAD 또는 "working tree">
context: <...>
delta: <...>
evidence: <...>
candidate_lessons: <...>
promotion: pending
```

`source`는 나중에 사람이 쌓인 record들을 훑어볼 때 자동 생성분과 수동 기록분을 구분하기 위함이다. 자동 생성 record의 `context`/`evidence`를 사람이 세션 대화 없이도 신뢰할 수 있는지 판단할 때 필요하다.

## Stop hook 지시문(reason) 내용

`reason`은 그 자체로 완결된 지시여야 한다 (원 설계의 대화형 `evolve` 스킬을 호출하는 게 아니라, 별도의 자기완결적 절차). 반드시 포함해야 할 것:

1. 델타가 있는 스킬 이름 목록과 각각의 `evolution/.state/<skill>.txt` 경로.
2. "사람에게 아무것도 묻지 마라. AskUserQuestion을 쓰지 마라. 이 세션의 대화 내용에서 무엇을 왜 바꿨는지 직접 추론해서 채워라."
3. `context`/`evidence`를 세션에서 합리적으로 추론할 수 없으면 억지로 지어내지 말고 `"세션 로그 기반 자동 추론 실패 — 검토 필요"`라고 쓰고 넘어가라는 명시적 허용.
4. record 스키마 전문(위 섹션 그대로).
5. record 작성 후 반드시 `/Users/deratio/skills/bin/evolve snapshot <skill-dir>`를 실행해 baseline을 리셋하라는 지시 — 이걸 안 하면 다음 Stop 시도에서 같은 델타가 또 잡혀 block이 반복된다.

## 안전장치

- `stop_hook_active=true`(이미 한 번 block한 뒤의 재시도)일 때는 pending이 남아있어도 다시 block하지 않는다. Claude Code 자체의 8회 연속 block 제한과 별개로, 이 훅은 "최대 1회만 block"으로 스스로 제한한다 — 델타 기록은 best-effort이지, 세션을 볼모로 잡을 정도로 중요하지 않다.
- `bin/evolve`나 `evolution/` 디렉토리가 없는 환경(이 저장소 밖)에서는 두 훅 스크립트 모두 조용히 exit 0.
- `evolve pending`이 스킬 디렉토리가 이미 삭제된 경우(baseline은 있었는데 스킬이 지워짐) 등 예외 상황을 만나면, 그 스킬은 건너뛰고 나머지는 계속 처리한다 — 하나의 실패가 전체 pending 목록을 막지 않는다.

## 범위 밖 (이번 확장에서 하지 않는 것)

- `evolution/lessons/`, `evolution/patterns/`로의 자동 승격 — 원 설계와 동일하게 항상 사람이 수동으로.
- 프로젝트별 옵트아웃 설정(특정 워크스페이스에서는 자동 추적 끄기) — 필요해지면 다음 확장에서.
- `plugin:skill` 형태의 마켓플레이스 스킬 추적 — 범위 밖.
- 델타가 있는데 Claude가 지시를 무시하고 그냥 넘어가는 경우에 대한 재시도/알림 — best-effort로 두고, 나중에 실제로 자주 발생하면 그때 다룬다.

## 테스트

- `bin/evolve track/pending/clear-session`에 대한 스모크 테스트 3~4개 추가 (기존 `tests/test-evolve.sh`에 케이스 추가): baseline 없는 스킬 track하면 자동 snapshot되는지, 세션 파일에 dedup되는지, pending이 델타 있는 것만 정확히 골라내는지, clear-session이 파일을 지우는지.
- 훅 스크립트 자체(`bin/hooks/*.sh`)는 실제 Claude Code 세션 없이 stdin으로 가짜 JSON을 흘려보내 최소 1개씩 수동/스크립트 테스트로 검증한다 (Stop hook의 block JSON 출력 형식, PostToolUse의 skip 조건 등).
