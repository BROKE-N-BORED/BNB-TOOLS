#!/usr/bin/env python3
"""Local CI (BNB-TOOLS T28) - a repo-agnostic pre-push check.

GitHub Actions is billing-locked account-wide, so no repo has
push-time CI. This tool is the free replacement, extracted from
the first proven instance: Forge Browser v0.9 item J1
(ci/check.sh + CI-STATUS.md). It runs locally, no runners, no
account, nothing that can be billing-locked - and it checks more
than Actions ever did (Actions ran only the suite).

What it checks, before a push:
  1. The full test suite (configurable command, under timeout).
  2. A throwaway Release-shaped zip build from the tree, with
     stored modes verified by reopening the zip (T1 mode rules:
     0o100755 for executables, 0o100644 for plain files,
     0o40755 for directories, file-type bits included).
  3. Stored modes on disk: every named executable must carry
     its exec bit in the tree.
  4. Doc counts: configurable counts (files, dirs, lines, regex
     matches) with optional expected/min/max assertions.

The verdict goes to CI-STATUS.md at the repo root (commit, date,
per-check pass/fail, counts, timing, repo size), so the repo page
itself shows the last result. The script exits 0 only when
everything passed, non-zero on any failure - a red repo never
ships.

Usage:
  python3 local_ci.py check [--repo PATH] [--config PATH]
  python3 local_ci.py setup <target-repo> [--force]
  python3 local_ci.py --help

`setup` installs this script plus a starter config into a repo
as ci/local_ci.py, ci/check.sh, and ci/config.json. From then on
the repo runs it as `sh ci/check.sh` (the J1 shape). The
installed copy is self-contained: one file, Python standard
library only, no network.

Config lives at <repo>/ci/config.json. Missing config degrades
to defaults with a plain message. See config.example.json and
config.schema.json for every key.
"""

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

VERSION = "0.1.0"

# ---------------------------------------------------------------- config

KNOWN_KEYS = {
    "project",
    "suite_command",
    "suite_timeout",
    "suite_count_pattern",
    "zip",
    "zip_top",
    "zip_executables",
    "zip_executable_globs",
    "zip_executables_file",
    "zip_exclude_dirs",
    "zip_exclude_suffixes",
    "mode_check",
    "doc_counts",
    "status_file",
    "tmp_base",
}

DEFAULT_SUITE_COMMAND = ["python3", "-m", "unittest", "discover",
                         "-s", "tests"]
DEFAULT_SUITE_TIMEOUT = 280
DEFAULT_SUITE_COUNT_PATTERN = r"Ran (\d+) tests?"
# T1's default executable list, kept in sync with
# ship-pipeline-scripts: named scripts plus shell/desktop globs.
DEFAULT_ZIP_EXECUTABLES = ["run.sh", "install.sh", "browser-setup.sh",
                            "install-gui.py", "uninstall.sh"]
DEFAULT_ZIP_EXECUTABLE_GLOBS = ["*.sh", "*.desktop"]
DEFAULT_ZIP_EXCLUDE_DIRS = ["__pycache__", ".git", ".venv",
                            "node_modules", ".forge"]
# .zip is excluded: the check zip is a throwaway, and nesting a
# Release zip inside it adds nothing but bytes.
DEFAULT_ZIP_EXCLUDE_SUFFIXES = [".pyc", ".pyo", ".zip"]
DEFAULT_STATUS_FILE = "CI-STATUS.md"

CHECK_SH_TEMPLATE = """#!/bin/sh
# Free CI entry point - runs the vendored local-ci check.
# Installed by BNB-TOOLS T28 local-ci (setup). Usage:
#   sh ci/check.sh        (from anywhere; the check finds the repo)
DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$DIR/local_ci.py" check --repo "$DIR/.."
"""


class ConfigError(Exception):
    """A config problem: broken JSON, an unknown key, or a bad value."""


