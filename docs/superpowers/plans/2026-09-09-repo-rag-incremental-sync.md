# Repository RAG Incremental Sync Implementation Plan

## Execution notes

Implementation completed; acceptance evidence and limitations: [verification report](../../reports/2026-09-09-repo-rag-sync-verification.md). Detailed checklist below preserves the original proposed sequence; core Tasks 1–3 were committed together after regression verification rather than as three artificial commits. Pure sync helpers perform preliminary freshness guards; the CLI still runs the existing canonical record/freshness validators before saving.

- [x] Tasks 1–3: reviewed planning, atomic application and lifecycle regression.
- [x] Task 4: incremental PostgreSQL indexing and actual database rollback tests.
- [x] Task 5: guide upgrade and shared skill/evaluation instructions.
- [x] Task 6 validation: actual Claude/Codex/Ollama exercise, independent artifact verification.
- [x] Task 6 delivery: global aliases verified and synthetic database namespaces cleaned. Git delivery is recorded by repository history.

- Implementation workspace: `.worktrees/rag-sync`, branch `feat/rag-incremental-sync`.
- Ruling: exclude internal `.repo-knowledge/` operational paths from snapshot excluded-list hashing. Otherwise saving a review file or creating the writer lock would invalidate its own plan. Canonical JSON remains included in the token.
- Ruling: a byte-identical no-op apply may retain the same content token. The token detects changed source/store state, not request replay; do not add a history service solely to reject an identical no-op.
- Core sync/CLI work has one owner; vectors and its tests have a separate owner. Documentation and integration probes are coordinated by the root agent. No shared implementation file has parallel writers.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking. Default to one executor; do not edit shared files concurrently. This document is a plan, not implemented behavior.

**Goal:** 레포 변경을 놓치지 않고 검토된 부분만 원자적으로 지식에 반영하며, 변경된 레코드만 다시 임베딩한다.

**Architecture:** JSON 정본에 선택적인 파일 검토 기준점을 추가한다. `sync-plan`은 읽기 전용으로 변경·영향 범위를 계산하고, `sync-apply`는 에이전트의 검토 결과를 현재 상태와 대조한 후 JSON을 한 번 교체한다. PostgreSQL은 별도 트랜잭션으로 증분 갱신하며 기존 검색의 해시/fingerprint 필터를 유지한다.

**Tech Stack:** 기존 Git, Python 3.9+ stdlib; 벡터는 Python 3.11, psycopg, PostgreSQL/pgvector, FastEmbed 0.8.0; 선택적 Ollama 추출.

**Spec:** 이 문서의 1–8절이 실행 사양이다. 원 요구는 업무 전후 증분 갱신, 관계 영향 확인, 실패 시 안전성, 변경된 평가 정답 감지다. 기존 계약은 `.claude/skills/repo-knowledge/SKILL.md`, `references/records.md`, `.claude/skills/rag-reliability/references/evaluation.md`를 함께 읽는다.

## Global Constraints

- Claude Code와 Codex 모두 동일 canonical 스킬과 Python CLI를 사용한다.
- JSON이 정본이고 PostgreSQL은 파생 인덱스다. JSON과 DB를 하나의 분산 트랜잭션으로 취급하지 않는다.
- Ollama 출력은 검토 전 초안이다. 명령이 모델의 의미 정확성을 인증하지 않는다.
- 기존 `init/status/source/query/extract/put/drop/refresh/index` 호출은 호환성을 유지한다.
- `query/status/sync-plan`은 파일·DB를 쓰거나 모델을 다운로드하지 않는다.
- 라이브 사용자 소스·Git 브랜치를 자동 수정하지 않는다. 테스트는 임시 레포만 사용한다.
- 새 패키지, daemon, watcher, AST 파서, 작업 큐, SQLite, HNSW, 자동 주기 작업을 추가하지 않는다.
- 추출/임베딩 호출 수 절감이 목표다. 기존 전체 파일 해시 검사는 유지한다. 증분이라는 이유로 mtime만 신뢰하지 않는다.
- task-orchestrator 관련 동시 수정은 이 작업 소유가 아니다. `git add .`, 전체 reset, 다른 작업 덮어쓰기를 금지한다.
- 이 계획에는 제품 구현이 포함되지 않았다. 체크박스는 실제 실행과 검증 후에만 체크한다.

## 1. 실행자가 알아야 할 현재 코드

기준 커밋은 `d0ca42e`다. 실행 직전 실제 HEAD와 diff를 확인하고 아래 함수가 변했다면 먼저 차이를 기록한다. 줄 번호보다 함수 이름을 검색한다.

