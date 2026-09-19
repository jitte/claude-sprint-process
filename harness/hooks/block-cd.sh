#!/bin/bash
# PreToolUse hook: Bash コマンド中の `cd <path>` を止める。
# CWD は常にプロジェクトルートである。タスクは bin/sprint run、参照は絶対パスで行う。
# sprint.config.json が無ければ判定せず素通りする（出力なし・exit 0）。
. "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
sprint_config_exists || exit 0
ROOT=$(sprint_root)

cmd=$(jq -r '.tool_input.command // ""')

# コマンド位置の cd で、引数がパスの形（英数字 . / ~ $ - 引用符）のものだけを止める。
# 「| cd コマンド」のような文書中の語（heredoc 内）は引数が日本語なので一致しない。
if grep -qE '(^|[;&|]\s*)cd[[:space:]]+["'"'"'./~$A-Za-z0-9_-]' <<<"$cmd"; then
  tasks=$(sprint_tasks | tr '\n' ' ')
  cat <<JSON
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"cd 禁止。CWD は常に $ROOT です。\n\nタスクはランナー経由で実行してください:\n  bash harness/bin/sprint run <task> [<component>]   task = ${tasks}\n  bash harness/bin/sprint run all\n\nファイル参照は絶対パス (例: $ROOT/...) を使ってください。"}}
JSON
  exit 0
fi

echo '{"continue":true}'
