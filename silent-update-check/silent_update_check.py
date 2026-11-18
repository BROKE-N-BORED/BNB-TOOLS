#!/usr/bin/env python3
"""silent-update-check (BNB-TOOLS T36): the shared updater module.

One droppable file. A project copies this file in and gets the
standing order (Joshua, main chat 2026-11-17): on launch, the app
silently checks its GitHub repo for a newer Release. Up to date:
nothing happens, no popup, no noise. Update exists: a popup asks,
and only on the user's tap does the app pull. The pull verifies
the release's checksum/sidecar before installing, never a blind
download. After the pull it asks "restart now to complete the
update, yes or no": Yes restarts with the update applied, No waits
for the next restart, and the staged update survives until then
with no re-download.

Four chainable pieces, each a function, each runnable and testable
alone, each also a CLI subcommand:

  check          silent launch check vs the GitHub Latest Release
  pull-verify    ask-first pull + checksum/sidecar verification
  install-swap   safe swap-over install, never half-installed
  restart-prompt ask-first restart, staged update survives

A project that already has part of the flow (notify-only, for
example) imports only the pieces it is missing; see
missing_pieces() and the README. Multi-platform repos are
handled: only the matching platform's release assets are ever
offered (the Android Photo Transfer case: same repo holds
Windows releases).

Public repos only. This module sends no auth of any kind: no
token, no login, no Authorization header. A private repo
answers 404 or 403 to an unauthenticated request, and the check
reports that as "could not check" rather than guessing.

No blind downloads, ever: if the release carries no checksum
sidecar for the asset, the pull refuses. If the checksum does
not match, the staged files are deleted and nothing installs.

Standard library only. No network except the GitHub API and the
release download. The swap is rename-based on one filesystem,
so it either happens whole or not at all; a failed swap puts
the old version back. The staged update and the state file live
in a sibling directory next to the app (app_dir + ".update"),
so the swap never touches them and the staged update survives
a restart.

Usage as a library (the intended shape for a Qt app):

  import silent_update_check as suc
  suc.apply_pending_on_launch(app_dir, state_dir)  # at startup
  result = suc.check_for_update("OWNER/REPO", current_version)
  if result["status"] == "update-available":
      if popup_asks_user_to_pull(result):          # your popup
          pulled = suc.pull_update(result, state_dir)
          if pulled["status"] == "staged":
              if suc.ask_restart(popup_asks_yes_or_no):  # your popup
                  suc.restart_now(app_dir, "main.py", state_dir)

Usage as a CLI (each piece alone, or the whole chain with run):

  python3 silent_update_check.py check OWNER/REPO --current 0.1.0
  python3 silent_update_check.py pull OWNER/REPO --current 0.1.0 --app-dir /path/to/app
  python3 silent_update_check.py install --app-dir /path/to/app
  python3 silent_update_check.py restart --app-dir /path/to/app --entry main.py
  python3 silent_update_check.py run OWNER/REPO --current 0.1.0 --app-dir /path/to/app
  python3 silent_update_check.py apply-pending --app-dir /path/to/app
  python3 silent_update_check.py rollback --app-dir /path/to/app
  python3 silent_update_check.py debug-report [--out PATH]
  python3 silent_update_check.py --help

Exit codes: 0 the step did what it should, 1 nothing to do
(up to date, no update pulled, no staged update, user said no),
2 the step could not run (no network, repo not found, rate
limited, checksum mismatch, bad input). Errors are plain words
naming the missing thing, never a traceback.

The --api-base flag (and the SILENT_UPDATE_API_BASE environment
variable) point the module at a different GitHub API base URL.
They exist for the test suite and the demo, which run against a
local fake release server. Do not use them for real checks.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

VERSION = "0.1.0"
APP_SLUG = "silent-update-check"
DEFAULT_API_BASE = "https://api.github.com"
DEFAULT_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 300
MIN_PYTHON = (3, 8)

# The debug log layer is imported lazily, inside _logger(): a launch
# check must be fast and silent, and the check/pull/install/restart
# path never touches the log layer, so importing this module must
# not pay the debug layer's import cost. write_debug_report() is
# the only caller that needs it.


class UpdateError(Exception):
    """A plain-words failure: the step could not run or finish."""


class RateLimited(UpdateError):
    """GitHub said the rate limit is reached. Never retried."""

    def __init__(self, reset_text):
        self.reset_text = reset_text  # human-readable time, or None
        if reset_text:
            message = ("GitHub API rate limit reached. No retry was "
                       "made. The limit resets at %s. Try again "
                       "after that time." % reset_text)
        else:
            message = ("GitHub API rate limit reached. No retry was "
                       "made. GitHub did not give a reset time. "
                       "Try again later.")
        super().__init__(message)


class ChecksumMismatch(UpdateError):
    """The downloaded file does not match the release checksum."""

    def __init__(self, asset_name):
        super().__init__(
            "Checksum mismatch for %s: the downloaded file does not "
            "match the release checksum. Nothing was installed and "
            "the staged files were deleted. Try the pull again; if "
            "it keeps failing, the release itself may be bad."
            % asset_name)


class NoChecksum(UpdateError):
    """The release carries no checksum for this asset."""

    def __init__(self, asset_name):
        super().__init__(
            "No checksum for %s in this release, so the pull "
            "refuses: installing without a checksum would be a "
            "blind download. The release needs a checksum sidecar "
            "(.sha256 or SHA256SUMS) before it can be pulled."
            % asset_name)


# ---------------------------------------------------------------- versions

def parse_version(text):
    """(numeric parts, pre-release) for a version string.

    A leading "v" is ignored, build metadata after "+" is
    ignored, and a pre-release suffix after "-" is kept
    separately. Non-numeric parts are kept as strings and
    compare lexically. "1.2" and "1.2.0" parse to the same
    parts once padded, so they compare equal.
    """
    s = str(text).strip()
    if s[:1] in ("v", "V"):
        s = s[1:]
    if "+" in s:
        s = s.split("+", 1)[0]
    pre = None
    if "-" in s:
        s, pre = s.split("-", 1)
    parts = []
    for piece in s.split("."):
        piece = piece.strip()
        if piece == "":
            parts.append(0)
            continue
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(piece)
    return (tuple(parts), pre)


def compare_versions(a, b):
    """-1 if a < b, 0 if a == b, 1 if a > b.

    Numeric parts compare numerically, missing parts count as
    zero, and a release beats the same version with a
    pre-release suffix ("1.0" > "1.0-rc1").
    """
    parts_a, pre_a = parse_version(a)
    parts_b, pre_b = parse_version(b)
    for i in range(max(len(parts_a), len(parts_b))):
        x = parts_a[i] if i < len(parts_a) else 0
        y = parts_b[i] if i < len(parts_b) else 0
        if x == y:
            continue
        if isinstance(x, int) and isinstance(y, int):
            return -1 if x < y else 1
        return -1 if str(x) < str(y) else 1
    if pre_a == pre_b:
        return 0
    if pre_a is None:
        return 1
    if pre_b is None:
        return -1
    return -1 if pre_a < pre_b else 1


def is_newer(latest, current):
    """True when the latest version is newer than the current one."""
    return compare_versions(latest, current) > 0


# ---------------------------------------------------------------- platforms

# Markers are matched against the tokens of an asset name (the
# name lowercased and split on anything that is not a letter or
# digit). A marker matches a token that equals it or starts with
# it, so "win64" matches "win" but "twin" does not.
PLATFORM_MARKERS = {
    "linux": ("linux", "ubuntu", "debian", "mint", "fedora",
              "appimage"),
    "windows": ("win", "windows", "win32", "win64", "exe", "msi"),
    "macos": ("mac", "macos", "darwin", "dmg"),
    "android": ("android", "apk"),
}

CHECKSUM_NAMES = ("sha256sums", "sha256sums.txt",
                  "checksums.txt", "checksums.sha256")


def _name_tokens(name):
    return [t for t in re.split(r"[^a-z0-9]+", name.lower()) if t]


def asset_platforms(name):
    """The set of platforms an asset name claims.

    Empty means generic: the name carries no platform marker,
    so it matches every platform.
    """
    tokens = _name_tokens(name)
    found = set()
    for platform, markers in PLATFORM_MARKERS.items():
        for marker in markers:
            if any(t == marker or t.startswith(marker)
                   for t in tokens):
                found.add(platform)
                break
    return found


def asset_matches_platform(name, platform):
    """True when the asset is for this platform (or generic)."""
    claimed = asset_platforms(name)
    if not claimed:
        return True
    return platform in claimed


def is_checksum_name(name):
    """True when the asset is a checksum sidecar, not a release."""
    low = name.lower()
    return low.endswith(".sha256") or low in CHECKSUM_NAMES


def pick_asset(assets, platform):
    """The best release asset for this platform, or None.

    Checksum sidecars and assets with no download URL are
    skipped. Assets for other platforms are skipped. Among
    what is left, .zip wins, then .tar.gz/.tgz, then anything
    else, ties broken by name. Only .zip is installable in
    v0.1.0; a .tar.gz pick is reported as unsupported-format
    by the pull, not silently skipped here.
    """
    candidates = []
    for asset in assets:
        name = asset.get("name", "")
        if is_checksum_name(name):
            continue
        if not asset.get("browser_download_url"):
            continue
        if not asset_matches_platform(name, platform):
            continue
        candidates.append(asset)
    if not candidates:
        return None

    def rank(asset):
        name = asset["name"].lower()
        if name.endswith(".zip"):
            return 0
        if name.endswith(".tar.gz") or name.endswith(".tgz"):
            return 1
        if name.endswith(".tar.bz2"):
            return 2
        return 3

    candidates.sort(key=lambda a: (rank(a), a["name"].lower()))
    return candidates[0]


def find_checksum_asset(assets, asset_name):
    """The checksum sidecar for an asset, or None.

    Looks first for "<asset>.sha256", then for a shared sums
    file (SHA256SUMS, checksums.txt). A shared file is only
    useful if it names the asset; parse_checksum_file decides
    that at pull time.
    """
    wanted = asset_name.lower() + ".sha256"
    shared = None
    for asset in assets:
        name = asset.get("name", "")
        low = name.lower()
        if low == wanted:
            return asset
        if low in CHECKSUM_NAMES and shared is None:
            shared = asset
    return shared


# ---------------------------------------------------------------- checksums

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _is_sha256(text):
    return bool(_SHA256_RE.match(text or ""))


def sha256_file(path):
    """The SHA-256 hex digest of a file, read in chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def parse_checksum_file(text, asset_name):
    """The expected SHA-256 hex for asset_name, or None.

    Accepts a bare hash on its own, or sha256sum lines
    ("<hash>  <filename>", one or two spaces, an optional "*"
    before binary-mode names). A multi-line file must name
    the asset; a bare hash only counts when it is the whole
    file, so a stray hash in a long list never matches the
    wrong asset.
    """
    lines = [line.strip() for line in (text or "").splitlines()
             if line.strip()]
    if not lines:
        return None
    for line in lines:
        parts = line.split()
        if len(parts) >= 2:
            digest, fname = parts[0], parts[-1].lstrip("*")
            if (fname == asset_name
                    or fname.endswith("/" + asset_name)) \
                    and _is_sha256(digest):
                return digest.lower()
    if len(lines) == 1:
        parts = lines[0].split()
        if len(parts) == 1 and _is_sha256(parts[0]):
            return parts[0].lower()
    return None


