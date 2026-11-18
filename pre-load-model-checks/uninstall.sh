#!/usr/bin/env bash
# Pre-Load Model Checks uninstaller - removes the app menu entry,
# desktop icon, command-line links, private tools folder, and the
# logs folder. Nothing else is ever written by this app, so there
# is nothing else to remove.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"

rm -f "$HOME/.local/share/applications/pre-load-model-checks.desktop"
rm -f "$HOME/Desktop/Pre-Load Model Checks.desktop"
rm -f "$HOME/.local/bin/preload-checks"
rm -f "$HOME/.local/bin/preloadchecks-cli"
rm -f "$HOME/.local/bin/ram-check"
rm -f "$HOME/.local/bin/process-check"
rm -f "$HOME/.local/bin/suitability-check"
rm -f "$HOME/.local/bin/model-watchdog"
rm -f "$HOME/.local/bin/kill-picker"
rm -rf "$DIR/.venv" "$DIR/.venv.backup"
rm -rf "$DIR/logs"
rm -f "$DIR/install.log"
# The debug logs live in the app data dir, not in the app
# folder (see logsetup.py): remove them too, or the
# "logs folder was removed" message below would be a lie.
DATA_BASE="${XDG_DATA_HOME:-$HOME/.local/share}"
rm -rf "$DATA_BASE/pre-load-model-checks"

echo "Pre-Load Model Checks is uninstalled. The logs folder was removed too."
echo "You can delete this folder now if you want it gone."
