#!/usr/bin/env bash
set -euo pipefail

LC_ALL=C
export LC_ALL

die() { printf 'slugify: %s\n' "$*" >&2; exit 1; }

slugify() {
  # ponytail: ASCII-only slug folding, byte-drops non-Latin input; add real Unicode transliteration (e.g. iconv -t ascii//TRANSLIT) if non-Latin input becomes a requirement
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9][^a-z0-9]*/-/g; s/^-*//; s/-*$//'
}

pass() { printf 'PASS: %s\n' "$1"; }
fail() { printf 'FAIL: %s\n' "$1"; exit 1; }

self_check() {
  local actual

  actual=$(printf 'Hello World' | "$0")
  [ "$actual" = 'hello-world' ] && pass 'normal text input' || fail 'normal text input'

  actual=$(printf ' \t\n' | "$0")
  [ "$actual" = '' ] && pass 'whitespace-only input' || fail 'whitespace-only input'

  actual=$(printf '  ...Hi There!!!  ' | "$0")
  [ "$actual" = 'hi-there' ] && pass 'leading and trailing punctuation' || fail 'leading and trailing punctuation'

  actual=$(printf 'one---two / three' | "$0")
  [ "$actual" = 'one-two-three' ] && pass 'consecutive separators' || fail 'consecutive separators'

  actual=$(printf '\377x' | "$0")
  case "$actual" in
    *[!a-z0-9-]*) fail 'non-ASCII byte input' ;;
    *) pass 'non-ASCII byte input' ;;
  esac

  actual=$(printf '' | "$0")
  [ "$actual" = '' ] && pass 'empty stdin' || fail 'empty stdin'

  actual=$("$0" 'Hello' 'Many' 'Words')
  [ "$actual" = 'hello-many-words' ] && pass 'multi-arg join' || fail 'multi-arg join'

  actual=$("$0" -- --self-check)
  [ "$actual" = 'self-check' ] && pass '-- literal self-check text' || fail '-- literal self-check text'
}

if [ "$#" -eq 1 ] && [ "$1" = '--self-check' ]; then
  self_check
  exit 0
fi

args=()
parsing_options=1
for arg in "$@"; do
  if [ "$parsing_options" -eq 1 ] && [ "$arg" = '--' ]; then
    parsing_options=0
    continue
  fi
  args+=("$arg")
done

if [ "${#args[@]}" -gt 0 ]; then
  input=$(IFS=' '; printf '%s' "${args[*]}")
else
  input=$(cat)
fi

printf '%s\n' "$(slugify "$input")"
