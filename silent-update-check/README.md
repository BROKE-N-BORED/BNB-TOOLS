# T36 - silent-update-check

Pairs with skill **S84** (silent-update-check: the standing
order).

One droppable Python module that gives any project the silent
update check + ask-first auto-update: on launch, the app
silently checks its GitHub repo for a newer Release. Up to
date: nothing happens, no popup, no noise. Update exists: a
popup asks, and only on the user's tap does the app pull. The
pull verifies the release's checksum/sidecar before installing,
never a blind download. After the pull it asks "restart now to
complete the update, yes or no": Yes restarts with the update
applied, No waits for the next restart, and the staged update
survives until then with no re-download.

## Why it exists

Main chat, 2026-11-17 ~15:53-15:56. Joshua ordered every
project to get this flow, and it was broadcast to 26 build
threads the same day. Ten-plus projects then hand-rolled the
same thing separately (MIMIK's U1 update.py, Android Photo
Transfer's 656-line engine, SOLDAR's server module). This is
the one shared implementation, so the next project copies one
file instead of writing its own updater.

WinLinx v0.4 was the first to ship the flow; Pixel Forge v0.69
is the named model for the notify half (Help menu check +
opt-in startup check). Web apps and spaces are exempt from the
order (always current on load), so note it and move on.

## The four pieces

Small, chainable, each runnable and testable alone, each a
function and a CLI subcommand:

| Piece | Function | What it does |
| --- | --- | --- |
| 1. check | `check_for_update()` | Silent launch check vs the GitHub Latest Release. One API request, no auth, no output of its own. |
| 2. pull-verify | `pull_update()` | Downloads the asset + its checksum sidecar into staging, verifies the SHA-256, extracts. Installs nothing. |
| 3. install-swap | `apply_staged_update()` | Rename-based swap: the current app moves to the backup slot, the staged version moves in. A failed swap puts the old version back. |
| 4. restart-prompt | `ask_restart()` + `restart_now()` | Asks the restart question through the caller's popup; Yes applies the staged update and re-execs the app, No leaves the staged update waiting. |

The chain, the way a launch wires it:

```text
launch -> apply_pending_on_launch()   (a staged update from last time?)
       -> check_for_update()          (silent; nothing happens if current)
       -> popup asks to pull          (only on an update; your popup)
       -> pull_update()               (verified, staged, nothing installed)
       -> ask_restart()               ("restart now, yes or no?")
       -> Yes: restart_now()          (applies, re-execs)
       -> No:  nothing more           (next launch applies it, no re-download)
```

## Dropping it into a project

Copy `silent_update_check.py` into the project (and
`debug_log.py` next to it if you want the debug report; the
module works without it). Standard library only, no new
dependencies. Then wire the launch, in the project's own code:

```python
import silent_update_check as suc

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = suc.default_state_dir(APP_DIR)  # APP_DIR + ".update"

# At startup, before anything else: a staged update from last
# time (the user said No to the restart prompt) applies now.
suc.apply_pending_on_launch(APP_DIR, STATE_DIR)

# The silent check: one API request, no auth, no output.
result = suc.check_for_update("BROKE-N-BORED/MY-PROJECT",
                              CURRENT_VERSION)
if result["status"] == "update-available":
    if popup_asks_user_to_pull(result):   # your Qt popup
        pulled = suc.pull_update(result, STATE_DIR)
        if pulled["status"] == "staged":
            if suc.ask_restart(popup_asks_yes_or_no):
                suc.restart_now(APP_DIR, "main.py", STATE_DIR)
```

The module never shows UI of its own: the caller owns the
popups, the module owns the question and the meaning of the
answer. `ask_restart()` takes a function that shows the
question and returns True for Yes, False for No.

The check reads the current version from the caller. Pass it
directly, or keep a `VERSION` file in the app dir and let
`read_version()` read it. Version strings compare as semver
(a leading `v` is ignored, `1.2` equals `1.2.0`, a release
beats the same version with a pre-release suffix).

## Partial implementations: only build what is missing

