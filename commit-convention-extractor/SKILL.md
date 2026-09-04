---
name: commit-convention-extractor
description: '임의의 레포지토리 경로를 분석해 커밋 메시지 컨벤션(Conventional Commits 여부, 스코프, breaking change 표기, 이슈키 포맷, imperative mood, body/footer/trailer 사용, commitlint/semantic-release 강제 여부)을 근거(evidence)와 confidence 레벨을 붙여 추출한다. human-authored 커밋 20개 미만이면 "insufficient evidence"로 명시한다. Trigger phrases — 한국어: "커밋 메시지 규칙 알려줘", "이 레포 커밋 컨벤션 뽑아줘", "커밋 메시지 어떻게 써야 해", "conventional commits 쓰는지 확인해줘"; English: "extract commit convention", "what commit message style does this repo use", "infer commit convention", "does this repo use conventional commits".'
---

# Commit Convention Extractor

임의의 레포지토리 경로가 주어졌을 때, 그 레포의 **커밋 메시지 컨벤션**을 근거 기반으로 추출하는 skill이다. 추측이나 일반 상식으로 결론 내지 말고, 매 결론에 증거(commit hash)를 붙여라. 증거가 threshold 미만이면 "insufficient evidence"로 명시한다.

## 0. 시작 전 절차

1. 대상 경로가 git repo인지 확인: `git -C <path> rev-parse --is-inside-work-tree`. 아니면 즉시 "커밋 이력 없음, 분석 불가"로 보고서 작성 후 종료.
2. `git -C <path> rev-parse HEAD`로 HEAD hash 기록 (opt-in JSON 스냅샷용).
3. 모노레포 여부 확인 (workspace manifest 존재 시). 모노레포라도 커밋 히스토리는 보통 레포 전체에 걸치므로, 커밋 컨벤션은 기본적으로 레포 단위로 분석하되 패키지별 커밋 스코프 패턴(`feat(pkg-a): ...`)이 워크스페이스 이름과 일치하는지는 별도로 관찰한다.

## 1. human-authored 커밋 필터링

1. `git -C <path> log --no-merges -n 300 --pretty=format:'%H%x01%an%x01%ae%x01%s%x01%b%x02'`로 merge 커밋을 제외한 커밋을 hash/author명/author이메일/제목/본문 구조화 형태로 가져온다 (`%x01`/`%x02`는 필드/레코드 구분자, 파싱용). subject만 필요하면 `--oneline`으로 충분하지만, 필터링(author 확인)과 body/footer 관찰(섹션 2)에는 본문이 필요하므로 처음부터 구조화 포맷을 쓴다.
2. revert 커밋, bot 커밋(author명/이메일이 `dependabot`, `renovate`, `github-actions`, `*[bot]` 등), 자동 release 커밋(`chore(release):`, `chore: bump version`, `Version Packages` 등 자동화 도구 패턴)을 추가로 제외해 "human-authored" 목록을 만든다. revert 판정은 GitHub 스타일(`^Revert "`)과 Conventional 스타일(`^revert(\(.+\))?:`, 대소문자 무시) 둘 다 포함한다 — 한 패턴만 쓰면 실제 revert 커밋을 놓친다.
3. **human-authored 커밋이 20개 미만**이면 전체를 "insufficient evidence"로 표시하고 세부 규칙을 추론하지 않는다. 이 경우 몇 개 확보했는지, 왜 부족한지(레포가 새로 생성됨, bot 커밋이 대부분 등)만 보고한다.
4. 20개 이상이면 최근 구간(최근 50개)과 넓은 시간대(6개월~1년 전, `git log --since`/`--until`)를 모두 샘플링해 최근 변경으로 인한 편향을 줄인다. 넓은 시간대 구간이 0건이면 전체 히스토리로 fallback하고 그 사실을 보고서에 명시한다.

## 2. 관찰 항목

