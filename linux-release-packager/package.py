#!/usr/bin/env python3
"""T6 linux-release-packager — turn a project tree into a real Linux
program: icon PNGs + GUI installer + .desktop menu entry + uninstaller.

Pairs with skill S6. Converges the per-project installers (Forge,
MIMIK, Pixel Forge, WinLinx, Forge Browser) into one template.

Outputs (into --out):
  <name>/                  staged app tree (excludes __pycache__ etc.)
  <name>/icons/            PNGs rendered from the icon SVG (16–256px)
  install.sh               GUI-friendly installer (double-clickable via
                           the .desktop below); copies the tree to the
                           install location, installs the menu entry,
                           then SELF-VERIFIES: every --dep module must
                           import after install, or install fails loudly
  uninstall.sh             removes the install + menu entry
  Install <Name>.desktop   double-click installer launcher
  <name>.desktop           the app's menu entry

.desktop Exec quoting (AGENTS.md, Code Forge WAVE 2026-11-12): GLib's
desktop parser REJECTS any nested escaped quote in Exec — the whole
file fails with "Desktop file didn't specify Exec field". So the
launcher MUST NOT use sh -c "$(dirname "%k")" or any nested quotes.
Working pattern: `python3 -c "..."` with %k as a SEPARATE argv token
(field-code expansion keeps a spaced path as one argument), dirname
done in Python, subprocess.call with a list. A gio-launch fallback
(os.getcwd()) covers launchers that expand %k to empty.

Icon rendering tries, in order: rsvg-convert, cairosvg (python -m),
ImageMagick convert/magick. If NONE is available, the tool prints a
clear error naming the missing tools and still generates everything
else (the SVG ships as the icon source of truth and the .desktop
points at it).

Stdlib only for the packager itself. Python 3.8+.
"""
import argparse
import os
import shutil
import subprocess
import sys

EXCLUDE_DIRS = {"__pycache__", ".forge", ".git", ".venv", "node_modules"}
EXCLUDE_FILES = {".pyc", ".pyo", ".DS_Store"}
ICON_SIZES = [16, 32, 48, 64, 128, 256]


def render_pngs(svg_path, out_dir):
    """Render PNGs at ICON_SIZES. Returns (rendered, missing_note)."""
    os.makedirs(out_dir, exist_ok=True)
    # Pick the first available renderer.
    renderer = None
    if shutil.which("rsvg-convert"):
        renderer = "rsvg"
    elif shutil.which("convert") or shutil.which("magick"):
        renderer = "imagemagick"
    else:
        try:
            import cairosvg  # noqa: F401
            renderer = "cairosvg"
        except ImportError:
            renderer = None
    if renderer is None:
        note = ("NO SVG RENDERER FOUND: install one of rsvg-convert "
                "(librsvg2-bin), cairosvg (pip install cairosvg), or "
                "ImageMagick (convert/magick) to render icon PNGs. "
                "Packaging continues with the SVG as the icon source "
                "of truth.")
        return ([], note)
    rendered = []
    for size in ICON_SIZES:
        png = os.path.join(out_dir, f"icon-{size}.png")
        try:
            if renderer == "rsvg":
                subprocess.run(["rsvg-convert", "-w", str(size), "-h",
                                str(size), "-o", png, svg_path], check=True)
            elif renderer == "imagemagick":
                cmd = shutil.which("convert") or shutil.which("magick")
                subprocess.run([cmd, "-background", "none", "-resize",
                                f"{size}x{size}", svg_path, png], check=True)
            else:
                subprocess.run([sys.executable, "-m", "cairosvg",
                                svg_path, "-o", png, "-W", str(size),
                                "-H", str(size)], check=True)
            rendered.append(png)
        except subprocess.CalledProcessError as e:
            print(f"warning: failed to render {size}px icon: {e}",
                  file=sys.stderr)
    return (rendered, None)


def desktop_exec_python(snippet):
    """GLib-safe Exec line: python3 -c "<snippet>" %k.

    The snippet must use single quotes only (no nested double quotes),
    and %k stays a separate argv token so spaced paths survive.
    """
    if '"' in snippet:
        raise ValueError("desktop Exec snippet must not contain double "
                         "quotes (GLib rejects nested escaped quotes)")
    return f'Exec=python3 -c "{snippet}" %k'


def make_install_desktop(app_name, display_name):
    # %k = path of this .desktop file; the installer script sits next
    # to it. dirname in Python, subprocess with a list, no shell.
    snippet = ("import os,subprocess,sys; d=os.path.dirname(sys.argv[1]) "
               "or os.getcwd(); subprocess.call(['bash', "
               "os.path.join(d, 'install.sh')])")
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        f"Name=Install {display_name}",
        f"Comment=Install {display_name}",
        desktop_exec_python(snippet),
        "Terminal=false",
        "Categories=Utility;",
        "",
    ])


def make_app_desktop(app_name, display_name, icon_path, entry_cmd):
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        f"Name={display_name}",
        f"Comment={display_name}",
        f"Exec={entry_cmd}",
        f"Icon={icon_path}",
        "Terminal=false",
        "Categories=Utility;",
        "",
    ])


