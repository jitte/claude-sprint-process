#!/bin/bash
# clause-anchors.sh — 条項アンカーの設置と参照のリンク化
#
# [[ID]] は GitHub でも Obsidian でも実体に繋がらない。条項の見出しの直前に明示
# アンカー <a id="ID"></a> を置き、参照を Markdown リンクに変える。見出しから
# 自動生成される id は見出しの本文が混ざるため、文言を直すとリンクが切れる。
#
# 使い方:
#   clause-anchors.sh           変換を適用する（冪等。2 回実行しても二重に入らない）
#   clause-anchors.sh --check   書き込まず、変更が必要なファイルを列挙する
#                               （変更が必要なら exit 1 / 不要なら exit 0）
#
# 走査ルートは環境変数 CLAUSE_ANCHORS_ROOT で差し替える（既定はリポジトリルート）。
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
ROOT="${CLAUSE_ANCHORS_ROOT:-$(sprint_root)}"

# 本体は同じディレクトリの clause-anchors.py。
exec python3 "$(dirname "$(readlink -f "$0")")/clause-anchors.py" "$ROOT" "$@"
