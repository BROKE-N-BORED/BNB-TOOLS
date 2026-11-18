"""Kill: stop only the processes the user picked, and only
when told to, with guards that cannot be switched off.

Guards (every one test-enforced):
  - never PID 1;
  - never our own process or any of its ancestors or
    descendants (killing our own tree would kill the picker
    itself, or the shell that started it);
  - never kernel threads (parent 0 or 2, bracketed names);
  - never protected system names (systemd, the desktop, the
    display server, the login manager, ssh);
  - never a process owned by another user (we could not stop
    it without admin rights anyway);
  - never without an explicit confirm (the CLI --confirm flag,
    or the picker's confirmation dialog);
  - never more than the PIDs the user picked.

A kill is SIGTERM first, then SIGKILL after a short wait when
the process does not stop on its own. Dry-run mode reports
what would be stopped and touches nothing.
"""

import os
import signal
import time

# System processes stopping one of these would break the
# session or the machine, so they are never offered and never
# killed, even if a PID is handed in directly.
PROTECTED_NAMES = frozenset({
    "systemd", "init", "kthreadd", "cinnamon", "muffin",
    "Xorg", "X", "lightdm", "gdm", "gdm3", "sddm", "sshd",
})

TERM_WAIT_SECONDS = 3.0
POLL_SECONDS = 0.1


