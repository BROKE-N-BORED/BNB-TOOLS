#!/usr/bin/env bash
# AppImage Runner launcher - opens the AppImage Runner window.
# With arguments it runs the command line instead (see
# appimagehelper-cli --help). No terminal needed.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
# Resolve symlinks, so launching through a link still finds this folder.
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
cd "$DIR"

if [ -x "$DIR/.venv/bin/python" ]; then
  PY="$DIR/.venv/bin/python"
else
  echo "AppImage Runner is not installed yet. Double-click Install AppImage Runner to install it." >&2
  exit 1
fi

# The window needs the interface toolkit; the command line does not.
# Guard the GUI launch with a plain-language message, never a
# traceback.
if [ "$#" -eq 0 ]; then
  if ! "$PY" -c "import PySide6.QtWidgets" 2>/dev/null; then
    echo "AppImage Runner is missing its interface toolkit. Double-click Install AppImage Runner to install it." >&2
    exit 1
  fi
  exec "$PY" -m appimagehelper.gui_main
fi

exec "$PY" -m appimagehelper "$@"
