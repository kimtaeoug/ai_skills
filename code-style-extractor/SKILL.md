---
name: code-style-extractor
description: '임의의 레포지토리 경로를 분석해 코드 포맷팅(formatter/linter 설정, indent, quote, trailing comma 등)과 주석 스타일(API 문서 주석, rationale 주석, TODO/FIXME 컨벤션, suppression 주석, 라이선스 헤더)을 근거(evidence)와 confidence 레벨을 붙여 추출한다. path-based override와 enforced-vs-observed 구분을 명시한다. Trigger phrases — 한국어: "코드 스타일 알려줘", "주석 쓰는 스타일 뽑아줘", "이 레포 포맷팅 규칙 확인해줘"; English: "extract code style", "what comment style does this repo use", "analyze formatting conventions".'
---

# Code Style & Comment Extractor

임의의 레포지토리 경로가 주어졌을 때, 그 레포의 **코드 포맷팅 및 주석 스타일**을 근거 기반으로 추출하는 skill이다. 추측이나 일반 상식으로 결론 내지 말고, 매 결론에 증거(file:line)를 붙여라. 증거가 threshold 미만이면 "insufficient evidence"로 명시한다.

## 0. 시작 전 절차

1. `git -C <path> rev-parse --is-inside-work-tree`로 git repo 여부 확인. git repo면 `git rev-parse HEAD`로 HEAD hash 기록 (opt-in JSON용). 아니면 HEAD hash는 `null`로 두고 formatter 도입 커밋 추적(섹션 4) 등 git 기반 항목은 스킵한다고 명시.
2. 전체 파일 인벤토리: `git -C <path> ls-files` (git repo 아니면 `find <path> -type f`).
3. noise 제외: `.git`, `node_modules`, `vendor`, `dist`, `build`, `.next`, `target`, `coverage`, `out`, `*.min.*`, `.venv`, `__pycache__`, `examples/`, `fixtures/`, `__snapshots__/`, `templates/`, `migrations/`. 이 필터를 인벤토리뿐 아니라 섹션 3의 TODO/FIXME grep 등 이후 모든 검색에도 동일하게 적용한다 (필터링 안 된 원본 경로로 grep하지 않는다).
4. **생성/minified 파일 제외**: `.gitattributes`의 `linguist-generated=true`, 파일명에 `.min.`/`.generated.` 포함된 파일은 스타일 분석 대상에서 뺀다. 이 파일들을 스타일 증거로 쓰면 안 된다.
5. 모노레포면 워크스페이스별로 formatter/linter config가 다를 수 있으므로(섹션 1 참고) 워크스페이스 단위로 반복 분석.

## 1. Formatter / Linter 설정 (enforced)

- 설정 파일 Read: `.eslintrc*` 및 `eslint.config.*`(ESLint v9 flat config), `.prettierrc*` 및 `prettier.config.*`, `biome.json`/`biome.jsonc`, `.golangci.yml`, `ruff.toml`/`.ruff.toml`/`pyproject.toml`의 `[tool.ruff]`/`[tool.black]`, `.editorconfig`, `.stylelintrc*`, `rustfmt.toml`, `.clang-format`.
- **path-based override 반드시 확인**: ESLint의 `overrides` 필드(또는 flat config의 배열 항목별 `files` 패턴), 서브디렉터리별 별도 `.eslintrc`/`.prettierrc` 존재 여부. 하나만 보고 전체 레포에 일반화하지 않는다.
- `.editorconfig`에서 `end_of_line`(line ending), `insert_final_newline`, `max_line_length`, `indent_style`/`indent_size` 확인.
- import sort 규칙: `import/order`(eslint), `isort`(python), ruff의 `I` 룰 — config에 규칙이 있는지 확인.
- trailing comma: prettier `"trailingComma"` 설정값 확인.
- 이 섹션에서 config 파일 존재를 확인한 규칙은 기본적으로 "configured/documented"로 라벨링한다. CI/pre-commit 훅/`package.json`의 `scripts`에서 실제로 그 formatter/linter가 호출되는 것까지 확인된 경우에만 "enforced"로 승격한다 (섹션 5 가드레일과 동일 기준). config 존재만으로 곧장 "enforced"라고 쓰지 않는다.

## 2. 샘플 코드 관찰 (observed)

