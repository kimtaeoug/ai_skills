---
name: repo-convention-extractor
description: '임의의 레포지토리 경로를 분석해 코드 컨벤션, 커밋 컨벤션, 패키지 관리/의존성 정책, 코드 스타일 및 주석 규칙을 근거(evidence)와 confidence 레벨을 붙여 추출한다. 증거 부족 시 "insufficient evidence"로 명시하고, 모노레포/다언어 레포는 워크스페이스 단위로 분리 분석한다. Trigger phrases — 한국어: "이 레포 컨벤션 분석해줘", "코드/커밋 컨벤션 뽑아줘", "이 프로젝트 스타일 가이드 추출해줘", "커밋 메시지 규칙 알려줘", "패키지 매니저 정책 확인해줘"; English: "analyze repo conventions", "extract code/commit conventions", "what''s the coding style here", "infer this repo''s commit convention", "summarize package management policy for this repo".'
---

# Repo Convention Extractor

임의의 레포지토리 경로가 주어졌을 때, 그 레포의 실제 컨벤션을 **근거 기반**으로 추출하는 skill이다. 절대 추측이나 일반 상식(vibe)으로 결론을 내지 말고, 매 결론에 증거(file:line 또는 commit hash)를 붙여라. 증거가 threshold 미만이면 "insufficient evidence"로 명시한다.

## 0. 시작 전 공통 절차

1. 대상 경로가 git repo인지 확인: `git -C <path> rev-parse --is-inside-work-tree`. 아니면 커밋 컨벤션 분석은 스킵하고 그 사실을 보고서에 명시한다.
2. `git -C <path> rev-parse HEAD`로 현재 HEAD hash를 기록해둔다 (나중에 opt-in JSON 스냅샷에 필요).
3. 전체 파일 인벤토리를 먼저 만든다: `git -C <path> ls-files` (git repo가 아니면 `find <path> -type f`). 이게 이후 모든 sampling의 기준 모집단이다.
4. noise 디렉터리를 인벤토리에서 제외한다: `.git`, `node_modules`, `vendor`, `dist`, `build`, `out`, `.next`, `target`, `coverage`, `*.min.js`, `*.lock` 이진/생성물, `.venv`, `__pycache__`, snapshot/fixture 디렉터리 등. `.gitignore`가 이미 커버하는 것들은 `git ls-files`를 쓰면 자동 제외되므로 우선 사용.
5. 워크스페이스 매니페스트를 찾아 모노레포 여부를 먼저 판단한다 (섹션 3 참고). 모노레포면 이후 모든 카테고리 분석을 워크스페이스 단위로 반복한다.

## 1. 추출 카테고리 4종

### 1-1. Code Convention
- 문서: `README*`, `ARCHITECTURE*`, `docs/adr/**`, `CONTRIBUTING*`, `docs/CONTRIBUTING*`를 Read로 확인. 명시된 규칙(예: "모든 API는 `internal/` 아래에 둘 것")은 "enforced/documented"로 표시.
- 테스트 레이아웃: `find`로 `*test*`, `*spec*` 경로 패턴을 모아 `__tests__/` vs co-located `*.test.ts` vs 별도 `tests/` 루트인지 확인.
- entry point: `package.json`의 `main`/`bin`/`exports`, `go.mod` + `main.go`, `pyproject.toml`의 `[project.scripts]` 등 언어별 매니페스트에서 확인.
- generated/vendor/ignored: `.gitignore`, `.gitattributes`(linguist-generated), `codegen`/`generated`/`gen` 디렉터리명 패턴을 sampling 전에 배제 리스트에 추가.
- enforced vs observed 구분: config 파일(예: `.eslintrc`의 `import/order` 룰, `golangci-lint` 룰)에 명시된 규칙은 "enforced"로, 실제 코드 샘플링으로만 관찰된 패턴은 "observed"로 라벨링해 절대 섞지 않는다.
- import ordering, module boundary(예: `internal/` 패키지, barrel file 사용 여부), error handling 패턴(exception vs error return vs Result 타입), 테스트 네이밍(`should_`, `test_`, `it(...)` 스타일), public API 노출 방식(`__init__.py`의 `__all__`, `index.ts` re-export 등)은 샘플링된 소스 파일에서 직접 관찰한다 (섹션 2의 sampling 전략을 따름).

