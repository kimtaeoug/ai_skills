# 스킬 진화 메커니즘 (Skill Evolution Mechanism) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 스킬(SKILL.md)이 생성 이후 실사용을 거치며 어떻게 바뀌었는지 baseline 대비 델타를 사람이 명시적으로 확정해 기록하고, 그 기록을 다음 스킬 생성 시 참고할 수 있게 하는 최소 도구를 만든다.

**Architecture:** 순수 로직 CLI(`bin/evolve`)가 git 유무와 무관하게 baseline snapshot과 diff를 담당하고, 대화형 스킬(`evolve`)이 그 diff를 받아 사람에게 맥락/효과를 묻고 `evolution/records/`에 불변 기록을 남긴다. 승격(레코드→lesson→pattern)은 항상 사람이 수동으로 한다.

**Tech Stack:** Bash(표준 유닉스 도구: git, diff, cp), Markdown(스킬/레코드 포맷).

## Global Constraints

- 외부 의존성 추가 금지 — bash, git, diff, cp 등 표준 도구만 사용한다.
- 레코드→lesson→pattern 승격은 항상 사람이 결정한다. 자동 승격 로직을 작성하지 않는다.
- v1 범위에서 `SKILL.md` 자동 수정 코드를 작성하지 않는다.
- `evolve` 스킬의 실제 소스는 `~/.agents/skills/evolve`에 두고, `~/.claude/skills/evolve`는 그리로 가는 symlink로 만든다 (기존 스킬들과 동일한 컨벤션: `~/.claude/skills/<name> -> ../../.agents/skills/<name>`).
- CLI(`bin/evolve`)와 데이터(`evolution/`)는 워크스페이스 repo(`/Users/deratio/skills`) 안에 둔다. `evolve` 스킬은 이 CLI를 절대경로로 호출한다.
- `evolution/.state/`(baseline 포인터, copy-mode 스냅샷 사본)는 로컬 기계 상태이므로 git에 커밋하지 않는다. `evolution/records/`, `evolution/lessons/`, `evolution/patterns/`는 커밋 대상이다.

---

### Task 1: `bin/evolve` CLI (snapshot / diff) + 스모크 테스트

**Files:**
- Create: `bin/evolve`
- Create: `tests/test-evolve.sh`
- Create: `.gitignore`

**Interfaces:**
- Produces: `bin/evolve snapshot <skill-dir>` — 종료 코드 0 성공, 1 에러(디렉토리 없음). stdout에 `evolve: snapshot recorded (...) for <skill-name>` 출력.
- Produces: `bin/evolve diff <skill-dir>` — baseline 없으면 exit 1, stderr에 `evolve: no baseline found for '<skill-name>'. Run: evolve snapshot <skill-dir>`. baseline 있으면 stdout에 unified diff 출력(변경 없으면 빈 출력), exit 0.
- Produces: 상태 파일 `evolution/.state/<skill-name>.txt` (내부 포맷 `mode=git|copy`, `ref=...`, `skill_path=...`) — 이후 Task에서 사람이 참고할 수 있으나 코드로 직접 파싱하는 다른 Task는 없음.

- [ ] **Step 1: 디렉토리 구조와 `.gitignore` 준비**

```bash
mkdir -p bin tests
```

`.gitignore` 생성:

```
evolution/.state/
```

- [ ] **Step 2: `bin/evolve` 작성**

