---
name: package-dependency-extractor
description: '임의의 레포지토리 경로를 분석해 패키지 매니저, 의존성 pinning/lockfile 전략, workspace 구성, private registry, overrides/patches, 자동 업데이트 도구(Dependabot/Renovate) 사용 여부를 근거(evidence)와 confidence 레벨을 붙여 추출한다. stale lockfile만으로 패키지 매니저를 단정하지 않는다. Trigger phrases — 한국어: "패키지 매니저 정책 확인해줘", "의존성 관리 방식 알려줘", "이 레포 패키지 관리 어떻게 해"; English: "extract package management policy", "what package manager does this repo use", "analyze dependency management".'
---

# Package & Dependency Extractor

임의의 레포지토리 경로가 주어졌을 때, 그 레포의 **패키지 관리 및 의존성 정책**을 근거 기반으로 추출하는 skill이다. 추측이나 일반 상식으로 결론 내지 말고, 매 결론에 증거(파일 경로 또는 커맨드 출처)를 붙여라. 증거가 threshold 미만이면 "insufficient evidence"로 명시한다.

## 0. 시작 전 절차

1. `git -C <path> rev-parse --is-inside-work-tree`로 git repo 여부 확인. git repo면 `git rev-parse HEAD`로 HEAD hash 기록 (opt-in JSON용). git repo가 아니면 lockfile 최신성 검사·Dependabot PR 이력 검사는 스킵하고 그 사실을 보고서에 명시, HEAD hash는 `null`로 둔다.
2. 전체 파일 인벤토리: `git -C <path> ls-files` (git repo 아니면 `find <path> -type f`). `.git`, `node_modules`, `vendor`, `dist`, `build`, `.venv`, `__pycache__` 등 noise 제외 후, 이 인벤토리 안에서만 매니페스트/lockfile을 찾는다 (vendored/생성된 매니페스트가 증거로 섞이는 것 방지).
3. 워크스페이스 매니페스트를 찾아 모노레포 여부 판단: `pnpm-workspace.yaml`, `package.json`의 `workspaces`, `lerna.json`, `nx.json`, `go.work`, `Cargo.toml`의 `[workspace]`. 모노레포면 루트 + 각 활성 패키지 단위로 아래 분석을 반복한다.
4. 레포 내 존재하는 매니페스트 파일을 전부 나열: `package.json`, `pyproject.toml`, `requirements*.txt`, `Pipfile`, `go.mod`, `Cargo.toml`, `pom.xml`, `build.gradle*`, `Gemfile`, `composer.json` 등. 여러 언어 매니페스트가 있다고 바로 다국어 레포로 단정하지 말고, 각 언어의 실제 소스 코드가 존재하는지 확인 후(섹션 4 가드레일 참고) 다국어면 각각 별도 섹션으로 보고한다.

## 1. 패키지 매니저 실사용 판정

"실제로 쓰이는 패키지 매니저"는 아래 중 최소 하나의 **직접 증거**가 있어야 결론 낼 수 있다:
- CI 워크플로(`.github/workflows/*.yml`과 `*.yaml`, `.gitlab-ci.yml`, `.circleci/config.yml`)의 install 커맨드 (`npm ci`, `pnpm install --frozen-lockfile`, `yarn install --frozen-lockfile`, `poetry install`, `uv sync` 등).
- `package.json`의 `packageManager` 필드 + Corepack 사용 여부.
- Dockerfile / 컨테이너 이미지 안의 install 커맨드 pinning.

`.tool-versions`(asdf), `.nvmrc`, `.python-version`, `.ruby-version` 같은 버전 고정 파일은 **런타임 버전**을 고정할 뿐 패키지 매니저 자체를 지정하지 않으므로 보조 증거로만 쓴다 — 이것만으로 결론 내지 않고 위 직접 증거와 함께 인용한다.

**stale lockfile 하나만 존재**하는 것으로 결론 내리지 않는다. `git log -1 --format=%ai -- <lockfile>`로 lockfile의 최근 수정 시각을 확인하고, 최근 커밋 활동(`git log -1 --format=%ai`)과 비교해 괴리가 크면(예: lockfile 6개월 이상 미갱신인데 레포는 활발) "possibly stale, low confidence"로 표시.

**모노레포 lockfile 처리**: 워크스페이스마다 독립된 lockfile 파일이 실제로 있는지 먼저 확인한다. 대부분의 pnpm/yarn/npm workspaces 설정은 **루트에 공유 lockfile 하나**만 두므로, 이 경우 워크스페이스별 lockfile 비교를 시도하지 않는다 — "워크스페이스 N개가 루트 공유 lockfile(`<path>`)을 사용"이라고 명시하고 레포 전체 기준으로 1회만 최신성 검사한다. 워크스페이스가 실제로 자체 lockfile 파일(`packages/*/package-lock.json` 등)을 갖고 있을 때만 그 워크스페이스에 영향을 준 커밋(`git log -1 --format=%ai -- <workspace-path>`)과 비교하고, CI가 그 워크스페이스의 lockfile을 실제로 참조하는지 함께 확인한다.

