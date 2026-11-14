"""Describe CLI against the fake Ollama server: fast-first,
escalation, down handling, cache, --json, and describe-as-given."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from helpers import (BLIND_DESCRIPTION, GOOD_DESCRIPTION,  # noqa: E402
                     SHORT_DESCRIPTION, FakeOllama, make_image)

TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DESCRIBE_JSON_KEYS = {"text", "model_used", "fast_seconds",
                      "smart_seconds", "escalated", "fast_tried",
                      "from_cache", "tokens_before", "tokens_after",
                      "bytes_before", "bytes_after"}


class DescribeCliTests(unittest.TestCase):
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
        self.small = make_image(
            os.path.join(self.tmp.name, "small.png"), 512, 288)
        self.servers = []

    def tearDown(self):
        for server in self.servers:
            server.stop()
        self.tmp.cleanup()

    def run_describe(self, args, timeout=120):
        return subprocess.run(
            [sys.executable, "-m", "optimizer.describe"] + args,
            cwd=TREE, env=self.env, capture_output=True, text=True,
            timeout=timeout)

    def start_server(self, **kwargs):
        server = FakeOllama(**kwargs).start()
        self.servers.append(server)
        return server

    def test_help_exit_0(self):
        proc = self.run_describe(["--help"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("usage: vision-describe", proc.stdout)
        self.assertIn("--ollama-url", proc.stdout)

    def test_good_fast_answer_uses_fast_model(self):
        server = self.start_server()
        proc = self.run_describe([self.img, "--ollama-url",
                                  server.base_url])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(GOOD_DESCRIPTION, proc.stdout)
        self.assertIn("Model: minicpm-v", proc.stdout)
        self.assertIn("Tokens: 2040 to 2040", proc.stdout)
        self.assertEqual(len(server.calls), 1)
        self.assertEqual(server.calls[0][0], "minicpm-v")

    def test_empty_fast_answer_escalates(self):
        server = self.start_server(
            responses={"minicpm-v": ""})
        proc = self.run_describe([self.img, "--ollama-url",
                                  server.base_url])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Model: qwen3-vl:2b-instruct", proc.stdout)
        self.assertEqual([c[0] for c in server.calls],
                         ["minicpm-v", "qwen3-vl:2b-instruct"])

    def test_short_fast_answer_escalates(self):
        server = self.start_server(
            responses={"minicpm-v": SHORT_DESCRIPTION})
        proc = self.run_describe([self.img, "--ollama-url",
                                  server.base_url])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Model: qwen3-vl:2b-instruct", proc.stdout)
        self.assertEqual(len(server.calls), 2)

    def test_blind_fast_answer_escalates(self):
        server = self.start_server(
            responses={"minicpm-v": BLIND_DESCRIPTION})
        proc = self.run_describe([self.img, "--ollama-url",
                                  server.base_url])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Model: qwen3-vl:2b-instruct", proc.stdout)
        self.assertEqual(len(server.calls), 2)

    def test_ollama_down_is_plain_error_exit_1(self):
        server = FakeOllama().start()
        url = server.base_url
        server.stop()
        proc = self.run_describe([self.img, "--ollama-url", url])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("not running", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_missing_file_is_plain_error_exit_1(self):
        proc = self.run_describe(["/no/such/file.png"])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("No such file", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_cache_hit_makes_no_new_calls(self):
        server = self.start_server()
        args = [self.img, "--ollama-url", server.base_url]
        first = self.run_describe(args)
        self.assertEqual(first.returncode, 0, first.stderr)
        calls_after_first = len(server.calls)
        self.assertGreater(calls_after_first, 0)
        second = self.run_describe(args)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("(from cache)", second.stdout)
        self.assertEqual(len(server.calls), calls_after_first)

    def test_json_output_schema(self):
        server = self.start_server()
        proc = self.run_describe([self.img, "--ollama-url",
                                  server.base_url, "--json"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(set(data), DESCRIBE_JSON_KEYS)
        self.assertEqual(data["text"], GOOD_DESCRIPTION)
        self.assertEqual(data["model_used"], "minicpm-v")
        self.assertIsNotNone(data["fast_seconds"])
        self.assertIsNone(data["smart_seconds"])
        self.assertFalse(data["escalated"])
        self.assertTrue(data["fast_tried"])
        self.assertFalse(data["from_cache"])
        self.assertEqual(data["tokens_before"], 2040)
        self.assertEqual(data["tokens_after"], 2040)
        self.assertEqual(data["bytes_before"],
                         os.path.getsize(self.img))
        self.assertEqual(data["bytes_after"],
                         os.path.getsize(self.img))

    def test_json_cache_hit_reports_from_cache(self):
        server = self.start_server()
        args = [self.img, "--ollama-url", server.base_url, "--json"]
        self.run_describe(args)
        proc = self.run_describe(args)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertTrue(data["from_cache"])
        self.assertEqual(len(server.calls), 1)

    def test_describes_file_as_given_no_shrink(self):
        # A 512-wide input is described at its own size: before and
        # after tokens match, and no optimized copy is written.
        server = self.start_server()
        proc = self.run_describe([self.small, "--ollama-url",
                                  server.base_url, "--json"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["tokens_before"], 144)
        self.assertEqual(data["tokens_after"], 144)
        self.assertFalse(os.path.exists(
            os.path.join(self.tmp.name, "optimized")))


if __name__ == "__main__":
    unittest.main()
