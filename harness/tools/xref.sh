#!/bin/bash
# xref.sh — §参照解決・識別子の実在確認の補助ツール
# Usage: xref.sh {verify|reverse <file.md> <section>}
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
sprint_config_require
ROOT=$(sprint_root)

# 生きている文書。定義は sprint.config.json の docs.livingDirs（spec-graph.py・clause-anchors.py と共有）。sprintRoot は入らない
mapfile -t LIVING_DIRS < <(sprint_config '.docs.livingDirs[]' | sed "s|^|$ROOT/|")

_find_file() {
  local base="$1"
  for d in "${LIVING_DIRS[@]}"; do
    [ -d "$d" ] || continue
    local found
    found=$(find "$d" -name "$base" -o -name "*_$base" 2>/dev/null | head -1)
    [ -n "$found" ] && echo "$found" && return 0
    found=$(find "$d" -name "*_${base%.md}.md" 2>/dev/null | head -1)
    [ -n "$found" ] && echo "$found" && return 0
  done
  return 1
}

_resolve() {
  local file="$1" sec="$2"
  grep -qE "<a id=\"$sec\">" "$file" && return 0
  grep -qE "^#+ *§?$sec[. ]" "$file" && return 0
  grep -qE "^#+ *${sec}[^0-9]" "$file" && return 0
  grep -qE "^#+ .*\b${sec}\b" "$file" && return 0
  return 1
}

cmd_verify() {
  local fail=0 checked=0
  for d in "${LIVING_DIRS[@]}"; do
    [ -d "$d" ] || continue
    while IFS= read -r src; do
      while IFS=: read -r line content; do
        while IFS= read -r pair; do
          local target sec tgt_file
          target=$(echo "$pair" | grep -oE '[A-Za-z][A-Za-z0-9_-]*\.md')
          sec=$(echo "$pair" | grep -oE '§[0-9]+(\.[0-9]+)*' | sed 's/§//')
          [ -z "$target" ] || [ -z "$sec" ] && continue
          # Skip generic refs (template names that exist in many dirs)
          case "$target" in README.md|SPEC.md|TEST.md) continue ;; esac
          tgt_file=$(_find_file "$target" 2>/dev/null) || { echo "MISS  $target §$sec  (file not found)  $src:$line"; fail=1; continue; }
          checked=$((checked+1))
          _resolve "$tgt_file" "$sec" || { echo "MISS  $target §$sec  (section not found)  $src:$line"; fail=1; }
        done < <(echo "$content" | grep -oE '[A-Za-z][A-Za-z0-9_-]*\.md *§[0-9]+(\.[0-9]+)*')
      done < <(grep -nE '[A-Za-z][A-Za-z0-9_-]*\.md *§[0-9]' "$src" 2>/dev/null || true)
    done < <(find "$d" -name "*.md" 2>/dev/null)
  done
  if [ "$fail" -ne 0 ]; then
    echo "--- VERIFY FAILED ---"
    exit 1
  fi
  echo "verify: OK ($checked refs checked)"
}


cmd_reverse() {
  local target="$1" sec="$2"
  [ -z "$target" ] || [ -z "$sec" ] && { echo "usage: xref.sh reverse <file.md> <section>"; exit 2; }
  for d in "${LIVING_DIRS[@]}"; do
    [ -d "$d" ] || continue
    grep -rnE "${target}[[:space:]]*§${sec}([^0-9]|$)" "$d" --include="*.md" 2>/dev/null || true
  done
}

case "${1:-}" in
  verify)  cmd_verify ;;
  reverse) cmd_reverse "${2:-}" "${3:-}" ;;
  --help|-h|"") echo "usage: xref.sh {verify|reverse <file.md> <section>}" ;;
  *) echo "unknown: $1"; exit 2 ;;
esac
