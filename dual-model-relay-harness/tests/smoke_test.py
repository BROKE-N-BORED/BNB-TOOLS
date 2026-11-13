#!/usr/bin/env python3
"""Smoke test for relay.py — runs real relays against a minimal
embedded fake Ollama stub (stdlib only, localhost, no network beyond
it) and proves the relay semantics: blind bare text, aware framing,
exact cap, phrase + agreement stops, transcript output.
Run: python3 tests/smoke_test.py"""

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import relay  # noqa: E402
from relay import OllamaClient, run_relay  # noqa: E402

PASSED = []
FAILED = []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print("%s %s%s" % ("PASS:" if cond else "FAIL:", name,
                       (" — " + detail) if detail and not cond else ""))


class StubHandler(BaseHTTPRequestHandler):
    """Minimal fake Ollama: /api/tags + non-streaming /api/chat.

    Replies are scripted per model from the server's `scripts` dict:
    each model answers with the next line of its script in turn.
    Every chat payload is recorded for exact-payload assertions.
    """

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send_json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            names = [{"name": n} for n in sorted(self.server.scripts)]
            self._send_json(200, {"models": names})
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/api/chat":
            self._send_json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        self.server.received.append(payload)
        model = payload.get("model")
        script = self.server.scripts.get(model)
        if script is None:
            self._send_json(404, {"error": "model '%s' not found" % model})
            return
        idx = self.server.counts.get(model, 0)
        self.server.counts[model] = idx + 1
        reply = script[min(idx, len(script) - 1)]
        self._send_json(200, {
            "model": model, "done": True,
            "message": {"role": "assistant", "content": reply},
            "eval_count": 10, "eval_duration": 100_000_000})


class StubServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, scripts):
        self.scripts = scripts
        self.received = []
        self.counts = {}
        super().__init__(("127.0.0.1", 0), StubHandler)
        self.port = self.server_address[1]


def fresh_client(scripts):
    server = StubServer(scripts)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = OllamaClient("http://127.0.0.1:%d" % server.port)
    return server, client


