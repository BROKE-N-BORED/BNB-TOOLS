"""Conflicting-process check: what is running that will fight
the model for RAM and CPU.

Reads /proc directly (stdlib only, no `ps` needed). Each
process is sampled twice, a short interval apart, so its CPU
use is a real measurement, not a lifetime total. The top few
by conflict score are the ones that matter: the picker shows
at most 6, never the whole list.

Conflict score (a judgment call, documented here): RAM used in
MB, plus 100 MB per 1% of one CPU core. A process burning a
whole core counts like 10 GB of RAM pressure; a quiet 2 GB
process counts as 2 GB. RAM is the binding constraint when a
model loads, CPU second.
"""

import json
import os
import time

DEFAULT_LIMIT = 6
DEFAULT_SAMPLE_INTERVAL = 0.5
CPU_WEIGHT_MB = 100  # 1% of one core counts as 100 MB of pressure


def _read_stat(pid, proc_root):
    """Parse /proc/PID/stat: (name, ppid, utime_ticks, stime_ticks).

    The name sits in parentheses and may itself contain spaces
    or parentheses, so split on the LAST closing paren.
    Returns None when the process is gone or unreadable.
    """
    try:
        with open(os.path.join(proc_root, str(pid), "stat"),
                  encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except (OSError, ValueError):
        return None
    left = raw.find("(")
    right = raw.rfind(")")
    if left < 0 or right < 0 or right <= left:
        return None
    name = raw[left + 1:right]
    fields = raw[right + 2:].split()
    # fields[0] is state, fields[1] is ppid, fields[11] is
    # utime, fields[12] is stime (stat fields 3, 4, 14, 15).
    try:
        ppid = int(fields[1])
        utime = int(fields[11])
        stime = int(fields[12])
    except (IndexError, ValueError):
        return None
    return name, ppid, utime, stime


def _read_status(pid, proc_root):
    """Parse /proc/PID/status: (rss_kb, uid). None when gone."""
    try:
        with open(os.path.join(proc_root, str(pid), "status"),
                  encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except (OSError, ValueError):
        return None
    rss_kb = 0
    uid = None
    for line in text.splitlines():
        if line.startswith("VmRSS:"):
            parts = line.split()
            try:
                rss_kb = int(parts[1])
            except (IndexError, ValueError):
                rss_kb = 0
        elif line.startswith("Uid:"):
            parts = line.split()
            try:
                uid = int(parts[1])
            except (IndexError, ValueError):
                uid = None
    return rss_kb, uid


def _pids(proc_root):
    try:
        names = os.listdir(proc_root)
    except OSError:
        return []
    return sorted(int(name) for name in names if name.isdigit())


def is_kernel_thread(info):
    """Kernel threads have no user memory to free and cannot be
    stopped: parent is 0 or 2, or the name is bracketed."""
    return info["ppid"] in (0, 2) or (
        info["name"].startswith("[") and info["name"].endswith("]"))


def conflict_score(info):
    """RAM in MB plus CPU pressure (see module docstring)."""
    return info["rss_mb"] + info["cpu_percent"] * CPU_WEIGHT_MB


def collect(proc_root="/proc", sample_interval=DEFAULT_SAMPLE_INTERVAL,
            own_pid=None):
    """Snapshot every visible process with its RAM and CPU use.

    Two samples of CPU time, `sample_interval` seconds apart.
    Processes that vanish between samples are skipped. Returns
    a list of dicts: pid, name, ppid, uid, rss_mb, cpu_percent.
    """
    if own_pid is None:
        own_pid = os.getpid()
    try:
        hertz = os.sysconf("SC_CLK_TCK")
    except (AttributeError, OSError, ValueError):
        hertz = 100
    try:
        ncpu = os.cpu_count() or 1
    except OSError:
        ncpu = 1
    first = {}
    for pid in _pids(proc_root):
        stat = _read_stat(pid, proc_root)
        if stat is not None:
            first[pid] = stat
    if sample_interval > 0:
        time.sleep(sample_interval)
    out = []
    for pid, (name, ppid, utime0, stime0) in first.items():
        stat = _read_stat(pid, proc_root)
        status = _read_status(pid, proc_root)
        if stat is None or status is None:
            continue
        _name, _ppid, utime1, stime1 = stat
        rss_kb, uid = status
        if sample_interval > 0:
            cpu_seconds = (utime1 + stime1 - utime0 - stime0) / hertz
            cpu_percent = cpu_seconds / sample_interval / ncpu * 100.0
        else:
            cpu_percent = 0.0
        out.append({
            "pid": pid,
            "name": name,
            "ppid": ppid,
            "uid": uid,
            "rss_mb": rss_kb / 1024.0,
            "cpu_percent": max(0.0, cpu_percent),
        })
    return out


def top_conflicts(processes, limit=DEFAULT_LIMIT, uid=None,
                  exclude_pids=None, killable_only=False):
    """The top `limit` conflicting processes, heaviest first.

    Kernel threads and PID 1 are never listed: they cannot be
    stopped and are not the model's competition. `exclude_pids`
    (our own process tree) is never listed either. With
    killable_only, only processes owned by `uid` are listed.
    """
    exclude = set(exclude_pids or ())
    ranked = []
    for info in processes:
        if info["pid"] == 1 or info["pid"] in exclude:
            continue
        if is_kernel_thread(info):
            continue
        if killable_only and uid is not None and info["uid"] != uid:
            continue
        ranked.append(info)
    ranked.sort(key=conflict_score, reverse=True)
    return ranked[:limit]


def format_plain(processes, uid=None):
    """The top processes in plain words, one per line."""
    if not processes:
        return "Nothing heavy is running. The model has the machine to itself.\n"
    lines = ["The heaviest running processes:"]
    for info in processes:
        killable = uid is None or info["uid"] == uid
        lines.append(
            "  %s (PID %d): %.0f MB RAM, %.0f%% CPU%s"
            % (info["name"], info["pid"], info["rss_mb"],
               info["cpu_percent"],
               "" if killable else " (runs as another user, cannot stop it)"))
    lines.append(
        "Stop the ones you do not need before loading the model.")
    return "\n".join(lines) + "\n"


def format_json(processes):
    """The top processes as JSON (rounded for readability)."""
    slim = [{
        "pid": info["pid"],
        "name": info["name"],
        "rss_mb": round(info["rss_mb"], 1),
        "cpu_percent": round(info["cpu_percent"], 1),
    } for info in processes]
    return json.dumps(slim, indent=2) + "\n"
