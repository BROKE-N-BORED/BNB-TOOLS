"""Shared test helpers: fake AppImages.

A fake AppImage is a small shell script standing in for a real
AppImage binary: the sandbox has no real AppImages, and the
tool's job (set the exec bit, run the file detached, watch what
happens) is the same either way. Real-AppImage behavior on the
user's Mint PC is unproven and the README says so.
"""

import os
import stat
import tempfile


def make_fake_appimage(body, name="Fake.AppImage", mode=0o644):
    """Write a fake AppImage script with this shell body into a
    fresh temp dir. Returns (dir, path). The file starts NOT
    executable (mode 0o644) unless a mode is passed: setting the
    exec bit is the tool's job, and the tests check it happened.
    """
    tmp = tempfile.mkdtemp(prefix="appimage-run-helper-test-")
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\n")
        fh.write(body)
        if not body.endswith("\n"):
            fh.write("\n")
    os.chmod(path, mode)
    return tmp, path


def mode_of(path):
    return stat.S_IMODE(os.stat(path).st_mode)
