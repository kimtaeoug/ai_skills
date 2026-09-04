# test-agent-team — 합의 계획

Claude·Codex 협업 토론 결과. 참여: Claude(초안), Codex(비평/보강, 2026-09-04).

## 목표

임의의 대상 레포에 대고 실행하는 범용 Claude Code 스킬 `test-agent-team`을 만든다.
`code-style-extractor` / `commit-convention-extractor` / `package-dependency-extractor` /
`repo-convention-extractor`와 같은 패턴(순수 markdown SKILL.md, 스크립트 없음, evidence 기반)을 따른다.

동작 요약:
1. 대상 레포의 기존 테스트/린트/타입체크 도구를 감지해 **그대로 재사용**.
2. 코드 관련 검사(lint, 타입체크, 유닛/통합 테스트, 빌드)는 서로 독립적이면 **병렬 fan-out**.
3. 실제 화면(UI) 테스트는 공유 자원(포트/서버/브라우저) 경합 때문에 **기본적으로 코드 검사 그룹이
   끝난 뒤 단일 lane 직렬 실행**. (Codex 비평 반영: "읽기 전용"이어도 포트/캐시/DB 등은 실제로 공유되므로
   기본값은 직렬. 병행은 향후 명시적 opt-in으로만 남겨둔다.)
4. 결과를 pass/fail/blocked/not-applicable/not-found 로 구분해 하나의 리포트로 취합.

## 위치

