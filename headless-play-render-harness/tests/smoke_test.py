#!/usr/bin/env python3
"""Smoke test for T13 headless-play-render-harness.

Three paths:
  1. --help + --check-deps (reports honestly what is present/missing)
  2. --mock run of the example plan (exercises plan/assert/measure/report)
  3. REAL DRIVER run against a fake CDP server (a minimal WebSocket server
     in this file that answers CDP methods like Chrome would). This verifies
     the actual WSClient + CDPDriver code end to end — the only part it
     cannot verify is a real Chrome binary, which this sandbox's bundled
     Chromium refuses to start (Hatch WebGL domain policy).
"""
import base64
import hashlib
import json
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
HARNESS = HERE.parent / "harness.py"
EXAMPLES = HERE.parent / "examples"
sys.path.insert(0, str(HERE.parent))
import harness as H  # noqa: E402


class FakeCDPServer(threading.Thread):
    """Minimal WebSocket server answering CDP methods like Chrome."""

    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(1)
        self.clicks = 0
        self.stopped = False

    def _read_exact(self, conn, n):
        buf = b""
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("closed")
            buf += chunk
        return buf

    def _read_frame(self, conn):
        b1, b2 = self._read_exact(conn, 2)
        ln = b2 & 0x7F
        if ln == 126:
            ln = struct.unpack(">H", self._read_exact(conn, 2))[0]
        elif ln == 127:
            ln = struct.unpack(">Q", self._read_exact(conn, 8))[0]
        mask = self._read_exact(conn, 4) if b2 & 0x80 else b""
        payload = self._read_exact(conn, ln)
        if mask:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return payload.decode("utf-8")

    def _send_frame(self, conn, text):
        payload = text.encode("utf-8")
        header = bytearray([0x81])
        if len(payload) < 126:
            header.append(len(payload))
        else:
            header.append(126)
            header += struct.pack(">H", len(payload))
        conn.sendall(bytes(header) + payload)

    def run(self):
        conn, _ = self.sock.accept()
        try:
            req = b""
            while b"\r\n\r\n" not in req:
                req += conn.recv(4096)
            key = [ln.split(":", 1)[1].strip()
                   for ln in req.decode().split("\r\n")
                   if ln.lower().startswith("sec-websocket-key")][0]
            accept = base64.b64encode(hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
            ).digest()).decode()
            conn.sendall(("HTTP/1.1 101 Switching Protocols\r\n"
                          "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                          "Sec-WebSocket-Accept: %s\r\n\r\n"
                          % accept).encode())
            while not self.stopped:
                try:
                    msg = json.loads(self._read_frame(conn))
                except (ConnectionError, json.JSONDecodeError):
                    break
                method, mid = msg.get("method"), msg.get("id")
                result = {}
                if method == "Runtime.evaluate":
                    expr = msg["params"]["expression"]
                    if expr == "document.title":
                        value = "Counter demo"
                    elif expr == "window.__state.ball.y":
                        value = 123.4
                    elif expr == "window.__state.count === 3":
                        value = self.clicks >= 3
                    else:
                        value = None
                    result = {"result": {"type": "string"
                                        if isinstance(value, str)
                                        else "number",
                                        "value": value}}
                elif method == "Input.dispatchMouseEvent":
                    if msg["params"]["type"] == "mousePressed":
                        self.clicks += 1
                elif method == "Page.captureScreenshot":
                    result = {"data": base64.b64encode(H.PNG_1X1).decode()}
                self._send_frame(conn, json.dumps(
                    {"id": mid, "result": result}))
                if method == "Page.navigate":
                    self._send_frame(conn, json.dumps(
                        {"method": "Page.loadEventFired", "params": {}}))
        finally:
            conn.close()


def run(*args, timeout=120):
    return subprocess.run([sys.executable, str(HARNESS), *args],
                          capture_output=True, text=True, timeout=timeout)


def main():
    fails = []
    p = run("--help")
    print("== --help exit=%d" % p.returncode)
    if p.returncode != 0:
        fails.append("--help failed")

    p = run("--check-deps")
    print("== --check-deps exit=%d" % p.returncode)
    print(p.stdout)
    # exit 0 only if a browser was found; either way the report must print
    if "chrome/chromium binary" not in p.stdout:
        fails.append("--check-deps did not report on the browser")

    # Build a runnable plan from the example (fill in EXAMPLES_DIR).
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="t13-smoke-"))
    plan = json.loads((EXAMPLES / "counter-plan.json").read_text())
    plan["url"] = "file://" + str(EXAMPLES / "counter.html")
    plan_path = tmp / "smoke-plan.json"
    plan_path.write_text(json.dumps(plan, indent=2))
    out = tmp / "smoke-out-mock"

    p = run("--plan", str(plan_path), "--mock", "--out", str(out))
    print("== mock run exit=%d" % p.returncode)
    print(p.stdout)
    if p.returncode != 0 or "RESULT: PASS" not in p.stdout:
        fails.append("mock run should pass")
    report = json.loads((out / "report.json").read_text())
    if report["measurements"].get("ball_rest_y") != 123.4:
        fails.append("mock measurement wrong: %r" % report["measurements"])
    if report["saved"].get("title") != "Counter demo":
        fails.append("mock saved value wrong: %r" % report["saved"])
    shots = list(out.glob("*.png"))
    if not shots or shots[0].stat().st_size == 0:
        fails.append("mock run produced no screenshot")

    # Real driver against the fake CDP server.
    server = FakeCDPServer()
    server.start()
    time.sleep(0.2)
    out2 = tmp / "smoke-out-cdp"
    p = run("--plan", str(plan_path), "--out", str(out2),
            "--cdp-url", "ws://127.0.0.1:%d/devtools/page/fake" % server.port)
    print("== fake-CDP run exit=%d (server saw %d clicks)"
          % (p.returncode, server.clicks))
    print(p.stdout)
    server.stopped = True
    if p.returncode != 0 or "RESULT: PASS" not in p.stdout:
        fails.append("fake-CDP run should pass: %s" % p.stderr[-500:])
    if server.clicks != 3:
        fails.append("fake server should have seen 3 clicks, saw %d"
                     % server.clicks)
    report2 = json.loads((out2 / "report.json").read_text())
    if report2["measurements"].get("ball_rest_y") != 123.4:
        fails.append("CDP measurement wrong: %r" % report2["measurements"])

    if fails:
        print("\nSMOKE TEST: FAIL")
        for f in fails:
            print("  - " + f)
        return 1
    print("\nSMOKE TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
