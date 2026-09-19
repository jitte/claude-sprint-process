#!/bin/bash
# CLOSED ゲート: SHIP ステージが closed であることを確認
# （SHIP の作業を完了せずに CLOSED に抜けるのを防ぐ）
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
sprint_config_require
ROOT=$(sprint_root)
FLAGS="$ROOT/.sprint/flags.json"

ACTIVE=$(jq -r '.active // ""' "$FLAGS")
[ -n "$ACTIVE" ] || { echo "active sprint not set"; exit 1; }

# 直前のステージ遷移で stage は既に CLOSED に変わっている場合があるので、
# 遷移元が SHIP だったかは sprint.sh 側で保証される（allowed_next で SHIP→CLOSED のみ許可）。
# ここでは「SHIP の成果物（コミット）が存在するか」をチェックする。
# README §8 のコミットハッシュが記入済みであることで代替。
SPRINT_DIR=$(jq -r --arg id "$ACTIVE" '.sprints[$id].sprint_dir // ""' "$FLAGS")
README="$ROOT/$SPRINT_DIR/README.md"

if [ ! -f "$README" ]; then
  echo "README.md not found: $README"
  exit 1
fi

if grep -q 'コミットハッシュ:$' "$README" || grep -q 'コミットハッシュ: *$' "$README"; then
  echo "README §8 にコミットハッシュが未記入です（SHIP が完了していません）"
  exit 1
fi

exit 0
