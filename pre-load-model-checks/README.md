# Pre-Load Model Checks

Before a model loads, check the machine: is there enough free
RAM for it, what is running that will fight it for RAM and CPU,
and is the model even able to do the job. If something is in
the way, a picker window lists the top few heavy processes with
checkboxes, so only the ones he picks get stopped. And once a
model starts loading, a watchdog stops it if it goes quiet
instead of hanging silently.

**Plain truth:** the checks read the machine as it is right
now. RAM use changes second by second, so a check that passed
a minute ago can be out of date by load time. Run the checks
right before loading, not ahead of time.

## Where this came from

Joshua-ordered, in two threads. CODE FORGE DEV, 2026-11-15:
before a model is loaded, check the system for running
processes that will conflict with running the model, tell him
to shut them, and pop a window listing the running processes
with checkboxes to select which ones to auto-kill, only the
top 5 or 6 highest-running processes, not the whole list.
HICKSFIELD, 2026-11-15: never load a model that will run a
while and do nothing, never hang silently when a model goes
quiet. The RAM check before loading each model was OST's P0
ask. The tool is the three asks in one chain.

## Install

Double-click **Install Pre-Load Model Checks**. It installs
everything the app needs into a private folder, adds Pre-Load
Model Checks to the app menu and the desktop, and asks if you
want to open it. No terminal needed.

The checks need no system program: they read `/proc`, which is
always there. The only download is the interface toolkit for
the picker window.

To remove it, run the uninstaller in the install folder
(`uninstall.sh`). It removes the app, the menu entry, the
desktop icon, and the logs folder.

## The chain

Run the checks in this order, right before loading a model:

```
ram-check -> process-check -> suitability-check -> load
                |                                  |
                +-- conflicts? --> kill-picker ----+
                |
                +-- load it under model-watchdog
```

1. **ram-check**: does the model fit in free RAM?
   `ram-check --require 4.5GB` answers yes or no, and how
   short it is when it does not fit. 1 GB is kept back for
   the system by default (`--reserve 0` to keep none).
   Exit 0 fits, 1 does not.
2. **process-check**: what is running that will fight the
   model? Lists the top 6 by RAM and CPU, plain text or
   `--json`. Kernel threads and PID 1 are never listed.
3. **suitability-check**: can this model do this job? A
   model card (what the model can do) against the task
   (what the job needs). When the model cannot do it, it
   says so before anything loads. Exit 0 suitable, 1 not.
4. **kill-picker**: when step 2 finds conflicts, the
   window lists the top 6 processes you can actually stop,
   with checkboxes. Tick the ones you do not need and press
   Kill selected. Only the ticked ones are stopped, and only
   after you confirm.
5. **model-watchdog**: load the model under it:
   `model-watchdog --quiet-seconds 60 -- ollama run example`.
   If the load prints nothing for 60 seconds, it is stopped
   and the watchdog says so, instead of hanging silently.
   The model's own exit code passes through when it finishes
   on its own; 124 means the watchdog stopped it for going
   quiet.

Each step also runs alone: `ram-check`, `process-check`,
`suitability-check`, `kill-picker`, and `model-watchdog` are
separate commands, and `preloadchecks-cli` carries every
command (`preloadchecks-cli --help`). `preload-checks` opens
the picker window with no arguments, and runs the command line
with arguments.

## The kill-picker window

The window shows free RAM at the top (and whether a model
fits, with `kill-picker --require 4.5GB`), then the top 6
heaviest processes you can stop, each with a checkbox, its
RAM use, and its CPU use. Refresh re-reads the machine. Kill
selected asks once, listing exactly what will be stopped,
then stops only those.

What can never be stopped, even if a PID is handed in
directly:

- PID 1 (it runs the whole system)
- this tool itself, or the shell that started it
- kernel threads
- system processes: systemd, the desktop, the display
  server, the login manager, ssh
- processes owned by another user

A stop is polite first (SIGTERM), then forced (SIGKILL) after
3 seconds when the process does not stop on its own.
`--dry-run` reports what would be stopped and touches nothing.

## Model cards

A model card is a JSON file saying what the model can do:

```json
{
  "name": "example-7b",
  "size_gb": 4.5,
  "capabilities": ["chat", "code"],
  "context_tokens": 32768
}
```

Task requirements are a JSON file too:

```json
{
  "needs_capabilities": ["code"],
  "min_context_tokens": 8192,
  "max_size_gb": 6
}
```

Or pass them on the command line:

```
suitability-check --card card.json --needs-capability code \
  --min-context 8192 --max-size 6GB
```

Add `--check-ram` to also check the model fits in free RAM.
Any field may be left out; a missing field is simply not
checked. When the card says nothing about capabilities at all,
the check warns that it cannot prove the model fits the task.

## Judgment calls (documented, not hidden)

- **Conflict score:** RAM in MB, plus 100 MB per 1% of one CPU
  core. A process burning a whole core counts like 10 GB of
  RAM pressure; a quiet 2 GB process counts as 2 GB. RAM is
  the binding constraint when a model loads, CPU second.
- **1 GB reserve:** ram-check keeps 1 GB back for the system
  by default. A model that eats every last byte will thrash,
  not run. Override with `--reserve`.
- **Sizes are 1024-based:** 1 GB = 1024 MB, matching how
  `/proc/meminfo` counts. A plain number means GB.
- **Top 6, not 5:** Joshua said "top 5 or 6". The picker
  shows 6; `process-check --limit` takes 1 to 20.
- **Watchdog and buffering:** a program that buffers its
  output looks quiet even while it works. Run Python programs
  unbuffered (`python3 -u`) under the watchdog.

## Debug report

`preloadchecks-cli debug-report` prints the debug report: app
version, how many processes are visible, free RAM. No network,
no secrets. Logs live under
`~/.local/share/pre-load-model-checks/logs`.

## Tests

`./run_tests.sh` runs the full suite: 160 tests, offscreen GUI
tests included. The real-kill tests stop throwaway processes
the suite spawns itself, and nothing else.
