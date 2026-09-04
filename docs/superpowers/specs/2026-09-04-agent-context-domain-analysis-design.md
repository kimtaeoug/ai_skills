# agent-context 도메인 분석 확장 — 설계

날짜: 2026-09-04
관련: `nimbalyst-local/plans/agent-context-git-store-cc.md` (agent-context 코어), `nimbalyst-local/agent-context/` (구현체)

## 목적

`agent-context-setup` 스킬로 워크스페이스를 세팅할 때, 그 레포지토리가 어떤 비즈니스/문제 도메인을 다루고 어떤 기술 스택으로 만들어졌는지를 에이전트(Claude/Codex)가 직접 읽고 요약해서, agent-context store에 공유 저장한다. 이후 다른 세션/다른 agent가 필요할 때 조회해서 "이 레포가 뭐 하는 곳인지" 빠르게 파악할 수 있게 한다.

세션 시작 훅(`onboard.sh`)에는 자동 주입하지 않는다 — 필요할 때 명시적으로 조회하는 방식으로 둔다(10,000자 훅 출력 캡을 도메인 요약이 잠식하지 않도록).

## 아키텍처

기존 `nimbalyst-local/agent-context/agent-context.sh`에 도메인 채널을 하나 추가하는 형태로 확장한다. 새 컴포넌트를 만들지 않는다.

### 저장 구조

- 새 ref: `refs/heads/agent-context/domain` — claude/codex 세션 ref와 별개인, 공유·append-only 채널 하나.
- 이벤트 헤더 스키마(`type`)에 `domain` 값 추가. 기존 `plan | decision | summary | checkpoint`에 이어 `plan | decision | summary | checkpoint | domain`.
- 커밋 body = 자유 텍스트, 두 섹션 고정 포맷:
  ```
  ## Business domain
  <내용, 또는 insufficient evidence>
  confidence: high | medium | low | insufficient evidence

  ## Technical stack
  <내용, 또는 insufficient evidence>
  confidence: high | medium | low | insufficient evidence
  ```
- 재분석하면 새 커밋이 이전 tip을 parent로 append(히스토리에 이전 버전 보존, 덮어쓰지 않음).
- 미러 파일 `.agent-context/DOMAIN.md`: 최신 도메인 문서 본문을 그대로 복사해 둔 캐시. source of truth는 git 커밋, 이 파일은 CLI 없이 빠르게 읽기 위한 파생물.

### CLI 추가 (`agent-context.sh`)

- `domain-set --target <repo>` — stdin으로 body를 받아:
  1. body가 공백/빈 문자열이면 `die`, 커밋 생성 안 함.
  2. 기존 append 프로토콜(CAS `update-ref` + 실패시 rebuild-retry) 그대로 재사용해 `refs/heads/agent-context/domain`에 `type: domain` 커밋 생성.
  3. 성공하면 `.agent-context/DOMAIN.md`를 mktemp+mv로 원자적 갱신(symlink 안전 — mv는 심볼릭 링크 자체를 교체, 타겟을 따라가지 않음).
- `domain-show --target <repo>` — domain ref tip이 없으면 `No domain analysis yet for this repo.` 출력 후 정상 종료(exit 0, git 원본 에러 노출 안 함). 있으면 최신 커밋의 body를 출력.
- `status --target <repo>` — claude/codex tip에 이어 domain tip도 같이 출력하도록 확장.
- `validate_type`에 `domain` 추가. `validate_agent`는 건드리지 않음 — domain은 "agent" 정체성이 아니라 별도 고정 채널이므로 `ref_for`/append 로직 내부에서 `domain`이라는 이름을 claude/codex와 같은 매개변수 자리에 놓고 재사용하되, CLI 표면(`domain-set`/`domain-show`)에서만 노출한다.

### 스킬(`agent-context-setup`) 흐름 확장

`SKILL.md`에 아래 단계 추가 (install.sh 실행 이후):

