# T1 — ship-pipeline-scripts

Pairs with skill **S1** (ship pipeline — verify → email → push → Release → hash-match).

One reusable tool for the zip half of every shipment. Generalizes the per-build packers `build_release_zip.py` and `build_graphqueue_zip.py`.

## What it does

- `build` — pack a tree into a zip with **correct stored modes**: `0o100755` for scripts, `0o100644` for plain files, `0o40755` for directories. The file-type bits are the whole point: bare `0o755` extracts fine under the `unzip` CLI but GUI extractors (Thunar's) drop the execute bit and the user gets "Permission denied" on `./install.sh`.
- `verify` — check stored modes inside an existing zip; fails on any entry missing file-type bits.
- `sha256` — print SHA-256 of files.
- `compare` — SHA-256-compare two files (local zip vs downloaded Release asset).

Default excludes: `__pycache__`, `.forge`, `.git`, `.venv`, `node_modules`, `*.pyc`. Default executable names: `run.sh`, `install.sh`, `browser-setup.sh`, `install-gui.py`, `uninstall.sh`, plus any `*.sh` / `*.desktop`.

## Requirements

Python 3.8+, stdlib only. No network.

## Usage

```bash
# Pack a tree (verifies modes automatically after packing)
python3 ship.py build "/path/to/My App" my-app-v1.0.zip --top "My App"

# Extra excludes / extra executables
python3 ship.py build ./tree out.zip --exclude-dir dist --script launch.py

# Verify an existing zip's stored modes
python3 ship.py verify my-app-v1.0.zip

# Hash a local zip and compare against a downloaded Release asset
python3 ship.py sha256 my-app-v1.0.zip
python3 ship.py compare my-app-v1.0.zip ~/Downloads/my-app-v1.0.zip
```

Exit codes: `build`/`verify` exit 1 on a mode failure; `compare` exits 1 on mismatch.

## Smoke test

```bash
bash smoke_test.sh
```

Packs a small sample tree, verifies stored modes, and hash-matches a copy of the zip.