`/Users/deratio/skills/.claude/skills/test-agent-team/SKILL.md`
(Codex 샌드박스가 작업 디렉터리 `/Users/deratio/skills` 바깥, 예: `~/.agents/skills/`, 에 대한
쓰기를 거부함이 확인됨 — 실제로 오늘 이전 세션에서 만든 형제 스킬 4개(`repo-convention-extractor` 등)도
이 cwd 안의 `.claude/skills/`에 생성됐었다. 따라서 쓰기 가능한 이 경로를 최종 위치로 확정한다.
스타일 참고용 원본은 `~/.agents/skills/<name>/SKILL.md`에 동일 내용으로 남아있으므로 읽기 참고만 하고,
실제 쓰기는 cwd 안에서 한다.
트리거 문구: "테스트 팀 돌려줘", "이 레포 테스트/린트/타입체크 다 돌려줘", "화면 테스트까지 포함해서
테스트해줘" 등 한/영 혼합.)

## 스킬 본문 설계 (Codex 비평 반영 최종안)

### 0. 시작 전 공통 절차
- 대상 경로 존재 확인, git repo 여부 확인(아니어도 진행은 가능, 커밋 관련 사용 안 하므로 큰 영향 없음).
- 모노레포 여부 먼저 판단(workspace 매니페스트: `pnpm-workspace.yaml`, `package.json.workspaces`,
  `go.work`, `Cargo.toml [workspace]`, `nx.json`, `turbo.json` 등). 모노레포면 **root/package별
  toolchain과 CI의 affected-only 규칙을 먼저 탐지**하고, 임의로 전체 workspace를 한 번에 돌리거나
  Turborepo/Nx 같은 새 캐싱 도구를 추가하지 않는다.

### 1. 스택/도구 탐지 (재발명 금지 원칙)
- 매니페스트로 언어 판별: `package.json`, `pyproject.toml`/`setup.cfg`, `Cargo.toml`, `go.mod`,
  Gradle/Maven(`build.gradle*`/`pom.xml`), `*.csproj`/`*.sln`, Ruby(`Gemfile`), PHP(`composer.json`).
- **정책: 저장소 CI/script/lockfile이 가리키는 명령을 항상 최우선으로 사용한다.**
  - `package.json`의 `scripts.test`/`scripts.lint`/`scripts.typecheck`/`scripts.build`
  - `.github/workflows/*.yml` 등 CI 설정에 실제로 호출되는 커맨드
  - Makefile / `justfile` / `Taskfile.yml` 타깃
- 도구가 **전혀 없을 때만** 언어별 최소 권장안을 "선택적 제안"으로만 보고한다(자동 설치·자동 교체 금지,
  새 의존성 설치나 lockfile 변경 금지):
  - JS/TS: 순수 Node 프로젝트는 `node --test`, Bun 프로젝트는 `bun test`, 그 외 신규 프로젝트는 Vitest.
    lint/format 도구가 전혀 없으면 Biome(또는 Oxlint) 제안. 타입체크는 `tsc --noEmit`
    (`tsgo`/TS7은 아직 beta라 실험적 옵션으로만 언급, 기본 채택 금지).
  - Python: `pytest` + lint/format은 `ruff`. `pytest-xdist -n auto`는 **다른 검사와 동시 실행되지 않고
    테스트 자체가 외부 자원(DB/네트워크/공유 상태)을 안 쓸 때만** 제안 — 병렬 그룹과 겹쳐 자동 활성화 금지.
    (`ty`는 아직 0.x라 mypy/Pyright 기본 대체 대상 아님.)
  - Rust: `cargo nextest`가 있으면 사용, doctest는 커버 안 되므로 `cargo test --doc`을 별도 단계로 추가.
  - Go: 기본은 `go test ./...` 그대로 존중한다. (주의: `-parallel`은 `t.Parallel()` 호출한 동일 바이너리
    내부에만 적용되고 패키지 간 병렬은 `go test`가 기본으로 처리한다 — "go test -parallel로 병렬화"라는
    식으로 잘못 서술하지 않는다.)
  - Java/Kotlin/.NET/Ruby/PHP 등 그 외 생태계는 별도 도구 비교 없이 "기존 커맨드 탐지 우선" 원칙만 적용
    (`./gradlew test`, `mvn test`, `dotnet test`, `bundle exec rspec`, `composer test` 등 그대로 실행).
  - UI/화면 테스트: Playwright가 기본. 이미 이 환경에 있는 `webapp-testing` 스킬(Playwright 기반)을 재사용.
    가능하면 `toHaveScreenshot()` 시각 비교를 병행 제안. `claude-in-chrome`은 보조용(재현 가능한 CI 대체재
    아님). Playwright의 코드 생성/자동 수정 기능이나 Applitools/Chromatic/Argos 같은 시각회귀 SaaS는
    자격증명·비용·외부 업로드가 필요하므로 기본 도입 대상에서 제외.

### 2. 병렬 그룹 (코드 관련 검사)
- 대상: lint/format 체크, 타입체크, 유닛/통합 테스트, (해당 시) 빌드 체크. 서로 파일을 수정하지 않고
  읽기+커맨드 실행만 하는 한 병렬 fan-out.
- **구현 방식**: 기본은 Agent tool로 검사당 서브에이전트 하나씩 한 메시지에 여러 tool call로 fan-out
  (고정 3~4개 lane). Claude Code Dynamic Workflow(`parallel()`)는 검사 수가 많거나(다수 패키지),
  반복 실행이 필요하거나, 엄격한 구조화된 결과가 필요할 때만 선택적으로 쓰는 가속 경로로 취급한다.
  ("에이전트 하나 = 명령 하나" 식의 과도한 분할은 지양 — 내부 테스트 러너가 이미 자체 병렬화되어 있어
  외부 병렬화와 겹치면 CPU/RAM 과구독 위험.)
- 각 서브에이전트 실행 전후로 `git status --porcelain` 기록. `--fix`/`--write`/snapshot-update/
  migration/seed 류 명령은 실행하지 않는다(부작용 방지). install 단계는 자동 수행하지 않는다.
- 비밀 환경변수·프로덕션 자격증명·배포 토큰을 대상 레포 스크립트에 전달하지 않는다(임의 코드 실행 위험).

### 3. 직렬 스텝 (화면/UI 테스트)
- 기본값: **병렬 그룹 완료 후 단일 lane 직렬 실행.** 코드 검사가 실패해도 UI 단계는 가능하면 계속
  실행해 추가 진단을 제공한다. 단, 서버 기동에 필요한 build/install 자체가 실패하면 `blocked`로 보고하고
  스킵한다.
- Playwright 기본 병렬 실행 설정을 그대로 두면 이 스킬의 "UI는 직렬" 계약이 깨지므로,
  `--workers=1`(또는 대상 레포 설정의 동등 옵션)을 명시적으로 지정한다.
- 자신이 띄운 dev 서버 PID만 종료한다 — 포트 기준으로 무차별 프로세스를 죽이지 않는다.
- 병렬 그룹과의 완전 동시 실행(백그라운드 병행)은 기본값으로 두지 않는다 — 재현성/플래키 판별이
  깨지기 때문. 필요하면 향후 명시적 opt-in 옵션으로만 추가.

### 4. 결과 취합 / 보고
- 상태 taxonomy: `pass` / `fail` / `blocked` / `not-applicable` / `not-found`.
  "테스트 도구를 못 찾음"을 `pass`로 취급하지 않는다.
- 재시도 정책: 기본 0회. 실패한 테스트만 1회 재실행 허용하며, 재실행 시 통과하면 원래 실패를
  숨기지 않고 `flaky-suspected`로 별도 표시한다.
- 최종 리포트: 검사별 상태, 실패 로그 핵심 요약, 사용한 실제 명령어(재현 가능하도록), 스킵/블록 사유,
  모노레포일 경우 패키지별 결과.

## 트레이드오프 / 명시적으로 하지 않는 것 (YAGNI)
- 모노레포 affected-only 캐싱(Turborepo/Nx) 신규 도입 안 함 — 대상 레포가 이미 쓰면 그 스크립트만 호출.
- 시각회귀 SaaS(Applitools/Chromatic/Argos) 연동 안 함 — 자격증명/비용 필요, 기본 스코프 밖.
- 병렬 그룹과 UI 테스트의 동시 병행 실행은 기본 미지원(향후 opt-in 후보로만 기록).
- 새 의존성 설치, 기존 도구를 "더 빠른 대안"으로 자동 교체 — 하지 않음. 기존 도구가 없을 때만 제안.

## 검증
스킬 자체는 markdown이라 빌드/테스트 대상이 없다. 검증은:
1. `SKILL.md` frontmatter(name/description) 파싱 가능 여부 확인.
2. 이 워크스페이스(`/Users/deratio/skills`) 또는 임의의 작은 샘플 레포를 대상으로 스킬을 실제 호출해
   병렬 그룹 + 직렬 UI 스텝이 설계대로 동작하는지 dry-run 리뷰(실제 코드 레포가 없으면 절차/문구
   검토로 대체하고 그 사실을 리뷰에 명시).

## 추가 노트 (2026-09-04, 사후 검토)

이 문서는 최초 설계 합의를 남긴 기록이라 본문은 그대로 두고, 이후 실제로 쓰인 skill이 여기서
합의된 것보다 더 나아간 부분 하나만 여기 덧붙인다.

실제로 커밋된 `.claude/skills/test-agent-team/SKILL.md`(399b88d)의 섹션 3에는 위 §3에 없던
**"3-1. 지갑(브라우저 익스텐션) 연동이 필요한 dApp 테스트"** 서브섹션이 추가돼 있다. 이 문서
작성 시점엔 지갑 연동 UI 테스트를 별도로 다루지 않았는데, 실제 스킬은 human-gated 안전
가드레일을 상당히 구체적으로 명문화했다. 요지만 요약하면:
- **mainnet/실자산 계정은 무조건 `blocked`.** 전용 Chrome 프로필 + 무자산 testnet/dev burner
  지갑만 허용, 시작 전 사용자 확인 필수.
- connect 권한 부여/계정 선택/네트워크 전환/서명(EIP-712 포함)/permit/approval/send·swap·bridge는
  전부 **사람이 직접 클릭하는 hard-stop** — 자동 클릭·자동 승인·"always allow" 금지.
- SRP/개인키/비밀번호/복구구문 등은 화면 노출·복사·로그 금지, 지갑 팝업 스크린샷/trace/video/
  콘솔 로그는 기본 비활성화 또는 마스킹.
- `claude-in-chrome` 사용 시 **Manual mode + origin allowlist만** 허용(Auto 모드·승인 스킵 금지).
- 스코프는 "실제 자금 이동 검증"이 아니라 무자산 테스트 계정으로 하는 UX/연동 호환성 점검으로
  한정.

즉 이 부분은 원래 합의 범위보다 더 상세하게 확장됐다는 뜻이다. 이 문서만 읽고 "지갑 테스트는
가드레일 없이 대충 되는구나"라고 오해하지 않도록, 실제 가드레일 내용은 항상 SKILL.md §3-1을
기준으로 봐야 한다.
