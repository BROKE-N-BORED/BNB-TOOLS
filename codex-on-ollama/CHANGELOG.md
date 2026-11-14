# Changelog

## v0.1.0 - 2026-11-14

First release.

- `codex_ollama.py` (single file, stdlib only): `setup`,
  `check`, and `launch` subcommands, plus `--help` and
  `--version`. Setup checks Ollama (0.13.4 minimum, notes
  the 0.15 minimum for `ollama launch codex`), checks Codex
  is installed (prints the install command and stops if it
  is not), picks a model from `ollama list` with a fuzzy
  preference order (coder models first, then general
  tool-capable models; vision-only, embedding, and unknown
  models skipped), writes the `bnb-ollama` Codex profile,
  and writes the context override. `--model` names any
  model; `--context` sets the context window (default
  65536, 32768 fallback). Check exits 0 when ready, 1 when
  something is missing (naming the first problem and the
  fix), 2 when the checks could not run. Launch runs
  `codex --profile bnb-ollama` and refuses when a check
  fails; `--dry-run` prints the exact command.
- `install-codex.sh`: checks Node and npm exist, then
  installs the Codex CLI with `npm install -g
  @openai/codex` and confirms with `codex --version`.
- `codex-profile.toml`: profile template (provider
  `bnb-ollama`, `base_url` `http://localhost:11434/v1/`,
  `wire_api` `responses`, `stream_idle_timeout_ms` 120000,
  context 65536).
- `ollama-context-override.conf`: systemd override
  template (`[Service]`,
  `Environment="OLLAMA_CONTEXT_LENGTH=65536"`).
- Test suite (`tests/test_codex_ollama.py`, run with
  `bash run_tests.sh`): template parsing and values,
  model-pick logic, version comparison, dry-run launch,
  check with Ollama stopped, setup refusals, help and
  version exit codes. No live Ollama or Codex needed.

Known limits: no live end-to-end run is proven (no Ollama
or Codex in the sandbox); the `/model` picker inside
Codex cannot see local models without a catalog file,
which this pack does not add; 64K context is unproven on
8 GB RAM (32768 fallback provided).
