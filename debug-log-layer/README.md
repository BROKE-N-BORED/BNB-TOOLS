# debug-log-layer

Drop-in debug log layer for any BNB project: timestamped logging to
a rotating file, a ring buffer of the last actions before an error,
error capture with full tracebacks, a context snapshot, and a debug
report — on demand or automatically on a crash — in the standard
format, scrubbed of secrets and safe to email.

Pairs with BNB SKILLS **debug-log-layer** (S61), which is the
standard this module implements.

## What it does

- `DebugLogger(app_name, version, log_dir="logs")` — one logger per
  app. Logs to `logs/<app>.log` with a `RotatingFileHandler`
  (default 1 MB x 3 files, so the log can never eat the disk) and
  timestamps on every line.
- `log.action(text)` records a user/system step in a ring buffer
  (default last 200) — the "what was it doing just before it broke"
  section of the report.
- `log.exception(msg)` logs an error with the current exception's
  full traceback; the last 20 errors are kept for the report.
- `log.set_setting(key, value)` registers a setting that affects
  behaviour (which model/provider, which mode). Values are scrubbed
  at report time — only present/absent survives for secrets.
- `log.register_service(name, check)` registers a dependency to
  status-check in the report. `check_ollama()` is included: it
  reports Ollama as running (with loaded models) or not reachable,
  with a 2-second timeout so a dead service cannot stall the report.
- `log.register_dependency(package)` records an installed package
  version (or "not installed") in the report.
- `log.generate_report(path=None)` writes
  `debug-report-<app>-<YYYYMMDD-HHMMSS>.txt` (default: the log
  dir; pass a path to put it in the project folder where he can
  find it). Two reports in the same second get `-2`, `-3` suffixes
  instead of overwriting each other.
- `log.install_crash_handler()` installs a `sys.excepthook` that
  writes a report on any unhandled exception, then re-raises the
  crash as normal. The report must never hide the crash itself.
- `scrub_text` / `scrub_dict` redact API keys, tokens, passwords,
  auth headers, `sk-` keys, GitHub tokens, and `user:password@` in
  URLs. Every log line and every report passes through them.

## Report format

One plain-text file, same sections in every project:

```
DEBUG REPORT — <app> <version>
Generated: <iso timestamp>
== Context ==      app, OS, Python, RAM, disk, dependencies
== Settings ==     scrubbed settings (present/absent for secrets)
== Services ==     one status line per registered service
== Recent actions ==  last N actions/steps
== Errors ==       captured errors with full tracebacks
== Log tail ==     last 200 log lines, scrubbed
```

If the logs are large, zip the report + the log files; the report
itself stays one file.

## Usage

Library (drop `debug_log.py` into the project):

```python
from debug_log import DebugLogger, check_ollama

log = DebugLogger("duo", "0.3.1", log_dir="logs")
log.register_service("ollama", check_ollama)
log.set_setting("model", "qwen3.5:2b")
log.install_crash_handler()

log.action("user pressed Send to Both")
log.info("relay started")
try:
    run_relay()
except Exception:
    log.exception("relay failed")

path = log.generate_report()  # from a "Generate debug report" button
```

One command (from the project folder, no code needed):

```bash
python3 debug_log.py report --app duo --version 0.3.1
python3 debug_log.py report --app duo --out ./debug-report.txt --ollama
```

The report is a single attachment for broke.n.bored.studio@gmail.com
— complete enough to diagnose from the report alone.

## Smoke test

```bash
python3 tests/smoke_test.py
```

26 checks, no network needed (the Ollama check points at a closed
port): scrubbing of keys/tokens/passwords/headers in text and dicts,
context collection, report sections + filename, traceback capture,
ring-buffer size, secret-free reports, timestamped lines, rotation
cap, crash-handler report, CLI report command.

## Source

Built from Joshua's order (main chat, 2026-11-12 ~20:22): a debug
and logging layer in every project build, triggered by the DUO case
the same evening — Ollama died silently on his PC and there was
nothing to diagnose from. The Ollama service check exists because
of that case.

## Requirements

Python 3, standard library only. No network needed except the
optional Ollama localhost check.