| 파일 | 현재 동작 | 변경 책임 |
| --- | --- | --- |
| `.claude/skills/repo-knowledge/scripts/knowledge.py` | inventory/read_source, JSON 검증/저장, writer lock, CLI, fresh 필터 | 새 CLI 연결, 메타데이터 검증, 검토 결과 적용 |
| `.claude/skills/repo-knowledge/scripts/vectors.py` | build 전체 삭제/재삽입, search fingerprint 검증 | 변경 행 임베딩/upsert/delete |
| `.claude/skills/repo-knowledge/scripts/ollama_extract.py` | 단일 파일 초안, 저장 없음 | 기본적으로 변경 없음 |
| `.claude/skills/repo-knowledge/scripts/sync.py` (신규) | 없음 | 변경 계획 계산/검토 배치 검증에 필요한 순수 함수 |
| `tests/test-repo-knowledge-sync.py` (신규) | 없음 | 임시 Git 레포의 CLI 회귀 |
| `tests/test-repo-knowledge-vectors.py` | 실제 PostgreSQL 통합 검사 | 증분성/롤백 추가 |
| `tests/test-repo-knowledge.py` | 기존 CLI 회귀 | 기존 동작 유지 확인 |
| 두 스킬의 SKILL.md 및 references | 갱신/평가 지침 | 업무 전후 순서와 평가 기준점 변경 |

현재 확인된 사실:

1. `inventory(root)`는 Git tracked + untracked 중 ignore되지 않은 파일을 나열하고 내용과 SHA-256을 읽는다. 제외 파일도 별도 반환한다.
2. `stale_records(data, sources)`는 근거 파일 부재·해시 변화·줄 범위 변화로 오래된 레코드를 찾는다.
3. `refresh`는 오래된 레코드를 삭제한다. 삭제 전에 기록하지 않으면 그 레코드의 관계 정보가 사라진다.
4. `put`은 입력 ID만 덮어쓴다. 같은 파일에서 사라진 다른 ID를 자동 삭제하지 않는다.
5. `writer(root)`는 `.repo-knowledge/.write-lock`으로 동시 CLI 쓰기를 막는다. 사용자 편집기까지 잠그지는 않는다.
6. `atomic_write`는 임시 파일 + fsync + replace를 사용한다. 새 원자 저장기를 만들지 않는다.
7. `vectors.build`는 레포 namespace 전체를 삭제한 뒤 모든 fresh 레코드를 임베딩한다.
8. `vectors.search`는 현재 JSON fingerprint와 일치하는 행만 LIMIT 이전에 선택한다. 이 필터를 약화하지 않는다.
9. namespace는 절대 레포 경로의 해시다. 같은 경로에서 브랜치를 전환하면 namespace는 같으며 내용 비교로 변경을 찾아야 한다.
10. `initialize`는 기존 guide.md를 덮어쓰지 않는다. 새 업무 흐름 배포 시 이 점을 별도로 해결해야 한다.

## 2. 설계에서 고정할 결정

### 2.1 자동화와 검토의 경계

자동 처리: 변경 탐지, 영향 후보 목록, 오래된 벡터 배제, 승인 배치 형식/근거 검증, 원자적 JSON 교체, 벡터 차이 계산.

에이전트 검토: 코드 의미, 사라진 사실, 이름 변경 후 ID, 관련 문서/테스트의 실제 영향, Ollama 초안 승인, 평가 정답 재작성.

`sync-apply` 입력의 review_reason은 검토 기록이지 진실성 증명이 아니다. 완전한 의미 분석이나 저장되지 않은 관계의 영향 탐지를 보장하지 않는다.

### 2.2 변경 단위

첫 버전은 파일 단위다. 선택한 파일의 변경으로 영향을 받는 레코드는 통째로 검토한다. 줄 변경 최적화는 하지 않는다.

새 파일과 기록 없이 검토한 파일을 구분하기 위해 별도 reviewed_files가 필요하다. records에 근거가 있다고 파일 전체가 검토된 것으로 간주하지 않는다.

이름 변경은 기본적으로 삭제+추가다. 내용 해시가 동일한 유일한 old/new 쌍만 `rename_hints`로 표시하고 자동으로 path 또는 ID를 고치지 않는다. 중복 내용이면 hint를 내지 않는다.

### 2.3 기존 레코드와 의미 영향

직접 영향 = 선택 파일을 근거로 가지는 모든 레코드. 신선한 레코드도 선택 파일을 다시 검토한다면 포함한다.

관계 영향 = 직접 영향 레코드의 subject/object `(type,id)`를 하나라도 공유하는 나머지 레코드, 딱 한 홉이다. type을 빼고 문자열 ID만 비교하지 않는다.

모든 영향 ID에 `replace/drop/keep` 중 하나의 결정이 있어야 apply한다. 해시가 달라진 레코드에는 keep을 허용하지 않는다. 관계 후보 keep은 현재 근거를 읽고 의미가 유효하다고 판단한 경우만 사용한다.

추론 관계를 재귀적으로 확장하지 않는다. 누락 관계·간접 영향·unchanged docs의 모순은 보고서에 검사 범위와 한계로 남긴다.

