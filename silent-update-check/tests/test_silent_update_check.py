"""Tests for silent-update-check (BNB-TOOLS T36).

No live network: every network test runs against the fake
release server in helpers.py (localhost). The suite proves each
of the four pieces standalone, the chain end to end, the
no-blind-download rule, the safe swap, the restart ask, the
multi-platform repo case, and the partial-implementation case.
"""
import ast
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_DIR = os.path.dirname(HERE)
sys.path.insert(0, TOOL_DIR)
sys.path.insert(0, HERE)

import silent_update_check as suc  # noqa: E402
from helpers import (  # noqa: E402
    CURRENT,
    LATEST,
    REPO,
    FakeReleaseServer,
    make_bad_zip_bytes,
    make_fake_app,
    make_release_zip,
)

DEBUG_LOG_SHA = (
    "d304c17e6c607b58d44b201bd4df7b8c355acb796a10bb13029ab69ec19e73a2"
)
EM_DASH = "\u2014"


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="suc-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def app_and_state(self, version=CURRENT):
        app_dir = make_fake_app(self.tmp, version)
        return app_dir, suc.default_state_dir(app_dir)


class TestVersions(unittest.TestCase):
    def test_equal(self):
        self.assertEqual(suc.compare_versions("1.2.3", "1.2.3"), 0)

    def test_greater_and_lesser(self):
        self.assertEqual(suc.compare_versions("1.2.4", "1.2.3"), 1)
        self.assertEqual(suc.compare_versions("1.2.3", "1.2.4"), -1)

    def test_numeric_not_lexical(self):
        # 10 beats 9 numerically; lexically "10" < "9".
        self.assertEqual(suc.compare_versions("1.10.0", "1.9.0"), 1)

    def test_v_prefix_ignored(self):
        self.assertEqual(suc.compare_versions("v0.2.0", "0.2.0"), 0)
        self.assertEqual(suc.compare_versions("V1.0", "v1.0"), 0)

    def test_missing_parts_are_zero(self):
        self.assertEqual(suc.compare_versions("1.2", "1.2.0"), 0)
        self.assertEqual(suc.compare_versions("1", "1.0.0"), 0)

    def test_release_beats_prerelease(self):
        self.assertEqual(suc.compare_versions("1.0", "1.0-rc1"), 1)
        self.assertEqual(suc.compare_versions("1.0-rc1", "1.0"), -1)

    def test_prereleases_compare(self):
        self.assertEqual(suc.compare_versions("1.0-rc1", "1.0-rc2"),
                         -1)

    def test_build_metadata_ignored(self):
        self.assertEqual(
            suc.compare_versions("1.0+build5", "1.0"), 0)

    def test_non_numeric_parts(self):
        self.assertEqual(
            suc.compare_versions("1.0a", "1.0b"), -1)

    def test_is_newer(self):
        self.assertTrue(suc.is_newer("v0.2.0", "0.1.0"))
        self.assertFalse(suc.is_newer("0.1.0", "0.1.0"))
        self.assertFalse(suc.is_newer("0.0.9", "0.1.0"))

    def test_whitespace_tolerated(self):
        self.assertEqual(suc.compare_versions(" 0.2.0 ", "0.2.0"), 0)


class TestPlatforms(unittest.TestCase):
    def test_linux_markers(self):
        for name in ("app-1.0-linux.zip", "app-ubuntu.zip",
                     "app-linuxmint.tar.gz", "app.AppImage"):
            self.assertIn("linux", suc.asset_platforms(name))

    def test_windows_markers(self):
        for name in ("app-1.0-win64.zip", "app-windows.exe",
                     "app-setup.msi", "app-win32.zip"):
            self.assertIn("windows", suc.asset_platforms(name))

    def test_macos_markers(self):
        for name in ("app-1.0-mac.dmg", "app-macos.zip",
                     "app-darwin.tar.gz"):
            self.assertIn("macos", suc.asset_platforms(name))

    def test_android_markers(self):
        self.assertIn("android",
                      suc.asset_platforms("app-1.0-android.apk"))

    def test_generic_matches_everything(self):
        self.assertEqual(suc.asset_platforms("app-1.0.zip"), set())
        for platform in ("linux", "windows", "macos", "android"):
            self.assertTrue(
                suc.asset_matches_platform("app-1.0.zip", platform))

    def test_win_token_does_not_match_twin(self):
        # "twin" contains "win" but is not a windows marker.
        self.assertEqual(suc.asset_platforms("twin-1.0.zip"), set())

    def test_windows_asset_does_not_match_linux(self):
        self.assertFalse(suc.asset_matches_platform(
            "app-1.0-win64.zip", "linux"))
        self.assertTrue(suc.asset_matches_platform(
            "app-1.0-win64.zip", "windows"))

    def test_mixed_markers_claim_both(self):
        claimed = suc.asset_platforms("app-linux-win.zip")
        self.assertEqual(claimed, {"linux", "windows"})

    def test_case_insensitive(self):
        self.assertIn("linux",
                      suc.asset_platforms("APP-1.0-LINUX.ZIP"))

    def test_checksum_names(self):
        self.assertTrue(suc.is_checksum_name("app.zip.sha256"))
        self.assertTrue(suc.is_checksum_name("SHA256SUMS"))
        self.assertTrue(suc.is_checksum_name("checksums.txt"))
        self.assertFalse(suc.is_checksum_name("app.zip"))


