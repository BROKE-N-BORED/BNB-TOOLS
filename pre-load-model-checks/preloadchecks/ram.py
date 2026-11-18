"""RAM check: does this model fit in free RAM.

Reads /proc/meminfo (MemAvailable, the memory actually free to
use). A model fits when free RAM covers the model size plus a
reserve kept back for the system (default 1 GB, overridable):
loading a model that eats every last byte will thrash, not run.

Sizes are 1024-based (1 GB = 1024 MB = 1024*1024 KB), matching
how /proc/meminfo counts. A plain number means GB.
"""

import os
import re

DEFAULT_RESERVE_BYTES = 1024 ** 3  # 1 GB kept back for the system

_SIZE_RE = re.compile(
    r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([kmgt]?b?)?\s*$",
    re.IGNORECASE)
_UNITS = {"": 1, "b": 1, "k": 1024, "kb": 1024,
          "m": 1024 ** 2, "mb": 1024 ** 2,
          "g": 1024 ** 3, "gb": 1024 ** 3,
          "t": 1024 ** 4, "tb": 1024 ** 4}


def parse_size(text):
    """Parse a size like '4.5GB', '4096 MB', '512', into bytes.

    A plain number means GB. Raises ValueError on bad input.
    """
    if isinstance(text, (int, float)):
        return int(text * 1024 ** 3)
    match = _SIZE_RE.match(str(text))
    if not match:
        raise ValueError("not a size: %r" % (text,))
    number, unit = match.groups()
    unit = (unit or "g").lower()
    return int(float(number) * _UNITS[unit])


def read_meminfo(path="/proc/meminfo"):
    """Parse /proc/meminfo into a dict of kB values."""
    values = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if ":" not in line:
                continue
            key, rest = line.split(":", 1)
            parts = rest.split()
            if not parts:
                continue
            try:
                values[key.strip()] = int(parts[0])
            except ValueError:
                continue
    return values


def available_bytes(meminfo=None, path="/proc/meminfo"):
    """Free RAM in bytes: MemAvailable, or MemFree + Buffers +
    Cached on kernels too old to report MemAvailable."""
    if meminfo is None:
        meminfo = read_meminfo(path)
    if "MemAvailable" in meminfo:
        return meminfo["MemAvailable"] * 1024
    return (meminfo.get("MemFree", 0)
            + meminfo.get("Buffers", 0)
            + meminfo.get("Cached", 0)) * 1024


def total_bytes(meminfo=None, path="/proc/meminfo"):
    """Total RAM in bytes."""
    if meminfo is None:
        meminfo = read_meminfo(path)
    return meminfo.get("MemTotal", 0) * 1024


def format_gb(nbytes):
    """Bytes as a short GB string: '4.5 GB', '512 MB' under 1 GB."""
    gb = nbytes / float(1024 ** 3)
    if gb >= 1:
        return "%.1f GB" % gb
    mb = nbytes / float(1024 ** 2)
    return "%d MB" % round(mb)


def check(required_bytes, reserve_bytes=DEFAULT_RESERVE_BYTES,
          meminfo=None, path="/proc/meminfo"):
    """The RAM verdict.

    Returns a dict: required, reserve, available, total, fits,
    shortfall (bytes missing when it does not fit, else 0).
    """
    available = available_bytes(meminfo, path)
    total = total_bytes(meminfo, path)
    needed = required_bytes + reserve_bytes
    fits = available >= needed
    return {
        "required": required_bytes,
        "reserve": reserve_bytes,
        "available": available,
        "total": total,
        "fits": fits,
        "shortfall": 0 if fits else needed - available,
    }


def plain_report(result):
    """The verdict in plain words."""
    lines = [
        "This model needs %s." % format_gb(result["required"]),
        "Free RAM: %s of %s total (%s kept back for the system)."
        % (format_gb(result["available"]),
           format_gb(result["total"]),
           format_gb(result["reserve"])),
    ]
    if result["fits"]:
        lines.append("It fits. You can load it.")
    else:
        lines.append(
            "It does not fit. You are short %s."
            % format_gb(result["shortfall"]))
        lines.append(
            "Close something first, or pick a smaller model.")
    return "\n".join(lines) + "\n"