A project that already has part of the flow imports only the
pieces it lacks. The GITDATA case: notify-only already
existed, so it needed pull-verify, install-swap, and
restart-prompt, and nothing else. `missing_pieces()` answers
the question in code:

```python
suc.missing_pieces(has_check=True)
# ['pull-verify', 'install-swap', 'restart-prompt']
```

Each function stands alone: `check_for_update()` needs no
state dir, `pull_update()` needs only a check result and a
state dir, `apply_staged_update()` needs only the app and
state dirs, `ask_restart()` needs only a prompt function.

## Multi-platform repos

Only the matching platform's releases are ever offered. The
case that proved the need: Android Photo Transfer's repo
holds Windows releases too, and a Linux install must never be
offered the Windows file. Asset names are matched by platform
markers (`linux`, `win64`, `mac`, `android`, `.exe`, `.dmg`,
`.apk`, and friends); an asset with no marker is generic and
matches every platform. Among the matches, `.zip` wins, then
`.tar.gz`, then anything else. A newer release with no asset
for this platform reports `no-release-for-platform`, not an
update and not an error.

## No blind downloads

The pull refuses unless the release carries a checksum sidecar
for the asset: a `<asset>.sha256` file, or a shared `SHA256SUMS`
/ `checksums.txt` that names the asset. The sidecar may hold a
bare hash or sha256sum lines (`<hash>  <filename>`). If the
downloaded bytes do not match the checksum, the staged files
are deleted and nothing installs. If the release has no usable
checksum, the pull refuses with a plain message saying the
release needs a sidecar. There is no flag to skip this.

Only `.zip` releases install in v0.1.0. A `.tar.gz` asset is
picked honestly (it is a real release file) and reported as
`unsupported-format` by the pull, not silently skipped.

## State, staging, and the swap

Everything the updater owns lives in a sibling directory next
to the app, named `<app>.update` (`default_state_dir()`):

```text
my-app/            the installed app (VERSION, main.py, ...)
my-app.update/     the updater's dir (a sibling, never swapped)
  state.json       current version, staged version, pending flag
  staging/         the verified download + extracted new version
  backup/          the previous version (one generation)
  failed/          the version a rollback moved aside
```

A sibling, not a child, so the swap never touches it: the
staged update and the state file survive the swap and the
restart that follows. `state.json` is written atomically (temp
file + rename), so a crash mid-write leaves the old state or
the new state, never half a file.

The swap is rename-based on one filesystem: the current app
moves to `backup/`, the staged version moves into its place.
If the second rename fails, the backup moves straight back,
so the app is never left half-installed, and the state file
still says pending, so the next launch retries. The previous
version stays in `backup/` for `rollback()`, which restores it
and moves the broken version aside to `failed/`.

One honest limit: the swap renames the app directory, so an
app that writes runtime files into its own dir (logs, caches)
will write into the renamed backup dir after a swap until it
restarts. Keep runtime writes in the state dir or the home
dir, not the app dir.

## CLI

Every piece is also a subcommand, for driving by hand and for
chaining into other tools:

```bash
python3 silent_update_check.py check OWNER/REPO --current 0.1.0
python3 silent_update_check.py check OWNER/REPO --current 0.1.0 --json
python3 silent_update_check.py check OWNER/REPO --app-dir /path/to/app --quiet
python3 silent_update_check.py pull OWNER/REPO --current 0.1.0 --app-dir /path/to/app
python3 silent_update_check.py install --app-dir /path/to/app
python3 silent_update_check.py apply-pending --app-dir /path/to/app
python3 silent_update_check.py rollback --app-dir /path/to/app
python3 silent_update_check.py restart --app-dir /path/to/app --entry main.py
python3 silent_update_check.py run OWNER/REPO --current 0.1.0 --app-dir /path/to/app
python3 silent_update_check.py debug-report [--out PATH]
python3 silent_update_check.py --help
```

`--current` may be left off when `--app-dir` has a `VERSION`
file. `--platform` (default `linux`) picks which platform's
assets to offer. `--state-dir` overrides the default sibling
dir. `--quiet` on `check` prints nothing when up to date (the
silent launch shape). `--json` on `check` prints the result
as JSON.

