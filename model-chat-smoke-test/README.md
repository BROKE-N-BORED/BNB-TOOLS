# T38 - model-chat-smoke-test

Run a canned chat through each model on a project's own engine and
report pass/fail per model. Small, single-purpose, chainable: one
stdlib-only script, no Ollama, no model loading, no network, no GUI.

## Why it exists

FYRN, Tue 2026-11-17 ~07:49. Joshua confirmed ("Both"): he wants
a chat app for his own engine AND a smoke test that runs a canned
chat through each model on that engine and produces a pass/fail
report. The chat app half belongs to FYRN-CHAT, his own repo. This
tool is the smoke-test half, standing alone: give it your engine's
command and your model names, and it tells you which models answer
and which hang, error, or stay silent.

## The chain

Four steps, each runnable alone where it makes sense:

1. **Define the engine command.** A command template with two
   placeholders: `{model}` for the model name, `{prompt}` for one
   canned prompt. Example (FYRN-style, replace with your engine's
   real command):

   ```bash
   --engine "fyrn chat --model {model} --prompt {prompt}"
   ```

   Both placeholders are required: without `{model}` every model
   would run the same command and the test would prove nothing.
   Values are shell-quoted before substitution, so spaces and
   quotes in a model name or prompt cannot break the command.

2. **List the models.** `--models` on the command line, or
   `--models-file FILE` with one model per line (`#` comments and
   blank lines skipped).

3. **Run the canned chat.** One engine call per model per prompt.
   `--dry-run` prints the exact commands that would run, without
   running anything: check the template before spending real time.
   `--list-prompts` prints the canned prompts (built-in three, or
   your `--prompts FILE`) without running anything.

4. **Read the report.** Plain text on stdout by default, JSON with
   `--format json`, and `--json FILE` writes the JSON report to a
   file as well. Exit 0 when every model passes, 1 when any model
   fails.

## Usage

```bash
python3 model_chat_smoke_test.py --engine "fyrn chat --model {model} --prompt {prompt}" --models tiny-1b tiny-2b
python3 model_chat_smoke_test.py --engine "CMD" --models-file models.txt --timeout 120
python3 model_chat_smoke_test.py --engine "CMD" --models a b --prompts my-prompts.txt --json report.json
python3 model_chat_smoke_test.py --engine "CMD" --models a --dry-run
python3 model_chat_smoke_test.py --list-prompts
python3 model_chat_smoke_test.py --debug-report
```

| Option | Default | What it does |
| --- | --- | --- |
| `--engine CMD` | (required) | Engine command template with `{model}` and `{prompt}` |
| `--models M...` | | One or more model names |
| `--models-file FILE` | | Model names from a file, one per line |
| `--prompts FILE` | built-in 3 | Canned prompts from a file, one per line |
| `--timeout SECONDS` | 60 | Seconds allowed per engine call before it is killed as hung |
| `--format text\|json` | text | Report format on stdout |
| `--json FILE` | | Also write the JSON report to FILE |
| `--dry-run` | off | Print the commands that would run, run nothing |
| `--list-prompts` | off | Print the canned prompts, run nothing |
| `--debug-report` | off | Write a debug report instead of running |
| `--version` | | Print the version |
| `--help` | | Print usage, exit 0 |

The built-in canned chat is three short prompts any working chat
model answers:

1. `Hello. Reply with one short sentence.`
2. `What is 2 + 2? Reply with the number only.`
3. `Name one color. Reply with the color only.`

## The report

One line per model, per-prompt detail underneath, summary at the
end:

```
tiny-1b: PASS (1 seconds)
  PASS 0s - Mock reply from tiny-1b to: Hello. Reply with one short sentence.
  PASS 0s - Mock reply from tiny-1b to: What is 2 + 2? Reply with the number only.
  PASS 0s - Mock reply from tiny-1b to: Name one color. Reply with the color only.
tiny-2b: TIMEOUT (180 seconds)
  TIMEOUT 60s - timed out after 60 seconds
  TIMEOUT 60s - timed out after 60 seconds
  TIMEOUT 60s - timed out after 60 seconds
Summary: 1 of 2 models passed
```

(The example above is the test mock, not a real engine: see the
worked example below.)

Verdicts, per model:

- `pass`: every prompt got a non-empty reply inside the timeout.
- `timeout`: at least one prompt hung past `--timeout` and was
  killed. A hung engine is killed as a whole process group, so a
  stray engine cannot keep running in the background after the
  timeout. A hung model costs one timeout per prompt: three
  prompts at 60 seconds is three minutes for that model.
- `error`: at least one engine call exited non-zero or failed to
  start. The engine's stderr (first 500 characters) is in the
  report, so the reason is visible.
- `empty`: at least one prompt got an empty or whitespace-only
  reply in time.

When a model's prompts disagree, the worst verdict wins: timeout
beats error, error beats empty, empty beats pass. The per-prompt
detail stays in the report either way, so the roll-up hides
nothing.

The JSON report carries the same verdicts plus the engine
template, the timeout, the prompts used, start/finish times, and
per-prompt seconds and reply previews (first 200 characters).

