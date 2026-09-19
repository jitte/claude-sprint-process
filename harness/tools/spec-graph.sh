#!/bin/bash
# spec-graph.sh — 仕様の参照グラフ（条項 ID の参照解決・循環と節番号参照の検出・陳腐化検出）
#
# 共通事項を個別 SPEC が再記述する構造をやめ、ベース仕様の「条項」を一度だけ書いて
# [ID](path#ID) で参照する。参照が実在し、循環せず、節番号の文字列参照が残っていないことを
# 機械検証する。条項を持つファイルは frontmatter の xref-prefix 宣言で決まる。
# 参照元には文書のほかにテストの名前（describe / it / test の第 1 引数の [[ID]]）が入る。
#
# 使い方:
#   spec-graph.sh verify            V1〜V3 / V5 / V6 / V8〜V11 を検証（違反 0 = exit 0 / 違反あり = exit 1）
#   spec-graph.sh index             グラフを JSON で stdout に出す（nodes は内容ハッシュ付き）
#   spec-graph.sh diff <git-ref>    <git-ref> 時点から内容が変わった条項と参照元を出す
#   spec-graph.sh reverse <ID>      <ID> を参照する箇所を ファイル:行 で列挙する
#   spec-graph.sh deps <FILE>       <FILE> が参照する条項を列挙する
#   spec-graph.sh files             条項を持つファイルの一覧（prefix・layer・条項数・被参照数）
#   spec-graph.sh layers            層 × 層の参照エッジ数の表（方向は指標。制約ではない）
#   spec-graph.sh resolve <FILE>    原文と、そこから到達する条項の本文を出す
#
# 走査ルートは環境変数 SPEC_GRAPH_ROOT で差し替える（既定はリポジトリルート）。
# 出力はすべて stdout に出す（呼び出し側が終了コードと出力の両方で判定するため）。
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
ROOT="${SPEC_GRAPH_ROOT:-$(sprint_root)}"

# 本体は同じディレクトリの spec-graph.py（単体で python3 spec-graph.py <ROOT> <cmd> と起動できる）。
exec python3 "$(dirname "$(readlink -f "$0")")/spec-graph.py" "$ROOT" "$@"
