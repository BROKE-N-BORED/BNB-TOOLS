# Changelog

## 0.1.0 (2026-11-17)

First release.

- ram-check: free RAM against a model size, 1 GB reserve kept
  back for the system by default.
- process-check: the top 6 conflicting processes by RAM and CPU,
  plain text or JSON.
- suitability-check: a model card against the job it is meant
  to do; warns instead of loading a model that cannot do it.
- kill-picker: a window with the top 6 stoppable processes and
  checkboxes; only the ticked ones are stopped, and only after
  confirmation. PID 1, our own process tree, kernel threads,
  system processes, and other users' processes can never be
  stopped.
- model-watchdog: runs a command and stops it if it goes quiet
  for too long, instead of hanging silently.