### 1-2. Commit Convention
1. `git -C <path> log --no-merges -n 300 --pretty=format:'%H%x01%an%x01%ae%x01%s%x01%b%x02'`로 merge 커밋을 제외한 커밋을 hash/author명/author이메일/제목/본문 구조화 형태로 가져온다 (`%x01`/`%x02`는 필드/레코드 구분자). body/footer 관찰(항목 5)에 본문이 필요하므로 `--oneline`은 쓰지 않는다.
2. revert 커밋, bot 커밋(author명/이메일이 `dependabot`, `renovate`, `github-actions`, `*[bot]` 등), release 자동 커밋(`chore(release):`, `chore: bump version`, `Version Packages` 등 자동화 도구 패턴)을 추가로 걸러내 "human-authored" 목록을 만든다. revert 판정은 GitHub 스타일(`^Revert "`)과 Conventional 스타일(`^revert(\(.+\))?:`, 대소문자 무시) 둘 다 포함한다 — 한 패턴만 쓰면 실제 revert 커밋을 놓친다.
3. human-authored 커밋이 **20개 미만**이면 commit convention 전체를 "insufficient evidence"로 표시하고 세부 규칙을 추론하지 않는다.
4. 20개 이상이면 최근 구간(예: 최근 50개)과 더 넓은 시간대(예: 6개월~1년 전 구간, `git log --since`/`--until` 활용)를 모두 샘플링해 최근 변경으로 인한 편향을 줄인다. 넓은 시간대 구간이 0건이면 전체 히스토리(`--since`/`--until` 제거)로 fallback하고, fallback했다는 사실을 보고서에 명시한다 (레포 나이가 짧아서일 수 있음).
5. 관찰할 항목: **형식 분류**(Conventional Commits 여부는 `feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert` 타입 접두어 중 하나로 시작하는지로 판정 — 이 목록에 없는 접두어는 freeform으로 카운트), scope 표기(`feat(auth): ...`), breaking change 표기(`BREAKING CHANGE:` footer, `!` 마커), issue key 포맷(`JIRA-123`, `#123`), 제목 대소문자, imperative mood 여부(`Add` vs `Added`/`Adds`), body/footer/trailer 사용 빈도(`Co-authored-by`, `Fixes #`).
6. 도구 증거를 문서보다 우선한다: `commitlint.config.*`, `.commitlintrc*`, `package.json`의 `commitlint`/`husky` 훅, `.releaserc*`(semantic-release) 존재 + 실제로 CI(`.github/workflows/*.yml`과 `*.yaml` 둘 다)/훅에서 호출되는지 확인되면 "enforced, high confidence". 문서에만 적혀있고 도구가 없으면 "documented but unverified, medium confidence" 이하로 낮춘다.