```bash
#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
EVOLUTION_DIR="$REPO_ROOT/evolution"
STATE_DIR="$EVOLUTION_DIR/.state"

usage() {
  echo "Usage: evolve snapshot <skill-dir> | evolve diff <skill-dir>" >&2
  exit 1
}

resolve_dir() {
  local d="$1"
  [ -d "$d" ] || { echo "evolve: not a directory: $d" >&2; exit 1; }
  (cd "$d" && pwd)
}

cmd_snapshot() {
  local skill_dir skill_name state_file
  skill_dir="$(resolve_dir "$1")"
  skill_name="$(basename "$skill_dir")"
  mkdir -p "$STATE_DIR"
  state_file="$STATE_DIR/${skill_name}.txt"

  if git -C "$skill_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    local sha
    sha="$(git -C "$skill_dir" rev-parse HEAD)"
    {
      echo "mode=git"
      echo "ref=$sha"
      echo "skill_path=$skill_dir"
    } > "$state_file"
    echo "evolve: snapshot recorded (git HEAD $sha) for $skill_name"
  else
    local snapshot_dir="$STATE_DIR/${skill_name}.snapshot"
    rm -rf "$snapshot_dir"
    cp -r "$skill_dir" "$snapshot_dir"
    {
      echo "mode=copy"
      echo "ref=$snapshot_dir"
      echo "skill_path=$skill_dir"
    } > "$state_file"
    echo "evolve: snapshot recorded (file copy) for $skill_name"
  fi
}

cmd_diff() {
  local skill_dir skill_name state_file mode ref skill_path
  skill_dir="$(resolve_dir "$1")"
  skill_name="$(basename "$skill_dir")"
  state_file="$STATE_DIR/${skill_name}.txt"

  [ -f "$state_file" ] || {
    echo "evolve: no baseline found for '$skill_name'. Run: evolve snapshot $skill_dir" >&2
    exit 1
  }

  while IFS='=' read -r key value; do
    case "$key" in
      mode) mode="$value" ;;
      ref) ref="$value" ;;
      skill_path) skill_path="$value" ;;
    esac
  done < "$state_file"

  if [ "$mode" = "git" ]; then
    git -C "$skill_path" diff "$ref" -- .
  else
    diff -ru "$ref" "$skill_path"
    local status=$?
    if [ "$status" -ge 2 ]; then
      echo "evolve: diff failed (exit $status)" >&2
      exit "$status"
    fi
  fi
}

case "${1:-}" in
  snapshot) shift; [ $# -eq 1 ] || usage; cmd_snapshot "$1" ;;
  diff) shift; [ $# -eq 1 ] || usage; cmd_diff "$1" ;;
  *) usage ;;
esac
```

```bash
chmod +x bin/evolve
```

- [ ] **Step 3: 스모크 테스트 작성**

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EVOLVE="$REPO_ROOT/bin/evolve"
TMP="$(mktemp -d)"

cleanup() {
  rm -rf "$TMP"
  rm -f "$REPO_ROOT/evolution/.state/copy-skill.txt"
  rm -rf "$REPO_ROOT/evolution/.state/copy-skill.snapshot"
  rm -f "$REPO_ROOT/evolution/.state/git-skill.txt"
  rm -f "$REPO_ROOT/evolution/.state/no-baseline.txt"
  rm -f "$REPO_ROOT/evolution/.state/no-change-skill.txt"
  rm -rf "$REPO_ROOT/evolution/.state/no-change-skill.snapshot"
}
trap cleanup EXIT

pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1"; exit 1; }

# --- copy-mode (non-git dir) ---
COPY_SKILL="$TMP/copy-skill"
mkdir -p "$COPY_SKILL"
echo "line one" > "$COPY_SKILL/SKILL.md"

"$EVOLVE" snapshot "$COPY_SKILL" > /dev/null
echo "line two" >> "$COPY_SKILL/SKILL.md"
DIFF_OUT="$("$EVOLVE" diff "$COPY_SKILL")"
echo "$DIFF_OUT" | grep -q "line two" && pass "copy-mode diff captures change" || fail "copy-mode diff missing change"

# --- git-mode ---
GIT_SKILL="$TMP/git-skill"
mkdir -p "$GIT_SKILL"
git -C "$GIT_SKILL" init -q
echo "line one" > "$GIT_SKILL/SKILL.md"
git -C "$GIT_SKILL" add SKILL.md
git -C "$GIT_SKILL" -c user.email=t@t.com -c user.name=t commit -q -m init

"$EVOLVE" snapshot "$GIT_SKILL" > /dev/null
echo "line two" >> "$GIT_SKILL/SKILL.md"
DIFF_OUT="$("$EVOLVE" diff "$GIT_SKILL")"
echo "$DIFF_OUT" | grep -q "line two" && pass "git-mode diff captures change" || fail "git-mode diff missing change"

# --- no-changes case ---
NO_CHANGE_SKILL="$TMP/no-change-skill"
mkdir -p "$NO_CHANGE_SKILL"
echo "content" > "$NO_CHANGE_SKILL/SKILL.md"
"$EVOLVE" snapshot "$NO_CHANGE_SKILL" > /dev/null
if OUT="$("$EVOLVE" diff "$NO_CHANGE_SKILL")"; then
  [ -z "$OUT" ] && pass "diff with no changes is empty and exits 0" || fail "diff with no changes should be empty, got: $OUT"
else
  fail "diff with no changes should exit 0"
fi

# --- error case: diff without snapshot ---
NO_BASELINE="$TMP/no-baseline"
mkdir -p "$NO_BASELINE"
if "$EVOLVE" diff "$NO_BASELINE" 2>"$TMP/err.log"; then
  fail "diff without snapshot should exit nonzero"
