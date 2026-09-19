#!/bin/bash
# tdd-audit.sh — TEST.md の Test ID を「実行証跡（証跡契約の JSON）」で照合する
#
# 設計原則: テストコードが「どう書かれているか」(grep) ではなく
# 「実行されて何が起きたか」(レポーター JSON) だけを判定根拠にする。
# skip 構文の変種・コメントアウト・.only・コメント内 ID 記載・
# 過去スプリントの同名 ID への相乗り — いずれも実行証跡が要求を満たさず fail する。
#
# 照合ルール:
#   1. TEST.md の表行のうち「先頭セルが Test ID」の行のみをテスト定義行とみなす
#      （網羅性マトリクス・本文中の ID 言及は対象外）
#   2. テスト定義行にはテストファイル (*.test.* / *.spec.*) の記載が必須（無ければ FORMAT fail）
#   3. 設定の全 (component, test|e2e) の証跡の tests[] から
#      「テスト名に ID を含み、ファイル名が行記載と一致」するテストを収集（.partial.json は読まない）
#   4. 0 件 → MISSING / passed 以外 (skipped, todo, pending, failed, flaky...) を含む → fail
#      全て passed → ok
#
# 汎用化（他プロジェクト展開用）: 以下の環境変数で上書き可能
#   TDD_TEST_MD      TEST.md のパス（省略時 .sprint/flags.json の active sprint から解決）
#   TDD_ID_PATTERN   Test ID の正規表現（省略時 TEST-[0-9]+(-[0-9]+)*\.[0-9]+[a-z]?）
#                    TEST-<sprint_id>-<major>.<minor> と TEST-<major>.<minor> の両方に一致する。
#
# 終了コード = 失敗分類（gate-check.sh §失敗分類）。失敗内容によって変わる:
#   1 = TEST.md 不在・FORMAT（テスト定義行にファイル記載なし）= 仕様の問題 → PLAN
#   3 = MISSING / NOT-PASS（実行証跡が要求を満たさない）= テストの問題 → BUILD
#   4 = 証跡が 1 つも無い（テスト未実行 = 手順の問題）→ 据え置き
# 複数が混在する場合は最も上流（数値が小さいもの）を返す。
set -euo pipefail

CLS=0
note() { # $1 = 分類コード。より上流（小さい値）を保持する
  if [ "$CLS" -eq 0 ] || [ "$1" -lt "$CLS" ]; then CLS="$1"; fi
}

. "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
. "$(dirname "$(readlink -f "$0")")/../lib/evidence.sh"
sprint_config_require
ROOT=$(sprint_root)
ID_PATTERN="${TDD_ID_PATTERN:-TEST-[0-9]+(-[0-9]+)*\.[0-9]+[a-z]?}"

# ── TEST.md の解決 ─────────────────────────────────────────
TEST_MD="${TDD_TEST_MD:-}"
if [ -z "$TEST_MD" ]; then
  FLAGS="$ROOT/.sprint/flags.json"
  if [ -f "$FLAGS" ]; then
    ACTIVE=$(jq -r '.active // ""' "$FLAGS")
    DIR=$(jq -r --arg id "$ACTIVE" '.sprints[$id].sprint_dir // ""' "$FLAGS")
    [ -n "$DIR" ] && TEST_MD="$ROOT/$DIR/TEST.md"
  fi
fi
if [ -z "$TEST_MD" ] || [ ! -f "$TEST_MD" ]; then
  echo "TEST.md not found: ${TEST_MD:-unset} (set TDD_TEST_MD)"
  exit 1
fi

# ── 証跡 → 統一形式 (file <TAB> status <TAB> name) ──（解析は evidence.sh）
EVIDENCE=$(mktemp)
trap 'rm -f "$EVIDENCE"' EXIT

if ! evidence_tests_tsv > "$EVIDENCE"; then
  echo "no test evidence found in $(evidence_dir) — run the full test suites first"
  exit 4
fi

