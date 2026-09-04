---
name: test-agent-team
description: '임의의 대상 레포지토리에 대고 "테스트 에이전트 팀"을 구성해 실행한다. 코드 관련 검사(lint, 타입체크, 유닛/통합 테스트, 빌드)는 서로 독립적이면 병렬로 fan-out하고, 실제 화면(UI) 테스트는 공유 자원(포트/서버/브라우저) 경합 때문에 병렬 그룹이 끝난 뒤 단일 lane으로 직렬 실행한다. 대상 레포에 이미 있는 테스트/린트 도구를 최우선으로 재사용하고, 도구가 전혀 없을 때만 최신 성능/효율 좋은 도구를 "제안"으로만 제시한다(자동 설치·자동 교체 금지). dApp의 지갑(브라우저 익스텐션) 연동 UI 테스트도 human-gated 안전 가드레일 하에 지원한다(무자산 테스트 계정 전용, mainnet/실자산은 blocked). Trigger phrases — 한국어: "테스트 팀 돌려줘", "이 레포 테스트/린트/타입체크 다 돌려줘", "화면 테스트까지 포함해서 테스트해줘", "코드 테스트랑 UI 테스트 병렬로 돌려줘", "지갑 연결 테스트도 해줘"; English: "run the test team", "test this repo (lint/typecheck/unit/e2e)", "run all checks in parallel except the screen test", "test the wallet connect flow".'
---

# Test Agent Team

임의의 대상 레포지토리 경로가 주어졌을 때, 그 레포의 **기존 테스트/린트/타입체크 도구를 그대로
재사용**해서 "테스트 에이전트 팀"을 구성해 실행하는 skill이다. 코드 관련 검사는 병렬로, 실제
화면(UI) 테스트는 병렬 그룹과 분리해 직렬로 실행한다. 새 의존성을 설치하거나 기존 도구를
"더 빠른 대안"으로 자동 교체하지 않는다 — 도구가 전혀 없을 때만 최소 권장안을 제안으로만 보고한다.

## 0. 시작 전 공통 절차

1. 대상 경로 존재 확인: `test -d <path>`.
2. git repo 여부 확인: `git -C <path> rev-parse --is-inside-work-tree` (아니어도 진행 가능 — 커밋
   히스토리를 쓰지 않으므로 영향 없음).
3. **모노레포 여부 먼저 판단**: `pnpm-workspace.yaml`, `package.json`의 `workspaces` 필드, `go.work`,
   `Cargo.toml`의 `[workspace]`, `nx.json`, `turbo.json`, `lerna.json`을 확인. 모노레포면:
   - root와 각 패키지의 toolchain을 각각 탐지한다 (하나로 뭉뚱그리지 않는다).
   - CI 설정(`.github/workflows/*.yml` 등)에 affected-only 규칙(예: `turbo run test --filter=...changed`,
     `nx affected -t test`)이 있으면 그 규칙을 그대로 따른다.
   - **임의로 전체 workspace를 한 번에 돌리거나, Turborepo/Nx 같은 새 캐싱 도구를 추가하지 않는다.**
     대상 레포가 이미 쓰고 있으면 그 스크립트만 호출한다.
4. 실행 전 부작용 감지 기준선을 남긴다: `git -C <path> status --porcelain > "$(mktemp)"`로 임시 파일에
   저장하고 경로를 기억해둔다 (고정 경로 대신 `mktemp` 사용 — 동시 실행 시 충돌 방지).
   git repo가 아니면 스킵하고 그 사실을 보고서에 명시.

## 1. 스택/도구 탐지 (재발명 금지 원칙)

**정책: 저장소 CI/script가 실제로 실행하는 명령을 항상 최우선으로 사용한다.** 우선순위:
1. `package.json`의 `scripts.test` / `scripts.lint` / `scripts.typecheck` / `scripts.build` 등
2. `.github/workflows/*.yml`, `.gitlab-ci.yml` 등 CI 설정에 **실제로 호출되는** 커맨드
3. `Makefile` / `justfile` / `Taskfile.yml` 타깃

(lockfile 자체는 실행 커맨드가 아니라 "어떤 패키지 매니저를 쓰는지"의 증거일 뿐이다 — 위 커맨드에
쓰인 매니저와 lockfile 종류가 다르면 lockfile 쪽을 의심하고 실제 CI/script 쪽을 신뢰한다.)

