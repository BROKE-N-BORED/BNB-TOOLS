#!/usr/bin/env bash
# Model Chat Smoke Test uninstaller - removes the app menu entry,
# desktop icon, command-line link, and the logs folder. There is no
# other user data: the tool keeps no settings or files of yours
# beyond its logs.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"

rm -f "$HOME/.local/share/applications/model-chat-smoke-test.desktop"
rm -f "$HOME/Desktop/Model Chat Smoke Test.desktop"
rm -f "$HOME/.local/bin/model-chat-smoke-test"
rm -rf "$DIR/logs"
rm -f "$DIR/install.log"

echo "Model Chat Smoke Test is uninstalled. The logs folder was removed too; the tool keeps nothing else of yours."
echo "You can delete this folder now if you want it gone."
