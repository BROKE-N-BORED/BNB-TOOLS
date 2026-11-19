"""Suite for T41 manual-pdf-builder. Stdlib only, no network.

The render tests use the real headless Chromium when one is
installed and skip (with a clear reason) when none is. The
missing-Chromium guard is tested for real, in a subprocess with
a scrubbed environment, either way.
"""
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL_DIR = HERE.parent
sys.path.insert(0, str(TOOL_DIR))

import manual_pdf as mp
from tests.helpers import (EM_DASH, EN_DASH, SAMPLE_MANUAL,
                           make_tree, write_manual)

T21_DEBUG_LOG_SHA256 = (
    "d304c17e6c607b58d44b201bd4df7b8c355acb796a10bb13029ab69ec19e73a2")

CHROMIUM = mp.find_chromium()
needs_chromium = unittest.skipUnless(
    CHROMIUM, "no headless Chromium found on this machine")


def run_cli(argv, env=None, cwd=None):
    """Run the CLI in a subprocess; returns the CompletedProcess."""
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(TOOL_DIR / "manual_pdf.py")] + argv,
        capture_output=True, text=True, env=full_env,
        cwd=str(cwd) if cwd else None, timeout=120)


class TestDashes(unittest.TestCase):
    def test_clean_text_passes(self):
        self.assertEqual(mp.find_dashes("plain words - a hyphen"), [])

    def test_em_dash_found_with_line(self):
        text = "line one\nline two " + EM_DASH + " dash\n"
        hits = mp.find_dashes(text)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["line"], 2)
        self.assertEqual(hits[0]["kind"], "em-dash")

    def test_en_dash_found(self):
        hits = mp.find_dashes("pages 1" + EN_DASH + "3")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["kind"], "en-dash")

    def test_multiple_dashes_all_found(self):
        text = EM_DASH + "\nclean\n" + EN_DASH + " and " + EM_DASH
        self.assertEqual(len(mp.find_dashes(text)), 3)

    def test_check_file_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            manual = write_manual(tmp)
            result = mp.check_em_dashes(str(manual))
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["problems"], [])

    def test_check_file_fail_names_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            manual = write_manual(tmp, "ok\nbad " + EM_DASH + " here\n")
            result = mp.check_em_dashes(str(manual))
        self.assertEqual(result["status"], "fail")
        self.assertIn("line 2", result["problems"][0])
        self.assertIn("em-dash", result["problems"][0])

    def test_check_missing_file_is_error(self):
        result = mp.check_em_dashes("/no/such/MANUAL.md")
        self.assertEqual(result["status"], "error")
        self.assertIn("no such manual file", result["problems"][0])


class TestMarkdown(unittest.TestCase):
    def test_headings_and_title(self):
        page = mp.markdown_to_html("# My Title\n\n## Section\n")
        self.assertIn("<title>My Title</title>", page)
        self.assertIn("<h1>My Title</h1>", page)
        self.assertIn("<h2>Section</h2>", page)

    def test_title_argument_wins(self):
        page = mp.markdown_to_html("# Heading\n", title="Given")
        self.assertIn("<title>Given</title>", page)

    def test_subtitle_class_on_paragraph_after_h1(self):
        page = mp.markdown_to_html("# T\n\nApp v1.0.0\n\nBody.\n")
        self.assertIn('<p class="title-sub">App v1.0.0</p>', page)

    def test_lists(self):
        page = mp.markdown_to_html("1. one\n2. two\n\n- a\n- b\n")
        self.assertIn("<ol>", page)
        self.assertIn("<li>one</li>", page)
        self.assertIn("<ul>", page)
        self.assertIn("<li>b</li>", page)

    def test_bold_code_and_link(self):
        page = mp.markdown_to_html(
            "Press **Save**, run `go.py`, see https://example.com/x\n")
        self.assertIn("<strong>Save</strong>", page)
        self.assertIn("<code>go.py</code>", page)
        self.assertIn('<a href="https://example.com/x">', page)

    def test_fenced_code_block_escaped(self):
        page = mp.markdown_to_html("```\nif a < b:\n    pass\n```\n")
        self.assertIn("<pre><code>", page)
        self.assertIn("a &lt; b", page)

    def test_html_in_prose_is_escaped(self):
        page = mp.markdown_to_html("Use <b>tags</b> carefully.\n")
        self.assertIn("&lt;b&gt;", page)
        self.assertNotIn("<p>Use <b>tags</b>", page)

    def test_unclosed_fence_still_renders(self):
        page = mp.markdown_to_html("```\ncode without end\n")
        self.assertIn("code without end", page)

    def test_a4_page_rule(self):
        page = mp.markdown_to_html("# T\n")
        self.assertIn("@page { size: A4;", page)


