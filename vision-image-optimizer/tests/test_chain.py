"""End-to-end chain tests: shrink then describe through the
standalone wrappers, run as subprocesses. Each piece works alone;
together they compose. The fake Ollama server answers describes;
no test touches the live API."""

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from helpers import GOOD_DESCRIPTION, FakeOllama, make_image  # noqa: E402

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
        # The wrappers fall back to `python3` when no .venv is
        # installed; point that at this test run's interpreter so
        # the wrappers use the Pillow that is actually here.
        bin_dir = os.path.join(self.tmp.name, "bin")
        os.makedirs(bin_dir)
        os.symlink(sys.executable, os.path.join(bin_dir, "python3"))
        self.env["PATH"] = bin_dir + os.pathsep + os.environ.get(
            "PATH", "")
        self.img = make_image(os.path.join(self.tmp.name, "shot.png"),
                              1920, 1080)
        self.servers = []

    def tearDown(self):
        for server in self.servers:
            server.stop()
        self.tmp.cleanup()

    def _run_wrapper(self, wrapper, args, timeout=120):
        # Run the wrappers through bash: a clone stores every file
        # 100644, so executing them directly would fail there even
        # though the Release zip carries the exec bits.
        return subprocess.run(
            ["bash", os.path.join(TREE, wrapper)] + args,
            cwd=TREE, env=self.env, capture_output=True, text=True,
            timeout=timeout)

    def test_wrappers_help_exit_0(self):
        shrink_help = self._run_wrapper("vision-shrink", ["--help"])
        self.assertEqual(shrink_help.returncode, 0,
                         shrink_help.stderr)
        self.assertIn("vision-shrink", shrink_help.stdout)
        describe_help = self._run_wrapper("vision-describe",
                                          ["--help"])
        self.assertEqual(describe_help.returncode, 0,
                         describe_help.stderr)
        self.assertIn("vision-describe", describe_help.stdout)

    def test_shrink_then_describe_via_wrappers(self):
        server = FakeOllama().start()
        self.servers.append(server)
        # Step one: shrink standalone.
        shrunk = self._run_wrapper(
            "vision-shrink", [self.img, "--width", "512"])
        self.assertEqual(shrunk.returncode, 0, shrunk.stderr)
        self.assertIn("Vision tokens: 2040 to 144", shrunk.stdout)
        out = os.path.join(self.tmp.name, "optimized",
                           "shot-512w.jpg")
        self.assertTrue(os.path.exists(out), shrunk.stdout)
        from PIL import Image
        with Image.open(out) as img:
            self.assertEqual(img.size, (512, 288))
        # Step two: describe the shrunk file standalone.
        described = self._run_wrapper(
            "vision-describe", [out, "--ollama-url",
                                server.base_url])
        self.assertEqual(described.returncode, 0, described.stderr)
        self.assertIn(GOOD_DESCRIPTION, described.stdout)
        self.assertIn("Model: minicpm-v", described.stdout)
        self.assertIn("Tokens: 144 to 144", described.stdout)

    def test_describe_standalone_on_original(self):
        # Each piece works alone: describe needs no shrink first.
        server = FakeOllama().start()
        self.servers.append(server)
        proc = self._run_wrapper(
            "vision-describe", [self.img, "--ollama-url",
                                server.base_url])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(GOOD_DESCRIPTION, proc.stdout)
        self.assertIn("Model: minicpm-v", proc.stdout)
        self.assertIn("Tokens: 2040 to 2040", proc.stdout)


if __name__ == "__main__":
    unittest.main()