### 1-3. Package Management & Dependencies
- 어떤 패키지 매니저가 "실제로 쓰이는지"는 다음 중 최소 하나의 강한 증거가 있어야 한다: CI 워크플로(`.github/workflows/*.yml`, `.gitlab-ci.yml` 등)의 install 커맨드(`npm ci`, `pnpm install`, `yarn install --frozen-lockfile`), `package.json`의 `packageManager` 필드 + Corepack, `.tool-versions`/`.nvmrc`/`.python-version` 같은 버전 고정 파일, Dockerfile/컨테이너 이미지의 pinning.
- **stale lockfile 하나만 존재**하는 것으로 "이 패키지 매니저가 쓰인다"고 결론 내리지 않는다. lockfile의 최신 커밋 시각을 `git log -1 --format=%ai -- <lockfile>`로 확인하고, 최근 활동과 괴리가 크면 "possibly stale" 표시. **모노레포에서 워크스페이스마다 독립된 lockfile이 없고 루트에 공유 lockfile 하나만 있는 경우**(pnpm/yarn/npm workspaces의 일반적 구조), 워크스페이스별 lockfile 비교를 시도하지 않는다 — 공유 lockfile은 레포 전체 기준 1회만 최신성 검사하고, 그 사실("워크스페이스 N개가 루트 공유 lockfile 사용")을 명시한다. 워크스페이스가 실제로 자체 lockfile 파일을 갖고 있을 때만 그 워크스페이스에 영향을 준 커밋(`git log -1 --format=%ai -- <workspace-path>`)과 비교한다.
- workspace 설정(`pnpm-workspace.yaml`, `package.json`의 `workspaces`, `lerna.json`, `nx.json`, `go.work`, `Cargo.toml`의 `[workspace]`), private registry(`.npmrc`의 `registry=`), patch/override/resolution(`resolutions`, `overrides`, `patches/` 디렉터리), vendored deps(`vendor/`, `third_party/`) 확인. 선언된 workspace glob 패턴에 걸리지 않는 매니페스트(예: 툴링 전용 `scripts/package.json`)를 발견하면 "비워크스페이스 매니페스트"로 별도 분류해서 보고하고, 워크스페이스 단위 의존성 정책 집계에서는 제외한다.
- direct/dev/optional/peer/transitive 의존성 정책: `package.json`의 `dependencies` vs `devDependencies` vs `peerDependencies` 분리 패턴, `pyproject.toml`의 `[project.optional-dependencies]` 등에서 관찰.
- `dependabot.yml`/`renovate.json` 존재 + 실제 PR 이력(`git log --grep="chore(deps)"` 등)으로 활성 여부 확인.
- `LICENSE`, `SECURITY.md`, `.github/dependabot.yml` 존재 여부 기록.

### 1-4. Code Style & Comments
- formatter/linter config: `.eslintrc*`, `.prettierrc*`, `biome.json`, `.golangci.yml`, `ruff.toml`/`pyproject.toml`의 `[tool.ruff]`, `.editorconfig` 등을 Read. path-based override(`overrides` 필드, `.eslintrc`가 서브디렉터리별로 별도 존재)를 반드시 확인하고 무시하지 않는다.
- 생성/minified 파일은 스타일 분석 대상에서 제외 (`.gitattributes`의 `linguist-generated=true`, 파일명에 `.min.`, `.generated.` 포함).
- `.editorconfig`에서 line ending(`end_of_line`), final newline(`insert_final_newline`), max width(`max_line_length`), indent 스타일 확인. import sort는 config(`import/order`, `isort`, `ruff` I-rule) + 실제 샘플 코드로 교차 검증.
- trailing comma는 formatter config(`"trailingComma"` in prettier) + 샘플 코드로 확인.
- 주석 분류: API 문서 주석(JSDoc/docstring/godoc 스타일), 이유 설명(rationale) 주석, `TODO`/`FIXME` 컨벤션(작성자/티켓 링크 포함 여부 확인), suppression 주석(`// eslint-disable`, `# noqa`, `// nolint`), 라이선스 헤더 유무 및 포맷. **TODO/FIXME나 다른 어떤 grep도 레포 경로에 직접 `grep -rn`을 걸지 않는다** — 섹션 0에서 만든 필터링된 인벤토리 목록에만 검색을 건다(예: `git ls-files | xargs grep -n "TODO\|FIXME"` 또는 필터링된 파일 목록을 순회). 필터링 없이 raw grep을 걸면 `node_modules`/빌드 산출물 등 noise가 실제 결과를 수십~수백 배 부풀린다.

## 2. 파일 샘플링 전략 (비용 통제)

