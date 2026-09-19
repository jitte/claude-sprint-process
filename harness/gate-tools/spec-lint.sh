#!/bin/bash
# spec-lint — 仕様の機械検査（REVIEW / build-red ゲート）。
#
# 使い方: spec-lint.sh [check ...]
#   check = graph | refs | test-id（省略時は全部。全部走らせてから集約する）
#   graph   : harness/tools/spec-graph.sh verify（条項参照 V1〜V3 / V5 / V6 / V8〜V11）
#   refs    : active スプリントの SPEC.md §0（参照する共通条項）に扱いと根拠が書かれている
#   test-id : active スプリントの TEST.md のテスト定義行の ID が TEST-<sprint_id>-<major>.<minor> の形
#
# 環境変数（テストの入口）:
#   SPEC_GRAPH_ROOT   graph の走査ルート
#   SPEC_REFS_TARGET  refs が読む SPEC.md（省略時は flags.json の active から解決）
#   TID_TEST_MD       test-id が読む TEST.md（同上）
#   TID_SPRINT_ID     test-id が期待する sprint id（同上）
#
# 終了コード: 0 = 通過 / 1 = 仕様の問題（PLAN に戻す）/ 4 = 不明な check
set -uo pipefail
. "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
sprint_config_require
ROOT=$(sprint_root)
FLAGS="$ROOT/.sprint/flags.json"
CHECKS=("$@")
[ ${#CHECKS[@]} -gt 0 ] || CHECKS=(graph refs test-id)
FAIL=0

active_id()  { jq -r '.active // ""' "$FLAGS" 2>/dev/null; }
active_dir() { jq -r --arg id "$(active_id)" '.sprints[$id].sprint_dir // ""' "$FLAGS" 2>/dev/null; }

check_graph() {
  local out
  out=$(bash "$(dirname "$(readlink -f "$0")")/../tools/spec-graph.sh" verify 2>&1) || { echo "$out"; FAIL=1; return; }
  echo "$out"
}

# §0 の表行に「テストの扱い」と「Test ID / 理由」が埋まっているかを見る。内容の妥当性は見ない。
# 受理するのは新記法 [ID](path#ID) の表行だけ。二重括弧の旧記法は表行として拾わない
# （受理を残すと新記法へ移行させる力が働かない）。読むのは active の SPEC.md 1 本だけ。
check_refs() {
  local spec section ref_cell rows n=0 bad=0 row cid handling evidence pair col val
  spec="${SPEC_REFS_TARGET:-$ROOT/$(active_dir)/SPEC.md}"
  [ -f "$spec" ] || { echo "SPEC.md not found: $spec"; FAIL=1; return; }
  if ! grep -q '^## 0\. 参照する共通条項' "$spec"; then
    echo "§0（## 0. 参照する共通条項）の見出しが無い"
    echo "  節ごと省略して検査を迂回できない。テンプレート docs/06_process/templates/SPEC.md に従う"
    FAIL=1; return
  fi
  section=$(awk '/^## 0\. 参照する共通条項/{f=1;next} f&&/^## /{exit} f{print}' "$spec")
  ref_cell='\[[A-Z]{2,6}-[0-9]+\]\([^)]*#[A-Z]{2,6}-[0-9]+\)'
  rows=$(printf '%s\n' "$section" | grep -E "^\|[[:space:]]*${ref_cell}[[:space:]]*\|" || true)
  if [ -z "$rows" ]; then
    if grep -qE '^\|[[:space:]]*（参照なし）[[:space:]]*\|' <<<"$section"; then
      echo "refs ok: §0 は参照ゼロ（（参照なし）行で判断を記録済み）"
      return
    fi
    echo "§0 に条項参照の表行も（参照なし）行も無い"
    echo "  参照する条項は [ID](<相対パス>#ID) の形で第 1 列に書く"
    echo "  二重括弧の旧記法は受理しない。記法は docs/05_specifications/README.md §3"
    echo "  共通条項に依存しないなら次の 1 行を書く:"
    echo "  | （参照なし） | — | 不要 | 共通条項に依存しない |"
    FAIL=1; return
  fi
  while IFS= read -r row; do
    n=$((n + 1))
    cid=$(printf '%s' "$row" | awk -F'|' '{gsub(/^[ \t]+|[ \t]+$/,"",$2); print $2}')
    handling=$(printf '%s' "$row" | awk -F'|' '{gsub(/^[ \t]+|[ \t]+$/,"",$4); print $4}')
    evidence=$(printf '%s' "$row" | awk -F'|' '{gsub(/^[ \t]+|[ \t]+$/,"",$5); print $5}')
    for pair in "テストの扱い:$handling" "Test ID / 理由:$evidence"; do
      col="${pair%%:*}"; val="${pair#*:}"
      case "$val" in
        ""|"—"|"-"|"TBD") echo "$cid: 「${col}」が空である"; bad=1 ;;
      esac
    done
    case "$handling" in
      新規|改修|流用|不要|""|"—"|"-"|"TBD") ;;
      *) echo "$cid: 「テストの扱い」が 4 値（新規 / 改修 / 流用 / 不要）以外である: $handling"; bad=1 ;;
    esac
  done <<< "$rows"
  if [ "$bad" -ne 0 ]; then echo "refs NG（$n 行を検査）"; FAIL=1; return; fi
  echo "refs ok: §0 の $n 行すべてに扱いと根拠がある"
}

