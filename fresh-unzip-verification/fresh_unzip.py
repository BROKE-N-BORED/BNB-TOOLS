#!/usr/bin/env python3
"""T11 — fresh-unzip-verification (standalone).

The "verify from a fresh unzip" step of the ship pipeline, as one command:
unzip a shipped zip into a clean temp directory, run smoke checks, run the
verification command there, and report pass/fail per check.

Checks performed:
  1. zip opens and extracts cleanly into a fresh temp dir
  2. expected files present (--expect, repeatable; glob patterns allowed)
  3. entry script exists and is executable where required (--entry)
  4. stored zip modes correct (--check-modes: scripts 0o100755, files
     0o100644 — the file-type bits matter; bare 0o755 extracts fine under the
     `unzip` CLI but GUI extractors drop the execute bit)
  5. verification command runs green there (default: python3 -m unittest
     discover -v; override with --command; --no-command skips it)
  6. optional GUI tab screenshots if a screenshot command is supplied
     (--screenshot-cmd, run with {dir} and {out} placeholders; skipped with
     a note when not supplied)

Usage:
    fresh_unzip.py release.zip
    fresh_unzip.py release.zip --expect run.sh --expect README.md \\
        --entry run.sh --command "python3 -m unittest discover -v"
    fresh_unzip.py release.zip --check-modes --keep  # --keep leaves the dir

Exit code: 0 = all checks passed, 1 = any check failed, 2 = usage error.
"""
import argparse
import fnmatch
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

DEFAULT_COMMAND = "python3 -m unittest discover -v"


class Check:
    def __init__(self, name):
        self.name = name
        self.status = "SKIP"
        self.detail = ""

    def ok(self, detail=""):
        self.status, self.detail = "PASS", detail

    def fail(self, detail):
        self.status, self.detail = "FAIL", detail

    def skip(self, detail=""):
        self.status, self.detail = "SKIP", detail


def zip_modes(path):
    """Return {name: mode} of stored unix modes (external_attr >> 16)."""
    modes = {}
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            modes[info.filename] = (info.external_attr >> 16) & 0o777777
    return modes


def extract_zip(zip_path, dest):
    """Extract honoring stored unix modes.

    Python's zipfile.extractall does NOT restore the execute bit (verified:
    a 0o100755 entry came out 0o100660), so a harness that used it would
    false-fail every entry script. Prefer the `unzip` CLI (restores modes,
    same as a user's GUI extractor); fall back to zipfile + a manual chmod
    pass from each entry's external_attr.
    """
    unzip = shutil.which("unzip")
    if unzip:
        p = subprocess.run([unzip, "-q", "-o", zip_path, "-d", dest],
                           capture_output=True, text=True)
        if p.returncode != 0:
            raise RuntimeError("unzip failed: %s" % p.stderr.strip())
        return "unzip CLI"
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)
        for info in zf.infolist():
            if info.is_dir():
                continue
            mode = (info.external_attr >> 16) & 0o777
            if mode:
                os.chmod(os.path.join(dest, info.filename), mode)
    return "zipfile + chmod pass"


