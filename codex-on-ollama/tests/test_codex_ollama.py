"""Tests for codex_ollama.py (BNB-TOOLS T29).

No live Ollama, no live Codex, no network. The HTTP layer and
the subprocess layer are faked with monkeypatched module
functions, and model lists are fake `ollama list` output.
"""

import argparse
import io
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_DIR = os.path.dirname(HERE)
sys.path.insert(0, TOOL_DIR)

import codex_ollama  # noqa: E402

FAKE_LIST = """NAME                    ID              SIZE      MODIFIED
qwen3-vl-2b:latest      aaa111111111    1.9 GB    2 days ago
qwen2.5-coder:1.5b      bbb222222222    986 MB    3 days ago
qwen3:2b                ccc333333333    1.4 GB    4 days ago
some-random-model:1b    ddd444444444    800 MB    5 days ago
"""

FAKE_LIST_GENERAL_ONLY = """NAME                    ID              SIZE      MODIFIED
qwen3:2b                ccc333333333    1.4 GB    4 days ago
phi4-mini:latest        eee555555555    2.5 GB    6 days ago
"""

FAKE_LIST_VISION_ONLY = """NAME                    ID              SIZE      MODIFIED
qwen3-vl-2b:latest      aaa111111111    1.9 GB    2 days ago
llava:7b                fff666666666    4.1 GB    7 days ago
"""

FAKE_LIST_EMPTY = """NAME                    ID              SIZE      MODIFIED
"""


def make_args(**kwargs):
    defaults = {"model": None, "context": 65536,
                "profile": "bnb-ollama", "home": None,
                "dry_run": False}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


class FakeEnv:
    """Monkeypatch the subprocess and HTTP layers."""

    def __init__(self, test, ollama_version="0.40.0",
                 codex_version="codex-cli 0.169.0",
                 ollama_list=FAKE_LIST, reachable=True):
        self.test = test
        self.ollama_version = ollama_version
        self.codex_version = codex_version
        self.ollama_list = ollama_list
        self.reachable = reachable
        self._orig_run = codex_ollama.run_cmd
        self._orig_http = codex_ollama.http_get_json

    def __enter__(self):
        def fake_run(cmd, timeout=15):
            if cmd == ["ollama", "--version"]:
                if self.ollama_version is None:
                    return None
                return (0, "ollama version is %s" % self.ollama_version)
            if cmd == ["codex", "--version"]:
                if self.codex_version is None:
                    return None
                return (0, self.codex_version)
            if cmd == ["ollama", "list"]:
                if not self.reachable:
                    return (1, "Error: could not connect to Ollama")
                return (0, self.ollama_list)
            raise AssertionError("unexpected command: %r" % (cmd,))

        def fake_http(url, timeout=3):
            if self.reachable:
                return {"models": []}
            return None

        codex_ollama.run_cmd = fake_run
        codex_ollama.http_get_json = fake_http
        return self

    def __exit__(self, *exc):
        codex_ollama.run_cmd = self._orig_run
        codex_ollama.http_get_json = self._orig_http
        return False


