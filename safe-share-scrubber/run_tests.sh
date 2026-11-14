#!/usr/bin/env bash
# Run the Safe Share Scrubber test suite (no live network in tests).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
FORGE_PY="/home/hatch/workspace/forge-v2-testenv/bin/python"
if [ -x "$FORGE_PY" ]; then
  PY="$FORGE_PY"
else
  PY="python3"
fi
export LD_LIBRARY_PATH="/home/hatch/workspace/qt-libs/root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export QT_QPA_PLATFORM=offscreen
export TMPDIR=/tmp
exec timeout 280 "$PY" -m unittest discover -s tests -v "$@"