1. `.agent-context/agent-context.sh domain-show --target <repo>` 로 기존 도메인 문서 존재 여부 확인.
2. 이미 있으면 스킵 — "이미 도메인 분석 있음, 다시 하려면 명시적으로 요청하라"고 사용자에게 짧게 안내.
3. 없으면 분석 수행:
   - 읽는 범위를 명시적으로 제한: `README*`, 최상위 매니페스트 파일(`package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `pom.xml` 등 존재하는 것만), 디렉터리 구조 최상위 2단계까지. 전체 재귀 읽기 금지(대형 모노레포 폭주 방지).
   - Business domain: 이 프로젝트가 무엇을 위한 것인지, README/설명에 실제로 근거가 있는 것만 기술. 근거 없으면 추측하지 말고 `insufficient evidence`.
   - Technical stack: 감지된 언어/프레임워크/런타임/아키텍처 스타일(모놀리스/CLI/라이브러리/마이크로서비스 등). 매니페스트/디렉터리 구조에서 실제로 확인된 것만.
   - 위 두 섹션 + confidence를 고정 포맷으로 작성.
4. `domain-set --target <repo>`로 저장.
5. 분석 단계에서 에러가 나도 setup 전체를 실패로 처리하지 않음 — install.sh의 vendoring/store init/훅 설정은 이미 별개로 완료된 상태이므로, 도메인 분석만 실패로 보고하고 "나중에 `domain-set` 수동 재시도 가능"이라고 안내.

## 데이터 흐름

```
[agent-context-setup 스킬 실행]
        │
        ├─ install.sh (기존, 변경 없음) ─ vendoring + store init + 훅 설정
        │
        └─ domain-show로 기존 문서 확인
                │
          없으면 ─ README/manifest/구조(제한된 범위) 읽기
                │
                └─ 요약 작성(confidence 포함) → domain-set
                        │
                        ├─ refs/heads/agent-context/domain 에 append 커밋
                        └─ .agent-context/DOMAIN.md 원자적 갱신
```

이후 다른 세션(같은 agent든 다른 agent든): `domain-show`로 언제든 조회, 훅에는 자동 주입 안 됨.

## 에러 처리

1. **신뢰도 명시 강제**: 모든 도메인 문서에 confidence 필수. 증거 없는 추측(회사명, 비즈니스 모델 등) 금지 — `insufficient evidence` 명시.
2. **`domain-set` 입력 검증**: 공백/빈 body → `die`, 커밋 생성 안 함(히스토리 오염 방지).
3. **`domain-show` graceful 처리**: 문서 없음 → 안내 메시지 + exit 0, git 원본 에러 노출 안 함(기존 `render_resume`의 "No context events for %s." 패턴과 동일선상).
4. **미러 파일 원자적 쓰기**: mktemp + mv로 교체. symlink가 이미 그 경로에 있어도 mv가 링크 자체를 교체하므로 임의 파일 덮어쓰기 위험 없음.
5. **동시성**: domain ref도 기존 append 프로토콜(CAS + rebuild-retry) 그대로 재사용 — 별도 동시성 코드 추가 안 함.
6. **read 범위 제한**: SKILL.md 지시에 명시적 상한(README/매니페스트/2단계 구조) — 대형 레포 폭주 방지.
7. **분석 실패 격리**: install.sh의 성공/실패와 도메인 분석의 성공/실패를 분리 — 도메인 분석 실패가 전체 setup 실패로 전파되지 않음.
8. **store 미초기화 상태에서 단독 호출**: 기존 CLI와 동일하게 `ensure_store`가 자동 생성(특별 케이스 없음, 일관성 우선).

## 테스트

- `smoke-test.sh`에 케이스 추가: `domain-show`(빈 상태) → "No domain analysis yet" 확인 → `domain-set`으로 문서 저장 → `domain-show` 왕복 확인 → `status`에 domain tip 표시 확인 → 빈 body로 `domain-set` 시도 시 실패(exit≠0, 커밋 생성 안 됨) 확인 → `.agent-context/DOMAIN.md` 내용 일치 확인 → symlink가 이미 그 경로에 있는 상태에서 `domain-set` 재실행해도 원본 링크 타겟 파일이 안 건드려지는지 확인.
- 실제 검증: README 있는 가짜 repo 만들어서, 실제 에이전트(나)가 스킬 흐름대로 직접 분석 수행 → `domain-show` 결과가 README 내용과 일치하는지 육안 확인. (이전 라운드들과 동일한 방식 — smoke-test.sh 외에 실제 repo로 수동 검증도 병행.)

## 범위 밖

- 세션 시작 훅에 도메인 요약 자동 주입 — 안 함(사용자 확정).
- cross-machine 동기화(`agent-store` 원격) — 기존 agent-context 코어 설계에서도 범위 밖으로 이미 결정됨, 이번 확장도 동일.
- 도메인 문서 보존 기간/정리(오래된 재분석 버전 squash 등) — 미정, 필요해지면 별도 논의.
