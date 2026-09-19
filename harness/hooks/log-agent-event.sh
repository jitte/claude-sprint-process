#!/bin/bash
# subagent のライフサイクルを tools.jsonl の同じ流れに混ぜる。
# 対象イベント: SubagentStart / SubagentStop / TaskCompleted
#
# 目的は「subagent とのやりとりを tail -F で追えること」。
# 送り（プロンプト）は Agent ツールの Pre レコードが input.prompt として持つ。
# 受け（最終報告）はここが AgentStop の msg として全文を記録する。
#
# 出力形式は pino NDJSON にする（`tail -F * | pino-pretty` で読むため）。
#   level: 30 / time: epoch ms / name: agent_type / msg: 人が読む本文
# AgentStop の msg にはエージェントの最終報告を**全文**入れる。切り詰めない。
# これを読むことが目的そのものであり、報告はツール出力ほど巨大にならない。
# 記録項目: evt(AgentStart|AgentStop) / actor(agent_type) / tool("Agent")
#           id(agent_id) / report(最終報告・全文) / tp(subagent transcript のパス)
#
# 不変条件: 何があってもブロックしない。常に {"continue":true} を返し exit 0。
. "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
sprint_config_exists || exit 0
ROOT=$(sprint_root)
LOGDIR="$ROOT/.sprint/logs"
INPUT=$(cat)

mkdir -p "$LOGDIR" 2>/dev/null
TS=$(sprint_date '+%Y-%m-%dT%H:%M:%S' 2>/dev/null)
MS=$(date +%s%3N 2>/dev/null)
case "$MS" in ''|*[!0-9]*) MS=$(( $(date +%s 2>/dev/null) * 1000 )) ;; esac

printf '%s' "$INPUT" | jq -c --arg ts "$TS" --argjson ms "$MS" '
  (.hook_event_name // "?") as $e |
  (if $e == "SubagentStart" then "AgentStart"
   elif $e == "SubagentStop" then "AgentStop"
   else $e end) as $evt |
  (.agent_type // "?") as $actor |
  ((.last_assistant_message // "") | tostring) as $report |
  {
    level: 30,
    time: $ms,
    name: $actor,
    msg: (if $evt == "AgentStart" then "⇢ 起動"
          elif $evt == "AgentStop" then "⇠ 完了\n\($report)"
          else $evt end),
    ts: $ts,
    evt: $evt,
    actor: $actor,
    tool: "Agent",
    id: (.agent_id // ""),
    tp: (.agent_transcript_path // null)
  }
  + (if $report != "" then {report: $report} else {} end)
' >> "$LOGDIR/tools.jsonl" 2>/dev/null

echo '{"continue":true}'
exit 0
