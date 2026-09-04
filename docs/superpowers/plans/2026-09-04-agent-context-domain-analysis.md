# agent-context Domain Analysis Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a shared `domain` channel to the existing `agent-context.sh` tool so the `agent-context-setup` skill can record a repo's business domain and technical stack, readable later by any Claude/Codex session via `domain-show`.

**Architecture:** Extend the existing single-file bash CLI (`nimbalyst-local/agent-context/agent-context.sh`) with two new subcommands (`domain-set`, `domain-show`) that reuse the existing append/CAS/ref-resolution machinery already used by `append`/`checkpoint`/`resume`. No new files, no new processes, no new dependencies. The setup skill (`SKILL.md`) gains a post-install step where the invoking agent reads a bounded set of repo files and writes a two-section (business domain / technical stack) summary through `domain-set`.

**Tech Stack:** Bash (`set -euo pipefail`), native Git plumbing (`hash-object`, `mktree`, `commit-tree`, `update-ref`) — same as the rest of the package. No jq/python3 needed for this extension (those are only used by `install.sh`'s config merging, untouched here).

## Global Constraints

- Reuse the existing append/CAS/rebuild-retry protocol for the new `domain` ref — do not write new concurrency-handling code (per spec section "에러 처리" item 5).
- Every domain document must carry an explicit confidence label (`high | medium | low | insufficient evidence`) per section; unevidenced claims must say `insufficient evidence` rather than guess (spec item 1).
- `domain-set` must reject an empty/whitespace-only body without creating a commit (spec item 2).
- `domain-show` must never surface a raw Git error for the no-data case; it prints `No domain analysis yet for this repo.` and exits 0 (spec item 3).
- The `.agent-context/DOMAIN.md` mirror file must be written atomically (mktemp + mv) and must not follow a pre-existing symlink at that path (spec item 4).
- The setup skill's repo-reading step is bounded: `README*`, top-level manifest files, and directory structure two levels deep only — never a full recursive read (spec item 6).
- A failure in the domain-analysis step must never fail the setup skill's overall result; `install.sh`'s vendoring/store-init/hook-merge success stands on its own (spec item 7).
- No automatic injection of the domain summary into the `SessionStart` hook (`hooks/onboard.sh` stays untouched) — confirmed out of scope by the user.

---

### Task 1: `domain-set` / `domain-show` / `status` in `agent-context.sh`

**Files:**
- Modify: `nimbalyst-local/agent-context/agent-context.sh`
- Test: `nimbalyst-local/agent-context/smoke-test.sh`

**Interfaces:**
- Produces: `agent-context.sh domain-set --target <repo>` (reads body from stdin, prints new commit OID on success, non-zero exit + no ref mutation on empty body).
- Produces: `agent-context.sh domain-show --target <repo>` (prints `No domain analysis yet for this repo.` or the latest body).
- Produces: `agent-context.sh status --target <repo>` now also prints a `domain: <oid|(unborn)>` line.
- Produces: `<repo-toplevel>/.agent-context/DOMAIN.md`, a plain-text mirror of the latest domain body, written atomically.
- Consumes (existing, unchanged): `ensure_store`, `append_event`, `ref_for`, `tip_for_ref`, `print_event_body`, `BODY_FILE` global convention from `command_append`/`command_checkpoint`.

- [ ] **Step 1: Write the failing smoke-test additions**

Open `nimbalyst-local/agent-context/smoke-test.sh`. Insert the following block immediately before the final line (`printf 'agent-context smoke test passed\n'`):

```bash
DOMAIN_EMPTY_OUTPUT=$("$CLI" domain-show --target "$TARGET")
[ "$DOMAIN_EMPTY_OUTPUT" = 'No domain analysis yet for this repo.' ]

if printf '   \n\t\n' | "$CLI" domain-set --target "$TARGET" >/dev/null 2>&1; then
  printf 'domain-set must reject an empty/whitespace body\n' >&2
  exit 1
fi
if git --git-dir="$STORE" rev-parse --verify --quiet refs/heads/agent-context/domain >/dev/null; then
  printf 'domain-set must not create a ref from an empty body\n' >&2
  exit 1
fi

DOMAIN_BODY_1=$'## Business domain\nSmoke-test fixture repository.\nconfidence: high\n\n## Technical stack\nBash only.\nconfidence: high'
DOMAIN_OID_1=$(printf '%s\n' "$DOMAIN_BODY_1" | "$CLI" domain-set --target "$TARGET")
test "$(git --git-dir="$STORE" rev-parse refs/heads/agent-context/domain)" = "$DOMAIN_OID_1"
"$CLI" domain-show --target "$TARGET" | grep -F 'Smoke-test fixture repository.' >/dev/null
"$CLI" status --target "$TARGET" | grep -F "domain: $DOMAIN_OID_1" >/dev/null
diff <(printf '%s\n' "$DOMAIN_BODY_1") "$TARGET/.agent-context/DOMAIN.md" >/dev/null

SENTINEL="$SCRATCH/sentinel.txt"
printf 'do not touch\n' > "$SENTINEL"
rm -f "$TARGET/.agent-context/DOMAIN.md"
ln -s "$SENTINEL" "$TARGET/.agent-context/DOMAIN.md"

DOMAIN_BODY_2=$'## Business domain\nUpdated after re-analysis.\nconfidence: medium\n\n## Technical stack\nBash only.\nconfidence: high'
DOMAIN_OID_2=$(printf '%s\n' "$DOMAIN_BODY_2" | "$CLI" domain-set --target "$TARGET")
test "$(git --git-dir="$STORE" rev-parse "$DOMAIN_OID_2^")" = "$DOMAIN_OID_1"
test "$(cat "$SENTINEL")" = 'do not touch'
test ! -L "$TARGET/.agent-context/DOMAIN.md"
diff <(printf '%s\n' "$DOMAIN_BODY_2") "$TARGET/.agent-context/DOMAIN.md" >/dev/null
```

- [ ] **Step 2: Run the smoke test to verify it fails**

Run: `bash nimbalyst-local/agent-context/smoke-test.sh`
Expected: FAIL — `agent-context: unknown command: domain-show` (the command doesn't exist yet).

- [ ] **Step 3: Implement `domain-set`, `domain-show`, and the `status` change**

In `nimbalyst-local/agent-context/agent-context.sh`:

3a. Replace the `validate_type` function:

```bash
validate_type() {
  case "$1" in plan|decision|summary|checkpoint) ;; *) die "type must be plan, decision, summary, or checkpoint" ;; esac
}
```

with:

```bash
validate_type() {
  case "$1" in plan|decision|summary|checkpoint|domain) ;; *) die "type must be plan, decision, summary, checkpoint, or domain" ;; esac
}
```

3b. Immediately after the `resolve_store` function (the one ending with `STORE="$common/agent-context.git"` followed by its closing `}`), add a new helper:

```bash
git_toplevel() {
  git -C "$TARGET" rev-parse --show-toplevel 2>/dev/null || die "cannot resolve working tree root for: $TARGET"
}
```

3c. Replace the `usage` function's heredoc body:

```bash
usage() {
  cat <<'EOF'
Usage:
  agent-context.sh init [--target DEV_REPO]
  agent-context.sh append AGENT TYPE [--session ID] [--supersedes OID] [--responds-to OID] [--seen OID,OID,...] [--target DEV_REPO]
  agent-context.sh checkpoint AGENT [--session ID] [--target DEV_REPO]
  agent-context.sh resume AGENT [--target DEV_REPO]
  agent-context.sh log AGENT [--target DEV_REPO]
  agent-context.sh status [--target DEV_REPO]
EOF
}
```

with:

```bash
usage() {
  cat <<'EOF'
Usage:
  agent-context.sh init [--target DEV_REPO]
  agent-context.sh append AGENT TYPE [--session ID] [--supersedes OID] [--responds-to OID] [--seen OID,OID,...] [--target DEV_REPO]
  agent-context.sh checkpoint AGENT [--session ID] [--target DEV_REPO]
  agent-context.sh resume AGENT [--target DEV_REPO]
  agent-context.sh log AGENT [--target DEV_REPO]
  agent-context.sh status [--target DEV_REPO]
  agent-context.sh domain-set [--target DEV_REPO]   (body on stdin)
  agent-context.sh domain-show [--target DEV_REPO]
EOF
}
```

3d. In `command_status`, change the agent loop to also cover the shared domain channel:

```bash
  for agent in claude codex; do
```

becomes:

```bash
  for agent in claude codex domain; do
```

(No other change inside that loop — `ref_for`/`tip_for_ref` are already generic on the identity string.)

3e. Immediately before the `main()` function definition, add two new command functions:

```bash
command_domain_set() {
  [ "$#" -eq 0 ] || die "domain-set accepts only --target"
  ensure_store
  local oid toplevel mirror temporary
  BODY_FILE=$(mktemp "${TMPDIR:-/tmp}/agent-context-body.XXXXXX")
  cat > "$BODY_FILE"
  if [ -z "$(tr -d '[:space:]' < "$BODY_FILE")" ]; then
    rm -f "$BODY_FILE"
    die "domain-set requires a non-empty body on stdin"
  fi
  oid=$(append_event domain domain "domain-analysis-$$" "" "" "")
  toplevel=$(git_toplevel)
  mirror="$toplevel/.agent-context/DOMAIN.md"
  mkdir -p "$(dirname "$mirror")"
  temporary=$(mktemp "${TMPDIR:-/tmp}/agent-context-domain.XXXXXX")
  cp "$BODY_FILE" "$temporary"
  mv "$temporary" "$mirror"
  rm -f "$BODY_FILE"
  printf '%s\n' "$oid"
}

command_domain_show() {
  [ "$#" -eq 0 ] || die "domain-show accepts only --target"
  ensure_store
  local ref tip
  ref=$(ref_for domain)
  tip=$(tip_for_ref "$ref")
  if [ -z "$tip" ]; then
    printf 'No domain analysis yet for this repo.\n'
    return
  fi
  print_event_body "$tip"
}
```

3f. In `main()`'s case statement, replace:

```bash
  case "$command" in
    init) command_init "$@" ;; append) command_append "$@" ;; checkpoint) command_checkpoint "$@" ;;
    resume) command_resume "$@" ;; log) command_log "$@" ;; status) command_status "$@" ;;
    -h|--help|help) usage ;; *) die "unknown command: $command" ;;
  esac
```

with:

```bash
  case "$command" in
    init) command_init "$@" ;; append) command_append "$@" ;; checkpoint) command_checkpoint "$@" ;;
    resume) command_resume "$@" ;; log) command_log "$@" ;; status) command_status "$@" ;;
    domain-set) command_domain_set "$@" ;; domain-show) command_domain_show "$@" ;;
    -h|--help|help) usage ;; *) die "unknown command: $command" ;;
  esac
```

- [ ] **Step 4: Run the smoke test to verify it passes**

Run: `bash nimbalyst-local/agent-context/smoke-test.sh`
Expected: PASS — final line `agent-context smoke test passed`, no errors.

Also re-run the existing onboarding smoke test to confirm no regression:

Run: `bash nimbalyst-local/agent-context/onboarding-smoke-test.sh`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nimbalyst-local/agent-context/agent-context.sh nimbalyst-local/agent-context/smoke-test.sh
git commit -m "feat: add domain-set/domain-show channel to agent-context CLI"
```

---

### Task 2: Domain-analysis step in the setup skill

**Files:**
- Modify: `nimbalyst-local/agent-context/SKILL.md`

**Interfaces:**
- Consumes: `domain-set`/`domain-show` from Task 1 (must be complete first — this task's manual verification in Task 4 depends on it).

- [ ] **Step 1: Replace `SKILL.md` in full**

Replace the entire contents of `nimbalyst-local/agent-context/SKILL.md` with:

```markdown
---
name: agent-context-setup
description: Enable agent-context in the current Git repository. Use when the user explicitly asks to set up shared agent context, or after the onboarding hook says it is not set up.
---

# Agent context setup

Run this skill's adjacent installer against the current repository root:

```bash
"$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/install.sh" "$(git rev-parse --show-toplevel)"
```

The installer vendors the runtime into `.agent-context/`, initializes the separate bare context store, and merges the Claude Code and Codex lifecycle-hook configuration. Report its created or modified paths.

## Domain analysis

After the installer succeeds, check whether a domain summary already exists:

```bash
.agent-context/agent-context.sh domain-show --target "$(git rev-parse --show-toplevel)"
```

If it prints anything other than `No domain analysis yet for this repo.`, a domain summary already exists — skip analysis and tell the user it's already set (mention they can ask you to redo it if the repo has changed significantly).

Otherwise, analyze the repository yourself, with a **bounded** read:

- `README*` at the repository root.
- Top-level manifest files that exist (e.g. `package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `pom.xml`).
- The directory structure two levels deep at most.
- Do **not** recursively read the whole tree — this is a quick orientation summary, not a full audit.

Write a summary in exactly this format, one confidence label per section from `high | medium | low | insufficient evidence`. Never state a business fact (company name, target users, business model) that isn't actually written in the files you read — if the evidence is thin, say `insufficient evidence` instead of guessing:

```
## Business domain
<what this repository is for, based only on what you read>
confidence: <high|medium|low|insufficient evidence>

## Technical stack
<languages/frameworks/architecture style you actually detected>
confidence: <high|medium|low|insufficient evidence>
```

Save it:

```bash
printf '%s\n' "$SUMMARY" | .agent-context/agent-context.sh domain-set --target "$(git rev-parse --show-toplevel)"
```

If any step in this Domain analysis section fails, do not treat the overall setup as failed — the installer already succeeded independently. Report that domain analysis failed and that `domain-set` can be retried manually later.
```

- [ ] **Step 2: Commit**

```bash
git add nimbalyst-local/agent-context/SKILL.md
git commit -m "docs: add domain-analysis step to agent-context-setup skill"
```

---

### Task 3: README documentation

**Files:**
- Modify: `nimbalyst-local/agent-context/README.md`

- [ ] **Step 1: Update the CLI example block and the agents/types sentence**

Replace:

```markdown
# Debug the agent's first-parent history and inspect both persistent tips.
"$CLI" log codex --target "$REPO"
"$CLI" status --target "$REPO"
```

The only allowed agents are `claude` and `codex`; event types are `plan`, `decision`, `summary`, and `checkpoint`. Appends use an expected-old-value `git update-ref` compare-and-swap. On a race, the script rereads the tip and rebuilds the commit with that new parent before retrying, so the ref only advances fast-forward.
```

with:

```markdown
# Debug the agent's first-parent history and inspect all persistent tips.
"$CLI" log codex --target "$REPO"
"$CLI" status --target "$REPO"

# Record (or refresh) the shared domain summary. Body comes from stdin.
printf '%s\n' '## Business domain
...
confidence: high

## Technical stack
...
confidence: high' | "$CLI" domain-set --target "$REPO"

# Read it back later, from any session.
"$CLI" domain-show --target "$REPO"
```

The only allowed per-session agents are `claude` and `codex`; event types are `plan`, `decision`, `summary`, and `checkpoint`. `domain` is a third, shared, non-per-agent type recorded on its own persistent ref (`refs/heads/agent-context/domain`) via `domain-set`/`domain-show`; it is not exposed through the generic `append` command. Appends (including `domain-set`) use an expected-old-value `git update-ref` compare-and-swap. On a race, the script rereads the tip and rebuilds the commit with that new parent before retrying, so the ref only advances fast-forward.
```

- [ ] **Step 2: Add a Domain analysis section**

Insert this new section right after the existing `## Workspace onboarding` section's last paragraph (after the `bash nimbalyst-local/agent-context/onboarding-smoke-test.sh` code block, i.e. at the end of the file):

```markdown

## Domain analysis

`domain-set` and `domain-show` share one persistent ref (`refs/heads/agent-context/domain`), separate from the per-agent `claude`/`codex` refs. It is meant to answer "what does this repository do, and with what stack" once per repo, not per session.

- `domain-set --target <repo>` rejects an empty or whitespace-only stdin body without creating a commit.
- On success, it also writes `<repo-toplevel>/.agent-context/DOMAIN.md` as a plain-text mirror of the latest body — the Git commit is the source of truth, the file is a convenience cache. The write is atomic (temp file + `mv`) and replaces a pre-existing file or symlink at that path rather than writing through it.
- `domain-show --target <repo>` prints `No domain analysis yet for this repo.` (exit 0) when the ref has no commits yet, instead of surfacing a raw Git error.
- The `agent-context-setup` skill runs this automatically after installation, skipping it if a domain summary already exists. It is not injected into the `SessionStart` hook output — call `domain-show` explicitly when you need it.
```

- [ ] **Step 3: Commit**

```bash
git add nimbalyst-local/agent-context/README.md
git commit -m "docs: document the domain-set/domain-show channel"
```

---

### Task 4: Real end-to-end verification

**Files:** none (verification only, no source changes)

This task exercises the actual analysis flow described in Task 2's `SKILL.md`, against a fixture repository whose content is fixed here so the expected output is deterministic (no ambiguity about what the "analysis" should conclude).

- [ ] **Step 1: Build the fixture repository**

```bash
FIXTURE=$(mktemp -d "${TMPDIR:-/tmp}/agent-context-domain-fixture.XXXXXX")
git init -q "$FIXTURE"
git -C "$FIXTURE" config user.name "Fixture"
git -C "$FIXTURE" config user.email "fixture@example.invalid"
cat > "$FIXTURE/README.md" <<'EOF'
# Widget Tracker

Widget Tracker is a small internal tool for the warehouse team to record
where each widget batch physically sits on the shelves.
EOF
cat > "$FIXTURE/package.json" <<'EOF'
{
  "name": "widget-tracker",
  "dependencies": {
    "express": "^4.19.0"
  }
}
EOF
git -C "$FIXTURE" add README.md package.json
git -C "$FIXTURE" commit -qm seed
```

- [ ] **Step 2: Run the installer against the fixture**

```bash
PACKAGE=/Users/deratio/skills/nimbalyst-local/agent-context
"$PACKAGE/install.sh" "$FIXTURE"
```

Expected output: four `created or updated:` lines (`.agent-context`, `.claude/settings.json`, `.codex/hooks.json`, `.codex/config.toml`).

- [ ] **Step 3: Confirm no domain summary exists yet**

```bash
"$FIXTURE/.agent-context/agent-context.sh" domain-show --target "$FIXTURE"
```

Expected: `No domain analysis yet for this repo.`

- [ ] **Step 4: Perform the bounded analysis exactly as `SKILL.md` instructs, and save it**

Read `$FIXTURE/README.md` and `$FIXTURE/package.json` (both already known from Step 1). Based on that fixed content, this is the expected summary:

```bash
SUMMARY='## Business domain
Internal tool for a warehouse team to track the physical shelf location of widget batches.
confidence: high

## Technical stack
Node.js service using the Express framework (from package.json dependencies).
confidence: high'

printf '%s\n' "$SUMMARY" | "$FIXTURE/.agent-context/agent-context.sh" domain-set --target "$FIXTURE"
```

- [ ] **Step 5: Verify retrieval and isolation**

```bash
"$FIXTURE/.agent-context/agent-context.sh" domain-show --target "$FIXTURE" | grep -F 'warehouse team' >/dev/null && echo "domain-show OK"
diff <(printf '%s\n' "$SUMMARY") "$FIXTURE/.agent-context/DOMAIN.md" >/dev/null && echo "mirror file OK"
"$FIXTURE/.agent-context/agent-context.sh" status --target "$FIXTURE"
git -C "$FIXTURE" log --oneline --all
git -C "$FIXTURE" branch -a
```

Expected: `domain-show OK`, `mirror file OK`, `status` lists non-`(unborn)` `claude`/`codex`/`domain` tips as appropriate (claude/codex remain `(unborn)` since this fixture never appended session events — only `domain` has a tip), and the fixture's own `git log`/`git branch` show only the human `seed` commit and `master` — no `agent-context` refs or commits leaked into the development repository's own namespace.

- [ ] **Step 6: Clean up**

```bash
rm -rf "$FIXTURE"
```

No commit for this task — it is a verification pass over a throwaway fixture, not a source change.
