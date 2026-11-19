"""AppImage Runner: run an AppImage by clicking, no terminal.

Drop an AppImage on the window (or pick the file) and press Run
it. The tool makes the file runnable, then runs it. The chain is
small tools: make-runnable sets the exec bit, launch makes it
runnable and runs it, view shows it in a window.
"""

__version__ = "0.1.0"
APP_NAME = "AppImage Runner"
APP_SLUG = "appimage-run-helper"
