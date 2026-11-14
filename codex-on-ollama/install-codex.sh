#!/usr/bin/env bash
# Install the Codex CLI via npm (BNB-TOOLS T29, codex-on-ollama).
# Codex is OpenAI's terminal coding agent. This script installs
# it only; codex_ollama.py wires it to local Ollama afterwards.
set -euo pipefail

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "Node.js and npm are not installed."
  echo "Install them first with:"
  echo "  sudo apt install nodejs npm"
  echo "Then run this script again."
  exit 1
fi

echo "Node version: $(node --version)"
echo "Codex needs a recent Node.js. If the install below fails on"
echo "version, upgrade Node and try again."
echo "Installing Codex CLI (this may take a minute)..."

if ! npm install -g @openai/codex; then
  echo "npm install failed. See the error above; if it mentions"
  echo "your Node version, install a recent Node.js and try again."
  exit 1
fi

codex --version
echo "Codex installed. Next step:"
echo "  python3 codex_ollama.py setup"
