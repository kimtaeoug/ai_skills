# repo-convention-extractor — 합의 계획

## 목표
임의 코드 레포지터리 경로를 입력받아 다음 4개 카테고리를 분석/보고하는 Claude Code 스킬 제작.
1. Code Convention
2. Commit Convention
3. 패키지 관리 및 의존성
4. 코드 스타일 및 주석 스타일

## 위치
`.claude/skills/repo-convention-extractor/SKILL.md`
(frontmatter: name, description — 트리거 문구: "이 레포 컨벤션 분석해줘", "코드/커밋 컨벤션 뽑아줘", "레포 스타일 파악해줘" 등)

## 카테고리별 탐지 항목 (Codex 비평 반영)

### 1. Code Convention
- README/ARCHITECTURE/ADR/CONTRIBUTING 문서 확인
- 테스트 레이아웃, entry point, generated/vendor/ignore 디렉토리 파악 (샘플링 전 제외)
- **enforced(설정 강제) vs observed(코드에서 관찰)** 구분해서 보고
- import 순서, 모듈 경계, 에러 핸들링 패턴, 테스트 네이밍, public API 배치

### 2. Commit Convention
- merge/revert/bot/release 커밋 별도 분리, human-authored만 집계
- 최근 커밋 + 넓은 기간 샘플 (최근만 보면 마이그레이션 중일 수 있음)
- scope 표기, breaking change 표기, 이슈키 포맷, 대소문자, imperative mood, body/footer, trailer
- commitlint/semantic-release 등 강제 도구 확인 (문서보다 강제 도구가 더 강한 증거)
- **최소 20개 human-authored 커밋** 없으면 "insufficient evidence"

### 3. 패키지 관리 및 의존성
- CI install 커맨드, `packageManager` 필드/Corepack, tool-version 파일, 컨테이너 이미지로 pinning 확인
- workspace 설정, private registry, patches/overrides/resolutions, vendored deps
- direct/dev/optional/peer/transitive 정책 구분 (매니페스트가 노출하는 범위 내)
- Dependabot/Renovate 등 자동 업데이트 설정, license/security 정책 파일
- lockfile 존재만으로 "사용 중"이라 판단 금지 — manifest metadata/CI 커맨드/최근 lockfile 이력 필요

### 4. 코드 스타일 및 주석 스타일
- formatter/linter 설정 + 경로별 override 확인
- generated/minified 파일 제외
- line ending, final newline, max width, import sort, trailing comma 등
- 주석 분류: API 문서, 근거(rationale) 주석, TODO/FIXME 컨벤션, suppression 주석, 라이선스 헤더

## 파일 샘플링 전략
- 전체 인벤토리 먼저 구성, `.git`/의존성/빌드 산출물/캐시/vendored/generated/minified 경로 제외
- 언어·역할(source/test/docs/config)·서브시스템 별로 partition
- **stratified sampling**: partition당 소스 2-4개 + 테스트 1-2개
- 크기별 캡: 소형 10-20개 / 중형 25-50개 / 대형 50-100개 파일, 커버리지 요약 명시
- 최근 변경 파일 + 랜덤 분산 파일 혼합 (recency만 쓰지 않음)
- 서브시스템별 최소 1개는 깊은 경로 파일 포함 (root 편향 방지)
- 모노레포: 활성 패키지별 최소 샘플 배정 후 나머지는 소스 파일 수 비례 배분
- 예산 부족으로 제외된 경로/미샘플 패키지는 리포트에 명시

## 모노레포/다언어 처리
- workspace manifest, build-system root, 독립 lockfile로 경계 탐지
- 자체 manifest/tooling/소스트리 있으면 별도 분석 단위로 취급
- 레포 전체 요약은 진짜 공유되는 것만 (root formatter, 공유 CI, root 커밋 이력)
- 언어/패키지별 컨벤션은 별도 서브섹션, 충돌 규칙 하나로 뭉뚱그리지 않음
- 상속 관계 명시: "root ESLint config가 A/B에 적용, C는 override"
- nested repo/submodule/example/template/third-party는 별도 스코프 또는 제외로 flag
- lockfile 여러 개면 의도적 다중 생태계인지 drift인지 단정하지 않고 명시

## 불일치/혼재 컨벤션 처리
- 디렉토리/패키지/언어/파일 최근 변경 시점별로 클러스터링
- config 강제 규칙 vs 샘플 코드 비교, 위반은 "drift"로 라벨 (규칙 재정의 아님)
- 분기 패턴은 카운트로: "TS 파일 20개 중 18개 camelCase, legacy-api/는 snake_case"
- 스코프 라벨: default / legacy exception / package-local override / unresolved inconsistency
- 마이그레이션 문서/codemod/formatter 도입 커밋으로 설명 가능한지 확인
- "quotes are mixed" 식으로 뭉개지 말고 어디에 어떤 스타일 적용되는지 명시
- 하위 스킬(코드 생성 등)에는 enforced > 가장 가까운 package-local convention 순으로 따르도록 권고

## 할루시네이션/과잉추론 방지
- naming rule: 관련 파일 5개 미만이면 레포 전체 규칙으로 단정 금지
- commit convention: merge/bot/revert 제외 후 human commit 20개 미만이면 추론 금지
- 설정 파일 존재 = "사용 중" 아님 — CI 호출/manifest script/실제 참조 필요
- 오래된 lockfile만으로 패키지 매니저 확정 금지 — manifest metadata/CI 커맨드/최근 이력 필요
- generated/example/fixture/migration/vendored 코드는 기본적으로 컨벤션 증거로 사용 안 함
- 신뢰도 등급: high(강제 설정+광범위 샘플 일치) / medium(광범위 샘플만) / low(희소/상충)
- 근거 부족하면 "insufficient evidence" 명시
- 모든 주요 결론에 file:line 또는 commit hash 인용, 인용 없으면 "hypothesis"로 라벨

## 출력 형식
- 기본: 인라인 Markdown 리포트 (4개 카테고리 섹션 + 신뢰도 + 근거)
- 사용자가 영속 저장 요청 시에만 아티팩트 작성:
  - `CONVENTIONS.md` (사람이 읽는 리포트)
  - `.repo-conventions.json` (구조화 데이터: scoped findings, evidence, confidence, exceptions, insufficient_evidence 플래그) — 분석 시각, git HEAD 포함
- Markdown은 JSON과 동일 findings에서 파생, 하위 스킬은 JSON을 파싱 (prose 파싱 금지)

## 다른 스킬과의 통합
- 기본은 매 실행마다 fresh 분석 (컨벤션은 drift 하므로 영속 메모리 기본 비활성)
- opt-in 스냅샷(`.repo-conventions.json`)은 git HEAD/설정 해시 포함, 하위 스킬이 최신성 검증 후 신뢰
- 근거 있는 규칙/예외만 저장, 추측성 컨벤션을 지시사항으로 영속화 금지
- formatter/tooling 마이그레이션, workspace 변경, 커밋 정책 대변화 시 재생성 권고

## 변경 대상 파일
- 신규: `.claude/skills/repo-convention-extractor/SKILL.md`

## 검증
- SKILL.md frontmatter 유효성 (name/description 존재, 트리거 문구 명확)
- 스킬 본문에 위 5개 섹션(카테고리별 탐지, 샘플링, 모노레포, 불일치, 할루시네이션 방지, 출력형식, 통합) 반영 여부 자체 점검
- 별도 빌드/테스트 없음 (마크다운 스킬 파일이므로) — 구조/누락 체크만