def default_config(repo):
    """The config a repo gets when ci/config.json is absent."""
    name = os.path.basename(os.path.abspath(repo))
    return {
        "project": name,
        "suite_command": None,
        "suite_timeout": DEFAULT_SUITE_TIMEOUT,
        "suite_count_pattern": DEFAULT_SUITE_COUNT_PATTERN,
        "zip": True,
        "zip_top": name,
        "zip_executables": list(DEFAULT_ZIP_EXECUTABLES),
        "zip_executable_globs": list(DEFAULT_ZIP_EXECUTABLE_GLOBS),
        "zip_executables_file": None,
        "zip_exclude_dirs": list(DEFAULT_ZIP_EXCLUDE_DIRS),
        "zip_exclude_suffixes": list(DEFAULT_ZIP_EXCLUDE_SUFFIXES),
        "mode_check": True,
        "doc_counts": [],
        "status_file": DEFAULT_STATUS_FILE,
        "tmp_base": None,
        # Internal: True only when the config file itself listed
        # zip_executables (see load_config).
        "_zip_executables_explicit": False,
    }


def load_config(repo, config_path=None):
    """(config, used_defaults): load ci/config.json, or defaults.

    A missing config file degrades to defaults with a plain
    message - a repo with a standard layout needs almost no
    config. A broken config, or an unknown key, is an error:
    a mistyped key silently ignored would mean the check you
    think is running is not the check running. Keys starting
    with "_" are comment keys and are ignored.
    """
    if config_path is None:
        config_path = os.path.join(repo, "ci", "config.json")
    if not os.path.isfile(config_path):
        print("no ci/config.json found, using defaults "
              "(run `local_ci.py setup` to install a starter config)")
        return default_config(repo), True
    try:
        with open(config_path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError) as exc:
        raise ConfigError(f"cannot read config {config_path}: {exc}")
    if not isinstance(raw, dict):
        raise ConfigError(f"config {config_path} must be a JSON object")
    unknown = sorted(k for k in raw
                     if k not in KNOWN_KEYS and not k.startswith("_"))
    if unknown:
        raise ConfigError(
            f"config {config_path} has unknown key(s): "
            f"{', '.join(unknown)} (a typo here would silently "
            f"change what the check runs)")
    config = default_config(repo)
    for key, value in raw.items():
        if key.startswith("_"):
            continue
        config[key] = value
    # Remember whether the executable list was written in the
    # config file: names the repo itself declares are required
    # (missing is a failure), while default-list names are
    # candidates (missing is fine, present-but-not-executable
    # is still a failure - see mode_check).
    config["_zip_executables_explicit"] = "zip_executables" in raw
    if isinstance(config["suite_command"], str):
        config["suite_command"] = shlex.split(config["suite_command"])
    return config, False


def work_base(config):
    """Where throwaway work dirs live: config tmp_base, then
    $LOCAL_CI_TMP, then ~/workspace/tmp when it exists (the
    sandbox /tmp is a small tmpfs and a suite run can fill it -
    the J1 lesson), else the system temp dir."""
    if config.get("tmp_base"):
        return config["tmp_base"]
    if os.environ.get("LOCAL_CI_TMP"):
        return os.environ["LOCAL_CI_TMP"]
    home_workspace_tmp = os.path.join(os.path.expanduser("~"),
                                      "workspace", "tmp")
    if os.path.isdir(os.path.dirname(home_workspace_tmp)):
        return home_workspace_tmp
    return tempfile.gettempdir()


# ---------------------------------------------------------------- checks

class CheckResult:
    """One check's outcome: PASS, FAIL, or SKIP, with a detail
    line for the terminal and the verdict file."""

    def __init__(self, name, status, detail, seconds=0.0, lines=None):
        self.name = name
        self.status = status  # "PASS", "FAIL", or "SKIP"
        self.detail = detail
        self.seconds = seconds
        # Extra verdict-file lines (doc counts use one per entry).
        self.lines = lines or []

    def verdict_line(self):
        return f"- {self.name}: {self.detail}"


