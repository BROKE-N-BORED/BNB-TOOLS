#!/usr/bin/env bash
# Safe Share Scrubber uninstaller - removes the app menu entry,
# desktop icon, command-line link, private tools folder, and the
# logs folder. There is no other user data: the app keeps no
# settings or files of yours beyond its logs.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"

rm -f "$HOME/.local/share/applications/safe-share-scrubber.desktop"
rm -f "$HOME/Desktop/Safe Share Scrubber.desktop"
rm -f "$HOME/.local/bin/safe-share-scrubber"
rm -rf "$DIR/.venv" "$DIR/.venv.backup"
rm -rf "$DIR/logs"
rm -f "$DIR/install.log"

echo "Safe Share Scrubber is uninstalled. The logs folder was removed too; the app keeps nothing else of yours."
echo "You can delete this folder now if you want it gone."
