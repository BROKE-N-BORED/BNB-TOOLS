# fake-provider-servers

Scripted fake provider servers for verifying chat and benchmark apps
over real HTTP, without real models, real keys, or real spend. Pairs
with BNB SKILLS **fake-provider-verification**.

## What it does

Two stdlib-only servers, in-process on ephemeral ports:

- **FakeOllamaServer** — `GET /api/tags`, `GET /api/ps`,
  `POST /api/chat`, `POST /api/generate`, `POST /api/show`,
  `POST /api/pull` (streamed progress events). Chat streams NDJSON
  ending in a `done: true` line with `eval_count` / `eval_duration`
  (20 tokens in 0.2 s = exactly 100 tok/s, so speed readouts are
  assertable). `/api/show` returns per-model capabilities.
- **FakeProviderServer** — OpenAI-compatible `GET /v1/models` and
  `POST /v1/chat/completions` with SSE streaming, a `data: [DONE]`
  terminator, and a usage object (20 in / 200 out) only when the
  request asked for it (`stream_options: {include_usage: true}`).

Both servers:

- Answer from canned brains — **smart** (always right), **partial**
  (some right), **dumb** (wrong or refuses) — so deterministic
  scoring stays exact: smart 100, partial 60, dumb 0.
- Record every request (`chat_history`, `generate_history`) so
  tests can assert the exact payload the app sent.
- Offer failure modes: `dead` (close without answering),
  `slow` (1 s chunk delays), `pull_fail` (pull answers 500), a
  broken model (500 "model exploded"), unknown model (404), and —
  provider only — a bad-key 401 (never retried). The fake good key
  is `sk-fake-good-key`, a fake key for a fake server.

## Usage

```python
from fake_servers import FakeOllamaServer, FakeProviderServer
import threading

ollama = FakeOllamaServer()  # 127.0.0.1, ephemeral port
threading.Thread(target=ollama.serve_forever, daemon=True).start()
print(ollama.port)
# ... run the app against http://127.0.0.1:<port> ...
assert ollama.chat_history[-1] == [{"role": "user", "content": "hello"}]
ollama.shutdown()
```

Standalone, for poking by hand:

```bash
python3 fake_servers.py ollama --port 11435
python3 fake_servers.py provider --port 11436
```

Custom models per run: `FakeOllamaServer(models={"my-model:1b":
"smart"})`, `FakeProviderServer(models={"my-gpt": "dumb"})`,
`FakeProviderServer(good_key="sk-test-123")`.

## Honest gaps

The fakes answer from a script, never from understanding: the fake
cannot truly see (vision answers come from the prompt), and real
providers vary (usage timing, `reasoning_content`, 429 rate
limits). A fake proves the app's wiring, scoring, and failure
handling; only a real call with a real key proves the provider —
the real-PC run is always the closer.

## Smoke test

```bash
python3 tests/smoke_test.py
```

Starts both servers and proves every endpoint and failure mode over
real HTTP. No network access beyond localhost is needed.

## Source

Generalizes the fake servers proven in OLLAMA System Test v3/v4/v5
and DUO v0.1–v0.3 verification
(`~/workspace/ollama-system-test-v5-verify/fake_ollama.py`).

## Requirements

Python 3, standard library only.