`run` is the whole chain: check, ask to pull, pull, ask to
restart, restart. Each ask is a real prompt on stdin; nothing
downloads or restarts without a Yes. `restart --yes` /
`--no` answer without asking (for scripts).

Exit codes: 0 the step did what it should, 1 nothing to do
(up to date, no update pulled, no staged update, user said
no), 2 the step could not run (no network, repo not found,
rate limited, checksum mismatch, no checksum, bad input).
Errors are plain words naming the missing thing, never a
traceback. The Python version guard (3.8+) is the same shape:
a plain message naming the Python version, exit 1.

## The demo

`demo.py` proves each piece standalone and chained, with no
network: a fake local release server (an HTTP server on
localhost) stands in for GitHub, and a fake app (a temp dir
with a VERSION file and a tiny entry point) stands in for a
real project. The restart step never actually replaces the
demo process: it passes a recorder in place of `os.execv`
and prints what the restart would have run.

```bash
python3 demo.py                 # full chain, restart Yes
python3 demo.py --answer no     # full chain, restart No, then
                                # a second "launch" applies the
                                # staged update, no re-download
python3 demo.py --pieces        # each piece alone, one at a time
```

## Rate limits

The launch check makes exactly one API request. If GitHub
answers that the rate limit is reached, the check stops
cleanly, names the reset time, and never retries. (A 404 on
the releases call costs one extra request, a repo-exists
probe, so "no releases yet" and "no such repo" report
differently. That is the error path only; the normal launch
check is one request.)

## Requirements

Python 3.8+, standard library only. No git binary, no token,
no login, no account. Public repos only: this module sends no
auth of any kind, so a private repo answers 404 or 403 to an
unauthenticated request and the check reports that as "could
not check" rather than guessing. If you need private repos,
that is a different tool with a credential flow, not a flag
on this one.

The debug log layer is imported lazily: importing the module
for a launch check never pays the debug layer's import cost.
Only `debug-report` touches it.

## Debug report

```bash
python3 silent_update_check.py debug-report [--out PATH]
```

Writes a debug report through the T21 debug log layer
(`debug_log.py`, copied unmodified, SHA-256 pinned in the
tests). The log dir is a temp dir, so no `logs/` directory
is left behind. The module has no credentials, so there is
nothing secret to scrub, and the layer scrubs secret-shaped
values anyway.

## Smoke test

```bash
bash run_tests.sh
```

No live network: every network test runs against a local fake
release server (the T30/T33 pattern). Covers version
comparison, platform matching (including the multi-platform
repo case and the `twin`/`win` token trap), asset picking,
checksum parsing (bare hash, sha256sum lines, shared sums
file), the check (up to date, update available, no releases,
repo not found, rate limit with reset time named and exactly
one request, 500, bad JSON, no network, no Authorization
header), the pull (happy path, checksum mismatch deletes
staging, no sidecar refuses, bad zip, zip-slip refused,
unsupported format, second pull replaces first), the swap
(happy path, backup kept, nothing staged, failed swap puts
the old version back, first install, pending survives until
launch), the restart ask (Yes/No, the exact question text,
real exec through the CLI), launch apply and rollback, the
full chain both ways (Yes restarts, No stages for the next
launch with no re-download), the partial-implementation
helper, the Python version guard, the CLI (help, version,
JSON, quiet, plain-word errors), the demo in all three modes,
the unmodified debug log layer (SHA-256 pinned), stdlib-only
imports, the no-em-dash rule, and the release zip modes.

## What it does not do

- It does not show UI. Popups belong to the calling app; the
  module owns the question and the answer, never the window.
- It does not check private repos. See above.
- It does not install `.tar.gz` releases in v0.1.0. Only
  `.zip`. A tarball release is reported, not silently skipped.
- It does not watch for updates on a schedule or in the
  background. It checks when the app calls it, at launch.
- It does not verify a release beyond its checksum: the
  checksum proves the download is what the release shipped,
  not that the release itself is good.
- It does not roll back automatically. `rollback()` exists
  and the backup is kept, but the decision to roll back stays
  with the app (or the user).
