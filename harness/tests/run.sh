#!/bin/bash
# harness のテストランナー。bun / node に依存しない。
set -euo pipefail

python3 -m unittest discover -s "$(dirname "$(readlink -f "$0")")" -p 'test_*.py' -v
