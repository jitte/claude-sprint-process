#!/bin/bash
# results — 実行証跡の鮮度・green を検査する。証跡契約の JSON だけを読む（解析は lib/evidence.sh）。
#
# 使い方: results.sh [check ...]
#   check = fresh | green（省略時は全部）
#   fresh : 設定の全 (component, task) について証跡ファイルがあり、finished_at がソース
#           （全コンポーネントの src ∪ tests に一致するファイル）の最終更新以上である
#   green : status が pass で、test / e2e は counts.failed = 0 かつ counts.skipped = 0、
#           lint / typecheck / build は errors = 0 かつ warnings = 0（GATE_ALLOW_WARN=1 なら warnings を見ない）
#           （.sprint/test-fails.json は読まない。hook が main の Bash 直後にしか書かず、ゲート内の再実行で古くなる）
#   .partial.json は読まない。
#
# 終了コード = 失敗分類（gate-check.sh）。失敗内容によって変わる:
#   2 = lint / typecheck / build の失敗（実装の問題 → BUILD）
#   3 = テストの失敗・skipped（テストの問題 → BUILD）
#   4 = 証跡ファイルが無い・古い（テスト未実行 = 手順の問題 → 据え置き）
# 複数が混在する場合は最も上流（数値が小さいもの）を返す。
set -uo pipefail
. "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
. "$(dirname "$(readlink -f "$0")")/../lib/evidence.sh"
sprint_config_require
ROOT=$(sprint_root)
CHECKS=("$@")
[ ${#CHECKS[@]} -gt 0 ] || CHECKS=(fresh green)

FAIL=0
CLS=0
note() { # $1 = 分類コード。より上流（小さい値）を保持する
  if [ "$CLS" -eq 0 ] || [ "$1" -lt "$CLS" ]; then CLS="$1"; fi
  FAIL=1
}

# ソースの最終更新（epoch 秒）。src ∪ tests に一致するファイルの最大値
latest_source_mtime() {
  local globs
  mapfile -t globs < <(sprint_component_globs src; sprint_component_globs tests)
  [ ${#globs[@]} -gt 0 ] || return 0
  sprint_glob_files "${globs[@]}" | sed "s|^|$ROOT/|" | xargs -r -d '\n' stat -c '%Y' 2>/dev/null | sort -rn | head -1
}

check_fresh() {
  local latest c t s st fl sk er wa fin
  latest=$(latest_source_mtime)
  [ -n "$latest" ] || { echo "no source files found"; note 4; return; }
  while read -r c t; do
    [ -n "$c" ] || continue
    s=$(evidence_summary "$c" "$t")
    [ -n "$s" ] || { echo "$c.$t.json not found"; note 4; continue; }
    read -r st fl sk er wa fin <<<"$s"
    if [ "${fin:-0}" -lt "$latest" ]; then
      echo "$c.$t is stale (finished=$fin < source=$latest)"
      note 4
    fi
  done < <(evidence_required)
}

check_green() {
  local c t s st fl sk er wa fin
  while read -r c t; do
    [ -n "$c" ] || continue
    s=$(evidence_summary "$c" "$t")
    [ -n "$s" ] || { echo "$c.$t.json not found"; note 4; continue; }
    read -r st fl sk er wa fin <<<"$s"
    case "$t" in
      test|e2e)
        if [ "${fl:-0}" -gt 0 ]; then
          echo "$c.$t: $fl failed"; note 3
        elif [ "$st" != "pass" ]; then
          echo "$c.$t: status $st"; note 3
        fi
        if [ "${sk:-0}" -gt 0 ]; then
          echo "$c.$t: $sk skipped"; note 3
        fi
        ;;
      *)
        if [ "${er:-0}" -gt 0 ]; then
          echo "$c.$t: $er errors"; note 2
        elif [ "$st" != "pass" ]; then
          echo "$c.$t: status $st"; note 2
        fi
        if [ "${wa:-0}" -gt 0 ] && [ "${GATE_ALLOW_WARN:-0}" != "1" ]; then
          echo "$c.$t: $wa warnings"; note 2
        fi
        ;;
    esac
  done < <(evidence_required)
}

for c in "${CHECKS[@]}"; do
  case "$c" in
    fresh) check_fresh ;;
    green) check_green ;;
    *) echo "unknown check: $c"; exit 4 ;;
  esac
done

[ "$FAIL" -eq 0 ] || exit "$CLS"
echo "ok (${CHECKS[*]})"