언어 판별 매니페스트: `package.json`(JS/TS), `pyproject.toml`/`setup.cfg`(Python), `Cargo.toml`(Rust),
`go.mod`(Go), `build.gradle*`/`pom.xml`(Java/Kotlin), `*.csproj`/`*.sln`(.NET), `Gemfile`(Ruby),
`composer.json`(PHP).

**도구가 전혀 없을 때만** 아래 최소 권장안을 "선택적 제안"으로 보고서에 적는다. 자동 설치, 새
의존성 추가, lockfile 변경, 기존 도구를 더 빠른 대안으로 임의 교체 — 전부 하지 않는다.

- **JS/TS**: 순수 Node면 `node --test`, Bun 프로젝트면 `bun test`, 그 외 신규 프로젝트는 Vitest 제안.
  lint/format 도구가 전혀 없으면 Biome(또는 Oxlint) 제안. 타입체크는 `tsc --noEmit`
  (`tsgo`/TS7은 아직 beta라 실험적 옵션으로만 언급, 기본 채택 금지).
- **Python**: `pytest` + lint/format은 `ruff`. `pytest-xdist -n auto`는 **다른 검사와 동시에 실행되지
  않고, 테스트 자체가 외부 자원(DB/네트워크/공유 상태)을 쓰지 않을 때만** 제안 — 병렬 그룹과 겹쳐
  자동 활성화하지 않는다. (`ty`는 아직 0.x라 mypy/Pyright 기본 대체 대상 아님.)
- **Rust**: `cargo nextest`가 이미 있으면 사용. doctest는 `cargo nextest`가 커버하지 않으므로
  `cargo test --doc`을 별도 단계로 추가.
- **Go**: 기본은 `go test ./...` 그대로 존중한다. (주의: `-parallel`은 `t.Parallel()`을 호출한 동일
  바이너리 내부에만 적용되고, 패키지 간 병렬 실행은 `go test`가 기본으로 처리한다 — 이걸 "병렬화 도구"로
  잘못 서술하지 않는다.)
- **Java/Kotlin/.NET/Ruby/PHP 등**: 새 러너 비교 없이 기존 커맨드 탐지 우선 원칙만 적용
  (`./gradlew test`, `mvn test`, `dotnet test`, `bundle exec rspec`, `composer test` 등 그대로 실행).
