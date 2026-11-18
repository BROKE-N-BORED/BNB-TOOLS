#!/usr/bin/env python3
"""model-chat-smoke-test (BNB-TOOLS T38): run a canned chat through
each model on a project's own engine and report pass/fail per model.

The tool is engine-agnostic: it does not know or load any model
itself. You give it a command template for your engine, with two
placeholders the runner fills in:

    {model}   the model name
    {prompt}  one canned prompt

Example (FYRN-style engine):

    python3 model_chat_smoke_test.py \\
        --engine "fyrn chat --model {model} --prompt {prompt}" \\
        --models tiny-1b tiny-2b

Each model is run through every canned prompt, one engine call per
prompt. A model passes only when every prompt gets a non-empty reply
inside the timeout. The verdicts are:

    pass     every prompt replied in time, none empty
    timeout  at least one prompt hung past --timeout (killed)
    error    at least one engine call exited non-zero or failed
    empty    at least one prompt got an empty reply in time

When prompts disagree, the worst verdict wins: timeout beats error,
error beats empty, empty beats pass. The per-prompt detail is in the
report either way, so nothing is hidden by the roll-up.

The report prints as plain text on stdout. --format json prints the
same report as JSON instead, and --json FILE writes the JSON report
to a file as well. Exit 0 when every model passes, 1 when any model
fails (or the engine command is missing, or the report cannot be
written), 2 for a usage or config problem.

The canned prompts are built in (see --list-prompts) and can be
replaced with --prompts FILE, one prompt per line. Models come from
--models or --models-file FILE, one model per line. --dry-run prints
the exact commands that would run, without running anything.

This tool runs NO model and needs NO Ollama: the engine command is
the project's own. Standard library only, no network.

    python3 model_chat_smoke_test.py --engine "CMD" --models a b
    python3 model_chat_smoke_test.py --engine "CMD" --models-file models.txt
    python3 model_chat_smoke_test.py --engine "CMD" --models a --dry-run
    python3 model_chat_smoke_test.py --list-prompts
    python3 model_chat_smoke_test.py --debug-report
"""

import argparse
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
from datetime import datetime

VERSION = "0.1.0"
APP_NAME = "model-chat-smoke-test"
DEFAULT_TIMEOUT = 60.0
MAX_PREVIEW = 200
MAX_ERROR = 500

# The canned chat. Short, model-agnostic prompts: any working chat
# model answers them, and a broken engine shows up fast.
BUILTIN_PROMPTS = [
    "Hello. Reply with one short sentence.",
    "What is 2 + 2? Reply with the number only.",
    "Name one color. Reply with the color only.",
]

# Worst verdict wins, in this order.
VERDICT_ORDER = ("timeout", "error", "empty", "pass")

# Shell builtins and keywords: the pre-flight engine check skips them,
# because they are not files on disk and shutil.which cannot find them.
SHELL_BUILTINS = {
    "cd", "echo", "exec", "eval", "export", "set", "source", ".",
    "test", "[", "true", "false", "time", "command", "builtin",
    "if", "then", "else", "fi", "for", "do", "done", "while",
}


class SmokeError(Exception):
    """A problem the user can fix, in plain words. Carries an exit code."""

    def __init__(self, message, exit_code=2):
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


# ---------------------------------------------------------------- engine


def check_engine_command(template):
    """Pre-flight guard: the command at the start of the template must
    exist before any model runs. Returns the command name.

    Raises SmokeError (exit 1) naming the missing command when it
    cannot be found. Skips the check for shell builtins, env
    assignments (FOO=bar ...), and templates whose first token is not
    a plain command word, because those have nothing to check.
    """
    try:
        tokens = shlex.split(template)
    except ValueError:
        raise SmokeError(
            "the --engine command has unbalanced quotes: %r" % template)
    if not tokens:
        raise SmokeError("the --engine command is empty")
    first = tokens[0]
    if first in SHELL_BUILTINS:
        return first
    if "=" in first and "/" not in first:
        return first  # env assignment, e.g. FOO=bar engine ...
    if "/" in first:
        if os.path.isfile(first) and os.access(first, os.X_OK):
            return first
        raise SmokeError(
            "cannot find the engine command %r: there is no executable "
            "file at that path. Check the --engine command and run again."
            % first, exit_code=1)
    if shutil.which(first) is None:
        raise SmokeError(
            "cannot find the engine command %r: it is not installed or "
            "not on PATH. Install it, or fix the --engine command, and "
            "run again." % first, exit_code=1)
    return first


def build_command(template, model, prompt):
    """Fill the template in for one model and one prompt. Both values
    are shell-quoted, so spaces and quotes in a model name or a prompt
    cannot break the command or inject a second command."""
    return template.replace("{model}", shlex.quote(model)).replace(
        "{prompt}", shlex.quote(prompt))


