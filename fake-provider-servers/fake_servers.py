#!/usr/bin/env python3
"""Scripted fake provider servers for verifying chat/benchmark apps.

Two stdlib-only HTTP servers that stand in for the real providers over
real HTTP, so a test suite can prove an app's wiring, scoring, and
failure handling without real models, real keys, or real spend:

- FakeOllamaServer: /api/tags, /api/chat, /api/generate, /api/show,
  /api/ps, /api/pull (streaming).
- FakeProviderServer: OpenAI-compatible /v1/models and
  /v1/chat/completions (SSE streaming + usage objects), with key
  checking, a bad-key 401 mode, and a dead mode.

Canned brains (smart / partial / dumb / broken) give deterministic
answers, and every request is recorded so tests can assert the exact
payload the app sent. Generalizes the fake servers proven in
OLLAMA System Test v3/v4/v5 and DUO v0.1-v0.3 verification
(see ~/workspace/ollama-system-test-v5-verify/fake_ollama.py).

Usage as a library:

    from fake_servers import FakeOllamaServer, FakeProviderServer
    ollama = FakeOllamaServer()   # binds 127.0.0.1 on an ephemeral port
    ollama.serve_forever()        # in a thread; ollama.port has the port
    ollama.chat_history           # every /api/chat payload received

Usage standalone (for poking by hand):

    python3 fake_servers.py ollama --port 11435
    python3 fake_servers.py provider --port 11436
"""

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---------------------------------------------------------------------------
# Canned brains. Deterministic on purpose: smart always answers right,
# partial answers some right, dumb answers wrong or refuses. A scoring
# bug then shows up as a wrong number, never as a flaky test.
# ---------------------------------------------------------------------------

SMART_ANSWER = "The capital of France is Paris."
PARTIAL_ANSWER = "I think it might be Paris, but I am not sure."
DUMB_ANSWER = "I cannot answer that question."

BRAINS = {
    "smart": SMART_ANSWER,
    "partial": PARTIAL_ANSWER,
    "dumb": DUMB_ANSWER,
}

# model name -> brain. Extend per test run by passing models= to the
# server constructor.
DEFAULT_OLLAMA_MODELS = {
    "fake-smart:1b": "smart",
    "fake-partial:1b": "partial",
    "fake-dumb:1b": "dumb",
}
BROKEN_OLLAMA_MODEL = "fake-broken:1b"

DEFAULT_PROVIDER_MODELS = {
    "fake-gpt-smart": "smart",
    "fake-gpt-partial": "partial",
    "fake-gpt-dumb": "dumb",
}
BROKEN_PROVIDER_MODEL = "fake-gpt-broken"

# The fake provider accepts this key and rejects everything else.
# It is a fake key for a fake server; never a real credential.
FAKE_GOOD_KEY = "sk-fake-good-key"

# Fixed timing figures, so speed readouts are assertable exactly.
EVAL_COUNT = 20
EVAL_DURATION_NS = 200_000_000  # 20 tokens in 0.2 s = exactly 100 tok/s
PROMPT_EVAL_COUNT = 10
PROMPT_EVAL_DURATION_NS = 100_000_000
LOAD_DURATION_NS = 50_000_000


def _answer_for(brain, prompt):
    """Canned reply for a brain. The prompt is ignored on purpose:
    the fake answers from its script, never from understanding."""
    return BRAINS.get(brain, DUMB_ANSWER)


class _BaseHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep test output clean
        pass

    def _send_json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError:
            return None

    def _close_without_answer(self):
        """Dead-server mode: drop the connection with no response."""
        self.close_connection = True
        try:
            self.connection.shutdown(1)
        except OSError:
            pass
        try:
            self.connection.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Fake Ollama
# ---------------------------------------------------------------------------

