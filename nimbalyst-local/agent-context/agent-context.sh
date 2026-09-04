#!/usr/bin/env bash
set -euo pipefail

ZERO_OID=0000000000000000000000000000000000000000
TARGET=$PWD
STORE=

die() { printf 'agent-context: %s\n' "$*" >&2; exit 1; }

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

require_value() { [ "$#" -ge 2 ] || die "$1 requires a value"; }

parse_target() {
  local remaining=()
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --target) require_value "$@"; TARGET=$2; shift 2 ;;
      --target=*) TARGET=${1#--target=}; shift ;;
      *) remaining+=("$1"); shift ;;
    esac
  done
  PARSED_ARGS=()
  [ "${#remaining[@]}" -eq 0 ] || PARSED_ARGS=("${remaining[@]}")
}

resolve_store() {
  local common
  TARGET=$(cd "$TARGET" 2>/dev/null && pwd -P) || die "cannot access target repository: $TARGET"
  common=$(git -C "$TARGET" rev-parse --git-common-dir 2>/dev/null) || die "target is not a Git repository: $TARGET"
  common=$(cd "$TARGET" && cd "$common" 2>/dev/null && pwd -P) || die "cannot resolve Git common directory"
  STORE="$common/agent-context.git"
}

git_toplevel() {
  git -C "$TARGET" rev-parse --show-toplevel 2>/dev/null || die "cannot resolve working tree root for: $TARGET"
}

ensure_store() {
  resolve_store
  [ -e "$STORE" ] || git init --bare -q "$STORE"
  [ -d "$STORE" ] || die "context store is not a directory: $STORE"
  [ "$(git --git-dir="$STORE" rev-parse --is-bare-repository 2>/dev/null)" = true ] || die "context store is not a bare Git repository: $STORE"
}

validate_agent() {
  case "$1" in claude|codex) ;; *) die "agent must be claude or codex" ;; esac
}

validate_type() {
  case "$1" in plan|decision|summary|checkpoint|domain) ;; *) die "type must be plan, decision, summary, checkpoint, or domain" ;; esac
}

validate_single_line() {
  case "$2" in *$'\n'*|*$'\r'*) die "$1 must be a single line" ;; esac
}

ref_for() { printf 'refs/heads/agent-context/%s\n' "$1"; }

tip_for_ref() { git --git-dir="$STORE" rev-parse --verify --quiet "$1^{commit}" 2>/dev/null || true; }

parent_of() { git --git-dir="$STORE" rev-parse --verify --quiet "$1^" 2>/dev/null || true; }

event_type() { git --git-dir="$STORE" show "$1:event.md" | sed -n 's/^type: //p' | sed -n '1p'; }

print_event_body() {
  git --git-dir="$STORE" show "$1:event.md" | awk 'body { print; next } $0 == "---" { body = 1 }'
}

write_event() {
  local event_file=$1 type=$2 agent=$3 session=$4 parent=$5 seen=$6 supersedes=$7 responds_to=$8
  {
    printf 'type: %s\n' "$type"
    printf 'author: %s\n' "$agent"
    printf 'session: %s\n' "$session"
    printf 'timestamp: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    [ -z "$seen" ] || printf 'seen: %s\n' "$seen"
    [ -z "$supersedes" ] || printf 'supersedes: %s\n' "$supersedes"
    [ -z "$responds_to" ] || printf 'responds-to: %s\n' "$responds_to"
    [ "$type" != checkpoint ] || printf 'covers_through: %s\n' "$parent"
    printf '%s\n' '---'
    cat "$BODY_FILE"
  } > "$event_file"
}