def validate_template(template):
    """The template must name both placeholders, or every model would
    run the same command and the smoke test would prove nothing."""
    if "{model}" not in template:
        raise SmokeError(
            "the --engine command has no {model} placeholder, so every "
            "model would run the same command. Add {model} where the "
            "model name goes.")
    if "{prompt}" not in template:
        raise SmokeError(
            "the --engine command has no {prompt} placeholder, so no "
            "prompt would ever reach the model. Add {prompt} where the "
            "prompt goes.")


# ---------------------------------------------------------------- running


def _one_line(text, limit):
    """One line, capped, for the report. Newlines become spaces."""
    flat = " ".join(text.split())
    if len(flat) > limit:
        return flat[:limit] + "..."
    return flat


def run_one(command, timeout):
    """Run one engine call. Returns (verdict, seconds, reply, error).

    verdict is one of pass / timeout / error / empty. reply is the
    stripped stdout (empty unless pass). error is a short plain-words
    reason (empty unless timeout or error). A hung call is killed as
    a whole process group, so a stray engine cannot keep running in
    the background after the timeout.
    """
    started = datetime.now()
    try:
        proc = subprocess.Popen(
            command, shell=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, errors="replace",
            start_new_session=True)
    except (OSError, ValueError) as exc:
        return ("error", 0.0, "", "could not start the engine: %s" % exc)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        # Reap the output after the kill: this closes the pipes too,
        # so no unclosed-file warning is left behind.
        proc.communicate()
        seconds = (datetime.now() - started).total_seconds()
        return ("timeout", seconds, "",
                "timed out after %s seconds" % _fmt_seconds(timeout))
    seconds = (datetime.now() - started).total_seconds()
    if proc.returncode != 0:
        reason = _one_line(err, MAX_ERROR) or "no error message"
        return ("error", seconds, "",
                "engine exited with code %d: %s"
                % (proc.returncode, reason))
    reply = out.strip()
    if not reply:
        return ("empty", seconds, "", "reply was empty")
    return ("pass", seconds, reply, "")


def _fmt_seconds(value):
    """Whole seconds print without a decimal point (60, not 60.0)."""
    if float(value).is_integer():
        return str(int(value))
    return str(value)


def _rollup(verdicts):
    """The worst per-prompt verdict wins."""
    for verdict in VERDICT_ORDER:
        if verdict in verdicts:
            return verdict
    return "pass"


def run_smoke_test(engine_template, models, prompts, timeout):
    """Run every model through every prompt. Returns the report dict."""
    started = datetime.now().astimezone().isoformat()
    model_results = []
    for model in models:
        prompt_results = []
        model_seconds = 0.0
        for prompt in prompts:
            command = build_command(engine_template, model, prompt)
            verdict, seconds, reply, error = run_one(command, timeout)
            model_seconds += seconds
            entry = {"prompt": prompt, "verdict": verdict,
                     "seconds": round(seconds, 3)}
            if verdict == "pass":
                entry["reply_preview"] = _one_line(reply, MAX_PREVIEW)
            elif error:
                entry["error"] = error
            prompt_results.append(entry)
        model_results.append({
            "model": model,
            "verdict": _rollup([p["verdict"] for p in prompt_results]),
            "seconds": round(model_seconds, 3),
            "prompts": prompt_results,
        })
    passed = sum(1 for m in model_results if m["verdict"] == "pass")
    return {
        "tool": APP_NAME,
        "version": VERSION,
        "engine_template": engine_template,
        "timeout_seconds": timeout,
        "prompts": list(prompts),
        "started_at": started,
        "finished_at": datetime.now().astimezone().isoformat(),
        "summary": {"total": len(model_results), "passed": passed,
                    "failed": len(model_results) - passed},
        "models": model_results,
    }


# ---------------------------------------------------------------- reports


def render_text(report):
    """The plain-text report: one line per model, then the per-prompt
    detail for any model that did not pass, then the summary line.
    Seconds are whole here: a smoke-test report is read by a human,
    and sub-second precision is not the point. The JSON report keeps
    three decimals."""
    lines = []
    for model in report["models"]:
        total = round(model["seconds"])
        lines.append("%s: %s (%d %s)"
                     % (model["model"], model["verdict"].upper(), total,
                        "second" if total == 1 else "seconds"))
        for entry in model["prompts"]:
            seconds = "%ds" % round(entry["seconds"])
            if entry["verdict"] == "pass":
                lines.append("  PASS %s - %s"
                             % (seconds, entry.get("reply_preview", "")))
            else:
                lines.append("  %s %s - %s"
                             % (entry["verdict"].upper(), seconds,
                                entry.get("error", "")))
    summary = report["summary"]
    lines.append("Summary: %d of %d models passed"
                 % (summary["passed"], summary["total"]))
    return "\n".join(lines) + "\n"


def render_json(report):
    """The JSON report: the same report, as indented JSON."""
    return json.dumps(report, indent=2) + "\n"


# ---------------------------------------------------------------- inputs


