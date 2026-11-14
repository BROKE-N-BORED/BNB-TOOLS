#!/usr/bin/env bash
# Song Key BPM uninstaller - removes the app menu entry,
# desktop icon, command-line links, private tools folder, and the
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

rm -f "$HOME/.local/share/applications/song-key-bpm.desktop"
rm -f "$HOME/Desktop/Song Key BPM.desktop"
rm -f "$HOME/.local/bin/song-key-bpm"
rm -f "$HOME/.local/bin/song-key-analyze"
rm -f "$HOME/.local/bin/song-key-export"
rm -f "$HOME/.local/bin/songkey-cli"
rm -rf "$DIR/.venv" "$DIR/.venv.backup"
rm -rf "$DIR/logs"
rm -f "$DIR/install.log"

echo "Song Key BPM is uninstalled. The logs folder was removed too; the app keeps nothing else of yours."
echo "You can delete this folder now if you want it gone."
