#!/usr/bin/env python3
"""Codex on Ollama launcher pack (BNB-TOOLS T29).

Wires the Codex CLI to a local Ollama server on this PC, so Codex
runs against local models with no API key and no cloud account.
Codex is a terminal coding agent: type in a terminal, the agent
reads and writes code, runs commands, runs tests. This pack is
the config and the small tool that sets it up, checks it, and
launches it.

It does not replace Forge. Forge is the GUI agent. Codex is for
quick terminal work with local models.

Usage:
  python3 codex_ollama.py setup [--model NAME] [--context N]
  python3 codex_ollama.py check
  python3 codex_ollama.py launch [--dry-run]
  python3 codex_ollama.py --help
  python3 codex_ollama.py --version

Setup writes a Codex profile named bnb-ollama to
~/.codex/bnb-ollama.config.toml and a systemd override file to
~/.codex/ollama-context-override.conf, then prints the short
commands that install the override. It never runs sudo itself
and never restarts any service.

Codex needs a 64K context window or more. Ollama defaults to 4K
on small hardware, so the context has to go up. 64K may swap on
8 GB RAM; if it does, re-run setup with --context 32768. Below
64K Codex may truncate or complain.

Never run bare `codex --oss` on this PC: it pulls gpt-oss:20b
(13 GB) without asking, and that model needs about 16 GB RAM.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request

VERSION = "0.1.0"
TOOL_NAME = "codex-on-ollama"
PROFILE_NAME = "bnb-ollama"
DEFAULT_CONTEXT = 65536
FALLBACK_CONTEXT = 32768
MIN_OLLAMA = (0, 13, 4)
LAUNCH_MIN_OLLAMA = (0, 15, 0)
OLLAMA_BASE = "http://localhost:11434"
OLLAMA_API = OLLAMA_BASE + "/v1/"
PULL_SUGGESTION = "qwen2.5-coder:1.5b"

# Model preference order, most preferred first. Matching is
# fuzzy: names are lowercased and separators stripped, then each
# pattern is a substring test. Coder models first, then general
# tool-capable models. Unknown families are never picked.
MODEL_PREFERENCE = [
    "qwen2.5-coder", "qwen3-coder", "deepseek-coder",
    "codellama", "starcoder", "codegemma", "coder",
    "qwen3", "qwen2.5", "qwen", "phi", "granite",
    "minicpm", "lfm", "dolphin", "bonsai",
    "llama", "mistral", "gemma", "heretic",
]

# Models to skip: vision-only models and embedding models do
# not drive a coding agent. Matched on whole name tokens, so
# "qwen3-vl-2b" is skipped but "qwen3" is not.
SKIP_TOKENS = {"vl", "vision", "llava", "moondream", "embed",
               "embedding", "clip"}

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------- helpers

def home_dir(home=None):
    return home if home is not None else os.path.expanduser("~")


def profile_path(home=None, profile=PROFILE_NAME):
    return os.path.join(home_dir(home), ".codex",
                        "%s.config.toml" % profile)


def local_override_path(home=None):
    return os.path.join(home_dir(home), ".codex",
                        "ollama-context-override.conf")


def system_override_path():
    return "/etc/systemd/system/ollama.service.d/override.conf"


def run_cmd(cmd, timeout=15):
    """Run a command. Returns (returncode, stdout), or None when
    the command is missing or times out."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return (proc.returncode, proc.stdout)


