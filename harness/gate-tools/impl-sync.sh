#!/bin/bash
# impl-sync — 実装の公開ルート集合と仕様が書くルート集合を双方向に比較する（TEST ゲート）。
#
# 使い方: impl-sync.sh [routes]
#   routes : harness/tools/api-routes.sh verify（実装の公開ルート集合 ↔ 05 が書くルート集合）
#
# 実装側の集合は正規表現で取らない。実装を import して出させる（dump-routes.ts）。
# 正規表現ではキー記法・コメント・文字列内の波括弧を列挙しきれず、拾えなかった要素が集合から黙って
# 消える。集合が縮む方向の失敗は、このゲートが検出すべき状態をゲート自身が隠す。
#
# プロジェクト固有の集合比較は gateToolsDirs のプロジェクト側にある
# （設定の gates が別のツールとして呼ぶ）。
#
# 環境変数（テストの入口）:
#   API_ROUTES_IMPL_CMD / API_ROUTES_ROOT   routes（api-routes.sh が読む）
#
# 終了コード = 失敗分類。
#   1 = 仕様（実装にあって仕様に無い → PLAN に戻す）
#   2 = 実装（仕様にあって実装に無い → BUILD に戻す）
#   4 = 基盤（対象が読めない・実装側の取得に失敗）
set -uo pipefail
. "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
sprint_config_require
REPO_ROOT=$(sprint_root)
CHECKS=("$@")
[ ${#CHECKS[@]} -gt 0 ] || CHECKS=(routes)

for c in "${CHECKS[@]}"; do
  case "$c" in
    routes) bash "$(dirname "$(readlink -f "$0")")/../tools/api-routes.sh" verify; exit $? ;;
    *) echo "unknown check: $c"; exit 4 ;;
  esac
done
