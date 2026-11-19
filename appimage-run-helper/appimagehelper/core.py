"""Core: make an AppImage runnable, then run it.

Two small steps, each its own function, each returning a plain
result dict the CLI and the window both read:

- make_runnable(path): add the exec bit (what ticking "Allow
  executing file as program" does in the file manager). A file
  that is already runnable is a success, not an error.
- launch(path): make it runnable, then run it detached, so the
  app keeps running after this tool closes. A short settle wait
  catches the common failure: the app dying the moment it
  starts.

Every failure is an AppImageError with plain words, never a
traceback. The module uses the standard library only, so the
command line works with no interface toolkit installed.
"""

import os
import subprocess
import time

# How long launch waits after starting the app before checking
# whether it is still alive. Long enough to catch an instant
# failure (a missing library, a bad file), short enough that the
# window never feels stuck.
LAUNCH_SETTLE_SECONDS = 0.3


class AppImageError(Exception):
    """A plain-words failure: the step could not run or finish."""


def is_appimage_name(path):
    """True when the file name ends in .AppImage (any case).

    A name check only, never a gate: plenty of AppImages carry no
    extension, and the tool runs whatever file the user picks. The
    window uses this to warn, not to refuse.
    """
    return os.path.basename(path).lower().endswith(".appimage")


def _regular_file(path):
    """The absolute path of this regular file, or raise."""
    full = os.path.abspath(path)
    if not os.path.exists(full):
        raise AppImageError("There is no file at %s." % path)
    if os.path.isdir(full):
        raise AppImageError("%s is a folder, not a file." % path)
    if not os.path.isfile(full):
        raise AppImageError("%s is not a regular file." % path)
    return full


def _mode_string(mode):
    return "0o%o" % mode


def make_runnable(path):
    """Add the exec bit to this file.

    Returns {"path": absolute path, "already": bool,
    "mode": "0o755"-style mode string, "error": None}.
    "already" is True when the file was runnable before this
    call. Raises AppImageError when the file cannot be found,
    is not a regular file, or the bit cannot be set.
    """
    full = _regular_file(path)
    try:
        old_mode = os.stat(full).st_mode
    except OSError as exc:
        raise AppImageError(
            "Could not read %s: %s" % (path, exc.strerror or exc))
    already = bool(old_mode & 0o111)
    new_mode = old_mode | 0o111
    if not already:
        try:
            os.chmod(full, new_mode)
        except OSError as exc:
            raise AppImageError(
                "Could not make %s runnable: %s"
                % (path, exc.strerror or exc))
        try:
            new_mode = os.stat(full).st_mode
        except OSError:
            pass
    return {"path": full, "already": already,
            "mode": _mode_string(new_mode & 0o777),
            "error": None}


def launch(path, settle=LAUNCH_SETTLE_SECONDS):
    """Make this file runnable, then run it detached.

    Returns {"path": absolute path, "made_runnable": bool,
    "already": bool, "pid": int or None, "running": bool,
    "finished": bool, "error": None}. "running" means the app was
    still alive after the settle wait; "finished" means it ran
    and exited cleanly in that time (a short helper, not a
    windowed app). Raises AppImageError when the file cannot be
    made runnable, cannot start, or stops right away with an
    error.
    """
    made = make_runnable(path)
    full = made["path"]
    try:
        proc = subprocess.Popen(
            [full], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, close_fds=True)
    except PermissionError:
        raise AppImageError(
            "%s would not start: permission denied. The file may "
            "sit on a drive that does not allow running programs."
            % path)
    except FileNotFoundError:
        raise AppImageError(
            "%s disappeared before it could start." % path)
    except OSError as exc:
        if exc.errno == 8:  # Exec format error
            raise AppImageError(
                "%s is not a program the computer can run."
                % path)
        raise AppImageError(
            "%s would not start: %s"
            % (path, exc.strerror or exc))
    if settle > 0:
        time.sleep(settle)
    code = proc.poll()
    if code is None:
        return {"path": full,
                "made_runnable": not made["already"],
                "already": made["already"],
                "pid": proc.pid, "running": True,
                "finished": False, "error": None}
    if code == 0:
        return {"path": full,
                "made_runnable": not made["already"],
                "already": made["already"],
                "pid": proc.pid, "running": False,
                "finished": True, "error": None}
    raise AppImageError(
        "%s stopped right away (exit %d). It may need a library "
        "this computer does not have." % (path, code))
