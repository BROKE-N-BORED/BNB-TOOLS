"""Combined CLI end to end, run as real subprocesses. The CLI
delegates: optimize to the shrink module, describe to the describe
module."""

import json
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
        self.assertIn("cache-stats", proc.stdout)
        self.assertIn("debug-report", proc.stdout)

    def test_version(self):
        proc = self.run_cli(["--version"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("vision-image-optimizer 0.2.0", proc.stdout)

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

    def test_optimize_json_delegates_to_shrink(self):
        proc = self.run_cli(["optimize", self.img, "--width", "512",
                             "--json"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["tokens_before"], 2040)
        self.assertEqual(data["tokens_after"], 144)
        self.assertEqual(data["width"], 512)
        self.assertFalse(data["from_cache"])

    def test_optimize_missing_file(self):
        proc = self.run_cli(["optimize", "/no/such/file.png"])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("No such file", proc.stderr)

    def test_describe_against_fake_server(self):
        server = FakeOllama().start()
        self.servers.append(server)
        proc = self.run_cli(["describe", self.img,
                             "--ollama-url", server.base_url])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(GOOD_DESCRIPTION, proc.stdout)
        self.assertIn("minicpm-v", proc.stdout)
        # Describe works on the file as given: no shrink inside.
        self.assertIn("Tokens: 2040 to 2040", proc.stdout)

    def test_describe_second_run_is_cached(self):
        server = FakeOllama().start()
        self.servers.append(server)
        args = ["describe", self.img, "--ollama-url",
                server.base_url]
        self.run_cli(args)
        calls_after_first = len(server.calls)
        proc = self.run_cli(args)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("from cache", proc.stdout)
        self.assertEqual(len(server.calls), calls_after_first)

    def test_describe_json_delegates_to_describe(self):
        server = FakeOllama().start()
        self.servers.append(server)
        proc = self.run_cli(["describe", self.img,
                             "--ollama-url", server.base_url,
                             "--json"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["text"], GOOD_DESCRIPTION)
        self.assertEqual(data["model_used"], "minicpm-v")
        self.assertEqual(data["tokens_before"], 2040)
        self.assertEqual(data["tokens_after"], 2040)

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

    def test_cache_stats_empty_then_filled(self):
        proc = self.run_cli(["cache-stats"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Cache: 0 optimized picture(s), "
                      "0 description(s), 0 B", proc.stdout)
        self.run_cli(["optimize", self.img, "--width", "512"])
        proc = self.run_cli(["cache-stats"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Cache: 1 optimized picture(s), "
                      "0 description(s), ", proc.stdout)

    def test_cache_stats_json(self):
        self.run_cli(["optimize", self.img, "--width", "512"])
        proc = self.run_cli(["cache-stats", "--json"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(set(data), {"optimized", "descriptions",
                                     "bytes"})
        self.assertEqual(data["optimized"], 1)
        self.assertEqual(data["descriptions"], 0)
        self.assertGreater(data["bytes"], 0)

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
