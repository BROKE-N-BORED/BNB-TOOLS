#!/usr/bin/env python3
"""T1 ship-pipeline-scripts — zip builder + verifier + SHA-256 compare.

Generalizes ~/workspace/build_release_zip.py and build_graphqueue_zip.py
(per-build packers) into one reusable tool.

The one rule that matters: stored zip modes MUST include the file-type
bits — 0o100755 for scripts, 0o100644 for plain files, 0o40755 for dirs.
Bare 0o755 (no file type) extracts fine under the `unzip` CLI but GUI
extractors (Thunar's) drop the execute bit and the user gets
"Permission denied" on ./install.sh. (AGENTS.md, Design Shell 2026-11-11.)

Subcommands:
  build    pack a tree into a zip with correct stored modes
  verify   check stored modes inside an existing zip
  sha256   print SHA-256 of one or more files
  compare  SHA-256-compare two files (local zip vs downloaded asset)

Stdlib only. Python 3.8+.
"""
import argparse
import fnmatch
import hashlib
import os
import sys
import zipfile

MODE_SCRIPT = 0o100755
MODE_FILE = 0o100644
MODE_DIR = 0o40755

DEFAULT_EXCLUDE_DIRS = {"__pycache__", ".forge", ".git", ".venv", "node_modules"}
DEFAULT_EXCLUDE_FILES = {"*.pyc", "*.pyo", ".DS_Store"}
DEFAULT_SCRIPTS = {"run.sh", "install.sh", "browser-setup.sh",
                   "install-gui.py", "uninstall.sh"}


def is_script(name, extra_scripts):
    if name in DEFAULT_SCRIPTS or name in extra_scripts:
        return True
    return name.endswith((".sh", ".desktop"))


def excluded_dir(name, extra):
    return name in DEFAULT_EXCLUDE_DIRS or name in extra


def excluded_file(name, patterns):
    for pat in list(DEFAULT_EXCLUDE_FILES) + list(patterns):
        if fnmatch.fnmatch(name, pat):
            return True
    return False


def build_zip(src, out, top, exclude_dirs, exclude_files, extra_scripts):
    src = os.path.abspath(src)
    if not os.path.isdir(src):
        raise SystemExit(f"error: source tree not found: {src}")
    count = dcount = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(src):
            dirs[:] = sorted(d for d in dirs
                             if not excluded_dir(d, exclude_dirs))
            rel_root = os.path.relpath(root, src)
            arc_root = top if rel_root == "." else f"{top}/{rel_root}"
            info = zipfile.ZipInfo(arc_root + "/")
            info.external_attr = MODE_DIR << 16
            z.writestr(info, b"")
            dcount += 1
            for name in sorted(files):
                if excluded_file(name, exclude_files):
                    continue
                full = os.path.join(root, name)
                if os.path.islink(full):
                    print(f"warning: skipping symlink {full}", file=sys.stderr)
                    continue
                rel = os.path.relpath(full, src)
                arc = f"{top}/{rel}"
                mode = MODE_SCRIPT if is_script(name, extra_scripts) else MODE_FILE
                info = zipfile.ZipInfo(arc)
                info.external_attr = mode << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                with open(full, "rb") as fh:
                    z.writestr(info, fh.read())
                count += 1
    size = os.path.getsize(out)
    print(f"wrote {out}: {count} files + {dcount} dirs, {size} bytes")
    return count, dcount, size


def verify_modes(zip_path):
    """Return (ok, problems). Every entry must carry file-type bits."""
    problems = []
    n_files = n_dirs = 0
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            mode = info.external_attr >> 16
            ftype = mode & 0o170000
            if info.is_dir():
                n_dirs += 1
                if mode != MODE_DIR:
                    problems.append(f"{info.filename}: dir mode "
                                    f"{oct(mode)}, expected {oct(MODE_DIR)}")
            else:
                n_files += 1
                if ftype != 0o100000:
                    problems.append(f"{info.filename}: missing file-type "
                                    f"bits (stored mode {oct(mode)}) — GUI "
                                    f"extractors will drop the exec bit")
                elif mode not in (MODE_SCRIPT, MODE_FILE):
                    problems.append(f"{info.filename}: unexpected mode "
                                    f"{oct(mode)}")
    print(f"{zip_path}: {n_files} files + {n_dirs} dirs checked")
    if problems:
        print(f"MODE CHECK FAILED: {len(problems)} problem(s)")
        for p in problems:
            print(f"  {p}")
        return False, problems
    print("MODE CHECK OK — every entry carries file-type bits")
    return True, []


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="ship.py",
        description="Ship pipeline: build zips with correct stored modes, "
                    "verify them, SHA-256-compare files.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="pack a tree into a zip")
    b.add_argument("tree", help="source tree to pack")
    b.add_argument("out", help="output zip path")
    b.add_argument("--top", default=None,
                   help="top folder name inside the zip "
                        "(default: basename of the tree)")
    b.add_argument("--exclude-dir", action="append", default=[],
                   help="extra directory name to exclude (repeatable)")
    b.add_argument("--exclude-file", action="append", default=[],
                   help="extra file glob to exclude (repeatable)")
    b.add_argument("--script", action="append", default=[],
                   help="extra filename to store as executable (repeatable)")

    v = sub.add_parser("verify", help="check stored modes inside a zip")
    v.add_argument("zip", help="zip file to check")

    s = sub.add_parser("sha256", help="print SHA-256 of file(s)")
    s.add_argument("files", nargs="+")

    c = sub.add_parser("compare", help="SHA-256-compare two files")
    c.add_argument("a", help="first file (e.g. local zip)")
    c.add_argument("b", help="second file (e.g. downloaded Release asset)")

    args = ap.parse_args(argv)

    if args.cmd == "build":
        top = args.top or os.path.basename(os.path.abspath(args.tree))
        build_zip(args.tree, args.out, top, set(args.exclude_dir),
                  args.exclude_file, set(args.script))
        ok, _ = verify_modes(args.out)
        return 0 if ok else 1
    if args.cmd == "verify":
        ok, _ = verify_modes(args.zip)
        return 0 if ok else 1
    if args.cmd == "sha256":
        for f in args.files:
            print(f"{sha256_of(f)}  {f}")
        return 0
    if args.cmd == "compare":
        ha, hb = sha256_of(args.a), sha256_of(args.b)
        print(f"{ha}  {args.a}")
        print(f"{hb}  {args.b}")
        if ha == hb:
            print("MATCH — files are byte-identical")
            return 0
        print("MISMATCH — files differ")
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
