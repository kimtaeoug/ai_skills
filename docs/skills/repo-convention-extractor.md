# repo-convention-extractor

저장소의 코드·커밋·의존성·스타일 컨벤션을 실제 파일과 Git 기록에 근거해 추출한다. 일반적인 관습을 추측으로 덧붙이지 않고, 증거가 부족하면 `insufficient evidence`로 표시한다.

## 호출

Claude에서는 자연어로 요청한다.

```text
이 레포 컨벤션 분석해줘: /path/to/repository
```

Codex에서는 명시 호출도 가능하다.

```text
$repo-convention-extractor /path/to/repository의 코드와 커밋 컨벤션을 분석해줘
```

다른 트리거 예시는 `코드/커밋 컨벤션 뽑아줘`, `이 프로젝트 스타일 가이드 추출해줘`, `analyze repo conventions`다.

## 분석 범위

다음 네 영역을 각각 근거와 confidence로 보고한다.

- 코드 컨벤션: 디렉터리 구조, 테스트 배치, import, 오류 처리, 공개 API 경계
- 커밋 컨벤션: human-authored 커밋의 형식, scope, 본문·footer, 이슈 키, 강제 도구
- 패키지·의존성 정책: 실제 CI/스크립트가 쓰는 패키지 매니저, 워크스페이스, lockfile, override·registry
- 코드 스타일·주석: formatter/linter, 들여쓰기, 줄바꿈, trailing comma, 문서·TODO·suppression 주석

## 사용 방법

대상 경로를 함께 주면 해당 경로를 분석한다. 생략 시 현재 작업 디렉터리를 대상으로 삼는 것이 자연스럽다.

```text
$repo-convention-extractor 이 모노레포의 TypeScript 패키지별 스타일 차이와 패키지 매니저 정책을 조사해줘
```

영속 파일까지 필요할 때만 명시한다.

```text
$repo-convention-extractor 이 저장소의 컨벤션을 분석하고 결과를 저장해줘
```

## 동작 원칙

1. Git 여부와 HEAD를 기록하고, 생성물·vendor·fixture 같은 noise를 제외한 인벤토리를 만든다.
2. 워크스페이스와 언어 경계를 먼저 찾아 독립 분석 단위로 나눈다.
3. 최근 변경과 안정된 파일을 섞어 결정적으로 샘플링한다.
4. 설정에 강제된 규칙과 코드에서 관찰한 규칙을 분리한다.
5. 불일치에는 `default`, `legacy exception`, `package-local override`, `unresolved inconsistency` 범위를 붙인다.

레포 전체 코드 규칙에는 관련 파일 5개 이상, 커밋 규칙에는 merge·bot·revert 제외 human-authored 커밋 20개 이상이 필요하다. 기준 미달이면 결론을 강제하지 않는다.

## 결과

기본 결과는 채팅의 Markdown 보고서다. 중요한 주장마다 `file:line` 또는 commit hash를 붙이고 `high`·`medium`·`low` confidence를 표시한다.

사용자가 저장을 요청한 경우에만 대상 저장소에 다음을 함께 만든다.

```text
CONVENTIONS.md
.repo-conventions.json
```

두 파일은 같은 findings에서 파생되며, JSON에는 분석 시점과 Git HEAD도 기록한다.

정확한 증거 기준과 샘플링 규칙은 [원본 스킬 정의](../../.claude/skills/repo-convention-extractor/SKILL.md)를 따른다.