- **UI/화면 테스트**: Playwright가 기본. 이 환경에 있는 `webapp-testing` skill(Playwright 기반)을
  재사용할 수 있으면 재사용. 가능하면 `toHaveScreenshot()` 시각 비교를 병행 제안. `claude-in-chrome`은
  보조용(재현 가능한 CI 대체재 아님)으로만 쓴다. Playwright의 코드 생성/자동 수정 기능이나
  Applitools/Chromatic/Argos 같은 시각회귀 SaaS는 자격증명·비용·외부 업로드가 필요하므로 기본
  도입 대상에서 제외한다.
  - **판정 엔진은 기본적으로 Claude 자신의 비전 능력을 쓴다** (스크린샷 찍어서 직접 보고 판정) —
    별도 vision API 벤더에 새로 종속되지 않는다. 대상 레포에 이미 `lookout`(YAML spec 기반 CLI,
    Ollama/Anthropic/OpenAI 선택 가능, MIT) 또는 `frontend-visualqa`(Playwright+DOM grounding,
    단 판정 엔진이 Yutori 유료 SaaS API에 하드 종속)가 설정돼 있으면 재발명 금지 원칙대로 그대로
    재사용하고 각자의 리포트 포맷(JUnit/CTRF)을 결과 취합에 흡수한다. **frontend-visualqa를 새로
    도입하는 것은 권장하지 않는다** — Yutori API 키/과금이라는 새 벤더 종속이 생기기 때문
    (기존에 이미 쓰고 있을 때만 존중).
  - 시각 확인 항목은 **"URL/화면 하나당 닫힌 자연어 질문 하나 + Pass/Fail/Blocked/
    Not-applicable 4지 판정"** 형태로 좁게 스코프한다(lookout의 스펙 패턴 차용) — "이 페이지 전체를
    리뷰해줘" 같은 열린 지시보다 스크린샷 1장+짧은 질문 쪽이 빠르고 판정이 안정적이다.
  - DOM 셀렉터로 잡을 수 없는 대상(캔버스/게임 UI 등)에서 픽셀 좌표가 꼭 필요할 때만
    `agent-vision-toolkit`의 `ground`/`detect` 같은 벤더 중립 CLI(BYO API 키, Claude API도 가능,
    MIT)를 보조로 써서 좌표를 얻고, 실제 클릭 실행은 그대로 Playwright가 한다 — 이 도구 자체는
    클릭/네비게이션을 하지 않는 순수 "스크린샷→텍스트/좌표 변환기"라는 점에 유의.
  - **판정 기준을 미리 명문화한다.** "보기 좋다"가 아니라 "요구사항 문구를 그대로 옮긴 닫힌 질문"
    으로 기준을 고정해야 케이스마다 엄격도가 흔들리지 않는다. 같은 대화가 테스트 설계·실행·판정을
    전부 맡으면 애매한 결함을 "의도된 차이"로 합리화하는 확증편향이 생길 수 있으므로, 판정 근거를
    스크린샷 속 구체적 요소(텍스트/색상/레이아웃 위치)로 반드시 인용한다.
  - **스크린샷만으로 확정할 수 없는 것**(클릭 가능 여부, 키보드 접근성, 로딩 중 상태, 반응형 전환
    애니메이션 등)은 `pass`로 우기지 않고 `not-applicable` 또는 `blocked`로 표시하고, 해당 항목은
    섹션 2의 코드 테스트(접근성 테스트, 인터랙션 테스트 등)로 보완하라고 보고서에 명시한다.
  - **2차 검증(선택, 기본 비활성)**: Claude 1차 판정이 애매하거나(예: 미묘한 정렬/오버플로/색상
    차이) 실패 후보로 나온 케이스에 한해, 원한다면 `codex:codex-rescue`(read-only)로 같은 스크린샷을
    독립된 모델에 재판정시켜 교차검증할 수 있다. **기본값으로 켜두지 않는다** — 로컬 환경에서 관찰된
    바로는 공유 브로커가 busy 상태일 때 다른 세션 내용이 섞여 들어오거나(재현됨), 호출마다 90초~
    300초 이상 걸리고, forwarding 전용이라 폴링/재시도 제어가 안 되기 때문에 반복 판정 루프의 기본
    엔진으로는 부적합하다. 소수의 애매한 케이스에만 예외적으로 쓰고, 이때도 다른 세션 내용이 섞인
    것으로 의심되는 응답(요청과 무관한 내용)은 즉시 버리고 재시도한다.

## 2. 병렬 그룹 실행 (코드 관련 검사)

대상: lint/format 체크, 타입체크, 유닛/통합 테스트, (해당 시) 빌드 체크.

**병렬 허용 판정 기준** (모두 만족해야 병렬 lane에 넣는다):
- 소스 파일을 수정하는 명령이 아니다(섹션 2의 `--fix`/`--write` 금지 규칙과 별개로, 원래도 읽기+실행
  전용이어야 한다).
- 서로 다른 lane이 **같은 산출물 경로**(예: 동일한 `dist/`, 동일한 커버리지 리포트 파일, 동일한 빌드
  출력 디렉터리)에 동시에 쓰지 않는다 — 겹치면 해당 lane들은 병렬에서 제외하고 순차 실행한다.
- 서로 다른 lane이 **같은 포트나 로컬 DB/서비스**를 점유하지 않는다 — 겹치면 순차 실행한다.
- 캐시(`node_modules/.cache`, `__pycache__`, `target/` 등)처럼 lane마다 동시에 읽기/쓰기해도 결과가
  달라지지 않는 산출물은 병렬 허용 대상이다(경고 없이 진행, 섹션 2 말미의 `git status` 비교에서
  기대된 변경으로 취급).

기준을 만족하는 lane들만 병렬로 fan-out한다.

