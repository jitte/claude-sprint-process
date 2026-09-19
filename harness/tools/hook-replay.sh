#!/bin/bash
# hook-replay.sh — 記録済みのツール呼び出しを 2 版の hook に流し、判定差を数える。
#
# .sprint/logs/tools.jsonl の Pre レコード（Write / Edit / Agent）から hook の入力
# {tool_name, tool_input, agent_type, cwd} を組み立て、<base> の hook（git show で取り出す）と
# 作業ツリーの hook の両方に流す。permissionDecision と permissionDecisionReason を比べ、
# 差があるレコードを出す。hook の整理（振る舞いを変えない変更）の検証に使う。
#
# 使い方: hook-replay.sh <base-ref> [tools.jsonl]
# 出力:   再生件数・判定差の件数（差があれば 1 件 1 行）。判定差 0 なら exit 0
# 環境変数:
#   HOOK_REPLAY_HOOKS   作業ツリー側の hook のディレクトリ（省略時 harness/hooks）。base 側は base に harness/hooks が
#                       あればそれを、無ければ旧配置（.claude/hooks）を取り出す
#
# 前提: 2 版とも同じ CLAUDE_PROJECT_DIR（作業ツリーのルート）で走らせる。ステージや封印の
# 状態は今のものを両方が読むので、記録時の判定と一致することは保証しない。比べるのは 2 版の間だけ。
set -uo pipefail
. "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
ROOT=$(sprint_root)
WORK_HOOKS="$ROOT/${HOOK_REPLAY_HOOKS:-harness/hooks}"
BASE="${1:-}"; LOG="${2:-$ROOT/.sprint/logs/tools.jsonl}"
[ -n "$BASE" ] || { echo "usage: hook-replay.sh <base-ref> [tools.jsonl]" >&2; exit 2; }
[ -f "$LOG" ] || { echo "not found: $LOG" >&2; exit 2; }

OLD=$(mktemp -d); trap 'rm -rf "$OLD"' EXIT
# base 側の hook の置き場。base に harness/hooks があればそれを、無ければ旧配置（.claude/hooks + scripts/lib）を取り出す
if git -C "$ROOT" cat-file -e "$BASE:harness/hooks/edit-scope-gate.sh" 2>/dev/null; then
  BASE_HOOKS="harness/hooks"
  mkdir -p "$OLD/harness/hooks" "$OLD/harness/lib"
  for f in agent-gate.sh edit-scope-gate.sh scope-lib.sh; do
    git -C "$ROOT" show "$BASE:harness/hooks/$f" > "$OLD/harness/hooks/$f" 2>/dev/null || : > "$OLD/harness/hooks/$f"
  done
  for f in env.sh config.sh evidence.sh; do
    git -C "$ROOT" show "$BASE:harness/lib/$f" > "$OLD/harness/lib/$f" 2>/dev/null || true
  done
  # 隣の tools/spec-seal.sh（UNSEAL 判定）は base 側のものを使う
  mkdir -p "$OLD/harness/tools"
  git -C "$ROOT" show "$BASE:harness/tools/spec-seal.sh" > "$OLD/harness/tools/spec-seal.sh" 2>/dev/null || true
  chmod +x "$OLD"/harness/hooks/*.sh
else
  BASE_HOOKS=".claude/hooks"
  mkdir -p "$OLD/.claude/hooks" "$OLD/scripts/lib"
  for f in agent-gate.sh edit-scope-gate.sh scope-lib.sh; do
    git -C "$ROOT" show "$BASE:.claude/hooks/$f" > "$OLD/.claude/hooks/$f" 2>/dev/null || : > "$OLD/.claude/hooks/$f"
  done
  # 旧版が lib（base に無いこともある）や scope-lib を固定パスで読む場合に備え、取り出した側を読ませる
  git -C "$ROOT" show "$BASE:scripts/lib/env.sh" > "$OLD/scripts/lib/env.sh" 2>/dev/null || true
  # 旧版（固定パスの既定値で scope-lib.sh を読む形）は、既定値がどこであっても取り出した側を読ませる
  sed -i -E "s|\"\\$\{CLAUDE_PROJECT_DIR:-[^}]*\}/.claude/hooks/scope-lib.sh\"|\"$OLD/.claude/hooks/scope-lib.sh\"|" "$OLD/.claude/hooks/edit-scope-gate.sh"
  chmod +x "$OLD"/.claude/hooks/*.sh
fi

export CLAUDE_PROJECT_DIR="$ROOT"
run_hook() { # <hook-path> <json>
  printf '%s' "$2" | bash "$1" 2>/dev/null | jq -c '[.hookSpecificOutput.permissionDecision // "allow", .hookSpecificOutput.permissionDecisionReason // ""]' 2>/dev/null || echo '["error",""]'
}

n=0; diff=0
while IFS= read -r rec; do
  n=$((n + 1))
  input=$(jq -c --arg cwd "$ROOT" '{tool_name: .tool, tool_input: .input, cwd: $cwd} + (if .actor != "main" then {agent_type: .actor} else {} end)' <<<"$rec")
  case "$(jq -r .tool <<<"$rec")" in
    Agent) h=agent-gate.sh ;;
    *)     h=edit-scope-gate.sh ;;
  esac
  a=$(run_hook "$OLD/$BASE_HOOKS/$h" "$input")
  b=$(run_hook "$WORK_HOOKS/$h" "$input")
  if [ "$a" != "$b" ]; then
    diff=$((diff + 1))
    echo "DIFF #$n $(jq -r '.tool + " " + (.actor // "main") + " " + ((.input.file_path // .input.subagent_type) // "")' <<<"$rec")"
    echo "  base: $a"
    echo "  work: $b"
  fi
done < <(jq -c 'select(.evt=="Pre" and (.tool=="Edit" or .tool=="Write" or .tool=="Agent"))' "$LOG")

echo "replayed: $n  diff: $diff"
[ "$diff" -eq 0 ]