def main():
    # --- Blind relay: bare text, exact cap, alternation ---------------
    server, client = fresh_client({
        "model-a:1b": ["I think rain is lovely.",
                       "Rain on a tin roof, yes.",
                       "Agreed, rain it is."],
        "model-b:1b": ["Rain is nice, but sun is nicer.",
                       "Sun on the water, then."],
    })
    turns, reason = run_relay(
        client, {"A": "model-a:1b", "B": "model-b:1b"},
        seed="Talk about the weather.", start_side="A",
        turn_cap=4, mode="blind")
    check("blind relay halts at exactly the cap",
          len(turns) == 4 and reason == "turn cap reached",
          "turns=%d reason=%r" % (len(turns), reason))
    check("blind relay alternates A/B/A/B",
          [t["side"] for t in turns] == ["A", "B", "A", "B"])
    check("blind hop 2 delivers bare text",
          server.received[1]["messages"][-1] ==
          {"role": "user", "content": "I think rain is lovely."},
          str(server.received[1]["messages"]))
    check("blind hop carries no AI mention anywhere",
          all("AI" not in json.dumps(p) for p in server.received))
    check("each side keeps its own history",
          len(server.received[2]["messages"]) == 3  # user+asst+user
          and server.received[2]["messages"][0]["content"] ==
          "Talk about the weather.",
          str(server.received[2]["messages"]))
    server.shutdown()

    # --- Aware relay: framed text with the sending side's name ---------
    server, client = fresh_client({
        "model-a:1b": ["Pine is cheaper."],
        "model-b:1b": ["Oak lasts longer."],
    })
    turns, reason = run_relay(
        client, {"A": "model-a:1b", "B": "model-b:1b"},
        seed="Pine or oak?", start_side="A",
        turn_cap=2, mode="aware")
    check("aware hop frames with the sending side",
          server.received[1]["messages"][-1]["content"] ==
          "You are talking with another AI assistant (Model A). "
          "It said: Pine is cheaper.",
          str(server.received[1]["messages"]))
    check("seed is delivered bare in aware mode too",
          server.received[0]["messages"][-1]["content"] == "Pine or oak?")
    server.shutdown()

    # --- Agreement stop beats the cap ----------------------------------
    server, client = fresh_client({
        "model-a:1b": ["Let's use pine."],
        "model-b:1b": ["Sounds good, pine it is."],
    })
    turns, reason = run_relay(
        client, {"A": "model-a:1b", "B": "model-b:1b"},
        seed="Pick a wood.", start_side="A",
        turn_cap=10, mode="blind", stop_on_agreement=True)
    check("agreement stops early with the phrase named",
          len(turns) == 2
          and reason == "agreement reached ('sounds good')",
          "turns=%d reason=%r" % (len(turns), reason))
    server.shutdown()

    # --- Agreement ignored when the toggle is off ----------------------
    server, client = fresh_client({
        "model-a:1b": ["Let's use pine.", "Pine then."],
        "model-b:1b": ["Sounds good, pine it is.", "Fine."],
    })
    turns, reason = run_relay(
        client, {"A": "model-a:1b", "B": "model-b:1b"},
        seed="Pick a wood.", start_side="A",
        turn_cap=3, mode="blind", stop_on_agreement=False)
    check("no agreement stop without the toggle",
          len(turns) == 3 and reason == "turn cap reached",
          "turns=%d reason=%r" % (len(turns), reason))
    server.shutdown()

    # --- Stop phrase (case-insensitive) --------------------------------
    server, client = fresh_client({
        "model-a:1b": ["We should STOP here."],
        "model-b:1b": ["Why stop?"],
    })
    turns, reason = run_relay(
        client, {"A": "model-a:1b", "B": "model-b:1b"},
        seed="Go.", start_side="A", turn_cap=10, mode="blind",
        stop_phrases=["stop"])
    check("stop phrase matches case-insensitively, names the phrase",
          len(turns) == 1 and reason == "phrase 'stop' found",
          "turns=%d reason=%r" % (len(turns), reason))
    server.shutdown()

    # --- Phrase stop beats the cap on the same turn --------------------
    server, client = fresh_client({
        "model-a:1b": ["First.", "Second, and goodbye."],
        "model-b:1b": ["Reply."],
    })
    turns, reason = run_relay(
        client, {"A": "model-a:1b", "B": "model-b:1b"},
        seed="Go.", start_side="A", turn_cap=3, mode="blind",
        stop_phrases=["goodbye"])
    check("phrase stop reported before the cap on the same turn",
          len(turns) == 3 and reason == "phrase 'goodbye' found",
          "turns=%d reason=%r" % (len(turns), reason))
    server.shutdown()

    # --- Start with B; cap clamping ------------------------------------
    server, client = fresh_client({
        "model-a:1b": ["A here."],
        "model-b:1b": ["B here."],
    })
    turns, reason = run_relay(
        client, {"A": "model-a:1b", "B": "model-b:1b"},
        seed="Go.", start_side="B", turn_cap=1, mode="blind")
    check("start side B speaks first",
          len(turns) == 1 and turns[0]["side"] == "B")
    server.shutdown()
    check("cap clamps to 1-50",
          relay.clamp_cap(0) == 1 and relay.clamp_cap(99) == 50
          and relay.clamp_cap(10) == 10)

    # --- CLI end-to-end with transcript file ---------------------------
    server, client = fresh_client({
        "model-a:1b": ["One.", "Three."],
        "model-b:1b": ["Two."],
    })
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "relay.json")
        code = relay.main([
            "--model-a", "model-a:1b", "--model-b", "model-b:1b",
            "--seed", "Count with me.", "--start", "A", "--cap", "3",
            "--mode", "blind",
            "--ollama-url", "http://127.0.0.1:%d" % server.port,
            "--out", out])
        with open(out, encoding="utf-8") as fh:
            transcript = json.load(fh)
    check("CLI exits 0 and writes a full transcript",
          code == 0 and transcript["stop_reason"] == "turn cap reached"
          and len(transcript["turns"]) == 3
          and transcript["turns"][1]["received"] == "One."
          and transcript["turns"][1]["reply"] == "Two.",
          "code=%r transcript=%r" % (code, transcript))
    server.shutdown()

    # --- Ollama down: plain error, exit 1 ------------------------------
    code = relay.main([
        "--model-a", "model-a:1b", "--model-b", "model-b:1b",
        "--seed", "Hi.", "--cap", "1",
        "--ollama-url", "http://127.0.0.1:9"])  # nothing listens here
    check("Ollama down exits 1 with a plain error", code == 1,
          "code=%r" % code)

    print("\n%d passed, %d failed" % (len(PASSED), len(FAILED)))
    if FAILED:
        print("FAILED:", ", ".join(FAILED))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
