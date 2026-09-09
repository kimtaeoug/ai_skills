# repo-knowledge

레포의 도메인 개념과 코드·문서·테스트 관계를 근거와 함께 저장하고, 실제 업무에서
검색해 사용한 뒤 변경 내용을 갱신하는 Claude Code/Codex 공용 스킬이다.

## 사용

Claude Code:

```text
/repo-knowledge /path/to/repo의 지식 베이스를 구축하고 이후 작업에서 참고하도록 연결해줘.
```

Codex:

```text
$repo-knowledge /path/to/repo의 지식 베이스를 구축하고 이후 작업에서 참고하도록 연결해줘.
```

구축 후에는 평소처럼 “결제 실패 처리를 수정해줘”라고 요청한다. 대상 레포의
`AGENTS.md`와 `CLAUDE.md` 지침을 읽은 에이전트가 작업 전 조회와 변경 후 갱신을
수행하도록 연결된다. 백그라운드 훅으로 실행을 강제하는 방식은 아니다.

## 설치와 호환성

원본은 `.claude/skills/repo-knowledge/` 하나다. 이 레포에는 현재 Codex 탐색용
`.agents/skills/repo-knowledge` 상대 심볼릭 링크와 기존 OMX 환경을 위한
`.codex/skills/repo-knowledge/SKILL.md` 진입점도 제공한다.

다른 환경에서는 **원본 폴더 전체**를 아래 경로에 복사한다. 기존 동명 설치가
있으면 내용을 비교해 갱신한다. 지원 파일 없이 `SKILL.md`만 복사하지 않는다.

| 도구 | 프로젝트 설치 | 개인 설치 |
| --- | --- | --- |
| Claude Code | `.claude/skills/repo-knowledge/` | `~/.claude/skills/repo-knowledge/` |
| Codex | `.agents/skills/repo-knowledge/` | `~/.agents/skills/repo-knowledge/` |

심볼릭 링크를 쓸 수 없는 환경에서도 폴더 복사로 사용 가능하다. 원본은 특정
설치 경로나 도구 전용 명령을 요구하지 않는다. 실행 의존성은 Python 3.9+와 Git이다.
필요하면 새 세션에서 스킬을 로드한다. 전역 설정 파일을 수정할 필요는 없다.

macOS/Linux에서 두 도구가 하나의 전역 설치본을 공유하려면 이 레포의 루트에서
다음 명령을 실행한다. 세 대상 경로에 기존 동명 스킬이 없는 최초 설치용이다.

```bash
mkdir -p "$HOME/.claude/skills" "$HOME/.agents/skills" "$HOME/.codex/skills"
cp -R .claude/skills/repo-knowledge "$HOME/.claude/skills/repo-knowledge"
ln -s ../../.claude/skills/repo-knowledge "$HOME/.agents/skills/repo-knowledge"
ln -s ../../.claude/skills/repo-knowledge "$HOME/.codex/skills/repo-knowledge"
```

Codex/OMX 호환 경로까지 동일한 설치본을 가리킨다. 이후 업데이트할 때는
`~/.claude/skills/repo-knowledge/` 원본을 갱신하면 된다. 전역 설치는 모든 레포의
지식을 미리 구축하지 않는다. 사용할 레포에서 위 구축 명령을 한 번 실행한다.

설치 경로는 [Claude Code 공식 문서](https://code.claude.com/docs/en/skills)와
[Codex 공식 문서](https://learn.chatgpt.com/docs/build-skills)를 기준으로 확인했다.
작업 지침의 적용 범위는 [CLAUDE.md 문서](https://code.claude.com/docs/en/memory)와
[AGENTS.md 문서](https://learn.chatgpt.com/docs/agent-configuration/agents-md)를 따른다.

## 실제 구성

대상 레포에 `.repo-knowledge/knowledge.json`(온톨로지와 근거 레코드),
`.repo-knowledge/guide.md`(작업 절차), 두 도구용 작업 지침 블록을 만든다.
기존 파일 내용은 보존하며 같은 초기화를 반복해도 블록을 중복 추가하지 않는다.
스킬 제작과 특정 레포의 지식 구축은 별개다. `init`만 실행하면 사실은 0개다.

- **구축:** 에이전트가 실제 소스를 읽고 도메인 개념·타입 관계·출처를 추출한다.
- **검색:** 키워드와 별칭으로 검색하고 연결된 관계 한 단계를 함께 조회한다.
  에이전트가 현재 코드와 대조해 인용이 있는 답변/작업 계획을 만든다.
- **갱신:** 파일 해시가 달라졌거나 삭제된 근거를 제외하고 다시 읽어 저장한다.
  커밋 전 변경, 새 파일, 이름 변경도 고려한다.

관찰과 추론을 구분하고, 추론에는 이유를 남긴다. 문서가 그대로여도 코드 변경으로
의미가 틀려질 수 있으므로 관련 관계는 에이전트가 다시 확인한다. 미인덱싱 파일과
제외된 파일을 표시하며, 조회가 없으면 직접 소스를 탐색한다.

벡터 DB와 임베딩은 포함하지 않는다. 한국어 조사나 동의어를 자동 이해하는 검색이
아니므로 도메인 별칭과 코드 용어를 함께 기록한다. 대규모 레포에서는 파일 해시
확인과 선형 검색의 비용을 먼저 측정하고 필요할 때 인덱스를 확장한다.

## 검증

```bash
python3 tests/test-repo-knowledge.py
```

임시 Git 레포에서 구축·조회·관계 확장·갱신·삭제·미커밋 변경·새 파일·잘못된 입력·
비밀 파일 제외·경로 이탈 차단·지침 보존·쓰기 충돌 차단을 확인한다. 이 검사는
에이전트가 모든 실제 세션에서 지침을 반드시 따른다는 보장은 아니다.

Claude Code와 Codex CLI의 실제 구축 및 일반 작업에서의 조회·갱신 결과는
[동작 검증 보고서](../reports/2026-09-09-repo-knowledge-verification.md)에 기록했다.