## 3. 정본 스키마와 호환성

JSON `version: 1`을 유지하고 선택 필드만 추가한다.

```json
{
  "version": 1,
  "ontology": {},
  "records": {},
  "sync": {
    "version": 1,
    "reviewed_files": {
      "src/auth.py": "sha256-of-reviewed-file"
    }
  }
}
```

예제의 해시 문자열은 설명용이다. 실제 입력 검증은 기존 `[0-9a-f]{64}`를 요구한다.

- sync 부재는 `{version:1, reviewed_files:{}}`로 메모리에서 해석한다. load/query로 파일을 자동 migration하지 않는다.
- 기존 records의 evidence 해시를 reviewed_files로 복사하지 않는다. 첫 sync는 해당 파일이 `unreviewed`로 나타나도 정상이다.
- reviewed_files에는 승인된 파일 전체 검토의 해시만 저장한다. 사실이 0개인 파일도 리뷰 결과가 있으면 저장할 수 있다.
- 삭제/제외된 경로를 승인한 경우 ledger에서 제거한다. 제외된 내용은 읽거나 모델로 보내지 않는다.
- 경로는 기존 relative_path/safe_path 정책을 따른다. sync 필드·버전·map·해시는 명시 검증하고 오류면 저장 전에 실패한다.
- `put/drop/refresh`는 sync ledger를 보존한다. 이들 명령은 파일 전체 검토 승인이 아니므로 ledger를 자동 진전시키지 않는다.

## 4. CLI 및 순수 함수 계약

### 4.1 sync-plan: 읽기 전용

```sh
python3 <helper> --repo <repo> sync-plan
python3 <helper> --repo <repo> sync-plan --path src/auth.py --path tests/test_auth.py
```

`--path`는 반복 가능한 정확한 레포 상대 파일 경로다. glob/디렉터리 축약은 지원하지 않는다. 생략하면 변경 후보 전체를 선택한다.

새 함수는 `sync.py`에 둔다. 이 모듈에서 knowledge.py를 import하지 않는다. CLI가 기존 함수로 데이터를 읽어 넘긴다.

```python
def snapshot_token(data, sources, excluded): ...
def make_plan(data, sources, excluded, selected_paths=None): ...
def apply_review(data, sources, excluded, review): ...
```

`sources`는 기존 `{path: (text, sha256)}` 구조다. 함수들은 입력을 수정하지 않으며 apply_review는 새 data와 report를 반환한다. I/O, Ollama, DB 호출은 없다.

token은 `json.dumps(..., sort_keys=True, ensure_ascii=False, separators=(',', ':'))`의 UTF-8 SHA-256이다. 대상은 전체 data, 현재 허용 파일 path→hash map, 정렬한 excluded 목록이다. 시간·HEAD만으로 token을 만들지 않는다.

출력의 필수 필드:

```json
{
  "version": 1,
  "base_token": "64-lowercase-hex",
  "selected_paths": ["src/auth.py"],
  "changes": [{"path":"src/auth.py","kind":"modified","before":"old-hash","after":"new-hash"}],
  "direct_ids": ["auth-limit"],
  "related_ids": ["auth-test"],
  "rename_hints": [],
  "excluded_paths": [],
  "remaining_paths": [],
  "stored": false
}
```

출력 hash 예시는 설명용이며 실행 시 실제 해시를 출력한다. 출력 배열은 정렬해 동일 상태의 반복 실행 결과가 동일하게 한다.

change.kind 규칙:

| 상태 | kind |
| --- | --- |
| 현재 허용 파일, ledger 없음 | unreviewed |
| 현재 허용 파일, ledger 해시 다름 | modified |
| ledger/evidence에 있었으나 현재 파일 없음 | missing |
| ledger/evidence에 있었고 excluded 목록에 있음 | unavailable |
| ledger 해시 같음 | 기본 후보 아님; --path로 지정하면 review |

후보집합은 ledger 경로, records evidence 경로, 현재 허용 파일의 합집합으로 계산한다. `missing`은 Git에서 정확한 delete/ignore를 단정하지 않는 명칭이다.
--path는 이 집합이나 excluded 집합에 있어야 한다. 임의의 알 수 없는 경로, 중복 경로, 절대 경로는 오류다.
unavailable를 지식으로 새로 추출하지 않는다. 해당 경로를 근거로 가진 레코드의 제거/대체 판단만 요청한다.

### 4.2 검토 배치

에이전트는 plan을 읽고 각 선택 파일과 영향 레코드를 검토한 뒤 다음 JSON을 작성한다. `.repo-knowledge/` 아래 임시 배치 또는 레포 밖을 사용해 인덱스 유입을 막는다.