class TemplateTests(unittest.TestCase):

    def test_profile_template_parses_as_toml(self):
        text = codex_ollama.load_template("codex-profile.toml")
        data = tomllib.loads(text)
        self.assertEqual(data["model_provider"], "bnb-ollama")
        self.assertEqual(data["model_context_window"], 65536)

    def test_rendered_profile_carries_right_values(self):
        text = codex_ollama.render_profile("qwen2.5-coder:1.5b", 65536)
        data = tomllib.loads(text)
        self.assertEqual(data["model"], "qwen2.5-coder:1.5b")
        self.assertEqual(data["model_provider"], "bnb-ollama")
        self.assertEqual(data["model_context_window"], 65536)
        provider = data["model_providers"]["bnb-ollama"]
        self.assertEqual(provider["base_url"],
                         "http://localhost:11434/v1/")
        self.assertEqual(provider["wire_api"], "responses")
        self.assertEqual(provider["stream_idle_timeout_ms"], 120000)

    def test_rendered_profile_uses_given_context(self):
        text = codex_ollama.render_profile("qwen3:2b", 32768)
        data = tomllib.loads(text)
        self.assertEqual(data["model"], "qwen3:2b")
        self.assertEqual(data["model_context_window"], 32768)

    def test_override_template_carries_right_value(self):
        text = codex_ollama.render_override(65536)
        self.assertIn("[Service]", text)
        self.assertIn('Environment="OLLAMA_CONTEXT_LENGTH=65536"', text)
        self.assertEqual(codex_ollama.parse_override_value(text), 65536)

    def test_override_template_uses_given_context(self):
        text = codex_ollama.render_override(32768)
        self.assertIn('Environment="OLLAMA_CONTEXT_LENGTH=32768"', text)
        self.assertEqual(codex_ollama.parse_override_value(text), 32768)

    def test_no_em_dash_in_templates(self):
        for filename in ("codex-profile.toml",
                         "ollama-context-override.conf"):
            text = codex_ollama.load_template(filename)
            self.assertNotIn("\u2014", text, filename)

    def test_no_em_dash_anywhere_in_pack(self):
        # U33: no em-dashes in user-visible text. Scan every file
        # in the pack for the real character.
        for root, dirs, files in os.walk(TOOL_DIR):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in files:
                path = os.path.join(root, name)
                with open(path, encoding="utf-8") as handle:
                    self.assertNotIn("\u2014", handle.read(), path)


class ModelPickTests(unittest.TestCase):

    def test_coder_first(self):
        models = codex_ollama.parse_ollama_list(FAKE_LIST)
        self.assertEqual(codex_ollama.pick_model(models),
                         "qwen2.5-coder:1.5b")

    def test_general_when_no_coder(self):
        models = codex_ollama.parse_ollama_list(FAKE_LIST_GENERAL_ONLY)
        self.assertEqual(codex_ollama.pick_model(models), "qwen3:2b")

    def test_skips_vision_only(self):
        models = codex_ollama.parse_ollama_list(FAKE_LIST_VISION_ONLY)
        self.assertIsNone(codex_ollama.pick_model(models))
        self.assertTrue(codex_ollama.skip_model("qwen3-vl-2b:latest"))
        self.assertTrue(codex_ollama.skip_model("llava:7b"))
        self.assertFalse(codex_ollama.skip_model("qwen3:2b"))

    def test_skips_unknown_families(self):
        self.assertIsNone(
            codex_ollama.pick_model(["some-random-model:1b"]))
        self.assertIsNone(codex_ollama.pick_model([]))

    def test_skips_embedding_models(self):
        self.assertTrue(codex_ollama.skip_model("nomic-embed-text"))
        self.assertIsNone(
            codex_ollama.pick_model(["nomic-embed-text:latest"]))

    def test_parse_ollama_list(self):
        models = codex_ollama.parse_ollama_list(FAKE_LIST)
        self.assertEqual(models, ["qwen3-vl-2b:latest",
                                  "qwen2.5-coder:1.5b",
                                  "qwen3:2b",
                                  "some-random-model:1b"])
        self.assertEqual(codex_ollama.parse_ollama_list(FAKE_LIST_EMPTY),
                         [])


class VersionTests(unittest.TestCase):

    def test_parse_version(self):
        self.assertEqual(
            codex_ollama.parse_version("ollama version is 0.13.4"),
            (0, 13, 4))
        self.assertEqual(codex_ollama.parse_version("0.40.0"),
                         (0, 40, 0))
        self.assertIsNone(codex_ollama.parse_version("no version here"))

    def test_0_13_3_too_old(self):
        self.assertLess(codex_ollama.parse_version("0.13.3"),
                        codex_ollama.MIN_OLLAMA)

    def test_0_13_4_ok(self):
        self.assertGreaterEqual(codex_ollama.parse_version("0.13.4"),
                                codex_ollama.MIN_OLLAMA)

    def test_0_15_launch_ok(self):
        self.assertGreaterEqual(codex_ollama.parse_version("0.15.0"),
                                codex_ollama.LAUNCH_MIN_OLLAMA)
        self.assertLess(codex_ollama.parse_version("0.14.9"),
                        codex_ollama.LAUNCH_MIN_OLLAMA)

    def test_check_flags_old_ollama(self):
        with tempfile.TemporaryDirectory() as home:
            with FakeEnv(self, ollama_version="0.13.3"):
                checks = codex_ollama.collect_checks(home=home)
            version = [c for c in checks
                       if c["name"] == "Ollama version"][0]
            self.assertFalse(version["ok"])
            self.assertIn("too old", version["detail"])


