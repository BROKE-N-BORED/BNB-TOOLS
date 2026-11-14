#!/usr/bin/env bash
# Repo Health Board uninstaller - removes the app menu entry,
# desktop icon, command-line link, and private tools folder. The
# saved board, settings, and logs live in your data folder
# (~/.local/share/repo-health-board) and are left alone, so a
# reinstall finds them again.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"

rm -f "$HOME/.local/share/applications/repo-health-board.desktop"
rm -f "$HOME/Desktop/Repo Health Board.desktop"
rm -f "$HOME/.local/bin/repo-health-board"
rm -f "$HOME/.local/bin/board-cli"
rm -f "$HOME/.local/bin/board-fetch"
rm -f "$HOME/.local/bin/board-flag"
rm -rf "$DIR/.venv" "$DIR/.venv.backup"
rm -f "$DIR/install.log"

echo "Repo Health Board is uninstalled. The saved board, settings, and logs were left in place, so a reinstall finds them again."
echo "You can delete this folder now if you want it gone."
