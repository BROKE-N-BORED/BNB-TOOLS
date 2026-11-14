# Safe Share Scrubber

Safe Share Scrubber finds secrets hiding in a file, like API keys,
passwords, and tokens, and replaces each one with a labeled marker
before you share the file with anyone. It shows you what it found,
by kind and line number, and writes a clean copy. Your original
file is never changed.

**Plain truth:** the app finds secrets by matching known patterns,
so it can only catch the kinds of secrets it knows how to look
for. It cannot prove a file holds no secret it has no pattern
for. Always read the clean copy once before you share it.

## Install

Double-click **Install Safe Share Scrubber**. It installs
everything the app needs into a private folder, adds Safe Share
Scrubber to the app menu and the desktop, and asks if you want to
open it. No terminal needed.

To remove it, run the uninstaller in the install folder
(`uninstall.sh`). It removes the app, the menu entry, the desktop
icon, and the logs folder. The app keeps nothing else of yours.

## How to use

1. **Add files:** drag text or log files onto the window, or use
   File, Add files. You can add several at once. Binary files are
   skipped and the report says so.
2. **Press Scrub.** Each file gets a safe copy next to it, with
   ".safe" in the name, and a short report file. Your original is
   never changed or overwritten.
3. **Read the report on the right.** It lists the secrets found,
   by kind and line number, and a plain verdict. It never shows
   the secret itself.
4. **Share the safe copy, not the original.** The safe copy has
   every secret the scrubber found replaced with a marker like
   [REDACTED AWS KEY].
5. **Read the safe copy once** before you share it. The plain
   truth above still applies.

The How to Use window (Help menu) carries the same steps inside
the app.

## Command line

The command line works while the window is open:

```
safe-share-scrubber scrub file.txt
safe-share-scrubber debug-report
```

`safe-share-scrubber --help` lists every option.

## If something breaks

File, Generate debug report (or `debug-report` on the
command line) writes a report file with the app version, the
computer details, the settings, and the recent actions and errors.
It never contains passwords or keys. Send it to
broke.n.bored.studio@gmail.com.

## What it needs

- Linux Mint (or any Linux with Python 3)
- Nothing paid, no accounts, and the app never uses the network
  at all. The installer downloads the interface toolkit once, then
  the app works fully offline.

## For advanced users (terminal route, optional)

The installer and the app never need a terminal. If you prefer one
anyway:

```
bash install.sh     # install
bash run.sh         # open the window
bash scrubber-cli --help
bash run_tests.sh   # run the test suite
```

## A note on the test files

The tests use obviously fake values, like `FAKE-KEY-1234`, so
nothing in the code or the tests is a real secret.
