#!/bin/bash
# PostToolUse hook: Bash で `sprint run` を実行した直後に、証跡契約の JSON からテスト失敗数を
# .sprint/test-fails.json に記録する。`bin/sprint status` の表示に使う。
# gate-check の results（green）は読まない（証跡を直接見る）。
# sprint.config.json が無ければ判定せず素通りする（出力なし・exit 0）。
#
# 形式: { "total": n, "tasks": { "<component>.<task>": n, ... }, "recorded_at": "..." }
#   n は test / e2e なら counts.failed、lint / typecheck なら errors、build なら status が fail のとき 1
. "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
sprint_config_exists || exit 0
. "$(dirname "$(readlink -f "$0")")/../lib/evidence.sh"
ROOT=$(sprint_root)
FAILS_FILE="$ROOT/.sprint/test-fails.json"
INPUT=$(cat)

# Bash ツールの command を取得
COMMAND=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null)

# sprint run でなければ何もしない
case "$COMMAND" in
  *"sprint run"*|*"sprint\" run"*) ;;
  *) echo '{"continue":true}'; exit 0 ;;
esac

total=0
tasks="{}"
while read -r c t; do
  [ -n "$c" ] || continue
  [ -f "$(evidence_file "$c" "$t")" ] || continue
  case "$t" in
    test|e2e) n=$(evidence_counts "$c" "$t" failed) ;;
    build)    if [ "$(evidence_status "$c" "$t")" = "pass" ]; then n=0; else n=1; fi ;;
    *)        n=$(evidence_errors "$c" "$t") ;;
  esac
  n=${n:-0}
  total=$((total + n))
  tasks=$(jq -c --arg k "$c.$t" --argjson n "$n" '. + {($k): $n}' <<<"$tasks")
done < <(evidence_required)

TS=$(sprint_date '+%Y-%m-%dT%H:%M:%S%z' 2>/dev/null)
mkdir -p "$(dirname "$FAILS_FILE")" 2>/dev/null
jq -nc --argjson total "$total" --argjson tasks "$tasks" --arg ts "$TS" \
  '{total: $total, tasks: $tasks, recorded_at: $ts}' > "$FAILS_FILE"

echo '{"continue":true}'
exit 0
