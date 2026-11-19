"""Shared helpers for the release-zip-mode-checker tests.

make_zip builds a fixture zip with exact stored modes, so the
tests prove the checker reads what is really in the zip rather
than what a builder usually writes.
"""
import io
import zipfile
from contextlib import redirect_stderr, redirect_stdout


def make_zip(path, entries, comment=b""):
    """Write a zip at path.

    entries: (name, data, mode, create_system) tuples. mode is
    the full Unix mode (0o100755) or None for no stored mode.
    Directories are entries whose name ends with '/'.
    """
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.comment = comment
        for name, data, mode, system in entries:
            info = zipfile.ZipInfo(name)
            info.create_system = system
            if mode is not None:
                info.external_attr = mode << 16
            zf.writestr(info, data)


def unix_file(name, data=b"x", mode=0o100644):
    """One Unix-created file entry."""
    return (name, data, mode, 3)


def unix_dir(name, mode=0o40755):
    """One Unix-created directory entry."""
    if not name.endswith("/"):
        name += "/"
    return (name, b"", mode, 3)


def dos_file(name, data=b"x"):
    """One DOS/Windows-created file entry: no Unix mode at all."""
    return (name, data, None, 0)


def run_cli(main, argv):
    """Run main(argv), capturing stdout/stderr. Returns
    (exit_code, stdout, stderr)."""
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()