# ── TEST.md からテスト定義行 (先頭セル = Test ID) を抽出 ──────
declare -A ID_FILES
ID_ORDER=()

while IFS= read -r line; do
  first_cell=$(sed -E 's/^[[:space:]]*\|[[:space:]]*([^|]*)\|.*/\1/' <<<"$line" | tr -d '[:space:]')
  if ! grep -qE "^${ID_PATTERN}$" <<<"$first_cell"; then
    continue
  fi
  tid="$first_cell"
  # grep 非マッチ（テストファイル記載なし）で pipefail により落ちないよう吸収する。
  # 記載なしの判定は下の files_trimmed が空かどうかで行い、FORMAT として報告する。
  files=$(grep -oE '[A-Za-z0-9_./-]+\.(test|spec)\.[A-Za-z]+' <<<"$line" | sort -u | tr '\n' ' ' || true)
  if [ -z "${ID_FILES[$tid]:-}" ]; then
    ID_ORDER+=("$tid")
    ID_FILES[$tid]="$files"
  else
    ID_FILES[$tid]="${ID_FILES[$tid]} $files"
  fi
done < <(grep -E '^[[:space:]]*\|' "$TEST_MD")

if [ "${#ID_ORDER[@]}" -eq 0 ]; then
  echo "warn: TEST.md にテスト定義行（先頭セルが Test ID の表行）が見つからない（仕様探索スプリント？）"
  exit 0
fi

# ── 照合 ─────────────────────────────────────────────────
FAIL=0
OK=0
ERRORS=""

for tid in "${ID_ORDER[@]}"; do
  files="${ID_FILES[$tid]}"
  files_trimmed=$(tr -s ' ' <<<"$files" | sed 's/^ //; s/ $//')

  if [ -z "$files_trimmed" ]; then
    ERRORS+="  FORMAT   $tid: テスト定義行にテストファイル (*.test.* / *.spec.*) の記載がない\n"
    FAIL=1
    note 1
    continue
  fi

  # テスト名に ID を含む実行結果を、記載ファイル名 (basename) で絞り込む
  # ID は「境界付き」で照合する。単純な部分文字列一致だと TEST-2.1 が
  # TEST-2.15 の実行名にマッチしてしまい、TEST-2.1 の実テストが無くても
  # TEST-2.15 の pass で充足されてしまう（前方包含による相乗り）。
  # ID の直後が英数字でないことを要求してこれを防ぐ。
  tid_re=$(sed 's/\./\\./g' <<<"$tid")

  hits=""
  while IFS=$'\t' read -r f s n; do
    [ -n "$f" ] || continue
    grep -qE "${tid_re}([^0-9A-Za-z]|$)" <<<"$n" || continue
    bn=$(basename "$f")
    for ef in $files_trimmed; do
      if [ "$(basename "$ef")" = "$bn" ]; then
        hits+="${s}\t${f}\t${n}\n"
        break
      fi
    done
  done < "$EVIDENCE"

  if [ -z "$hits" ]; then
    ERRORS+="  MISSING  $tid: 実行結果に該当テストがない（対象: ${files_trimmed}）\n"
    FAIL=1
    note 3
    continue
  fi

  bad=$(printf '%b' "$hits" | awk -F'\t' '$1 != "passed"' || true)
  if [ -n "$bad" ]; then
    first_bad=$(head -1 <<<"$bad")
    ERRORS+="  NOT-PASS $tid: $(cut -f1 <<<"$first_bad") — $(cut -f2- <<<"$first_bad" | tr '\t' ' ')\n"
    FAIL=1
    note 3
    continue
  fi

  OK=$((OK + 1))
done

TOTAL="${#ID_ORDER[@]}"

if [ "$FAIL" -ne 0 ]; then
  echo "tdd-audit (runtime evidence): $OK/$TOTAL passed"
  printf '%b' "$ERRORS"
  exit "$CLS"
fi

echo "ok: $OK/$TOTAL test IDs verified against runtime evidence"
