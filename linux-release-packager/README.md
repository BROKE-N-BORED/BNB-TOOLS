# T6 — linux-release-packager

Pairs with skill **S6** (Linux release packaging — icon + double-click installer + menu entry).

From a project tree + icon SVG, produces a real Linux program package. Converges the per-project installers (Forge, MIMIK, Pixel Forge, WinLinx, Forge Browser) into one template.

## What it does

Into `--out` it generates:

- `<name>/` — the staged app tree (excludes `__pycache__`, `.forge`, `.git`, `.venv`, `*.pyc`).
- `<name>/icons/` — PNGs rendered from the icon SVG at 16/32/48/64/128/256 px, when a renderer is available. Tries `rsvg-convert`, then `cairosvg`, then ImageMagick (`convert`/`magick`). If **none** is available it prints a clear error naming the missing tools and still generates everything else, with the SVG as the icon source of truth.
- `install.sh` — installer (double-clickable via the desktop file, or `bash install.sh`). Copies the tree to `~/.local/share/<name>`, installs the menu entry, then **self-verifies**: every `--dep` module must import after install or the install fails loudly. Deps are core, never optional.
- `uninstall.sh` — removes the install + menu entry.
- `Install <Name>.desktop` — double-click installer launcher.
- `<name>.desktop` — the app's menu entry.

## .desktop Exec quoting

GLib's desktop parser **rejects any nested escaped quote** in `Exec` — the whole file fails with "Desktop file didn't specify Exec field" (AGENTS.md, Code Forge WAVE 2026-11-12). The launcher therefore uses `python3 -c "..."` with `%k` as a **separate argv token** (field-code expansion keeps a spaced path as one argument), dirname done in Python, `subprocess.call` with a list — never `sh -c "$(dirname "%k")"`. An `os.getcwd()` fallback covers launchers (like `gio launch`) that expand `%k` to empty.

## Requirements

- Python 3.8+, stdlib only for the packager itself.
- One SVG renderer for PNG icons: `rsvg-convert` (librsvg2-bin), `cairosvg` (`pip install cairosvg`), or ImageMagick. Optional — packaging continues without PNGs if none is present.

## Usage

```bash
python3 package.py --tree ./my-app --name myapp \
    --display-name "My App" --icon ./icon.svg \
    --entry main.py --dep PySide6 --dep requests \
    --out ./myapp-release
```

## Smoke test

```bash
bash smoke_test.sh
```

Packages a tiny sample app tree, checks the `.desktop` files parse (via `desktop-file-validate` when present, else a parser check), and validates the installer with `bash -n`.
