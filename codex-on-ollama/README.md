# Codex on Ollama (BNB-TOOLS T29)

Wire the Codex CLI to your local Ollama server, so Codex runs
against your own models on your own PC. No API key. No cloud
account. No cost.

Codex is a terminal coding agent: you type in a terminal, and
the agent reads and writes code, runs commands, and runs tests.
This pack sets it up against Ollama, checks the setup, and
launches it.

This does not replace Forge. Forge is the GUI agent. Codex is
for quick terminal work with local models.

## What it does

- `codex_ollama.py setup` picks a model from your installed
  Ollama models, writes a Codex profile named `bnb-ollama`,
  and writes a systemd override that raises the Ollama
  context length to 64K.
- `codex_ollama.py check` reports what is ready and what is
  missing, and names the fix for the first problem.
- `codex_ollama.py launch` runs Codex with the local profile.
- `install-codex.sh` installs the Codex CLI with npm.

The profile lives at `~/.codex/bnb-ollama.config.toml`. The
name is distinct from the `ollama-launch` profile that
`ollama launch codex` writes, so the two do not fight.

## Requirements

- Ollama 0.13.4 or newer, installed and running. (Ollama has
  served the endpoint Codex needs since 0.13.3; Codex
  requires 0.13.4 or newer. `ollama launch codex` needs
  Ollama 0.15 or newer, but this pack works from 0.13.4.)
- Node.js and npm, for the Codex install.
- A small model installed in Ollama. Setup picks a coder
  model first (Qwen2.5-Coder and friends), then a general
  model (Qwen3, Phi, Granite, MiniCPM, LFM, Dolphin, Bonsai
  and others). Vision-only models and embedding models are
  skipped. If nothing suitable is installed, setup says so
  and names what to pull.

## Steps, in order

### 1. Install Codex

```sh
bash install-codex.sh
```

This checks Node and npm exist, then runs
`npm install -g @openai/codex` and confirms with
`codex --version`. If Node or npm is missing, it tells you
to install them first:

```sh
sudo apt install nodejs npm
```

### 2. Raise the context

Codex needs a 64K context window or more. Ollama defaults
to 4K on small hardware, so the server context has to go
up. Install the shipped override file:

```sh
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo cp ollama-context-override.conf /etc/systemd/system/ollama.service.d/override.conf
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

Run those from this folder. Or, without sudo, run Ollama
by hand in a terminal instead of as a service:

```sh
OLLAMA_CONTEXT_LENGTH=65536 ollama serve
```

That only works if the Ollama service is not already
running. If it is, stop it first or use the override
above.

### 3. Setup

```sh
python3 codex_ollama.py setup
```

Setup checks Ollama and Codex, picks a model, writes the
profile to `~/.codex/bnb-ollama.config.toml`, and writes
the override to `~/.codex/ollama-context-override.conf`.
It never runs sudo and never restarts a service. If you
skipped step 2, it prints the commands to install the
override.

Pick a model yourself:

```sh
python3 codex_ollama.py setup --model qwen3:2b
```

Lower the context (see the 64K note below):

```sh
python3 codex_ollama.py setup --context 32768
```

### 4. Check, then launch

```sh
python3 codex_ollama.py check
python3 codex_ollama.py launch
```

`check` exits 0 when everything is ready, 1 when
something is missing (naming what), 2 when it could not
run the checks at all. `launch` refuses to start when a
check fails, and names the first problem and the fix.

See the exact launch command without running it:

```sh
python3 codex_ollama.py launch --dry-run
```

## The 64K note

Codex wants 64K, but 8 GB of RAM may swap at 64K. This is
not proven on this PC either way. The pack sets 65536
because Codex requires it, and the context is a knob you
can turn down. If 64K swaps, re-run setup with
`--context 32768`, then install the override setup wrote
to `~/.codex/ollama-context-override.conf` with the four
commands setup prints, and restart Ollama. Below 64K Codex
may truncate or complain. The real-PC run is the test.

## Honest caveats

- Trial, not a promise. Codex's tool loop was tuned for
  big hosted models. Small local models (2B class) may
  struggle with it: slow, stuck, or wrong tool calls. Try
  it on small jobs first.
- 64K may swap on 8 GB RAM. See the 64K note above.
- Never run bare `codex --oss` on this PC. That mode
  defaults to `gpt-oss:20b` and pulls it without asking
  if it is missing: a 13 GB download, and the model needs
  about 16 GB RAM. It does not fit this PC.
- The `/model` picker inside Codex lists OpenAI's cloud
  catalog by default and cannot see your local models
  without a catalog file. This pack does not add one, so
  use the profile's model, or re-run setup with `--model`
  to switch models.
- No live run is proven. The sandbox has no Ollama and
  none of your models, so the end-to-end run (setup
  against a real server, a real launch, a real Codex
  session) is unproven until it runs on your PC. The
  test suite proves the logic, not the live wiring.

## When a step fails

- **Ollama is not running.** Start it (`ollama serve` in a
  terminal, or start the service), then run the command
  again. `check` reports this plainly and never crashes.
- **Codex is not installed.** Run `bash install-codex.sh`.
  Setup does not install Codex itself.
- **No suitable model installed.** Pull one:
  `ollama pull qwen2.5-coder:1.5b`, then run setup again.
- **Ollama is too old.** Update Ollama to 0.13.4 or newer.
  `check` shows the installed version.
- **Node or npm is missing.** Run
  `sudo apt install nodejs npm`, then run the install
  script again.
- **64K swaps.** Drop to 32768 (see the 64K note above).

## Files

- `codex_ollama.py`: the tool. Stdlib only, one file.
  Subcommands: `setup`, `check`, `launch`, plus `--help`
  and `--version`.
- `install-codex.sh`: installs the Codex CLI via npm.
- `codex-profile.toml`: the profile template setup fills
  in (picked model, context). Provider `bnb-ollama`,
  `base_url` `http://localhost:11434/v1/`,
  `wire_api` `responses`, `stream_idle_timeout_ms` 120000
  (local models are slower, so the idle timeout is raised).
- `ollama-context-override.conf`: the systemd override
  template: `[Service]` plus
  `Environment="OLLAMA_CONTEXT_LENGTH=65536"`.
- `tests/test_codex_ollama.py`: the test suite. Run it
  with `bash run_tests.sh`. No live Ollama or Codex needed.

## Version

v0.1.0. See CHANGELOG.md.