def suite_check(repo, config, work_dir):
    """Run the suite under timeout, parse the test count."""
    name = "Suite"
    print("=== Suite ===")
    command = config["suite_command"]
    if command is None:
        if os.path.isdir(os.path.join(repo, "tests")):
            command = list(DEFAULT_SUITE_COMMAND)
        else:
            detail = ("SKIP, no tests/ dir and no suite_command "
                      "configured")
            print(detail)
            return CheckResult(name, "SKIP", detail)
    print("command:", " ".join(command))
    log_path = os.path.join(work_dir, "suite.log")
    timeout = config["suite_timeout"]
    env = dict(os.environ)
    env["TMPDIR"] = work_dir
    start = time.monotonic()
    try:
        with open(log_path, "w", encoding="utf-8") as log:
            proc = subprocess.run(
                command, cwd=repo, stdout=log,
                stderr=subprocess.STDOUT, env=env, timeout=timeout)
        timed_out = False
    except FileNotFoundError:
        seconds = time.monotonic() - start
        detail = f"FAIL, suite command not found: {command[0]}"
        print(detail)
        return CheckResult(name, "FAIL", detail, seconds)
    except subprocess.TimeoutExpired:
        seconds = time.monotonic() - start
        detail = f"FAIL, timed out after {timeout}s"
        print(detail)
        return CheckResult(name, "FAIL", detail, seconds)
    seconds = time.monotonic() - start
    with open(log_path, encoding="utf-8", errors="replace") as handle:
        log_text = handle.read()
    count = "?"
    try:
        pattern = re.compile(config["suite_count_pattern"])
    except re.error as exc:
        detail = f"FAIL, bad suite_count_pattern: {exc}"
        print(detail)
        return CheckResult(name, "FAIL", detail, seconds)
    matches = pattern.findall(log_text)
    if matches:
        count = matches[-1]
    # Show the tail, and name the failures - a failing CI that
    # does not say what failed is half-useless, and the work dir
    # is removed on exit, so the names have to reach the
    # terminal now.
    tail = log_text.rstrip("\n").split("\n")[-5:]
    for line in tail:
        print(line)
    if proc.returncode == 0:
        detail = f"{count} checks - PASS ({seconds:.1f}s)"
        print(f"suite: {detail}")
        return CheckResult(name, "PASS", detail, seconds)
    for line in log_text.split("\n"):
        if line.startswith(("FAIL:", "ERROR:")):
            print(line)
    detail = f"{count} checks - FAIL ({seconds:.1f}s)"
    print(f"suite: {detail}")
    return CheckResult(name, "FAIL", detail, seconds)


def collect_tree(repo, skip_dirs, skip_suffixes):
    """(files, dirs): root-relative paths, files sorted. files is
    a list of (absolute path, relative path); dirs is the set of
    parent dirs implied by the files. Same skips as the zip step,
    so the repo-size numbers and the zip numbers agree."""
    skip_dirs = set(skip_dirs)
    files = []
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for name in sorted(filenames):
            if name.endswith(tuple(skip_suffixes)):
                continue
            full = os.path.join(dirpath, name)
            files.append((full, os.path.relpath(full, repo)))
    files.sort(key=lambda item: item[1])
    dirs = set()
    for _full, rel in files:
        parent = os.path.dirname(rel)
        while parent:
            dirs.add(parent)
            parent = os.path.dirname(parent)
    return files, dirs


def load_manifest(repo, manifest_rel):
    """Executable names from a manifest file in the repo (one
    root-relative path per line, # comments) - the Forge Browser
    EXECUTABLES.txt shape. Fails loudly on a missing or empty
    manifest rather than guessing."""
    path = os.path.join(repo, manifest_rel)
    if not os.path.isfile(path):
        raise ConfigError(f"missing manifest: {path}")
    names = set()
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#"):
                names.add(line)
    if not names:
        raise ConfigError(f"empty manifest: {path}")
    return names


def executable_names(repo, config):
    """(all_names, required_names): the explicit executable list.

    all_names is config names plus manifest names, if a manifest
    file is configured. required_names is the subset the repo
    itself declared - config-listed names (only when the config
    file actually lists zip_executables) plus manifest names.
    Default-list names are candidates, not requirements."""
    names = set(config["zip_executables"])
    required = (set(config["zip_executables"])
                if config.get("_zip_executables_explicit") else set())
    manifest = config["zip_executables_file"]
    if manifest:
        manifest_names = load_manifest(repo, manifest)
        names |= manifest_names
        required |= manifest_names
    return names, required


