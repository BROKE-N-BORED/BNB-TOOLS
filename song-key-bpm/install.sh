#!/usr/bin/env bash
# Song Key BPM installer - double-click "Install Song Key BPM"
# or run: bash install.sh
#
# Installs PySide6, aubio, miniaudio, and numpy into a private
# .venv (Mint's Python is externally managed, so no --user pip),
# writes the app-menu launcher, and verifies the install works
# before reporting success.
#
# The installer is a real window when a dialog tool is installed
# (xenity, zenity, or yad): a progress window, then a success dialog
# asking "Open it now?", or a plain-language error dialog with the
# log path on failure. Without a dialog tool it runs in the terminal
# instead - the documented degraded path, not the plan.
#
# No terminal command appears in any user-facing message. The
# installer heals its own missing system prerequisite (python3-venv)
# with one pkexec call instead of asking the user to type anything.
#
# Parallel work is capped for an 8 GB machine: PySide6, aubio,
# miniaudio, and numpy ship wheels only, so there is no compile
# step at all - the only heavy step is the download, which runs
# as one job.
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
BACKUP_DIR=""
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

# --- upgrade backup: the previous install is put back on failure ---
restore_backup() {
  if [ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR" ]; then
    rm -rf "$DIR/.venv"
    mv "$BACKUP_DIR" "$DIR/.venv"
    echo "The previous install was put back." >&2
  fi
}

cleanup_backup() {
  if [ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR" ]; then
    rm -rf "$BACKUP_DIR"
  fi
}

on_exit() {
  code=$?
  if [ "$INSTALL_OK" = "1" ]; then
    cleanup_backup
    return
  fi
  if [ "$code" -ne 0 ]; then
    restore_backup
  fi
}
trap on_exit EXIT

venv_ok() {
  [ -x "$DIR/.venv/bin/python" ] && \
    "$DIR/.venv/bin/python" -c \
      "import PySide6.QtWidgets, PySide6.QtSvg, aubio, miniaudio, numpy" 2>/dev/null
}

pip_install_deps() {
  # Retry the big download up to 3 times. A failed try leaves its
  # partial download in pip's cache, so the next try picks up where
  # the last one got to instead of starting over from scratch.
  # Every package ships wheels - no compile step, no compiler
  # needed on his PC.
  echo "Downloading the interface toolkit and the audio tools (one-time, about 160 MB)..."
  tries=0
  until "$DIR/.venv/bin/python" -m pip install \
      PySide6-Essentials PySide6-Addons aubio miniaudio numpy; do
    tries=$((tries + 1))
    if [ "$tries" -ge 3 ]; then
      fail "the download failed 3 times. Check the network and run the installer again; the next try resumes from the cache instead of starting over."
    fi
    echo "Download interrupted, trying again ($tries of 3)..."
    sleep 2
  done
  echo "Toolkit downloaded."
}

do_install() {
  # All install output goes to install.log in the install folder.
  exec > >(tee -a "$LOG") 2>&1

  echo "Installing Song Key BPM from $DIR ..."
  progress 5 "Checking Python..."

  if ! command -v python3 >/dev/null 2>&1; then
    fail "Python 3 was not found on this computer, so the install cannot continue."
  fi

  # Private venv (never touches system Python).
  if venv_ok; then
    echo "The tools from the last install are still good; reusing them."
  elif [ -x "$DIR/.venv/bin/python" ]; then
    progress 10 "Fixing the tools folder..."
    echo "The tools folder exists but is missing pieces; repairing it..."
    pip_install_deps
  else
    if [ -d "$DIR/.venv" ]; then
      BACKUP_DIR="$DIR/.venv.backup"
      rm -rf "$BACKUP_DIR"
      mv "$DIR/.venv" "$BACKUP_DIR"
      echo "Backed up the previous install."
    fi
    progress 10 "Setting up the private tools folder..."
    if ! python3 -m venv "$DIR/.venv"; then
      rm -rf "$DIR/.venv"
      # Self-heal: install the one missing system package with a
      # single GUI password prompt, then retry once.
      echo "The tools folder needs one system package; asking for permission to install it..."
      if command -v pkexec >/dev/null 2>&1 && \
         pkexec apt-get install -y python3-venv; then
        python3 -m venv "$DIR/.venv" || \
          fail "the tools folder still could not be created after installing the missing package."
      else
        fail "this install needs one system package. Re-run the installer and allow it when asked."
      fi
    fi
    echo "Setting up Song Key BPM's Python tools..."
    "$DIR/.venv/bin/python" -m pip install --upgrade pip
    progress 25 "Downloading the interface toolkit..."
    pip_install_deps
  fi

  progress 70 "Checking the install..."
  # Fatal check: the GUI toolkit and the audio tools must import,
  # or the install failed.
  if ! venv_ok; then
    fail "the interface toolkit installed but cannot be imported. Try again with a network connection, or check disk space."
  fi

  # Warning check: can the GUI actually start on this machine's
  # system libraries? Names the missing library instead of failing
  # cryptically later.
  if ! QT_QPA_PLATFORM=offscreen "$DIR/.venv/bin/python" -c \
      "from PySide6.QtWidgets import QApplication; QApplication([])" \
      2>"$DIR/.qt-probe.err"; then
    missing="$(grep -o "lib[a-zA-Z0-9_.-]*\.so[^ ]*" "$DIR/.qt-probe.err" | head -n 1 || true)"
    rm -f "$DIR/.qt-probe.err"
    if [ -n "$missing" ]; then
      echo "WARNING: the window may not open on this computer: the system library $missing is missing." >&2
    else
      echo "WARNING: the window could not be started in a test run; it may still open normally." >&2
    fi
  else
    rm -f "$DIR/.qt-probe.err"
  fi

  progress 80 "Making the app icon..."
  # Icon PNGs: the release zip ships them, but a fresh clone has only
  # the SVG - render them now so the launcher never points at a
  # missing file. A failed render only warns: the app still works,
  # the icon just falls back to the system default.
  if [ ! -f "$DIR/assets/songkey.png" ]; then
    if ! QT_QPA_PLATFORM=offscreen "$DIR/.venv/bin/python" \
        "$DIR/render_icons.py" >/dev/null 2>&1; then
      echo "WARNING: could not render the app icon from assets/songkey.svg." >&2
    fi
  fi

  progress 90 "Adding the app menu entry..."
  # App-menu launcher (absolute paths - no quoting tricks needed).
  # NOTE: Exec= is quoted, Icon= must NOT be quoted. GLib strips
  # quotes from Exec= but NOT from Icon=, so a quoted Icon= shows
  # the generic gear icon.
  mkdir -p "$HOME/.local/share/applications"
  cat > "$HOME/.local/share/applications/song-key-bpm.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Song Key BPM
Comment=Find the key and BPM of your songs
Exec="$DIR/run.sh"
Icon=$DIR/assets/songkey.png
Terminal=false
Categories=Utility;
StartupWMClass=Song Key BPM
StartupNotify=false
EOF

  # Desktop copy for double-click launch from the desktop too.
  # Cinnamon/Nemo refuse to launch an untrusted .desktop file, so the
  # copy is made executable AND marked trusted.
  if [ -d "$HOME/Desktop" ]; then
    cp "$HOME/.local/share/applications/song-key-bpm.desktop" \
       "$HOME/Desktop/Song Key BPM.desktop" 2>/dev/null || true
    chmod +x "$HOME/Desktop/Song Key BPM.desktop" 2>/dev/null || true
    if command -v gio >/dev/null 2>&1; then
      gio set "$HOME/Desktop/Song Key BPM.desktop" \
        metadata::trusted true 2>/dev/null || true
    fi
  fi

  # Command line on PATH after install: the window launcher, the
  # full command, and the two one-job commands, each runnable
  # alone from anywhere.
  mkdir -p "$HOME/.local/bin"
  ln -sf "$DIR/song-key-bpm" "$HOME/.local/bin/song-key-bpm"
  ln -sf "$DIR/songkey-cli" "$HOME/.local/bin/songkey-cli"
  ln -sf "$DIR/song-key-analyze" "$HOME/.local/bin/song-key-analyze"
  ln -sf "$DIR/song-key-export" "$HOME/.local/bin/song-key-export"

  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications" \
      >/dev/null 2>&1 || true
  fi

  progress 95 "Final check..."
  # Final check: Song Key BPM itself must import.
  if ! "$DIR/.venv/bin/python" -c \
      "import songkey; print(songkey.__version__)" 2>/dev/null; then
    fail "Song Key BPM did not start after install."
  fi

  progress 100 "Done."
  echo "Song Key BPM is installed. Open it from the app menu (Song Key BPM) or double-click Song Key BPM on the desktop. No terminal needed."
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
      --title="Installing Song Key BPM" \
      --text="Starting..." --percentage=0 --auto-close; then
    if "$TOOL" --question --title="Song Key BPM" \
        --text="Song Key BPM is installed. Open it now?"; then
      (bash "$DIR/run.sh" >/dev/null 2>&1 &)
    fi
  else
    "$TOOL" --error --title="Song Key BPM" \
      --text="The install did not finish. The log is at $LOG" \
      || true
    exit 1
  fi
else
  # No dialog tool installed: terminal install, the documented
  # degraded path.
  do_install
fi
