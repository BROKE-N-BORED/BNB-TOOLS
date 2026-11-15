#!/usr/bin/env bash
# Run the battery-waiter test suite (no live network in tests).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
exec timeout 280 python3 -m unittest discover -s tests -v "$@"
