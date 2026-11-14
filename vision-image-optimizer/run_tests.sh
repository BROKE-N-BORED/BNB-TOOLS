#!/usr/bin/env bash
# Run the Vision Image Optimizer test suite (no live network in tests).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
if [ -x "$DIR/.venv/bin/python" ]; then
  PY="$DIR/.venv/bin/python"
else
  PY="python3"
fi
export QT_QPA_PLATFORM=offscreen
export TMPDIR=/tmp
exec timeout 280 "$PY" -m unittest discover -s tests -v "$@"
