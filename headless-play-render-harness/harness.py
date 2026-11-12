#!/usr/bin/env python3
"""T13 — headless-play-render-harness (pairs with BNB SKILLS S24).

Drive a real page in headless Chrome at a phone viewport, run scripted
interactions, read live state, take screenshots, measure numbers, and report
pass/fail per step. Built for the "verify the way the user will use it"
discipline: phone-size viewports (360x800 / 430x950), human-style input
(clicks at coordinates, typed text), live state reads via JS evaluation,
and numeric measurement instead of eyeballing.

How it drives Chrome: the DevTools Protocol (CDP) over a WebSocket, with a
minimal WebSocket client written on the Python standard library (no
puppeteer, no playwright, no pip install). Chrome is launched with
--remote-debugging-port and the harness talks to its page target directly.

Browser requirement (read this first): the real path needs a working
headless Chrome/Chromium binary. Set it with --chrome or the CHROME_BIN
environment variable; without one the harness searches the usual paths.
--check-deps reports exactly what is present and what is missing.

Sandbox note (2026-11-12): this sandbox's bundled Chromium
(/opt/meta-chromium/chrome, a Hatch CVM build) refuses to start with
"Hatch WebGL domain policy is required for browser startup", so the real
Chrome path could NOT be exercised here. The driver code itself is verified
by the smoke test against a fake CDP server (see tests/smoke_test.py), and
--mock exercises the plan/assert/report logic without any browser. On a
normal Linux machine with stock chromium/chrome, the real path runs.

Plan format (JSON):
    {
      "viewport": {"width": 360, "height": 800,
                   "deviceScaleFactor": 2, "isMobile": true},
      "url": "file:///path/to/page.html",
      "steps": [
        {"action": "navigate", "url": "..."},
        {"action": "wait", "ms": 500},
        {"action": "click", "x": 180, "y": 400},
        {"action": "type", "text": "hello"},
        {"action": "key", "key": "Enter"},
        {"action": "evaluate", "expression": "document.title",
         "save": "title"},
        {"action": "assert",
         "expression": "window.__state.count === 3",
         "message": "counter reached 3"},
        {"action": "measure", "name": "ball_rest_y",
         "expression": "window.__state.ball.y"},
        {"action": "screenshot", "name": "after-click"}
      ],
      "mock": {"evaluate": {"document.title": "Mock page"}}
    }

Usage:
    harness.py --check-deps
    harness.py --plan plan.json --out out/
    harness.py --plan plan.json --mock --out out/
    harness.py --plan plan.json --cdp-url ws://127.0.0.1:9222/devtools/page/...

Exit code: 0 = all assertions passed, 1 = any failed / driver error.
"""
import argparse
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
import zlib

CHROME_CANDIDATES = [
    "/opt/meta-chromium/chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/snap/bin/chromium",
]

# A valid 1x1 transparent PNG, built with stdlib only (used by the mock
# browser so report shape matches the real path).
def _png_1x1():
    def chunk(typ, data):
        c = struct.pack(">I", len(data)) + typ + data
        return c + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    raw = b"\x00\x00\x00\x00\x00"  # one transparent RGBA pixel
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


PNG_1X1 = _png_1x1()


