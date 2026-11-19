#!/usr/bin/env bash
# AppImage Runner installer.
# Double-click "Install AppImage Runner.desktop" to run this - no terminal needed.
# Re-running it upgrades in place. bash install.sh also works.
#
# FUSE note: AppImages need the FUSE library to start. If it is
# missing this installer warns in plain words and keeps going:
# the tool still installs, files still get made runnable, and
# some AppImages may not start until FUSE is added. The warning
# is never a failure: the chmod step, the tool's first job, does
# not need FUSE at all.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

APP_NAME="AppImage Runner"
DESKTOP_SRC="$DIR/appimage-run-helper.desktop"
DESKTOP_DST="$HOME/.local/share/applications/appimage-run-helper.desktop"
DESKTOP_ICON="$HOME/Desktop/AppImage Runner.desktop"

# --- Pick a dialog tool (xenity is the installed one on this PC) -----------
DIALOG=""
for tool in xenity zenity yad; do
  if command -v "$tool" >/dev/null 2>&1; then
    DIALOG="$tool"
    break
  fi
done

HEADLESS=0
for arg in "$@"; do
  if [ "$arg" = "--headless" ]; then
    HEADLESS=1
  fi
done

log() { echo "[install] $*"; }

# A real display is one thing; whether a dialog tool can reach
# it is another. Test it: xenity can exit 0 with DISPLAY set but
# no session behind it, so a real test window decides. Returns 0
# when a dialog can actually show.
dialog_works() {
  [ "$HEADLESS" -eq 0 ] || return 1
  [ -n "$DIALOG" ] || return 1
  [ -n "${DISPLAY:-}" ] || return 1
  case "$DIALOG" in
    xenity) timeout 3 xenity --info --title="$APP_NAME" --text="Testing the installer window..." >/dev/null 2>&1 || return 1 ;;
    zenity) timeout 3 zenity --info --title="$APP_NAME" --text="Testing the installer window..." >/dev/null 2>&1 || return 1 ;;
    yad)    timeout 3 yad --title="$APP_NAME" --text="Testing the installer window..." --button=OK >/dev/null 2>&1 || return 1 ;;
  esac
  return 0
}

# Show a progress window while the installer works. Long
# installs (the first pip download) must never look frozen.
# PROGRESS_FD holds the write end; progress_update writes a
# percentage line plus a "# text" line (the zenity/xenity/yad
# pulsate protocol). progress_close ends it.
PROGRESS_FD=""
progress_start() {
  [ "$GUI_MODE" -eq 1 ] || return 0
  local fifo="$DIR/.install-progress.fifo"
  rm -f "$fifo"
  mkfifo "$fifo" || return 0
  case "$DIALOG" in
    xenity) xenity --progress --pulsate --title="$APP_NAME" --text="Installing..." --auto-close < "$fifo" >/dev/null 2>&1 & ;;
    zenity) zenity --progress --pulsate --title="$APP_NAME" --text="Installing..." --auto-close < "$fifo" >/dev/null 2>&1 & ;;
    yad)    yad --progress --title="$APP_NAME" --text="Installing..." --auto-close < "$fifo" >/dev/null 2>&1 & ;;
  esac
  # Open the fifo for writing without blocking (the reader is up).
  exec {PROGRESS_FD}>"$fifo"
  rm -f "$fifo"
}
progress_update() {
  [ -n "$PROGRESS_FD" ] || return 0
  printf '50\n# %s\n' "$1" >&"$PROGRESS_FD" 2>/dev/null || true
}
progress_close() {
  if [ -n "$PROGRESS_FD" ]; then
    exec {PROGRESS_FD}>&-
    PROGRESS_FD=""
  fi
}

# Failure path: plain-language message, log kept, exit 1.
# GUI dialog when one can really show, else stdout.
fail() {
  local msg="$1"
  progress_close
  log "FAILED: $msg"
  log "Install log: $DIR/install.log"
  if [ "$GUI_MODE" -eq 1 ]; then
    case "$DIALOG" in
      xenity) xenity --error --title="$APP_NAME" --text="$msg" >/dev/null 2>&1 || true ;;
      zenity) zenity --error --title="$APP_NAME" --text="$msg" >/dev/null 2>&1 || true ;;
      yad)    yad --title="$APP_NAME" --text="$msg" --button=OK >/dev/null 2>&1 || true ;;
    esac
  fi
  echo "$msg"
  exit 1
}