def read_list_file(path, what):
    """Read a --models-file / --prompts file: one entry per line,
    blank lines and lines starting with # skipped."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            entries = [line.strip() for line in handle]
    except OSError as exc:
        raise SmokeError("cannot read the %s file %s: %s"
                         % (what, path, exc.strerror or exc))
    entries = [e for e in entries if e and not e.startswith("#")]
    if not entries:
        raise SmokeError("the %s file %s has no %s in it"
                         % (what, path, what))
    return entries


# ---------------------------------------------------------------- debug


def make_logger(log_dir_path=None):
    """The T21 debug log layer, wired to this tool."""
    from debug_log import DebugLogger
    logger = DebugLogger(APP_NAME, VERSION,
                         log_dir=log_dir_path or "logs")
    logger.set_setting("app_version", VERSION)
    logger.register_service(
        "network and services",
        lambda: "none: this tool has no network and no services")
    return logger


def cmd_debug_report():
    """Write a debug report and print where it went."""
    logger = make_logger()
    path = logger.generate_report()
    print("Debug report written to %s" % path)
    return 0


# ---------------------------------------------------------------- CLI


def build_parser():
    parser = argparse.ArgumentParser(
        prog="model_chat_smoke_test.py",
        description="Model Chat Smoke Test (BNB-TOOLS T38): run a "
                    "canned chat through each model on a project's own "
                    "engine and report pass/fail per model. No Ollama, "
                    "no model loading: the engine command is yours.")
    parser.add_argument("--engine", default=None, metavar="CMD",
                        help="engine command template with {model} and "
                             "{prompt} placeholders, e.g. "
                             "\"fyrn chat --model {model} "
                             "--prompt {prompt}\"")
    parser.add_argument("--models", nargs="+", default=None,
                        metavar="MODEL",
                        help="one or more model names to smoke test")
    parser.add_argument("--models-file", default=None, metavar="FILE",
                        help="read the model names from FILE instead, "
                             "one per line (# comments and blank lines "
                             "skipped)")
    parser.add_argument("--prompts", default=None, metavar="FILE",
                        help="read the canned prompts from FILE "
                             "instead of the built-in three, one per "
                             "line (# comments and blank lines skipped)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        metavar="SECONDS",
                        help="seconds allowed per engine call before "
                             "it is killed as hung (default 60)")
    parser.add_argument("--format", choices=("text", "json"),
                        default="text",
                        help="report format on stdout (default text)")
    parser.add_argument("--json", default=None, metavar="FILE",
                        help="also write the JSON report to FILE")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the exact commands that would run, "
                             "and run nothing")
    parser.add_argument("--list-prompts", action="store_true",
                        help="print the canned prompts and exit")
    parser.add_argument("--debug-report", action="store_true",
                        help="write a debug report and print its path, "
                             "instead of running a smoke test")
    parser.add_argument("--version", action="version",
                        version="%(prog)s " + VERSION)
    return parser


def _resolve_prompts(args):
    if args.prompts is not None:
        return read_list_file(args.prompts, "prompts")
    return list(BUILTIN_PROMPTS)


def _resolve_models(args):
    if args.models is not None and args.models_file is not None:
        raise SmokeError("give the models with --models or with "
                         "--models-file, not both")
    if args.models is not None:
        return list(args.models)
    if args.models_file is not None:
        return read_list_file(args.models_file, "models")
    raise SmokeError("no models given: pass --models, or --models-file "
                     "with one model per line")


def _validate_timeout(timeout):
    if timeout <= 0:
        raise SmokeError("--timeout must be above 0 (got %s)"
                         % _fmt_seconds(timeout))


def run(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.debug_report:
            return cmd_debug_report()
        if args.list_prompts:
            for prompt in _resolve_prompts(args):
                print(prompt)
            return 0
        if args.engine is None:
            raise SmokeError("no engine command given: pass --engine "
                             "with a command template holding {model} "
                             "and {prompt}")
        _validate_timeout(args.timeout)
        validate_template(args.engine)
        models = _resolve_models(args)
        prompts = _resolve_prompts(args)
        if args.dry_run:
            # Before the engine guard on purpose: a dry run checks
            # the template without running anything, and must work
            # even when the engine is not installed on this machine.
            for model in models:
                for prompt in prompts:
                    print(build_command(args.engine, model, prompt))
            return 0
        check_engine_command(args.engine)
        report = run_smoke_test(args.engine, models, prompts,
                                args.timeout)
        if args.json is not None:
            try:
                with open(args.json, "w", encoding="utf-8") as handle:
                    handle.write(render_json(report))
            except OSError as exc:
                raise SmokeError("cannot write the JSON report to %s: %s"
                                 % (args.json, exc.strerror or exc),
                                 exit_code=1)
        if args.format == "json":
            print(render_json(report), end="")
        else:
            print(render_text(report), end="")
        return 0 if report["summary"]["failed"] == 0 else 1
    except SmokeError as exc:
        print("model-chat-smoke-test: %s" % exc.message, file=sys.stderr)
        return exc.exit_code


def main():
    sys.exit(run())


if __name__ == "__main__":
    main()