def make_install_sh(app_name, display_name, deps, entry_file):
    dep_checks = ""
    for dep in deps:
        dep_checks += (
            f'if ! "$PY" -c "import {dep}" 2>/dev/null; then\n'
            f'  echo "INSTALL FAILED: required module \'{dep}\' is not '
            f'importable after install." >&2\n'
            f'  exit 1\n'
            f'fi\n')
    return f"""#!/bin/bash
# Installer for {display_name}. Generated by bnb-tools T6.
# Double-click "Install {display_name}.desktop", or run: bash install.sh
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.local/share/{app_name}"
PY="$(command -v python3)"
echo "Installing {display_name} to $DEST ..."
rm -rf "$DEST"
mkdir -p "$DEST"
cp -r "$DIR/{app_name}/." "$DEST/"
mkdir -p "$HOME/.local/share/applications"
cp "$DIR/{app_name}.desktop" "$HOME/.local/share/applications/"
# Self-verification: every required dependency must import AFTER install.
{dep_checks}echo "Verifying entry point ..."
test -f "$DEST/{entry_file}" || {{ echo "INSTALL FAILED: {entry_file} missing from install." >&2; exit 1; }}
echo "{display_name} installed. Launch it from your applications menu."
"""


def make_uninstall_sh(app_name, display_name):
    return f"""#!/bin/bash
# Uninstaller for {display_name}. Generated by bnb-tools T6.
set -euo pipefail
rm -rf "$HOME/.local/share/{app_name}"
rm -f "$HOME/.local/share/applications/{app_name}.desktop"
echo "{display_name} uninstalled."
"""


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="package.py",
        description="Package a project tree as a Linux release: icons, "
                    "GUI installer, .desktop entries, uninstaller.")
    ap.add_argument("--tree", required=True, help="project tree to package")
    ap.add_argument("--name", required=True,
                    help="app id (lowercase, no spaces), e.g. winlinx")
    ap.add_argument("--display-name", default=None,
                    help="human name for menus (default: --name)")
    ap.add_argument("--icon", default=None,
                    help="icon SVG file (source of truth)")
    ap.add_argument("--entry", required=True,
                    help="entry file inside the tree, e.g. main.py or run.sh")
    ap.add_argument("--dep", action="append", default=[],
                    help="Python module that must import after install "
                         "(repeatable; installer self-verifies)")
    ap.add_argument("--out", required=True, help="output directory")
    args = ap.parse_args(argv)
    display = args.display_name or args.name
    tree = os.path.abspath(args.tree)
    out = os.path.abspath(args.out)
    if not os.path.isdir(tree):
        raise SystemExit(f"error: tree not found: {tree}")
    if not os.path.isfile(os.path.join(tree, args.entry)):
        raise SystemExit(f"error: entry file {args.entry!r} not in tree")
    staged = os.path.join(out, args.name)
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)

    def ignore(dirpath, names):
        ignored = []
        for n in names:
            if n in EXCLUDE_DIRS:
                ignored.append(n)
            elif any(n.endswith(s) for s in EXCLUDE_FILES):
                ignored.append(n)
        return ignored

    shutil.copytree(tree, staged, ignore=ignore)
    print(f"staged tree -> {staged}")

    icon_target = None
    if args.icon:
        if not os.path.isfile(args.icon):
            raise SystemExit(f"error: icon not found: {args.icon}")
        icons_dir = os.path.join(staged, "icons")
        shutil.copy2(args.icon, os.path.join(staged, "icon.svg"))
        rendered, note = render_pngs(args.icon, icons_dir)
        if note:
            print(f"WARNING: {note}", file=sys.stderr)
        if rendered:
            print(f"rendered {len(rendered)} icon PNGs via "
                  f"{os.path.basename(icons_dir)}")
            icon_target = os.path.join(
                os.path.expanduser("~"), ".local", "share", args.name,
                "icons", "icon-128.png")
        else:
            icon_target = os.path.join(
                os.path.expanduser("~"), ".local", "share", args.name,
                "icon.svg")
    else:
        icon_target = ""

    entry_cmd = (f"bash {os.path.expanduser('~')}/.local/share/{args.name}/"
                 f"{args.entry}" if args.entry.endswith(".sh")
                 else f"python3 {os.path.expanduser('~')}/.local/share/"
                      f"{args.name}/{args.entry}")

    with open(os.path.join(out, f"Install {display}.desktop"), "w",
              encoding="utf-8") as f:
        f.write(make_install_desktop(args.name, display))
    with open(os.path.join(out, f"{args.name}.desktop"), "w",
              encoding="utf-8") as f:
        f.write(make_app_desktop(args.name, display, icon_target, entry_cmd))
    with open(os.path.join(out, "install.sh"), "w", encoding="utf-8") as f:
        f.write(make_install_sh(args.name, display, args.dep, args.entry))
    with open(os.path.join(out, "uninstall.sh"), "w",
              encoding="utf-8") as f:
        f.write(make_uninstall_sh(args.name, display))
    os.chmod(os.path.join(out, "install.sh"), 0o755)
    os.chmod(os.path.join(out, "uninstall.sh"), 0o755)
    print(f"package -> {out}")
    print("files: install.sh, uninstall.sh, "
          f"'Install {display}.desktop', {args.name}.desktop, "
          f"{args.name}/ (staged tree)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
