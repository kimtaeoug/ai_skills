# repo-knowledge 동작 검증

2026-09-09 검증 완료. 실제 Claude Code와 Codex CLI에서 지식 구축과,
스킬 이름을 언급하지 않은 후속 개발 요청의 조회→수정→검사→갱신을 확인했다.
검증 중 발견한 두 결함은 수정 후 재현 테스트와 독립 재검사를 통과했다.

## 실제 세션

| 검사 | Claude Code 2.1.197 | Codex CLI 0.153.4 |
| --- | --- | --- |
| 복사한 스킬 발견·실행 | `.claude/skills/repo-knowledge` 성공 | `.agents/skills/repo-knowledge` 성공 |
| 코드·문서·테스트 근거 구축 | 3개 | 3개 |
| AGENTS.md·CLAUDE.md 연결 | 두 파일 모두 성공 | 두 파일 모두 성공 |
| 일반 작업에서 수정 전 실제 query 실행 | 성공 | 성공 |
| 미커밋 변경으로 오래된 근거 제외 | 성공 | 성공 |
| 코드·문서·테스트 재시도 한도 3→1 수정 | 성공 | 성공 |
| 기존 로컬 주석 보존 | 성공 | 성공 |
| 수정 후 refresh→source→put | 성공 | 성공 |
| 최종 근거 상태 | 3개 모두 최신, stale 0 | 3개 모두 최신, stale 0 |
| 코드 실행 및 경계 조건 검사 | 통과 | 통과 |
| 추가 커밋 없이 완료 | 확인 | 확인 |

각 도구에 같은 합성 Python 레포를 별도로 제공했다. 첫 세션에서 지식을 구축한
후 소스에 미커밋 주석을 추가하여 기존 코드 근거를 오래된 상태로 만들었다.
두 번째는 새 세션이며 다음 일반 요청을 사용했다. 스킬명과 조회·갱신 명령은
이 요청에 포함하지 않았다.

```text
Change the transient payment retry limit from 3 to 1. Update the documentation
and runnable checks to match, preserving nontransient and negative-attempt
behavior. Follow this repository's existing work instructions, work only here,
use no subagents or dependencies, run the checks, and do not commit.
```

실제 후속 세션 JSONL의 도구 호출 순서:

| 호출 | Claude 로그 행 | Codex 로그 행 |
| --- | --- | --- |
| 수정 전 status + query | 24 | 7 |
| 첫 소스 수정 | 34 | 14 |
| 변경 후 refresh | 47 | 16 |
| 재검토한 근거의 put | 88 | 18 |

검증 담당자가 최종 출처의 SHA-256을 모두 재계산하고 별도로 코드를 실행했다.
`MAX_RETRIES == 1`, transient attempt 0만 재시도, -1/1/2/3과 nontransient는
재시도하지 않음을 assert로 확인했다. 문서의 `below 1`, 기존 주석 보존,
최초 커밋 1개 유지, `git diff --check`도 확인했다.

## 발견·수정한 결함

1. **추론 이유 타입 검증:** 기존 `str(None)` 처리로 `rationale: null`이 저장됐다.
   비어 있지 않은 문자열만 허용하도록 수정했다. null·숫자·배열·공백 문자열의
   거부와 저장소 보존을 회귀 검사에 추가했다.
2. **근거 파일의 링크 전환:** 저장된 소스가 심볼릭 링크로 바뀌면 기존
   status/query/refresh가 모두 중단됐다. 저장된 경로의 문법 검사와 실제 파일 접근
   검사를 분리했다. 해당 근거만 stale로 처리하며 링크 대상은 읽지 않는다.

두 테스트가 기존 코드에서 실패하는 것을 확인한 뒤 수정했다. 독립 검사에서도
외부 링크의 식별용 문자열이 검색 결과에 노출되지 않았고, source 명령은 거부됐다.

## 반복 가능한 검사

```bash
python3 tests/test-repo-knowledge.py
/usr/bin/python3 tests/test-repo-knowledge.py
```

Python 3.14.5와 3.9.6 모두 통과. 초기화 반복, 기존 지침·줄바꿈 보존,
override 연결, 한국어 키워드 검색, 관계 확장, 오래된 이웃 제외, 변경·삭제·새 파일,
링크 전환, 잘못된 입력, 비밀 파일 제외, 쓰기 충돌, 검색 목록 제한을 검사했다.
추가 임시 검사에서는 이름 변경, 유효/무효 혼합 배치의 원자성, 잘못된 온톨로지
타입, 커밋 없는 레포의 `indexed_commit: null`도 통과했다.

Python 3.9 문법 검사, 세 진입점의 skill-creator 형식 검사와 whitespace 검사도
통과했다. 새 의존성은 설치하지 않았다.

## 범위와 로그

