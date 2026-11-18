"""Watchdog: never hang silently when a model goes quiet.

Wraps a command (usually the model load) and watches its
output. If nothing is printed for `quiet_seconds`, the command
is stopped and the wrapper says so in plain words, instead of
sitting silent forever. Output passes through live, and the
command's own exit code passes through untouched when it
finishes on its own.

Exit codes: the command's code when it finishes; 124 when the
watchdog stops it for going quiet; 2 for a usage error.

Note: a wrapped program that buffers its output looks quiet
even while it works. Run Python programs unbuffered
(`python3 -u`) under the watchdog, or flush after each line.
"""

import os
import select
import signal
import subprocess
import sys
import time

QUIET_KILLED_EXIT = 124
TERM_WAIT_SECONDS = 3.0


def run(argv, quiet_seconds, out=None):
    """Run argv under the watchdog.

    Returns the exit code: the command's own code, or 124 when
    stopped for going quiet. `out` is the stream output is
    passed to (stdout by default).
    """
    if out is None:
        out = sys.stdout
    try:
        proc = subprocess.Popen(
            argv, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, bufsize=0,
            start_new_session=True)
    except OSError as exc:
        print("Could not start %s: %s"
              % (argv[0] if argv else "the command",
                 exc.strerror or exc), file=sys.stderr)
        return 2
    fd = proc.stdout.fileno()
    last_output = time.time()
    killed_quiet = False
    while True:
        if proc.poll() is not None:
            break
        ready, _w, _x = select.select([fd], [], [], 0.2)
        if ready:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                chunk = b""
            if chunk:
                out.write(chunk.decode("utf-8", "replace"))
                out.flush()
                last_output = time.time()
                continue
            # Pipe closed but the process is still listed as
            # running: give it a moment, then re-check.
            if proc.poll() is not None:
                break
        if time.time() - last_output >= quiet_seconds:
            killed_quiet = True
            break
    if killed_quiet:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            proc.wait(timeout=TERM_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            try:
                proc.wait(timeout=TERM_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
                pass
        # Drain whatever it printed before dying.
        try:
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                out.write(chunk.decode("utf-8", "replace"))
            out.flush()
        except OSError:
            pass
        print("Stopped: the command went quiet for %d second%s "
              "with no output, so it was stopped instead of "
              "hanging silently." % (quiet_seconds,
                                     "" if quiet_seconds == 1
                                     else "s"),
              file=sys.stderr)
        return QUIET_KILLED_EXIT
    # Finished on its own: drain the rest of the output.
    try:
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            out.write(chunk.decode("utf-8", "replace"))
        out.flush()
    except OSError:
        pass
    return proc.returncode
