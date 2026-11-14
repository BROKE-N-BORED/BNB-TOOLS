"""The chain end to end: scrub and verify each work standalone
against fixtures, and the chain closes — scrub a dirty file, verify
the safe copy, and it comes back safe."""

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

TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ChainTests(unittest.TestCase):
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

    def run_cli(self, args, timeout=120):
        return subprocess.run(
            [sys.executable, "-m", "scrubber"] + args,
            cwd=TREE, env=self.env, capture_output=True, text=True,
            timeout=timeout)

    def safe_copy_of(self, path):
        # Same naming as core.safe_copy_path: debug.log ->
        # debug.safe.log.
        name = os.path.basename(path)
        stem, dot, suffix = name.rpartition(".")
        if dot:
            return os.path.join(self.tmp.name,
                                stem + ".safe." + suffix)
        return os.path.join(self.tmp.name, name + ".safe")

    def test_scrub_then_verify_safe_copy_is_safe(self):
        scrubbed = self.run_cli(["scrub", self.log])
        self.assertEqual(scrubbed.returncode, 0, scrubbed.stderr)
        safe = self.safe_copy_of(self.log)
        self.assertTrue(os.path.exists(safe))
        for fake in ALL_FAKES:
            self.assertNotIn(
                fake, Path(safe).read_text(encoding="utf-8"))
        verified = self.run_cli(["verify", safe])
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertIn("Secrets found: 0", verified.stdout)
        self.assertIn("Verdict: Safe to share", verified.stdout)
        # The original is still dirty: scrub never changes it.
        still_dirty = self.run_cli(["verify", self.log])
        self.assertEqual(still_dirty.returncode, 1)
        self.assertIn("Secrets found: 15", still_dirty.stdout)

    def test_verify_then_scrub_then_verify(self):
        first = self.run_cli(["verify", self.log])
        self.assertEqual(first.returncode, 1, first.stderr)
        scrubbed = self.run_cli(["scrub", self.log])
        self.assertEqual(scrubbed.returncode, 0, scrubbed.stderr)
        safe = self.safe_copy_of(self.log)
        verified = self.run_cli(["verify", "--json", safe])
        self.assertEqual(verified.returncode, 0, verified.stderr)
        results = json.loads(verified.stdout)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["verdict"], "safe")
        self.assertEqual(results[0]["secrets_found"], 0)

    def test_chain_clean_file(self):
        scrubbed = self.run_cli(["scrub", self.clean])
        self.assertEqual(scrubbed.returncode, 0, scrubbed.stderr)
        safe = self.safe_copy_of(self.clean)
        self.assertEqual(Path(safe).read_text(encoding="utf-8"),
                         sample_innocent_text())
        verified = self.run_cli(["verify", safe])
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertIn("Secrets found: 0", verified.stdout)

    def test_chain_multiple_files(self):
        scrubbed = self.run_cli(["scrub", self.log, self.clean])
        self.assertEqual(scrubbed.returncode, 0, scrubbed.stderr)
        safe_log = self.safe_copy_of(self.log)
        safe_clean = self.safe_copy_of(self.clean)
        verified = self.run_cli(["verify", safe_log, safe_clean])
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertEqual(verified.stdout.count("Safe to share"), 2)

    def test_chain_through_the_wrappers(self):
        # The one-job commands close the chain on their own, from
        # another working directory.
        workdir = os.path.join(self.tmp.name, "elsewhere")
        os.mkdir(workdir)
        scrubbed = subprocess.run(
            ["bash", os.path.join(TREE, "safe-share-scrub"),
             self.log],
            cwd=workdir, env=self.env, capture_output=True,
            text=True, timeout=120)
        self.assertEqual(scrubbed.returncode, 0, scrubbed.stderr)
        safe = self.safe_copy_of(self.log)
        verified = subprocess.run(
            ["bash", os.path.join(TREE, "safe-share-verify"),
             safe],
            cwd=workdir, env=self.env, capture_output=True,
            text=True, timeout=120)
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertIn("Safe to share", verified.stdout)


if __name__ == "__main__":
    unittest.main()