**구현 방식**: 탐지된 검사 종류당 하나씩, 고정 3~4개 lane을 **Agent tool로 한 메시지 안에 여러
tool call을 넣어 동시에 fan-out**한다 (예: lint 서브에이전트 1개 + 타입체크 서브에이전트 1개 +
테스트 서브에이전트 1개 + 빌드 서브에이전트 1개, 총 4개를 한 메시지로 병렬 호출). 검사 수가
많거나(다수 패키지), 반복 실행이 필요하거나, 엄격한 구조화된 결과가 필요할 때만 Claude Code
Dynamic Workflow(`parallel()`)를 선택적 가속 경로로 쓴다. "에이전트 하나 = 명령 하나" 식의 과도한
분할은 하지 않는다 — 내부 테스트 러너가 이미 자체 병렬화되어 있어 외부 병렬화와 겹치면 CPU/RAM
과구독 위험이 있다.

각 서브에이전트에게 명시할 것:
- 정확히 어떤 명령을 실행할지 (섹션 1에서 탐지된 실제 명령).
- **읽기 전용 실행**: `--fix`, `--write`, snapshot-update, migration, seed 류 명령을 실행하지 않는다.
- install 단계는 자동 수행하지 않는다 (사전에 이미 설치돼 있다고 가정하거나, 설치가 안 돼 있으면
  `blocked`로 보고).
- 비밀 환경변수·프로덕션 자격증명·배포 토큰을 대상 레포 스크립트에 전달하지 않는다 (임의 코드 실행
  위험 — CI script/Makefile은 임의 명령을 담고 있을 수 있음).
- 실행 결과(stdout/stderr 핵심, 종료 코드)를 요약해서 보고.

병렬 그룹이 모두 끝난 뒤: `git -C <path> status --porcelain`을 다시 실행해 섹션 0-4의 기준선과
비교한다. 차이가 있으면(검사 도구가 캐시/coverage/산출물 파일을 생성한 경우) 그 파일들을 보고서에
명시한다 — 예상치 못한 소스 파일 변경이면 `critical`로 플래그한다.

## 3. 직렬 스텝 (화면/UI 테스트)

기본값: **병렬 그룹 완료 후, 단일 lane으로 직렬 실행한다.** 병렬 그룹과 완전 동시(백그라운드 병행)
실행은 기본값으로 두지 않는다 — 포트/서버 상태/브라우저 세션 등 공유 자원 경합으로 재현성·플래키
판별이 깨지기 때문. (필요하면 향후 명시적 opt-in 옵션으로만 추가 — 기본 동작에는 없음.)

절차:
1. 코드 검사가 실패해도 UI 단계는 가능하면 계속 실행해 추가 진단을 제공한다. 단, 서버 기동에 필요한
   build/install 자체가 실패하면 `blocked`로 보고하고 스킵한다.
2. dev 서버를 기동하고 PID를 기록한다.
3. Playwright(또는 `webapp-testing` skill)로 실제 화면을 확인한다. **Playwright 기본 병렬 실행
   설정을 그대로 두면 "UI는 직렬"이라는 이 스킬의 계약이 깨지므로, `--workers=1`(또는 대상 레포
   설정의 동등 옵션)을 명시적으로 지정한다.**
4. 종료 시 **자신이 띄운 dev 서버 PID만 종료**한다 — 포트 기준으로 무차별 프로세스를 죽이지 않는다.
   Playwright 실행이 실패하거나 중간에 취소돼도 이 정리 단계는 항상 수행한다(성공 경로에서만
   종료하지 않는다).

### 3-1. 지갑(브라우저 익스텐션) 연동이 필요한 dApp 테스트

대상 dApp이 지갑 연결/서명을 요구할 때만 적용한다. 지갑은 Playwright의 격리된 브라우저 컨텍스트에
기본으로 없는 **실제 브라우저 확장 프로그램**(MetaMask 등)이라는 전제를 따른다.

**도구 우선순위(재발명 금지 원칙 그대로)**:
1. 대상 레포에 이미 지갑 E2E 자동화가 설정돼 있으면(Synpress, dappwright, `@coinbase/onchaintestkit`,
   provider mock 등) 그걸 그대로 재사용한다.
2. 없고 확장 UI 자체를 실제로 구동해야 하면, Playwright persistent context로 확장을 로드하는 방식을
   1순위로 검토한다 — 단, "Playwright에 확장 로드 = 사용자의 실 Chrome 프로필 재현"은 아니다.
3. 그것도 안 되거나 사람의 수동 확인이 필요하면 `claude-in-chrome`을 **human-gated 로컬 대화형
   검증**으로만 쓴다. 이 경로는 `local-interactive` / `manual-action-required`로 보고하고 CI
   release gate로 취급하지 않는다.