```json
{
  "version": 1,
  "base_token": "token-returned-by-sync-plan",
  "selected_paths": ["src/auth.py"],
  "files": [{"path":"src/auth.py","sha256":"current-hash","review_reason":"Reviewed the full file; limit is now 6."}],
  "decisions": [
    {"id":"auth-limit","action":"replace","review_reason":"Value changed; replacement is in records."},
    {"id":"auth-test","action":"keep","review_reason":"Read current test; assertion uses shared constant and remains valid."}
  ],
  "records": [{
    "id":"auth-limit",
    "subject":{"id":"src/auth.py:LIMIT","type":"symbol"},
    "relation":"implements",
    "object":{"id":"login-retry-limit","type":"concept"},
    "summary":"LIMIT is 6.",
    "epistemic":"observed",
    "evidence":[{"path":"src/auth.py","start":1,"end":1,"sha256":"current-hash"}]
  }]
}
```

이 예제는 src/auth.py 첫 줄이 `LIMIT = 6`일 때의 전체 레코드 구조다.
`current-hash`와 token은 문서상의 기호다. 실행 배치는 source/sync-plan이 반환한 실제 64자리 해시를 복사해야 하며 기호 문자열은 검증에서 실패해야 한다.

배치 검증:

1. version/필드 타입/필수 필드/문자열/중복을 검증한다. 목록이 아닌 입력을 순회하지 않는다.
2. 현재 snapshot_token이 base_token과 다르면 `Sync snapshot changed; rerun sync-plan`으로 실패한다.
3. selected_paths로 make_plan을 다시 계산한다. 저장된 direct_ids를 신뢰하지 않는다.
4. files의 경로 집합은 selected_paths와 정확히 같아야 한다. 현재 없는/제외 경로는 sha256=null, 있는 경로는 현재 해시다. review_reason은 공백 제외 비어 있지 않아야 한다.
5. decisions ID 집합은 direct_ids∪related_ids와 정확히 같아야 한다. 누락·추가·중복은 실패한다.
6. action은 replace/drop/keep뿐이다. keep은 기존 evidence가 모두 fresh여야 한다. replace는 같은 ID의 새 레코드가 records에 정확히 1개 존재해야 한다.
7. drop/keep ID는 records에 존재하면 안 된다. 새 ID 추가는 허용하지만 기존 비영향 ID를 덮어쓰면 실패한다.
8. 신규 레코드는 선택 경로 중 하나를 evidence로 가져야 한다. replace는 다른 유효 근거로 대체할 수 있다. 모든 새/대체 레코드는 기존 validate_record 및 현재 소스 freshness 검사를 통과해야 한다.
9. 전체 선택 파일을 검토했어도 의미 있는 사실이 없으면 records=[]를 허용한다. 이 경우 replace 결정이 없어야 한다. 삭제만 있는 배치도 허용한다.
10. 직접/관계 레코드 중 unresolved가 있으면 해당 배치는 적용하지 않는다. 더 작은 --path 범위로 새 계획을 만들 수 있지만 그 범위의 관계 영향도 다시 검토해야 한다.

### 4.3 sync-apply: JSON 한 번 저장

```sh
python3 <helper> --repo <repo> sync-apply .repo-knowledge/review.json
```

새 CLI는 writer 집합에 넣는다. lock 획득 → inventory/load → 배치 읽기/검증 → 메모리 복사 수정 → 다시 inventory/load/token 확인 → save 한 번 순서다. 검증 중 원본 data를 수정하지 않는다.

replace/drop ID를 먼저 복사본에서 제거하고 승인 records를 넣는다. keep은 indexed_commit을 포함해 원래 레코드 bytes-equivalent 값을 유지한다. 새/교체 records에만 put과 동일한 HEAD 또는 null 규칙을 적용한다.

선택 경로 ledger만 현재 해시로 승인하고 없는 경로는 제거한다. 비선택 파일 baseline은 그대로 둔다. unrelated 파일까지 자동으로 승인하지 않는다.

결과: `applied:true`, sorted `stored_ids/dropped_ids/kept_ids/reviewed_paths`, `remaining_paths`, `vectors_next:"Run index"`.
오류 시 exit=1, JSON bytes 불변. 재적용은 token mismatch로 실패한다. 이를 멱등 성공이라고 표시하지 않는다.

사용자 편집기는 잠글 수 없으므로 마지막 확인 직후 편집까지 막는다고 주장하지 않는다. 검색 시 해시 검증이 최종 방어선이다. 실패/충돌 시 자동 재시도·LLM 자동 재호출을 하지 않는다.

## 5. PostgreSQL 증분 인덱스 계약

`vectors.build(root, fresh, rebuild=False)`로 확장하고 CLI에 `index --rebuild`를 추가한다. 기존 `index`는 증분이 기본이다.

기존 `fingerprint(record)`와 `SIGNATURE`를 그대로 사용한다. 스키마 변경은 필요 없다. signature 변경 또는 --rebuild이면 모든 현재 fresh 레코드를 재임베딩한다.