class TestReferences(unittest.TestCase):
    def test_extract_paths_from_sample(self):
        refs = mp.extract_references(SAMPLE_MANUAL)
        paths = {r["path"] for r in refs}
        self.assertIn("install.sh", paths)
        self.assertIn("uninstall.sh", paths)
        self.assertIn("src/app.py", paths)
        self.assertIn("src/helper.py", paths)
        self.assertIn("docs/rules.md", paths)

    def test_home_path_not_checked(self):
        refs = mp.extract_references(SAMPLE_MANUAL)
        self.assertNotIn("~/.local/sampleapp",
                         {r["path"] for r in refs})

    def test_url_not_a_path(self):
        refs = mp.extract_references("See `https://example.com/a.py`\n")
        self.assertEqual(refs, [])

    def test_bare_path_span(self):
        refs = mp.extract_references("Open `src/main.py` now.\n")
        self.assertEqual([r["path"] for r in refs], ["src/main.py"])

    def test_fenced_block_commands(self):
        md = "Steps:\n\n```\nbash setup.sh\ncd tools\n```\n"
        paths = {r["path"] for r in mp.extract_references(md)}
        self.assertEqual(paths, {"setup.sh", "tools"})

    def test_chmod_target(self):
        refs = mp.extract_references("Run `chmod +x install.sh`.\n")
        self.assertEqual([r["path"] for r in refs], ["install.sh"])

    def test_cp_checks_source_not_destination(self):
        refs = mp.extract_references("`cp old.txt new.txt`\n")
        self.assertEqual([r["path"] for r in refs], ["old.txt"])

    def test_flag_only_command_checks_nothing(self):
        refs = mp.extract_references("`ls -la` and `python3 -m pytest`\n")
        self.assertEqual(refs, [])

    def test_line_numbers(self):
        refs = mp.extract_references("one\ntwo\nOpen `a.py`.\n")
        self.assertEqual(refs[0]["line"], 3)

    def test_check_passes_on_matching_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = make_tree(tmp)
            manual = write_manual(tmp)
            result = mp.check_references(str(manual), str(tree))
        self.assertEqual(result["status"], "pass", result["problems"])
        self.assertEqual(result["checked_paths"], 5)
        self.assertEqual(result["checked_versions"], 1)

    def test_check_fails_on_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = make_tree(tmp)
            (tree / "src" / "helper.py").unlink()
            manual = write_manual(tmp)
            result = mp.check_references(str(manual), str(tree))
        self.assertEqual(result["status"], "fail")
        self.assertTrue(any("src/helper.py" in p
                            for p in result["problems"]))

    def test_extension_span_is_not_a_path(self):
        # The SOLDAR manual's shape: "named after the workflow
        # with `.soldar.json` on the end" cites an extension,
        # not a file.
        refs = mp.extract_references(
            "The copy ends with `.soldar.json` on it.\n")
        self.assertEqual(refs, [])

    def test_skip_comment_exempts_runtime_paths(self):
        text = ("# App\n\n<!-- manual-pdf-skip: update/ -->\n\n"
                "Files: `soldar.db` lives here, `update/` waits.\n"
                "Run `bash install.sh`.\n")
        with tempfile.TemporaryDirectory() as tmp:
            tree = make_tree(tmp)
            manual = write_manual(tmp, text)
            result = mp.check_references(str(manual), str(tree))
            self.assertEqual(result["status"], "pass",
                             result["problems"])
            self.assertEqual(result["skipped_paths"], 1)
            # Without the comment, the same manual fails.
            manual = write_manual(
                tmp, text.replace(
                    "<!-- manual-pdf-skip: update/ -->", ""))
            result = mp.check_references(str(manual), str(tree))
            self.assertEqual(result["status"], "fail")
            self.assertTrue(any("update/" in p
                                for p in result["problems"]))

    def test_release_zip_checked_by_version_not_existence(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = make_tree(tmp)
            manual = write_manual(
                tmp, "# SampleApp\n\nDownload `sampleapp-v0.1.0.zip` "
                     "from the Releases page.\n")
            result = mp.check_references(str(manual), str(tree))
            self.assertEqual(result["status"], "pass",
                             result["problems"])
            manual = write_manual(
                tmp, "# SampleApp\n\nDownload `sampleapp-v0.9.0.zip` "
                     "from the Releases page.\n")
            result = mp.check_references(str(manual), str(tree))
            self.assertEqual(result["status"], "fail")
            self.assertTrue(any("v0.9.0" in p
                                for p in result["problems"]))

    def test_check_missing_inputs_are_errors(self):
        result = mp.check_references("/no/MANUAL.md", "/no/tree")
        self.assertEqual(result["status"], "error")
        with tempfile.TemporaryDirectory() as tmp:
            manual = write_manual(tmp)
            result = mp.check_references(str(manual), "/no/tree")
        self.assertEqual(result["status"], "error")
        self.assertIn("no such project tree", result["problems"][0])


class TestVersions(unittest.TestCase):
    def test_v_prefixed_always_extracted(self):
        found = mp.extract_versions("App v1.2.3 is out.\n", "Other")
        self.assertEqual([f["version"] for f in found], ["1.2.3"])

    def test_two_part_v_version_padded(self):
        found = mp.extract_versions("App v1.2 is out.\n")
        self.assertEqual(found[0]["version"], "1.2.0")

    def test_bare_version_needs_project_name(self):
        text = "Needs Node 20.1.0 and SampleApp 0.1.0 today.\n"
        found = mp.extract_versions(text, "SampleApp")
        self.assertEqual([f["version"] for f in found], ["0.1.0"])

    def test_dependency_version_ignored(self):
        found = mp.extract_versions("Python 3.12.1 or newer.\n",
                                    "SampleApp")
        self.assertEqual(found, [])

    def test_tree_version_from_changelog(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = make_tree(tmp)
            version, source = mp.find_tree_version(str(tree))
        self.assertEqual(version, "0.1.0")
        self.assertEqual(source, "CHANGELOG.md")

    def test_tree_version_from_version_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = make_tree(tmp)
            (tree / "VERSION").write_text("2.5\n", encoding="utf-8")
            version, source = mp.find_tree_version(str(tree))
        self.assertEqual(version, "2.5.0")
        self.assertEqual(source, "VERSION")

    def test_tree_version_none_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            version, source = mp.find_tree_version(tmp)
        self.assertIsNone(version)
        self.assertIsNone(source)

    def test_version_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = make_tree(tmp)
            manual = write_manual(
                tmp, SAMPLE_MANUAL.replace("v0.1.0", "v0.2.0"))
            result = mp.check_references(str(manual), str(tree))
        self.assertEqual(result["status"], "fail")
        self.assertTrue(any("v0.2.0" in p and "v0.1.0" in p
                            for p in result["problems"]))

    def test_version_unverifiable_is_warning_not_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "bare"
            tree.mkdir()
            (tree / "install.sh").write_text("x\n", encoding="utf-8")
            manual = write_manual(tmp, "# Bare v9.9.9\n\n"
                                       "Run `bash install.sh`.\n")
            result = mp.check_references(str(manual), str(tree))
        self.assertEqual(result["status"], "pass")
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("could not be checked", result["warnings"][0])


class TestChromiumDiscovery(unittest.TestCase):
    def test_explicit_path_wins(self):
        self.assertEqual(mp.find_chromium(sys.executable),
                         sys.executable)

    def test_explicit_missing_returns_none(self):
        self.assertIsNone(mp.find_chromium("/no/such/chromium"))

    def test_env_var(self):
        old = os.environ.get("MANUAL_PDF_CHROMIUM")
        os.environ["MANUAL_PDF_CHROMIUM"] = sys.executable
        try:
            self.assertEqual(mp.find_chromium(), sys.executable)
        finally:
            if old is None:
                del os.environ["MANUAL_PDF_CHROMIUM"]
            else:
                os.environ["MANUAL_PDF_CHROMIUM"] = old


class TestRender(unittest.TestCase):
    @needs_chromium
    def test_render_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            manual = write_manual(tmp)
            out = Path(tmp) / "Manual.pdf"
            result = mp.render_pdf(str(manual), str(out))
            self.assertEqual(result["status"], "pass",
                             result["problems"])
            self.assertTrue(out.is_file())
            self.assertEqual(out.read_bytes()[:4], b"%PDF")
            self.assertGreaterEqual(result["pages"], 1)
            self.assertEqual(result["pages"],
                             mp.count_pdf_pages(out))
            self.assertGreater(result["bytes"], 1000)

    @needs_chromium
    def test_render_long_manual_has_multiple_pages(self):
        text = "# Long\n\n" + "\n\n".join(
            "## Section %d\n\nSome body text for section %d."
            % (i, i) for i in range(30))
        with tempfile.TemporaryDirectory() as tmp:
            manual = write_manual(tmp, text)
            out = Path(tmp) / "Long.pdf"
            result = mp.render_pdf(str(manual), str(out))
        self.assertEqual(result["status"], "pass", result["problems"])
        self.assertGreaterEqual(result["pages"], 3)

    @needs_chromium
    def test_render_refuses_dashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            manual = write_manual(tmp, "# T\n\nBad " + EM_DASH + " dash\n")
            out = Path(tmp) / "X.pdf"
            result = mp.render_pdf(str(manual), str(out))
            self.assertEqual(result["status"], "fail")
            self.assertFalse(out.exists())

    def test_render_missing_manual_is_error(self):
        result = mp.render_pdf("/no/MANUAL.md", "/tmp/x.pdf")
        self.assertEqual(result["status"], "error")

    def test_count_pages_missing_file(self):
        self.assertEqual(mp.count_pdf_pages("/no/such.pdf"), 0)


class TestBuildChain(unittest.TestCase):
    @needs_chromium
    def test_build_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = make_tree(tmp)
            manual = write_manual(tmp)
            out = Path(tmp) / "Manual.pdf"
            result = mp.build(str(manual), str(tree), str(out))
            self.assertEqual(result["status"], "pass",
                             result.get("problems"))
            self.assertEqual(result["step"], "render")
            self.assertTrue(out.is_file())
            self.assertEqual(result["checked_paths"], 5)

    def test_build_stops_at_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = make_tree(tmp)
            (tree / "install.sh").unlink()
            manual = write_manual(tmp)
            out = Path(tmp) / "Manual.pdf"
            result = mp.build(str(manual), str(tree), str(out))
            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["step"], "check")
            self.assertFalse(out.exists())

    def test_build_stops_at_emdash(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = make_tree(tmp)
            manual = write_manual(
                tmp, SAMPLE_MANUAL + "\nA dash " + EM_DASH + " here.\n")
            out = Path(tmp) / "Manual.pdf"
            result = mp.build(str(manual), str(tree), str(out))
            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["step"], "emdash")


class TestCli(unittest.TestCase):
    def test_help(self):
        proc = run_cli(["--help"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("check", proc.stdout)
        self.assertIn("render", proc.stdout)

    def test_version(self):
        proc = run_cli(["--version"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("0.1.0", proc.stdout)

    def test_no_command_prints_help_exit_2(self):
        proc = run_cli([])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("usage", proc.stdout.lower())

    def test_cli_check_pass_and_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = make_tree(tmp)
            manual = write_manual(tmp)
            ok = run_cli(["check", str(manual), "--tree", str(tree)])
            self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
            self.assertIn("OK:", ok.stdout)
            (tree / "docs" / "rules.md").unlink()
            bad = run_cli(["check", str(manual), "--tree", str(tree)])
            self.assertEqual(bad.returncode, 1)
            self.assertIn("docs/rules.md", bad.stdout)
            self.assertNotIn("Traceback", bad.stdout + bad.stderr)

    def test_cli_emdash(self):
        with tempfile.TemporaryDirectory() as tmp:
            manual = write_manual(tmp, "text " + EN_DASH + " dash\n")
            proc = run_cli(["emdash", str(manual)])
            self.assertEqual(proc.returncode, 1)
            self.assertIn("en-dash", proc.stdout)

    def test_cli_missing_manual_plain_error_no_traceback(self):
        proc = run_cli(["emdash", "/no/such/MANUAL.md"])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no such manual file", proc.stdout)
        self.assertNotIn("Traceback", proc.stdout + proc.stderr)

    @needs_chromium
    def test_cli_render_and_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = make_tree(tmp)
            manual = write_manual(tmp)
            out = Path(tmp) / "Out.pdf"
            proc = run_cli(["render", str(manual), "--out", str(out)])
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("Wrote", proc.stdout)
            self.assertTrue(out.is_file())
            out2 = Path(tmp) / "Out2.pdf"
            proc = run_cli(["build", str(manual), "--tree", str(tree),
                            "--out", str(out2)])
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("Built", proc.stdout)
            self.assertTrue(out2.is_file())

    def test_missing_chromium_guard(self):
        """Regression test for the missing-dependency guard: with
        no Chromium anywhere (empty HOME, empty PATH, no env var),
        render must exit 1, name what is missing and how to get
        it, and never print a traceback."""
        with tempfile.TemporaryDirectory() as tmp:
            manual = write_manual(tmp)
            empty_bin = Path(tmp) / "bin"
            empty_bin.mkdir()
            fake_home = Path(tmp) / "home"
            fake_home.mkdir()
            env = {"PATH": str(empty_bin), "HOME": str(fake_home),
                   "MANUAL_PDF_CHROMIUM": ""}
            # PATH is scrubbed, so invoke python by absolute path.
            proc = subprocess.run(
                [sys.executable, str(TOOL_DIR / "manual_pdf.py"),
                 "render", str(manual), "--out",
                 str(Path(tmp) / "X.pdf")],
                capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(proc.returncode, 1,
                             proc.stdout + proc.stderr)
            self.assertIn("headless Chromium", proc.stdout)
            self.assertIn("playwright install", proc.stdout)
            self.assertNotIn("Traceback", proc.stdout + proc.stderr)
            self.assertFalse((Path(tmp) / "X.pdf").exists())


class TestPackaging(unittest.TestCase):
    def test_debug_log_unmodified(self):
        digest = hashlib.sha256(
            (TOOL_DIR / "debug_log.py").read_bytes()).hexdigest()
        self.assertEqual(digest, T21_DEBUG_LOG_SHA256)

    def test_no_em_dash_bytes_in_tree(self):
        # debug_log.py is excluded: it is the T21 file, copied
        # unmodified and pinned by SHA-256 instead (it carries a
        # few em-dash bytes of its own, by design of the layer).
        needle = bytes([0xE2, 0x80, 0x94])
        offenders = []
        for path in TOOL_DIR.rglob("*"):
            if (path.is_file() and "__pycache__" not in str(path)
                    and path.name != "debug_log.py"):
                if needle in path.read_bytes():
                    offenders.append(str(path))
        self.assertEqual(offenders, [])

    def test_stdlib_only_imports(self):
        import ast
        # debug_log (the bundled T21 module, imported lazily) and
        # manual_pdf (the tool's own module, imported by demo.py)
        # are local; everything else must be standard library.
        allowed = set(sys.stdlib_module_names) | {"debug_log",
                                                  "manual_pdf"}
        for name in ("manual_pdf.py", "demo.py", "build_zip.py"):
            tree = ast.parse((TOOL_DIR / name).read_text(
                encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertIn(alias.name.split(".")[0], allowed,
                                      "%s imports %s" % (name, alias.name))
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.level == 0:
                        self.assertIn(node.module.split(".")[0], allowed,
                                      "%s imports %s" % (name, node.module))

    def test_zip_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "tool.zip"
            proc = subprocess.run(
                [sys.executable, str(TOOL_DIR / "build_zip.py"),
                 "--out", str(out)],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            with zipfile.ZipFile(out) as zf:
                infos = {i.filename: i for i in zf.infolist()}
            self.assertIn("manual_pdf.py", infos)
            self.assertIn("README.md", infos)
            self.assertNotIn("BUILD_REPORT.md", infos)
            script_mode = infos["manual_pdf.py"].external_attr >> 16
            plain_mode = infos["README.md"].external_attr >> 16
            self.assertEqual(script_mode, 0o100755)
            self.assertEqual(plain_mode, 0o100644)

    def test_debug_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.txt"
            proc = run_cli(["debug-report", "--out", str(out)])
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertTrue(out.is_file())
            self.assertIn("manual-pdf-builder",
                          out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