# ---------------------------------------------------------------- WebSocket
class WSClient:
    """Minimal WebSocket client (RFC 6455) on the stdlib. Client frames are
    masked, as the spec requires; server frames are read unmasked."""

    def __init__(self, url, timeout=30):
        from urllib.parse import urlparse
        u = urlparse(url)
        self.host, self.port = u.hostname, u.port or 80
        self.path = u.path + ("?" + u.query if u.query else "")
        self.sock = socket.create_connection((self.host, self.port),
                                             timeout=timeout)
        self.sock.settimeout(timeout)
        self._buf = b""
        key = base64.b64encode(os.urandom(16)).decode()
        req = ("GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\n"
               "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
               "Sec-WebSocket-Version: 13\r\n\r\n"
               % (self.path, self.host, self.port, key))
        self.sock.sendall(req.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("websocket handshake: no response")
            resp += chunk
        if b"101" not in resp.split(b"\r\n", 1)[0]:
            raise ConnectionError("websocket handshake rejected: %r"
                                  % resp[:200])

    def _read_exact(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("websocket closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def send_text(self, text):
        payload = text.encode("utf-8")
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        header = bytearray([0x81])
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        self.sock.sendall(bytes(header) + mask + masked)

    def recv_text(self):
        # Returns the next complete text message, skipping pings/pongs.
        while True:
            b1, b2 = self._read_exact(2)
            opcode = b1 & 0x0F
            masked = b2 & 0x80
            ln = b2 & 0x7F
            if ln == 126:
                ln = struct.unpack(">H", self._read_exact(2))[0]
            elif ln == 127:
                ln = struct.unpack(">Q", self._read_exact(8))[0]
            mask = self._read_exact(4) if masked else b""
            payload = self._read_exact(ln)
            if mask:
                payload = bytes(b ^ mask[i % 4]
                                for i, b in enumerate(payload))
            if opcode == 0x9:  # ping -> pong
                self.sock.sendall(b"\x8a\x80" + os.urandom(4))
                continue
            if opcode == 0x8:  # close
                raise ConnectionError("websocket closed by peer")
            if opcode == 0x1:
                return payload.decode("utf-8")

    def close(self):
        try:
            self.sock.sendall(b"\x88\x80" + os.urandom(4))
            self.sock.close()
        except OSError:
            pass


# ---------------------------------------------------------------- CDP driver
class CDPDriver:
    """Drives one Chrome page target over CDP."""

    def __init__(self, ws_url, timeout=30):
        self.ws = WSClient(ws_url, timeout=timeout)
        self._next_id = 0
        self._events = []

    def call(self, method, params=None, timeout=30):
        self._next_id += 1
        mid = self._next_id
        self.ws.send_text(json.dumps(
            {"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = json.loads(self.ws.recv_text())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError("CDP %s failed: %s"
                                       % (method, msg["error"]))
                return msg.get("result", {})
            self._events.append(msg)  # an event, not our reply
        raise TimeoutError("CDP %s timed out" % method)

    def wait_for_event(self, name, timeout=30):
        deadline = time.time() + timeout
        for i, ev in enumerate(self._events):
            if ev.get("method") == name:
                del self._events[i]
                return ev
        while time.time() < deadline:
            msg = json.loads(self.ws.recv_text())
            if msg.get("method") == name:
                return msg
            self._events.append(msg)
        raise TimeoutError("waiting for %s timed out" % name)

    # -- high-level steps ------------------------------------------------
    def setup(self, viewport):
        self.call("Page.enable")
        self.call("Runtime.enable")
        self.call("Emulation.setDeviceMetricsOverride", {
            "width": viewport.get("width", 360),
            "height": viewport.get("height", 800),
            "deviceScaleFactor": viewport.get("deviceScaleFactor", 2),
            "mobile": viewport.get("isMobile", True),
        })

    def navigate(self, url):
        self.call("Page.navigate", {"url": url})
        try:
            self.wait_for_event("Page.loadEventFired", timeout=30)
        except TimeoutError:
            pass  # data: URLs and slow pages may not fire; continue

    def click(self, x, y):
        for typ in ("mousePressed", "mouseReleased"):
            self.call("Input.dispatchMouseEvent", {
                "type": typ, "x": x, "y": y, "button": "left",
                "clickCount": 1})
            time.sleep(0.05)

    def type_text(self, text):
        self.call("Input.insertText", {"text": text})

    def key(self, key):
        for typ in ("keyDown", "keyUp"):
            self.call("Input.dispatchKeyEvent", {"type": typ, "key": key})
            time.sleep(0.03)

    def evaluate(self, expression):
        res = self.call("Runtime.evaluate", {
            "expression": expression, "returnByValue": True,
            "awaitPromise": True})
        if "exceptionDetails" in res:
            raise RuntimeError("JS error evaluating %r: %s"
                               % (expression,
                                  res["exceptionDetails"].get("text", "")))
        return res.get("result", {}).get("value")

    def screenshot(self):
        res = self.call("Page.captureScreenshot", {"format": "png"})
        return base64.b64decode(res["data"])

    def close(self):
        self.ws.close()


class ChromeLauncher:
    """Launches headless Chrome with remote debugging and returns the page
    target's WebSocket URL."""

    def __init__(self, chrome_bin):
        self.chrome_bin = chrome_bin
        self.proc = None
        self.profile = None

    def start(self):
        self.profile = tempfile.mkdtemp(prefix="t13-chrome-")
        cmd = [self.chrome_bin, "--headless=new", "--disable-gpu",
               "--no-sandbox", "--hide-scrollbars",
               "--remote-debugging-port=0",
               "--user-data-dir=" + self.profile,
               "about:blank"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        port = None
        for _ in range(100):
            port_file = os.path.join(self.profile, "DevToolsActivePort")
            if os.path.exists(port_file):
                with open(port_file) as f:
                    port = int(f.readline().strip())
                break
            if self.proc.poll() is not None:
                raise RuntimeError(
                    "Chrome exited immediately (exit %d) — see --check-deps "
                    "and the README's browser note" % self.proc.returncode)
            time.sleep(0.1)
        if port is None:
            raise RuntimeError("Chrome did not write DevToolsActivePort")
        return self._page_ws_url(port)

    def _page_ws_url(self, port):
        for _ in range(50):
            try:
                with urllib.request.urlopen(
                        "http://127.0.0.1:%d/json/list" % port,
                        timeout=5) as resp:
                    targets = json.loads(resp.read().decode())
                for t in targets:
                    if t.get("type") == "page":
                        return t["webSocketDebuggerUrl"]
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("no page target found on port %d" % port)

    def stop(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.profile:
            shutil.rmtree(self.profile, ignore_errors=True)


# ---------------------------------------------------------------- Mock browser
class MockDriver:
    """Stand-in browser that exercises the plan/assert/report logic with no
    browser at all. Evaluate results come from plan['mock']['evaluate'].
    Screenshots are 1x1 placeholder PNGs (labelled as mock in the report)."""

    def __init__(self, plan):
        self.mock = plan.get("mock", {})
        self.evals = self.mock.get("evaluate", {})
        self.url = None

    def setup(self, viewport):
        self.viewport = viewport

    def navigate(self, url):
        self.url = url

    def click(self, x, y):
        pass

    def type_text(self, text):
        pass

    def key(self, key):
        pass

    def evaluate(self, expression):
        if expression in self.evals:
            return self.evals[expression]
        raise RuntimeError(
            "mock browser has no canned value for %r — add it under "
            "plan['mock']['evaluate']" % expression)

    def screenshot(self):
        return PNG_1X1

    def close(self):
        pass


# ---------------------------------------------------------------- deps
def find_chrome(explicit=None):
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    env = os.environ.get("CHROME_BIN")
    if env and os.path.isfile(env):
        return env
    for name in ("chromium", "chromium-browser", "google-chrome",
                 "google-chrome-stable"):
        found = shutil.which(name)
        if found:
            return found
    for path in CHROME_CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


def check_deps():
    print("HEADLESS HARNESS — dependency check")
    print("-" * 60)
    chrome = find_chrome()
    print("  [%s] chrome/chromium binary: %s"
          % ("OK  " if chrome else "MISS", chrome or "not found"))
    starts = False
    start_note = ""
    if chrome:
        # A binary existing is not enough — actually start it. (Exit code
        # alone lies: this sandbox's bundled Chromium exits 0 while
        # printing a fatal startup error and no DOM.)
        try:
            p = subprocess.run(
                [chrome, "--headless=new", "--no-sandbox", "--disable-gpu",
                 "--dump-dom", "data:text/html,t13-start-probe"],
                capture_output=True, text=True, timeout=25)
            starts = "t13-start-probe" in p.stdout
            if not starts:
                err = (p.stderr or "").strip().splitlines()
                start_note = err[-1] if err else "no DOM output"
        except (OSError, subprocess.TimeoutExpired) as e:
            start_note = str(e)
        print("  [%s] chrome actually starts headless%s"
              % ("OK  " if starts else "MISS",
                 (": " + start_note) if start_note else ""))
    if not chrome:
        print("       searched CHROME_BIN, PATH "
              "(chromium, chromium-browser, google-chrome) and:")
        for p in CHROME_CANDIDATES:
            print("         %s" % p)
        print("       Install chromium (e.g. `sudo apt install chromium`) "
              "or point CHROME_BIN at a chrome binary.")
    print("  [%s] python3 %s" % ("OK  ", sys.version.split()[0]))
    node = shutil.which("node")
    print("  [%s] node: %s (optional — not needed; driver is pure Python)"
          % ("OK  " if node else " -- ", node or "not found"))
    print()
    if chrome and starts:
        print("Real-browser path: AVAILABLE (run without --mock).")
    elif chrome:
        print("Real-browser path: UNAVAILABLE — a binary exists at %s but "
              "it will not start headless here." % chrome)
        print("Use --mock, or install stock chromium/chrome.")
    else:
        print("Real-browser path: UNAVAILABLE — use --mock to exercise "
              "plan/assert/report logic, or install a browser.")
    return 0 if (chrome and starts) else 1


# ---------------------------------------------------------------- plan runner
def run_plan(plan, driver, outdir, mock=False):
    os.makedirs(outdir, exist_ok=True)
    viewport = plan.get("viewport", {"width": 360, "height": 800})
    results = {"viewport": viewport, "mock": mock, "steps": [],
               "measurements": {}, "saved": {}, "screenshots": []}
    driver.setup(viewport)
    if plan.get("url"):
        driver.navigate(plan["url"])
        results["steps"].append({"action": "navigate",
                                 "url": plan["url"], "status": "PASS"})
    failed = 0
    for i, step in enumerate(plan.get("steps", [])):
        action = step.get("action")
        rec = {"n": i + 1, "action": action, "status": "PASS"}
        try:
            if action == "navigate":
                driver.navigate(step["url"])
                rec["url"] = step["url"]
            elif action == "wait":
                time.sleep(step.get("ms", 500) / 1000.0)
            elif action == "click":
                driver.click(step["x"], step["y"])
                rec["at"] = [step["x"], step["y"]]
            elif action == "type":
                driver.type_text(step["text"])
            elif action == "key":
                driver.key(step["key"])
            elif action == "evaluate":
                value = driver.evaluate(step["expression"])
                rec["value"] = value
                if "save" in step:
                    results["saved"][step["save"]] = value
            elif action == "assert":
                value = driver.evaluate(step["expression"])
                rec["value"] = value
                if value is not True:
                    rec["status"] = "FAIL"
                    rec["detail"] = step.get("message", "") or (
                        "expected true, got %r" % (value,))
                    failed += 1
            elif action == "measure":
                value = driver.evaluate(step["expression"])
                results["measurements"][step["name"]] = value
                rec["name"], rec["value"] = step["name"], value
            elif action == "screenshot":
                name = "%02d-%s.png" % (i + 1, step.get("name", "shot"))
                path = os.path.join(outdir, name)
                with open(path, "wb") as f:
                    f.write(driver.screenshot())
                results["screenshots"].append(name)
                rec["file"] = name
            else:
                rec["status"] = "FAIL"
                rec["detail"] = "unknown action %r" % action
                failed += 1
        except Exception as e:
            rec["status"] = "FAIL"
            rec["detail"] = str(e)
            failed += 1
        results["steps"].append(rec)
    results["failed"] = failed
    return results


def write_report(results, outdir):
    lines = []
    lines.append("HEADLESS PLAY/RENDER REPORT%s"
                 % (" (MOCK BROWSER)" if results["mock"] else ""))
    vp = results["viewport"]
    lines.append("viewport: %dx%d (scale %s, mobile %s)"
                 % (vp.get("width"), vp.get("height"),
                    vp.get("deviceScaleFactor", 1),
                    vp.get("isMobile", False)))
    lines.append("-" * 60)
    for s in results["steps"]:
        extra = ""
        if "value" in s:
            extra = " -> %r" % (s["value"],)
        if s.get("detail"):
            extra += " | " + s["detail"]
        lines.append("[%s] #%s %s%s"
                     % (s["status"], s.get("n", "-"), s["action"], extra))
    if results["measurements"]:
        lines.append("-" * 60)
        lines.append("measurements:")
        for k, v in results["measurements"].items():
            lines.append("  %s = %r" % (k, v))
    if results["screenshots"]:
        lines.append("screenshots: %s" % ", ".join(results["screenshots"]))
    lines.append("-" * 60)
    n = len(results["steps"])
    lines.append("%d/%d steps passed"
                 % (n - results["failed"], n))
    lines.append("RESULT: %s" % ("PASS" if results["failed"] == 0
                                 else "FAIL"))
    text = "\n".join(lines) + "\n"
    with open(os.path.join(outdir, "report.txt"), "w") as f:
        f.write(text)
    with open(os.path.join(outdir, "report.json"), "w") as f:
        json.dump(results, f, indent=2)
    return text


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Headless play/render verification harness: drive a "
                    "page at phone viewport, script input, read live "
                    "state, screenshot, measure.")
    ap.add_argument("--plan", help="plan JSON file")
    ap.add_argument("--out", default="harness-out",
                    help="output dir for screenshots + report")
    ap.add_argument("--mock", action="store_true",
                    help="run against the mock browser (no browser needed)")
    ap.add_argument("--chrome", help="chrome/chromium binary to launch")
    ap.add_argument("--cdp-url",
                    help="connect to an already-running browser's page "
                         "target WebSocket URL instead of launching")
    ap.add_argument("--check-deps", action="store_true",
                    help="report browser/tool availability, run nothing")
    args = ap.parse_args(argv)

    if args.check_deps:
        return check_deps()
    if not args.plan:
        ap.error("--plan is required (or use --check-deps)")
    if not os.path.isfile(args.plan):
        print("error: no such plan file: %s" % args.plan, file=sys.stderr)
        return 2
    with open(args.plan) as f:
        plan = json.load(f)

    launcher = None
    try:
        if args.mock:
            driver = MockDriver(plan)
        elif args.cdp_url:
            driver = CDPDriver(args.cdp_url)
        else:
            chrome = find_chrome(args.chrome)
            if not chrome:
                print("error: no chrome/chromium binary found. "
                      "Run --check-deps, set CHROME_BIN, or use --mock.",
                      file=sys.stderr)
                return 2
            launcher = ChromeLauncher(chrome)
            driver = CDPDriver(launcher.start())
        try:
            results = run_plan(plan, driver, args.out, mock=args.mock)
        finally:
            driver.close()
    except (ConnectionError, RuntimeError, TimeoutError) as e:
        print("DRIVER ERROR: %s" % e, file=sys.stderr)
        return 1
    finally:
        if launcher:
            launcher.stop()

    print(write_report(results, args.out))
    return 0 if results["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