class SetupTests(unittest.TestCase):

    def run_setup(self, home, **kwargs):
        args = make_args(home=home, **kwargs)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = codex_ollama.cmd_setup(args)
        return code, buf.getvalue()

    def test_setup_happy_path_writes_profile_and_override(self):
        with tempfile.TemporaryDirectory() as home:
            with FakeEnv(self):
                code, out = self.run_setup(home)
            self.assertEqual(code, 0, out)
            profile = os.path.join(home, ".codex",
                                   "bnb-ollama.config.toml")
            with open(profile, encoding="utf-8") as handle:
                data = tomllib.loads(handle.read())
            self.assertEqual(data["model"], "qwen2.5-coder:1.5b")
            self.assertEqual(data["model_context_window"], 65536)
            override = os.path.join(home, ".codex",
                                    "ollama-context-override.conf")
            with open(override, encoding="utf-8") as handle:
                text = handle.read()
            self.assertIn("OLLAMA_CONTEXT_LENGTH=65536", text)
            self.assertIn("trial", out.lower())

    def test_setup_with_context_fallback(self):
        with tempfile.TemporaryDirectory() as home:
            with FakeEnv(self):
                code, out = self.run_setup(home, context=32768)
            self.assertEqual(code, 0, out)
            profile = os.path.join(home, ".codex",
                                   "bnb-ollama.config.toml")
            with open(profile, encoding="utf-8") as handle:
                data = tomllib.loads(handle.read())
            self.assertEqual(data["model_context_window"], 32768)

    def test_setup_with_model_override(self):
        with tempfile.TemporaryDirectory() as home:
            with FakeEnv(self):
                code, out = self.run_setup(home, model="qwen3:2b")
            self.assertEqual(code, 0, out)
            profile = os.path.join(home, ".codex",
                                   "bnb-ollama.config.toml")
            with open(profile, encoding="utf-8") as handle:
                data = tomllib.loads(handle.read())
            self.assertEqual(data["model"], "qwen3:2b")

    def test_setup_refuses_when_codex_missing(self):
        with tempfile.TemporaryDirectory() as home:
            with FakeEnv(self, codex_version=None):
                code, out = self.run_setup(home)
            self.assertEqual(code, 1)
            self.assertIn("Codex is not installed", out)
            self.assertIn("bash install-codex.sh", out)
            self.assertFalse(os.path.exists(
                os.path.join(home, ".codex", "bnb-ollama.config.toml")))

    def test_setup_refuses_when_ollama_missing(self):
        with tempfile.TemporaryDirectory() as home:
            with FakeEnv(self, ollama_version=None, reachable=False):
                code, out = self.run_setup(home)
            self.assertEqual(code, 1)
            self.assertIn("Ollama is not installed", out)

    def test_setup_refuses_when_ollama_not_running(self):
        with tempfile.TemporaryDirectory() as home:
            with FakeEnv(self, reachable=False):
                code, out = self.run_setup(home)
            self.assertEqual(code, 1)
            self.assertIn("Ollama is not running", out)

    def test_setup_fails_plainly_with_no_suitable_model(self):
        with tempfile.TemporaryDirectory() as home:
            with FakeEnv(self, ollama_list=FAKE_LIST_VISION_ONLY):
                code, out = self.run_setup(home)
            self.assertEqual(code, 1)
            self.assertIn("No suitable model is installed", out)
            self.assertIn("ollama pull qwen2.5-coder:1.5b", out)

    def test_setup_fails_plainly_with_empty_model_list(self):
        with tempfile.TemporaryDirectory() as home:
            with FakeEnv(self, ollama_list=FAKE_LIST_EMPTY):
                code, out = self.run_setup(home)
            self.assertEqual(code, 1)
            self.assertIn("No suitable model is installed", out)
            self.assertIn("ollama pull qwen2.5-coder:1.5b", out)

    def test_setup_refuses_unknown_model_override(self):
        with tempfile.TemporaryDirectory() as home:
            with FakeEnv(self):
                code, out = self.run_setup(home, model="not-a-model:9b")
            self.assertEqual(code, 1)
            self.assertIn("is not installed", out)