# --- Logging: keep a log file next to the installer -------------------------
exec > >(tee -a "$DIR/install.log") 2>&1
log "Installing $APP_NAME from $DIR"

GUI_MODE=0
if dialog_works; then
  GUI_MODE=1
fi
log "Dialog tool: ${DIALOG:-none} (GUI mode: $GUI_MODE)"

# --- Preconditions -----------------------------------------------------------
command -v python3 >/dev/null 2>&1 || fail "Python 3 was not found on this computer. Install Python 3 first, then run this installer again."

# FUSE check (warning only, never a failure): the runner itself
# works without FUSE. AppImages mount through FUSE when they
# start, so a missing fusermount means some AppImages will not
# start. The debug report checks this too.
if ! command -v fusermount >/dev/null 2>&1 && ! command -v fusermount3 >/dev/null 2>&1; then
  log "WARNING: the FUSE library was not found. Some AppImages need it to start."
  log "The tool is installed anyway: making files runnable works without it."
  log "If an AppImage will not start, install FUSE in the Software Manager (search for libfuse2)."
fi

progress_start
trap 'progress_close' EXIT

# --- Remember the previous install so an upgrade can restore it ------------
BACKUP_DIR=""
if [ -d "$DIR/.venv" ]; then
  BACKUP_DIR="$(mktemp -d)"
  cp -a "$DIR/.venv" "$BACKUP_DIR/venv"
  log "Upgrade: saved the previous install to restore if this one fails."
fi

