# T39 - release-zip-mode-checker

Pairs with skill **S6** (linux-release-packaging - the zip
builder must store `.sh` and `.desktop` files executable).

A small chainable checker: is a built Release zip safe to
upload? It reads the stored modes in the zip and fails if any
`.sh` or `.desktop` entry is not stored executable
(0o100755), because that is the difference between a program
Joshua can install by double-clicking and one that opens in a
text editor or says "Permission denied".

Two pieces, each runnable alone:

- **check** - reads a built zip, lists the stored mode of
  every `.sh` and `.desktop` entry, and passes or fails.
  Exit 0 pass, 1 bad modes, 2 could not check.
- **fix** - rebuilds the zip with correct modes and reports
  every mode it changed.

Chain: build the Release zip with S6's packager, run `check`
on it, and only upload when it passes. If it fails, run `fix`
and check again:

```text
python3 release_zip_mode_checker.py check myapp-v1.0.zip
python3 release_zip_mode_checker.py fix myapp-v1.0.zip
python3 release_zip_mode_checker.py check myapp-v1.0-modes-fixed.zip
```

Errors are plain words naming the missing thing, never a
traceback. Standard library only: no install, no network, no
credentials of any kind.

## Why it exists: OST v22

On 2026-11-18, OLLAMA SYSTEM TEST shipped Release v22 with an
install package whose `installer.desktop` was stored
non-executable. Joshua double-clicked it and a text editor
opened instead of the installer. In his words: "No i shouldn't
need the fucjing terminal".

The fixed asset had to be built again and re-uploaded to the
Release (new zip SHA-256
`3bc65955dd3840eec1d9bd5cd0c3299d8db0f7bb58c3d523b217455987f3fbb1`).
The bug is invisible from the terminal: the `unzip` CLI is
forgiving about modes, but GUI extractors (Thunar, Nemo) read
the mode stored in the zip, and a `.desktop` file stored
without the exec bit is just a text file to them. S6 encodes
the rule; this tool enforces it before the upload, not after
Joshua finds it.

Run against the bad v22 zip, `check` would have printed:

```text
$ python3 release_zip_mode_checker.py check OLLAMA-SYSTEM-TEST-v22.zip
Checking OLLAMA-SYSTEM-TEST-v22.zip (14 entries)...
  install.sh                 0o100755  OK
  installer.desktop          0o100644  FAIL - needs 0o100755
Checked 2 launchers/scripts, 11 other files, 1 directory.
FAIL: 1 entry has the wrong stored mode. Fix it before uploading the Release.
```

Exit 1, the offending entry named with its stored mode. One
command, before the upload, instead of a broken Release.

## What counts as executable

The stored mode is the top 16 bits of the zip entry's
`external_attr`, and it only means something when the entry
was created on Unix (`create_system` 3). The check requires
the full mode **0o100755** (regular file, rwxr-xr-x) for every
`.sh` and `.desktop` entry:

- **0o100644** fails: stored readable, not executable.
- **0o755** (no file-type bits) fails: it extracts fine under
  the `unzip` CLI but GUI extractors drop the execute bit.
- **No stored mode** fails: an entry from a zip built on
  Windows carries no Unix mode, so nothing in the zip says it
  is executable.

Files that are not launchers or scripts are counted, not
checked: a `.py` or `.md` file may be stored however the
builder likes. Directory entries are counted and skipped.

## check

```text
python3 release_zip_mode_checker.py check <zip> [--json] [--debug-report PATH]
```

Plain-words output lists each checked entry with its stored
mode and OK/FAIL, then the counts, then the verdict. `--json`
prints the same result as JSON (modes as octal strings like
`"0o100644"`, `null` when no mode is stored, plus a
`failures` list of names) for chaining into other tools.

Exit codes: **0** every `.sh` and `.desktop` entry is stored
0o100755 (or there are none), **1** at least one is not,
**2** the check could not run (no such file, not a zip,
unreadable).

## fix

```text
python3 release_zip_mode_checker.py fix <zip> [--out PATH] [--in-place] [--debug-report PATH]
```

Rebuilds the zip with correct modes and reports each change
(`name: old mode -> new mode`) plus how many entries were
unchanged. By default it writes `<name>-modes-fixed.zip`
next to the input and never touches the input. `--out PATH`
picks the destination; writing over the input is refused
unless `--in-place` is given, which rewrites the input
through a temp file, atomically, and leaves the original
untouched if anything fails.

What fix sets:

- `.sh` and `.desktop` entries: **0o100755**, always.
- Directories: **0o40755**.
- Any other file with **no stored Unix mode** (for example
  from a Windows-built zip): **0o100644**.
- Any other file that already carries a Unix mode: **left
  exactly as stored**. Fix never strips an exec bit something
  else put there on purpose.

Contents, entry order, compression, dates, comments, and
extra fields are preserved byte for byte; only stored modes
change. The fixed zip can go straight back through `check`.

## Debug report

```text
python3 release_zip_mode_checker.py debug-report [--out PATH]
python3 release_zip_mode_checker.py check <zip> --debug-report PATH
```

Ships the T21 debug log layer (`debug_log.py`, verbatim) for
the standard report: rotating logs, crash capture, secret
scrubbing. This tool has no credentials, no network, and no
services to check; the report carries the app version and the
run's own log.

## Requirements

- Python 3, standard library only.
- No installer and no GUI: this is a script tool in the
  T28/T33/T34 family, run by the assistant or by a ship
  checklist, not something Joshua installs. (Packaging
  decision, recorded in BUILD_REPORT.md.)

## What is NOT proven

- **Never run against a real Release zip on Joshua's PC.**
  The suite proves the check and the fix against fixture
  zips built with exact stored modes, including the OST v22
  shape (a `.desktop` at 0o100644), and the tool's own
  release zip passes its own check. The first real Release
  zip it gates is the proof that matters.
- **No GUI-extractor round trip.** The claim that Thunar and
  Nemo drop the exec bit on a 0o755-no-type-bits entry comes
  from the S6 record and the OST v22 incident, not from a
  live extraction test in this build.
- **Zip comments, extra fields, and per-entry compression
  are preserved** per the suite's byte checks; exotic zip
  features (encryption, multi-disk, zip64 archives past the
  fixture sizes) are not exercised.

## Tests

```text
./run_tests.sh
```

48 tests: the check (clean, 644, bare 755, DOS-created,
zero-attr, empty, directories, case-insensitive suffixes,
plain files untouched), the CLI (exit codes, plain-words
errors, JSON shape, JSON errors), the fix (rebuild, content
and order preserved, exec bit never stripped, modeless plain
files, directory modes, default and explicit output,
overwrite refusal, in-place, in-place failure leaves the
input untouched), the debug report, the script running
without `debug_log.py`, and the packaging (the built zip's
own stored modes, no em-dash bytes in shipped files).