else
  grep -q "no baseline found" "$TMP/err.log" && pass "diff without snapshot errors clearly" || fail "error message missing expected text"
fi

echo "all tests passed"
```

```bash
chmod +x tests/test-evolve.sh
```

- [ ] **Step 4: 테스트 실행해 통과 확인**

Run: `./tests/test-evolve.sh`
Expected: 5개 `PASS:` 라인 + `all tests passed`, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add bin/evolve tests/test-evolve.sh .gitignore
git commit -m "feat: add bin/evolve CLI for skill baseline snapshot and diff"
```

---

### Task 2: `evolve` 대화형 스킬 + symlink 설치

**Files:**
- Create: `~/.agents/skills/evolve/SKILL.md`
- Create: `~/.claude/skills/evolve` (symlink → `../../.agents/skills/evolve`)

**Interfaces:**
- Consumes: `bin/evolve diff <skill-dir>`, `bin/evolve snapshot <skill-dir>` (Task 1) — 절대경로 `/Users/deratio/skills/bin/evolve`로 호출.
- Produces: `evolution/records/<skill-name>/<YYYY-MM-DD>-<slug>.md` 레코드 파일 (스킬 실행 시 대화를 통해 사람이 채움 — 코드가 아니라 스킬 지침이 이 산출물을 만든다).

- [ ] **Step 1: 스킬 소스 디렉토리 생성**

```bash
mkdir -p ~/.agents/skills/evolve
```

- [ ] **Step 2: `~/.agents/skills/evolve/SKILL.md` 작성**

```markdown
---
name: evolve
description: '스킬이 실사용 후 어떻게 바뀌었는지(초기 상태 대비 델타)를 기록해 다음 생성에 참고할 교훈으로 남긴다. bin/evolve CLI로 diff를 뽑고, 사용자에게 맥락/효과를 물어 evolution/records/<skill>/에 레코드를 쓴다. Trigger phrases — 한국어: "이 스킬 진화 기록해줘", "여기까지 변경사항 델타로 남겨줘", "/evolve"; English: "record this skill''s evolution", "capture what changed in this skill", "/evolve".'
---

# Evolve

스킬 하나의 baseline(생성 직후 상태) 대비 현재 상태 사이의 델타를 사람이 명시적으로 확정(승격)해 기록으로 남기는 스킬이다. 자동 트리거 없음 — 사용자가 이 스킬을 호출한 시점에만 동작한다.

## 절차

1. 대상 스킬 디렉토리를 확인한다 (사용자가 지정하지 않으면 물어본다).
2. baseline이 있는지 확인: `/Users/deratio/skills/bin/evolve diff <skill-dir>` 실행.
   - `no baseline found` 에러가 나면, 먼저 `/Users/deratio/skills/bin/evolve snapshot <skill-dir>`로 baseline을 잡을지 사용자에게 확인한다. 방금 baseline을 잡았다면 이번 세션에서는 델타가 없다는 뜻이므로, 다음번 호출부터 의미가 생긴다고 안내하고 종료한다.
   - diff 출력이 비어 있으면(변경 없음) 그대로 사용자에게 알리고 종료한다.
3. diff가 있으면 출력 전체를 읽고, 사용자에게 순서대로 질문한다 (한 번에 하나씩, 답 받고 다음 질문):
   - 이 변경을 어느 프로젝트/도메인에 적용해봤는지 (context)
   - 뭐가 안 먹혀서 고쳤는지 / 뭐가 먹혔는지 (delta 요약, evidence)
   - 다른 스킬에도 재사용할 만한 규칙이라고 생각하는지 (candidate_lessons) — 없으면 생략 가능
4. 답변을 바탕으로 아래 스키마로 레코드를 작성해 `/Users/deratio/skills/evolution/records/<skill-name>/<YYYY-MM-DD>-<slug>.md`에 저장한다. `<slug>`는 변경 내용을 3~5단어로 요약한 kebab-case. 디렉토리가 없으면 만든다.

```md
skill: <skill-name>
baseline: <git SHA 또는 snapshot 경로 — diff 실행 결과에서 확인>
final: <현재 git HEAD 또는 "working tree">
context: <사용자 답변>
delta: <diff 요약, 구조/지침/검증 규칙 변화>
evidence: <사용자가 준 실패/성공 사례. 없으면 이 필드 생략>
candidate_lessons: <재사용 가능 규칙. 없으면 이 필드 생략>
promotion: pending
```

5. 레코드 작성 후 사용자에게 `/Users/deratio/skills/bin/evolve snapshot <skill-dir>`로 baseline을 지금 시점으로 갱신할지 물어본다 (갱신하면 다음 `/evolve`는 이번 이후의 변경만 잡는다). 동의 없이 실행하지 않는다.
6. `evolution/lessons/<skill-name>.md`에 이미 있는 내용과 candidate_lessons가 겹치지 않으면, 사용자에게 그 파일에 추가할지 물어보고 승인 시에만 append한다. 자동으로 추가하지 않는다.

## 하지 않는 것

- `SKILL.md` 자동 수정 금지.
- `evolution/patterns/`로의 자동 승격 금지 — 이건 여러 records/lessons가 쌓인 뒤 사람이 수동으로 한다.
- baseline 갱신을 사용자 동의 없이 하지 않는다.
```

