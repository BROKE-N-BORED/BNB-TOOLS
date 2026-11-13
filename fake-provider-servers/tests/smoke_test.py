#!/usr/bin/env python3
"""Smoke test for fake_servers.py — starts both fake servers on
ephemeral ports and proves every endpoint and failure mode over real
HTTP. Run: python3 tests/smoke_test.py"""

import json
import os
import sys
import threading
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fake_servers import (  # noqa: E402
    BROKEN_OLLAMA_MODEL, BROKEN_PROVIDER_MODEL, FAKE_GOOD_KEY,
    FakeOllamaServer, FakeProviderServer)

PASSED = []
FAILED = []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print("%s %s%s" % ("PASS:" if cond else "FAIL:", name,
                       (" — " + detail) if detail and not cond else ""))


def get(base, path, headers=None):
    req = urllib.request.Request(base + path, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def post(base, path, payload, headers=None):
    data = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(headers or {})
    req = urllib.request.Request(base + path, data=data, headers=hdrs,
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def post_stream(base, path, payload, headers=None):
    """POST and return the raw streamed body lines."""
    data = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(headers or {})
    req = urllib.request.Request(base + path, data=data, headers=hdrs,
                                 method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, resp.read().decode("utf-8")


def main():
    ollama = FakeOllamaServer()
    provider = FakeProviderServer()
    threads = [threading.Thread(target=s.serve_forever, daemon=True)
               for s in (ollama, provider)]
    for t in threads:
        t.start()
    obase = "http://127.0.0.1:%d" % ollama.port
    pbase = "http://127.0.0.1:%d" % provider.port

    # --- Fake Ollama: /api/tags + /api/ps -------------------------------
    status, body = get(obase, "/api/tags")
    names = sorted(m["name"] for m in json.loads(body)["models"])
    check("tags lists all models + broken model",
          status == 200 and names == ["fake-broken:1b", "fake-dumb:1b",
                                      "fake-partial:1b", "fake-smart:1b"],
          str(names))
    status, body = get(obase, "/api/ps")
    check("ps lists running models",
          status == 200 and len(json.loads(body)["models"]) == 3)

    # --- Fake Ollama: /api/show capabilities ----------------------------
    status, body = post(obase, "/api/show", {"model": "fake-smart:1b"})
    check("show returns capabilities",
          status == 200 and json.loads(body)["capabilities"] ==
          ["long_context", "tools", "vision"], body[:120])
    status, body = post(obase, "/api/show", {"model": "fake-dumb:1b"})
    check("dumb model has no capabilities",
          status == 200 and json.loads(body)["capabilities"] == [])

    # --- Fake Ollama: /api/chat streaming NDJSON ------------------------
    status, raw = post_stream(
        obase, "/api/chat",
        {"model": "fake-smart:1b", "stream": True,
         "messages": [{"role": "user", "content": "hello"}]})
    lines = [json.loads(ln) for ln in raw.splitlines() if ln.strip()]
    text = "".join(ln.get("message", {}).get("content", "") for ln in lines)
    last = lines[-1]
    check("chat streams NDJSON ending done:true with timing",
          status == 200 and last["done"] is True
          and last["eval_count"] == 20
          and last["eval_duration"] == 200_000_000
          and text == "The capital of France is Paris.",
          "text=%r last=%r" % (text, last))
    check("chat history records the exact payload",
          ollama.chat_history[-1] ==
          [{"role": "user", "content": "hello"}],
          str(ollama.chat_history[-1]))

    # --- Fake Ollama: /api/chat non-streaming ---------------------------
    status, body = post(
        obase, "/api/chat",
        {"model": "fake-dumb:1b", "stream": False,
         "messages": [{"role": "user", "content": "hello"}]})
    payload = json.loads(body)
    check("non-stream chat returns one JSON object",
          status == 200 and payload["done"] is True
          and payload["message"]["content"] == "I cannot answer that "
          "question.", body[:160])

    # --- Fake Ollama: errors --------------------------------------------
    status, body = post(
        obase, "/api/chat",
        {"model": "no-such-model:1b", "stream": False,
         "messages": [{"role": "user", "content": "hi"}]})
    check("unknown model 404", status == 404, body[:100])
    status, body = post(
        obase, "/api/chat",
        {"model": BROKEN_OLLAMA_MODEL, "stream": False,
         "messages": [{"role": "user", "content": "hi"}]})
    check("broken model 500", status == 500
          and "exploded" in body, body[:100])

    # --- Fake Ollama: /api/generate -------------------------------------
    status, body = post(obase, "/api/generate",
                        {"model": "fake-partial:1b", "stream": False,
                         "prompt": "2+2?"})
    check("generate returns the partial brain answer",
          status == 200 and json.loads(body)["response"].startswith(
              "I think it might be Paris"), body[:120])
    check("generate history recorded",
          ollama.generate_history == ["2+2?"],
          str(ollama.generate_history))

    # --- Fake Ollama: /api/pull streaming -------------------------------
    status, raw = post_stream(obase, "/api/pull",
                              {"name": "fake-new:1b"})
    events = [json.loads(ln) for ln in raw.splitlines() if ln.strip()]
    check("pull streams progress and success",
          status == 200 and events[-1]["status"] == "success"
          and any(e["status"] == "downloading"
                  and e["completed"] == 50_000_000 for e in events),
          str(events[-1]))
    check("pulled model recorded at success",
          "fake-new:1b" in ollama.pulled)
    ollama.pull_fail = True
    status, body = post(obase, "/api/pull", {"name": "fake-new:1b"})
    check("pull failure mode 500", status == 500, body[:100])
    ollama.pull_fail = False

    # --- Fake Ollama: dead mode -----------------------------------------
    ollama.dead = True
    try:
        post(obase, "/api/chat",
             {"model": "fake-smart:1b", "stream": False,
              "messages": [{"role": "user", "content": "hi"}]})
        check("dead mode closes without answering", False,
              "got a response from a dead server")
    except Exception as exc:  # RemoteDisconnected / URLError
        check("dead mode closes without answering", True)
    finally:
        ollama.dead = False
    status, _ = get(obase, "/api/tags")
    check("server answers again after dead mode", status == 200)

    # --- Fake provider: /v1/models + key check --------------------------
    good = {"Authorization": "Bearer " + FAKE_GOOD_KEY}
    bad = {"Authorization": "Bearer sk-wrong-key"}
    status, body = get(pbase, "/v1/models", headers=good)
    ids = sorted(m["id"] for m in json.loads(body)["data"])
    check("provider models lists with good key",
          status == 200 and ids == ["fake-gpt-dumb", "fake-gpt-partial",
                                    "fake-gpt-smart"], str(ids))
    status, body = get(pbase, "/v1/models", headers=bad)
    check("bad key 401 on models", status == 401, body[:100])
    status, body = get(pbase, "/v1/models")
    check("missing key 401 on models", status == 401, body[:100])

    # --- Fake provider: chat completions, non-stream --------------------
    status, body = post(pbase, "/v1/chat/completions",
                        {"model": "fake-gpt-smart", "stream": False,
                         "messages": [{"role": "user",
                                       "content": "hello"}]},
                        headers=good)
    payload = json.loads(body)
    check("provider non-stream completion + usage",
          status == 200
          and payload["choices"][0]["message"]["content"] ==
          "The capital of France is Paris."
          and payload["usage"] == {"prompt_tokens": 20,
                                   "completion_tokens": 200,
                                   "total_tokens": 220},
          body[:200])
    status, body = post(pbase, "/v1/chat/completions",
                        {"model": "fake-gpt-smart", "stream": False,
                         "messages": [{"role": "user",
                                       "content": "hello"}]},
                        headers=bad)
    check("provider bad key 401 on completions", status == 401)
    status, body = post(pbase, "/v1/chat/completions",
                        {"model": BROKEN_PROVIDER_MODEL, "stream": False,
                         "messages": [{"role": "user",
                                       "content": "hello"}]},
                        headers=good)
    check("provider broken model 500", status == 500, body[:100])

    # --- Fake provider: SSE streaming with usage ------------------------
    status, raw = post_stream(
        pbase, "/v1/chat/completions",
        {"model": "fake-gpt-partial", "stream": True,
         "stream_options": {"include_usage": True},
         "messages": [{"role": "user", "content": "hello"}]},
        headers=good)
    events = [json.loads(ln[6:]) for ln in raw.splitlines()
              if ln.startswith("data: ") and "[DONE]" not in ln]
    text = "".join(e["choices"][0]["delta"].get("content", "")
                   for e in events)
    check("provider SSE streams deltas, usage, [DONE]",
          status == 200 and raw.rstrip().endswith("data: [DONE]")
          and text == "I think it might be Paris, but I am not sure."
          and events[-1].get("usage", {}).get("total_tokens") == 220,
          "text=%r" % text)
    check("provider history records the exact payload",
          provider.chat_history[-1] ==
          [{"role": "user", "content": "hello"}],
          str(provider.chat_history[-1]))

    # --- Fake provider: SSE without include_usage has no usage ----------
    status, raw = post_stream(
        pbase, "/v1/chat/completions",
        {"model": "fake-gpt-smart", "stream": True,
         "messages": [{"role": "user", "content": "hello"}]},
        headers=good)
    check("no usage object unless requested",
          '"usage"' not in raw, raw[:200])

    # --- Fake provider: dead mode ---------------------------------------
    provider.dead = True
    try:
        post(pbase, "/v1/chat/completions",
             {"model": "fake-gpt-smart", "stream": False,
              "messages": [{"role": "user", "content": "hi"}]},
             headers=good)
        check("provider dead mode closes without answering", False,
              "got a response from a dead server")
    except Exception:
        check("provider dead mode closes without answering", True)
    finally:
        provider.dead = False

    ollama.shutdown()
    provider.shutdown()
    print("\n%d passed, %d failed" % (len(PASSED), len(FAILED)))
    if FAILED:
        print("FAILED:", ", ".join(FAILED))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
