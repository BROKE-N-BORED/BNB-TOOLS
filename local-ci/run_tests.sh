#!/usr/bin/env bash
# Run the Local CI test suite (no live network in tests).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
exec timeout 280 python3 -m unittest discover -s tests -v "$@"