- [ ] **Step 3: symlink 생성**

```bash
ln -s ../../.agents/skills/evolve ~/.claude/skills/evolve
```

- [ ] **Step 4: symlink와 frontmatter 검증**

Run: `ls -la ~/.claude/skills/evolve && head -5 ~/.claude/skills/evolve/SKILL.md`
Expected: symlink가 `../../.agents/skills/evolve`를 가리키고, frontmatter의 `name: evolve` 라인이 보여야 한다.

- [ ] **Step 5: Commit**

이 Task 산출물은 워크스페이스 repo 바깥(`~/.agents`, `~/.claude`)에 있으므로 이 repo에 커밋할 파일이 없다. 커밋 스킵.

---

### Task 3: MVP 실전 적용 — `repo-convention-extractor`에 baseline 설정 및 검증

**Files:**
- Modify: 없음 (도구 실행만, 워크스페이스 repo 파일 변경 없음)

**Interfaces:**
- Consumes: `bin/evolve snapshot`, `bin/evolve diff` (Task 1)

- [ ] **Step 1: 실제 대상 스킬 디렉토리 확인**

Run: `ls ~/.agents/skills/repo-convention-extractor`
Expected: `SKILL.md` 존재.

- [ ] **Step 2: baseline 스냅샷 생성**

Run: `/Users/deratio/skills/bin/evolve snapshot ~/.agents/skills/repo-convention-extractor`
Expected: `evolve: snapshot recorded (file copy) for repo-convention-extractor` 출력 (해당 디렉토리가 git repo가 아니므로 copy-mode로 동작 — fallback 경로가 실제로 검증됨).

- [ ] **Step 3: 변경 없는 상태에서 diff 확인**

Run: `/Users/deratio/skills/bin/evolve diff ~/.agents/skills/repo-convention-extractor`
Expected: 빈 출력, exit code 0. (`echo $?`로 확인)

- [ ] **Step 4: 상태 파일 확인**

Run: `cat /Users/deratio/skills/evolution/.state/repo-convention-extractor.txt`
Expected: `mode=copy`, `ref=/Users/deratio/skills/evolution/.state/repo-convention-extractor.snapshot`, `skill_path=<실제 경로>` 세 줄.

이걸로 baseline이 잡혔으니, `repo-convention-extractor`를 실제로 쓰다가 SKILL.md를 고치게 되면 그 시점에 `evolve` 스킬(Task 2)을 호출해 첫 실제 레코드를 만들 수 있다. 지금은 델타가 없으므로 레코드를 억지로 만들지 않는다 — 있지도 않은 실사용 증거를 조작하지 않는다.

Commit 없음 (`.state`는 gitignore 대상).

---

## Self-Review 결과

- **Spec coverage:** 최소 구성요소(캡처: Task 1) / 하이브리드 트리거(Task 2 절차 1-2) / 3계층 저장소(evolution/records·lessons·patterns, Task 1 스캐폴딩 + Task 2 스킬 지침) / CLI+스킬 인터페이스(Task 1+2) / 레코드 스키마(Task 2 Step 2) / MVP 범위 단일 스킬 적용(Task 3) — 모두 커버됨. 스펙의 "패턴 라이브러리 자동 승격 없음", "SKILL.md 자동 수정 없음"은 Task 2 "하지 않는 것" 섹션과 Global Constraints에 명시.
- **Placeholder scan:** TBD/TODO 없음. 모든 코드 블록은 실행 가능한 전체 내용.
- **Type/interface consistency:** `bin/evolve snapshot <dir>` / `bin/evolve diff <dir>` 시그니처가 Task 1~3에서 동일하게 쓰임. 상태 파일 키(`mode`/`ref`/`skill_path`)도 Task 1 구현과 Task 3 검증에서 일치.
