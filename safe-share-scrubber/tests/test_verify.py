"""verify, scrub --json, and the CLI wrappers, run as real subprocesses.

verify is read-only: it writes nothing, exits 0 when every file is
clean, 1 when any secret is found, 2 when a file could not be read
or scanned, and an unscanned file outranks a found secret (exit 2
wins over exit 1).
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from helpers import (ALL_FAKES, make_text_file,  # noqa: E402
                     sample_innocent_text,
                     sample_log_with_secrets)
from scrubber.cli import VERIFY_CAVEAT  # noqa: E402

TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

VERIFY_KEYS = {"path", "findings", "secrets_found", "verdict",
               "skipped_reason", "error"}
SCRUB_KEYS = {"path", "safe_path", "findings", "secrets_found",
              "verdict", "skipped", "skipped_reason", "error",
              "report_path"}


class CliRunner:
    """Shared subprocess plumbing: XDG dirs redirected into the
    temp dir so no test touches the real home."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ)
        self.env["XDG_CONFIG_HOME"] = os.path.join(self.tmp.name,
                                                   "config")
        self.env["XDG_CACHE_HOME"] = os.path.join(self.tmp.name,
                                                  "cache")
        self.env["QT_QPA_PLATFORM"] = "offscreen"
        self.env["TMPDIR"] = "/tmp"
        self.log = make_text_file(
            os.path.join(self.tmp.name, "debug.log"),
            sample_log_with_secrets())
        self.clean = make_text_file(
            os.path.join(self.tmp.name, "clean.log"),
            sample_innocent_text())

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, args, cwd=None, timeout=120):
        return subprocess.run(
            [sys.executable, "-m", "scrubber"] + args,
            cwd=cwd or TREE, env=self.env, capture_output=True,
            text=True, timeout=timeout)

    def run_wrapper(self, name, args, cwd=None, timeout=120):
        # Through bash, not direct exec: the clone simulation runs
        # with every file 100644, and bash still proves the
        # wrapper resolves its folder and runs the command.
        return subprocess.run(
            ["bash", os.path.join(TREE, name)] + args,
            cwd=cwd or TREE, env=self.env, capture_output=True,
            text=True, timeout=timeout)


