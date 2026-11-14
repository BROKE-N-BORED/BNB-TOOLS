#!/usr/bin/env bash
# Repo Health Board launcher - opens the Repo Health Board window.
# With arguments it runs the command line instead (see
# repo-health-board-cli --help). No terminal needed.
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
  echo "Repo Health Board is not installed yet. Double-click Install Repo Health Board to install it." >&2
  exit 1
fi

# The window needs the interface toolkit; the command line does not.
# Guard the GUI launch with a plain-language message, never a
# traceback.
if [ "$#" -eq 0 ]; then
  if ! "$PY" -c "import PySide6.QtWidgets" 2>/dev/null; then
    echo "Repo Health Board is missing its interface toolkit. Double-click Install Repo Health Board to install it." >&2
    exit 1
  fi
  exec "$PY" -m board.gui_main
fi

exec "$PY" -m board "$@"