단일 DB 트랜잭션 안에서 현재 advisory lock을 유지한다:

```python
current = {record_id: fingerprint(record) for record_id, record in fresh.items()}
# existing: 해당 namespace DB의 id -> fingerprint, signature 확인 후 조회
removed = sorted(set(existing) - set(current))
changed = sorted(k for k in current if rebuild or existing.get(k) != current[k])
unchanged = sorted(set(current) - set(changed))
```

실제 구현은 signature mismatch도 rebuild=True로 처리한다. signature가 없으면 namespace header를 먼저 INSERT한다.
removed만 DELETE하고 changed만 embed/upsert한다. psycopg placeholder로 모든 값을 바인딩한다. 다른 namespace 행은 만지지 않는다.

```sql
INSERT INTO repo_knowledge.embeddings (repo,id,fingerprint,embedding)
VALUES (%s,%s,%s,%s::vector)
ON CONFLICT (repo,id) DO UPDATE
SET fingerprint=EXCLUDED.fingerprint, embedding=EXCLUDED.embedding
```

- changed가 비어 있으면 embedder를 생성하지 않는다. 삭제만 있어도 모델 호출은 0이다.
- 임베딩 수/차원 문제는 예외를 내고 DB 트랜잭션 전체 롤백한다. signature 변경도 함께 롤백돼야 한다.
- 반환값 기존 indexed/backend/model/namespace 유지; embedded/deleted/unchanged/rebuilt 추가.
- indexed는 최종 fresh 레코드 총수다. 이번에 임베딩한 개수가 아니다.
- JSON 성공 후 DB 실패: JSON은 새 상태 유지, DB는 이전 상태 유지. 사용자에게 인덱스 지연을 알리고 index만 재실행한다. JSON을 과거 상태로 되돌리지 않는다.
- 현재 search의 fingerprint+근거 필터와 unindexed_fresh_records를 유지한다. DB 지연 중 stale 행은 제외되고 새 레코드 미색인은 표시한다.
- 임베딩 모델 변경만으로 Ollama 추출을 다시 하지 않는다. 추출 모델 변경만으로 기존 승인 사실을 무효화하지 않는다.

## 6. 업무 흐름 및 신뢰도 스킬 연결

업무 시작: status → sync-plan → query → 현재 코드 확인. pending이 있어도 원래 사용자 업무는 직접 탐색으로 계속할 수 있다. 읽기 전용 질문은 저장/추출을 자동 수행하지 않는다.

업무 종료(코드 변경 또는 지식 갱신이 요청된 경우): sync-plan --path ... → source/extract(선택) → 영향 레코드 검토 → sync-apply → index → 대표 질의 확인. 이 새 흐름 전에 refresh를 호출하지 않는다. refresh는 명시적 수동 stale 삭제용으로 남긴다.

변경 없는 파일의 추출을 반복하지 않는다. unreviewed 목록이 크면 업무 관련 경로만 선택하고 remaining_paths를 남긴다. 모든 파일을 한 번에 검토했다고 보고하지 않는다.

평가 케이스는 골드 evidence hash를 먼저 확인한다. 경로 삭제/이름 변경/해시 변화가 있는 케이스는 재검토 필요로 분류하고 결과에서 숨기지 않는다. 골드 answer/hash를 자동 치환하지 않는다. frozen benchmark version을 올린 뒤 새 평가를 수행한다. 이전/이후 버전 점수를 동일 조건 비교로 표시하지 않는다.

기존 guide 갱신: 명시적인 `init --update-guide` 옵션을 추가한다. 기본 init은 기존 guide 보존을 유지한다. 옵션은 기존 guide bytes를 `.repo-knowledge/guide.md.bak`에 독점 생성으로 백업한 뒤 GUIDE로 교체한다. 이미 bak가 있으면 덮어쓰지 않고 실패한다. guide가 없으면 새로 생성하고 백업은 만들지 않는다. 이 옵션은 문서 갱신만 하며 facts/ledger/index를 수정하지 않는다.
글로벌 설치만으로 모든 대상 레포 guide가 갱신된다고 말하지 않는다. 활성 레포에서 새 workflow로 전환할 때만 옵션을 실행한다.

## 7. 구현 작업 순서와 검증

각 Task는 RED → 구현 → GREEN → 해당 파일만 commit 순서다. 실제 fixture는 tempfile Git 레포, 테스트 데이터는 `.repo-knowledge/` 내부에 둔다. 기존 테스트의 run/git/put 패턴을 읽고 재사용하되 제품에 테스트 전용 helper를 추가하지 않는다.

### Task 1 — 읽기 전용 변경 계획

