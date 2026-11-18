# Changelog

## v0.1.0 - 2026-11-17

First release.

- Engine-agnostic runner (`model_chat_smoke_test.py`): runs a
  canned chat through each model on the project's own engine, no
  Ollama, no model loading. The engine is a command template with
  `{model}` and `{prompt}` placeholders, both required; values are
  shell-quoted before substitution. One engine call per model per
  prompt; a model passes only when every prompt gets a non-empty
  reply inside `--timeout` (default 60 seconds).
- Verdicts per model: pass, timeout (hung past the timeout, killed
  as a whole process group), error (non-zero exit or failed start,
  stderr in the report), empty (blank reply in time). Worst
  verdict wins across a model's prompts; per-prompt detail stays
  in the report.
- Report as plain text on stdout, JSON with `--format json`, and
  `--json FILE` writes the JSON report to a file as well. Exit 0
  when every model passes, 1 when any fails, 2 for a usage or
  config problem.
- Chain steps runnable alone: `--dry-run` prints the exact
  commands without running anything; `--list-prompts` prints the
  canned prompts (built-in three, or `--prompts FILE`).
- Models from `--models` or `--models-file FILE` (one per line,
  `#` comments and blank lines skipped). Prompts from `--prompts
  FILE` the same way.
- Pre-flight engine guard: the command at the start of the
  template must exist before any model runs. A missing command is
  a plain-words error naming the command, exit 1, never a
  traceback (the T31 missing-dependency guard pattern). Shell
  builtins and env assignments skip the check.
- Mock engine (`tests/mock_engine.py`): a labeled test fixture
  that replies, hangs, errors, or stays silent on demand, plus an
  `auto` mode that picks behavior from the model or prompt name.
  The tool itself never calls it.
- Installer (`install.sh` + "Install Model Chat Smoke
  Test.desktop"): checks Python 3, adds the app menu entry and
  desktop icon, links `model-chat-smoke-test` onto PATH, verifies
  before reporting success. Stdlib only, nothing to download. The
  installer Exec line is byte-identical to the fixed S6 desktop
  template. `uninstall.sh` removes the menu entry, desktop icon,
  command link, and logs folder.
- Debug report (`--debug-report`): the T21 debug log layer,
  copied unmodified (SHA-256 pinned in the tests). Normal runs
  never touch it and never create a `logs/` dir.
- 46 tests, no network, no real model: every run goes through the
  mock engine fixture.
