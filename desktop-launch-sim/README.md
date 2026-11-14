# T25 — desktop-launch-sim

Simulate what happens when the user double-clicks an installed
`.desktop` launcher: place the launcher in a different folder from the
program (simulating the Desktop), launch it from an unrelated working
directory with `%k` expanded to the placed path, and report whether the
app actually starts.

## Why

ACR v0.8 shipped a desktop icon that did nothing when clicked — the icon
sat on the Desktop and looked for the program next to itself, while the
program was in the folder the user unzipped (ACR DEV, 2026-11-13 17:51:
"when I click on the icon, it doesn't open"). The app runs fine from its
own folder, so no unzip or clone check caught it. v0.8.1 fixed it by
pointing the icon straight at the program, verified by "the new launch
simulation — a fake install with the icon in a different folder, run from
another directory, and the app actually starts and logs it" (2026-11-13
18:07). This tool is that simulation, automated.

## What it does

- Copies the `.desktop` file into a fresh place-dir (the simulated
  Desktop) and runs its Exec line from an unrelated cwd — the same
  geometry as a real install.
- Expands `%k` to the placed `.desktop` path, as a desktop environment
  does. A launcher that resolves its program relative to `%k` therefore
  fails here exactly as it fails on the user's Desktop.
- Runs the command without a shell (shlex split), watches it for a probe
  window (default 3 s), and reports:
  - **STARTED** — still running at the end of the probe window. Pass.
  - **FAILED** — exited quickly (nonzero code, or code 0 at once), or
    could not be started. The report includes the exit code and the
    tail of stderr.
- `--expect-marker PATH` additionally requires the app to write a marker
  file — proves the app actually ran its startup code, not just that
  some process stayed alive.
- A `.desktop` file with no Exec= line is a usage error (exit 2), not a
  FAILED.

## Usage

```
python3 launch_sim.py path/to/app.desktop
python3 launch_sim.py path/to/app.desktop --expect-marker /tmp/app-started
python3 launch_sim.py path/to/app.desktop --probe-seconds 5
```

Exit code 0 on STARTED, 1 on FAILED, 2 on usage error.

## Smoke test

`tests/smoke_test.py` — three fixtures, all headless Python stubs (no
display, no network):

1. Good absolute-path launcher → STARTED, marker written.
2. Broken `%k`-relative launcher (the ACR v0.8 bug shape: program looked
   up next to the placed icon) → FAILED, detected.
3. `.desktop` with no Exec= line → usage error (exit 2).

Run it:

```
python3 tests/smoke_test.py
```

Smoke test result (run 2026-11-13 ~20:05 EST, sandbox, Python 3):
3/3 fixtures passed — good launcher STARTED with marker, broken
`%k`-relative launcher FAILED as expected, missing Exec= line gave the
usage error (exit 2).

## Limits

- The probe window only proves the app starts and stays up for a few
  seconds; it does not prove the window renders correctly. Pair it with
  the Qt proof harness (S63) for that.
- A launcher that starts a detached daemon and exits at once reads as
  FAILED — that shape needs `--expect-marker` on a file the daemon
  writes, or a longer probe against the daemon itself.
- Stdlib only. No network, no display, no dependencies.

## Where this comes from

- ACR DEV thread (f9230b1c), 2026-11-13 17:51–18:09 EST: the v0.8 desktop
  icon did nothing on click; v0.8.1 fixed it (one line: icon points
  straight at the program) and verified it with a launch simulation.
  Pairs with S6 (linux-release-packaging) and the T11
  fresh-unzip-verification launch-simulation check.