def _read_ppid(pid, proc_root):
    """A process's parent PID from /proc/PID/stat, or None."""
    try:
        with open(os.path.join(proc_root, str(pid), "stat"),
                  encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except (OSError, ValueError):
        return None
    right = raw.rfind(")")
    if right < 0:
        return None
    fields = raw[right + 2:].split()
    try:
        return int(fields[1])
    except (IndexError, ValueError):
        return None


def _read_name_uid(pid, proc_root):
    """(name, uid) for a PID, or (None, None) when gone."""
    try:
        with open(os.path.join(proc_root, str(pid), "stat"),
                  encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except (OSError, ValueError):
        return None, None
    left = raw.find("(")
    right = raw.rfind(")")
    name = raw[left + 1:right] if 0 <= left < right else None
    uid = None
    try:
        with open(os.path.join(proc_root, str(pid), "status"),
                  encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("Uid:"):
                    uid = int(line.split()[1])
                    break
    except (OSError, ValueError, IndexError):
        uid = None
    return name, uid


def _children_map(proc_root):
    """parent PID -> [child PIDs] for the whole table."""
    children = {}
    try:
        names = os.listdir(proc_root)
    except OSError:
        return children
    for name in names:
        if not name.isdigit():
            continue
        pid = int(name)
        ppid = _read_ppid(pid, proc_root)
        if ppid is not None:
            children.setdefault(ppid, []).append(pid)
    return children


def own_tree_pids(proc_root="/proc", own_pid=None):
    """Our own PID, our ancestors up to PID 1, and all our
    descendants. None of these may ever be killed."""
    if own_pid is None:
        own_pid = os.getpid()
    tree = {own_pid}
    pid = own_pid
    while pid and pid != 1:
        ppid = _read_ppid(pid, proc_root)
        if ppid is None or ppid in tree:
            break
        tree.add(ppid)
        pid = ppid
    children = _children_map(proc_root)
    stack = [own_pid]
    while stack:
        parent = stack.pop()
        for child in children.get(parent, ()):
            if child not in tree:
                tree.add(child)
                stack.append(child)
    return tree


def refusal_reason(pid, proc_root="/proc", uid=None,
                   own_tree=None):
    """Why PID must not be killed, or None when it may be.

    Returns a plain-words reason, or None. A process that is
    already gone is not a refusal: there is nothing to stop.
    """
    if pid == 1:
        return "PID 1 runs the whole system and cannot be stopped"
    if own_tree is None:
        own_tree = own_tree_pids(proc_root)
    if pid in own_tree:
        return ("PID %d is part of this tool or the shell that "
                "started it" % pid)
    name, owner_uid = _read_name_uid(pid, proc_root)
    if name is None:
        return None  # already gone: nothing to refuse
    ppid = _read_ppid(pid, proc_root)
    if ppid in (0, 2) or (name.startswith("[")
                          and name.endswith("]")):
        return "PID %d (%s) is a kernel thread" % (pid, name)
    if name in PROTECTED_NAMES:
        return ("PID %d (%s) is a system process and must keep "
                "running" % (pid, name))
    if uid is None:
        uid = os.getuid()
    if owner_uid is not None and owner_uid != uid:
        return ("PID %d (%s) runs as another user; stopping it "
                "needs admin rights" % (pid, name))
    return None


def _is_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _is_zombie(pid, proc_root):
    """A zombie has already stopped; waiting on it is pointless."""
    try:
        with open(os.path.join(proc_root, str(pid), "stat"),
                  encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except (OSError, ValueError):
        return True  # gone entirely: treat as stopped
    right = raw.rfind(")")
    if right < 0:
        return False
    fields = raw[right + 2:].split()
    return bool(fields) and fields[0] == "Z"


def kill_pids(pids, confirm=False, dry_run=False,
              term_wait=TERM_WAIT_SECONDS, proc_root="/proc",
              uid=None):
    """Stop the given PIDs, each guarded.

    Without confirm=True, every PID is refused: the CLI needs
    --confirm, the picker needs its confirmation dialog.
    With dry_run=True, nothing is touched: each killable PID
    reports 'would stop'.

    Returns a list of result dicts: pid, name, outcome
    ('stopped', 'would stop', 'refused', 'already stopped',
    'failed'), reason (plain words when refused or failed).
    """
    if uid is None:
        uid = os.getuid()
    own_tree = own_tree_pids(proc_root)
    results = []
    for pid in pids:
        name, _owner = _read_name_uid(pid, proc_root)
        display = name or ("PID %d" % pid)
        if not confirm and not dry_run:
            results.append({"pid": pid, "name": display,
                            "outcome": "refused",
                            "reason": "no confirmation given"})
            continue
        reason = refusal_reason(pid, proc_root, uid, own_tree)
        if reason is not None:
            results.append({"pid": pid, "name": display,
                            "outcome": "refused", "reason": reason})
            continue
        if name is None:
            results.append({"pid": pid, "name": display,
                            "outcome": "already stopped",
                            "reason": ""})
            continue
        if dry_run:
            results.append({"pid": pid, "name": display,
                            "outcome": "would stop", "reason": ""})
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            results.append({"pid": pid, "name": display,
                            "outcome": "already stopped",
                            "reason": ""})
            continue
        except PermissionError:
            results.append({"pid": pid, "name": display,
                            "outcome": "failed",
                            "reason": "not allowed to stop it"})
            continue
        except OSError as exc:
            results.append({"pid": pid, "name": display,
                            "outcome": "failed", "reason": str(exc)})
            continue
        deadline = time.time() + term_wait
        while time.time() < deadline:
            if not _is_alive(pid) or _is_zombie(pid, proc_root):
                break
            time.sleep(POLL_SECONDS)
        if _is_alive(pid) and not _is_zombie(pid, proc_root):
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            deadline = time.time() + term_wait
            while time.time() < deadline:
                if not _is_alive(pid) or _is_zombie(pid, proc_root):
                    break
                time.sleep(POLL_SECONDS)
        if _is_alive(pid) and not _is_zombie(pid, proc_root):
            results.append({"pid": pid, "name": display,
                            "outcome": "failed",
                            "reason": "it would not stop"})
        else:
            results.append({"pid": pid, "name": display,
                            "outcome": "stopped", "reason": ""})
    return results


def plain_report(results):
    """Kill results in plain words."""
    lines = []
    for result in results:
        if result["outcome"] == "stopped":
            lines.append("Stopped %s (PID %d)."
                         % (result["name"], result["pid"]))
        elif result["outcome"] == "would stop":
            lines.append("Would stop %s (PID %d)."
                         % (result["name"], result["pid"]))
        elif result["outcome"] == "already stopped":
            lines.append("%s (PID %d) had already stopped."
                         % (result["name"], result["pid"]))
        elif result["outcome"] == "refused":
            lines.append("Did not stop %s (PID %d): %s."
                         % (result["name"], result["pid"],
                            result["reason"]))
        else:
            lines.append("Could not stop %s (PID %d): %s."
                         % (result["name"], result["pid"],
                            result["reason"]))
    return "\n".join(lines) + "\n"
