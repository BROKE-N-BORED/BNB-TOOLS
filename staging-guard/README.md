# T24 — staging-guard

Pairs with skill **S1** (ship pipeline — verify → push → Release →
hash-match).

Pre-build check for a publish staging directory: verify that staging
still holds every file it must hold, with the right bytes, before a
Release zip is built from it.

## Why it exists

A sync that rebuilds the publish staging from the tree silently drops
staging-only files, and an rsync with `--delete-excluded` deletes the
excluded staging-owned files outright. Code Forge, 2026-11-13:

- DEV's v2.5-merged push sync rebuilt the Code Forge publish staging
  from the tree and dropped all 7 installer files from staging. The
  GITHUB thread caught it in the pre-build check, restored them from
  main, and verified byte-identical before building (GITHUB thread
  14:43).
- A separate `--delete-excluded` rsync wiped CHANGELOG.md, README.md,
  and install.sh from the same staging in one run (AGENTS.md,
  2026-11-13; recovered from a fresh clone of main).

The staging sync itself stays overlay-only (plain `rsync -a` with
`--exclude`, no `--delete` of any kind — see S1). This tool is the
check that catches it when the sync, or a hand edit, drops something
anyway.

## What it does

- `manifest` — build a manifest (relative path → SHA-256) for named
  required files, taken from a trusted source dir, usually a fresh
  clone of main. Refuses to build from an incomplete source: a named
  file missing from the source is an error, not a silent skip.
- `check` — verify a staging dir against a manifest: every listed
  file present, every hash matching. Reports the staging file count
  and can enforce a minimum with `--min-files`. Prints each problem
  (MISSING / CHANGED / TOO FEW FILES) and exits 1 on any failure,
  0 when clean.

The tool never writes into the staging dir. It reads the manifest,
hashes the files, and reports.

## Requirements

Python 3.8+, stdlib only. No network.

## Usage

```bash
# Build the manifest from a fresh clone of main (the trusted source)
python3 staging_guard.py manifest --source ./main-clone \
    --files install.sh run.sh INSTALL.txt README.md CHANGELOG.md \
    --out required.json

# Check staging before building the Release zip
python3 staging_guard.py check --staging ./publish \
    --manifest required.json --min-files 150
```

Exit codes: `check` exits 1 when any required file is missing or
changed, or the file count is below `--min-files`; 0 when clean.
`manifest` exits 1 when a named file is missing from the source.

## Smoke test

```bash
python3 -m unittest discover -s tests -v
```

Runs without network access and without touching a live repo: fixture
dirs are built in a temp directory. Covers manifest generation,
a clean check, a missing file, a changed file, and the minimum
file-count gate.

## What it does not do

- It does not sync staging, restore missing files, or build the zip.
  When it fails, restore from a fresh clone of main (see S1) and
  re-run the check until it passes.
- It does not verify the zip or the Release — that is T1.
- It does not check file modes — that is T1's `verify`.
