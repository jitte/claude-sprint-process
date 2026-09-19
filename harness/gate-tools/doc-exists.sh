#!/bin/bash
# docs スプリント用ゲート: README §2 等に列挙された成果物文書が実在するか確認する。
# TEST ゲート（BUILD→TEST）で使う = BUILD 完了＝成果物文書の執筆済みを確認する。
# README 内に現れる docs/...\.md パスのうち、自スプリント（docs.sprintRoot 配下）以外を成果物候補とし、
# すべて実在すれば pass。新規作成すべき成果物が未執筆なら MISSING で fail。
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
sprint_config_require
ROOT=$(sprint_root)
FLAGS="$ROOT/.sprint/flags.json"
ID=$(jq -r '.active // ""' "$FLAGS")
DIR=$(jq -r --arg id "$ID" '.sprints[$id].sprint_dir // ""' "$FLAGS")
README="$ROOT/$DIR/README.md"
SPRINT_ROOT_REL=$(sprint_config '.docs.sprintRoot')

[ -f "$README" ] || { echo "README.md not found: $README"; exit 1; }

# README から docs/...\.md パスを抽出（成果物・参照文書の候補）
FILES=$(grep -oE 'docs/[A-Za-z0-9_./-]+\.md' "$README" | sort -u || true)
[ -n "$FILES" ] || { echo "warn: README に docs 文書パスが見つからない"; exit 0; }

FAIL=0
MISSING=""
FOUND=0
for f in $FILES; do
  # 自スプリント文書（sprintRoot 配下の README/SPEC/TEST 自身）は除外
  case "$f" in
    "$SPRINT_ROOT_REL"/*) continue ;;
  esac
  if [ -f "$ROOT/$f" ]; then
    FOUND=$((FOUND + 1))
  else
    MISSING="$MISSING  $f\n"
    FAIL=1
  fi
done

if [ "$FAIL" -ne 0 ]; then
  echo "MISSING 成果物/参照文書（README に記載だが未存在）:"
  printf "$MISSING"
  exit 1
fi

echo "ok: $FOUND 文書が実在"