**Files:** 신규 sync.py 및 tests/test-repo-knowledge-sync.py; knowledge.py load/execute/main.
**Consumes:** inventory, relative_path, records evidence, 선택적 sync ledger.
**Produces:** snapshot_token/make_plan, sync-plan CLI. 뒤 Task는 3–4절의 정확한 키 이름을 사용한다.

새 테스트의 시작점은 다음 실행 가능한 fixture다. 이 단계에서는 새 명령 부재로 실패한다.
후속 assertion과 시나리오는 이 tempfile 범위 안에 추가한다.

```python
import json
from pathlib import Path
import subprocess
import sys
import tempfile

HELPER = Path(__file__).resolve().parents[1] / '.claude/skills/repo-knowledge/scripts/knowledge.py'

def main():
    with tempfile.TemporaryDirectory(prefix='knowledge sync ') as directory:
        root = Path(directory)
        subprocess.run(['git', '-C', directory, 'init', '-q'], check=True)
        (root / 'auth.py').write_text('LIMIT = 5\n', encoding='utf-8')

        def run(*args, ok=True):
            result = subprocess.run(
                [sys.executable, str(HELPER), '--repo', directory, *args],
                capture_output=True, text=True, timeout=30)
            assert (result.returncode == 0) == ok, (args, result.stdout, result.stderr)
            return json.loads(result.stdout) if ok else result.stderr

        run('init')
        store = root / '.repo-knowledge/knowledge.json'
        before = store.read_bytes()
        first = run('sync-plan', '--path', 'auth.py')
        second = run('sync-plan', '--path', 'auth.py')
        assert first == second
        assert before == store.read_bytes()
        assert first['stored'] is False
        assert first['changes'][0]['kind'] == 'unreviewed'

if __name__ == '__main__':
    main()
```

- [ ] 테스트 fixture: auth.py `LIMIT = 5`, 관련 test_auth.py, 독립 readme.md, 명시 record 2개. init/put 후 JSON을 보관한다.
- [ ] 실패 테스트: `run('sync-plan')`에 stored=False와 auth.py unreviewed가 있어야 한다. 두 번 결과와 JSON bytes가 같아야 한다. 초기 실패 이유는 command 부재여야 한다.
- [ ] 3절 선택 sync 검증과 snapshot_token을 구현한다. sorted canonical JSON + sha256을 사용한다.
- [ ] 4.1절 kind/선택/direct/related/hint를 구현한다. typed entity pair를 set으로 구성한다.
- [ ] CLI parser/dispatch를 연결한다. writer 및 venv 재실행 목록에는 sync-plan을 넣지 않는다.
- [ ] 다음 핵심 assertion을 구현하고 실행한다.

```python
assert first == second
assert before == store.read_bytes()
assert plan['stored'] is False
assert plan['direct_ids'] == ['auth-limit']
assert plan['related_ids'] == ['auth-test']
```

- [ ] `python3 tests/test-repo-knowledge-sync.py` 통과 후 `feat: plan repository knowledge changes` 커밋.

### Task 2 — 승인 배치와 원자 반영

**Files:** sync.py apply_review; knowledge.py sync-apply 분기/lock; sync 테스트.
**Consumes:** Task 1 plan/token. **Produces:** 새 data/report, sync-apply CLI.

- [ ] RED: auth LIMIT을 6으로 수정한 후 plan을 만들고, replace auth-limit + keep auth-test 배치를 준비한다. helper가 아직 없어서 실패해야 한다.
- [ ] 4.2절 각 검증을 저장보다 먼저 수행한다. 기존 validate_record/freshness는 knowledge.py에서 재사용한다. sync.py에 복사하지 않는다.
- [ ] token 확인은 lock 안에서 수행한다. 적용 직전 두 번째 inventory/load 검사를 연결한다.
- [ ] deepcopy한 data에 결정과 ledger를 반영하고 기존 save를 정확히 한 번 호출한다.
- [ ] 다음 테스트를 실제 CLI로 실행한다.

```python
assert result['stored_ids'] == ['auth-limit']
assert result['kept_ids'] == ['auth-test']
assert saved['records']['auth-test'] == original_test_record
assert saved['sync']['reviewed_files']['auth.py'] == current_hash
assert unrelated_path not in saved['sync']['reviewed_files']
```

- [ ] 오류 배치 각각에서 `assert store.read_bytes() == before`: 결정 누락/중복, stale keep, 잘못된 해시, replace without record, 비영향 ID 덮어쓰기, 잘못된 endpoint.
- [ ] `python3 tests/test-repo-knowledge-sync.py` 및 기존 test-repo-knowledge.py 통과 후 `feat: apply reviewed knowledge changes atomically` 커밋.

### Task 3 — 삭제·분기 전환·중단 회복

**Files:** sync 테스트, 발견된 결함에 한해 sync.py/knowledge.py.
**Consumes:** Task 2 CLI. **Produces:** 변경 생명주기의 검증된 회귀.

