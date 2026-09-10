# AI Skills

저장소의 실제 코드, 설정, Git 이력에서 개발 컨벤션을 추출하는 AI 에이전트 스킬 모음입니다. 새 프로젝트에 합류하거나 기존 코드에 맞춰 작업할 때, 규칙과 적용 범위를 근거와 함께 확인할 수 있습니다.

각 스킬은 에이전트가 읽고 수행하는 `SKILL.md`로 구성됩니다. 분석 결과에는 파일 위치 또는 커밋 해시와 신뢰도를 붙이며, 근거가 부족하면 `insufficient evidence`로 표시합니다.

> 이 문서는 GitHub 기본 브랜치 `main`의 스킬 구성을 기준으로 합니다.

## 스킬 목록

| 스킬 | 분석 범위 | 이런 경우에 사용하세요 |
| --- | --- | --- |
| [repo-convention-extractor](https://github.com/kimtaeoug/ai_skills/blob/main/repo-convention-extractor/SKILL.md) | 코드 구조, 커밋, 패키지 관리, 코드·주석 스타일 통합 분석 | 저장소 전체의 개발 규칙을 파악할 때 |
| [code-style-extractor](https://github.com/kimtaeoug/ai_skills/blob/main/code-style-extractor/SKILL.md) | Formatter/Linter, 들여쓰기, 따옴표, 네이밍, 주석, 경로별 설정 | 기존 코드에 맞춰 작성하거나 리뷰할 때 |
| [commit-convention-extractor](https://github.com/kimtaeoug/ai_skills/blob/main/commit-convention-extractor/SKILL.md) | Conventional Commits, scope, breaking change, 이슈 참조, body/footer | 커밋 메시지 작성 규칙을 확인할 때 |
| [package-dependency-extractor](https://github.com/kimtaeoug/ai_skills/blob/main/package-dependency-extractor/SKILL.md) | 패키지 매니저, lockfile, workspace, registry, 버전 고정, 자동 업데이트 | 의존성 관리 방식을 파악할 때 |

전체 분석은 `repo-convention-extractor` 하나로 시작하면 됩니다. 특정 영역만 필요하면 해당 전문 스킬을 선택하세요.

## 빠른 시작

### 1. 저장소 가져오기

```bash
git clone --branch main https://github.com/kimtaeoug/ai_skills.git
cd ai_skills
```

별도 빌드나 패키지 설치는 없습니다. 로컬 파일과 셸 명령을 사용할 수 있는 AI 에이전트가 필요하며, 커밋 분석에는 Git과 대상 저장소의 커밋 이력이 필요합니다.

### 2. 에이전트에 분석 요청하기

설치 없이 사용하려면 에이전트에 스킬 파일과 분석 대상의 실제 경로를 지정합니다.

```text
/path/to/ai_skills/repo-convention-extractor/SKILL.md를 읽고 지침에 따라
/path/to/my-project의 컨벤션을 분석해줘.
```

반복해서 사용하려면 원하는 스킬 폴더를 사용하는 도구의 스킬 디렉터리에 복사합니다. 아래는 `repo-convention-extractor`를 개인 스킬로 설치하는 예시입니다. 기존 동명 폴더가 없는 경우에 실행하세요.

**Claude Code**

```bash
mkdir -p "$HOME/.claude/skills"
cp -R repo-convention-extractor "$HOME/.claude/skills/"
```

**Codex**

```bash
mkdir -p "$HOME/.agents/skills"
cp -R repo-convention-extractor "$HOME/.agents/skills/"
```

다른 스킬도 폴더 이름을 바꿔 같은 방식으로 설치할 수 있습니다. 새 세션에서 스킬이 로드된 뒤 분석할 저장소 경로와 요청을 전달하세요.

## 사용 예시

아래는 에이전트 채팅에 입력하는 요청입니다. 설치한 스킬을 명확히 지정하려면 요청 앞에 Claude Code에서는 `/스킬이름`, Codex에서는 `$스킬이름`을 붙일 수 있습니다.

```text
이 레포 컨벤션 분석해줘: /path/to/my-project

/path/to/my-project의 코드 스타일과 주석 쓰는 스타일을 뽑아줘.

/path/to/my-project의 커밋 메시지 규칙을 알려줘.

/path/to/my-project의 패키지 매니저 정책과 의존성 관리 방식을 확인해줘.
```

분석 결과를 파일로 남기려면 저장 요청을 명시합니다.

```text
/path/to/my-project의 컨벤션을 분석하고 결과를 저장해줘.
```

## 분석 원칙

- **근거와 신뢰도:** 중요한 결론마다 `file:line` 또는 커밋 해시를 인용하고 `high`, `medium`, `low` 신뢰도를 표시합니다.
- **설정과 관찰 구분:** 설정·문서의 규칙과 실제 코드에서 관찰한 패턴을 구분합니다. 도구 실사용 여부는 CI·훅·스크립트 등의 근거로 확인합니다.
- **범위와 예외 명시:** 모노레포는 워크스페이스별로 분석하고, 경로별 override와 레거시 예외를 구분합니다.
- **분석 대상 선별:** 생성물, vendor, fixture 등은 컨벤션 표본에서 제외하고, 샘플 수와 분석하지 못한 범위를 보고합니다.
- **과잉 추론 방지:** 관련 파일 5개 미만으로 저장소 전체 스타일을 추론하지 않습니다. 커밋 규칙은 merge·bot·revert 등을 제외한 사람 작성 커밋이 20개 미만이면 근거 부족으로 표시합니다.
- **최신성 확인:** 오래된 lockfile 하나만으로 패키지 매니저를 단정하지 않으며, 저장된 분석 결과도 코드·설정 변경 후에는 다시 확인합니다.

## 결과물

기본 결과는 채팅의 Markdown 보고서입니다. **사용자가 저장을 요청한 경우에만** 다음 파일을 생성합니다.

| 스킬 | 저장 파일 |
| --- | --- |
| `repo-convention-extractor` | `CONVENTIONS.md`, `.repo-conventions.json` |
| `code-style-extractor` | `.code-style.json` |
| `commit-convention-extractor` | `.commit-convention.json` |
| `package-dependency-extractor` | `.package-policy.json` |

JSON에는 분석 항목별 근거·신뢰도, 분석 시각, Git HEAD 등의 정보가 포함됩니다. 통합 스킬의 `CONVENTIONS.md`와 `.repo-conventions.json`은 동일한 분석 결과에서 생성하며, 후속 자동화는 JSON을 사용하도록 안내합니다.

Git 저장소가 아닌 경로도 파일 기반 분석은 가능하지만, 커밋 분석과 Git 이력이 필요한 검사는 수행할 수 없습니다. 얕은 클론이나 이력이 적은 저장소에서는 분석 범위가 제한될 수 있습니다.

## 저장소 구조

```text
ai_skills/
├── code-style-extractor/
│   └── SKILL.md
├── commit-convention-extractor/
│   └── SKILL.md
├── package-dependency-extractor/
│   └── SKILL.md
└── repo-convention-extractor/
    └── SKILL.md
```

세부 분석 절차, 표본 기준, 출력 필드는 각 스킬의 `SKILL.md`에서 확인할 수 있습니다.
