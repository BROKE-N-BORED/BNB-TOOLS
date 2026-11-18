#!/usr/bin/env bash
# Model Chat Smoke Test installer - double-click "Install Model Chat
# Smoke Test" or run: bash install.sh
#
# Standard library only, so there is nothing to download and no
# private tools folder: the installer checks Python 3, writes the
# app-menu launcher and desktop icon, links the command onto PATH,
# and verifies the install works before reporting success.
#
# The installer is a real window when a dialog tool is installed
# (xenity, zenity, or yad): a progress window, then a success dialog,
# or a plain-language error dialog with the log path on failure.
# Without a dialog tool it runs in the terminal instead - the
# documented degraded path, not the plan.
#
# No terminal command appears in any user-facing message.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
# Resolve symlinks, so installing through a link still finds this folder.
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
cd "$DIR"

LOG="$DIR/install.log"
INSTALL_OK=0

# Progress lines for the dialog tool: a bare number sets the percent,
# a "# ..." line sets the step text. Other log lines are ignored by
# the progress window and still land in install.log.
progress() {
  echo "$1"
  echo "# $2"
}

fail() {
  echo "ERROR: $1" >&2
  exit 1
}

do_install() {
  # All install output goes to install.log in the install folder.
  exec > >(tee -a "$LOG") 2>&1

  echo "Installing Model Chat Smoke Test from $DIR ..."
  progress 10 "Checking Python..."

  if ! command -v python3 >/dev/null 2>&1; then
    fail "Python 3 was not found on this computer, so the install cannot continue."
  fi

  progress 40 "Checking the tool runs..."
  if ! python3 "$DIR/model_chat_smoke_test.py" --version >/dev/null 2>&1; then
    fail "Model Chat Smoke Test did not start. The install folder may be incomplete."
  fi

  progress 60 "Adding the app menu entry..."
  # App-menu launcher (absolute paths - no quoting tricks needed).
  # NOTE: Exec= is quoted, Icon= must NOT be quoted. GLib strips
  # quotes from Exec= but NOT from Icon=, so a quoted Icon= shows
  # the generic gear icon. Terminal=true: this is a command-line
  # tool, so the icon opens a terminal showing what it does.
  mkdir -p "$HOME/.local/share/applications"
  cat > "$HOME/.local/share/applications/model-chat-smoke-test.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Model Chat Smoke Test
Comment=Run a canned chat through each model and report pass or fail
Exec="$DIR/show-help.sh"
Icon=utilities-terminal
Terminal=true
Categories=Utility;
StartupNotify=false
EOF

  # Desktop copy for double-click launch from the desktop too.
  # Cinnamon/Nemo refuse to launch an untrusted .desktop file, so the
  # copy is made executable AND marked trusted.
  if [ -d "$HOME/Desktop" ]; then
    cp "$HOME/.local/share/applications/model-chat-smoke-test.desktop" \
       "$HOME/Desktop/Model Chat Smoke Test.desktop" 2>/dev/null || true
    chmod +x "$HOME/Desktop/Model Chat Smoke Test.desktop" 2>/dev/null || true
    if command -v gio >/dev/null 2>&1; then
      gio set "$HOME/Desktop/Model Chat Smoke Test.desktop" \
        metadata::trusted true 2>/dev/null || true
    fi
  fi

  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications" \
      >/dev/null 2>&1 || true
  fi

  progress 80 "Adding the command..."
  # Command line on PATH after install.
  mkdir -p "$HOME/.local/bin"
  ln -sf "$DIR/model_chat_smoke_test.py" \
    "$HOME/.local/bin/model-chat-smoke-test"

  progress 95 "Final check..."
  if ! "$HOME/.local/bin/model-chat-smoke-test" --version >/dev/null 2>&1; then
    fail "The command did not start after install."
  fi

  progress 100 "Done."
  echo "Model Chat Smoke Test is installed. Open it from the app menu (Model Chat Smoke Test) or double-click Model Chat Smoke Test on the desktop to see what it does. No terminal needed."
  INSTALL_OK=1
}

dialog_tool() {
  # Cinnamon's probe order: xenity is Mint's maintained Zenity fork.
  for tool in xenity zenity yad; do
    if command -v "$tool" >/dev/null 2>&1; then
      echo "$tool"
      return 0
    fi
  done
  return 1
}

# --- entry point ---
if [ "${1:-}" = "--headless" ]; then
  do_install
  exit 0
fi

TOOL="$(dialog_tool || true)"
if [ -n "$TOOL" ]; then
  if bash "$0" --headless | "$TOOL" --progress \
      --title="Installing Model Chat Smoke Test" \
      --text="Starting..." --percentage=0 --auto-close; then
    "$TOOL" --info --title="Model Chat Smoke Test" \
      --text="Model Chat Smoke Test is installed. Open it from the app menu or the desktop icon to see what it does." \
      || true
  else
    "$TOOL" --error --title="Model Chat Smoke Test" \
      --text="The install did not finish. The log is at $LOG" \
      || true
    exit 1
  fi
else
  # No dialog tool installed: terminal install, the documented
  # degraded path.
  do_install
fi