작은 합성 레포에서 각 도구의 구축 1회·후속 작업 1회를 실행했다. 모든 모델·설정에서
항상 지침을 따른다는 보장이나 대규모 성능·검색 정확도의 통계적 평가가 아니다.
Claude는 프로젝트 설정과 제한된 도구 허용 목록, Codex는 사용자 config를 제외한
workspace-write 환경을 사용했다. 기존 CLI 인증을 사용했고 전역 설정은 수정하지 않았다.
Claude의 선택적 임시 파일 삭제는 허용 목록에서 차단되어 파일을 남겼으며 핵심 검사는 완료됐다.

원본 로그와 합성 레포는 다음 로컬 임시 디렉터리에 있다. OS 정리 대상이므로
반복 가능한 CLI 검사는 테스트 파일에 별도로 남겨두었다.

```text
$TMPDIR/repo-knowledge-live-<run-id>/
  claude-build.jsonl
  claude-change.jsonl
  codex-build.jsonl
  codex-change.jsonl
  claude/
  codex/
```

## 후속 변경: PostgreSQL 벡터 검색

위 CLI 세션 검증은 기존 lexical 구현에 대한 기록이다. 후속 벡터 구현은 로컬
PostgreSQL 18.4 + pgvector 0.8.2, Python 3.11.15, psycopg 3.3.5,
FastEmbed 0.8.0으로 별도 검사했다. 모델은
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`(384차원)이다.
JSON이 정본이고 DB는 레포별 파생 인덱스다.

```bash
python3 tests/test-repo-knowledge.py
/usr/bin/python3 tests/test-repo-knowledge.py
~/.claude/skills/repo-knowledge/.venv/bin/python tests/test-repo-knowledge-vectors.py
```

통과 항목:

- 한국어 비밀번호 복구 질문: lexical 결과 0건, vector/hybrid 첫 결과는 영어 복구 근거.
- 소스 변경·삭제·레코드 교체·drop 후 오래된 벡터 제외, LIMIT 1 이전 필터링.
- 다른 레포 네임스페이스 분리, 잘못된 벡터 차원으로 갱신 실패 시 기존 인덱스 롤백.
- 조회 전후 DB 행 동일, HTTP 요청을 차단해도 캐시된 모델 추론 성공.
- 빈 인덱스 재구축, 누락된 인덱스의 명시적 vector 오류 및 auto lexical fallback.
- 전역 Codex 별칭에서 기본 Python 3.14로 CLI를 호출하고 공용 `.venv`로
  자동 전환한 상태에서도 벡터 검사 전체 통과. Claude 경로와 두 Codex 별칭은
  동일 설치본을 가리키고 원본 파일과 바이트 단위로 일치했다.

독립 코드 리뷰, Python 컴파일, whitespace 검사도 통과했다. 새 벡터 버전으로
Claude/Codex 에이전트의 전체 업무 세션을 다시 실행한 것은 아니며, 이번 검사는
공용 helper와 전역 경로에 대한 실제 DB 통합 검사다. 대규모 성능 측정과 HNSW는
포함하지 않았다. 테스트 레포의 DB 행은 종료 시 제거했다.

## 후속 변경: Ollama 구조화 추출

Homebrew Ollama CLI를 0.24.0에서 0.33.3으로 업데이트해 실행 중인 서버
0.33.3과 맞췄다. 설치되어 있던 `qwen2.5-coder:7b`를 기본 모델로 연결하고,
단일 소스 파일에서 온톨로지 레코드 초안을 만드는 `extract` 명령을 추가했다.
이 명령은 `127.0.0.1:11434`만 호출하고 JSON이나 PostgreSQL에 쓰지 않는다.

```bash
python3 tests/test-repo-knowledge-ollama.py
```

실제 모델로 Python의 로그인 재시도 상수와 함수를 구조화 레코드로 추출했다.
리터럴 값 보존, 근거 경로·해시·줄 범위, 현재 온톨로지 endpoint 검증,
검토 전 레코드 수 0, 승인 레코드 `put` 후 lexical 검색을 확인했다. 첫 시도에서
모델이 값 `5`를 rationale에만 남기고 summary에서 빠뜨려, 프롬프트에 리터럴 값
보존과 명시되지 않은 효과 금지를 추가했다. 생성 내용은 실행마다 달라질 수 있어 구조 검증은
내용의 진실성을 증명하지 않으므로, 스킬은 에이전트가 인용 줄을 검토한 레코드만
`put`하도록 유지한다.

Claude Code와 Codex CLI의 전역 스킬 실제 사용도 각각 통과했다. 둘 다 초안을 인용
줄과 대조한 뒤 2개 레코드만 저장했고, lexical 검색과 원본 파일 불변을 확인했다.
Codex의 첫 실행에서 Python 소스를 `document`로 분류한 사례가 있어 코드 경로는
`module`/`symbol` subject만 사용하도록 프롬프트와 회귀 검사를 보강했다. Codex의
기본 `workspace-write` 샌드박스는 localhost를 차단하므로, 이 명령은 localhost가
허용된 실행 환경이나 샌드박스 밖에서 실행해야 한다.