class VerifyTests(CliRunner, unittest.TestCase):
    def test_verify_help_exits_zero(self):
        proc = self.run_cli(["verify", "--help"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("scan", proc.stdout)
        # The exit-code contract is stated in the parent help
        # (argparse wraps it across lines, so flatten first).
        parent = self.run_cli(["--help"])
        flat = " ".join(parent.stdout.split())
        self.assertIn("exit 0 when clean", flat)

    def test_verify_clean_file_exits_zero(self):
        proc = self.run_cli(["verify", self.clean])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Secrets found: 0", proc.stdout)
        self.assertIn("Verdict: Safe to share", proc.stdout)

    def test_verify_dirty_file_exits_one_and_names_kinds_and_lines(
            self):
        proc = self.run_cli(["verify", self.log])
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("Secrets found: 15", proc.stdout)
        self.assertIn("AWS access key: line 2", proc.stdout)
        self.assertIn("Verdict: Not safe to share: secrets found",
                      proc.stdout)

    def test_verify_missing_file_exits_two(self):
        missing = os.path.join(self.tmp.name, "nope.log")
        proc = self.run_cli(["verify", missing])
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("No such file", proc.stdout)
        self.assertIn("Verdict: Not scanned", proc.stdout)

    def test_verify_dirty_plus_missing_exits_two(self):
        # An unscanned file outranks a found secret: exit 2 wins
        # over exit 1, because the verdict is incomplete.
        missing = os.path.join(self.tmp.name, "nope.log")
        proc = self.run_cli(["verify", self.log, missing])
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("Secrets found: 15", proc.stdout)
        self.assertIn("No such file", proc.stdout)

    def test_verify_binary_file_exits_two(self):
        blob = os.path.join(self.tmp.name, "blob.bin")
        with open(blob, "wb") as fh:
            fh.write(b"binary\x00data")
        proc = self.run_cli(["verify", blob])
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("Skipped: binary file", proc.stdout)
        self.assertIn("Verdict: Not scanned", proc.stdout)

    def test_verify_directory_exits_two(self):
        proc = self.run_cli(["verify", self.tmp.name])
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("Not a file", proc.stdout)

    def test_verify_writes_nothing(self):
        # Only the fixture files: the CLI's own debug log lands in
        # the redirected config/cache dirs, which are not the
        # fixtures' folder.
        def fixture_names():
            return {name for name in os.listdir(self.tmp.name)
                    if name not in ("config", "cache")}
        before = fixture_names()
        original = Path(self.log).read_bytes()
        mtime = os.path.getmtime(self.log)
        proc = self.run_cli(["verify", self.log, self.clean])
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertEqual(before, fixture_names())
        self.assertFalse(os.path.exists(
            os.path.join(self.tmp.name, "debug.safe.log")))
        self.assertFalse(os.path.exists(
            os.path.join(self.tmp.name, "debug.safe-report.txt")))
        self.assertFalse(os.path.exists(
            os.path.join(self.tmp.name, "clean.safe.log")))
        self.assertFalse(os.path.exists(
            os.path.join(self.tmp.name, "clean.safe-report.txt")))
        self.assertEqual(Path(self.log).read_bytes(), original)
        self.assertEqual(os.path.getmtime(self.log), mtime)

    def test_verify_human_output_has_the_caveat_and_no_secrets(self):
        proc = self.run_cli(["verify", self.log])
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn(VERIFY_CAVEAT, proc.stdout)
        # Verify writes no safe copy, so its caveat must not
        # mention one.
        self.assertNotIn("safe copy", proc.stdout)
        for fake in ALL_FAKES:
            self.assertNotIn(fake, proc.stdout)
            self.assertNotIn(fake, proc.stderr)

    def test_verify_json_schema(self):
        missing = os.path.join(self.tmp.name, "nope.log")
        proc = self.run_cli(["verify", "--json", self.log,
                             self.clean, missing])
        self.assertEqual(proc.returncode, 2, proc.stderr)
        results = json.loads(proc.stdout)
        self.assertEqual(len(results), 3)
        for result in results:
            self.assertEqual(set(result), VERIFY_KEYS)
        dirty, clean, gone = results
        self.assertEqual(dirty["path"], self.log)
        self.assertEqual(dirty["verdict"], "unsafe")
        self.assertEqual(dirty["secrets_found"], 15)
        self.assertEqual(len(dirty["findings"]), 15)
        for finding in dirty["findings"]:
            self.assertEqual(set(finding), {"kind", "line"})
        kinds = {f["kind"] for f in dirty["findings"]}
        self.assertIn("AWS access key", kinds)
        aws_lines = [f["line"] for f in dirty["findings"]
                     if f["kind"] == "AWS access key"]
        self.assertEqual(aws_lines, [2])
        self.assertIsNone(dirty["skipped_reason"])
        self.assertIsNone(dirty["error"])
        self.assertEqual(clean["verdict"], "safe")
        self.assertEqual(clean["secrets_found"], 0)
        self.assertEqual(clean["findings"], [])
        self.assertIsNone(clean["skipped_reason"])
        self.assertIsNone(clean["error"])
        self.assertEqual(gone["verdict"], "skipped")
        self.assertEqual(gone["secrets_found"], 0)
        self.assertEqual(gone["findings"], [])
        self.assertIsNone(gone["skipped_reason"])
        self.assertEqual(gone["error"], "No such file")
        for fake in ALL_FAKES:
            self.assertNotIn(fake, proc.stdout)

    def test_verify_json_binary_entry(self):
        blob = os.path.join(self.tmp.name, "blob.bin")
        with open(blob, "wb") as fh:
            fh.write(b"binary\x00data")
        proc = self.run_cli(["verify", "--json", blob])
        self.assertEqual(proc.returncode, 2, proc.stderr)
        results = json.loads(proc.stdout)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["verdict"], "skipped")
        self.assertIn("binary file", results[0]["skipped_reason"])
        self.assertIsNone(results[0]["error"])


class ScrubJsonTests(CliRunner, unittest.TestCase):
    def test_scrub_json_is_valid_and_complete(self):
        proc = self.run_cli(["scrub", "--json", self.log,
                             self.clean])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        results = json.loads(proc.stdout)
        self.assertEqual(len(results), 2)
        for result in results:
            self.assertEqual(set(result), SCRUB_KEYS)
        dirty, clean = results
        self.assertEqual(dirty["path"], self.log)
        self.assertEqual(dirty["secrets_found"], 15)
        self.assertEqual(dirty["verdict"], "Safe to share")
        self.assertIsNotNone(dirty["safe_path"])
        self.assertIsNotNone(dirty["report_path"])
        self.assertTrue(os.path.exists(dirty["safe_path"]))
        self.assertTrue(os.path.exists(dirty["report_path"]))
        self.assertFalse(dirty["skipped"])
        self.assertIsNone(dirty["error"])
        self.assertEqual(clean["secrets_found"], 0)
        self.assertEqual(clean["verdict"], "Safe to share")
        self.assertTrue(os.path.exists(clean["safe_path"]))
        self.assertTrue(os.path.exists(clean["report_path"]))
        for fake in ALL_FAKES:
            self.assertNotIn(fake, proc.stdout)

    def test_scrub_json_missing_file_keeps_list_complete(self):
        missing = os.path.join(self.tmp.name, "nope.log")
        proc = self.run_cli(["scrub", "--json", missing, self.log])
        self.assertEqual(proc.returncode, 1, proc.stderr)
        results = json.loads(proc.stdout)
        self.assertEqual(len(results), 2)
        gone, dirty = results
        self.assertEqual(gone["path"], missing)
        self.assertEqual(gone["error"], "No such file")
        self.assertIsNone(gone["safe_path"])
        self.assertIsNone(gone["report_path"])
        self.assertEqual(gone["verdict"], "Could not read file")
        self.assertEqual(gone["secrets_found"], 0)
        self.assertEqual(dirty["path"], self.log)
        self.assertEqual(dirty["secrets_found"], 15)
        self.assertTrue(os.path.exists(dirty["safe_path"]))
        self.assertTrue(os.path.exists(dirty["report_path"]))

    def test_scrub_json_binary_entry(self):
        blob = os.path.join(self.tmp.name, "blob.bin")
        with open(blob, "wb") as fh:
            fh.write(b"binary\x00data")
        proc = self.run_cli(["scrub", "--json", blob])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        results = json.loads(proc.stdout)
        self.assertEqual(len(results), 1)
        entry = results[0]
        self.assertTrue(entry["skipped"])
        self.assertIn("binary file", entry["skipped_reason"])
        self.assertIsNone(entry["safe_path"])
        self.assertIsNotNone(entry["report_path"])
        self.assertTrue(os.path.exists(entry["report_path"]))
        self.assertEqual(entry["verdict"],
                         "Skipped: binary file, not scrubbed")


class WrapperTests(CliRunner, unittest.TestCase):
    def test_wrappers_answer_help(self):
        for name, args in (("scrubber-cli", ["--help"]),
                           ("safe-share-scrub", ["--help"]),
                           ("safe-share-verify", ["--help"])):
            proc = self.run_wrapper(name, args)
            self.assertEqual(proc.returncode, 0,
                             "%s: %s" % (name, proc.stderr))
            self.assertTrue(proc.stdout.strip(), name)
        combined = self.run_wrapper("scrubber-cli", ["--help"])
        self.assertIn("scrub", combined.stdout)
        self.assertIn("verify", combined.stdout)
        self.assertIn("debug-report", combined.stdout)

    def test_safe_share_scrub_runs_real_scrub_from_another_cwd(self):
        workdir = os.path.join(self.tmp.name, "elsewhere")
        os.mkdir(workdir)
        proc = self.run_wrapper("safe-share-scrub", [self.log],
                                cwd=workdir)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        safe = os.path.join(self.tmp.name, "debug.safe.log")
        self.assertTrue(os.path.exists(safe))
        scrubbed = Path(safe).read_text(encoding="utf-8")
        for fake in ALL_FAKES:
            self.assertNotIn(fake, scrubbed)
        self.assertIn("Secrets found: 15", proc.stdout)

    def test_safe_share_verify_runs_real_verify_from_another_cwd(
            self):
        workdir = os.path.join(self.tmp.name, "elsewhere")
        os.mkdir(workdir)
        dirty = self.run_wrapper("safe-share-verify", [self.log],
                                 cwd=workdir)
        self.assertEqual(dirty.returncode, 1, dirty.stderr)
        self.assertIn("Secrets found: 15", dirty.stdout)
        self.assertFalse(os.path.exists(
            os.path.join(self.tmp.name, "debug.safe.log")))
        clean = self.run_wrapper("safe-share-verify", [self.clean],
                                 cwd=workdir)
        self.assertEqual(clean.returncode, 0, clean.stderr)
        self.assertIn("Safe to share", clean.stdout)

    def test_wrappers_accept_relative_paths_from_another_cwd(self):
        # A command on PATH is run from the user's own folder with
        # relative file names; those must resolve against the
        # caller's directory, not the app folder.
        workdir = os.path.join(self.tmp.name, "elsewhere")
        os.mkdir(workdir)
        make_text_file(os.path.join(workdir, "notes.log"),
                       sample_log_with_secrets())
        proc = self.run_wrapper("safe-share-verify", ["notes.log"],
                                cwd=workdir)
        self.assertEqual(proc.returncode, 1,
                         "%s%s" % (proc.stdout, proc.stderr))
        self.assertIn("Secrets found: 15", proc.stdout)
        proc = self.run_wrapper("scrubber-cli",
                                ["verify", "notes.log"],
                                cwd=workdir)
        self.assertEqual(proc.returncode, 1, proc.stderr)
        proc = self.run_wrapper("safe-share-scrub", ["notes.log"],
                                cwd=workdir)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(os.path.exists(
            os.path.join(workdir, "notes.safe.log")))
        self.assertTrue(os.path.exists(
            os.path.join(workdir, "notes.safe-report.txt")))

    def test_wrappers_work_through_symlinks_from_another_cwd(self):
        # The installed commands are symlinks in ~/.local/bin; the
        # wrapper must resolve the link and find the app folder.
        bindir = os.path.join(self.tmp.name, "bin")
        os.mkdir(bindir)
        workdir = os.path.join(self.tmp.name, "elsewhere")
        os.mkdir(workdir)
        for wrapper, link_name in (
                ("scrubber-cli", "safe-share-scrubber"),
                ("safe-share-scrub", "safe-share-scrub"),
                ("safe-share-verify", "safe-share-verify")):
            link = os.path.join(bindir, link_name)
            os.symlink(os.path.join(TREE, wrapper), link)
            proc = subprocess.run(
                ["bash", link, "--help"], cwd=workdir,
                env=self.env, capture_output=True, text=True,
                timeout=120)
            self.assertEqual(proc.returncode, 0,
                             "%s: %s" % (link_name, proc.stderr))
            self.assertNotIn("ModuleNotFoundError", proc.stderr)
            self.assertTrue(proc.stdout.strip(), link_name)
        # And a real scrub through the symlinked scrub wrapper.
        proc = subprocess.run(
            ["bash", os.path.join(bindir, "safe-share-scrub"),
             self.log],
            cwd=workdir, env=self.env, capture_output=True,
            text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(os.path.exists(
            os.path.join(self.tmp.name, "debug.safe.log")))


if __name__ == "__main__":
    unittest.main()
