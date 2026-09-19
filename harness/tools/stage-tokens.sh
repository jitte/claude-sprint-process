#!/bin/bash
# stage-tokens.sh — stage 単位の token 消費を記録する。
#   sprint.sh の stage 遷移時（次 stage へ進めると判定した時点）に呼ばれる。
#   前回スナップショット（カーソル）以降に消費した token を transcript JSONL から
#   集計し .sprint/logs/stage-tokens.jsonl に 1 行追記する。
#
# 記録は「漏れなく後から再構成できる」よう自己完結にする:
#   - 正確な境界 since/until（UTC・カーソル値）
#   - main: message.usage の内訳（in/out/cache_w/cache_r・model 別）
#   - subagent: Agent の tool_use_id に紐づく tool_result から subagent_tokens を確実抽出
#     （トランスクリプト全文 scan は調査時の表示テキストまで拾うため、tool_use_id 相関で限定）
#   本ファイルは記録の完全性に責任を持つ。表示は用意しない（見方は都度変わる）。
#   出力は pino NDJSON なので `tail -F | pino-pretty` でそのまま読める。
#
# 不変条件: sprint.sh を絶対に止めない。いかなる失敗でも exit 0。
#   集計に成功したときだけカーソルを前進させる（失敗分は次回に持ち越し）。
#
# 使い方: stage-tokens.sh <sprint_id> <from_stage> <to_stage>
set -u
. "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
ROOT=$(sprint_root)
LOGDIR="$ROOT/.sprint/logs"
CURSOR="$LOGDIR/.stage-tokens-cursor"
OUT="$LOGDIR/stage-tokens.jsonl"
SPRINT="${1:-?}"; FROM="${2:-?}"; TO="${3:-?}"

mkdir -p "$LOGDIR" 2>/dev/null
TS_JST=$(sprint_date '+%Y-%m-%dT%H:%M:%S' 2>/dev/null)
NOW_UTC=$(date -u '+%Y-%m-%dT%H:%M:%S.000Z' 2>/dev/null)
MS=$(date +%s%3N 2>/dev/null)
case "$MS" in ''|*[!0-9]*) MS=$(( $(date +%s 2>/dev/null) * 1000 )) ;; esac

# transcript ディレクトリ = $HOME/.claude/projects/<ルートのスラッグ>（`/` と `.` を `-` に置換）
TDIR="$HOME/.claude/projects/$(printf '%s' "$ROOT" | sed 's#[/.]#-#g')"
[ -d "$TDIR" ] || exit 0

# 初回（カーソル無し）: 初期化のみ（以降の差分の起点）
if [ ! -f "$CURSOR" ]; then
  echo "$NOW_UTC" > "$CURSOR" 2>/dev/null
  jq -nc --argjson ms "$MS" --arg ts "$TS_JST" --arg until "$NOW_UTC" --arg sp "$SPRINT" --arg f "$FROM" --arg t "$TO" \
    '{level:30, time:$ms, name:"tokens", msg:"\($sp)  cursor-init",
      ts:$ts, since:null, until:$until, sprint:$sp, from:$f, to:$t, note:"cursor-init", total_tokens:0}' >> "$OUT" 2>/dev/null
  exit 0
fi

SINCE=$(cat "$CURSOR" 2>/dev/null)
# カーソル以降に更新された transcript のみ対象（mtime 基準で絞り込み）
FILES=$(find "$TDIR" -maxdepth 1 -name '*.jsonl' -newer "$CURSOR" 2>/dev/null)

TMP=$(mktemp 2>/dev/null) || exit 0
if [ -n "$FILES" ]; then
  # shellcheck disable=SC2086
  jq -sc --argjson ms "$MS" --arg since "$SINCE" --arg until "$NOW_UTC" --arg ts "$TS_JST" --arg sp "$SPRINT" --arg f "$FROM" --arg t "$TO" '
    def agg(arr): { msgs:(arr|length),
      in:     (arr|[.[].message.usage.input_tokens]|add // 0),
      out:    (arr|[.[].message.usage.output_tokens]|add // 0),
      cache_w:(arr|[.[].message.usage.cache_creation_input_tokens]|add // 0),
      cache_r:(arr|[.[].message.usage.cache_read_input_tokens]|add // 0) };
    ( [ .[] | select(.type=="assistant" and ((.timestamp // "") > $since) and (.message.usage != null)) ] ) as $m
    | ( [ .[] | select(.type=="assistant") | .message.content[]?
          | select(.type=="tool_use" and (.name=="Task" or .name=="Agent")) | .id ] ) as $aids
    | ( [ .[] | select(.type=="user" and ((.timestamp // "") > $since)) | .message.content[]?
          | select(.type=="tool_result" and ((.tool_use_id) as $id | ($aids | index($id)) != null)) ] ) as $res
    # subagent の消費は tool_result ではなく <task-notification> の本文に載る。
    # 非同期 Agent の tool_result は起動の応答だけで usage を持たない（D3）。
    # 表記は XML タグ <subagent_tokens>N</subagent_tokens> である（`: N` ではない）。
    # 対象は user メッセージの text ブロック（content が文字列の場合も拾う）。
    | ( [ .[] | select(.type=="user" and ((.timestamp // "") > $since)) | .message.content
          | if type=="string" then . else ([.[]? | select(.type=="text") | .text] | join("\n")) end
          | select(. != null) | scan("<subagent_tokens>([0-9]+)</subagent_tokens>") | .[0] | tonumber ] ) as $st
    | (agg($m)) as $ma
    | (($ma.in + $ma.out + $ma.cache_w + $ma.cache_r) + ($st|add // 0)) as $tot
    | {
        level: 30,
        time: $ms,
        name: "usage",
        msg: "\($sp)  \($f) → \($t)  total=\($tot)  main=\($ma.in + $ma.out)(+cache \($ma.cache_w + $ma.cache_r))  sub=\($st|add // 0)(\($st|length)件)",
        ts:$ts, since:$since, until:$until, sprint:$sp, from:$f, to:$t,
        main: ($ma + { by_model: ($m | group_by(.message.model) | map({ (.[0].message.model // "?"): agg(.) }) | add) }),
        subagent: { calls: ($res|length), results: ($st|length), tokens: ($st|add // 0) },
        total_tokens: $tot
      }
  ' $FILES > "$TMP" 2>/dev/null
else
  # 新規 transcript 更新なし → 0 消費（境界は記録）
  jq -nc --argjson ms "$MS" --arg since "$SINCE" --arg until "$NOW_UTC" --arg ts "$TS_JST" --arg sp "$SPRINT" --arg f "$FROM" --arg t "$TO" \
    '{level:30, time:$ms, name:"tokens", msg:"\($sp)  \($f) → \($t)  total=0",
      ts:$ts, since:$since, until:$until, sprint:$sp, from:$f, to:$t,
      main:{msgs:0,in:0,out:0,cache_w:0,cache_r:0}, subagent:{calls:0,results:0,tokens:0}, total_tokens:0}' > "$TMP" 2>/dev/null
fi

if [ -s "$TMP" ]; then
  cat "$TMP" >> "$OUT" 2>/dev/null
  echo "$NOW_UTC" > "$CURSOR" 2>/dev/null   # 成功時のみカーソル前進
fi
rm -f "$TMP" 2>/dev/null
exit 0
