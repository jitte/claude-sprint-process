#!/bin/bash
# spec-coverage.sh — ベース仕様の条項参照カバレッジ（cov / rcov / tcov）。評価指標であり fail させない。
#
# 使い方:
#   spec-coverage.sh                 active sprint の SPEC.md を考慮
#   spec-coverage.sh --sprint <id>   sprint ID で指定
#   spec-coverage.sh --spec <path>   SPEC.md のパスで指定
#   spec-coverage.sh --no-sprint     ベース仕様だけ
#   spec-coverage.sh --unreferenced  未被参照の条項 ID を末尾に列挙
#   spec-coverage.sh --untested      specDir の条項のうちテストから参照されない ID を文書別に列挙
#   spec-coverage.sh --json          機械可読
#
# 走査ルートは環境変数 SPEC_GRAPH_ROOT で差し替える（既定はプロジェクトルート）。
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
ROOT="${SPEC_GRAPH_ROOT:-$(sprint_root)}"

# 本体は同じディレクトリの spec-coverage.py（単体で python3 spec-coverage.py <ROOT> [options] と起動できる）。
exec python3 "$(dirname "$(readlink -f "$0")")/spec-coverage.py" "$ROOT" "$@"
