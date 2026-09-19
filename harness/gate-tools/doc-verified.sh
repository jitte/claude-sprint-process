#!/bin/bash
# docs スプリント用ゲート: TEST.md の UNSEAL ブロックにある判定表（見出し行に「判定」列を持つ最初の表）を読み、
# 最新の巡（判定が記入された最後の行）の判定が 🟢 であることを確認する。
# DOCS/SHIP ゲートで使う = TEST 完了＝ドキュメント整合性チェックが green を確認する（results の green の docs 版）。
#
# 見るのは表のセルだけ。UNSEAL の散文に 🔴 や 🟢 があっても判定に使わない。
# 判定セルは 🟢 / 🟡 / 🔴 のどれか 1 つ。雛形の記入前の行（🔴🟡🟢）は未記入として飛ばす。
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
sprint_config_require
ROOT=$(sprint_root)
FLAGS="$ROOT/.sprint/flags.json"
ID=$(jq -r '.active // ""' "$FLAGS")
DIR=$(jq -r --arg id "$ID" '.sprints[$id].sprint_dir // ""' "$FLAGS")
TEST_MD="$ROOT/$DIR/TEST.md"

[ -f "$TEST_MD" ] || { echo "TEST.md not found: $TEST_MD"; exit 1; }

# UNSEAL ブロック内（qa の実行結果記入欄）の判定表から、記入済みの判定セルを行順に出す
VERDICTS=$(awk '
  /UNSEAL:BEGIN/ { f = 1; next }
  /UNSEAL:END/   { f = 0 }
  !f { next }
  /^[[:space:]]*\|/ {
    n = split($0, c, "|")
    if (col == 0) {                       # 見出し行を探す
      for (i = 2; i < n; i++) { gsub(/^[[:space:]]+|[[:space:]]+$/, "", c[i]); if (c[i] == "判定") { col = i; break } }
      next
    }
    if (done) next
    if ($0 ~ /^[[:space:]]*\|[[:space:]]*-+/) next   # 区切り行
    v = c[col]; gsub(/^[[:space:]]+|[[:space:]]+$/, "", v)
    if (v == "🟢" || v == "🟡" || v == "🔴") print v
    next
  }
  { if (col > 0) done = 1 }                # 表が終わった
' "$TEST_MD")

LAST=$(printf '%s\n' "$VERDICTS" | tail -1)
if [ -z "$LAST" ]; then
  echo "TEST.md の UNSEAL に判定が記入された行がない（判定表の「判定」列に 🟢 / 🟡 / 🔴 を書く）"
  exit 1
fi
if [ "$LAST" != "🟢" ]; then
  echo "TEST.md の最新の巡の判定が $LAST（🟢 でない）"
  exit 1
fi

echo "ok: TEST.md 整合性チェック green（最新の巡）"