# Test ID をスプリント ID で前置して全スプリントで一意にする。旧形式（前置なし）が
# 1 件でも残っていれば fail。旧形式の ID は書き換えない（形が違うため新形式と衝突しない）。
# 旧設計（他スプリントの TEST.md と (ID, ファイル) の組で照合）は、テストファイル列の
# 無い過去 TEST.md で組を作れず素通りした。ID 体系を変えることが本来の解である。
check_test_id() {
  local sprint_id test_md expect ids bad total
  sprint_id="${TID_SPRINT_ID:-$(active_id)}"
  test_md="${TID_TEST_MD:-$ROOT/$(active_dir)/TEST.md}"
  [ -n "$sprint_id" ] || { echo "active sprint id が解決できません"; FAIL=1; return; }
  [ -f "$test_md" ] || { echo "TEST.md not found: $test_md"; FAIL=1; return; }
  expect="TEST-${sprint_id}-"
  # テスト定義行（先頭セルが Test ID の行）。新旧どちらの形式も拾う（旧形式を検出して落とすため）
  ids=$(
    grep -E '^[[:space:]]*\|' "$test_md" \
    | awk -F'|' '{ gsub(/^[ \t]+|[ \t]+$/, "", $2); gsub(/\*/, "", $2); print $2 }' \
    | grep -E '^TEST-[0-9]+(-[0-9]+)*\.[0-9]+[a-z]?$' || true
  )
  if [ -z "$ids" ]; then echo "test-id ok（テスト定義行なし）"; return; fi
  bad=$(grep -v -F "$expect" <<<"$ids" || true)
  if [ -n "$bad" ]; then
    echo "旧形式の Test ID が残っています。全スプリントで一意にするため ${expect}<major>.<minor> の形に振り直してください。"
    echo "$bad" | sort -u | sed 's/^/  /'
    FAIL=1; return
  fi
  total=$(wc -l <<<"$ids" | tr -d ' ')
  echo "test-id ok（$total 件すべて ${expect} 形式）"
}

for c in "${CHECKS[@]}"; do
  case "$c" in
    graph)   check_graph ;;
    refs)    check_refs ;;
    test-id) check_test_id ;;
    *) echo "unknown check: $c"; exit 4 ;;
  esac
done

[ "$FAIL" -eq 0 ] || exit 1
exit 0
