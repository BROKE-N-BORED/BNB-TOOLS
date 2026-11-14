"""Core redaction engine tests.

Every fake secret is constructed from FAKE markers and matches a
pattern by shape only. Nothing here resembles a real secret.
"""

import os
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from helpers import (ALL_FAKES, FAKE_API_KEY, FAKE_AWS,  # noqa: E402
                     FAKE_BARE_MIXED, FAKE_BEARER, FAKE_GITHUB,
                     FAKE_GITHUB_PAT, FAKE_GOOGLE, FAKE_HEX_KEY,
                     FAKE_JWT, FAKE_PASSWORD, FAKE_PEM,
                     FAKE_PEM_BODY, FAKE_QUERY_KEY, FAKE_SK,
                     FAKE_SLACK, FAKE_URL_PASS, INNOCENT_BASE64,
                     INNOCENT_GIT_HASH, INNOCENT_PROSE,
                     INNOCENT_URL, INNOCENT_UUID,
                     make_text_file, sample_innocent_text,
                     sample_log_with_secrets)
from scrubber import core, report  # noqa: E402


class ScrubTextTests(unittest.TestCase):
    def assert_caught(self, text, secret, kind, marker, line=1):
        scrubbed, findings = core.scrub_text(text)
        self.assertNotIn(secret, scrubbed)
        self.assertIn(marker, scrubbed)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["kind"], kind)
        self.assertEqual(findings[0]["line"], line)
        self.assertEqual(findings[0]["marker"], marker)
        return scrubbed

    def test_aws_key(self):
        self.assert_caught("key " + FAKE_AWS, FAKE_AWS,
                           core.KIND_AWS, core.MARKER_AWS)

    def test_jwt(self):
        self.assert_caught("jwt: " + FAKE_JWT, FAKE_JWT,
                           core.KIND_JWT, core.MARKER_JWT)

    def test_private_key_pem_block(self):
        scrubbed, findings = core.scrub_text(
            "before\n" + FAKE_PEM + "\nafter")
        self.assertNotIn(FAKE_PEM_BODY, scrubbed)
        self.assertNotIn("BEGIN RSA PRIVATE KEY", scrubbed)
        self.assertNotIn("END RSA PRIVATE KEY", scrubbed)
        self.assertIn(core.MARKER_PRIVATE_KEY, scrubbed)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["kind"], core.KIND_PRIVATE_KEY)
        self.assertEqual(findings[0]["line"], 2)
        self.assertIn("before", scrubbed)
        self.assertIn("after", scrubbed)

    def test_private_key_openssh_header(self):
        pem = ("-----BEGIN OPENSSH PRIVATE KEY-----\n"
               + FAKE_PEM_BODY
               + "\n-----END OPENSSH PRIVATE KEY-----")
        scrubbed, findings = core.scrub_text(pem)
        self.assertNotIn(FAKE_PEM_BODY, scrubbed)
        self.assertIn(core.MARKER_PRIVATE_KEY, scrubbed)
        self.assertEqual(len(findings), 1)

    def test_github_token(self):
        self.assert_caught("token " + FAKE_GITHUB, FAKE_GITHUB,
                           core.KIND_GITHUB, core.MARKER_GITHUB)

    def test_github_fine_grained_token(self):
        self.assert_caught("token " + FAKE_GITHUB_PAT,
                           FAKE_GITHUB_PAT, core.KIND_GITHUB,
                           core.MARKER_GITHUB)

    def test_slack_token(self):
        self.assert_caught("slack " + FAKE_SLACK, FAKE_SLACK,
                           core.KIND_SLACK, core.MARKER_SLACK)

    def test_google_api_key(self):
        self.assert_caught("key " + FAKE_GOOGLE, FAKE_GOOGLE,
                           core.KIND_GOOGLE, core.MARKER_GOOGLE)

    def test_bearer_token_keeps_header(self):
        scrubbed = self.assert_caught(
            "Authorization: Bearer " + FAKE_BEARER, FAKE_BEARER,
            core.KIND_BEARER, core.MARKER_BEARER)
        self.assertIn("Authorization: Bearer ", scrubbed)

    def test_assignment_password_keeps_key_name(self):
        scrubbed = self.assert_caught(
            "password=" + FAKE_PASSWORD, FAKE_PASSWORD,
            core.KIND_ASSIGNMENT, core.MARKER_ASSIGNMENT)
        self.assertIn("password=", scrubbed)

    def test_assignment_api_key_colon(self):
        scrubbed = self.assert_caught(
            "api-key: " + FAKE_API_KEY, FAKE_API_KEY,
            core.KIND_ASSIGNMENT, core.MARKER_ASSIGNMENT)
        self.assertIn("api-key: ", scrubbed)

    def test_assignment_quoted_json_value(self):
        scrubbed = self.assert_caught(
            '"secret": "' + FAKE_PASSWORD + '"', FAKE_PASSWORD,
            core.KIND_ASSIGNMENT, core.MARKER_ASSIGNMENT)
        self.assertIn('"secret": "', scrubbed)

    def test_url_basic_auth_keeps_user_and_host(self):
        text = ("https://fakeuser:" + FAKE_URL_PASS
                + "@example.com/path")
        scrubbed = self.assert_caught(
            text, FAKE_URL_PASS, core.KIND_URL_PASSWORD,
            core.MARKER_URL_PASSWORD)
        self.assertIn("https://fakeuser:", scrubbed)
        self.assertIn("@example.com/path", scrubbed)

    def test_url_query_param_keeps_param_name(self):
        text = ("https://example.com/api?api_key=" + FAKE_QUERY_KEY
                + "&x=1")
        scrubbed = self.assert_caught(
            text, FAKE_QUERY_KEY, core.KIND_URL_QUERY,
            core.MARKER_URL_QUERY)
        self.assertIn("api_key=", scrubbed)
        self.assertIn("x=1", scrubbed)

    def test_url_query_token_param(self):
        text = "https://example.com/?token=" + FAKE_QUERY_KEY
        self.assert_caught(text, FAKE_QUERY_KEY,
                           core.KIND_URL_QUERY, core.MARKER_URL_QUERY)

    def test_bare_sk_token(self):
        self.assert_caught("key " + FAKE_SK, FAKE_SK,
                           core.KIND_BARE_TOKEN,
                           core.MARKER_BARE_TOKEN)

    def test_bare_mixed_token(self):
        self.assert_caught("key " + FAKE_BARE_MIXED, FAKE_BARE_MIXED,
                           core.KIND_BARE_TOKEN,
                           core.MARKER_BARE_TOKEN)

    def test_bare_hex_next_to_key_word(self):
        self.assert_caught("token " + FAKE_HEX_KEY, FAKE_HEX_KEY,
                           core.KIND_BARE_TOKEN,
                           core.MARKER_BARE_TOKEN)

    def test_secret_in_traceback(self):
        text = ("\n".join([
            "Traceback (most recent call last):",
            '  File "app.py", line 9, in main',
            '    raise ValueError("token ' + FAKE_GITHUB + '")',
        ]))
        scrubbed, findings = core.scrub_text(text)
        self.assertNotIn(FAKE_GITHUB, scrubbed)
        self.assertIn(core.MARKER_GITHUB, scrubbed)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["kind"], core.KIND_GITHUB)
        self.assertEqual(findings[0]["line"], 3)

    def test_line_numbers_after_pem_block(self):
        # A PEM block collapses to one line; findings after it still
        # point at the ORIGINAL line numbers.
        text = FAKE_PEM + "\nafter\nkey " + FAKE_AWS
        _, findings = core.scrub_text(text)
        self.assertEqual([f["line"] for f in findings], [1, 6])
        self.assertEqual(findings[1]["kind"], core.KIND_AWS)

    def test_two_secrets_on_one_line(self):
        text = FAKE_AWS + " and " + FAKE_GITHUB
        scrubbed, findings = core.scrub_text(text)
        self.assertNotIn(FAKE_AWS, scrubbed)
        self.assertNotIn(FAKE_GITHUB, scrubbed)
        self.assertEqual(len(findings), 2)
        self.assertEqual({f["line"] for f in findings}, {1})

    def test_full_sample_log(self):
        scrubbed, findings = core.scrub_text(
            sample_log_with_secrets())
        for fake in ALL_FAKES:
            self.assertNotIn(fake, scrubbed)
        kinds = [f["kind"] for f in findings]
        for kind in (core.KIND_AWS, core.KIND_JWT, core.KIND_GITHUB,
                     core.KIND_SLACK, core.KIND_GOOGLE,
                     core.KIND_BEARER, core.KIND_ASSIGNMENT,
                     core.KIND_URL_PASSWORD, core.KIND_URL_QUERY,
                     core.KIND_BARE_TOKEN, core.KIND_PRIVATE_KEY):
            self.assertIn(kind, kinds)
        self.assertEqual(len(findings), 15)
        # Findings come back in line order.
        lines = [f["line"] for f in findings]
        self.assertEqual(lines, sorted(lines))
        # A re-scan of the scrubbed text finds nothing left.
        self.assertEqual(core.scrub_text(scrubbed)[1], [])


