"""Shared test helpers: deterministic test pictures and a fake Ollama.

The fake Ollama answers /api/tags and /api/generate with scripted
answers, so describe/escalation/timeout behaviour is provable with
no real model and no network beyond localhost.
"""

import json
import os
import random
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

GOOD_DESCRIPTION = ("A red bicycle leaning against a brick wall, with "
                    "a basket on the front and autumn leaves on the "
                    "ground beside it.")
BLIND_DESCRIPTION = "I cannot see the image clearly."
SHORT_DESCRIPTION = "A bike."


def make_image(path, width=1920, height=1080, noise=False):
    """Write a deterministic test picture (PNG unless .jpg)."""
    if noise:
        rng = random.Random(42)
        data = bytes(rng.randrange(256)
                     for _ in range(width * height * 3))
        img = Image.frombytes("RGB", (width, height), data)
    else:
        img = Image.new("RGB", (width, height), (180, 60, 40))
        for x in range(0, width, 40):
            for y in range(0, height, 40):
                if (x + y) % 80 == 0:
                    img.paste((40, 120, 200),
                              (x, y, x + 20, y + 20))
    img.save(path)
    return path


class FakeOllama:
    """A scriptable Ollama stand-in on localhost."""

    def __init__(self, models=None, responses=None, delay=0.0,
                 tags_delay=0.0):
        self.models = models if models is not None else [
            "minicpm-v", "qwen3-vl:2b-instruct"]
        self.responses = responses or {}
        self.delay = delay
        self.tags_delay = tags_delay
        self.calls = []       # (model, prompt) per /api/generate
        self.tags_calls = 0
        self._server = None
        self._thread = None

    @property
    def base_url(self):
        return "http://127.0.0.1:%d" % (
            self._server.server_address[1])

    def start(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path == "/api/tags":
                    fake.tags_calls += 1
                    if fake.tags_delay:
                        import time
                        time.sleep(fake.tags_delay)
                    payload = {"models": [{"name": m}
                                          for m in fake.models]}
                    self._send_json(payload)
                else:
                    self.send_error(404)

            def do_POST(self):
                if self.path != "/api/generate":
                    self.send_error(404)
                    return
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                model = body.get("model", "")
                fake.calls.append((model, body.get("prompt", "")))
                if fake.delay:
                    import time
                    time.sleep(fake.delay)
                text = fake.responses.get(
                    model, fake.responses.get(
                        "*", GOOD_DESCRIPTION))
                self._send_json({"model": model, "response": text,
                                 "done": True})

            def _send_json(self, payload):
                data = json.dumps(payload).encode("utf-8")
                try:
                    self.send_response(200)
                    self.send_header("Content-Type",
                                     "application/json")
                    self.send_header("Content-Length",
                                     str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    # The client gave up (the timeout test does this
                    # on purpose); a dead socket is not an error.
                    pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
