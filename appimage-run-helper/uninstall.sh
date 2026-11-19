#!/usr/bin/env bash
# AppImage Runner uninstaller.
# Run with: bash uninstall.sh
# Removes the menu entry, the desktop icon, the terminal command
# links, the venv, the debug logs, and the install log.
# It does NOT remove this folder itself, the settings in
# ~/.local/share/appimage-run-helper, or any AppImage file: it
# only undoes what install.sh created.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

rm -f "$HOME/.local/share/applications/appimage-run-helper.desktop"
rm -f "$HOME/Desktop/AppImage Runner.desktop"
rm -f "$HOME/.local/bin/appimage-run"
rm -f "$HOME/.local/bin/appimage-make-runnable"
rm -f "$HOME/.local/bin/appimagehelper-cli"
rm -rf "$DIR/.venv"
rm -rf "$HOME/.local/share/appimage-run-helper/logs"
rm -f "$DIR/install.log"

echo "AppImage Runner removed (menu entry, desktop icon, command links, environment, logs)."
echo "This folder and your settings in ~/.local/share/appimage-run-helper are still here; delete them by hand if you want them gone."