- [ ] 아래 matrix의 S01–S15를 실패부터 확인한다. 테스트가 이미 통과하면 불필요한 제품 변경을 하지 않는다.
- [ ] 삭제 승인 후 옛 ID가 canonical에서 없어지고 lexical 결과에도 없어야 한다.
- [ ] plan 후 unrelated 파일 편집도 token mismatch로 실패해야 한다. 보수적인 전역 snapshot 정책이다.
- [ ] 기존 writer lock이 있으면 exit=1이며 lock을 자동 지우지 않아야 한다.
- [ ] 신규 파일 records=[] 승인 후 재계획에서 unreviewed로 반복 표시되지 않아야 한다.
- [ ] 기존 put/drop/refresh를 실행해 ledger 보존을 검증한다.
- [ ] 수정한 범위만 `test: cover incremental knowledge lifecycle` 커밋.

### Task 4 — 변경된 벡터만 재생성

**Files:** vectors.py build, knowledge.py index parser, test-repo-knowledge-vectors.py.
**Consumes:** 현재 fresh records와 기존 DB schema. **Produces:** index 기본 증분/--rebuild와 카운터.

- [ ] RED: 두 번째 동일 index에서 embedded=0; 기존 구현에는 카운터가 없어 실패해야 한다.
- [ ] 5절 알고리즘/SQL/카운터 구현. SQL mutation과 임베딩 모두 기존 DB 트랜잭션 범위에 둔다.
- [ ] no-op/deletion-only에서는 embedder를 예외를 내는 sentinel로 대체하고 성공을 검증한다. 나머지 vector/query 검사는 실제 cached 모델을 사용한다.
- [ ] 레코드 1개 변경 시 embedded=1, unchanged=N-1; 삭제 시 deleted=1, embedded=0을 검사한다.
- [ ] 강제 잘못된 임베딩 결과로 실패시켜 전체 DB rows와 signature가 이전과 동일한지 검사한다.
- [ ] 실제 PostgreSQL 통합 검사를 실행하고 `perf: update only changed repository vectors` 커밋.

### Task 5 — 에이전트 지침과 평가 연결

**Files:** knowledge.py GUIDE/init parser, repo-knowledge SKILL.md/references/records.md, docs/skills/repo-knowledge.md, rag-reliability SKILL.md/references/evaluation.md, 기존 CLI 테스트.
**Consumes:** Task 1–4 명령. **Produces:** 업무 전후 일관된 흐름, 명시 guide upgrade.

- [ ] RED: 기본 init은 custom guide 보존, --update-guide는 backup 후 변경, 기존 backup 존재 시 bytes 불변.
- [ ] 옵션 구현 시 symlink 검사는 기존 safe_path를 사용한다. backup은 exclusive creation으로 저장한다.
- [ ] 6절 흐름을 각 문서에 반영한다. 새 흐름에서 refresh-before-plan 지시가 남지 않게 검색한다.
- [ ] 평가 지침에는 gold invalidation이 재검토 요청이지 자동 정답 수정이 아님을 추가한다.
- [ ] `rg -n 'refresh|rebuild|sync-plan|sync-apply' .claude/skills/repo-knowledge docs/skills/repo-knowledge.md` 결과를 읽고 기존 수동 명령 설명과 새 기본 흐름을 구분한다.
- [ ] 해당 회귀 및 두 스킬 quick_validate 통과 후 `docs: define incremental RAG maintenance workflow` 커밋.

### Task 6 — 실제 에이전트 적용과 배포

**Files:** 검증 보고서 `docs/reports/2026-09-09-repo-rag-incremental-sync-verification.md`; 수정 스킬 전역 복사본.
**Consumes:** 완료된 Task 1–5. **Produces:** 사용 가능한 전역 설치와 증거.

- [ ] 아래 8절 전체 명령을 실행한다. DB/Ollama 부재는 건너뛴 항목으로 기록하고 전체 통과라 보고하지 않는다.
- [ ] 임시 레포에서 초기 구축 → 값 변경 → 관련 문서 모순 → sync-plan → 검토 → apply → index → query를 실제 Claude와 Codex 각각 실행한다. 두 실행은 별도 경로/namespace를 사용한다.
- [ ] 에이전트가 unsupported Ollama 초안을 그대로 승인했는지 원문 대조로 검토한다. 원문과 검토 배치/명령 로그를 보고서에 연결한다.
- [ ] benchmark의 기존 값/해시가 자동으로 새 정답으로 바뀌지 않고 invalid로 표시되는지 확인한다. 실제 테스트는 평가 스킬의 적용 검증이며 자동 평가 CLI가 생겼다고 말하지 않는다.
- [ ] 임시 DB namespace만 정리한다. 사용자 namespace는 삭제하지 않는다.
- [ ] 전역 canonical에 rsync --exclude .venv로 반영하고 Claude/Codex/agents 경로에서 같은 파일 및 CLI help를 확인한다.
- [ ] 수정한 파일만 커밋/푸시한다. 다른 세션의 staged 파일은 포함하지 않는다. 최종 보고에 버전/범위/테스트/미검증 항목/commit을 명시한다.