1. 섹션 0에서 만든 전체 인벤토리에서 noise 제외 후, 언어/역할(source, test, docs, config)/서브시스템(최상위 디렉터리 또는 워크스페이스 패키지)별로 파티션을 나눈다.
2. 각 파티션마다 stratified sampling: source 파일 2~4개, test 파일 1~2개.
3. 레포 크기에 따라 총 샘플 **소프트 타겟**을 둔다: 전체 파일 수 기준 소형(<500 파일) 10~20개, 중형(500~5000) 25~50개, 대형(5000+) 50~100개. 이 타겟은 상한이 아니다 — 활성 워크스페이스 수 × 최소 3개(항목 6)가 이 타겟보다 크면 워크스페이스 최소 배정이 우선한다. 소프트 타겟을 억지로 맞추려고 워크스페이스를 누락시키지 않는다. 샘플링 완료 후 "몇 개 파일 중 몇 개를 봤는지"와 목표 대비 실제 샘플 수를 coverage summary로 보고서에 명시한다.
4. 최근 변경 파일(`git log --since="30 days ago" --name-only`)과 무작위로 고른 파일을 섞는다. 결과가 비어 있으면 `--since="90 days ago"`, 그래도 비어 있으면 `--since="365 days ago"`로 넓힌다. 그래도 없으면(레포가 최근 커밋이 없거나 얕은 클론) 무작위 선택만 쓰고 그 사실을 보고서에 명시한다.
5. 무작위 선택은 `shuf` 같은 셔플 도구 가용성에 의존하지 않는 **결정적(deterministic) systematic sampling**을 쓴다: 필터링된 파일 목록을 정렬한 뒤, 목표 개수 K에 대해 `step = 목록 길이 / K`를 계산해 매 step번째 파일을 선택한다 (예: `awk` 한 줄로 가능). 재현 가능하고 특정 셸 도구에 의존하지 않는다.
6. 각 주요 서브시스템/워크스페이스마다 최소 1개는 깊은 경로(디렉터리 depth가 큰 파일)를 포함시켜 표면적인 최상위 파일만 보는 편향을 방지한다.
7. 모노레포의 경우: 활성 패키지(최근 1년 내 커밋 있는 패키지)마다 최소 샘플(예: 각 패키지당 최소 3개 파일)을 우선 배정한 뒤, 남은 예산은 패키지별 source 파일 수에 비례 배분한다. 활성 패키지 수가 많아 최소 배정 합이 소프트 타겟을 초과하면, 초과분을 그대로 받아들이고 보고서에 사유("워크스페이스 N개 × 최소 3개가 소프트 타겟 M개를 초과해 실제 샘플은 N×3개")를 명시한다.
8. 제외한 경로와 샘플링하지 못한 패키지 목록을 보고서 말미에 명시한다 ("다음 패키지는 예산 부족으로 미샘플링: ...").

## 3. 모노레포 / 다언어 처리

1. 워크스페이스 경계 탐지: `pnpm-workspace.yaml`, `package.json`의 `workspaces`, `lerna.json`, `nx.json`, `go.work`, `Cargo.toml`의 `[workspace] members`, 여러 개의 독립된 lockfile(`packages/*/package-lock.json` 등), 여러 개의 독립된 빌드 루트(`Makefile`, `BUILD.bazel`)로 판단.
2. 자체 매니페스트를 가진 워크스페이스/패키지는 각각 별도의 분석 단위로 취급한다 — 섹션 1의 4개 카테고리를 패키지별로 반복.
3. 레포 전체 요약은 "진짜로 공유되는" 컨벤션에만 적용한다: 루트 formatter 설정, 공유 CI 워크플로, 루트 커밋 히스토리(커밋은 보통 레포 전체에 걸치므로).
4. 언어/패키지별로 섹션을 분리해서 작성하고, 충돌하는 규칙을 하나로 뭉뚱그리지 않는다.
5. 상속 관계를 명시한다: 예 "루트 ESLint config가 packages/A, packages/B에 적용됨; packages/C는 자체 `.eslintrc`로 override".
6. 중첩된 git repo, git submodule, `examples/`, `templates/`, 서드파티 vendored 코드는 별도 스코프로 플래그하거나 분석 대상에서 제외한다고 명시한다.
7. lockfile이 여러 개 존재하면 (예: `package-lock.json`과 `yarn.lock`이 동시에 존재), 의도된 멀티 에코시스템인지 아니면 drift(둘 중 하나가 stale)인지 명시적으로 판단해서 기술한다. 판단 근거(최근 수정 시각, CI에서 실제 사용되는 lockfile)를 함께 제시.

## 4. 불일치/혼재 컨벤션 처리

