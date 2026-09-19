#!/bin/bash
# TEST.md の全 Test ID がテストソースコード（設定の tests の glob に一致するファイル）に存在することを確認（skip は許容）
# BUILD ゲート用 — build-red 直後は skip があって当然
#
# 環境変数（テストの入口）:
#   TDD_TEST_MD     TEST.md のパス（省略時 .sprint/flags.json の active sprint から解決）
#   TDD_ID_PATTERN  Test ID の正規表現（tdd-audit.sh と同じ既定値）
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
sprint_config_require
ROOT=$(sprint_root)
TEST_MD="${TDD_TEST_MD:-}"
if [ -z "$TEST_MD" ]; then
  FLAGS="$ROOT/.sprint/flags.json"
  ID=$(jq -r '.active // ""' "$FLAGS")
  DIR=$(jq -r --arg id "$ID" '.sprints[$id].sprint_dir // ""' "$FLAGS")
  TEST_MD="$ROOT/$DIR/TEST.md"
fi

[ -f "$TEST_MD" ] || { echo "TEST.md not found: $TEST_MD"; exit 1; }

# Test ID の形式。TEST-<sprint_id>-<major>.<minor> と TEST-<major>.<minor> の両方に一致する。
# tdd-audit.sh と同じ既定値を使う。
ID_PATTERN="${TDD_ID_PATTERN:-TEST-[0-9]+(-[0-9]+)*\.[0-9]+[a-z]?}"

# テスト定義表の Test ID 列（表の1列目）だけを対象にする。
# 本文中の言及（削除対象の ID・改修の説明・網羅性マトリクスの参照）は
# 「そのテストが存在すべき」ことを意味しないため除外する。
# 抽出 0 件でも set -e で沈黙終了しないよう || true で受け、下の分岐で理由を出す。
SPEC_IDS=$(sed -nE "s/^[[:space:]]*\|[[:space:]]*(${ID_PATTERN})[[:space:]]*\|.*/\1/p" "$TEST_MD" | sort -u || true)

if [ -z "$SPEC_IDS" ]; then
  # 本文には ID があるのに定義表から 1 件も取れない場合は TEST.md の形式が想定外。
  # 何も検査せず pass すると欠落を見逃すため、エラーで止める。
  if grep -qE "$ID_PATTERN" "$TEST_MD"; then
    echo "TEST.md に Test ID はあるが、テスト定義表（1列目が Test ID の表）から抽出できない"
    exit 1
  fi
  echo "warn: TEST.md に Test ID が見つからない"
  exit 0
fi

FAIL=0
MISSING=""
FOUND=0

# 走査対象 = 設定の tests の glob に一致するファイル
mapfile -t TEST_GLOBS < <(sprint_component_globs tests)
TEST_FILES=$(sprint_glob_files "${TEST_GLOBS[@]}" | sed "s|^|$ROOT/|")

for tid in $SPEC_IDS; do
  HITS=$(printf '%s\n' "$TEST_FILES" | xargs -r -d '\n' grep -n "$tid" 2>/dev/null || true)

  if [ -z "$HITS" ]; then
    MISSING="$MISSING  $tid\n"
    FAIL=1
    continue
  fi
  FOUND=$((FOUND + 1))
done

TOTAL=$(echo "$SPEC_IDS" | wc -w)

if [ -n "$MISSING" ]; then
  echo "MISSING (Test ID in TEST.md but not in test source):"
  printf "$MISSING"
fi

if [ "$FAIL" -ne 0 ]; then
  echo "tdd-exists: $FOUND/$TOTAL found"
  exit 1
fi

echo "ok: $FOUND/$TOTAL test IDs exist in source"