class TestPickAsset(unittest.TestCase):
    def _asset(self, name):
        return {"name": name,
                "browser_download_url": "http://x/" + name}

    def test_zip_preferred_over_tarball(self):
        assets = [self._asset("app-1.0-linux.tar.gz"),
                  self._asset("app-1.0-linux.zip")]
        self.assertEqual(suc.pick_asset(assets, "linux")["name"],
                         "app-1.0-linux.zip")

    def test_platform_filter(self):
        assets = [self._asset("app-1.0-win64.zip"),
                  self._asset("app-1.0-linux.zip")]
        self.assertEqual(suc.pick_asset(assets, "linux")["name"],
                         "app-1.0-linux.zip")
        self.assertEqual(suc.pick_asset(assets, "windows")["name"],
                         "app-1.0-win64.zip")

    def test_sidecars_skipped(self):
        assets = [self._asset("app-1.0-linux.zip.sha256"),
                  self._asset("SHA256SUMS"),
                  self._asset("app-1.0-linux.zip")]
        self.assertEqual(suc.pick_asset(assets, "linux")["name"],
                         "app-1.0-linux.zip")

    def test_no_match_is_none(self):
        assets = [self._asset("app-1.0-win64.zip")]
        self.assertIsNone(suc.pick_asset(assets, "linux"))

    def test_no_url_skipped(self):
        assets = [{"name": "app-1.0-linux.zip"},
                  self._asset("app-1.0.zip")]
        self.assertEqual(suc.pick_asset(assets, "linux")["name"],
                         "app-1.0.zip")

    def test_generic_asset_is_fine(self):
        assets = [self._asset("app-1.0.zip")]
        self.assertEqual(suc.pick_asset(assets, "linux")["name"],
                         "app-1.0.zip")

    def test_find_checksum_asset_prefers_named_sidecar(self):
        assets = [self._asset("SHA256SUMS"),
                  self._asset("app.zip"),
                  self._asset("app.zip.sha256")]
        found = suc.find_checksum_asset(assets, "app.zip")
        self.assertEqual(found["name"], "app.zip.sha256")

    def test_find_checksum_asset_falls_back_to_shared(self):
        assets = [self._asset("SHA256SUMS"),
                  self._asset("app.zip")]
        found = suc.find_checksum_asset(assets, "app.zip")
        self.assertEqual(found["name"], "SHA256SUMS")

    def test_find_checksum_asset_none_when_absent(self):
        assets = [self._asset("app.zip")]
        self.assertIsNone(suc.find_checksum_asset(assets, "app.zip"))


class TestChecksumParsing(unittest.TestCase):
    HASH = "a" * 64
    OTHER = "b" * 64

    def test_bare_hash(self):
        self.assertEqual(
            suc.parse_checksum_file(self.HASH + "\n", "app.zip"),
            self.HASH)

    def test_sha256sum_two_column(self):
        text = "%s  app.zip\n" % self.HASH
        self.assertEqual(suc.parse_checksum_file(text, "app.zip"),
                         self.HASH)

    def test_sha256sum_binary_mode_star(self):
        text = "%s *app.zip\n" % self.HASH
        self.assertEqual(suc.parse_checksum_file(text, "app.zip"),
                         self.HASH)

    def test_multi_entry_picks_the_right_one(self):
        text = "%s  other.zip\n%s  app.zip\n" % (self.OTHER,
                                                 self.HASH)
        self.assertEqual(suc.parse_checksum_file(text, "app.zip"),
                         self.HASH)

    def test_wrong_file_is_none(self):
        text = "%s  other.zip\n" % self.HASH
        self.assertIsNone(suc.parse_checksum_file(text, "app.zip"))

    def test_bad_hash_is_none(self):
        self.assertIsNone(
            suc.parse_checksum_file("not-a-hash\n", "app.zip"))
        self.assertIsNone(
            suc.parse_checksum_file("xyz  app.zip\n", "app.zip"))

    def test_empty_is_none(self):
        self.assertIsNone(suc.parse_checksum_file("", "app.zip"))
        self.assertIsNone(suc.parse_checksum_file("  \n", "app.zip"))

    def test_sha256_file_matches_hashlib(self):
        data = b"hello update"
        path = os.path.join(tempfile.mkdtemp(), "f.bin")
        with open(path, "wb") as handle:
            handle.write(data)
        try:
            self.assertEqual(
                suc.sha256_file(path),
                hashlib.sha256(data).hexdigest())
        finally:
            os.unlink(path)


class TestMissingPieces(unittest.TestCase):
    def test_nothing_has_everything_missing(self):
        self.assertEqual(suc.missing_pieces(),
                         ["check", "pull-verify", "install-swap",
                          "restart-prompt"])

    def test_notify_only_gets_the_rest(self):
        # The GITDATA case: notify-only already exists.
        self.assertEqual(suc.missing_pieces(has_check=True),
                         ["pull-verify", "install-swap",
                          "restart-prompt"])

    def test_everything_present_is_empty(self):
        self.assertEqual(suc.missing_pieces(
            has_check=True, has_pull=True, has_install=True,
            has_restart=True), [])

    def test_partial_in_chain_order(self):
        self.assertEqual(suc.missing_pieces(has_pull=True),
                         ["check", "install-swap", "restart-prompt"])