여러 lockfile이 동시에 존재하면(`package-lock.json` + `yarn.lock` 등) 의도된 다중 에코시스템인지 drift인지 최근 수정 시각과 CI 실사용 여부로 판단해서 명시한다.

## 2. Workspace / Registry / Override

- workspace 설정: `pnpm-workspace.yaml`, `package.json`의 `workspaces`, `lerna.json`, `nx.json`, `go.work`, `Cargo.toml`의 `[workspace]`. 선언된 workspace glob 패턴에 걸리지 않는 매니페스트(예: 툴링/스크립트 전용 `scripts/package.json`)를 발견하면 "비워크스페이스 매니페스트"로 별도 분류해서 보고하고, 워크스페이스 단위 의존성 정책 집계에서는 제외한다.
- private registry: `.npmrc`의 전역 `registry=` 뿐 아니라 스코프별 설정(`@scope:registry=...`)도 확인, `.yarnrc.yml`의 `npmRegistryServer`와 `npmScopes` 매핑, `pip.conf`/`pyproject.toml`의 `[[tool.uv.index]]` 등.
- patch/override/resolution: `package.json`의 `resolutions`(yarn)/`overrides`(npm), `patches/` 디렉터리(patch-package), Cargo의 `[patch]`.
- vendored dependencies: `vendor/`, `third_party/` 디렉터리 존재 여부와 규모.

## 3. 의존성 정책

- direct/dev/optional/peer 구분: `package.json`의 `dependencies` vs `devDependencies` vs `peerDependencies` vs `optionalDependencies` 분리 패턴 관찰. `pyproject.toml`의 `[project.optional-dependencies]`, `[dependency-groups]` 등도 확인. transitive(간접) 의존성은 매니페스트가 아니라 lockfile을 파싱해야 알 수 있으므로, lockfile을 실제로 파싱하지 않았다면 "transitive dependency policy: not analyzed (매니페스트만으로는 확인 불가)"로 명시하고 direct 의존성 정책만 결론 낸다.
- 버전 명시 스타일: exact pin(`1.2.3`) vs range(`^1.2.3`, `~1.2.3`) vs `*`. 매니페스트 내 비율로 보고 ("dependencies 42개 중 38개 caret range").
- 자동 업데이트 도구: `.github/dependabot.yml`/`.yaml`, `renovate.json`/`.renovaterc*` 존재 확인 + `git log --grep="chore(deps)\|bump.*from.*to" -n 50`으로 실제 PR/커밋 이력이 있는지 확인해 "설정만 있음" vs "활성 사용 중"을 구분.
- `LICENSE`, `SECURITY.md` 존재 여부와 의존성 라이선스 정책 명시 여부(`license-checker` 설정, `.github/workflows`의 라이선스 스캔 스텝 등) 기록.

## 4. 가드레일

- 설정 파일 존재만으로 "이 도구가 쓰인다"고 말하지 않는다 — CI 호출/manifest script 등록/실제 참조를 확인 후에만 "in use"로 표기.
- stale lockfile 하나만으로 패키지 매니저 단정 금지.
- 여러 매니페스트가 있다고 무조건 다국어 레포로 단정하지 않는다 — 실제 소스 코드가 각 언어로 존재하는지, 아니면 하나는 죽은 설정(예전 마이그레이션 잔재)인지 최근 커밋 이력으로 교차 확인.
- confidence 레벨: `high` = CI/훅에서 실제 호출 확인, `medium` = 매니페스트/버전 고정 파일 존재하지만 CI 호출 미확인, `low` = lockfile만 존재하거나 stale.
- 모든 결론에 `file:line`(설정 파일) 또는 커밋 이력을 확인했다면 commit hash를 인용한다. 근거 없는 결론은 "hypothesis"로 라벨링.

## 5. 출력 형식

- 기본값은 인라인 Markdown 보고서: 언어/패키지별 섹션으로 나누고, 패키지 매니저/workspace/registry/override/의존성 정책/자동 업데이트 도구 각각에 confidence + 근거를 붙인다. 모노레포면 워크스페이스별로 반복.
- 사용자가 명시적으로 저장을 요청한 경우에만 `.package-policy.json`을 만든다. 모든 카테고리(`package_manager`, `workspaces`, `registries`, `overrides`, `dependency_pinning_style`, `auto_update_tooling`)의 각 finding은 동일한 스키마를 따른다: `value`, `evidence`(file:line 또는 commit hash 배열), `confidence`, `insufficient_evidence` 플래그. 최상위에 분석 timestamp와 git HEAD hash(git repo 아니면 `null`)를 포함한다.