def is_executable(rel, names, globs):
    """True when a root-relative path ships with the exec bit:
    listed by path or by basename, or matching a glob (checked
    against the path and the basename). One rule for build and
    verify alike - J1 matched the manifest by path in the build
    and by basename in the verify, which disagrees on nested
    scripts."""
    if rel in names or os.path.basename(rel) in names:
        return True
    base = os.path.basename(rel)
    return any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(base, g)
               for g in globs)


def build_zip(repo, out_path, config, names):
    """Write the throwaway zip with T1's mode rules: every entry
    gets create_system=3 (Unix) and an explicit external_attr
    with the file-type bits included. Returns
    (files, dirs, size)."""
    files, dirs = collect_tree(repo, config["zip_exclude_dirs"],
                               config["zip_exclude_suffixes"])
    top = config["zip_top"]
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for d in sorted(dirs):
            info = zipfile.ZipInfo(top + "/" + d + "/")
            info.create_system = 3
            info.external_attr = 0o40755 << 16
            zf.writestr(info, b"")
        for full, rel in files:
            mode = (0o100755 if is_executable(
                rel, names, config["zip_executable_globs"])
                    else 0o100644)
            info = zipfile.ZipInfo(top + "/" + rel)
            info.create_system = 3
            info.external_attr = mode << 16
            info.date_time = time.localtime(
                os.path.getmtime(full))[:6]
            with open(full, "rb") as handle:
                zf.writestr(info, handle.read())
    return len(files), len(dirs), os.path.getsize(out_path)


def verify_zip(out_path, names, globs, top):
    """Reopen the zip and prove every entry carries the mode it
    should - the build fails loudly if an executable would
    extract without its exec bit."""
    with zipfile.ZipFile(out_path) as zf:
        for info in zf.infolist():
            mode = info.external_attr >> 16
            if info.create_system != 3:
                raise ValueError(
                    f"{info.filename}: create_system is "
                    f"{info.create_system}, not 3 (Unix)")
            rel = info.filename
            if rel.startswith(top + "/"):
                rel = rel[len(top) + 1:]
            if info.is_dir():
                expect = 0o40755
            elif is_executable(rel.rstrip("/"), names, globs):
                expect = 0o100755
            else:
                expect = 0o100644
            if mode != expect:
                raise ValueError(
                    f"{info.filename}: mode {oct(mode)}, "
                    f"expected {oct(expect)}")


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def zip_check(repo, config, work_dir):
    """Build a throwaway Release-shaped zip and verify it."""
    name = "Release zip"
    print()
    print("=== Release zip (throwaway build from this tree) ===")
    if not config["zip"]:
        detail = "SKIP, zip check disabled in config"
        print(detail)
        return CheckResult(name, "SKIP", detail)
    try:
        names, _required = executable_names(repo, config)
    except ConfigError as exc:
        detail = f"FAIL, {exc}"
        print(detail)
        return CheckResult(name, "FAIL", detail)
    out_path = os.path.join(work_dir, "check.zip")
    start = time.monotonic()
    try:
        files, dirs, size = build_zip(repo, out_path, config, names)
        verify_zip(out_path, names, config["zip_executable_globs"],
                   config["zip_top"])
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        seconds = time.monotonic() - start
        detail = f"FAIL, {exc}"
        print(detail)
        return CheckResult(name, "FAIL", detail, seconds)
    seconds = time.monotonic() - start
    detail = (f"OK: {files} files, {dirs} dirs, {size} bytes, modes "
              f"verified, SHA-256 {sha256_of(out_path)} "
              f"({seconds:.1f}s)")
    print(detail)
    return CheckResult(name, "PASS", detail, seconds)