## 8. 수용 테스트와 완료 기준

| ID | 입력/상황 | 반드시 관찰할 결과 |
| --- | --- | --- |
| S01 | ledger 없는 v1 store | 읽기 성공, 파일 unreviewed, migration 쓰기 없음 |
| S02 | 동일 파일 재계획 | 안정적 token/결과, Ollama 0회 |
| S03 | 상수 5→6 | modified, 직접 ID+typed one-hop 후보 |
| S04 | 파일 삭제 | missing, 검토 후 해당 ID drop |
| S05 | 이름 변경 | 삭제+추가, unique hash일 때 hint만 |
| S06 | 동일 내용 파일 여러 개 | rename 자동 추정 없음 |
| S07 | symlink/ignore/secret로 전환 | 내용 전송 없음, 기존 근거 stale |
| S08 | 새 untracked 허용 파일 | unreviewed; ignored 새 파일은 추출 제외 |
| S09 | 여러 파일 근거 레코드 | 하나만 변경해도 전체 레코드 재검토 |
| S10 | 관계 ID 같고 type 다름 | 잘못된 one-hop 매칭 없음 |
| S11 | plan 후 소스/JSON 변경 | token 충돌, bytes 불변 |
| S12 | mixed valid/invalid batch | 부분 반영 0 |
| S13 | 파일 검토 결과 사실 0 | 승인 가능, ledger 진전, 반복 추출 없음 |
| S14 | 동일 경로 branch 전환 | HEAD 대신 해시 차이로 감지 |
| S15 | 일부 경로만 apply | 나머지 baseline 보존, remaining 노출 |
| V01 | 동일 index 2회 | 두 번째 embedded=0, 모델 생성 0 |
| V02 | record 1개 변경/추가 | 해당 개수만 임베딩 |
| V03 | 삭제만 | DB 삭제, 모델 호출 0 |
| V04 | signature 변경/--rebuild | 전체 fresh 재임베딩 |
| V05 | embedding/DB 실패 | 이전 rows+signature 보존 |
| V06 | JSON 반영 후 DB 실패 | 새 JSON 유지, stale DB 검색 제외, index만 재시도 |
| V07 | 다른 레포 namespace | 행/검색 불변 |
| G01 | 미변경 문서가 코드와 모순 | 에이전트 의미 검토에서 수정/삭제; hash만으로 통과하지 않음 |
| G02 | 골드 근거 변경 | invalid/provisional, 자동 정답 치환 없음 |
| G03 | guide 사용자 수정 | 기본 init 보존; 명시 upgrade backup |

검증 명령은 저장소 루트에서 실행한다. python 경로는 실행 환경에서 확인하고 의존성 미설치를 테스트 통과로 바꾸지 않는다.

```sh
python3 tests/test-repo-knowledge-sync.py
python3 tests/test-repo-knowledge.py
/usr/bin/python3 tests/test-repo-knowledge-sync.py
/usr/bin/python3 tests/test-repo-knowledge.py
~/.claude/skills/repo-knowledge/.venv/bin/python tests/test-repo-knowledge-vectors.py
python3 tests/test-repo-knowledge-ollama.py
python3 -m py_compile .claude/skills/repo-knowledge/scripts/knowledge.py .claude/skills/repo-knowledge/scripts/sync.py .claude/skills/repo-knowledge/scripts/vectors.py
/usr/bin/python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py .claude/skills/repo-knowledge
/usr/bin/python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py .claude/skills/rag-reliability
git diff --check
```

완료 조건: S/V/G 필수 항목의 실행 증거가 있고, 기존 회귀가 유지되고, 전역 경로에서 새 CLI가 동작하며, 평가 결과와 실제 구현 범위가 일치한다. 계획 작성/코드 컴파일/모의 시험만으로 실제 레포 신뢰도 개선을 주장하지 않는다.

## 실행 전 자기 검토

- 요구 추적: 증분 파일 검토=Task1–3, 관계 영향=Task1–2/G01, 안전한 저장=Task2–4, 업무 전후=Task5–6, 평가 변경=Task5/G02.
- 모든 명령과 데이터 필드는 위 계약에서 정의됐다. 기존 명령 호환성과 legacy ledger 부재 처리를 명시했다.
- 단계별 독립 완료 기준과 실패시 보존 범위가 있다. JSON/DB 양쪽 동시 원자성을 약속하지 않는다.
- 성능 상한: inventory와 비교는 전체 O(files+records)이며 관계 후보도 저장된 그래프 범위다. 더 큰 시스템은 별도 측정 후 설계한다.
