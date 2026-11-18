"""Shared test helpers: a fake /proc tree, fake meminfo, and a
detached victim process for the real-kill tests.
"""

import os
import subprocess
import sys
import time


def write_fake_proc(proc_root, pid, name, ppid=1, rss_kb=1024,
                    uid=1000, utime=0, stime=0):
    """Write /proc/PID/stat + status for one fake process."""
    pdir = os.path.join(proc_root, str(pid))
    os.makedirs(pdir, exist_ok=True)
    fields = ["R", str(ppid), "1", "1", "0", "0", "0", "0", "0",
              "0", "0", "0", str(utime), str(stime)]
    with open(os.path.join(pdir, "stat"), "w",
              encoding="utf-8") as fh:
        fh.write("%d (%s) %s\n" % (pid, name, " ".join(fields)))
    with open(os.path.join(pdir, "status"), "w",
              encoding="utf-8") as fh:
        fh.write("Name:\t%s\n" % name)
        fh.write("Uid:\t%d\t%d\t%d\t%d\n" % (uid, uid, uid, uid))
        fh.write("VmRSS:\t%d kB\n" % rss_kb)


FAKE_MEMINFO = """MemTotal:        8192000 kB
MemFree:         1024000 kB
MemAvailable:    5242880 kB
Buffers:          512000 kB
Cached:          2048000 kB
"""


def write_fake_meminfo(path, text=FAKE_MEMINFO):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


_VICTIM_CODE = """
import os, signal, sys, time
seconds = int(sys.argv[1])
ignore_term = len(sys.argv) > 2 and sys.argv[2] == "ignore-term"
pid = os.fork()
if pid > 0:
    print(pid, flush=True)
    os._exit(0)
os.setsid()
# Detach from the helper's pipes: the caller waits on the pipe
# for the printed PID, so a grandchild that keeps it open would
# hang that wait until the grandchild exits.
devnull = os.open(os.devnull, os.O_RDWR)
os.dup2(devnull, 0)
os.dup2(devnull, 1)
os.dup2(devnull, 2)
if devnull > 2:
    os.close(devnull)
if ignore_term:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
time.sleep(seconds)
"""


def spawn_detached_victim(seconds=60, ignore_term=False):
    """Spawn a process that is NOT in our process tree.

    A helper double-forks: the grandchild is reparented to init,
    so it is not our descendant and the killer's own-tree guard
    does not protect it. Returns the grandchild PID. The caller
    must stop it (or it exits after `seconds` on its own).
    """
    argv = [sys.executable, "-c", _VICTIM_CODE, str(seconds)]
    if ignore_term:
        argv.append("ignore-term")
    proc = subprocess.run(argv, capture_output=True, text=True,
                          timeout=30)
    if proc.returncode != 0:
        raise RuntimeError("victim helper failed: %s" % proc.stderr)
    return int(proc.stdout.strip())


def stop_pid(pid, timeout=5.0):
    """Best-effort stop of a leftover test process."""
    import signal
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _pid_exists(pid):
            return
        time.sleep(0.05)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def _pid_exists(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def assert_stopped(test_case, pid, timeout=5.0):
    """Assert a PID is gone or a zombie within `timeout`."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        stat_path = "/proc/%d/stat" % pid
        try:
            with open(stat_path, encoding="utf-8") as fh:
                raw = fh.read()
        except OSError:
            return  # gone entirely
        right = raw.rfind(")")
        fields = raw[right + 2:].split() if right >= 0 else []
        if fields and fields[0] == "Z":
            return  # zombie: already stopped, waiting to be reaped
        time.sleep(0.05)
    test_case.fail("PID %d is still running after %.1f seconds"
                   % (pid, timeout))