restore_backup() {
  if [ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR/venv" ]; then
    log "Restoring the previous install."
    rm -rf "$DIR/.venv"
    cp -a "$BACKUP_DIR/venv" "$DIR/.venv"
  fi
}

# --- Create the virtual environment ------------------------------------------
if ! python3 -c "import venv, ensurepip" >/dev/null 2>&1; then
  # The venv module is missing (Linux Mint splits it into
  # python3-venv). Self-heal with pkexec: a GUI password prompt,
  # no terminal. If pkexec is unavailable or the user declines,
  # fall back to the plain message.
  healed=0
  if [ "$GUI_MODE" -eq 1 ] && command -v pkexec >/dev/null 2>&1; then
    log "Python venv support is missing. Asking for permission to install it (GUI password prompt)."
    if pkexec apt-get install -y python3-venv python3-full >/dev/null 2>&1 \
       && python3 -c "import venv, ensurepip" >/dev/null 2>&1; then
      healed=1
      log "python3-venv installed."
    fi
  fi
  if [ "$healed" -eq 0 ]; then
    restore_backup
    fail "Python 3 venv support is missing, and the automatic fix did not work. Ask for help installing python3-venv, then run this installer again."
  fi
fi

progress_update "Setting up the app environment..."
if ! python3 -m venv "$DIR/.venv" >>"$DIR/install.log" 2>&1; then
  restore_backup
  fail "Could not create the app environment. See install.log in this folder for details."
fi
VENV_PY="$DIR/.venv/bin/python"

# --- Install PySide6 into the venv -------------------------------------------
# Idempotent: pip checks what is already installed. Three
# attempts with plain progress text; the failure message never
# shows a traceback.
progress_update "Downloading the interface library (first install only, this can take a few minutes)..."
PIP_OK=0
for attempt in 1 2 3; do
  if "$VENV_PY" -m pip install --upgrade PySide6-Essentials PySide6-Addons >>"$DIR/install.log" 2>&1; then
    PIP_OK=1
    break
  fi
  log "pip attempt $attempt failed; retrying."
  progress_update "Download hiccup, retrying (attempt $attempt of 3)..."
  sleep 2
done
if [ "$PIP_OK" -eq 0 ]; then
  restore_backup
  fail "Could not download the interface library after 3 attempts. Check the internet connection, then run this installer again."
fi

# --- Warning probe: can Qt actually open a window here? ----------------------
# Offscreen, so this never shows a window. A failure names the
# missing system library in plain words. It is a warning, not a
# failure: the system libraries exist on the target PC even
# when a sandbox cannot load them.
progress_update "Checking the interface library..."
if ! QT_QPA_PLATFORM=offscreen "$VENV_PY" -c "from PySide6.QtWidgets import QApplication; QApplication([])" >/dev/null 2>"$DIR/.qt-probe.err"; then
  log "WARNING: the interface library probe failed on this machine:"
  sed 's/^/[install]   /' "$DIR/.qt-probe.err" 2>/dev/null || true
  log "The app is installed anyway. If the window will not open, a system library is missing; the error above names it."
fi
rm -f "$DIR/.qt-probe.err"

# --- Icon: render the menu PNGs from the SVG master ---------------------------
# assets/appimage.svg is the checked-in master. A fresh clone or
# zip has no PNGs (they are gitignored build products), so
# render them now with the venv python (QtSvg ships in Addons).
# Best effort: a render failure leaves the SVG in place and the
# menu entry falls back to a stock icon name.
progress_update "Drawing the app icon..."
if [ -f "$DIR/assets/appimage.svg" ] && [ ! -f "$DIR/assets/appimage.png" ]; then
  if QT_QPA_PLATFORM=offscreen "$VENV_PY" "$DIR/render_icons.py" "$DIR/assets" >>"$DIR/install.log" 2>&1; then
    log "Icon rendered: assets/appimage.png"
  else
    log "WARNING: the icon render failed; the menu entry will use a stock icon."
  fi
fi

# --- Final check: the package imports in the venv -----------------------------
progress_update "Final check..."
if ! PYTHONPATH="$DIR" "$VENV_PY" -c "import appimagehelper, appimagehelper.core, appimagehelper.cli" >>"$DIR/install.log" 2>&1; then
  restore_backup
  fail "The app files did not check out. See install.log in this folder for details."
fi

# --- Menu entry ----------------------------------------------------------------
mkdir -p "$HOME/.local/share/applications"
ICON_PATH="$DIR/assets/appimage.png"
if [ -f "$ICON_PATH" ]; then
  ICON_LINE="Icon=$ICON_PATH"
else
  ICON_LINE="Icon=system-run"
fi
{
  echo "[Desktop Entry]"
  echo "Type=Application"
  echo "Name=AppImage Runner"
  echo "Comment=Run an AppImage by clicking, no terminal"
  echo "Exec=\"$DIR/run.sh\""
  echo "$ICON_LINE"
  echo "Terminal=false"
  echo "Categories=Utility;"
} > "$DESKTOP_DST"
chmod +x "$DESKTOP_DST"
# Mark the menu entry trusted where the desktop shell supports it.
gio set "$DESKTOP_DST" metadata::trusted true >/dev/null 2>&1 || true
log "Menu entry written: $DESKTOP_DST"

# --- Desktop icon ----------------------------------------------------------------
if [ -d "$HOME/Desktop" ]; then
  cp "$DESKTOP_DST" "$DESKTOP_ICON"
  chmod +x "$DESKTOP_ICON"
  gio set "$DESKTOP_ICON" metadata::trusted true >/dev/null 2>&1 || true
  log "Desktop icon written: $DESKTOP_ICON"
fi

# --- Terminal commands on PATH ---------------------------------------------------
mkdir -p "$HOME/.local/bin"
ln -sf "$DIR/appimage-run" "$HOME/.local/bin/appimage-run"
ln -sf "$DIR/appimage-make-runnable" "$HOME/.local/bin/appimage-make-runnable"
ln -sf "$DIR/appimagehelper-cli" "$HOME/.local/bin/appimagehelper-cli"
log "Commands linked in ~/.local/bin: appimage-run, appimage-make-runnable, appimagehelper-cli"

progress_close
trap - EXIT
if [ -n "$BACKUP_DIR" ]; then
  rm -rf "$BACKUP_DIR"
fi

log "Done. AppImage Runner is ready: look for it in the menu or on the desktop."
if [ "$GUI_MODE" -eq 1 ]; then
  case "$DIALOG" in
    xenity) xenity --info --title="$APP_NAME" --text="AppImage Runner is installed. Look for AppImage Runner in your menu or on the desktop." >/dev/null 2>&1 || true ;;
    zenity) zenity --info --title="$APP_NAME" --text="AppImage Runner is installed. Look for AppImage Runner in your menu or on the desktop." >/dev/null 2>&1 || true ;;
    yad)    yad --title="$APP_NAME" --text="AppImage Runner is installed. Look for AppImage Runner in your menu or on the desktop." --button=OK >/dev/null 2>&1 || true ;;
  esac
fi
echo "AppImage Runner is installed. Look for AppImage Runner in your menu or on the desktop."
