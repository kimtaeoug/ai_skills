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
설치 경로나 도구 전용 명령을 요구하지 않는다. 기본 lexical 조회는 Python 3.9+와
Git만 있으면 동작한다. 벡터 조회는 Python 3.11, PostgreSQL+pgvector,
`requirements.txt`의 `psycopg[binary]`와 `fastembed`를 사용한다.
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

벡터 조회를 쓸 환경은 원본 스킬 폴더에서 의존성을 설치한다. 기본 로컬 DB 이름은
`repo_knowledge`이고, 다른 접속 정보는 `REPO_KNOWLEDGE_DSN` 환경 변수로만 전달한다.
저장소에는 DB 자격 증명을 남기지 않는다.

```bash
cd "$HOME/.claude/skills/repo-knowledge"
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt
createdb repo_knowledge
```

이미 DB가 있으면 `createdb`는 생략한다. `CREATE EXTENSION IF NOT EXISTS vector`는
`index` 명령이 처리하지만 권한이 필요하므로, 권한이 없으면 DBA가 pgvector 확장을
먼저 설치해야 한다. helper는 `SKILL.md` 옆 `.venv`가 있으면 `index`와 `query`에서
그 인터프리터로 자동 재실행한다.

설치 경로는 [Claude Code 공식 문서](https://code.claude.com/docs/en/skills)와
[Codex 공식 문서](https://learn.chatgpt.com/docs/build-skills)를 기준으로 확인했다.
작업 지침의 적용 범위는 [CLAUDE.md 문서](https://code.claude.com/docs/en/memory)와
[AGENTS.md 문서](https://learn.chatgpt.com/docs/agent-configuration/agents-md)를 따른다.

## 실제 구성

대상 레포에 `.repo-knowledge/knowledge.json`(온톨로지와 근거 레코드),
`.repo-knowledge/guide.md`(작업 절차), 두 도구용 작업 지침 블록을 만든다.
PostgreSQL의 `repo_knowledge` 스키마와 `vector(384)` 행은 파생 인덱스이며,
정본은 항상 JSON이다. 레포 네임스페이스는 실제 Git 루트 절대 경로의 SHA-256이다.
기존 파일 내용은 보존하며 같은 초기화를 반복해도 블록을 중복 추가하지 않는다.
스킬 제작과 특정 레포의 지식 구축은 별개다. `init`만 실행하면 사실은 0개다.

- **구축:** 에이전트가 실제 소스를 읽고 도메인 개념·타입 관계·출처를 추출한다.
  로컬 Ollama가 있으면 `extract <path>`로 `qwen2.5-coder:7b`의 구조화된 초안을
  만들 수 있다. 이 명령은 저장하지 않으며, 에이전트가 주장과 인용 줄을 원문과
  대조한 뒤 승인한 레코드만 `put`한다. 다른 설치 모델은
  `REPO_KNOWLEDGE_OLLAMA_MODEL`로 지정한다.
- **검색:** 기본 `query --mode auto`는 PostgreSQL 인덱스가 가능하면 hybrid,
  아니면 lexical fallback을 명시한다. `lexical`, `vector`, `hybrid` 모드를
  직접 지정할 수 있고, 명시적 vector/hybrid는 인덱스가 없으면 실패한다.
  에이전트가 현재 코드와 대조해 인용이 있는 답변/작업 계획을 만든다.
- **갱신:** `sync-plan --path <파일>`로 변경과 연결된 레코드를 확인하고,
  에이전트가 각 파일과 영향 레코드를 검토한 배치를 `sync-apply`로 한 번에 반영한다.
  `index`는 변경 레코드만 임베딩하고 삭제된 행을 제거한다. 동일 상태에서는
  임베딩을 호출하지 않는다. 전체 재생성은 `index --rebuild`를 사용한다.

업무 시작에는 `status → sync-plan → query`, 승인된 코드 작업 종료에는
`sync-plan → 검토 → sync-apply → index` 순서다. 읽기 전용 질문은 자동 갱신하지 않는다.
배치 작성 전에 `references/records.md`의 Incremental sync 계약을 읽는다.
`refresh`를 먼저 실행하면 검토할 옛 관계가 사라지므로 새 갱신 흐름에서는 사용하지 않는다.
기존 수동 `put/drop/refresh`는 계속 사용할 수 있다.

파일 내용이 같고 검토가 끝난 파일은 다시 추출하지 않는다. 파일에서 지식을 0개
추출했어도 전체 검토 이력을 남길 수 있다. 이름 변경은 삭제+추가로 검토하며,
내용이 같은 유일한 쌍에만 힌트를 제공한다. 선택하지 않은 경로는 pending으로 남는다.
소스나 JSON이 계획 이후 바뀌면 전체 배치를 거부한다. JSON 반영 후 DB 실패 시에는
JSON을 되돌리지 않고 `index`만 재시도한다. 오래된 벡터는 검색에서 제외된다.

기존 레포의 절차 문서는 `init --update-guide`로 명시 갱신한다. 기존 guide를
`guide.md.bak`에 백업하며 같은 백업을 덮어쓰지 않는다. 전역 스킬 업데이트가
모든 레포 guide를 자동 수정하지는 않는다.

관찰과 추론을 구분하고, 추론에는 이유를 남긴다. 문서가 그대로여도 코드 변경으로
의미가 틀려질 수 있으므로 관련 관계는 에이전트가 다시 확인한다. 미인덱싱 파일과
제외된 파일을 표시하며, 조회가 없으면 직접 소스를 탐색한다.

벡터 조회는 FastEmbed 0.8.0의 로컬
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` 모델을 사용한다.
첫 `index`가 약 0.22GB 모델을 내려받을 수 있지만 `query`는 다운로드하거나
레포/DB/스키마를 변경하지 않는다. 모든 후보는 LIMIT 전에 근거 해시와 전체 JSON
레코드 fingerprint를 확인한다. 검색은 exact cosine이며 HNSW는 아직 없다.
semantic similarity는 조사 단서이지 증명이나 확정 threshold가 아니다.

Ollama 추출은 `127.0.0.1:11434`의 로컬 API만 호출한다. 설치된 모델이 없으면
`ollama pull qwen2.5-coder:7b`를 한 번 실행한다. JSON Schema와 온톨로지 검증은
형식을 보장할 뿐 내용의 진실성을 보장하지 않으므로 검토 전 자동 저장하지 않는다.
CLI의 `workspace-write` 샌드박스가 localhost를 차단하면 명시적인 오류를 반환한다.
해당 명령에 네트워크를 허용하거나 샌드박스 밖에서 `extract`를 실행한 뒤 같은
검토 절차를 따른다.

## 검증

```bash
python3 tests/test-repo-knowledge.py
python3 tests/test-repo-knowledge-sync.py
.claude/skills/repo-knowledge/.venv/bin/python tests/test-repo-knowledge-vectors.py
python3 tests/test-repo-knowledge-ollama.py
```

임시 Git 레포에서 구축·조회·관계 확장·갱신·삭제·미커밋 변경·새 파일·잘못된 입력·
비밀 파일 제외·경로 이탈 차단·지침 보존·쓰기 충돌 차단을 확인한다. 이 검사는
에이전트가 모든 실제 세션에서 지침을 반드시 따른다는 보장은 아니다.
벡터 검사는 PostgreSQL 18.4와 pgvector 0.8.2에서 한국어/영어 검색, hybrid 조회,
read-only/offline query, 레포 격리, rollback, stale filtering, replacement,
deletion, rebuild를 확인한다.

Claude Code와 Codex CLI의 실제 구축 및 일반 작업에서의 조회·갱신 결과는
[동작 검증 보고서](../reports/2026-09-09-repo-knowledge-verification.md)에 기록했다.
