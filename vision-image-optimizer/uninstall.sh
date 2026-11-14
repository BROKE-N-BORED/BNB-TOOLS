#!/usr/bin/env bash
# Vision Image Optimizer uninstaller — removes the app menu entry,
# desktop icon, command-line link, and the private tools folder.
# Your pictures, settings, and cache are left alone unless you pass
# --remove-data.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"

REMOVE_DATA=0
if [ "${1:-}" = "--remove-data" ]; then
  REMOVE_DATA=1
fi

rm -f "$HOME/.local/share/applications/vision-image-optimizer.desktop"
rm -f "$HOME/Desktop/Vision Image Optimizer.desktop"
rm -f "$HOME/.local/bin/vision-image-optimizer"
rm -rf "$DIR/.venv" "$DIR/.venv.backup"

if [ "$REMOVE_DATA" = "1" ]; then
  rm -rf "$HOME/.config/vision-image-optimizer"
  rm -rf "$HOME/.cache/vision-image-optimizer"
  echo "Vision Image Optimizer is uninstalled, including its settings and cache."
else
  echo "Vision Image Optimizer is uninstalled. Your settings and cache were left alone."
fi
echo "You can delete this folder now if you want it gone."
