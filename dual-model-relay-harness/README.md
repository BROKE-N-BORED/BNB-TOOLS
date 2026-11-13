# dual-model-relay-harness

Scripted dual-model AI-to-AI relay over Ollama, from the command
line. Pairs with BNB SKILLS **dual-model-ai-relay**.

## What it does

Runs the DUO relay loop without opening the GUI: a seed message goes
to the starting model, and each reply is handed to the other model,
one generation at a time, until the turn cap, a stop phrase,
agreement, or Ctrl+C.

- **Blind mode** (default): the other model receives the bare reply
  text as a plain user message — no framing, no mention of AI.
- **Aware mode**: the reply is framed — "You are talking with
  another AI assistant (Model %s). It said: %s".
- **Turn cap**: default 10, clamped to 1–50. A turn is one
  generation; the seed turn is turn 1, so a cap of N means exactly
  N generations.
- **Stop phrases**: repeatable `--stop-phrase`, case-insensitive
  substring match; the stop reason names the phrase found.
- **Stop on agreement**: `--stop-on-agreement` stops on the fixed
  list ("i agree", "agreed", "sounds good", "that works") — plain
  string matching, no LLM judge.
- A phrase or agreement stop is reported before the cap when they
  land on the same turn.
- Each model keeps its own history, like DUO's two panes. The
  transcript JSON records every turn, the exact message each model
  received, and the stop reason.

## Usage

```bash
python3 relay.py --model-a qwen3.5:2b --model-b lfm3:1.7b \
    --seed "Should we build the treehouse out of pine or oak?" \
    --start A --cap 6 --mode blind --out relay.json

python3 relay.py --model-a A --model-b B --seed "Hi" \
    --ollama-url http://127.0.0.1:11435 \
    --stop-phrase goodbye --stop-on-agreement
```

Ollama URL defaults to `http://127.0.0.1:11434`, overridable with
`--ollama-url` or the `DUAL_CHAT_OLLAMA_URL` environment variable.
Ollama down is a plain error and exit code 1; Ctrl+C stops the relay
(exit 130). Nothing is sent anywhere except the configured Ollama
server.

## Smoke test

```bash
python3 tests/smoke_test.py
```

Runs real relays against an embedded minimal fake Ollama stub and
proves blind bare text, aware framing, the exact cap, phrase and
agreement stops, start-side B, cap clamping, CLI transcript output,
and the Ollama-down error. No network access beyond localhost.

## Source

Relay semantics mirror DUO's `RelaySession` exactly
(`~/workspace/dual-chat-v03-build/dual_chat.py`, proven in DUO v0.2
blind 4-turn + aware 2-turn drives, 54/54 tests).

## Requirements

Python 3, standard library only. Ollama running locally with the
named models pulled (or a fake Ollama server for testing).