**안전 가드레일 (하드 스톱, 예외 없음)**:
- **mainnet/실자산 계정은 무조건 `blocked`.** 전용 Chrome 프로필 + 무자산 testnet/dev burner
  지갑만 사용한다. 시작 전 사용자에게 "이 계정이 테스트용/무자산인지" 확인받는다.
- connect 권한 부여, 계정 선택, 네트워크 추가/전환, 메시지/EIP-712 서명, permit, token/NFT approval
  (`setApprovalForAll` 포함), send/swap/bridge — **전부 사람이 직접 클릭하는 hard-stop**이다. 자동
  클릭·자동 승인·"always allow" 설정 금지.
- 승인 전에 화면에서 확인해야 할 항목: origin, chain ID, 수신/컨트랙트 주소, 함수/calldata, 금액,
  gas, spending cap. calldata를 해석할 수 없으면(blind signing), unlimited allowance면, 또는
  지갑이 자체 보안 경고를 띄우면 **즉시 중단**한다.
- SRP/개인키/비밀번호/클립보드/QR/복구구문은 화면에 노출·복사·로그 금지. 지갑 팝업 스크린샷·trace·
  video·콘솔 로그는 기본 비활성화하거나 마스킹한다 (`claude-in-chrome`은 화면을 스크린샷으로 대화
  맥락에 넣으므로 특히 주의).
- `claude-in-chrome` 사용 시 Manual mode + origin allowlist만 허용한다. Auto 모드나 승인 스킵
  설정은 이 경로에서 금지.
- 실행 중 확장이 자동 업데이트되거나 예상 밖의 네트워크/계정 전환 팝업이 뜨면 즉시 중단하고, wallet/
  Chrome/extension 버전과 chain ID만 보고서에 남긴다(주소·잔액 등 민감정보는 남기지 않는다).
- 이 경로의 스코프는 "실제 자금 이동 검증"이 아니라 **무자산 테스트 계정으로 하는 UX/연동 호환성
  점검**으로 좁힌다.
- 섹션 3의 "직렬(단일 lane)" 원칙을 그대로 따른다 — 브라우저 세션/확장 상태가 공유 자원이라 병렬
  그룹과 분리한다.

## 4. 결과 취합 / 보고

상태 taxonomy (5종, 반드시 이 중 하나로 분류):
- `pass` — 실행됐고 통과.
- `fail` — 실행됐고 실패.
- `blocked` — 실행 자체를 못 함 (install/build 실패, 서버 기동 실패 등).
- `not-applicable` — 이 레포/워크스페이스에 해당 검사 종류가 원래 없음(예: UI가 없는 CLI 도구).
- `not-found` — 해당 검사 종류가 있어야 할 것 같은데 도구를 못 찾음.

**"테스트 도구를 못 찾음"을 `pass`로 취급하지 않는다.** `not-found`와 `not-applicable`을 반드시
구분해서 보고한다.

재시도 정책: 기본 0회. 실패한 테스트만 1회 재실행 허용하며, 재실행 시 통과하면 원래 실패를 숨기지
않고 `flaky-suspected`로 별도 표시한다 (원래 실패 결과도 함께 보고).

최종 리포트에 포함할 것:
- 검사별 상태(위 taxonomy), 실행한 실제 명령어(재현 가능하도록 그대로 기재).
- 실패 로그 핵심 요약(전체 로그 덤프 금지, 결정적인 몇 줄만).
- 스킵/블록 사유.
- 모노레포일 경우 패키지별 결과.
- 섹션 2 말미의 `git status --porcelain` diff 결과(부작용 발견 시).
- 섹션 1에서 "도구 없음"으로 제안한 항목이 있다면 그 제안 목록(적용은 사용자 승인 후에만).

## 안전 가드레일 (요약)

- 새 의존성 설치, lockfile 변경, 기존 도구의 자동 교체 — 하지 않는다.
- `--fix`/`--write`/snapshot-update/migration/seed 명령 금지.
- 비밀·자격증명·배포 토큰을 대상 레포 스크립트에 전달하지 않는다.
- UI 테스트는 자신이 띄운 프로세스만 정리한다.
- 병렬 그룹과 UI 테스트의 동시 병행 실행은 기본 미지원.