build_commit() {
  local type=$1 agent=$2 session=$3 parent=$4 seen=$5 supersedes=$6 responds_to=$7
  local event_file blob tree commit
  event_file=$(mktemp "${TMPDIR:-/tmp}/agent-context-event.XXXXXX")
  write_event "$event_file" "$type" "$agent" "$session" "$parent" "$seen" "$supersedes" "$responds_to"
  blob=$(git --git-dir="$STORE" hash-object -w "$event_file")
  tree=$(printf '100644 blob %s\tevent.md\n' "$blob" | git --git-dir="$STORE" mktree)
  if [ -n "$parent" ]; then
    commit=$(GIT_AUTHOR_NAME="agent-context-$agent" GIT_AUTHOR_EMAIL="$agent@agent-context.invalid" GIT_COMMITTER_NAME="agent-context-$agent" GIT_COMMITTER_EMAIL="$agent@agent-context.invalid" git --git-dir="$STORE" commit-tree "$tree" -p "$parent" -F "$event_file")
  else
    commit=$(GIT_AUTHOR_NAME="agent-context-$agent" GIT_AUTHOR_EMAIL="$agent@agent-context.invalid" GIT_COMMITTER_NAME="agent-context-$agent" GIT_COMMITTER_EMAIL="$agent@agent-context.invalid" git --git-dir="$STORE" commit-tree "$tree" -F "$event_file")
  fi
  rm -f "$event_file"
  printf '%s\n' "$commit"
}

append_event() {
  local agent=$1 type=$2 session=$3 seen=$4 supersedes=$5 responds_to=$6
  local ref parent expected new
  ref=$(ref_for "$agent")
  while :; do
    parent=$(tip_for_ref "$ref")
    expected=$parent
    [ -n "$expected" ] || expected=$ZERO_OID
    new=$(build_commit "$type" "$agent" "$session" "$parent" "$seen" "$supersedes" "$responds_to")
    if git --git-dir="$STORE" update-ref "$ref" "$new" "$expected"; then
      printf '%s\n' "$new"
      return
    fi
  done
}

events_since_checkpoint() {
  local agent=$1 ref current count=0
  ref=$(ref_for "$agent")
  current=$(tip_for_ref "$ref")
  while [ -n "$current" ]; do
    [ "$(event_type "$current")" = checkpoint ] && break
    count=$((count + 1))
    current=$(parent_of "$current")
  done
  printf '%s\n' "$count"
}

render_resume() {
  local agent=$1 ref current found=0 index i
  local chain=()
  ref=$(ref_for "$agent")
  current=$(tip_for_ref "$ref")
  [ -n "$current" ] || { printf 'No context events for %s.\n' "$agent"; return; }
  while [ -n "$current" ]; do
    chain+=("$current")
    if [ "$(event_type "$current")" = checkpoint ]; then found=1; break; fi
    current=$(parent_of "$current")
  done
  if [ "$found" -eq 1 ]; then
    index=$((${#chain[@]} - 1))
    printf '=== CHECKPOINT %s ===\n' "${chain[$index]}"
    print_event_body "${chain[$index]}"
    printf '\n'
    i=$((index - 1))
  else
    printf '=== NO CHECKPOINT: replaying from root ===\n'
    i=$((${#chain[@]} - 1))
  fi
  while [ "$i" -ge 0 ]; do
    printf '=== EVENT %s (%s) ===\n' "${chain[$i]}" "$(event_type "${chain[$i]}")"
    git --git-dir="$STORE" show "${chain[$i]}:event.md"
    printf '\n'
    i=$((i - 1))
  done
}

maybe_auto_checkpoint() {
  local agent=$1 session=$2 count tip auto_body auto_oid
  count=$(events_since_checkpoint "$agent")
  if [ "$count" -lt 20 ]; then
    return 0
  fi
  tip=$(tip_for_ref "$(ref_for "$agent")")
  auto_body=$(mktemp "${TMPDIR:-/tmp}/agent-context-checkpoint.XXXXXX")
  {
    printf 'goal: Preserve %s context through %s.\n' "$agent" "$tip"
    printf 'confirmed decisions/invariants: Captured in the source context below.\n'
    printf 'completed work: Captured in the source context below.\n'
    printf 'active plan: Captured in the source context below.\n'
    printf 'next action: Review the source context below before continuing.\n'
    printf 'open questions: Captured in the source context below.\n\n'
    printf 'Source context:\n'
    render_resume "$agent"
  } > "$auto_body"
  BODY_FILE=$auto_body
  auto_oid=$(append_event "$agent" checkpoint "$session" "" "" "")
  rm -f "$auto_body"
  printf 'agent-context: automatic checkpoint %s after %s events\n' "$auto_oid" "$count" >&2
}

command_init() {
  [ "$#" -eq 0 ] || die "init accepts only --target"
  ensure_store
  printf '%s\n' "$STORE"
}

command_append() {
  [ "$#" -ge 2 ] || die "append requires AGENT and TYPE"
  local agent=$1 type=$2 session="session-${HOSTNAME:-local}-$$" seen='' supersedes='' responds_to='' oid
  shift 2
  validate_agent "$agent"; validate_type "$type"
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --session|--supersedes|--responds-to|--seen)
        require_value "$@"
        case "$1" in
          --session) session=$2 ;; --supersedes) supersedes=$2 ;; --responds-to) responds_to=$2 ;; --seen) seen=$2 ;;
        esac
        shift 2 ;;
      *) die "unknown append option: $1" ;;
    esac
  done
  validate_single_line session "$session"; validate_single_line seen "$seen"
  validate_single_line supersedes "$supersedes"; validate_single_line responds-to "$responds_to"
  ensure_store
  BODY_FILE=$(mktemp "${TMPDIR:-/tmp}/agent-context-body.XXXXXX")
  cat > "$BODY_FILE"
  oid=$(append_event "$agent" "$type" "$session" "$seen" "$supersedes" "$responds_to")
  rm -f "$BODY_FILE"
  printf '%s\n' "$oid"
  if [ "$type" != checkpoint ]; then
    maybe_auto_checkpoint "$agent" "$session"
  fi
}