def mode_check(repo, config):
    """Every named executable must carry its exec bit on disk.

    Only the explicit list is checked (config names + manifest
    names). Glob-matched files are not: a *.sh invoked only via
    `sh file.sh` needs no exec bit, and the zip step stores
    100755 for it either way."""
    name = "Modes"
    print()
    print("=== Stored modes on disk ===")
    if not config["mode_check"]:
        detail = "SKIP, mode check disabled in config"
        print(detail)
        return CheckResult(name, "SKIP", detail)
    try:
        names, required = executable_names(repo, config)
    except ConfigError as exc:
        detail = f"FAIL, {exc}"
        print(detail)
        return CheckResult(name, "FAIL", detail)
    problems = []
    checked = 0
    for rel in sorted(names):
        # Names are root-relative paths (the EXECUTABLES.txt
        # shape). A name the repo itself declared (config or
        # manifest) must exist; a default-list name that is
        # absent is fine - the default list is candidates, not
        # requirements. A name that exists without its exec bit
        # is a failure either way: a file called install.sh
        # that cannot run is broken by any reading.
        path = os.path.join(repo, rel)
        if not os.path.isfile(path):
            if rel in required:
                problems.append(f"listed executable missing: {rel}")
            continue
        checked += 1
        if not os.access(path, os.X_OK):
            problems.append(f"not executable on disk: {rel}")
    if problems:
        for problem in problems:
            print(problem)
        detail = f"FAIL, {len(problems)} problem(s)"
        return CheckResult(name, "FAIL", detail)
    detail = f"{checked} executables on disk OK - PASS"
    print(detail)
    return CheckResult(name, "PASS", detail)


def count_entry(repo, config, entry):
    """Count one doc-count entry. Returns (count, error): count
    is None when the entry cannot be counted, with error naming
    why. Kinds:
      files   - files under path (recursive) matching the glob
                pattern (default "*"), same skips as the zip
      dirs    - immediate subdirectories of path (skip dirs
                excluded)
      lines   - lines in the file at path
      matches - regex matches in the file at path
    """
    label = entry.get("label", entry.get("path", "?"))
    kind = entry.get("kind")
    rel = entry.get("path", "")
    path = os.path.join(repo, rel)
    if kind not in ("files", "dirs", "lines", "matches"):
        return None, f"doc count '{label}': unknown kind {kind!r}"
    if kind in ("files", "dirs"):
        if not os.path.isdir(path):
            return None, f"doc count '{label}': path not found: {rel}"
        if kind == "dirs":
            skip = set(config["zip_exclude_dirs"])
            count = sum(1 for name in os.listdir(path)
                        if os.path.isdir(os.path.join(path, name))
                        and name not in skip)
            return count, None
        pattern = entry.get("pattern", "*")
        count = 0
        for dirpath, dirnames, filenames in os.walk(path):
            dirnames[:] = [d for d in dirnames
                           if d not in config["zip_exclude_dirs"]]
            for name in filenames:
                if name.endswith(tuple(config["zip_exclude_suffixes"])):
                    continue
                if fnmatch.fnmatch(name, pattern):
                    count += 1
        return count, None
    if not os.path.isfile(path):
        return None, f"doc count '{label}': path not found: {rel}"
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError as exc:
        return None, f"doc count '{label}': cannot read {rel}: {exc}"
    if kind == "lines":
        return len(text.splitlines()), None
    try:
        found = re.findall(entry.get("pattern", ""), text)
    except re.error as exc:
        return None, f"doc count '{label}': bad pattern: {exc}"
    return len(found), None


