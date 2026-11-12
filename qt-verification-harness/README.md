# T12 — qt-verification-harness

One command that sets the known-good Qt test environment and runs a
launch / screenshot / render-grab check. Standalone — the reusable form of
the incantation that used to be re-derived every time (recipe from
`AGENTS.md`).

## The recipe it encodes

| Setting | Value | Why |
|---|---|---|
| `LD_LIBRARY_PATH` | `~/workspace/qt-libs/root/usr/lib/x86_64-linux-gnu` | VM restarts wipe system packages; the EGL/xcb libs live extracted here |
| `__EGL_VENDOR_LIBRARY_DIRS` | `~/workspace/qt-libs/root/usr/share/glvnd/egl_vendor.d` | offscreen EGL needs the vendor dir |
| python | `~/workspace/forge-v2-testenv/bin/python` when present, else system `python3` with a warning | the venv has PySide6 |
| `TMPDIR` | `/tmp` **ALWAYS** | never the workspace — btrfs inotify is racy (spurious duplicate events broke FileWatcher tests deterministically) |
| `HOME` | `/tmp/forge-test-home` when it exists | overriding HOME to a *fresh* /tmp dir breaks Qt xcb plugin init with misleading "missing lib" errors |
| `QT_QPA_PLATFORM` | `offscreen` (default) | headless window open/close, screenshots, widget tests |
| `--opengl` mode | `xvfb-run -a` + `xcb` | `QOpenGLWidget` has **no GL context** under offscreen; Mesa llvmpipe provides the GL under Xvfb |

## Usage

```bash
python3 qt_harness.py probe.py
python3 qt_harness.py --command "{python} -m unittest discover -v"
python3 qt_harness.py --opengl gl_probe.py
python3 qt_harness.py --check      # report present/missing, run nothing
python3 qt_harness.py --show-env   # print the env, run nothing
```

Exit code is the target's exit code (0 = target passed). Missing qt-libs or
venv is a **warning**, not a failure — a PySide6-free probe can still run;
the report says which path ran.

## Rebuilding qt-libs

If `qt-libs` is absent on a machine, the EGL/xcb libs are Ubuntu noble `.deb`
packages extracted into `~/workspace/qt-libs/root` (no install, no root):

- EGL: `libegl1`, `libegl-mesa0`, `libglapi-mesa`
- xcb (for `--opengl`): `libxcb-cursor0` (pool/universe), `libxcb-icccm4`,
  `libxcb-image0`, `libxcb-keysyms1`, `libxcb-render-util0`,
  `libxcb-util1`, `libxcb-xkb1`, `libxkbcommon-x11-0` (pool/main)

Extract each with `dpkg-deb -x <pkg>.deb ~/workspace/qt-libs/root`.
If the xcb plugin fails to load, run with `QT_DEBUG_PLUGINS=1` and `ldd`
the `libqxcb.so` to name the next missing lib.

## Requirements

Python 3 stdlib + a Qt install for real checks (the test venv's PySide6).
`xvfb-run` only for `--opengl` mode.