command_checkpoint() {
  [ "$#" -ge 1 ] || die "checkpoint requires AGENT"
  local agent=$1 session="session-${HOSTNAME:-local}-$$" oid
  shift
  validate_agent "$agent"
  while [ "$#" -gt 0 ]; do
    case "$1" in --session) require_value "$@"; session=$2; shift 2 ;; *) die "unknown checkpoint option: $1" ;; esac
  done
  validate_single_line session "$session"
  ensure_store
  BODY_FILE=$(mktemp "${TMPDIR:-/tmp}/agent-context-body.XXXXXX")
  cat > "$BODY_FILE"
  oid=$(append_event "$agent" checkpoint "$session" "" "" "")
  rm -f "$BODY_FILE"
  printf '%s\n' "$oid"
}

command_resume() {
  [ "$#" -eq 1 ] || die "resume requires AGENT"
  validate_agent "$1"; ensure_store; render_resume "$1"
}

command_log() {
  [ "$#" -eq 1 ] || die "log requires AGENT"
  local ref
  validate_agent "$1"; ensure_store; ref=$(ref_for "$1")
  if [ -n "$(tip_for_ref "$ref")" ]; then git --git-dir="$STORE" log --first-parent --format='%H %s' "$ref"; else printf '(no events)\n'; fi
}

command_status() {
  [ "$#" -eq 0 ] || die "status accepts only --target"
  local agent ref tip
  resolve_store
  [ -d "$STORE" ] || die "context store does not exist: $STORE"
  [ "$(git --git-dir="$STORE" rev-parse --is-bare-repository 2>/dev/null)" = true ] || die "context store is not a bare Git repository: $STORE"
  printf 'store: %s\n' "$STORE"
  for agent in claude codex domain; do
    ref=$(ref_for "$agent"); tip=$(tip_for_ref "$ref")
    printf '%s: %s\n' "$agent" "${tip:-(unborn)}"
  done
}

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

main() {
  [ "$#" -gt 0 ] || { usage >&2; exit 1; }
  local command=$1
  shift
  parse_target "$@"
  if [ "${#PARSED_ARGS[@]}" -gt 0 ]; then
    set -- "${PARSED_ARGS[@]}"
  else
    set --
  fi
  case "$command" in
    init) command_init "$@" ;; append) command_append "$@" ;; checkpoint) command_checkpoint "$@" ;;
    resume) command_resume "$@" ;; log) command_log "$@" ;; status) command_status "$@" ;;
    domain-set) command_domain_set "$@" ;; domain-show) command_domain_show "$@" ;;
    -h|--help|help) usage ;; *) die "unknown command: $command" ;;
  esac
}

main "$@"