## Worked example: all four verdicts, against the test mock

The test suite ships a mock engine (`tests/mock_engine.py`) that
replies, hangs, errors, or stays silent on demand. It is a test
fixture, clearly labeled, not a demo path in the real tool: the
tool itself never calls it. It is useful here to show what the
report looks like before you point the tool at a real engine:

```bash
python3 model_chat_smoke_test.py \
  --engine "python3 tests/mock_engine.py --mode auto --model {model} --prompt {prompt}" \
  --models good bad-hang bad-error bad-empty \
  --prompts tests/one-prompt.txt --timeout 10
```

(`--mode auto` picks the behavior from the model name: a name
containing HANG hangs, ERROR errors, EMPTY stays silent, anything
else replies. `tests/one-prompt.txt` is a one-line prompts file
the suite uses to keep hang tests fast. The 10-second timeout
gives a slow machine room to start the engine: a timeout shorter
than the engine's own startup time would flag a working engine as
hung.)

Output:

```
good: PASS (0 seconds)
  PASS 0s - Mock reply from good to: hello
bad-hang: TIMEOUT (10 seconds)
  TIMEOUT 10s - timed out after 10 seconds
bad-error: ERROR (0 seconds)
  ERROR 0s - engine exited with code 1: mock engine failed on purpose
bad-empty: EMPTY (0 seconds)
  EMPTY 0s - reply was empty
Summary: 1 of 4 models passed
```

Exit code 1: three of the four models failed, as the mock was told
to.

## Errors

Plain words, never a traceback:

- No `--engine`, no models, `--models` and `--models-file` together,
  a missing or empty models/prompts file, `--timeout` at or below
  0, a template missing `{model}` or `{prompt}`, or unbalanced
  quotes in the template: exit 2, naming the problem.
- The engine command is not found (checked before any model runs,
  so a typo does not burn a timeout per model): exit 1, naming the
  command. "cannot find the engine command 'fyrn': it is not
  installed or not on PATH. Install it, or fix the --engine
  command, and run again." A template starting with a shell
  builtin (`echo ...`) or an env assignment (`FOO=bar ...`) skips
  the check, because there is no file to find.
- `--json` to a place that cannot be written: exit 1, naming the
  path.
- `--help`, `--version`, `--list-prompts`, `--dry-run`, and
  `--debug-report` never run an engine call.

## Debug report

```bash
python3 model_chat_smoke_test.py --debug-report
```

Writes a debug report through the T21 debug log layer
(`debug_log.py`, copied unmodified) and prints where it went
(`logs/debug-report-model-chat-smoke-test-<date>.txt`). Normal
smoke-test runs never touch the log layer and never create a
`logs/` dir, so the tool stays side-effect free for chaining. The
report carries the app version and a note that the tool has no
network and no services.

## Install

Double-click "Install Model Chat Smoke Test". It checks Python 3,
adds the app menu entry and desktop icon, links the
`model-chat-smoke-test` command onto PATH, and verifies the
install before reporting success. Standard library only, so there
is nothing to download. The desktop icon opens a terminal showing
what the tool does; the tool itself runs from the command line.
`uninstall.sh` removes the menu entry, desktop icon, command link,
and logs folder.

## Requirements

Python 3.8+. No third-party packages, no network, no account, no
GPU. The engine command you point it at is yours to install: the
tool only runs it.

## Smoke test

```bash
bash run_tests.sh
```

46 tests, no network, no real model: every run goes through the
mock engine fixture. Covers help/version, `--list-prompts` (built
in and from a file), `--dry-run` (every command listed, nothing
run, values shell-quoted, works without the engine installed),
template validation (missing
placeholders, unbalanced quotes, empty template), the
missing-engine guard (plain words, exit 1, no traceback, plus the
path form and the shell-builtin skip), all four verdicts (reply,
hang with a proven kill, error with stderr in the report, empty),
mixed verdicts in one run, verdict precedence (timeout beats
error beats empty beats pass), the JSON report (stdout format and
`--json` file, unwritable file), models/prompts file parsing
(comments and blanks skipped, missing and empty files), bad
`--timeout`, the debug report, the unmodified debug log layer
(SHA-256 pinned), the no-em-dash rule (output and docs), the
installer Exec line pinned to the fixed S6 template, and the
version agreeing with the CHANGELOG.

## What it does not do

- It does not load, run, or talk to a model itself: it runs your
  engine's command and reads what comes back. If your engine needs
  a different call shape than one command per prompt, this tool
  does not fit it.
- It does not grade reply quality: a reply that says the wrong
  thing still passes. It checks that the model answers, in time,
  with something in it. Quality grading is a different tool.
- It does not retry a failed prompt, and it does not stop a model
  early after a failure: every model runs every prompt, so the
  report shows the full picture.
- It does not watch models over time or run on a schedule: it runs
  when you run it, on the models you name.
- It does not use Ollama, and it does not know what a GGUF file
  is: the engine is yours, the smoke test just drives it.
