#!/usr/bin/env bash
# Run the Model Chat Smoke Test suite (no live network, no real model).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
FORGE_PY="/home/hatch/workspace/forge-v2-testenv/bin/python"
if [ -x "$FORGE_PY" ]; then
  PY="$FORGE_PY"
else
  PY="python3"
fi
exec timeout 280 "$PY" -m unittest discover -s tests -v "$@"