1. 관찰된 패턴을 디렉터리/패키지/언어/파일 나이 기준으로 클러스터링한다.
2. config로 강제된 규칙과 샘플링된 실제 코드를 비교해서, 코드가 config와 다르면 "drift"(재정의가 아니라 이탈)로 라벨링한다.
3. 분할 패턴은 카운트와 함께 보고한다. 예: "TS 파일 20개 중 18개가 camelCase 사용, `legacy-api/`는 snake_case 사용".
4. 스코프 라벨을 사용한다: `default` / `legacy exception` / `package-local override` / `unresolved inconsistency`.
5. migration 문서, codemod 스크립트, "adopt prettier" 같은 formatter 도입 커밋(`git log --grep="prettier\|format\|migrate"`)이 있으면 왜 스타일이 갈렸는지 설명 근거로 확인하고 인용한다.
6. 서로 다른 스타일을 평균 내서 애매한 결론으로 뭉개지 않는다 ("대체로 camelCase인 것 같다" 같은 표현 금지, 정확한 카운트와 예외 위치를 명시).
7. 다운스트림 코드 생성기에게 권고할 때는: enforced 규칙을 최우선으로 따르고, 그다음으로 대상 파일과 가장 가까운 package-local convention을 따르라고 안내한다.

## 5. 환각/과잉 추론 방지 가드레일

- 5개 미만의 관련 파일로 레포 전체 네이밍 규칙을 추론하지 않는다.
- merge/bot/revert 제외 후 human-authored 커밋 20개 미만으로 커밋 컨벤션을 추론하지 않는다.
- config 파일이 존재한다는 이유만으로 "이 도구가 쓰인다"고 말하지 않는다 — CI에서 실제로 호출되는지, manifest script(`package.json`의 `scripts`)에 등록되어 있는지, 다른 곳에서 능동적으로 참조되는지 확인 후에만 "in use"로 표기한다.
- stale lockfile 하나만으로 패키지 매니저를 단정하지 않는다.
- generated/example/fixture/migration/vendored 코드는 기본적으로 컨벤션 증거로 사용하지 않는다.
- confidence 레벨을 매긴다: `high` = enforced config + 폭넓게 일치하는 샘플, `medium` = 폭넓게 일치하는 샘플만 있고 enforced config 없음, `low` = 샘플이 희소하거나 서로 충돌.
- threshold 미달이면 "insufficient evidence"로 명시하고 억지로 결론 내지 않는다.
- 모든 중요한 결론에는 `file:line` 또는 commit hash를 인용한다. 인용할 근거가 없는 주장은 "hypothesis"로 라벨링해서 구분한다.

## 6. 출력 형식

- 기본값은 인라인 Markdown 보고서다. 4개 카테고리(Code Convention, Commit Convention, Package Management & Dependencies, Code Style & Comments)별로 섹션을 나누고, 각 결론에 confidence 레벨과 증거 인용을 붙인다.
- 사용자가 명시적으로 "저장해줘"/"persist해줘"라고 요청한 경우에만 다음 두 파일을 함께 만든다:
  - `CONVENTIONS.md`: 사람이 읽기 위한 요약본.
  - `.repo-conventions.json`: 구조화된 데이터. 다음 필드를 포함: 카테고리/스코프별 findings, 각 finding의 evidence 배열(`file:line` 또는 commit hash), confidence, exceptions(예외 목록), insufficient_evidence 플래그, 분석 timestamp, git HEAD hash.
- `CONVENTIONS.md`는 반드시 `.repo-conventions.json`과 동일한 findings에서 파생되어야 한다 — 서로 다른 근거로 따로 작성하지 않는다. 다운스트림 skill이나 도구는 JSON을 소비해야 하고, Markdown 프로즈를 파싱해서는 안 된다는 점을 안내 문구로 남긴다.

## 7. 통합(Integration) 가이드

- 기본은 매 실행마다 fresh하게 분석한다 (영속 메모리 없음). 컨벤션은 시간이 지나며 drift하므로 캐시된 과거 결과를 그대로 신뢰하지 않는다.
- opt-in 스냅샷 JSON(`.repo-conventions.json`)에는 git HEAD hash와 (있다면) 주요 config 파일들의 해시를 포함시켜서, 다운스트림 skill이 이 스냅샷을 쓰기 전에 최신성(freshness)을 검증할 수 있게 한다.
- 근거가 뒷받침된 규칙과 스코프가 명확한 예외만 persist한다. 추측성 컨벤션은 절대 저장하지 않는다.
- formatter/tooling 마이그레이션, 워크스페이스 구조 변경, 커밋 정책의 큰 변화가 있었다면 스냅샷을 재생성하라고 권고한다.
