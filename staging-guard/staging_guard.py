#!/usr/bin/env python3
"""T24 — staging-guard: pre-build check for a publish staging dir.

Before a Release zip is built from a publish staging directory, verify
that the staging dir still holds every file it must hold, with the
right bytes. A sync that rebuilds staging from the tree (or an rsync
with --delete-excluded) silently drops staging-only files — the Code
Forge v2.5-merged sync dropped all 7 installer files from staging
(2026-11-13), caught only by a manual check before the build.

Two commands:

  manifest  Build a manifest (relative path -> SHA-256) for named
            required files, taken from a trusted source dir — usually
            a fresh clone of main.
  check     Verify a staging dir against a manifest: every listed
            file present, every hash matching. Also reports the
            staging file count and can enforce a minimum.

Stdlib only. No network. Never writes into the staging dir.

Usage:
  python3 staging_guard.py manifest --source ./main-clone \
      --files install.sh run.sh INSTALL.txt --out required.json
  python3 staging_guard.py check --staging ./publish \
      --manifest required.json --min-files 150
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path


def sha256_file(path):
    """SHA-256 hex digest of a file, streamed."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(source, files):
    """Map each named relative path to its SHA-256 in source.

    Raises FileNotFoundError naming the first missing file, so a
    manifest is never built from an incomplete source.
    """
    source = Path(source)
    manifest = {}
    for rel in files:
        path = source / rel
        if not path.is_file():
            raise FileNotFoundError(
                "required file %s is not in source dir %s" % (rel, source)
            )
        manifest[rel] = sha256_file(path)
    return {"files": manifest}


def count_files(directory):
    """Count files under directory, recursively (files only)."""
    return sum(1 for path in Path(directory).rglob("*") if path.is_file())


def check_staging(staging, manifest, min_files=None):
    """Verify staging against the manifest.

    Returns (problems, file_count): problems is a list of human
    readable strings, empty when the staging dir is clean.
    """
    staging = Path(staging)
    problems = []
    for rel, expected in sorted(manifest["files"].items()):
        path = staging / rel
        if not path.is_file():
            problems.append("MISSING: %s" % rel)
            continue
        actual = sha256_file(path)
        if actual != expected:
            problems.append(
                "CHANGED: %s (expected %s, got %s)"
                % (rel, expected[:12], actual[:12])
            )
    file_count = count_files(staging)
    if min_files is not None and file_count < min_files:
        problems.append(
            "TOO FEW FILES: staging holds %d files, expected at least %d"
            % (file_count, min_files)
        )
    return problems, file_count


def cmd_manifest(args):
    try:
        manifest = build_manifest(args.source, args.files)
    except FileNotFoundError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1
    out = Path(args.out)
    out.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    print("wrote %s (%d files)" % (out, len(manifest["files"])))
    return 0


def cmd_check(args):
    staging = Path(args.staging)
    if not staging.is_dir():
        print("ERROR: staging dir %s does not exist" % staging,
              file=sys.stderr)
        return 1
    try:
        manifest = json.loads(Path(args.manifest).read_text())
    except (OSError, ValueError) as exc:
        print("ERROR: cannot read manifest %s: %s" % (args.manifest, exc),
              file=sys.stderr)
        return 1
    problems, file_count = check_staging(staging, manifest, args.min_files)
    print("staging: %s (%d files)" % (staging, file_count))
    print("required: %d files" % len(manifest["files"]))
    if problems:
        for problem in problems:
            print("FAIL: %s" % problem)
        print("STAGING CHECK FAILED: %d problem(s)" % len(problems))
        return 1
    print("STAGING CHECK PASSED: all required files present, hashes match")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Pre-build check for a publish staging dir.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_manifest = sub.add_parser(
        "manifest",
        help="build a required-files manifest from a trusted source dir")
    p_manifest.add_argument("--source", required=True,
                            help="trusted source dir (e.g. fresh clone of main)")
    p_manifest.add_argument("--files", required=True, nargs="+",
                            help="required files, relative to --source")
    p_manifest.add_argument("--out", required=True,
                            help="manifest JSON file to write")
    p_manifest.set_defaults(func=cmd_manifest)

    p_check = sub.add_parser(
        "check", help="verify a staging dir against a manifest")
    p_check.add_argument("--staging", required=True,
                         help="publish staging dir to check")
    p_check.add_argument("--manifest", required=True,
                         help="manifest JSON file from `manifest`")
    p_check.add_argument("--min-files", type=int, default=None,
                         help="fail if staging holds fewer files than this")
    p_check.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
