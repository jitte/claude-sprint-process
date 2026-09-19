#!/bin/bash
# harness/lib/env.sh — プロジェクトルートの解決（正本）。hooks / tools / gate-tools / bin はここだけを使う。
#
# 優先順:
#   1. CLAUDE_PROJECT_DIR  hook には Claude Code が渡す。fixture テストもこの変数で一時ディレクトリを指す
#   2. cwd から上へ辿って最初に sprint.config.json を持つディレクトリ（1 つの git リポジトリに複数のプロジェクトがある形）
#   3. git rev-parse       main の Bash では CLAUDE_PROJECT_DIR が無い
#   4. pwd
#
# 読み込み方（自分の位置から相対で辿る。シンボリックリンク越しでも本体の位置に解決する）:
#   harness/bin/*          . "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
#   harness/tools/*.sh     . "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
#   harness/gate-tools/*.sh . "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
#   harness/hooks/*.sh     . "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
# 本ファイルは同じディレクトリの config.sh を読む。呼び出し側は env.sh だけを読めばよい。

sprint_root() {
  if [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then
    printf '%s\n' "$CLAUDE_PROJECT_DIR"
    return 0
  fi
  local d
  d=$(pwd)
  while [ "$d" != "/" ]; do
    if [ -f "$d/sprint.config.json" ]; then printf '%s\n' "$d"; return 0; fi
    d=$(dirname "$d")
  done
  git rev-parse --show-toplevel 2>/dev/null || pwd
}

. "$(dirname "${BASH_SOURCE[0]}")/config.sh"

# ── タイムゾーン ──
# 記録（tools.jsonl・stage-transitions.jsonl・stage-tokens.jsonl・test-fails.json・flags.json の
# updated_at）の時刻はすべてこのゾーンで書く。既定は設定の project.timezone。環境変数 SPRINT_TZ が優先する。
# 設定が無いときはシステムの既定ゾーンで書く。
_sprint_tz() {
  if [ -n "${SPRINT_TZ:-}" ]; then printf '%s\n' "$SPRINT_TZ"; return 0; fi
  if sprint_config_exists; then sprint_config '.project.timezone // empty'; fi
}
sprint_date() { # <date のフォーマット引数...>
  local tz
  tz=$(_sprint_tz)
  if [ -n "$tz" ]; then TZ="$tz" date "$@"; else date "$@"; fi
}

# ── ゲート経由の起動 ──
# gate-check.sh はループ前に SPRINT_GATE=1 を export する。ツールは sprint_via_gate で判別する
# （例: size-audit は手動なら 🟡 を失敗、ゲート経由なら通過にする）。
sprint_via_gate() {
  [ "${SPRINT_GATE:-}" = "1" ]
}