def doc_counts_check(repo, config):
    """The configured doc counts, each with its assertion."""
    name = "Doc counts"
    print()
    print("=== Doc counts ===")
    entries = config["doc_counts"]
    if not entries:
        detail = "no doc counts configured"
        print(detail)
        return CheckResult(name, "SKIP", detail)
    problems = []
    lines = []
    for entry in entries:
        label = entry.get("label", entry.get("path", "?"))
        count, error = count_entry(repo, config, entry)
        if error is not None:
            problems.append(error)
            print(error)
            continue
        assertion = ""
        ok = True
        if "expected" in entry:
            assertion = f" (expected {entry['expected']})"
            ok = count == entry["expected"]
        elif "min" in entry or "max" in entry:
            bits = []
            if "min" in entry:
                bits.append(f"min {entry['min']}")
                ok = ok and count >= entry["min"]
            if "max" in entry:
                bits.append(f"max {entry['max']}")
                ok = ok and count <= entry["max"]
            assertion = f" ({', '.join(bits)})"
        status = "PASS" if ok else "FAIL"
        if not ok:
            problems.append(f"doc count '{label}': got {count}"
                            f"{assertion}")
        line = f"{label}: {count}{assertion} - {status}"
        lines.append(line)
        print(line)
    if problems:
        detail = f"FAIL, {len(problems)} problem(s)"
        return CheckResult(name, "FAIL", detail, lines=lines)
    detail = f"{len(entries)} count(s) - PASS"
    return CheckResult(name, "PASS", detail, lines=lines)


# ---------------------------------------------------------------- verdict