def http_get_json(url, timeout=3):
    """GET a URL and parse the JSON body. None on any failure."""
    try:
        req = urllib.request.Request(
            url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except Exception:
        return None


def ollama_reachable():
    return http_get_json(OLLAMA_BASE + "/api/tags") is not None


def parse_version(text):
    """Pull a (major, minor, patch) tuple out of version output.
    Returns None when no version number is found."""
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    if match:
        return tuple(int(g) for g in match.groups())
    match = re.search(r"(\d+)\.(\d+)", text or "")
    if match:
        return (int(match.group(1)), int(match.group(2)), 0)
    return None


def version_string(version):
    return ".".join(str(n) for n in version)


def normalize_name(name):
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def name_tokens(name):
    return [t for t in re.split(r"[^a-z0-9]+", name.lower()) if t]


def skip_model(name):
    tokens = name_tokens(name)
    if set(tokens) & SKIP_TOKENS:
        return True
    return any(t.startswith("embed") for t in tokens)


def pick_model(models):
    """Pick the best model from a list of Ollama model names.

    Walks MODEL_PREFERENCE in order and returns the first
    installed model that matches. Returns None when nothing
    installed is suitable."""
    usable = [m for m in models if not skip_model(m)]
    for pattern in MODEL_PREFERENCE:
        needle = normalize_name(pattern)
        for model in usable:
            if needle in normalize_name(model):
                return model
    return None


def parse_ollama_list(text):
    """Parse `ollama list` output into a list of model names."""
    models = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        first = line.split()[0]
        if first.upper() == "NAME":
            continue
        models.append(first)
    return models


def load_template(filename):
    path = os.path.join(TOOL_DIR, filename)
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def render_profile(model, context=DEFAULT_CONTEXT):
    """Fill the profile template with the picked model and context."""
    text = load_template("codex-profile.toml")
    safe_model = model.replace("\\", "\\\\").replace('"', '\\"')
    text = text.replace("__MODEL__", safe_model)
    text = re.sub(r"(model_context_window\s*=\s*)\d+",
                  r"\g<1>%d" % context, text)
    return text


def render_override(context=DEFAULT_CONTEXT):
    """Fill the systemd override template with the context value."""
    text = load_template("ollama-context-override.conf")
    text = re.sub(r"(OLLAMA_CONTEXT_LENGTH=)\d+",
                  r"\g<1>%d" % context, text)
    return text


def parse_override_value(text):
    """Read the OLLAMA_CONTEXT_LENGTH value out of override text."""
    match = re.search(r"OLLAMA_CONTEXT_LENGTH=(\d+)", text or "")
    if match:
        return int(match.group(1))
    return None


def read_text_file(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------- checks

def collect_checks(home=None, profile=PROFILE_NAME):
    """Run every readiness check.

    Returns a list of dicts with keys: name, ok, detail, fix.
    A check that cannot run because an earlier fact is missing
    is reported as skipped (ok True, detail says skipped) so one
    problem is not reported twice. Never raises for a missing
    Ollama, a missing Codex, or a missing file."""
    checks = []

    def add(name, ok, detail, fix=""):
        checks.append({"name": name, "ok": ok, "detail": detail,
                       "fix": fix})

    # 1. Ollama installed, and its version.
    result = run_cmd(["ollama", "--version"])
    ollama_version = None
    if result is None:
        add("Ollama installed", False, "ollama command not found",
            "Install Ollama, then run setup again.")
        add("Ollama version", True, "skipped: Ollama is not installed")
    else:
        ollama_version = parse_version(result[1])
        if result[0] != 0 or ollama_version is None:
            add("Ollama installed", False,
                "ollama --version did not report a version",
                "Reinstall Ollama, then run setup again.")
            add("Ollama version", True,
                "skipped: Ollama version unknown")
        else:
            add("Ollama installed", True,
                "version %s" % version_string(ollama_version))
            if ollama_version < MIN_OLLAMA:
                add("Ollama version", False,
                    "%s is too old, 0.13.4 or newer is needed"
                    % version_string(ollama_version),
                    "Update Ollama to 0.13.4 or newer, then run setup again.")
            else:
                detail = "%s (0.13.4 or newer needed)" % (
                    version_string(ollama_version))
                if ollama_version < LAUNCH_MIN_OLLAMA:
                    detail += "; below 0.15, so ollama launch codex "
                    detail += "is not available, but this pack works "
                    detail += "from 0.13.4"
                add("Ollama version", True, detail)

    # 2. Ollama reachable.
    reachable = ollama_reachable()
    if reachable:
        add("Ollama running", True, "http://localhost:11434 answers")
    else:
        add("Ollama running", False, "Ollama is not running",
            "Start Ollama: run ollama serve in a terminal, or "
            "start the Ollama service.")

    # 3. Codex installed.
    result = run_cmd(["codex", "--version"])
    if result is None or result[0] != 0:
        add("Codex installed", False, "codex command not found",
            "Run: bash install-codex.sh")
    else:
        version = result[1].strip().splitlines()
        add("Codex installed", True,
            version[0] if version else "codex found")

    # 4. Profile file present with the right values.
    profile_file = profile_path(home, profile)
    profile_text = read_text_file(profile_file)
    profile_context = None
    if profile_text is None:
        add("Codex profile", False,
            "%s is missing" % profile_file,
            "Run: python3 codex_ollama.py setup")
    else:
        try:
            import tomllib
            data = tomllib.loads(profile_text)
        except Exception:
            data = None
        if data is None:
            add("Codex profile", False,
                "%s does not parse as TOML" % profile_file,
                "Run: python3 codex_ollama.py setup")
        else:
            providers = data.get("model_providers", {})
            provider = providers.get(profile, {})
            problems = []
            if data.get("model_provider") != profile:
                problems.append("model_provider is not %s" % profile)
            if provider.get("base_url") != OLLAMA_API:
                problems.append("base_url is not %s" % OLLAMA_API)
            if provider.get("wire_api") != "responses":
                problems.append("wire_api is not responses")
            profile_context = data.get("model_context_window")
            if not isinstance(profile_context, int):
                problems.append("model_context_window is missing")
            if problems:
                add("Codex profile", False, "; ".join(problems),
                    "Run: python3 codex_ollama.py setup")
            else:
                detail = "%s, model %s, context %d" % (
                    os.path.basename(profile_file),
                    data.get("model", "?"), profile_context)
                if profile_context < DEFAULT_CONTEXT:
                    detail += " (below the 64K Codex wants; "
                    detail += "it may truncate or complain)"
                add("Codex profile", True, detail)

    # 5. Context override installed.
    expected = profile_context if isinstance(profile_context, int) \
        else DEFAULT_CONTEXT
    system_text = read_text_file(system_override_path())
    if system_text is not None:
        value = parse_override_value(system_text)
        if value == expected:
            add("Context override", True,
                "installed, OLLAMA_CONTEXT_LENGTH=%d" % value)
        elif value is None:
            add("Context override", False,
                "override file exists but carries no context value",
                "Reinstall the override with the commands setup printed.")
        else:
            add("Context override", False,
                "override sets %d but the profile wants %d"
                % (value, expected),
                "Reinstall the override with the commands setup printed, "
                "then restart Ollama.")
    elif read_text_file(local_override_path(home)) is not None:
        add("Context override", False,
            "written to ~/.codex but not installed in /etc",
            "Install it with the commands setup printed, then "
            "restart Ollama. Or run Ollama with "
            "OLLAMA_CONTEXT_LENGTH=%d set." % expected)
    else:
        add("Context override", False,
            "no override file found",
            "Run: python3 codex_ollama.py setup")

    # 6. Model list, with the picked model marked.
    if not reachable:
        add("Model", True, "skipped: Ollama is not running")
    else:
        result = run_cmd(["ollama", "list"])
        if result is None or result[0] != 0:
            add("Model", False, "could not list models (ollama list failed)",
                "Check Ollama is running, then run check again.")
        else:
            models = parse_ollama_list(result[1])
            picked = pick_model(models)
            if picked is None:
                if models:
                    detail = "no suitable model installed (found: %s)" % (
                        ", ".join(models))
                else:
                    detail = "no models installed"
                add("Model", False, detail,
                    "Run: ollama pull %s" % PULL_SUGGESTION)
            else:
                marked = ["%s (picked)" % m if m == picked else m
                          for m in models]
                add("Model", True, ", ".join(marked))

    return checks


def print_checks(checks):
    for check in checks:
        mark = "OK  " if check["ok"] else "MISS"
        print("%s %s: %s" % (mark, check["name"], check["detail"]))


def print_caveats(context):
    print()
    print("Two things to know before you launch:")
    print("1. This is a trial, not a promise. Small local models may")
    print("   struggle with Codex's tool loop, which was tuned for big")
    print("   hosted models. It may be slow, and it may get stuck.")
    print("2. Context is set to %d. On 8 GB RAM, 64K may swap. If it" % context)
    print("   does, re-run setup with --context %d. Below 64K Codex" % FALLBACK_CONTEXT)
    print("   may truncate or complain.")
    print()
    print("Never run bare codex --oss on this PC: it pulls gpt-oss:20b")
    print("(13 GB) without asking, and that model needs about 16 GB RAM.")


# ---------------------------------------------------------------- commands

def cmd_setup(args):
    home = args.home
    context = args.context
    profile = args.profile

    if context <= 0:
        print("Context must be a positive number of tokens.")
        return 1

    # 1. Ollama installed and new enough.
    result = run_cmd(["ollama", "--version"])
    if result is None:
        print("Ollama is not installed. Install Ollama first,")
        print("then run setup again.")
        return 1
    version = parse_version(result[1])
    if result[0] != 0 or version is None:
        print("Ollama is installed but its version could not be read.")
        print("Reinstall Ollama, then run setup again.")
        return 1
    if version < MIN_OLLAMA:
        print("Ollama %s is too old. Codex needs Ollama 0.13.4 or newer."
              % version_string(version))
        print("Update Ollama, then run setup again.")
        return 1
    print("Ollama %s found." % version_string(version))
    if version < LAUNCH_MIN_OLLAMA:
        print("Note: ollama launch codex needs Ollama 0.15 or newer,")
        print("but this pack works from 0.13.4, so setup continues.")

    # 2. Codex installed. Setup does not install it.
    result = run_cmd(["codex", "--version"])
    if result is None or result[0] != 0:
        print("Codex is not installed. Setup does not install it.")
        print("Run this first, then run setup again:")
        print("  bash install-codex.sh")
        print("Or install it directly with:")
        print("  npm install -g @openai/codex")
        return 1
    print("Codex found: %s" % result[1].strip().splitlines()[0])

    # 3. Ollama reachable.
    if not ollama_reachable():
        print("Ollama is not running. Start it first:")
        print("  ollama serve")
        print("Or start the Ollama service, then run setup again.")
        return 1
    print("Ollama is running.")

    # 4. Pick a model.
    result = run_cmd(["ollama", "list"])
    models = parse_ollama_list(result[1]) if result else []
    if args.model:
        wanted = normalize_name(args.model)
        match = None
        for model in models:
            if model == args.model or wanted in normalize_name(model):
                match = model
                break
        if match is None:
            print("Model %s is not installed." % args.model)
            if models:
                print("Installed models: %s" % ", ".join(models))
            else:
                print("No models are installed.")
            print("Pull one first, for example:")
            print("  ollama pull %s" % PULL_SUGGESTION)
            return 1
        model = match
    else:
        model = pick_model(models)
        if model is None:
            print("No suitable model is installed.")
            if models:
                print("Installed models: %s" % ", ".join(models))
                print("None of them is a coder or general chat model")
                print("this pack can use.")
            print("Pull a small coder model first:")
            print("  ollama pull %s" % PULL_SUGGESTION)
            return 1
    print("Picked model: %s" % model)
    if context < DEFAULT_CONTEXT:
        print("Note: context %d is below the 64K Codex wants." % context)
        print("Codex may truncate or complain.")

    # 5. Write the profile and the override.
    codex_dir = os.path.join(home_dir(home), ".codex")
    try:
        os.makedirs(codex_dir, exist_ok=True)
        with open(profile_path(home, profile), "w",
                  encoding="utf-8") as handle:
            handle.write(render_profile(model, context))
        with open(local_override_path(home), "w",
                  encoding="utf-8") as handle:
            handle.write(render_override(context))
    except OSError as exc:
        print("Could not write the config files: %s" % exc)
        return 1
    print("Wrote profile: %s" % profile_path(home, profile))
    print("Wrote override: %s" % local_override_path(home))

    # 6. Next steps: install the override, then launch.
    print()
    print("Next: raise the Ollama context. Run these four commands:")
    print("  sudo mkdir -p /etc/systemd/system/ollama.service.d")
    print("  sudo cp ~/.codex/ollama-context-override.conf /etc/systemd/system/ollama.service.d/override.conf")
    print("  sudo systemctl daemon-reload")
    print("  sudo systemctl restart ollama")
    print("Or, without sudo, run Ollama by hand in a terminal:")
    print("  OLLAMA_CONTEXT_LENGTH=%d ollama serve" % context)
    print("(Only if the Ollama service is not already running.)")
    print()
    print("Then check everything and launch:")
    print("  python3 codex_ollama.py check")
    print("  python3 codex_ollama.py launch")
    print_caveats(context)
    return 0


def cmd_check(args):
    try:
        checks = collect_checks(args.home, args.profile)
    except Exception as exc:
        print("Could not run the checks: %s" % exc)
        return 2
    print("Codex on Ollama check")
    print_checks(checks)
    missing = [c for c in checks if not c["ok"]]
    if not missing:
        print()
        print("Ready. Launch with:")
        print("  python3 codex_ollama.py launch")
        return 0
    print()
    print("Not ready: %d problem(s). Fix the first one, then run" % len(missing))
    print("check again.")
    first = missing[0]
    print("First problem: %s: %s" % (first["name"], first["detail"]))
    if first["fix"]:
        print("Fix: %s" % first["fix"])
    return 1


def cmd_launch(args):
    profile = args.profile
    command = ["codex", "--profile", profile]
    if args.dry_run:
        print(" ".join(command))
        return 0
    try:
        checks = collect_checks(args.home, profile)
    except Exception as exc:
        print("Could not run the checks: %s" % exc)
        return 2
    missing = [c for c in checks if not c["ok"]]
    if missing:
        first = missing[0]
        print("Cannot launch: %s: %s" % (first["name"], first["detail"]))
        if first["fix"]:
            print("Fix: %s" % first["fix"])
        print("Run check for the full list:")
        print("  python3 codex_ollama.py check")
        return 1
    print("Trial run: a small local model driving Codex. It may be")
    print("slow or struggle with the tool loop. Trial, not a promise.")
    os.execvp("codex", command)
    return 0


# ---------------------------------------------------------------- entry

def build_parser():
    parser = argparse.ArgumentParser(
        prog="codex_ollama.py",
        description="Wire the Codex CLI to local Ollama. No API key, "
                    "no cloud account. See README.md for the steps.")
    parser.add_argument("--version", action="version",
                        version="%s %s" % (TOOL_NAME, VERSION))
    sub = parser.add_subparsers(dest="command", metavar="command")

    setup = sub.add_parser(
        "setup",
        help="write the Codex profile and the context override")
    setup.add_argument("--model", default=None,
                       help="name a model instead of auto-picking one")
    setup.add_argument("--context", type=int, default=DEFAULT_CONTEXT,
                       help="context window in tokens (default 65536; "
                            "32768 is the fallback on 8 GB RAM)")
    setup.add_argument("--profile", default=PROFILE_NAME,
                       help="Codex profile name (default bnb-ollama)")
    setup.add_argument("--home", default=None,
                       help="home directory to write under "
                            "(default: your real home)")
    setup.set_defaults(func=cmd_setup)

    check = sub.add_parser(
        "check",
        help="report what is ready and what is missing")
    check.add_argument("--profile", default=PROFILE_NAME,
                       help="Codex profile name (default bnb-ollama)")
    check.add_argument("--home", default=None,
                       help="home directory to check under "
                            "(default: your real home)")
    check.set_defaults(func=cmd_check)

    launch = sub.add_parser(
        "launch",
        help="run Codex with the local Ollama profile")
    launch.add_argument("--dry-run", action="store_true",
                        help="print the launch command instead of running it")
    launch.add_argument("--profile", default=PROFILE_NAME,
                       help="Codex profile name (default bnb-ollama)")
    launch.add_argument("--home", default=None,
                        help="home directory to check under "
                             "(default: your real home)")
    launch.set_defaults(func=cmd_launch)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print()
        print("Stopped.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
