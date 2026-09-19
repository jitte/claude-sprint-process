#!/bin/bash
# ステージゲートチェック ランナー
#
# Usage: gate-check.sh <STAGE>
#
# sprint.config.json の gates.<kind>.<STAGE> から指定ステージのツール一覧を読み、
# gateToolsDirs の順に <dir>/<tool>.sh を探して実行する。
# 1つでも fail (exit != 0) があれば全体を fail で返す。
#
# 失敗時は「失敗の分類」と「推奨遷移先」を提示する（§失敗分類）。
# 遷移そのものは実行しない — 巻き戻し先の判断は人間が行う。
set -euo pipefail

. "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
sprint_config_require
ROOT=$(sprint_root)
FLAGS="$ROOT/.sprint/flags.json"
STAGE="${1:-}"
# ツールの置き場（設定の gateToolsDirs。先に見つかった方を使う）
mapfile -t TOOLS_DIRS < <(sprint_config '.gateToolsDirs[]' | while IFS= read -r d; do sprint_abs_path "$d"; done)

# ── 失敗分類 ──────────────────────────────────────────────
# ゲート失敗を4分類し、推奨遷移先を提示する。分類は「どこに戻れば直せるか」で切る。
#   1 = 仕様の問題   → PLAN
#   2 = 実装の問題   → BUILD
#   3 = テストの問題 → BUILD
#   4 = 基盤・手順   → 据え置き（現ステージで修復。遷移不要）
#
# ツールが終了コード 2/3/4 を返した場合はそれを採用する（失敗内容によって
# 分類が変わるもの = results / impl-sync / tdd-audit / size-audit）。exit 1 のツールは
# 下記の既定分類に従う。プロジェクト固有のツール（gateToolsDirs の 2 つ目以降）の既定分類は
# 設定の gateToolClasses（{ "<tool>": 1〜4 }）に書く。無ければ 2。
default_class() {
  local c
  c=$(jq -r --arg t "$1" '.gateToolClasses[$t] // empty' "$(sprint_config_path)" 2>/dev/null)
  case "$c" in 1|2|3|4) echo "$c"; return ;; esac
  case "$1" in
    spec-files-exist|spec-seal)  echo 1 ;;  # 仕様アーティファクトの不在・改変
    spec-lint)                   echo 1 ;;  # 条項参照の破れ・§0 の未記入・Test ID の形式（仕様の構造）
    impl-sync)                   echo 1 ;;  # 動的分類（1/2/4）を返す。exit 1 = 仕様
    tdd-audit)                   echo 1 ;;  # exit 1 = TEST.md 不在・書式（動的分類は 3/4 を返す）
    verify|size-audit)           echo 2 ;;  # 実装が通らない・サイズ超過（size-audit は動的 2）
    doc-exists)                  echo 2 ;;  # docs では執筆＝実装相当
    tdd-exists|doc-verified)     echo 3 ;;  # テストの不足・検証記入が未了
    results|ship-closed)         echo 4 ;;  # 手順の抜け（results は動的 2/3/4 を返す）
    *)                           echo 2 ;;
  esac
}

class_label() {
  case "$1" in
    1) echo "仕様" ;;
    2) echo "実装" ;;
    3) echo "テスト" ;;
    4) echo "基盤" ;;
    *) echo "不明" ;;
  esac
}

suggest() {
  case "$1" in
    1) echo "PLAN に巻き戻す（SPEC/TEST を修正 → REVIEW → bash harness/bin/sprint seal → build-red）" ;;
    2) echo "BUILD に巻き戻す（実装を修正）" ;;
    3) echo "BUILD に巻き戻す（テストを修正・skip 解除・再実行）" ;;
    4) echo "ステージ据え置き（環境・手順の問題。テスト再実行や記入漏れの補完で解消する）" ;;
    *) echo "分類不明。出力を確認してください" ;;
  esac
}

[ -n "$STAGE" ] || { echo "Usage: gate-check.sh <STAGE>" >&2; exit 1; }

# active sprint の kind（code|docs、未設定は code）でゲートセットを選ぶ
KIND="code"
if [ -f "$FLAGS" ]; then
  AID=$(jq -r '.active // ""' "$FLAGS" 2>/dev/null || echo "")
  [ -n "$AID" ] && KIND=$(jq -r --arg id "$AID" '.sprints[$id].kind // "code"' "$FLAGS" 2>/dev/null || echo "code")
fi

# ステージのツール一覧を取得（kind 別）
TOOLS=$(jq -r --arg k "$KIND" --arg s "$STAGE" '.gates[$k][$s] // [] | .[]' "$(sprint_config_path)" 2>/dev/null)

if [ -z "$TOOLS" ]; then
  echo "gate ($STAGE): no checks defined — pass"
  exit 0
fi

FAIL=0
TOTAL=0
PASSED=0
CLASSES=""

# ゲート経由の起動であることをツールに伝える。
# ツールを `bash "$SCRIPT"` と引数なしで起動するためフラグを渡せない。
# サブシェルは環境を継承するので、ループ前で一度 export すれば全ツールが判別できる
# （ツール側は lib/env.sh の sprint_via_gate で読む）。
# 例: size-audit は手動実行なら 🟡 を失敗（1）、ゲート経由なら通過（0）にする。
export SPRINT_GATE=1

echo "=== Gate Check: $STAGE (kind=$KIND) ==="
for tool in $TOOLS; do
  TOTAL=$((TOTAL + 1))
  # gateToolsDirs の順に探す
  SCRIPT=""
  for d in "${TOOLS_DIRS[@]}"; do
    [ -f "$d/${tool}.sh" ] && { SCRIPT="$d/${tool}.sh"; break; }
  done

  if [ -z "$SCRIPT" ]; then
    echo "  ✗ $tool [基盤] — script not found: ${tool}.sh（${TOOLS_DIRS[*]}）"
    FAIL=1
    CLASSES="$CLASSES 4"
    continue
  fi

  OUTPUT=$(bash "$SCRIPT" 2>&1) && RC=0 || RC=$?

  if [ "$RC" -eq 0 ]; then
    echo "  ✓ $tool"
    PASSED=$((PASSED + 1))
    continue
  fi

  # 2/3/4 はツールが返した動的分類。それ以外（1 = 分類なし、および
  # set -e / pipefail 由来の予期しないコード 123 等）はすべて既定分類マップに落とす。
  case "$RC" in
    2|3|4) CLS="$RC" ;;
    *)     CLS=$(default_class "$tool") ;;
  esac

  # 出力が空だと原因が追えないため、終了コードを添える
  [ -n "$OUTPUT" ] || OUTPUT="(出力なし・終了コード ${RC})"

  echo "  ✗ $tool [$(class_label "$CLS")] — $OUTPUT"
  FAIL=1
  CLASSES="$CLASSES $CLS"
done

echo "--- $PASSED/$TOTAL passed ---"

if [ "$FAIL" -ne 0 ]; then
  echo "=== GATE BLOCKED ==="
  # 最も上流の分類（数値が小さいもの）を推奨の根拠にする。
  WORST=$(printf '%s\n' $CLASSES | sort -n | head -1)
  LABELS=""
  for c in $(printf '%s\n' $CLASSES | sort -nu); do LABELS="$LABELS $(class_label "$c")"; done
  echo "失敗分類:$LABELS"
  echo "推奨: $(suggest "$WORST")"
  echo "（遷移は自動実行しません。巻き戻し先の判断はユーザーが行ってください）"
  exit 1
fi

echo "=== GATE PASSED ==="
exit 0