class TestState(TempDirTest):
    def test_default_state_dir_is_a_sibling(self):
        app_dir = os.path.join(self.tmp, "my-app")
        state = suc.default_state_dir(app_dir)
        self.assertEqual(state,
                         os.path.join(self.tmp, "my-app.update"))
        self.assertNotEqual(os.path.dirname(state), app_dir)

    def test_save_and_load_round_trip(self):
        state_dir = os.path.join(self.tmp, "s")
        suc.save_state(state_dir, {"pending": True, "n": 3})
        self.assertEqual(suc.load_state(state_dir),
                         {"pending": True, "n": 3})

    def test_load_missing_is_empty(self):
        self.assertEqual(
            suc.load_state(os.path.join(self.tmp, "nope")), {})

    def test_load_corrupt_is_empty(self):
        state_dir = os.path.join(self.tmp, "s")
        os.makedirs(state_dir)
        with open(os.path.join(state_dir, "state.json"),
                  "w") as handle:
            handle.write("{not json")
        self.assertEqual(suc.load_state(state_dir), {})

    def test_read_version(self):
        app_dir = make_fake_app(self.tmp, "1.2.3")
        self.assertEqual(suc.read_version(app_dir), "1.2.3")
        self.assertIsNone(suc.read_version(self.tmp))


class TestPythonGuard(unittest.TestCase):
    def test_new_enough_is_none(self):
        self.assertIsNone(suc.check_python_version((3, 8, 0)))
        self.assertIsNone(suc.check_python_version((3, 12, 1)))

    def test_too_old_names_the_piece(self):
        message = suc.check_python_version((3, 7, 9))
        self.assertIn("Python 3.8", message)
        self.assertIn("Python 3.7", message)

    def test_running_interpreter_passes(self):
        self.assertIsNone(suc.check_python_version())


class TestCheck(TempDirTest):
    def check(self, server, current=CURRENT, platform="linux"):
        return suc.check_for_update(REPO, current,
                                    platform=platform,
                                    api_base=server.api_base)

    def test_update_available(self):
        with FakeReleaseServer() as server:
            result = self.check(server)
        self.assertEqual(result["status"], "update-available")
        self.assertEqual(result["latest_version"], "v" + LATEST)
        self.assertEqual(result["asset"]["name"],
                         server.asset_name)
        self.assertIsNotNone(result["checksum_asset"])
        self.assertIn("0.2.0", result["message"])

    def test_up_to_date(self):
        with FakeReleaseServer() as server:
            result = self.check(server, current=LATEST)
        self.assertEqual(result["status"], "up-to-date")
        self.assertIsNone(result["asset"])

    def test_up_to_date_when_ahead(self):
        with FakeReleaseServer() as server:
            result = self.check(server, current="9.9.9")
        self.assertEqual(result["status"], "up-to-date")

    def test_no_releases(self):
        with FakeReleaseServer(fail="404-release") as server:
            result = self.check(server)
        self.assertEqual(result["status"], "no-releases")
        self.assertIsNone(result["latest_version"])

    def test_repo_not_found(self):
        with FakeReleaseServer(fail="404-repo") as server:
            with self.assertRaises(suc.UpdateError) as caught:
                self.check(server)
        self.assertIn("not found", str(caught.exception))

    def test_rate_limit_names_reset_and_never_retries(self):
        with FakeReleaseServer(fail="rate-limit") as server:
            with self.assertRaises(suc.RateLimited) as caught:
                self.check(server)
            # Exactly one API request: no retry was made.
            self.assertEqual(len(server.api_requests), 1)
        # 1794567600 = 2026-11-13T11:00:00Z.
        self.assertIn("2026-11-13T11:00:00Z",
                      str(caught.exception))

    def test_server_error(self):
        with FakeReleaseServer(fail="500") as server:
            with self.assertRaises(suc.UpdateError) as caught:
                self.check(server)
        self.assertIn("500", str(caught.exception))

    def test_bad_json(self):
        with FakeReleaseServer(fail="bad-json") as server:
            with self.assertRaises(suc.UpdateError) as caught:
                self.check(server)
        self.assertIn("not JSON", str(caught.exception))

    def test_no_network(self):
        server = FakeReleaseServer()
        with server:
            base = server.api_base
        # The server is stopped now: the check cannot connect.
        with self.assertRaises(suc.UpdateError) as caught:
            suc.check_for_update(REPO, CURRENT, api_base=base,
                                 timeout=2)
        self.assertIn("Could not reach GitHub",
                      str(caught.exception))

    def test_no_auth_header_sent(self):
        with FakeReleaseServer() as server:
            self.check(server)
            for headers in server.headers_seen:
                lowered = {k.lower(): v
                           for k, v in headers.items()}
                self.assertNotIn("authorization", lowered)

    def test_launch_check_is_one_request(self):
        with FakeReleaseServer() as server:
            self.check(server)
            self.assertEqual(len(server.api_requests), 1)

    def test_no_release_for_platform(self):
        data = make_release_zip(LATEST)
        assets = [("demo-app-%s-win64.zip" % LATEST, data)]
        with FakeReleaseServer(assets=assets,
                               checksums={}) as server:
            result = self.check(server, platform="linux")
        self.assertEqual(result["status"],
                         "no-release-for-platform")
        self.assertIsNone(result["asset"])

    def test_multi_platform_repo_picks_the_match(self):
        # The Android Photo Transfer case: same repo holds
        # Windows releases; linux must only ever be offered
        # the linux file.
        data = make_release_zip(LATEST)
        digest = hashlib.sha256(data).hexdigest()
        win = "demo-app-%s-win64.zip" % LATEST
        lin = "demo-app-%s-linux.zip" % LATEST
        assets = [(win, data), (lin, data)]
        checksums = {win: "%s  %s\n" % (digest, win),
                     lin: "%s  %s\n" % (digest, lin)}
        with FakeReleaseServer(assets=assets,
                               checksums=checksums) as server:
            result = self.check(server, platform="linux")
        self.assertEqual(result["status"], "update-available")
        self.assertEqual(result["asset"]["name"], lin)

    def test_bad_repo_name(self):
        with FakeReleaseServer() as server:
            with self.assertRaises(suc.UpdateError) as caught:
                suc.check_for_update("no-slash-here", CURRENT,
                                     api_base=server.api_base)
        self.assertIn("owner/repo", str(caught.exception))

    def test_unknown_platform(self):
        with FakeReleaseServer() as server:
            with self.assertRaises(suc.UpdateError) as caught:
                suc.check_for_update(REPO, CURRENT,
                                     platform="amiga",
                                     api_base=server.api_base)
        self.assertIn("Unknown platform", str(caught.exception))

    def test_tag_without_v(self):
        with FakeReleaseServer(tag=LATEST) as server:
            result = self.check(server)
        self.assertEqual(result["status"], "update-available")


