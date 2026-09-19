#!/bin/bash
# verify — 設定の tasks（lint / typecheck / build / test / e2e）が通るか。
#
# 使い方: verify.sh [task ...]
#   task = 設定の tasks のいずれか（省略時は tasks の順で全部）
#
# 各タスクを `bin/sprint run <task>` で実行し、証跡契約の JSON で判定する（解析は lib/evidence.sh）。
#   - test / e2e: counts.failed = 0 かつ counts.skipped = 0
#   - lint / typecheck / build: errors = 0。warnings > 0 は fail。GATE_ALLOW_WARN=1（ユーザが go と判断）のときだけ通過
#
# 環境変数:
#   GATE_ALLOW_WARN   1 なら warning を通過させる
#
# 終了コード: 0 = 通過 / 2 = 実装の問題（BUILD に戻す）/ 4 = 不明な task
set -uo pipefail
HARNESS="$(dirname "$(readlink -f "$0")")/.."
. "$HARNESS/lib/env.sh"
. "$HARNESS/lib/evidence.sh"
sprint_config_require

STEPS=("$@")
[ ${#STEPS[@]} -gt 0 ] || mapfile -t STEPS < <(sprint_tasks)

check_task() { # <task>
  local t="$1" c n st ok=1
  while read -r c tt; do
    [ "$tt" = "$t" ] || continue
    st=$(evidence_status "$c" "$t")
    case "$t" in
      test|e2e)
        n=$(evidence_counts "$c" "$t" failed)
        [ "${n:-0}" -eq 0 ] || { echo "$c.$t: $n failed"; ok=0; }
        n=$(evidence_counts "$c" "$t" skipped)
        [ "${n:-0}" -eq 0 ] || { echo "$c.$t: $n skipped"; ok=0; }
        ;;
      *)
        n=$(evidence_errors "$c" "$t")
        [ "${n:-0}" -eq 0 ] || { echo "$c.$t: $n errors（修正必須・override 不可）"; ok=0; }
        n=$(evidence_warnings "$c" "$t")
        if [ "${n:-0}" -gt 0 ]; then
          if [ "${GATE_ALLOW_WARN:-0}" = "1" ]; then
            echo "$c.$t: warning $n 件・ユーザ go 済みで通過"
          else
            echo "$c.$t: $n warnings（go/no-go はユーザ判断。go なら GATE_ALLOW_WARN=1 を付けて再実行）"; ok=0
          fi
        fi
        ;;
    esac
    [ "$st" = "pass" ] || { echo "$c.$t: status $st"; ok=0; }
  done < <(evidence_required)
  [ "$ok" -eq 1 ]
}

for s in "${STEPS[@]}"; do
  grep -qx "$s" <<<"$(sprint_tasks)" || { echo "unknown task: $s"; exit 4; }
  bash "$HARNESS/bin/sprint" run "$s" > /dev/null 2>&1 || true
  check_task "$s" || { echo "$s failed"; exit 2; }
  echo "$s ok"
done
exit 0
