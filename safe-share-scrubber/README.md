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

## How to use the window

1. **Add files:** drag text or log files onto the window, or use
   File, Add files. You can add several at once. Binary files are
   skipped and the report says so.
2. **Press Verify** to check the files without changing anything.
   It lists the secrets found, by kind and line number, and
   writes no files at all.
3. **Press Scrub** to redact what was found. Each file gets a safe
   copy next to it, with ".safe" in the name, and a short report
   file. Your original is never changed or overwritten.
4. **Read the report on the right.** It lists the secrets found,
   by kind and line number, and a plain verdict. It never shows
   the secret itself.
5. **Share the safe copy, not the original.** The safe copy has
   every secret the scrubber found replaced with a marker like
   [REDACTED AWS KEY].
6. **Read the safe copy once** before you share it. The plain
   truth above still applies.

The How to Use window (Help menu) carries the same steps inside
the app.

## The chain: scrub, verify, view

Each step is its own command and runs alone from the terminal.
The window runs these same commands and shows their results, so
the window and the terminal always agree.

```
safe-share-scrub file.txt      # scrub: redact, write the safe
                               # copy and the report
safe-share-verify file.txt     # verify: scan only, writes nothing.
                               # Exit 0 when clean, 1 when a secret
                               # is found, 2 when a file could not
                               # be scanned
```

The full check in one line: scrub a file, then prove the safe
copy reads clean:

```
safe-share-scrub file.txt && safe-share-verify file.safe.log
```

The full command carries every subcommand, and works while the
window is open:

```
safe-share-scrubber scrub file.txt
safe-share-scrubber verify file.txt
safe-share-scrubber debug-report
```

`safe-share-scrubber --help` lists every option. Both `scrub`
and `verify` take `--json` to print the results as JSON instead
of the human report.

## What it catches

Eleven secret shapes, each replaced with a labeled marker:

1. AWS access keys
2. JSON Web Tokens (JWTs)
3. Private keys, PEM blocks including OpenSSH headers, spanning
   several lines
4. GitHub tokens (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`,
   `github_pat_`)
5. Slack tokens
6. Google API keys
7. Bearer tokens (the word Bearer stays, the token goes)
8. Passwords and secrets in assignment form, like `password = ...`
   or `"password": "..."` in JSON (the key name stays)
9. Passwords in URLs, like `https://user:password@host` (the user
   and host stay)
10. Secrets in URL query strings, like `?api_key=...` (the
    parameter name stays)
11. Bare high-entropy tokens: `sk-...` and other long runs of
    mixed-case letters and digits. A bare hex string only counts
    when it sits next to a key-ish word.

After redaction the text is scanned again. The verdict "Safe to
share" is given only when zero secrets remain.

## What it leaves alone

These look secret-shaped but are not secrets, and are left
untouched:

- A git commit hash sitting in a sentence
- A UUID
- A normal URL, including one with a port number
- The word "password" in ordinary prose
- A base64 blob that decodes to readable text (treated as data,
  not a token)

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
bash safe-share-scrub --help
bash safe-share-verify --help
bash run_tests.sh   # run the test suite
```

## A note on the test files

The tests use obviously fake values, like `FAKE-KEY-1234`, so
nothing in the code or the tests is a real secret.