def extract_root(workdir):
    """If the zip contains a single top-level directory, checks run inside
    it; otherwise the workdir itself is the root."""
    entries = [e for e in os.listdir(workdir)
               if not e.startswith("__MACOSX")]
    if len(entries) == 1 and os.path.isdir(os.path.join(workdir, entries[0])):
        return os.path.join(workdir, entries[0])
    return workdir


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Verify a shipped zip from a fresh unzip in a clean "
                    "temp directory.")
    ap.add_argument("zip", help="zip file to verify")
    ap.add_argument("--expect", action="append", default=[],
                    help="expected file (glob allowed); repeatable")
    ap.add_argument("--entry",
                    help="entry script that must exist and be executable")
    ap.add_argument("--check-modes", action="store_true",
                    help="verify stored zip modes (scripts 0o100755, "
                         "files 0o100644)")
    ap.add_argument("--command", default=DEFAULT_COMMAND,
                    help="verification command run inside the fresh unzip "
                         "(default: %(default)s)")
    ap.add_argument("--no-command", action="store_true",
                    help="skip the verification command")
    ap.add_argument("--screenshot-cmd",
                    help="command to screenshot GUI tabs; {dir} = extracted "
                         "root, {out} = output dir. Skipped with a note if "
                         "not supplied.")
    ap.add_argument("--keep", action="store_true",
                    help="keep the temp dir and print its path")
    ap.add_argument("--timeout", type=int, default=600,
                    help="timeout in seconds for the verification command")
    args = ap.parse_args(argv)

    checks = []
    if not os.path.isfile(args.zip):
        print("error: no such file: %s" % args.zip, file=sys.stderr)
        return 2
    if not zipfile.is_zipfile(args.zip):
        print("error: not a zip file: %s" % args.zip, file=sys.stderr)
        return 2

    tmpdir = tempfile.mkdtemp(prefix="fresh-unzip-")
    try:
        c = Check("extract")
        checks.append(c)
        try:
            method = extract_zip(args.zip, tmpdir)
            c.ok("extracted %s to %s (%s)" % (args.zip, tmpdir, method))
        except Exception as e:
            c.fail("extraction failed: %s" % e)
            report(checks)
            return 1
        root = extract_root(tmpdir)

        # Expected files
        for pattern in args.expect:
            c = Check("expect: %s" % pattern)
            checks.append(c)
            found = []
            for dirpath, _dirs, files in os.walk(root):
                for f in files:
                    rel = os.path.relpath(os.path.join(dirpath, f), root)
                    if fnmatch.fnmatch(rel, pattern):
                        found.append(rel)
            if found:
                c.ok("found: %s" % ", ".join(sorted(found)[:3]))
            else:
                c.fail("no file matching %r under %s" % (pattern, root))

        # Entry script
        if args.entry:
            c = Check("entry: %s" % args.entry)
            checks.append(c)
            path = os.path.join(root, args.entry)
            if not os.path.isfile(path):
                c.fail("entry script missing: %s" % path)
            elif not os.access(path, os.X_OK):
                c.fail("entry script exists but is NOT executable: %s" % path)
            else:
                c.ok("exists and executable")

        # Stored zip modes
        if args.check_modes:
            c = Check("zip modes")
            checks.append(c)
            bad = []
            for name, mode in sorted(zip_modes(args.zip).items()):
                if name.endswith(".sh") and mode != 0o100755:
                    bad.append("%s: stored %o, want 100755" % (name, mode))
                elif not name.endswith(".sh") and mode not in (0o100644,
                                                                0o100755):
                    bad.append("%s: stored %o (missing file-type bits?)"
                               % (name, mode))
            if bad:
                c.fail("; ".join(bad[:5]))
            else:
                c.ok("all stored modes carry file-type bits")

        # Verification command
        c = Check("command: %s" % args.command)
        checks.append(c)
        if args.no_command:
            c.skip("--no-command given")
        else:
            try:
                p = subprocess.run(args.command, shell=True, cwd=root,
                                   capture_output=True, text=True,
                                   timeout=args.timeout)
                tail = (p.stdout + p.stderr).strip().splitlines()
                last = tail[-1] if tail else ""
                if p.returncode == 0:
                    c.ok("exit 0; last line: %s" % last)
                else:
                    c.fail("exit %d; last lines:\n      %s"
                           % (p.returncode,
                              "\n      ".join(tail[-5:])))
            except subprocess.TimeoutExpired:
                c.fail("timed out after %ds" % args.timeout)

        # Optional screenshots
        c = Check("screenshots")
        checks.append(c)
        if not args.screenshot_cmd:
            c.skip("no --screenshot-cmd supplied")
        else:
            outdir = os.path.join(tmpdir, "screenshots")
            os.makedirs(outdir, exist_ok=True)
            cmd = args.screenshot_cmd.format(dir=root, out=outdir)
            p = subprocess.run(cmd, shell=True, capture_output=True,
                               text=True, timeout=args.timeout)
            shots = sorted(os.listdir(outdir))
            if p.returncode == 0 and shots:
                c.ok("%d screenshot(s) in %s" % (len(shots), outdir))
            else:
                c.fail("screenshot command exit %d; %s"
                       % (p.returncode, (p.stderr or "").strip()[-200:]))
    finally:
        if args.keep:
            print("temp dir kept: %s" % tmpdir)
        else:
            shutil.rmtree(tmpdir, ignore_errors=True)

    return report(checks)


def report(checks):
    print()
    print("FRESH-UNZIP VERIFICATION")
    print("-" * 60)
    failed = 0
    for c in checks:
        print("[%s] %s" % (c.status, c.name))
        if c.detail:
            for line in c.detail.splitlines():
                print("       %s" % line)
        if c.status == "FAIL":
            failed += 1
    print("-" * 60)
    n_pass = sum(1 for c in checks if c.status == "PASS")
    print("%d passed, %d failed, %d skipped"
          % (n_pass, failed,
             sum(1 for c in checks if c.status == "SKIP")))
    print("RESULT: %s" % ("PASS" if failed == 0 else "FAIL"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