- **형식 프리픽스**: Conventional Commits 여부는 `feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert` 타입 접두어 중 하나로 시작하는지로 판정한다 (이 목록에 없는 접두어는 콜론이 있어도 freeform으로 카운트). gitmoji(`:sparkles:`, `✨`) 사용 여부도 별도 카운트. 카운트로 보고 ("120개 중 98개가 Conventional Commits 형식, 타입 목록: feat/fix/chore/...").
- **scope 표기**: `feat(auth): ...` 형태의 괄호 스코프 사용 여부, 스코프 값이 디렉터리/패키지명과 일치하는지.
- **breaking change 표기**: `BREAKING CHANGE:` footer, 타입 뒤 `!` 마커(`feat!:`) 사용 여부와 빈도.
- **issue key 포맷**: `JIRA-123`, `#123`, `(closes #123)` 등 이슈 참조 스타일과 위치(제목 vs footer).
- **제목 스타일**: 대소문자(첫 글자 대문자 여부), imperative mood(`Add` vs `Added`/`Adds`), 제목 길이 분포(50자 제한 준수 여부), 마침표 유무.
- **body/footer/trailer**: body 작성 비율, `Co-authored-by`, `Fixes #`, `Signed-off-by` 등 trailer 사용 빈도.
- **도구 증거 우선**: `commitlint.config.*`, `.commitlintrc*`, `package.json`의 `commitlint`/`husky` 설정(commit-msg 훅), `.releaserc*`(semantic-release), `.github/workflows/*.yml`과 `*.yaml` 둘 다 안에서 commitlint가 실제로 실행되는지 확인. `lint-staged`는 staged 파일 린트용이지 커밋 메시지 검증이 아니므로 증거로 쓰지 않는다. 훅(`commit-msg`) 또는 CI 호출까지 확인되면 "enforced, high confidence"; 설정 파일만 있고 훅/CI 호출이 없으면 "configured but not verified as enforced, medium confidence"; 문서(`CONTRIBUTING.md`)에만 적혀있고 도구가 전혀 없으면 "documented but unverified, low confidence".

## 3. 불일치 처리

- 커밋 스타일이 시점에 따라 갈리면(예: 특정 시점부터 Conventional Commits 도입) `git log --grep="conventional\|commitlint\|standardize commit"` 등으로 도입 커밋을 찾아 "YYYY-MM 이후 도입, 그 이전은 freeform" 형태로 시계열 분리해서 보고한다.
- 여러 스타일이 동시에 섞여 있고 시계열 설명이 안 되면 "unresolved inconsistency"로 라벨링하고 각 스타일의 비율만 카운트로 제시한다. "대체로 X 형식인 듯" 같은 애매한 표현 금지.

## 4. 가드레일

- human-authored 커밋 20개 미만으로 세부 규칙(스코프 패턴, breaking change 표기 등) 추론 금지 — insufficient evidence로만 보고.
- commitlint 등 설정 파일 존재만으로 "강제된다"고 말하지 않는다 — CI/훅에서 실제 호출되는지 확인 필요.
- 커밋 히스토리 관찰(형식/스코프/breaking/이슈키/제목/body 등)은 commit hash로 인용하고, 도구 강제 여부(commitlint/훅/CI) 관찰은 `file:line`으로 인용한다. 어느 쪽이든 인용 없는 주장은 "hypothesis"로 라벨링.
- confidence 레벨: `high` = enforced 도구 + 폭넓게 일치하는 샘플, `medium` = 폭넓게 일치하는 샘플만, `low` = 샘플 희소/상충.

## 5. 출력 형식

- 기본값은 인라인 Markdown 보고서: 형식 프리픽스 사용 비율, scope/breaking/issue-key/제목스타일/body-footer 각 항목별 관찰 + confidence + 근거 commit hash.
- 사용자가 명시적으로 저장을 요청한 경우에만 `.commit-convention.json`을 만든다. 필드: `format` (conventional/gitmoji/freeform 비율), `scope_pattern`, `breaking_change_notation`, `issue_key_format`, `title_style`, `trailers`, 각 항목의 `evidence`(commit hash 배열), `confidence`, `insufficient_evidence` 플래그, 분석 timestamp, git HEAD hash.
