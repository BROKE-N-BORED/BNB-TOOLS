#!/usr/bin/env bash
# OCR Reader uninstaller - removes the app menu entry,
# desktop icon, command-line links, private tools folder, and the
# logs folder. Text files you saved with the app stay exactly
# where you saved them: the uninstaller never touches them.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"

rm -f "$HOME/.local/share/applications/ocr-reader.desktop"
rm -f "$HOME/Desktop/OCR Reader.desktop"
rm -f "$HOME/.local/bin/ocr-reader"
rm -f "$HOME/.local/bin/ocr-read"
rm -f "$HOME/.local/bin/ocr-clean"
rm -f "$HOME/.local/bin/ocrreader-cli"
rm -rf "$DIR/.venv" "$DIR/.venv.backup"
rm -rf "$DIR/logs"
rm -f "$DIR/install.log"

echo "OCR Reader is uninstalled. The logs folder was removed too; any text files you saved stay where they are."
echo "You can delete this folder now if you want it gone."