def git_commit(repo):
    try:
        out = subprocess.run(
            ["git", "-C", repo, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return "unknown (not a git checkout)"
    if out.returncode != 0:
        return "unknown (not a git checkout)"
    return out.stdout.strip() or "unknown (not a git checkout)"


def repo_size(repo, config):
    """(file count, byte total) over the same collection the zip
    step uses, so the numbers agree."""
    files, _dirs = collect_tree(repo, config["zip_exclude_dirs"],
                                config["zip_exclude_suffixes"])
    total = 0
    for full, _rel in files:
        try:
            total += os.path.getsize(full)
        except OSError:
            pass
    return len(files), total


def write_verdict(repo, config, results, total_seconds, overall):
    """CI-STATUS.md at the repo root, in J1's shape: commit,
    date, one line per check, repo size, total time. No
    em-dashes anywhere in the file (U33)."""
    date = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    lines = [
        f"# {config['project']} CI status",
        "",
        "Free CI (`ci/check.sh`) - GitHub Actions is billing-locked",
        "account-wide, so this file is the verdict record. Last checked:",
        "",
        f"- Commit: {git_commit(repo)}",
        f"- Date (UTC): {date}",
        f"- Verdict: {overall}",
    ]
    for result in results:
        lines.append(result.verdict_line())
        for extra in result.lines:
            lines.append(f"  - {extra}")
    files, size = repo_size(repo, config)
    lines.append(f"- Repo: {files} files, {size} bytes")
    lines.append(f"- Total: {total_seconds:.1f}s")
    lines.append("")
    lines.append("Run `sh ci/check.sh` from the repo root to re-check.")
    lines.append("")
    path = os.path.join(repo, config["status_file"])
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return path


# ---------------------------------------------------------------- commands

def cmd_check(args):
    """Run the pre-push gate. Exit 0 green, 1 red, 2 could not run."""
    repo = os.path.abspath(args.repo)
    if not os.path.isdir(repo):
        print(f"error: not a directory: {repo}", file=sys.stderr)
        return 2
    try:
        config, _used_defaults = load_config(repo, args.config)
    except ConfigError as exc:
        # A broken config still writes a red verdict: a stale
        # green CI-STATUS.md is worse than a red one.
        print(f"error: {exc}", file=sys.stderr)
        config = default_config(repo)
        result = CheckResult("Config", "FAIL", str(exc))
        if not args.no_status:
            write_verdict(repo, config, [result], 0.0, "FAIL")
        return 2
    base = work_base(config)
    try:
        os.makedirs(base, exist_ok=True)
        work_dir = tempfile.mkdtemp(prefix="local-ci.", dir=base)
    except OSError as exc:
        print(f"error: cannot make work dir under {base}: {exc}",
              file=sys.stderr)
        return 2
    start = time.monotonic()
    try:
        results = [
            suite_check(repo, config, work_dir),
            zip_check(repo, config, work_dir),
            mode_check(repo, config),
            doc_counts_check(repo, config),
        ]
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    total = time.monotonic() - start
    failed = any(r.status == "FAIL" for r in results)
    overall = "FAIL" if failed else "PASS"
    status_path = None
    if not args.no_status:
        status_path = write_verdict(repo, config, results, total,
                                    overall)
    print()
    if failed:
        print(f"CI FAIL - verdict written to {status_path}"
              if status_path else "CI FAIL")
        return 1
    print(f"CI PASS - verdict written to {status_path}"
          if status_path else "CI PASS")
    return 0


def starter_config(target):
    """The config setup installs: project name from the dir,
    suite command only when a tests/ dir exists (otherwise the
    check honestly SKIPs the suite), manifest file only when
    EXECUTABLES.txt exists."""
    name = os.path.basename(os.path.abspath(target))
    config = {"project": name}
    if os.path.isdir(os.path.join(target, "tests")):
        config["suite_command"] = DEFAULT_SUITE_COMMAND
    if os.path.isfile(os.path.join(target, "EXECUTABLES.txt")):
        config["zip_executables_file"] = "EXECUTABLES.txt"
    return config


def cmd_setup(args):
    """Install the check into a target repo: ci/local_ci.py (this
    script, self-contained), ci/check.sh (thin wrapper, the J1
    invocation shape), ci/config.json (starter config). Wires
    nothing into GitHub - no runners, no account, nothing
    billing-lockable."""
    target = os.path.abspath(args.target)
    if not os.path.isdir(target):
        print(f"error: not a directory: {target}", file=sys.stderr)
        return 1
    ci_dir = os.path.join(target, "ci")
    script_dst = os.path.join(ci_dir, "local_ci.py")
    wrapper_dst = os.path.join(ci_dir, "check.sh")
    config_dst = os.path.join(ci_dir, "config.json")
    existing = [p for p in (script_dst, wrapper_dst, config_dst)
                if os.path.exists(p)]
    if existing and not args.force:
        print("already installed (use --force to overwrite):",
              file=sys.stderr)
        for path in existing:
            print(f"  {path}", file=sys.stderr)
        return 1
    os.makedirs(ci_dir, exist_ok=True)
    script_src = os.path.abspath(__file__)
    shutil.copyfile(script_src, script_dst)
    os.chmod(script_dst, 0o755)
    with open(wrapper_dst, "w", encoding="utf-8") as handle:
        handle.write(CHECK_SH_TEMPLATE)
    os.chmod(wrapper_dst, 0o755)
    config = starter_config(target)
    if args.project:
        config["project"] = args.project
    with open(config_dst, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2)
        handle.write("\n")
    print(f"installed local CI into {target}:")
    print(f"  ci/local_ci.py (the check, {VERSION})")
    print("  ci/check.sh (run it as: sh ci/check.sh)")
    print("  ci/config.json (starter config, edit to fit the repo)")
    return 0


# ---------------------------------------------------------------- CLI

def build_parser():
    parser = argparse.ArgumentParser(
        prog="local_ci.py",
        description="Local CI (BNB-TOOLS T28): a repo-agnostic "
                    "pre-push check. Runs the suite, a throwaway "
                    "zip build with stored-mode verification, an "
                    "on-disk mode check, and configured doc "
                    "counts, then writes the verdict to "
                    "CI-STATUS.md. Exit 0 green, 1 red, "
                    "2 could not run.")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {VERSION}")
    sub = parser.add_subparsers(dest="command", metavar="command")
    check = sub.add_parser(
        "check", help="run the pre-push gate against a repo")
    check.add_argument("--repo", default=".",
                       help="repo root to check (default: current dir)")
    check.add_argument("--config", default=None,
                       help="config file (default: <repo>/ci/config.json)")
    check.add_argument("--no-status", action="store_true",
                       help="do not write CI-STATUS.md")
    check.set_defaults(func=cmd_check)
    setup = sub.add_parser(
        "setup", help="install the check into a target repo")
    setup.add_argument("target", help="repo root to install into")
    setup.add_argument("--force", action="store_true",
                       help="overwrite an existing install")
    setup.add_argument("--project", default=None,
                       help="project name for the starter config")
    setup.set_defaults(func=cmd_setup)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
