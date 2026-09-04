#!/usr/bin/env bash
set -euo pipefail

usage() { printf 'usage: bootstrap.sh [base-directory]\n' >&2; exit 1; }
[ "$#" -le 1 ] || usage

PACKAGE_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
BASE_DIRECTORY=${1:-"${HOME:?HOME must be set}"}

for tool_directory in .claude .codex; do
  destination="$BASE_DIRECTORY/$tool_directory/skills/agent-context-setup"
  if [ -e "$destination" ] || [ -L "$destination" ]; then
    printf 'exists; skipped: %s\n' "$destination"
    continue
  fi
  mkdir -p "$(dirname "$destination")"
  ln -s "$PACKAGE_ROOT" "$destination"
  printf 'linked: %s -> %s\n' "$destination" "$PACKAGE_ROOT"
done