- 섹션 0에서 만든 인벤토리를 언어/역할(source, test, docs, config)/서브시스템(최상위 디렉터리 또는 워크스페이스 패키지)별로 파티션 나눈 뒤, 파티션당 stratified sampling(source 2~4개 + test 1~2개)을 한다.
- 레포 크기에 따라 총 샘플 **소프트 타겟**: 소형(<500 파일) 10~20개, 중형(500~5000) 25~50개, 대형(5000+) 50~100개. 이 타겟은 상한이 아니다 — 활성 워크스페이스 수 × 최소 3개가 이 타겟보다 크면 워크스페이스 최소 배정이 우선하고, 초과분을 그대로 받아들여 보고서에 사유를 명시한다 (워크스페이스를 억지로 누락시키지 않는다).
- 최근 변경 파일(`git log --since="30 days ago" --name-only`) + 무작위 파일을 섞는다. 30일 결과가 비면 90일, 그래도 비면 365일로 넓히고, 그래도 없으면 무작위만 쓰고 그 사실을 명시한다. 무작위 선택은 `shuf` 가용성에 의존하지 않는 결정적 systematic sampling(필터링된 목록 정렬 후 매 `len/K`번째 파일 선택)을 쓴다. 서브시스템/워크스페이스당 최소 1개는 깊은 경로 파일 포함.
- 샘플링 완료 후 "전체 몇 개 파일 중 몇 개를 봤는지" coverage summary와, 예산 부족으로 제외된 경로/미샘플링 패키지 목록을 보고서에 명시한다.
- 관찰 항목: quote 스타일(single/double), 세미콜론 사용 여부, 실제 indent(설정과 일치하는지), 실제 trailing comma 사용률, 함수/변수 네이밍(camelCase/snake_case/PascalCase) 비율.
- config에 규칙이 없는 항목(예: quote 스타일이 formatter에 강제 안 됨)은 코드 샘플에서 관찰된 비율로만 보고하고 "observed, config 강제 아님"으로 라벨링. enforced와 observed를 섞어서 하나의 규칙처럼 서술하지 않는다.

## 3. 주석 스타일 분류

- **API 문서 주석**: JSDoc(`/** ... */` + `@param`/`@returns`), Python docstring(`"""..."""`), Go doc comment(`// FuncName ...`) 스타일과 커버리지(공개 함수 중 몇 %가 문서화됐는지, 샘플 기준).
- **rationale 주석**: "왜"를 설명하는 주석 존재 빈도 (표본 파일에서 관찰, 정량화 어려우면 정성적으로 "드묾/보통/많음" + 예시 file:line).
- **TODO/FIXME 컨벤션**: 섹션 0에서 필터링한 인벤토리에만 검색을 건다 — 예: `git ls-files | xargs grep -n "TODO\|FIXME"` (또는 필터링된 파일 목록을 순회). 레포 경로에 직접 `grep -rn "TODO\|FIXME" <path>`를 걸지 않는다 — `node_modules`/빌드 산출물 등 noise가 섞여 실제 결과보다 수십~수백 배 부풀려진다. 작성자명/티켓 링크 포함 여부 패턴 확인 (`TODO(username):`, `TODO(JIRA-123):`, 그냥 `TODO:` 등).
- **suppression 주석**: `// eslint-disable`, `# noqa`, `// nolint`, `# type: ignore` 등의 사용 빈도와 이유 주석 동반 여부.
- **라이선스 헤더**: 소스 파일 상단에 라이선스 헤더가 있는지, 있다면 포맷(SPDX 식별자 vs 전체 텍스트 블록) 확인. 샘플 중 몇 %에 있는지 카운트로 보고.

## 4. 불일치 처리

- 스타일이 디렉터리/패키지별로 갈리면 카운트와 함께 보고: "TS 파일 20개 중 18개 single quote, `legacy/`는 double quote".
- config(enforced)와 실제 코드(observed)가 다르면 "drift"로 라벨링 (설정 재정의가 아니라 이탈).
- formatter 도입 커밋(`git log --grep="prettier\|format\|adopt.*style" -n 20`)이 있으면 왜 스타일이 갈렸는지 근거로 인용.
- 뭉뚱그려서 "대체로 X 스타일"이라 결론 내지 않는다 — 정확한 비율과 예외 위치 명시.

## 5. 가드레일

- 5개 미만의 관련 파일로 레포 전체 네이밍/스타일 규칙 추론 금지 — "insufficient evidence"로 명시.
- generated/example/fixture/vendored 코드는 스타일 증거로 사용하지 않는다.
- config 파일 존재만으로 "이 포맷터가 쓰인다"고 말하지 않는다 — CI/pre-commit 훅에서 실제 호출되는지 확인 (`.github/workflows`, `.pre-commit-config.yaml`, `package.json`의 `scripts`/`lint-staged`).
- confidence 레벨: `high` = enforced config + 폭넓게 일치하는 샘플, `medium` = 샘플만 폭넓게 일치, `low` = 희소/상충.
- 모든 결론에 file:line 인용. 인용 없는 주장은 "hypothesis"로 라벨링.

## 6. 출력 형식

- 기본값은 인라인 Markdown 보고서: enforced(설정 기반)와 observed(코드 관찰) 섹션을 명확히 분리, 주석 스타일은 5개 하위 분류별로 서술, 각 결론에 confidence + 근거.
- 사용자가 명시적으로 저장을 요청한 경우에만 `.code-style.json`을 만든다. 필드: `formatter_config`(configured/enforced rules + file source), `observed_style`(quote, semicolon, naming, trailing comma — 비율 포함), `comment_style`(5개 하위 분류별 findings), 각 finding의 `evidence`, `confidence`, `insufficient_evidence` 플래그, 분석 timestamp, git HEAD hash(git repo 아니면 `null`).