class FakeOllamaHandler(_BaseHandler):
    def do_GET(self):
        if self.path == "/api/tags":
            models = [
                {"name": name, "size": 1_000_000_000,
                 "modified_at": "2026-11-12T00:00:00Z"}
                for name in sorted(self.server.models)
            ]
            models.append({"name": BROKEN_OLLAMA_MODEL,
                           "size": 500_000_000,
                           "modified_at": "2026-11-12T00:00:00Z"})
            self._send_json(200, {"models": models})
            return
        if self.path == "/api/ps":
            running = [
                {"name": name, "size": 1_000_000_000,
                 "size_vram": 1_000_000_000}
                for name in sorted(self.server.models)
            ]
            self._send_json(200, {"models": running})
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/api/pull":
            self._handle_pull()
            return
        if self.path == "/api/show":
            self._handle_show()
            return
        if self.path == "/api/chat":
            self._handle_chat()
            return
        if self.path == "/api/generate":
            self._handle_generate()
            return
        self._send_json(404, {"error": "not found"})

    def _model_or_error(self, model):
        """Return (brain, None) or (None, (code, payload))."""
        if model == BROKEN_OLLAMA_MODEL:
            return None, (500, {"error": "model exploded"})
        brain = self.server.models.get(model)
        if brain is None:
            return None, (404, {"error": "model '%s' not found" % model})
        return brain, None

    def _handle_show(self):
        payload = self._read_json()
        if payload is None:
            self._send_json(400, {"error": "bad json"})
            return
        model = payload.get("model")
        brain, err = self._model_or_error(model)
        if err is not None:
            self._send_json(*err)
            return
        caps = self.server.capabilities.get(model, [])
        self._send_json(200, {
            "model": model,
            "capabilities": sorted(caps),
            "details": {"family": "fake", "parameter_size": "1B"},
        })

    def _handle_chat(self):
        payload = self._read_json()
        if payload is None:
            self._send_json(400, {"error": "bad json"})
            return
        self.server.chat_count += 1
        if self.server.dead:
            self._close_without_answer()
            return
        model = payload.get("model")
        brain, err = self._model_or_error(model)
        if err is not None:
            self._send_json(*err)
            return
        messages = payload.get("messages") or []
        # Record the full history: tests prove the client sent every
        # earlier turn (multi-turn) or exactly the bare text (blind
        # relay), not just the latest prompt.
        self.server.chat_history.append(messages)
        self.server.chat_images_seen += sum(
            len(m.get("images") or []) for m in messages)
        if payload.get("tools"):
            self.server.chat_tools_seen += 1
        last_user = ""
        for message in messages:
            if message.get("role") == "user":
                last_user = message.get("content") or ""
        answer = _answer_for(brain, last_user)
        self._stream_ndjson(model, answer, payload.get("stream", True))

    def _handle_generate(self):
        payload = self._read_json()
        if payload is None:
            self._send_json(400, {"error": "bad json"})
            return
        if self.server.dead:
            self._close_without_answer()
            return
        model = payload.get("model")
        brain, err = self._model_or_error(model)
        if err is not None:
            self._send_json(*err)
            return
        prompt = payload.get("prompt") or ""
        self.server.generate_history.append(prompt)
        answer = _answer_for(brain, prompt)
        self._stream_ndjson(model, answer, payload.get("stream", True),
                            generate=True)

    def _stream_ndjson(self, model, answer, stream, generate=False):
        total = LOAD_DURATION_NS + PROMPT_EVAL_DURATION_NS + EVAL_DURATION_NS
        done = {
            "model": model,
            "created_at": "2026-11-12T00:00:00Z",
            "done": True,
            "done_reason": "stop",
            "total_duration": total,
            "load_duration": LOAD_DURATION_NS,
            "prompt_eval_count": PROMPT_EVAL_COUNT,
            "prompt_eval_duration": PROMPT_EVAL_DURATION_NS,
            "eval_count": EVAL_COUNT,
            "eval_duration": EVAL_DURATION_NS,
        }
        if generate:
            done["response"] = answer
        else:
            done["message"] = {"role": "assistant", "content": answer}
        if not stream:
            self._send_json(200, done)
            return
        chunk_delay = 1.0 if self.server.slow else 0.02
        chunk_count = 12 if self.server.slow else 3
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        try:
            n = len(answer)
            bounds = [round(n * i / chunk_count)
                      for i in range(chunk_count + 1)]
            for i in range(chunk_count):
                piece = answer[bounds[i]:bounds[i + 1]]
                line = {"model": model,
                        "created_at": "2026-11-12T00:00:00Z",
                        "done": False}
                if generate:
                    line["response"] = piece
                else:
                    line["message"] = {"role": "assistant",
                                       "content": piece}
                self.wfile.write((json.dumps(line) + "\n").encode("utf-8"))
                self.wfile.flush()
                time.sleep(chunk_delay)
            final = dict(done)
            if generate:
                final["response"] = ""
            else:
                final["message"] = {"role": "assistant", "content": ""}
            self.wfile.write((json.dumps(final) + "\n").encode("utf-8"))
            self.wfile.flush()
            self.server.chat_done += 1
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _handle_pull(self):
        payload = self._read_json()
        if payload is None:
            self._send_json(400, {"error": "bad json"})
            return
        name = payload.get("name", "")
        if self.server.pull_fail:
            self._send_json(500, {"error": "pull exploded"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        total = 100_000_000
        events = [
            {"status": "pulling manifest"},
            {"status": "downloading", "digest": "sha256:abc",
             "total": total, "completed": 25_000_000},
            {"status": "downloading", "digest": "sha256:abc",
             "total": total, "completed": 50_000_000},
            {"status": "downloading", "digest": "sha256:abc",
             "total": total, "completed": 75_000_000},
            {"status": "downloading", "digest": "sha256:abc",
             "total": total, "completed": 100_000_000},
            {"status": "verifying sha256 digest"},
            {"status": "writing manifest"},
            {"status": "success"},
        ]
        try:
            for event in events:
                self.wfile.write((json.dumps(event) + "\n").encode("utf-8"))
                self.wfile.flush()
                if event["status"] == "success":
                    # Record the pull the moment the client can see
                    # success, or the client's list refresh races us.
                    self.server.pulled.add(name)
                time.sleep(0.05)
        except (BrokenPipeError, ConnectionResetError):
            return


class FakeOllamaServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, host="127.0.0.1", port=0, models=None,
                 capabilities=None):
        self.models = dict(models) if models else dict(DEFAULT_OLLAMA_MODELS)
        self.capabilities = dict(capabilities) if capabilities else {
            "fake-smart:1b": ["vision", "tools", "long_context"],
            "fake-partial:1b": ["vision", "long_context"],
            "fake-dumb:1b": [],
        }
        self.chat_history = []       # every /api/chat messages list
        self.generate_history = []   # every /api/generate prompt
        self.chat_count = 0
        self.chat_done = 0
        self.chat_images_seen = 0
        self.chat_tools_seen = 0
        self.pulled = set()
        self.dead = False            # close without answering
        self.slow = False            # 1 s chunk delays (exact tok/s)
        self.pull_fail = False       # /api/pull answers 500
        super().__init__((host, port), FakeOllamaHandler)
        self.port = self.server_address[1]


# ---------------------------------------------------------------------------
# Fake OpenAI-compatible provider
# ---------------------------------------------------------------------------

class FakeProviderHandler(_BaseHandler):
    def _key_ok(self):
        auth = self.headers.get("Authorization") or ""
        return auth == "Bearer " + self.server.good_key

    def _unauthorized(self):
        self._send_json(401, {"error": {
            "message": "Incorrect API key provided.",
            "type": "invalid_request_error", "code": "invalid_api_key"}})

    def do_GET(self):
        if self.path != "/v1/models":
            self._send_json(404, {"error": "not found"})
            return
        if not self._key_ok():
            self._unauthorized()
            return
        data = [{"id": mid, "object": "model", "owned_by": "fake"}
                for mid in sorted(self.server.models)]
        self._send_json(200, {"object": "list", "data": data})

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self._send_json(404, {"error": "not found"})
            return
        self._handle_chat_completions()

    def _handle_chat_completions(self):
        payload = self._read_json()
        if payload is None:
            self._send_json(400, {"error": "bad json"})
            return
        self.server.chat_count += 1
        if self.server.dead:
            self._close_without_answer()
            return
        if not self._key_ok():
            self._unauthorized()
            return
        model = payload.get("model")
        if model == BROKEN_PROVIDER_MODEL:
            self._send_json(500, {"error": {"message": "model exploded"}})
            return
        brain = self.server.models.get(model)
        if brain is None:
            self._send_json(404, {"error": {"message":
                                            "model '%s' not found" % model}})
            return
        messages = payload.get("messages") or []
        self.server.chat_history.append(messages)
        last_user = ""
        for message in messages:
            if message.get("role") == "user":
                last_user = message.get("content") or ""
        answer = _answer_for(brain, last_user)
        usage = {"prompt_tokens": 20, "completion_tokens": 200,
                 "total_tokens": 220}
        stream = payload.get("stream", False)
        want_usage = bool((payload.get("stream_options") or {}).get(
            "include_usage"))
        if not stream:
            self._send_json(200, {
                "id": "chatcmpl-fake", "object": "chat.completion",
                "model": model,
                "choices": [{"index": 0,
                             "message": {"role": "assistant",
                                         "content": answer},
                             "finish_reason": "stop"}],
                "usage": usage})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            chunks = [answer[:len(answer) // 2], answer[len(answer) // 2:]]
            for i, piece in enumerate(chunks):
                delta = {"role": "assistant"} if i == 0 else {}
                delta["content"] = piece
                event = {"id": "chatcmpl-fake",
                         "object": "chat.completion.chunk",
                         "model": model,
                         "choices": [{"index": 0, "delta": delta,
                                      "finish_reason": None}]}
                self.wfile.write(("data: %s\n\n" % json.dumps(event)
                                  ).encode("utf-8"))
                self.wfile.flush()
                time.sleep(0.02)
            last = {"id": "chatcmpl-fake",
                    "object": "chat.completion.chunk", "model": model,
                    "choices": [{"index": 0, "delta": {},
                                 "finish_reason": "stop"}]}
            if want_usage:
                last["usage"] = usage
            self.wfile.write(("data: %s\n\n" % json.dumps(last)
                              ).encode("utf-8"))
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


class FakeProviderServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, host="127.0.0.1", port=0, models=None,
                 good_key=FAKE_GOOD_KEY):
        self.models = dict(models) if models else dict(DEFAULT_PROVIDER_MODELS)
        self.good_key = good_key
        self.chat_history = []       # every /v1/chat/completions messages
        self.chat_count = 0
        self.dead = False            # close without answering
        super().__init__((host, port), FakeProviderHandler)
        self.port = self.server_address[1]


def main():
    parser = argparse.ArgumentParser(
        description="Run a fake provider server for manual testing.")
    parser.add_argument("kind", choices=["ollama", "provider"])
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    cls = FakeOllamaServer if args.kind == "ollama" else FakeProviderServer
    server = cls(host=args.host, port=args.port)
    print("fake %s on http://%s:%d (Ctrl+C to stop)"
          % (args.kind, args.host, server.port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