# ---------------------------------------------------------------- http

def _request(url):
    """A GitHub request with a User-Agent and no auth of any kind."""
    return urllib.request.Request(
        url, headers={
            "User-Agent": "silent-update-check/%s" % VERSION,
            "Accept": "application/vnd.github+json",
        })


def _rate_limit_reset_text(headers):
    """Human-readable reset time from rate-limit headers, or None."""
    reset = headers.get("X-RateLimit-Reset")
    if not reset:
        return None
    try:
        when = datetime.datetime.fromtimestamp(
            int(reset), datetime.timezone.utc)
        return when.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, OverflowError):
        return None


def _http_error_message(error, what):
    """Plain-words message for an HTTP failure, or None to re-raise
    as a rate-limit error instead."""
    if error.code == 403 \
            and error.headers.get("X-RateLimit-Remaining") == "0":
        raise RateLimited(_rate_limit_reset_text(error.headers))
    if error.code == 404:
        return "%s was not found on GitHub (HTTP 404)." % what
    if error.code == 403:
        return ("GitHub refused the request (HTTP 403). Private "
                "repos answer this way: this module only checks "
                "public repos.")
    return "GitHub answered HTTP %d for %s." % (error.code, what)


def _get_json(url, timeout):
    """GET a URL and parse the JSON body. Raises UpdateError."""
    try:
        with urllib.request.urlopen(_request(url),
                                    timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        raise UpdateError(_http_error_message(error, url))
    except urllib.error.URLError as error:
        raise UpdateError(
            "Could not reach GitHub: %s. Check the network "
            "connection and try again." % error.reason)
    except TimeoutError:
        raise UpdateError(
            "GitHub did not answer in %d seconds. Try again."
            % timeout)
    try:
        return json.loads(body)
    except ValueError:
        raise UpdateError(
            "GitHub answered with something that is not JSON. "
            "Try again.")


def _get_bytes(url, timeout):
    """GET a URL and return the raw bytes. Raises UpdateError."""
    try:
        with urllib.request.urlopen(_request(url),
                                    timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as error:
        raise UpdateError(_http_error_message(error, url))
    except urllib.error.URLError as error:
        raise UpdateError(
            "Could not reach GitHub: %s. Check the network "
            "connection and try again." % error.reason)
    except TimeoutError:
        raise UpdateError(
            "GitHub did not answer in %d seconds. Try again."
            % timeout)


def _get_text(url, timeout):
    return _get_bytes(url, timeout).decode("utf-8", "replace")


def _repo_exists(repo, api_base, timeout):
    """True when the repo exists (used only after a 404 on the
    releases call, to tell "no releases yet" from "no such
    repo"). A failure here is reported as "cannot tell"."""
    url = "%s/repos/%s" % (api_base.rstrip("/"), repo)
    try:
        with urllib.request.urlopen(_request(url),
                                    timeout=timeout) as resp:
            resp.read()
        return True
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False
        raise UpdateError(_http_error_message(error, url))
    except urllib.error.URLError as error:
        raise UpdateError(
            "Could not reach GitHub: %s. Check the network "
            "connection and try again." % error.reason)


# ---------------------------------------------------------------- piece 1:
# check: the silent launch check

def check_for_update(repo, current_version, platform="linux",
                     api_base=DEFAULT_API_BASE,
                     timeout=DEFAULT_TIMEOUT):
    """Check the repo's Latest Release against current_version.

    Returns a dict, never prints (a launch check must be
    silent). Statuses:

      up-to-date              latest <= current, nothing to do
      update-available        a newer release with a matching
                              asset for this platform
      no-release-for-platform a newer release exists but none of
                              its assets is for this platform
      no-releases             the repo has no releases yet

    On update-available, "asset" is {"name", "url"} and
    "checksum_asset" is the sidecar {"name", "url"} or None.
    Raises UpdateError (plain words) when the check could not
    run: no network, repo not found, rate limited, bad reply.
    """
    if "/" not in repo or repo.count("/") != 1 \
            or not all(repo.split("/")):
        raise UpdateError(
            "Bad repo name: %r. Use the owner/repo shape, for "
            "example BROKE-N-BORED/PIXEL-FORGE." % repo)
    if platform not in PLATFORM_MARKERS:
        raise UpdateError(
            "Unknown platform: %r. Use one of: %s."
            % (platform, ", ".join(sorted(PLATFORM_MARKERS))))
    base = api_base.rstrip("/")
    url = "%s/repos/%s/releases/latest" % (base, repo)
    try:
        release = _get_json(url, timeout)
    except UpdateError as error:
        if "HTTP 404" in str(error):
            if _repo_exists(repo, api_base, timeout):
                return {
                    "status": "no-releases",
                    "repo": repo,
                    "current_version": current_version,
                    "latest_version": None,
                    "asset": None,
                    "checksum_asset": None,
                    "release_url": None,
                    "notes": None,
                    "message": "No releases published yet for %s."
                               % repo,
                }
            raise UpdateError(
                "Repo not found on GitHub: %s. Check the owner "
                "and repo name. Private repos also answer this "
                "way: this module only checks public repos."
                % repo)
        raise
    tag = release.get("tag_name") or ""
    if not tag:
        raise UpdateError(
            "The Latest Release for %s has no version tag."
            % repo)
    result = {
        "status": "up-to-date",
        "repo": repo,
        "current_version": current_version,
        "latest_version": tag,
        "asset": None,
        "checksum_asset": None,
        "release_url": release.get("html_url"),
        "notes": release.get("body"),
        "message": "Up to date: %s is the latest release."
                   % tag,
    }
    if not is_newer(tag, current_version):
        return result
    assets = release.get("assets") or []
    asset = pick_asset(assets, platform)
    if asset is None:
        result["status"] = "no-release-for-platform"
        result["message"] = (
            "Release %s is newer, but none of its files is for "
            "%s, so there is nothing to offer." % (tag, platform))
        return result
    sidecar = find_checksum_asset(assets, asset["name"])
    result["status"] = "update-available"
    result["asset"] = {
        "name": asset["name"],
        "url": asset["browser_download_url"],
    }
    result["checksum_asset"] = (
        {"name": sidecar["name"],
         "url": sidecar["browser_download_url"]}
        if sidecar else None)
    result["message"] = (
        "Update available: %s (you have %s)."
        % (tag, current_version))
    return result


# ---------------------------------------------------------------- state

def default_state_dir(app_dir):
    """Where staging and state live: a sibling of the app dir.

    A sibling, not a child, so the swap never touches it: the
    staged update and the state file survive the swap and the
    restart that follows.
    """
    app_dir = os.path.abspath(app_dir)
    parent = os.path.dirname(app_dir)
    return os.path.join(parent,
                        os.path.basename(app_dir) + ".update")


def read_version(app_dir):
    """The current version from the app's VERSION file, or None."""
    path = os.path.join(app_dir, "VERSION")
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    return None


def load_state(state_dir):
    """The state dict, or {} when there is no state file yet."""
    path = os.path.join(state_dir, "state.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def save_state(state_dir, state):
    """Write the state file atomically (temp file + rename)."""
    os.makedirs(state_dir, exist_ok=True)
    path = os.path.join(state_dir, "state.json")
    handle, tmp = tempfile.mkstemp(dir=state_dir,
                                   prefix=".state-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(state, out, indent=2, sort_keys=True)
            out.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _now_text():
    return datetime.datetime.now(
        datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- piece 2:
# pull-verify: ask-first pull + checksum verification

def _extract_zip(zip_path, dest_dir):
    """Extract a zip, refusing entries that escape dest_dir.

    Zip-slip guard: an entry with ".." or an absolute path is
    an error, not a write outside the staging dir.
    """
    dest = os.path.abspath(dest_dir)
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            target = os.path.abspath(os.path.join(dest,
                                                  info.filename))
            if target != dest and not target.startswith(dest + os.sep):
                raise UpdateError(
                    "The release zip holds a file that escapes "
                    "its own folder (%r). Refusing to extract it."
                    % info.filename)
        zf.extractall(dest)


def pull_update(check_result, state_dir, timeout=DOWNLOAD_TIMEOUT):
    """Pull and verify the update from a check result.

    Downloads the asset and its checksum sidecar into staging,
    verifies the SHA-256 before anything is installed, extracts
    the zip, and records the staged update in the state file.
    Returns a dict with one of these statuses:

      staged              verified, extracted, waiting to install
      no-checksum         the release has no usable checksum for
                          this asset: refusing a blind download
      checksum-mismatch   the download does not match the
                          checksum: staged files deleted
      unsupported-format  the asset is not a .zip (v0.1.0 only
                          installs zips)

    Raises UpdateError when the download itself fails. Nothing
    is ever installed by this piece: that is install-swap's job.
    """
    if check_result.get("status") != "update-available":
        raise UpdateError(
            "Nothing to pull: the check said %s."
            % check_result.get("status", "unknown"))
    asset = check_result["asset"]
    name = asset["name"]
    staging = os.path.join(state_dir, "staging")
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging, exist_ok=True)
    download_path = os.path.join(staging, name)
    try:
        data = _get_bytes(asset["url"], timeout)
    except UpdateError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    with open(download_path, "wb") as handle:
        handle.write(data)
    sidecar = check_result.get("checksum_asset")
    if sidecar is None:
        shutil.rmtree(staging, ignore_errors=True)
        raise NoChecksum(name)
    try:
        sidecar_text = _get_text(sidecar["url"], timeout)
    except UpdateError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    expected = parse_checksum_file(sidecar_text, name)
    if expected is None:
        shutil.rmtree(staging, ignore_errors=True)
        raise NoChecksum(name)
    actual = sha256_file(download_path)
    if actual != expected:
        shutil.rmtree(staging, ignore_errors=True)
        raise ChecksumMismatch(name)
    if not name.lower().endswith(".zip"):
        shutil.rmtree(staging, ignore_errors=True)
        return {
            "status": "unsupported-format",
            "version": check_result["latest_version"],
            "asset": name,
            "message": ("The release file %s is not a .zip, and "
                        "v0.1.0 only installs .zip releases. The "
                        "verified download was deleted." % name),
        }
    extracted = os.path.join(staging, "extracted")
    os.makedirs(extracted, exist_ok=True)
    try:
        _extract_zip(download_path, extracted)
    except (UpdateError, zipfile.BadZipFile, OSError) as error:
        shutil.rmtree(staging, ignore_errors=True)
        if isinstance(error, UpdateError):
            raise
        raise UpdateError(
            "The release zip %s could not be opened: %s."
            % (name, error))
    version = check_result["latest_version"]
    state = load_state(state_dir)
    state.update({
        "staged_version": version,
        "staged_dir": extracted,
        "staged_asset": name,
        "staged_at": _now_text(),
        "pending": True,
    })
    save_state(state_dir, state)
    return {
        "status": "staged",
        "version": version,
        "asset": name,
        "staged_dir": extracted,
        "message": ("Update %s pulled and verified. It installs "
                    "when you restart." % version),
    }


# ---------------------------------------------------------------- piece 3:
# install-swap: safe swap-over install

def apply_staged_update(app_dir, state_dir):
    """Swap the staged update into place, or report nothing staged.

    Rename-based on one filesystem, so the swap either happens
    whole or not at all: the current app moves to the backup
    slot, the staged version moves into its place. If the
    second rename fails, the backup moves straight back, so
    the app is never left half-installed. The previous version
    stays in the backup slot (one generation) for rollback().
    Returns a dict with status applied | nothing-staged |
    failed. A failed swap restores the old version and the
    state file still says pending, so the next launch retries.
    """
    state = load_state(state_dir)
    staged = state.get("staged_dir")
    version = state.get("staged_version")
    if not state.get("pending") or not staged \
            or not os.path.isdir(staged):
        return {
            "status": "nothing-staged",
            "message": "No staged update is waiting.",
        }
    backup_dir = os.path.join(state_dir, "backup")
    if os.path.exists(backup_dir):
        shutil.rmtree(backup_dir, ignore_errors=True)
    if os.path.exists(backup_dir):
        return {
            "status": "failed",
            "message": ("Could not clear the old backup, so the "
                        "update was not installed. The staged "
                        "update is still waiting."),
        }
    app_dir = os.path.abspath(app_dir)
    had_app = os.path.exists(app_dir)
    old_version = read_version(app_dir) if had_app else None
    if had_app:
        try:
            os.rename(app_dir, backup_dir)
        except OSError as error:
            return {
                "status": "failed",
                "message": ("Could not move the current app out "
                            "of the way (%s), so the update was "
                            "not installed. The staged update is "
                            "still waiting." % error),
            }
    try:
        os.rename(staged, app_dir)
    except OSError as error:
        if had_app:
            try:
                os.rename(backup_dir, app_dir)
            except OSError:
                pass
        return {
            "status": "failed",
            "message": ("The swap failed (%s). The old version "
                        "was put back. The staged update is "
                        "still waiting." % error),
        }
    state.update({
        "current_version": version,
        "backup_version": old_version,
        "pending": False,
        "staged_dir": None,
        "staged_version": None,
        "applied_at": _now_text(),
    })
    save_state(state_dir, state)
    return {
        "status": "applied",
        "version": version,
        "previous_version": old_version,
        "message": "Update %s is now installed." % version,
    }


def apply_pending_on_launch(app_dir, state_dir):
    """What an app calls at startup, before anything else.

    If a staged update is waiting (the user said No to the
    restart prompt last time), swap it in now, so the update
    completes on this restart with no re-download. Returns the
    same dict as apply_staged_update(); "nothing-staged" is
    the normal case and needs no action.
    """
    return apply_staged_update(app_dir, state_dir)


def rollback(app_dir, state_dir):
    """Restore the backup kept by the last swap.

    The current (broken) version moves aside to the failed
    slot, the backup moves back into place. Returns a dict
    with status restored | nothing-to-restore | failed.
    """
    backup_dir = os.path.join(state_dir, "backup")
    if not os.path.isdir(backup_dir):
        return {
            "status": "nothing-to-restore",
            "message": "No backup version is kept, so there is "
                       "nothing to roll back to.",
        }
    failed_dir = os.path.join(state_dir, "failed")
    if os.path.exists(failed_dir):
        shutil.rmtree(failed_dir, ignore_errors=True)
    app_dir = os.path.abspath(app_dir)
    if os.path.exists(app_dir):
        try:
            os.rename(app_dir, failed_dir)
        except OSError as error:
            return {
                "status": "failed",
                "message": "Could not move the current version "
                           "aside (%s), so nothing changed."
                           % error,
            }
    try:
        os.rename(backup_dir, app_dir)
    except OSError as error:
        try:
            os.rename(failed_dir, app_dir)
        except OSError:
            pass
        return {
            "status": "failed",
            "message": ("The rollback failed (%s). The current "
                        "version was put back." % error),
        }
    state = load_state(state_dir)
    state.update({
        "current_version": state.get("backup_version"),
        "backup_version": None,
        "pending": False,
        "rolled_back_at": _now_text(),
    })
    save_state(state_dir, state)
    return {
        "status": "restored",
        "version": state.get("current_version"),
        "message": "Rolled back to version %s."
                   % state.get("current_version"),
    }


# ---------------------------------------------------------------- piece 4:
# restart-prompt: ask-first restart

RESTART_QUESTION = (
    "Restart now to complete the update, yes or no? "
    "Yes restarts with the update applied. "
    "No waits for the next restart: the update is already "
    "downloaded and verified, so nothing is downloaded again."
)


def ask_restart(prompt_fn):
    """Ask the restart question through the caller's prompt.

    prompt_fn is a function taking the question text and
    returning True for Yes, False for No. A Qt app passes a
    popup; the CLI passes the stdin prompt. The module never
    shows UI of its own: the caller owns the popup, this
    function owns the question and the meaning of the answer.
    """
    return bool(prompt_fn(RESTART_QUESTION))


def restart_now(app_dir, entry, state_dir=None, exec_fn=None):
    """Apply any pending update, then restart into the app.

    Applies the staged update first (if one is waiting), then
    replaces this process with the app entry point, run from
    the app dir. exec_fn defaults to os.execv; tests inject a
    recorder instead, so the restart is provable without
    actually replacing the test process. Raises UpdateError
    when the entry point is missing.
    """
    if state_dir is not None:
        result = apply_staged_update(app_dir, state_dir)
        if result["status"] == "failed":
            raise UpdateError(result["message"])
    entry_path = os.path.join(app_dir, entry)
    if not os.path.isfile(entry_path):
        raise UpdateError(
            "Cannot restart: the app entry point is missing: %s. "
            "The update is still staged and will apply on the "
            "next launch." % entry_path)
    argv = [sys.executable, entry_path]
    if exec_fn is None:
        os.chdir(app_dir)
        os.execv(sys.executable, argv)
    else:
        exec_fn(sys.executable, argv, app_dir)


# ---------------------------------------------------------------- partial
# implementations: only build what is missing

PIECES = ("check", "pull-verify", "install-swap", "restart-prompt")


def missing_pieces(has_check=False, has_pull=False,
                   has_install=False, has_restart=False):
    """The pieces a project still needs, given what it has.

    A project with notify-only (check) gets pull-verify,
    install-swap, and restart-prompt. A project with nothing
    gets all four. The answer is a list of piece names in
    chain order, so the builder works down the list.
    """
    have = {
        "check": has_check,
        "pull-verify": has_pull,
        "install-swap": has_install,
        "restart-prompt": has_restart,
    }
    return [piece for piece in PIECES if not have[piece]]


# ---------------------------------------------------------------- guards

def check_python_version(version_info=None):
    """None when the interpreter is new enough, else a plain-words
    message naming the missing piece. The module needs Python
    3.8+ (stdlib only, but the code uses 3.8 features)."""
    current = version_info if version_info is not None \
        else sys.version_info
    if current < MIN_PYTHON:
        return (
            "This tool needs Python %d.%d or newer, and this "
            "machine has Python %d.%d. Install a newer Python "
            "to run it."
            % (MIN_PYTHON[0], MIN_PYTHON[1],
               current[0], current[1]))
    return None


# ---------------------------------------------------------------- debug log

def _logger(log_dir):
    """A DebugLogger wired to this app, or None when the layer is
    unavailable.

    Imported here, not at module top, so the launch-check path
    never pays the debug layer's import cost. The log dir is a
    temp dir owned by the caller, so no logs/ directory is
    left behind. Settings carry the app version and the API
    base; there are no secrets (this module has no
    credentials) and the layer scrubs secret-shaped values
    anyway.
    """
    try:
        from debug_log import DebugLogger
    except ImportError:  # the module copied without its debug_log.py
        return None
    try:
        logger = DebugLogger(APP_SLUG, VERSION, log_dir=log_dir)
    except Exception:
        return None
    logger.set_setting("app_version", VERSION)
    logger.set_setting("api_base", DEFAULT_API_BASE)
    return logger


def _close_logger(logger):
    for handler in list(logger.logger.handlers):
        try:
            handler.close()
        finally:
            logger.logger.removeHandler(handler)


def write_debug_report(out=None):
    """Write a T21 debug report; returns the path, or None when
    the debug layer is not available."""
    if out is None:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        out = "debug-report-%s-%s.txt" % (APP_SLUG, stamp)
    with tempfile.TemporaryDirectory(prefix="suc-debug.") as tmp:
        logger = _logger(tmp)
        if logger is None:
            return None
        try:
            logger.info("debug report requested")
            return logger.generate_report(out)
        finally:
            _close_logger(logger)


# ---------------------------------------------------------------- CLI

def _stdin_prompt(message):
    """Yes/No on stdin. EOF or Ctrl-C counts as No."""
    try:
        answer = input(message + " (yes/no) ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("y", "yes")


def _api_base(args):
    return (getattr(args, "api_base", None)
            or os.environ.get("SILENT_UPDATE_API_BASE")
            or DEFAULT_API_BASE)


def _state_dir(args):
    if getattr(args, "state_dir", None):
        return args.state_dir
    return default_state_dir(args.app_dir)


def _current_version(args):
    if getattr(args, "current", None):
        return args.current
    app_dir = getattr(args, "app_dir", None)
    if app_dir is None:
        raise UpdateError(
            "No version given. Pass --current, or pass --app-dir "
            "so the version can be read from its VERSION file.")
    version = read_version(app_dir)
    if version is None:
        raise UpdateError(
            "No version given and no VERSION file in %s. Pass "
            "--current, or put the version in a VERSION file "
            "in the app dir." % app_dir)
    return version


def cmd_check(args):
    result = check_for_update(
        args.repo, _current_version(args),
        platform=args.platform, api_base=_api_base(args),
        timeout=args.timeout)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif not args.quiet or result["status"] != "up-to-date":
        print(result["message"])
        if result["status"] == "update-available" \
                and result.get("notes"):
            print()
            print(result["notes"])
    if result["status"] == "update-available":
        return 1
    return 0


def cmd_pull(args):
    result = check_for_update(
        args.repo, _current_version(args),
        platform=args.platform, api_base=_api_base(args),
        timeout=args.timeout)
    if result["status"] != "update-available":
        print(result["message"])
        return 1
    try:
        pulled = pull_update(result, _state_dir(args),
                             timeout=args.download_timeout)
    except (NoChecksum, ChecksumMismatch) as error:
        print("error: %s" % error, file=sys.stderr)
        return 2
    print(pulled["message"])
    return 0 if pulled["status"] == "staged" else 1


def cmd_install(args):
    result = apply_staged_update(args.app_dir, _state_dir(args))
    print(result["message"])
    return 0 if result["status"] == "applied" else 1


def cmd_apply_pending(args):
    result = apply_pending_on_launch(args.app_dir,
                                     _state_dir(args))
    if result["status"] != "nothing-staged":
        print(result["message"])
    return 0


def cmd_rollback(args):
    result = rollback(args.app_dir, _state_dir(args))
    print(result["message"])
    return 0 if result["status"] == "restored" else 1


def cmd_restart(args):
    if args.yes:
        answer = True
    elif args.no:
        answer = False
    else:
        answer = ask_restart(_stdin_prompt)
    if not answer:
        print("Not restarting now. The staged update will apply "
              "on the next launch.")
        return 1
    restart_now(args.app_dir, args.entry, _state_dir(args))
    return 0  # restart_now replaces the process; never reached


def cmd_run(args):
    """The whole chain, the way a launch wires it: check, ask,
    pull, ask, restart. Each ask is a real prompt; nothing
    downloads or restarts without a Yes."""
    result = check_for_update(
        args.repo, _current_version(args),
        platform=args.platform, api_base=_api_base(args),
        timeout=args.timeout)
    if result["status"] != "update-available":
        print(result["message"])
        return 1
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    print(result["message"])
    if result.get("notes"):
        print()
        print(result["notes"])
    if not _stdin_prompt("Pull this update now?"):
        print("Update not pulled.")
        return 1
    try:
        pulled = pull_update(result, _state_dir(args),
                             timeout=args.download_timeout)
    except (NoChecksum, ChecksumMismatch) as error:
        print("error: %s" % error, file=sys.stderr)
        return 2
    if pulled["status"] != "staged":
        print(pulled["message"])
        return 1
    print(pulled["message"])
    if ask_restart(_stdin_prompt):
        restart_now(args.app_dir, args.entry, _state_dir(args))
        return 0  # never reached: restart_now replaces us
    print("Not restarting now. The update is staged and will "
          "apply on the next launch.")
    return 1


def cmd_debug_report(args):
    path = write_debug_report(args.out)
    if path is None:
        print("error: the debug log layer is not available "
              "(debug_log.py is missing).", file=sys.stderr)
        return 2
    print("Debug report written to %s" % path)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="silent_update_check.py",
        description="Shared updater: silent launch check, "
                    "ask-first pull with checksum verification, "
                    "safe swap install, ask-first restart.")
    parser.add_argument("--version", action="version",
                        version="silent-update-check %s" % VERSION)
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    def repo_args(p):
        p.add_argument("repo", help="owner/repo on GitHub")
        p.add_argument("--current", default=None,
                       help="current version (default: read the "
                            "VERSION file in --app-dir)")
        p.add_argument("--platform", default="linux",
                       choices=sorted(PLATFORM_MARKERS),
                       help="platform to match release files "
                            "for (default: linux)")
        p.add_argument("--api-base", default=None,
                       help="GitHub API base URL, for tests only")
        p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                       help="seconds to wait for the GitHub reply "
                            "(default: %d)" % DEFAULT_TIMEOUT)

    def app_args(p):
        p.add_argument("--app-dir", required=True,
                       help="the installed app directory")
        p.add_argument("--state-dir", default=None,
                       help="staging/state dir (default: a "
                            "sibling of the app dir, named "
                            "<app>.update)")

    p = sub.add_parser("check", help="silent launch check: is a "
                       "newer release out?")
    repo_args(p)
    p.add_argument("--app-dir", default=None,
                   help="app dir, to read the VERSION file from "
                        "when --current is not given")
    p.add_argument("--json", action="store_true",
                   help="print the result as JSON")
    p.add_argument("--quiet", action="store_true",
                   help="print nothing when up to date")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("pull", help="pull the update and verify "
                       "its checksum (nothing installs yet)")
    repo_args(p)
    app_args(p)
    p.add_argument("--download-timeout", type=int,
                   default=DOWNLOAD_TIMEOUT,
                   help="seconds to wait for the download "
                        "(default: %d)" % DOWNLOAD_TIMEOUT)
    p.set_defaults(func=cmd_pull)

    p = sub.add_parser("install", help="swap the staged update "
                       "into place")
    app_args(p)
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("apply-pending", help="at launch: apply a "
                       "staged update waiting from last time")
    app_args(p)
    p.set_defaults(func=cmd_apply_pending)

    p = sub.add_parser("rollback", help="restore the version kept "
                       "by the last swap")
    app_args(p)
    p.set_defaults(func=cmd_rollback)

    p = sub.add_parser("restart", help="ask, then restart into "
                       "the updated app")
    app_args(p)
    p.add_argument("--entry", default="main.py",
                   help="app entry point inside the app dir "
                        "(default: main.py)")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--yes", action="store_true",
                       help="answer Yes without asking")
    group.add_argument("--no", action="store_true",
                       help="answer No without asking")
    p.set_defaults(func=cmd_restart)

    p = sub.add_parser("run", help="the whole chain: check, ask, "
                       "pull, ask, restart")
    repo_args(p)
    app_args(p)
    p.add_argument("--entry", default="main.py",
                   help="app entry point inside the app dir "
                        "(default: main.py)")
    p.add_argument("--download-timeout", type=int,
                   default=DOWNLOAD_TIMEOUT,
                   help="seconds to wait for the download "
                        "(default: %d)" % DOWNLOAD_TIMEOUT)
    p.add_argument("--json", action="store_true",
                   help="also print the check result as JSON")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("debug-report", help="write a T21 debug "
                       "report")
    p.add_argument("--out", default=None,
                   help="where to write the report (default: a "
                        "temp dir)")
    p.set_defaults(func=cmd_debug_report)

    return parser


def main(argv=None):
    too_old = check_python_version()
    if too_old is not None:
        print("error: %s" % too_old, file=sys.stderr)
        return 1
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except UpdateError as error:
        print("error: %s" % error, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())