class FalsePositiveTests(unittest.TestCase):
    def assert_untouched(self, text):
        scrubbed, findings = core.scrub_text(text)
        self.assertEqual(scrubbed, text)
        self.assertEqual(findings, [])

    def test_git_commit_hash_in_sentence(self):
        self.assert_untouched(
            "Fixed in commit " + INNOCENT_GIT_HASH
            + ", see the log.")

    def test_uuid(self):
        self.assert_untouched(
            "Session " + INNOCENT_UUID + " started.")

    def test_normal_url(self):
        self.assert_untouched(
            "See " + INNOCENT_URL + " for details.")

    def test_url_with_port_but_no_auth(self):
        self.assert_untouched(
            "Listening on http://127.0.0.1:8080/status now.")

    def test_password_in_prose_with_no_value(self):
        self.assert_untouched(INNOCENT_PROSE)

    def test_base64_blob_that_is_not_a_jwt(self):
        self.assert_untouched("Blob: " + INNOCENT_BASE64)

    def test_whole_innocent_sample(self):
        self.assert_untouched(sample_innocent_text())


class ScrubFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _path(self, name):
        return os.path.join(self.tmp.name, name)

    def test_safe_copy_name(self):
        self.assertEqual(
            str(core.safe_copy_path("/tmp/debug.log")),
            "/tmp/debug.safe.log")
        self.assertEqual(
            str(core.safe_copy_path("/tmp/notes")),
            "/tmp/notes.safe")

    def test_scrub_file_writes_safe_copy(self):
        path = make_text_file(self._path("debug.log"),
                              sample_log_with_secrets())
        original = Path(path).read_bytes()
        result = core.scrub_file(path)
        self.assertEqual(result["verdict"], core.VERDICT_SAFE)
        self.assertEqual(result["secrets_found"], 15)
        safe = result["safe_path"]
        self.assertEqual(safe, self._path("debug.safe.log"))
        self.assertTrue(os.path.exists(safe))
        scrubbed = Path(safe).read_text(encoding="utf-8")
        for fake in ALL_FAKES:
            self.assertNotIn(fake, scrubbed)
        # The original is untouched, byte for byte.
        self.assertEqual(Path(path).read_bytes(), original)

    def test_no_extension_safe_copy(self):
        path = make_text_file(self._path("notes"),
                              "key " + FAKE_AWS + "\n")
        result = core.scrub_file(path)
        self.assertEqual(result["safe_path"],
                         self._path("notes.safe"))
        self.assertTrue(os.path.exists(self._path("notes.safe")))

    def test_empty_file(self):
        path = make_text_file(self._path("empty.log"), "")
        result = core.scrub_file(path)
        self.assertEqual(result["verdict"], core.VERDICT_SAFE)
        self.assertEqual(result["findings"], [])
        safe = result["safe_path"]
        self.assertTrue(os.path.exists(safe))
        self.assertEqual(Path(safe).read_bytes(), b"")

    def test_file_with_no_secrets(self):
        content = sample_innocent_text()
        path = make_text_file(self._path("clean.log"), content)
        result = core.scrub_file(path)
        self.assertEqual(result["verdict"], core.VERDICT_SAFE)
        self.assertEqual(result["findings"], [])
        safe = result["safe_path"]
        self.assertEqual(Path(safe).read_text(encoding="utf-8"),
                         content)

    def test_binary_file_with_nuls_skipped(self):
        path = self._path("blob.bin")
        with open(path, "wb") as fh:
            fh.write(b"PK\x03\x04\x00\x01\x02binary\x00stuff")
        result = core.scrub_file(path)
        self.assertTrue(result["skipped"])
        self.assertIsNone(result["safe_path"])
        self.assertEqual(result["verdict"], core.VERDICT_BINARY)
        self.assertIn("binary", result["skipped_reason"])
        self.assertFalse(os.path.exists(self._path("blob.safe.bin")))

    def test_non_utf8_file_skipped(self):
        path = self._path("latin.log")
        with open(path, "wb") as fh:
            fh.write(b"caf\xe9 latin-1 bytes, no NUL here")
        result = core.scrub_file(path)
        self.assertTrue(result["skipped"])
        self.assertIsNone(result["safe_path"])
        self.assertEqual(result["verdict"], core.VERDICT_BINARY)

    def test_missing_file(self):
        result = core.scrub_file(self._path("nope.log"))
        self.assertIsNone(result["safe_path"])
        self.assertIsNotNone(result["error"])
        self.assertEqual(result["verdict"], core.VERDICT_UNREADABLE)


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _path(self, name):
        return os.path.join(self.tmp.name, name)

    def test_report_has_kinds_lines_and_verdict(self):
        path = make_text_file(self._path("debug.log"),
                              sample_log_with_secrets())
        result = core.scrub_file(path)
        text = report.build_file_report(result)
        self.assertIn("AWS access key: line 2", text)
        self.assertIn("GitHub token: lines 4, 21", text)
        self.assertIn("Private key: line 15", text)
        self.assertIn("Secrets found: 15", text)
        self.assertIn("Verdict: Safe to share", text)
        self.assertIn("debug.safe.log", text)

    def test_report_contains_no_secret_values(self):
        path = make_text_file(self._path("debug.log"),
                              sample_log_with_secrets())
        result = core.scrub_file(path)
        text = report.build_file_report(result)
        for fake in ALL_FAKES:
            self.assertNotIn(fake, text)

    def test_report_carries_the_caveat(self):
        path = make_text_file(self._path("clean.log"),
                              sample_innocent_text())
        result = core.scrub_file(path)
        text = report.build_file_report(result)
        self.assertIn(report.CAVEAT_TEXT, text)
        self.assertIn("cannot prove", text)

    def test_report_for_skipped_file(self):
        path = self._path("blob.bin")
        with open(path, "wb") as fh:
            fh.write(b"binary\x00data")
        result = core.scrub_file(path)
        text = report.build_file_report(result)
        self.assertIn("Skipped: binary file", text)
        self.assertIn("No safe copy was written.", text)
        self.assertIn("Verdict: Skipped", text)

    def test_report_for_clean_file(self):
        path = make_text_file(self._path("clean.log"),
                              sample_innocent_text())
        result = core.scrub_file(path)
        text = report.build_file_report(result)
        self.assertIn("Secrets found: 0", text)
        self.assertIn("None. The safe copy matches the original.",
                      text)
        self.assertIn("Verdict: Safe to share", text)

    def test_report_file_name_and_write(self):
        self.assertEqual(
            str(report.report_file_path("/tmp/debug.log")),
            "/tmp/debug.safe-report.txt")
        path = make_text_file(self._path("debug.log"),
                              "key " + FAKE_AWS + "\n")
        result = core.scrub_file(path)
        written = report.write_report_file(result)
        self.assertEqual(written,
                         self._path("debug.safe-report.txt"))
        self.assertTrue(os.path.exists(written))
        content = Path(written).read_text(encoding="utf-8")
        self.assertNotIn(FAKE_AWS, content)
        self.assertIn("Verdict: Safe to share", content)


if __name__ == "__main__":
    unittest.main()
