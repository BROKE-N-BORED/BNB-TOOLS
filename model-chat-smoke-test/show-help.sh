#!/usr/bin/env bash
# Model Chat Smoke Test - what the desktop icon runs: shows what the
# tool does, then waits so the window stays open to read.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
# Resolve symlinks, so launching through a link still finds this folder.
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
cd "$DIR"

python3 "$DIR/model_chat_smoke_test.py" --help
echo
echo "This tool runs from the command line: give it your engine's"
echo "command and your model names, and it runs a canned chat"
echo "through each model and reports pass or fail. See README.md"
echo "in this folder for the full chain."
echo
read -r -p "Press Enter to close. " _
