# T11 — fresh-unzip-verification

Verify a shipped zip the way the user will receive it: unzip into a clean
temp directory, run smoke checks, run the test suite there, report pass/fail
per check. Standalone (the discipline is the existing
`verify_like_the_user` skill).

## Checks

1. **extract** — zip opens and extracts cleanly
2. **expect** — expected files present (`--expect`, glob patterns, repeatable)
3. **entry** — entry script exists and is executable (`--entry run.sh`)
4. **zip modes** (`--check-modes`) — stored unix modes carry the file-type
   bits: scripts `0o100755`, plain files `0o100644`. Bare `0o755` (no file
   type) extracts fine under the `unzip` CLI but GUI extractors drop the
   execute bit, and the user gets "Permission denied" on `./install.sh`.
5. **command** — verification command run inside the fresh unzip
   (default `python3 -m unittest discover -v`; override with `--command`,
   skip with `--no-command`)
6. **screenshots** — optional GUI tab screenshots if a screenshot command is
   supplied (`--screenshot-cmd`, with `{dir}` and `{out}` placeholders);
   skipped with a note when not supplied

If the zip contains a single top-level directory, checks run inside it;
otherwise they run at the extraction root.

## Usage

```bash
python3 fresh_unzip.py release.zip
python3 fresh_unzip.py release.zip --expect run.sh --expect README.md \
    --entry run.sh --check-modes
python3 fresh_unzip.py release.zip --command "python3 -m pytest -q" --keep
```

Exit code 0 = all checks passed, 1 = any check failed, 2 = usage error.
`--keep` leaves the temp dir in place and prints its path.

## Requirements

Python 3, standard library only.
