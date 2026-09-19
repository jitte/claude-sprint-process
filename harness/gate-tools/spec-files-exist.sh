#!/bin/bash
# SPEC.md / TEST.md が存在するか
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
sprint_config_require
ROOT=$(sprint_root)
FLAGS="$ROOT/.sprint/flags.json"
ID=$(jq -r '.active // ""' "$FLAGS")
DIR=$(jq -r --arg id "$ID" '.sprints[$id].sprint_dir // ""' "$FLAGS")
[ -f "$ROOT/$DIR/SPEC.md" ] || { echo "SPEC.md not found: $DIR/SPEC.md"; exit 1; }
[ -f "$ROOT/$DIR/TEST.md" ] || { echo "TEST.md not found: $DIR/TEST.md"; exit 1; }
echo "ok"
