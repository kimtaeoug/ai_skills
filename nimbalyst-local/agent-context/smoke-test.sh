#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
CLI="$ROOT_DIR/agent-context.sh"
SCRATCH=$(mktemp -d "${TMPDIR:-/tmp}/agent-context-smoke.XXXXXX")
TARGET="$SCRATCH/dev-repo"

cleanup() {
  rm -rf "$SCRATCH"
}
trap cleanup EXIT

git init -q "$TARGET"
git -C "$TARGET" config user.name "Smoke Test"
git -C "$TARGET" config user.email "smoke@example.invalid"
printf 'seed\n' > "$TARGET/README"
git -C "$TARGET" add README
git -C "$TARGET" commit -qm seed

if "$CLI" status --target "$TARGET" >/dev/null 2>&1; then
  printf 'status must not create a missing store\n' >&2
  exit 1
fi
test ! -e "$TARGET/.git/agent-context.git"

"$CLI" init --target "$TARGET"
STORE="$TARGET/.git/agent-context.git"
test -d "$STORE"
test "$(git --git-dir="$STORE" rev-parse --is-bare-repository)" = true

PLAN_OID=$(printf 'Build the shared context CLI.\n' | "$CLI" append claude plan --session smoke-1 --target "$TARGET")
DECISION_OID=$(printf 'Use a separate bare repository.\n' | "$CLI" append claude decision --responds-to "$PLAN_OID" --target "$TARGET")
ROOT_RESUME_OUTPUT=$("$CLI" resume claude --target "$TARGET")
echo "$ROOT_RESUME_OUTPUT" | grep -F 'NO CHECKPOINT' >/dev/null
echo "$ROOT_RESUME_OUTPUT" | grep -F 'Build the shared context CLI.' >/dev/null
CHECKPOINT_OID=$(printf 'goal: smoke test\nconfirmed decisions/invariants: separate bare repo\ncompleted work: two events\nactive plan: verify resume\nnext action: append summary\nopen questions: none\n' | "$CLI" checkpoint claude --target "$TARGET")
SUMMARY_OID=$(printf 'Smoke-test context is ready.\n' | "$CLI" append claude summary --seen "$PLAN_OID,$DECISION_OID" --target "$TARGET")

test "$(git --git-dir="$STORE" rev-parse refs/heads/agent-context/claude)" = "$SUMMARY_OID"
test "$(git --git-dir="$STORE" rev-parse "$SUMMARY_OID^")" = "$CHECKPOINT_OID"
test "$(git --git-dir="$STORE" rev-parse "$CHECKPOINT_OID^")" = "$DECISION_OID"
git --git-dir="$STORE" show "$CHECKPOINT_OID:event.md" | grep -F "covers_through: $DECISION_OID" >/dev/null
git -C "$TARGET" show-ref | grep -F 'agent-context/' && exit 1 || true

RESUME_OUTPUT=$("$CLI" resume claude --target "$TARGET")
echo "$RESUME_OUTPUT" | grep -F 'CHECKPOINT' >/dev/null
echo "$RESUME_OUTPUT" | grep -F 'goal: smoke test' >/dev/null
echo "$RESUME_OUTPUT" | grep -F 'Smoke-test context is ready.' >/dev/null
"$CLI" status --target "$TARGET" | grep -F "claude: $SUMMARY_OID" >/dev/null
"$CLI" log claude --target "$TARGET" | grep -F "$SUMMARY_OID" >/dev/null

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

printf 'agent-context smoke test passed\n'