class TestPull(TempDirTest):
    def checked(self, server, **kwargs):
        return suc.check_for_update(REPO, CURRENT,
                                    api_base=server.api_base,
                                    **kwargs)

    def test_happy_path_stages_and_extracts(self):
        app_dir, state_dir = self.app_and_state()
        with FakeReleaseServer() as server:
            result = self.checked(server)
            pulled = suc.pull_update(result, state_dir)
        self.assertEqual(pulled["status"], "staged")
        self.assertEqual(pulled["version"], "v" + LATEST)
        state = suc.load_state(state_dir)
        self.assertTrue(state["pending"])
        self.assertEqual(state["staged_version"], "v" + LATEST)
        staged = state["staged_dir"]
        self.assertEqual(suc.read_version(staged), LATEST)
        self.assertTrue(os.path.isfile(
            os.path.join(staged, "main.py")))
        # The installed app is untouched until the swap.
        self.assertEqual(suc.read_version(app_dir), CURRENT)

    def test_checksum_mismatch_deletes_staging(self):
        data = make_release_zip(LATEST)
        name = "demo-app-%s-linux.zip" % LATEST
        wrong = "0" * 64
        app_dir, state_dir = self.app_and_state()
        with FakeReleaseServer(
                assets=[(name, data)],
                checksums={name: "%s  %s\n" % (wrong, name)}) \
                as server:
            result = self.checked(server)
            with self.assertRaises(suc.ChecksumMismatch):
                suc.pull_update(result, state_dir)
        self.assertFalse(os.path.exists(
            os.path.join(state_dir, "staging")))
        self.assertFalse(suc.load_state(state_dir).get("pending"))

    def test_no_sidecar_refuses(self):
        # No blind downloads: no checksum, no pull.
        with FakeReleaseServer(checksums={}) as server:
            result = self.checked(server)
            self.assertIsNone(result["checksum_asset"])
            with self.assertRaises(suc.NoChecksum):
                suc.pull_update(result, self.app_and_state()[1])

    def test_sidecar_not_naming_the_asset_refuses(self):
        data = make_release_zip(LATEST)
        name = "demo-app-%s-linux.zip" % LATEST
        digest = hashlib.sha256(data).hexdigest()
        with FakeReleaseServer(
                assets=[(name, data)],
                checksums={name: "%s  some-other.zip\n"
                           % digest}) as server:
            result = self.checked(server)
            with self.assertRaises(suc.NoChecksum):
                suc.pull_update(result, self.app_and_state()[1])

    def test_shared_sums_file_works(self):
        # A shared SHA256SUMS asset instead of a named sidecar:
        # the pull finds it, parses the line for this asset,
        # and verifies against it.
        data = make_release_zip(LATEST)
        name = "demo-app-%s-linux.zip" % LATEST
        digest = hashlib.sha256(data).hexdigest()
        sums = "%s  %s\n%s  other.zip\n" % (
            digest, name, "f" * 64)
        app_dir, state_dir = self.app_and_state()
        with FakeReleaseServer(
                assets=[(name, data)],
                checksums={},
                shared_sums=sums) as server:
            result = self.checked(server)
            self.assertIsNotNone(result["checksum_asset"])
            self.assertEqual(result["checksum_asset"]["name"],
                             "SHA256SUMS")
            pulled = suc.pull_update(result, state_dir)
        self.assertEqual(pulled["status"], "staged")

    def test_download_failure(self):
        data = make_release_zip(LATEST)
        name = "demo-app-%s-linux.zip" % LATEST
        with FakeReleaseServer(
                assets=[(name, data)],
                checksums={name: "%s  %s\n"
                           % (hashlib.sha256(data).hexdigest(),
                              name)},
                asset_fail={name: 500}) as server:
            result = self.checked(server)
            with self.assertRaises(suc.UpdateError) as caught:
                suc.pull_update(result, self.app_and_state()[1])
        self.assertIn("500", str(caught.exception))

    def test_bad_zip(self):
        name = "demo-app-%s-linux.zip" % LATEST
        data = make_bad_zip_bytes()
        with FakeReleaseServer(
                assets=[(name, data)],
                checksums={name: "%s  %s\n"
                           % (hashlib.sha256(data).hexdigest(),
                              name)}) as server:
            result = self.checked(server)
            with self.assertRaises(suc.UpdateError) as caught:
                suc.pull_update(result, self.app_and_state()[1])
        self.assertIn("could not be opened", str(caught.exception))

    def test_zip_slip_refused(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../escape.txt", "nope")
            zf.writestr("VERSION", LATEST + "\n")
        data = buf.getvalue()
        name = "demo-app-%s-linux.zip" % LATEST
        with FakeReleaseServer(
                assets=[(name, data)],
                checksums={name: "%s  %s\n"
                           % (hashlib.sha256(data).hexdigest(),
                              name)}) as server:
            result = self.checked(server)
            with self.assertRaises(suc.UpdateError) as caught:
                suc.pull_update(result, self.app_and_state()[1])
        self.assertIn("escapes", str(caught.exception))
        self.assertFalse(os.path.exists(
            os.path.join(self.tmp, "escape.txt")))

    def test_unsupported_format(self):
        data = b"fake tarball bytes"
        name = "demo-app-%s-linux.tar.gz" % LATEST
        with FakeReleaseServer(
                assets=[(name, data)],
                checksums={name: "%s  %s\n"
                           % (hashlib.sha256(data).hexdigest(),
                              name)}) as server:
            result = self.checked(server)
            pulled = suc.pull_update(result,
                                     self.app_and_state()[1])
        self.assertEqual(pulled["status"], "unsupported-format")
        self.assertIn("not a .zip", pulled["message"])

    def test_pull_requires_update_available(self):
        app_dir, state_dir = self.app_and_state()
        with FakeReleaseServer() as server:
            result = suc.check_for_update(
                REPO, LATEST, api_base=server.api_base)
        self.assertEqual(result["status"], "up-to-date")
        with self.assertRaises(suc.UpdateError):
            suc.pull_update(result, state_dir)

    def test_second_pull_replaces_first(self):
        app_dir, state_dir = self.app_and_state()
        with FakeReleaseServer() as server:
            result = self.checked(server)
            first = suc.pull_update(result, state_dir)
            second = suc.pull_update(result, state_dir)
        self.assertEqual(first["status"], "staged")
        self.assertEqual(second["status"], "staged")
        state = suc.load_state(state_dir)
        self.assertTrue(state["pending"])


class TestInstallSwap(TempDirTest):
    def staged(self, app_dir, state_dir):
        with FakeReleaseServer() as server:
            result = suc.check_for_update(
                REPO, CURRENT, api_base=server.api_base)
            pulled = suc.pull_update(result, state_dir)
        self.assertEqual(pulled["status"], "staged")
        return pulled

    def test_swap_installs_the_new_version(self):
        app_dir, state_dir = self.app_and_state()
        self.staged(app_dir, state_dir)
        applied = suc.apply_staged_update(app_dir, state_dir)
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(applied["version"], "v" + LATEST)
        self.assertEqual(applied["previous_version"], CURRENT)
        self.assertEqual(suc.read_version(app_dir), LATEST)
        self.assertTrue(os.path.isfile(
            os.path.join(app_dir, "main.py")))
        state = suc.load_state(state_dir)
        self.assertFalse(state["pending"])
        self.assertEqual(state["current_version"], "v" + LATEST)

    def test_backup_keeps_the_old_version(self):
        app_dir, state_dir = self.app_and_state()
        self.staged(app_dir, state_dir)
        suc.apply_staged_update(app_dir, state_dir)
        backup = os.path.join(state_dir, "backup")
        self.assertEqual(suc.read_version(backup), CURRENT)

    def test_nothing_staged(self):
        app_dir, state_dir = self.app_and_state()
        result = suc.apply_staged_update(app_dir, state_dir)
        self.assertEqual(result["status"], "nothing-staged")
        self.assertEqual(suc.read_version(app_dir), CURRENT)

    def test_staged_dir_missing_is_nothing_staged(self):
        app_dir, state_dir = self.app_and_state()
        suc.save_state(state_dir, {
            "pending": True,
            "staged_dir": os.path.join(state_dir, "gone"),
            "staged_version": "v9.9.9",
        })
        result = suc.apply_staged_update(app_dir, state_dir)
        self.assertEqual(result["status"], "nothing-staged")

    def test_failed_swap_puts_the_old_version_back(self):
        from unittest import mock
        app_dir, state_dir = self.app_and_state()
        self.staged(app_dir, state_dir)
        real_rename = os.rename
        calls = []

        def failing_rename(src, dst):
            calls.append((src, dst))
            if len(calls) == 2:
                raise OSError("simulated swap failure")
            return real_rename(src, dst)

        with mock.patch("os.rename", side_effect=failing_rename):
            result = suc.apply_staged_update(app_dir, state_dir)
        self.assertEqual(result["status"], "failed")
        # The old version is back in place, untouched.
        self.assertEqual(suc.read_version(app_dir), CURRENT)
        self.assertTrue(os.path.isfile(
            os.path.join(app_dir, "main.py")))
        # Still pending, so the next launch retries.
        self.assertTrue(suc.load_state(state_dir)["pending"])

    def test_first_install_without_an_app_dir(self):
        app_dir = os.path.join(self.tmp, "demo-app")
        state_dir = suc.default_state_dir(app_dir)
        with FakeReleaseServer() as server:
            result = suc.check_for_update(
                REPO, CURRENT, api_base=server.api_base)
            suc.pull_update(result, state_dir)
        applied = suc.apply_staged_update(app_dir, state_dir)
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(suc.read_version(app_dir), LATEST)

    def test_pending_survives_until_launch(self):
        # The "No" path: pull, do not install, and the staged
        # update is still there for the next launch.
        app_dir, state_dir = self.app_and_state()
        self.staged(app_dir, state_dir)
        self.assertEqual(suc.read_version(app_dir), CURRENT)
        applied = suc.apply_pending_on_launch(app_dir, state_dir)
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(suc.read_version(app_dir), LATEST)


class TestRestart(TempDirTest):
    def test_ask_yes(self):
        self.assertTrue(suc.ask_restart(lambda q: True))

    def test_ask_no(self):
        self.assertFalse(suc.ask_restart(lambda q: False))

    def test_question_text(self):
        seen = []
        suc.ask_restart(lambda q: seen.append(q) or False)
        self.assertEqual(len(seen), 1)
        self.assertIn("Restart now to complete the update, yes "
                      "or no?", seen[0])
        self.assertIn("next restart", seen[0])

    def test_restart_now_applies_pending_then_execs(self):
        app_dir, state_dir = self.app_and_state()
        with FakeReleaseServer() as server:
            result = suc.check_for_update(
                REPO, CURRENT, api_base=server.api_base)
            suc.pull_update(result, state_dir)
        executed = []

        def fake_exec(executable, argv, cwd):
            executed.append((executable, argv, cwd))

        suc.restart_now(app_dir, "main.py", state_dir,
                        exec_fn=fake_exec)
        # The pending update applied before the exec.
        self.assertEqual(suc.read_version(app_dir), LATEST)
        self.assertEqual(len(executed), 1)
        executable, argv, cwd = executed[0]
        self.assertEqual(cwd, app_dir)
        self.assertEqual(argv[1], os.path.join(app_dir, "main.py"))

    def test_restart_now_without_pending_still_execs(self):
        app_dir, state_dir = self.app_and_state()
        executed = []
        suc.restart_now(app_dir, "main.py", state_dir,
                        exec_fn=lambda e, a, c: executed.append(a))
        self.assertEqual(len(executed), 1)

    def test_restart_now_missing_entry_point(self):
        app_dir, state_dir = self.app_and_state()
        with self.assertRaises(suc.UpdateError) as caught:
            suc.restart_now(app_dir, "nope.py", state_dir,
                            exec_fn=lambda e, a, c: None)
        self.assertIn("entry point is missing",
                      str(caught.exception))

    def test_restart_now_without_state_dir(self):
        app_dir, _ = self.app_and_state()
        executed = []
        suc.restart_now(app_dir, "main.py", None,
                        exec_fn=lambda e, a, c: executed.append(a))
        self.assertEqual(len(executed), 1)


class TestLaunchAndRollback(TempDirTest):
    def test_launch_with_nothing_pending_is_a_noop(self):
        app_dir, state_dir = self.app_and_state()
        result = suc.apply_pending_on_launch(app_dir, state_dir)
        self.assertEqual(result["status"], "nothing-staged")
        self.assertEqual(suc.read_version(app_dir), CURRENT)

    def test_rollback_restores_the_backup(self):
        app_dir, state_dir = self.app_and_state()
        with FakeReleaseServer() as server:
            result = suc.check_for_update(
                REPO, CURRENT, api_base=server.api_base)
            suc.pull_update(result, state_dir)
        suc.apply_staged_update(app_dir, state_dir)
        self.assertEqual(suc.read_version(app_dir), LATEST)
        restored = suc.rollback(app_dir, state_dir)
        self.assertEqual(restored["status"], "restored")
        self.assertEqual(restored["version"], CURRENT)
        self.assertEqual(suc.read_version(app_dir), CURRENT)
        # The broken version was moved aside, not deleted.
        failed = os.path.join(state_dir, "failed")
        self.assertEqual(suc.read_version(failed), LATEST)

    def test_rollback_with_no_backup(self):
        app_dir, state_dir = self.app_and_state()
        result = suc.rollback(app_dir, state_dir)
        self.assertEqual(result["status"], "nothing-to-restore")
        self.assertEqual(suc.read_version(app_dir), CURRENT)


class TestChainEndToEnd(TempDirTest):
    def test_full_chain_yes_restart(self):
        app_dir, state_dir = self.app_and_state()
        with FakeReleaseServer() as server:
            base = server.api_base
            self.assertEqual(
                suc.apply_pending_on_launch(
                    app_dir, state_dir)["status"],
                "nothing-staged")
            result = suc.check_for_update(REPO, CURRENT,
                                          api_base=base)
            self.assertEqual(result["status"], "update-available")
            pulled = suc.pull_update(result, state_dir)
            self.assertEqual(pulled["status"], "staged")
            executed = []
            self.assertTrue(suc.ask_restart(lambda q: True))
            suc.restart_now(app_dir, "main.py", state_dir,
                            exec_fn=lambda e, a, c:
                            executed.append(a))
            self.assertEqual(len(executed), 1)
        self.assertEqual(suc.read_version(app_dir), LATEST)
        # The launch check cost exactly one API request.
        self.assertEqual(len(server.api_requests), 1)

    def test_full_chain_no_restart_then_next_launch(self):
        app_dir, state_dir = self.app_and_state()
        with FakeReleaseServer() as server:
            base = server.api_base
            result = suc.check_for_update(REPO, CURRENT,
                                          api_base=base)
            suc.pull_update(result, state_dir)
            self.assertFalse(suc.ask_restart(lambda q: False))
            # Still the old version: no restart happened.
            self.assertEqual(suc.read_version(app_dir), CURRENT)
            requests_after_pull = len(server.api_requests)
            # Next launch: applies with no re-download.
            applied = suc.apply_pending_on_launch(app_dir,
                                                  state_dir)
            self.assertEqual(applied["status"], "applied")
            self.assertEqual(len(server.api_requests),
                             requests_after_pull)
        self.assertEqual(suc.read_version(app_dir), LATEST)


class TestCLI(TempDirTest):
    def run_cli(self, argv, input_text=None):
        return subprocess.run(
            [sys.executable,
             os.path.join(TOOL_DIR, "silent_update_check.py")]
            + argv,
            input=input_text, capture_output=True, text=True,
            cwd=TOOL_DIR, timeout=120)

    def test_help(self):
        proc = self.run_cli(["--help"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("silent launch check", proc.stdout)
        self.assertNotIn(EM_DASH, proc.stdout)

    def test_version(self):
        proc = self.run_cli(["--version"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn(suc.VERSION, proc.stdout)

    def test_no_command_prints_help_and_exits_2(self):
        proc = self.run_cli([])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("usage:", proc.stdout)

    def test_check_update_available_exit_1(self):
        with FakeReleaseServer() as server:
            proc = self.run_cli([
                "check", REPO, "--current", CURRENT,
                "--api-base", server.api_base])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Update available", proc.stdout)

    def test_check_up_to_date_exit_0(self):
        with FakeReleaseServer() as server:
            proc = self.run_cli([
                "check", REPO, "--current", LATEST,
                "--api-base", server.api_base])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Up to date", proc.stdout)

    def test_check_quiet_prints_nothing_when_up_to_date(self):
        with FakeReleaseServer() as server:
            proc = self.run_cli([
                "check", REPO, "--current", LATEST, "--quiet",
                "--api-base", server.api_base])
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")

    def test_check_json(self):
        with FakeReleaseServer() as server:
            proc = self.run_cli([
                "check", REPO, "--current", CURRENT, "--json",
                "--api-base", server.api_base])
        self.assertEqual(proc.returncode, 1)
        data = json.loads(proc.stdout)
        self.assertEqual(data["status"], "update-available")
        self.assertEqual(data["latest_version"], "v" + LATEST)

    def test_check_bad_repo_exit_2_plain_words(self):
        with FakeReleaseServer() as server:
            proc = self.run_cli([
                "check", "no-slash", "--current", CURRENT,
                "--api-base", server.api_base])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("owner/repo", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_pull_then_install(self):
        app_dir, state_dir = self.app_and_state()
        with FakeReleaseServer() as server:
            proc = self.run_cli([
                "pull", REPO, "--current", CURRENT,
                "--app-dir", app_dir,
                "--api-base", server.api_base])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("pulled and verified", proc.stdout)
        self.assertEqual(suc.read_version(app_dir), CURRENT)
        proc = self.run_cli(["install", "--app-dir", app_dir])
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(suc.read_version(app_dir), LATEST)

    def test_pull_up_to_date_exit_1(self):
        app_dir, _ = self.app_and_state()
        with FakeReleaseServer() as server:
            proc = self.run_cli([
                "pull", REPO, "--current", LATEST,
                "--app-dir", app_dir,
                "--api-base", server.api_base])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Up to date", proc.stdout)

    def test_pull_no_checksum_exit_2(self):
        app_dir, _ = self.app_and_state()
        with FakeReleaseServer(checksums={}) as server:
            proc = self.run_cli([
                "pull", REPO, "--current", CURRENT,
                "--app-dir", app_dir,
                "--api-base", server.api_base])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("No checksum", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_install_nothing_staged_exit_1(self):
        app_dir, _ = self.app_and_state()
        proc = self.run_cli(["install", "--app-dir", app_dir])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("No staged update", proc.stdout)

    def test_apply_pending_at_launch(self):
        app_dir, state_dir = self.app_and_state()
        with FakeReleaseServer() as server:
            proc = self.run_cli([
                "pull", REPO, "--current", CURRENT,
                "--app-dir", app_dir,
                "--api-base", server.api_base])
        self.assertEqual(proc.returncode, 0)
        proc = self.run_cli(
            ["apply-pending", "--app-dir", app_dir])
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(suc.read_version(app_dir), LATEST)
        # Second launch: nothing pending, still exit 0, silent.
        proc = self.run_cli(
            ["apply-pending", "--app-dir", app_dir])
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")

    def test_restart_no_exit_1(self):
        app_dir, _ = self.app_and_state()
        proc = self.run_cli(["restart", "--app-dir", app_dir,
                             "--entry", "main.py", "--no"])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Not restarting now", proc.stdout)

    def test_restart_yes_really_execs(self):
        # The real exec path: the CLI process replaces itself
        # with the fake app's entry point, which prints its
        # version and exits 0.
        app_dir, state_dir = self.app_and_state()
        with FakeReleaseServer() as server:
            proc = self.run_cli([
                "pull", REPO, "--current", CURRENT,
                "--app-dir", app_dir,
                "--api-base", server.api_base])
        self.assertEqual(proc.returncode, 0)
        proc = self.run_cli(["restart", "--app-dir", app_dir,
                             "--entry", "main.py", "--yes"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("demo app version %s" % LATEST,
                      proc.stdout)

    def test_run_full_chain_says_no_to_pull(self):
        app_dir, _ = self.app_and_state()
        with FakeReleaseServer() as server:
            proc = self.run_cli([
                "run", REPO, "--current", CURRENT,
                "--app-dir", app_dir,
                "--api-base", server.api_base],
                input_text="no\n")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Update not pulled", proc.stdout)
        self.assertEqual(suc.read_version(app_dir), CURRENT)

    def test_run_full_chain_yes_yes_execs(self):
        app_dir, _ = self.app_and_state()
        with FakeReleaseServer() as server:
            proc = self.run_cli([
                "run", REPO, "--current", CURRENT,
                "--app-dir", app_dir,
                "--api-base", server.api_base],
                input_text="yes\nyes\n")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("demo app version %s" % LATEST,
                      proc.stdout)

    def test_run_full_chain_yes_no_stages_for_next_launch(self):
        app_dir, state_dir = self.app_and_state()
        with FakeReleaseServer() as server:
            proc = self.run_cli([
                "run", REPO, "--current", CURRENT,
                "--app-dir", app_dir,
                "--api-base", server.api_base],
                input_text="yes\nno\n")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("will apply on the next launch",
                      proc.stdout)
        self.assertEqual(suc.read_version(app_dir), CURRENT)
        self.assertTrue(suc.load_state(state_dir)["pending"])

    def test_rollback_cli(self):
        app_dir, _ = self.app_and_state()
        with FakeReleaseServer() as server:
            proc = self.run_cli([
                "pull", REPO, "--current", CURRENT,
                "--app-dir", app_dir,
                "--api-base", server.api_base])
        self.assertEqual(proc.returncode, 0)
        proc = self.run_cli(["install", "--app-dir", app_dir])
        self.assertEqual(proc.returncode, 0)
        proc = self.run_cli(["rollback", "--app-dir", app_dir])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Rolled back", proc.stdout)
        self.assertEqual(suc.read_version(app_dir), CURRENT)

    def test_debug_report_cli(self):
        out = os.path.join(self.tmp, "report.txt")
        proc = self.run_cli(["debug-report", "--out", out])
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(os.path.isfile(out))
        with open(out, "r", encoding="utf-8") as handle:
            self.assertIn("silent-update-check",
                          handle.read())

    def test_current_from_version_file(self):
        app_dir, _ = self.app_and_state(version=CURRENT)
        with FakeReleaseServer() as server:
            proc = self.run_cli([
                "check", REPO, "--app-dir", app_dir,
                "--api-base", server.api_base])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Update available", proc.stdout)

    def test_no_version_anywhere_is_plain_error(self):
        empty = os.path.join(self.tmp, "empty-app")
        os.makedirs(empty)
        with FakeReleaseServer() as server:
            proc = self.run_cli([
                "check", REPO, "--app-dir", empty,
                "--api-base", server.api_base])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("No version given", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_check_without_current_or_app_dir_is_plain_error(self):
        # Regression: check with neither --current nor
        # --app-dir used to crash with a TypeError traceback.
        with FakeReleaseServer() as server:
            proc = self.run_cli([
                "check", REPO, "--api-base", server.api_base])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("No version given", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)


class TestPackaging(unittest.TestCase):
    def test_debug_log_layer_unmodified(self):
        path = os.path.join(TOOL_DIR, "debug_log.py")
        with open(path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        self.assertEqual(digest, DEBUG_LOG_SHA)

    def test_no_em_dash_in_visible_text(self):
        for name in ("silent_update_check.py", "demo.py",
                     "README.md", "CHANGELOG.md", "build_zip.py",
                     "run_tests.sh"):
            path = os.path.join(TOOL_DIR, name)
            with open(path, "r", encoding="utf-8") as handle:
                self.assertNotIn(
                    EM_DASH, handle.read(),
                    "%s contains an em-dash" % name)

    def test_stdlib_only(self):
        """Every import in the module is stdlib or debug_log."""
        allowed = {
            "argparse", "datetime", "hashlib", "json", "os", "re",
            "shutil", "sys", "tempfile", "urllib", "zipfile",
            "debug_log",
        }
        path = os.path.join(TOOL_DIR, "silent_update_check.py")
        with open(path, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(alias.name.split(".")[0],
                                  allowed, alias.name)
            elif isinstance(node, ast.ImportFrom):
                self.assertIn((node.module or "").split(".")[0],
                              allowed, node.module)

    def test_release_zip_modes_and_contents(self):
        with tempfile.TemporaryDirectory(
                prefix="suc-zip.") as tmp:
            out = os.path.join(tmp, "silent-update-check.zip")
            proc = subprocess.run(
                [sys.executable,
                 os.path.join(TOOL_DIR, "build_zip.py"),
                 "--out", out],
                capture_output=True, text=True, cwd=TOOL_DIR,
                timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            with zipfile.ZipFile(out) as zf:
                names = zf.namelist()
                self.assertIn("silent_update_check.py", names)
                self.assertIn("demo.py", names)
                self.assertIn("README.md", names)
                self.assertIn("CHANGELOG.md", names)
                self.assertIn("debug_log.py", names)
                self.assertNotIn("BUILD_REPORT.md", names)
                self.assertFalse(
                    [n for n in names if n.endswith(".pyc")])
                self.assertFalse(
                    [n for n in names if n.endswith(".zip")])
                for info in zf.infolist():
                    mode = info.external_attr >> 16
                    if info.is_dir():
                        self.assertEqual(mode, 0o40755, info.filename)
                    elif info.filename in (
                            "silent_update_check.py", "demo.py",
                            "run_tests.sh", "build_zip.py"):
                        self.assertEqual(mode, 0o100755,
                                         info.filename)
                    else:
                        self.assertEqual(mode, 0o100644,
                                         info.filename)


class TestDemo(TempDirTest):
    def run_demo(self, argv):
        return subprocess.run(
            [sys.executable, os.path.join(TOOL_DIR, "demo.py")]
            + argv,
            capture_output=True, text=True, cwd=TOOL_DIR,
            timeout=120)

    def test_demo_yes(self):
        proc = self.run_demo([])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Chain complete.", proc.stdout)
        self.assertIn("app version after restart: %s" % LATEST,
                      proc.stdout)

    def test_demo_no(self):
        proc = self.run_demo(["--answer", "no"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Chain complete.", proc.stdout)
        self.assertIn("app version after next launch: %s" % LATEST,
                      proc.stdout)

    def test_demo_pieces(self):
        proc = self.run_demo(["--pieces"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("All four pieces work alone.", proc.stdout)
        self.assertIn("[1 check]", proc.stdout)
        self.assertIn("[2 pull-verify]", proc.stdout)
        self.assertIn("[3 install-swap]", proc.stdout)
        self.assertIn("[4 restart-prompt]", proc.stdout)


if __name__ == "__main__":
    unittest.main()
