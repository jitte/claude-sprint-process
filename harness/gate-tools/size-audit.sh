#!/bin/bash
# ファイルサイズ監査 — 上限を超えるソース（設定の src − tests）を列挙する
#
# 目的: サイズ超過ファイルの申し送りを人手転記に頼らない。
#
# 判定は 2 段。一律の上限では運用できないため、報告と却下を分ける。
#   〜SIZE_WARN     🟢 通過
#   SIZE_WARN+1 〜 SIZE_LIMIT  🟡 通過。毎回一覧で報告する
#   SIZE_LIMIT+1 〜 🔴 却下
#
# 終了コードは起動形態で変える。切替は環境変数 SPRINT_GATE（sprint_via_gate）で行う。
#   SPRINT_GATE=1（ゲート経由）: 🟢 0 / 🟡 0 / 🔴 2（2 = 実装の失敗。gate-check.sh の失敗分類）
#   SPRINT_GATE なし（手動）: 🟢 0 / 🟡 1 / 🔴 1
# 手動実行で 🟡 を 1 にするのは、意図して確認するときに超過が残っていることを
# 失敗として受け取りたいためである。
#
# 環境変数:
#   SIZE_WARN        警告閾値（既定 800）
#   SIZE_LIMIT       却下閾値（既定 1200）
#   SIZE_AUDIT_ROOT  走査ルート。未設定なら git のトップレベル（テスト用）
#   SPRINT_GATE      ゲート経由の起動を示す。gate-check.sh が export する
#
# 手動実行は `bash harness/bin/sprint size-audit`。TEST ゲートに接続済み（sprint.config.json の gates）。
set -euo pipefail

WARN=${SIZE_WARN:-800}
LIMIT=${SIZE_LIMIT:-1200}

. "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
sprint_config_require
ROOT="${SIZE_AUDIT_ROOT:-$(sprint_root)}"

# 走査対象 = src に一致し tests に一致しないファイル（設定の glob）
mapfile -t SRC_GLOBS < <(sprint_component_globs src)
mapfile -t TEST_GLOBS < <(sprint_component_globs tests)
TARGETS=$(comm -23 \
  <(sprint_glob_files -r "$ROOT" "${SRC_GLOBS[@]}") \
  <(sprint_glob_files -r "$ROOT" "${TEST_GLOBS[@]}"))

if [ -z "$TARGETS" ]; then
  echo "ok: no file over ${WARN} lines"
  exit 0
fi

# 警告閾値を超えるファイルを行数の降順で列挙する
WARN_HITS=$(printf '%s\n' "$TARGETS" | sed "s|^|$ROOT/|" \
  | xargs -r -d '\n' wc -l 2>/dev/null \
  | grep -v ' total$' \
  | awk -v limit="$WARN" '$1 > limit { print $1 "\t" $2 }' \
  | sort -rn || true)

if [ -z "$WARN_HITS" ]; then
  echo "ok: no file over ${WARN} lines"
  exit 0
fi

WARN_COUNT=$(echo "$WARN_HITS" | wc -l | tr -d ' ')
OVER_HITS=$(echo "$WARN_HITS" | awk -F'\t' -v limit="$LIMIT" '$1 > limit' || true)

if [ -n "$OVER_HITS" ]; then
  OVER_COUNT=$(echo "$OVER_HITS" | wc -l | tr -d ' ')
  echo "size over ${LIMIT} lines: ${OVER_COUNT} file(s) — ${WARN} 行以下に分割してください"
  echo "$OVER_HITS" | sed "s|$ROOT/||"
  echo "（参考）${WARN} 行超過: ${WARN_COUNT} 件"
  echo "$WARN_HITS" | sed "s|$ROOT/||"
  # ゲート経由は 2（実装の失敗）、手動は 1
  if sprint_via_gate; then exit 2; fi
  exit 1
fi

echo "warn: ${WARN} 行超過 ${WARN_COUNT} 件（${LIMIT} 行までは通過）"
echo "$WARN_HITS" | sed "s|$ROOT/||"
# ゲート経由は通過させる。手動は失敗として受け取る
if sprint_via_gate; then exit 0; fi
exit 1
