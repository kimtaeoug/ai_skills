#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C # Byte/ASCII-oriented counting; wc character classes are locale-sensitive.

die() { printf 'word-count.sh: %s\n' "$*" >&2; exit 1; }

input_file=
cleanup_input() { [ -z "$input_file" ] || rm -f "$input_file"; }
trap cleanup_input EXIT

count() {
  local mode=$1 raw
  shift
  raw=$(wc "$mode" -- "$1")
  raw=${raw#"${raw%%[![:space:]]*}"}
  printf '%s\n' "${raw%%[[:space:]]*}"
}

run() {
  local file=${1-}

  if [ "$#" -eq 0 ]; then
    input_file=$(mktemp "${TMPDIR:-/tmp}/word-count-input.XXXXXX") || die 'cannot create temporary file'
    cat > "$input_file"
    file=$input_file
  elif [ ! -f "$file" ] || [ ! -r "$file" ]; then
    die "cannot read file: $file"
  fi

  printf 'words: %s\n' "$(count -w "$file")"
  # wc -l counts newline bytes, so a final unterminated line is not counted.
  printf 'lines: %s\n' "$(count -l "$file")"
}

pass() { printf 'PASS: %s\n' "$1"; }
fail() { printf 'FAIL: %s\n' "$1"; exit 1; }
self_check_tmp=
cleanup_self_check() { [ -z "$self_check_tmp" ] || rm -rf "$self_check_tmp"; }

self_check() {
  local normal empty unterminated output
  self_check_tmp=$(mktemp -d "${TMPDIR:-/tmp}/word-count.XXXXXX")
  trap cleanup_self_check EXIT
  normal="$self_check_tmp/normal.txt"
  empty="$self_check_tmp/empty.txt"
  unterminated="$self_check_tmp/unterminated.txt"

  printf 'one two\nthree four\n' > "$normal"
  : > "$empty"
  printf 'one two' > "$unterminated"

  if output=$("$0" "$normal") && [ "$output" = $'words: 4\nlines: 2' ]; then
    pass 'normal file'
  else
    fail 'normal file'
  fi

  if output=$("$0" "$empty") && [ "$output" = $'words: 0\nlines: 0' ]; then
    pass 'empty file'
  else
    fail 'empty file'
  fi

  if output=$("$0" "$unterminated") && [ "$output" = $'words: 2\nlines: 0' ]; then
    pass 'unterminated final line'
  else
    fail 'unterminated final line'
  fi

  if "$0" "$self_check_tmp/missing.txt" > /dev/null 2> "$self_check_tmp/missing.err"; then
    fail 'missing file rejected'
  elif grep -Fqx "word-count.sh: cannot read file: $self_check_tmp/missing.txt" "$self_check_tmp/missing.err"; then
    pass 'missing file rejected'
  else
    fail 'missing file rejected'
  fi

  if output=$(printf 'one two\n' | "$0") && [ "$output" = $'words: 2\nlines: 1' ]; then
    pass 'stdin input'
  else
    fail 'stdin input'
  fi

  if "$0" "$normal" "$empty" > /dev/null 2> "$self_check_tmp/multi.err"; then
    fail 'multiple files rejected'
  elif grep -Fqx 'word-count.sh: usage: word-count.sh [--] [FILE]' "$self_check_tmp/multi.err"; then
    pass 'multiple files rejected'
  else
    fail 'multiple files rejected'
  fi
}

if [ "$#" -eq 1 ] && [ "$1" = '--self-check' ]; then
  self_check
  exit 0
fi

files=()
end_options=false
for arg in "$@"; do
  if ! "$end_options" && [ "$arg" = '--' ]; then
    end_options=true
  else
    files+=("$arg")
  fi
done

[ "${#files[@]}" -le 1 ] || die 'usage: word-count.sh [--] [FILE]'
if [ "${#files[@]}" -eq 0 ]; then
  run
else
  run "${files[0]}"
fi
