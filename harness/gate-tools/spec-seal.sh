#!/bin/bash
# spec-verify（封印ハッシュ一致確認）
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
sprint_config_require
ROOT=$(sprint_root)
bash "$(dirname "$(readlink -f "$0")")/../tools/spec-seal.sh" verify > /dev/null 2>&1 || { echo "spec-verify failed"; exit 1; }
echo "ok"
