#!/bin/bash
# PreToolUse / PostToolUse ロギングフック。
# 全ツール呼び出しを .sprint/logs/tools.jsonl に1行ずつ追記する（tail -F で垂れ流す用途）。
#
# 不変条件: ツールを絶対にブロックしない。常に {"continue":true} を返し exit 0。
#   jq 失敗・ディレクトリ不在など、いかなるエラーでもツール実行を妨げない。
#
# 出力形式は pino NDJSON にする（`tail -F * | pino-pretty` で読むため）。
#   level: 30 固定 / time: epoch ms / name: actor / msg: 人が読む 1 行
#   ts は JST ISO を併記（生ログを目で追うとき用）
# 記録項目: evt(Pre|Post) / actor / tool / id(tool_use_id)
#           Pre: input(tool_input そのまま)
#           Post: dur_ms / out_len(tool_response の全長)
#
# tool_response の本体を記録しない理由: 全文は ~/.claude の transcript の
# toolUseResult と同一で、そちらが正本として残る（実測で確認）。tools.jsonl は
# 「リアルタイムに 1 本の流れで追う」ための view であり、正本の複製ではない。
# 出力を読みたいときは transcript を引く。長さだけ out_len で残す。
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
  ((.hook_event_name // "") | sub("ToolUse"; "")) as $evt |
  (.agent_type // "main") as $actor |
  (.tool_name // "?") as $tool |
  ((.tool_input // {}) | tostring | gsub("[\n\r]"; " ") | .[0:160]) as $head |
  {
    level: 30,
    time: $ms,
    name: $actor,
    msg: (if $evt == "Pre" then "▶ \($tool)  \($head)"
          else "✓ \($tool)  \(.duration_ms // 0)ms" end),
    ts: $ts,
    evt: $evt,
    actor: $actor,
    tool: $tool,
    id: (.tool_use_id // ""),
    dur_ms: (.duration_ms // null)
  }
  + (if $evt == "Pre"  then {input: (.tool_input // {})} else {} end)
  + (if $evt == "Post" then {out_len: ((.tool_response // "") | tostring | length)} else {} end)
' >> "$LOGDIR/tools.jsonl" 2>/dev/null

echo '{"continue":true}'
exit 0
