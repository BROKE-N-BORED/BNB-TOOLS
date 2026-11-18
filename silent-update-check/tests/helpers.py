"""Test helpers: a fake GitHub release server and fake app builders.

No live network anywhere in the suite: every network test runs
against FakeReleaseServer on localhost, the T30/T33 pattern.
"""
import hashlib
import io
import json
import os
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = "BROKE-N-BORED/demo-app"
CURRENT = "0.1.0"
LATEST = "0.2.0"


def make_release_zip(version, extra_files=None):
    """The bytes of a release zip for a fake app at a version."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("VERSION", version + "\n")
        zf.writestr("main.py",
                    "# fake demo app\n"
                    "print('demo app version %s')\n" % version)
        for name, content in (extra_files or {}).items():
            zf.writestr(name, content)
    return buf.getvalue()


def make_bad_zip_bytes():
    """Bytes that are not a zip at all."""
    return b"this is not a zip file"


def make_fake_app(root, version, name="demo-app"):
    """A fake installed app: a dir with VERSION + main.py."""
    app_dir = os.path.join(root, name)
    os.makedirs(app_dir, exist_ok=True)
    with open(os.path.join(app_dir, "VERSION"), "w") as handle:
        handle.write(version + "\n")
    with open(os.path.join(app_dir, "main.py"), "w") as handle:
        handle.write("# fake demo app\n"
                     "print('demo app version %s')\n" % version)
    return app_dir


class FakeReleaseServer:
    """A configurable fake GitHub releases API on localhost.

    Config (constructor kwargs):
      tag: the release tag (default "v0.2.0")
      assets: list of (name, bytes) release files to serve
      checksums: {asset name: sidecar text}; an asset with no
        entry gets no sidecar asset at all. A sidecar entry of
        None means the sidecar asset exists but is empty.
      shared_sums: text of a shared SHA256SUMS asset to add to
        the release (None for no shared file)
      fail: None (normal) or one of:
        "404-release"  releases/latest answers 404, repo exists
        "404-repo"     releases/latest and the repo both 404
        "500"          releases/latest answers 500
        "bad-json"     releases/latest answers non-JSON
        "rate-limit"   releases/latest answers 403 with
                       rate-limit headers
      rate_limit_reset: epoch seconds for the reset header
      asset_fail: {asset name: status code} to fail a download
    Records:
      api_requests: paths hit on the API side (releases/latest
        and the repo check), in order
      headers_seen: the request headers of each API call, so
        tests can prove no Authorization header is ever sent
    """

    def __init__(self, tag="v" + LATEST, assets=None,
                 checksums=None, fail=None,
                 rate_limit_reset=1794567600, asset_fail=None,
                 shared_sums=None):
        self.tag = tag
        self.assets = dict(assets) if assets else {}
        self.checksums = checksums if checksums is not None else {}
        self.shared_sums = shared_sums
        self.fail = fail
        self.rate_limit_reset = rate_limit_reset
        self.asset_fail = asset_fail or {}
        self.api_requests = []
        self.headers_seen = []
        self._server = None
        self._thread = None
        if assets is None:
            # The default release: one linux zip + its sidecar,
            # unless the caller passed checksums explicitly
            # (an empty dict means "no sidecar on purpose").
            data = make_release_zip(LATEST)
            name = "demo-app-%s-linux.zip" % LATEST
            self.assets = {name: data}
            if checksums is None:
                self.checksums = {
                    name: "%s  %s\n"
                          % (hashlib.sha256(data).hexdigest(), name),
                }

    @property
    def api_base(self):
        return "http://127.0.0.1:%d" % self._server.server_port

    @property
    def asset_name(self):
        """The first asset name, for tests that need one."""
        return sorted(self.assets)[0]

    def __enter__(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def _send(self, status, body, ctype, extra=None):
                data = body if isinstance(body, bytes) \
                    else body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                for key, value in (extra or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(data)

            def _release_payload(self):
                base = server.api_base
                items = []
                for name in sorted(server.assets):
                    items.append({
                        "name": name,
                        "browser_download_url":
                            base + "/assets/" + name,
                    })
                    if name in server.checksums:
                        items.append({
                            "name": name + ".sha256",
                            "browser_download_url":
                                base + "/assets/" + name + ".sha256",
                        })
                if server.shared_sums is not None:
                    items.append({
                        "name": "SHA256SUMS",
                        "browser_download_url":
                            base + "/assets/SHA256SUMS",
                    })
                return {
                    "tag_name": server.tag,
                    "html_url": base + "/releases/" + server.tag,
                    "body": "Fake release for the test suite.",
                    "assets": items,
                }

            def do_GET(self):
                path = self.path.split("?", 1)[0]
                if path.endswith("/releases/latest"):
                    server.api_requests.append(path)
                    server.headers_seen.append(dict(self.headers))
                    if server.fail == "rate-limit":
                        self._send(403, "rate limited",
                                   "text/plain", {
                                       "X-RateLimit-Remaining": "0",
                                       "X-RateLimit-Reset":
                                           str(server.rate_limit_reset),
                                   })
                    elif server.fail == "500":
                        self._send(500, "server error", "text/plain")
                    elif server.fail == "bad-json":
                        self._send(200, "not json at all {",
                                   "application/json")
                    elif server.fail in ("404-release", "404-repo"):
                        self._send(404, "not found", "text/plain")
                    else:
                        self._send(200,
                                   json.dumps(self._release_payload()),
                                   "application/json")
                elif path.startswith("/repos/") \
                        and path.count("/") == 3:
                    # The repo-exists probe after a 404.
                    server.api_requests.append(path)
                    if server.fail == "404-repo":
                        self._send(404, "not found", "text/plain")
                    else:
                        self._send(200, json.dumps(
                            {"full_name": REPO}), "application/json")
                elif path.startswith("/assets/"):
                    name = path[len("/assets/"):]
                    if name in server.asset_fail:
                        self._send(server.asset_fail[name],
                                   "download failed", "text/plain")
                    elif name in server.assets:
                        self._send(200, server.assets[name],
                                   "application/octet-stream")
                    elif name.endswith(".sha256") and \
                            name[:-7] in server.checksums:
                        text = server.checksums[name[:-7]]
                        self._send(200, text or "", "text/plain")
                    elif name == "SHA256SUMS" and \
                            server.shared_sums is not None:
                        self._send(200, server.shared_sums,
                                   "text/plain")
                    else:
                        self._send(404, "not found", "text/plain")
                else:
                    self._send(404, "not found", "text/plain")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self.stop()
        return False

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
