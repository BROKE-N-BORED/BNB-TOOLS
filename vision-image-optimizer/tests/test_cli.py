"""CLI end to end, run as real subprocesses."""

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from helpers import GOOD_DESCRIPTION, FakeOllama, make_image  # noqa: E402

TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ)
        self.env["XDG_CONFIG_HOME"] = os.path.join(self.tmp.name,
                                                   "config")
        self.env["XDG_CACHE_HOME"] = os.path.join(self.tmp.name,
                                                  "cache")
        self.env["QT_QPA_PLATFORM"] = "offscreen"
        self.env["TMPDIR"] = "/tmp"
        self.img = make_image(os.path.join(self.tmp.name, "shot.png"),
                              1920, 1080)
        self.servers = []

    def tearDown(self):
        for server in self.servers:
            server.stop()
        self.tmp.cleanup()

    def run_cli(self, args, timeout=120):
        return subprocess.run(
            [sys.executable, "-m", "optimizer"] + args,
            cwd=TREE, env=self.env, capture_output=True, text=True,
            timeout=timeout)

    def test_help_exit_0_and_usage(self):
        proc = self.run_cli(["--help"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("optimize", proc.stdout)
        self.assertIn("describe", proc.stdout)
        self.assertIn("cache-clear", proc.stdout)
        self.assertIn("debug-report", proc.stdout)

    def test_optimize_end_to_end(self):
        proc = self.run_cli(["optimize", self.img, "--width", "512"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("2040 to 144", proc.stdout)
        out = os.path.join(self.tmp.name, "optimized",
                           "shot-512w.jpg")
        self.assertTrue(os.path.exists(out), proc.stdout)
        # The source is untouched.
        from PIL import Image
        with Image.open(self.img) as img:
            self.assertEqual(img.size, (1920, 1080))

    def test_optimize_second_run_is_cached(self):
        self.run_cli(["optimize", self.img, "--width", "512"])
        proc = self.run_cli(["optimize", self.img, "--width", "512"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("from cache", proc.stdout)

    def test_optimize_missing_file(self):
        proc = self.run_cli(["optimize", "/no/such/file.png"])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("No such file", proc.stderr)

    def test_describe_against_fake_server(self):
        server = FakeOllama().start()
        self.servers.append(server)
        proc = self.run_cli(["describe", self.img,
                             "--ollama-url", server.base_url,
                             "--width", "512"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(GOOD_DESCRIPTION, proc.stdout)
        self.assertIn("minicpm-v", proc.stdout)
        self.assertIn("Tokens: 2040 to 144", proc.stdout)

    def test_describe_second_run_is_cached(self):
        server = FakeOllama().start()
        self.servers.append(server)
        args = ["describe", self.img, "--ollama-url",
                server.base_url, "--width", "512"]
        self.run_cli(args)
        calls_after_first = len(server.calls)
        proc = self.run_cli(args)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("from cache", proc.stdout)
        self.assertEqual(len(server.calls), calls_after_first)

    def test_describe_ollama_down_is_plain_error(self):
        server = FakeOllama().start()
        url = server.base_url
        server.stop()
        proc = self.run_cli(["describe", self.img,
                             "--ollama-url", url])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("not running", proc.stderr)
        # Optimizing still works with Ollama down.
        proc = self.run_cli(["optimize", self.img, "--width", "512"])
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_cache_clear(self):
        self.run_cli(["optimize", self.img, "--width", "512"])
        proc = self.run_cli(["cache-clear"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Cache cleared", proc.stdout)
        proc = self.run_cli(["cache-clear"])
        self.assertIn("0 files removed", proc.stdout)

    def test_debug_report_writes_file(self):
        out = os.path.join(self.tmp.name, "report.txt")
        proc = self.run_cli(["debug-report", "--out", out])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(os.path.exists(out))
        with open(out, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("vision-image-optimizer", text)
        self.assertIn("== Context ==", text)
        self.assertIn("== Services ==", text)
        self.assertIn("ollama", text)

    def test_optimizer_cli_script_via_symlink(self):
        # S6: the CLI wrapper must resolve its own symlink.
        link_dir = os.path.join(self.tmp.name, "bin")
        os.makedirs(link_dir)
        link = os.path.join(link_dir, "vision-image-optimizer")
        os.symlink(os.path.join(TREE, "optimizer-cli"), link)
        proc = subprocess.run(
            ["bash", link, "--help"], cwd=self.tmp.name, env=self.env,
            capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("optimize", proc.stdout)


if __name__ == "__main__":
    unittest.main()
