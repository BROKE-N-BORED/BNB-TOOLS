#!/usr/bin/env python3
"""Demo harness for silent-update-check (BNB-TOOLS T36).

Proves each piece standalone and chained, with no network: a fake
local "release server" (an HTTP server on localhost) stands in
for GitHub, and a fake app (a temp dir with a VERSION file and a
tiny entry point) stands in for a real project.

Run it:

  python3 demo.py            # full chain, restart answer Yes
  python3 demo.py --answer no  # full chain, restart answer No,
                               # then a second "launch" applies
                               # the staged update with no
                               # re-download
  python3 demo.py --pieces   # each piece alone, one at a time

Everything happens in temp dirs and is deleted at the end. The
restart step never actually replaces this process: the demo
passes a recorder in place of os.execv and prints what the
restart would have run.
"""

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import silent_update_check as suc  # noqa: E402

REPO = "BROKE-N-BORED/demo-app"
CURRENT = "0.1.0"
LATEST = "0.2.0"
ASSET_NAME = "demo-app-0.2.0-linux.zip"


def make_release_zip(version):
    """The bytes of a release zip for a fake app at a version."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("VERSION", version + "\n")
        zf.writestr("main.py",
                    "# fake demo app\n"
                    "print('demo app version %s')\n" % version)
    return buf.getvalue()


def make_fake_app(root, version):
    """A fake installed app: a dir with VERSION + main.py."""
    app_dir = os.path.join(root, "demo-app")
    os.makedirs(app_dir, exist_ok=True)
    with open(os.path.join(app_dir, "VERSION"), "w") as handle:
        handle.write(version + "\n")
    with open(os.path.join(app_dir, "main.py"), "w") as handle:
        handle.write("# fake demo app\n"
                     "print('demo app version %s')\n" % version)
    return app_dir


class FakeReleaseServer:
    """A local HTTP server pretending to be GitHub releases.

    Serves one Latest Release: tag LATEST, one .zip asset for
    linux, and its .sha256 sidecar. Counts API requests, so the
    demo can show the launch check costs exactly one.
    """

    def __init__(self):
        self.zip_bytes = make_release_zip(LATEST)
        self.sha256 = hashlib.sha256(self.zip_bytes).hexdigest()
        self.requests = 0
        self._server = None
        self._thread = None

    @property
    def api_base(self):
        return "http://127.0.0.1:%d" % self._server.server_port

    def __enter__(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def _send(self, status, body, ctype):
                data = body if isinstance(body, bytes) \
                    else body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path.endswith("/releases/latest"):
                    server.requests += 1
                    base = server.api_base
                    payload = {
                        "tag_name": "v" + LATEST,
                        "html_url": base + "/releases/v" + LATEST,
                        "body": "Demo release: the fake app, "
                                "one version newer.",
                        "assets": [
                            {"name": ASSET_NAME,
                             "browser_download_url":
                                 base + "/assets/" + ASSET_NAME},
                            {"name": ASSET_NAME + ".sha256",
                             "browser_download_url":
                                 base + "/assets/" + ASSET_NAME
                                 + ".sha256"},
                        ],
                    }
                    self._send(200, json.dumps(payload),
                               "application/json")
                elif self.path.endswith("/" + ASSET_NAME):
                    self._send(200, server.zip_bytes,
                               "application/zip")
                elif self.path.endswith("/" + ASSET_NAME + ".sha256"):
                    text = "%s  %s\n" % (server.sha256, ASSET_NAME)
                    self._send(200, text, "text/plain")
                else:
                    self._send(404, "not found", "text/plain")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()
        return False


def show(title, result):
    print("[%s] %s" % (title, result.get("message", result)))


def run_pieces(server, root):
    """Each piece alone, in chain order, on a fresh fake app."""
    print("Each piece alone:")
    app_dir = make_fake_app(root, CURRENT)
    state_dir = suc.default_state_dir(app_dir)

    result = suc.check_for_update(REPO, CURRENT,
                                  api_base=server.api_base)
    show("1 check", result)
    assert result["status"] == "update-available"
    assert server.requests == 1, "the launch check is one request"

    pulled = suc.pull_update(result, state_dir)
    show("2 pull-verify", pulled)
    assert pulled["status"] == "staged"
    assert suc.load_state(state_dir)["pending"] is True

    applied = suc.apply_staged_update(app_dir, state_dir)
    show("3 install-swap", applied)
    assert applied["status"] == "applied"
    assert suc.read_version(app_dir) == LATEST

    calls = []

    def fake_prompt(question):
        calls.append(question)
        return True

    answer = suc.ask_restart(fake_prompt)
    print("[4 restart-prompt] asked: %r, answer: %s"
          % (calls[0][:50] + "...", "Yes" if answer else "No"))
    assert answer is True

    executed = []

    def fake_exec(executable, argv, cwd):
        executed.append((executable, argv, cwd))

    suc.restart_now(app_dir, "main.py", state_dir, exec_fn=fake_exec)
    print("[4 restart-prompt] would exec: %s"
          % " ".join(executed[0][1]))
    assert executed[0][2] == app_dir
    print("All four pieces work alone.")
    return app_dir


def run_chain(server, root, answer_yes):
    """The whole chain the way a launch wires it."""
    print("Full chain, restart answer: %s"
          % ("Yes" if answer_yes else "No"))
    app_dir = make_fake_app(root, CURRENT)
    state_dir = suc.default_state_dir(app_dir)

    # At launch: apply anything staged from last time.
    pending = suc.apply_pending_on_launch(app_dir, state_dir)
    print("launch: %s" % pending["message"])

    result = suc.check_for_update(REPO, CURRENT,
                                  api_base=server.api_base)
    show("check", result)
    if result["status"] != "update-available":
        print("No update: nothing happens, no popup, no noise.")
        return
    print("popup: an update is available (this is where the app "
          "asks; the demo answers Yes to the pull).")

    pulled = suc.pull_update(result, state_dir)
    show("pull-verify", pulled)

    calls = []

    def scripted_prompt(question):
        calls.append(question)
        return answer_yes

    if suc.ask_restart(scripted_prompt):
        executed = []

        def fake_exec(executable, argv, cwd):
            executed.append((executable, argv, cwd))

        suc.restart_now(app_dir, "main.py", state_dir,
                        exec_fn=fake_exec)
        print("restart: Yes, would exec %s"
              % " ".join(executed[0][1]))
        print("app version after restart: %s"
              % suc.read_version(app_dir))
        assert suc.read_version(app_dir) == LATEST
    else:
        print("restart: No, waiting for the next restart.")
        print("app version now: %s (still the old one)"
              % suc.read_version(app_dir))
        assert suc.read_version(app_dir) == CURRENT
        # Second launch: the staged update applies, no download.
        before = server.requests
        applied = suc.apply_pending_on_launch(app_dir, state_dir)
        show("next launch", applied)
        assert server.requests == before, \
            "no re-download on the next launch"
        print("app version after next launch: %s"
              % suc.read_version(app_dir))
        assert suc.read_version(app_dir) == LATEST
    print("Chain complete.")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Demo the silent-update-check pieces against "
                    "a fake local release server (no network).")
    parser.add_argument("--answer", choices=["yes", "no"],
                        default="yes",
                        help="scripted answer to the restart "
                             "prompt (default: yes)")
    parser.add_argument("--pieces", action="store_true",
                        help="run each piece alone instead of "
                             "the full chain")
    args = parser.parse_args(argv)
    root = tempfile.mkdtemp(prefix="suc-demo-")
    try:
        with FakeReleaseServer() as server:
            if args.pieces:
                run_pieces(server, root)
            else:
                run_chain(server, root, args.answer == "yes")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