class CheckTests(unittest.TestCase):

    def test_check_tolerates_ollama_not_running(self):
        with tempfile.TemporaryDirectory() as home:
            with FakeEnv(self, reachable=False):
                checks = codex_ollama.collect_checks(home=home)
            running = [c for c in checks
                       if c["name"] == "Ollama running"][0]
            self.assertFalse(running["ok"])
            self.assertIn("not running", running["detail"])
            model = [c for c in checks if c["name"] == "Model"][0]
            self.assertIn("skipped", model["detail"])
            args = make_args(home=home)
            buf = io.StringIO()
            with FakeEnv(self, reachable=False):
                with redirect_stdout(buf):
                    code = codex_ollama.cmd_check(args)
            self.assertEqual(code, 1)
            self.assertIn("Ollama is not running", buf.getvalue())

    def test_check_reports_missing_profile(self):
        with tempfile.TemporaryDirectory() as home:
            with FakeEnv(self):
                checks = codex_ollama.collect_checks(home=home)
            profile = [c for c in checks
                       if c["name"] == "Codex profile"][0]
            self.assertFalse(profile["ok"])
            self.assertIn("missing", profile["detail"])

    def test_check_marks_picked_model(self):
        with tempfile.TemporaryDirectory() as home:
            with FakeEnv(self):
                checks = codex_ollama.collect_checks(home=home)
            model = [c for c in checks if c["name"] == "Model"][0]
            self.assertTrue(model["ok"])
            self.assertIn("qwen2.5-coder:1.5b (picked)", model["detail"])

    def test_check_reports_no_suitable_model(self):
        with tempfile.TemporaryDirectory() as home:
            with FakeEnv(self, ollama_list=FAKE_LIST_VISION_ONLY):
                checks = codex_ollama.collect_checks(home=home)
            model = [c for c in checks if c["name"] == "Model"][0]
            self.assertFalse(model["ok"])
            self.assertIn("ollama pull qwen2.5-coder:1.5b", model["fix"])


class LaunchTests(unittest.TestCase):

    def test_dry_run_prints_exact_command(self):
        args = make_args(dry_run=True)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = codex_ollama.cmd_launch(args)
        self.assertEqual(code, 0)
        self.assertEqual(buf.getvalue(), "codex --profile bnb-ollama\n")

    def test_dry_run_needs_no_ollama_or_codex(self):
        # No FakeEnv: dry-run must not touch the network or disk.
        args = make_args(dry_run=True)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = codex_ollama.cmd_launch(args)
        self.assertEqual(code, 0)
        self.assertEqual(buf.getvalue(), "codex --profile bnb-ollama\n")

    def test_launch_refuses_when_checks_fail(self):
        with tempfile.TemporaryDirectory() as home:
            args = make_args(home=home)
            buf = io.StringIO()
            with FakeEnv(self, reachable=False):
                with redirect_stdout(buf):
                    code = codex_ollama.cmd_launch(args)
            self.assertEqual(code, 1)
            self.assertIn("Cannot launch", buf.getvalue())
            self.assertIn("Ollama is not running", buf.getvalue())


class CliTests(unittest.TestCase):

    def run_cli(self, *argv):
        return subprocess.run(
            [sys.executable,
             os.path.join(TOOL_DIR, "codex_ollama.py")] + list(argv),
            capture_output=True, text=True, timeout=30)

    def test_help_exits_0(self):
        proc = self.run_cli("--help")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("setup", proc.stdout)
        self.assertIn("check", proc.stdout)
        self.assertIn("launch", proc.stdout)

    def test_version_exits_0(self):
        proc = self.run_cli("--version")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("codex-on-ollama", proc.stdout)
        self.assertIn("0.1.0", proc.stdout)

    def test_subcommand_help_exits_0(self):
        for sub in ("setup", "check", "launch"):
            proc = self.run_cli(sub, "--help")
            self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
