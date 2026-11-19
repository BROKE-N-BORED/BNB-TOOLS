"""Tests for release-zip-mode-checker (T39).

No network, no real Release zips: every zip is a fixture built
in a temp dir with exact stored modes.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL_DIR = HERE.parent
sys.path.insert(0, str(TOOL_DIR))

from helpers import dos_file, make_zip, run_cli, unix_dir, unix_file
import release_zip_mode_checker as rzmc


class CheckFunctionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def zip_path(self, name="app.zip"):
        return self.dir / name

    def test_clean_zip_passes(self):
        path = self.zip_path()
        make_zip(path, [
            unix_file("install.sh", b"#!/bin/sh\n", 0o100755),
            unix_file("installer.desktop", b"[Desktop Entry]\n",
                      0o100755),
            unix_file("README.md", b"hi\n", 0o100644),
        ])
        result = rzmc.check_zip(str(path))
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["checked"]), 2)
        self.assertEqual(len(result["failures"]), 0)
        self.assertEqual(result["other_files"], 1)
        self.assertEqual(result["entries"], 3)

    def test_sh_at_644_fails(self):
        path = self.zip_path()
        make_zip(path, [unix_file("install.sh", mode=0o100644)])
        result = rzmc.check_zip(str(path))
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["failures"]), 1)
        self.assertEqual(result["failures"][0]["name"],
                         "install.sh")
        self.assertEqual(result["failures"][0]["mode"], 0o100644)

    def test_desktop_at_644_fails(self):
        # The OST v22 failure, exactly: installer.desktop stored
        # 0o100644, double-click opened a text editor.
        path = self.zip_path()
        make_zip(path, [
            unix_file("installer.desktop", mode=0o100644)])
        result = rzmc.check_zip(str(path))
        self.assertFalse(result["ok"])
        self.assertEqual(result["failures"][0]["name"],
                         "installer.desktop")

    def test_bare_755_without_file_type_bits_fails(self):
        # 0o755 with no file-type bits extracts fine under the
        # unzip CLI but GUI extractors drop the exec bit, so it
        # is NOT 0o100755 and must fail.
        path = self.zip_path()
        make_zip(path, [unix_file("install.sh", mode=0o755)])
        result = rzmc.check_zip(str(path))
        self.assertFalse(result["ok"])
        self.assertEqual(result["failures"][0]["mode"], 0o755)

    def test_dos_created_entry_has_no_stored_mode_and_fails(self):
        path = self.zip_path()
        make_zip(path, [dos_file("install.sh")])
        result = rzmc.check_zip(str(path))
        self.assertFalse(result["ok"])
        self.assertIsNone(result["failures"][0]["mode"])

    def test_unix_entry_with_zero_external_attr_fails(self):
        # Python's writestr will not write a zero external_attr
        # (it substitutes 0o600), so build the zip, then zero
        # the external_attr field in the central directory
        # (offset 38 in the PK\x01\x02 header) by hand.
        path = self.zip_path()
        make_zip(path, [unix_file("install.sh", mode=0o100644)])
        data = bytearray(path.read_bytes())
        idx = data.find(b"PK\x01\x02")
        self.assertNotEqual(idx, -1)
        data[idx + 38:idx + 42] = b"\x00\x00\x00\x00"
        path.write_bytes(bytes(data))
        result = rzmc.check_zip(str(path))
        self.assertFalse(result["ok"])
        self.assertIsNone(result["failures"][0]["mode"])

    def test_empty_zip_passes(self):
        path = self.zip_path()
        make_zip(path, [])
        result = rzmc.check_zip(str(path))
        self.assertTrue(result["ok"])
        self.assertEqual(result["checked"], [])

    def test_zip_with_no_exec_entries_passes(self):
        path = self.zip_path()
        make_zip(path, [unix_file("app.py", mode=0o100644),
                        unix_file("README.md", mode=0o100644)])
        result = rzmc.check_zip(str(path))
        self.assertTrue(result["ok"])
        self.assertEqual(result["other_files"], 2)

    def test_plain_files_not_checked_even_when_executable(self):
        path = self.zip_path()
        make_zip(path, [unix_file("app.py", mode=0o100755),
                        unix_file("run.bin", mode=0o100777)])
        result = rzmc.check_zip(str(path))
        self.assertTrue(result["ok"])
        self.assertEqual(result["checked"], [])

    def test_directories_skipped(self):
        path = self.zip_path()
        make_zip(path, [unix_dir("app"),
                        unix_file("app/install.sh", mode=0o100755)])
        result = rzmc.check_zip(str(path))
        self.assertTrue(result["ok"])
        self.assertEqual(result["directories"], 1)

    def test_suffix_match_is_case_insensitive(self):
        path = self.zip_path()
        make_zip(path, [unix_file("INSTALL.SH", mode=0o100644),
                        unix_file("App.Desktop", mode=0o100644)])
        result = rzmc.check_zip(str(path))
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["failures"]), 2)

    def test_missing_file_raises_plain_words(self):
        with self.assertRaises(rzmc.CheckError) as ctx:
            rzmc.check_zip(str(self.dir / "nope.zip"))
        self.assertIn("no such file", str(ctx.exception))

    def test_not_a_zip_raises_plain_words(self):
        path = self.zip_path()
        path.write_text("this is not a zip\n")
        with self.assertRaises(rzmc.CheckError) as ctx:
            rzmc.check_zip(str(path))
        self.assertIn("not a zip file", str(ctx.exception))

    def test_directory_input_raises_plain_words(self):
        with self.assertRaises(rzmc.CheckError) as ctx:
            rzmc.check_zip(str(self.dir))
        self.assertIn("not a file", str(ctx.exception))

    def test_mode_text(self):
        self.assertEqual(rzmc.mode_text(0o100644), "0o100644")
        self.assertEqual(rzmc.mode_text(0o100755), "0o100755")
        self.assertEqual(rzmc.mode_text(None), "no stored mode")


class CheckCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cli_pass_exit_0_names_entries(self):
        path = self.dir / "app.zip"
        make_zip(path, [
            unix_file("install.sh", mode=0o100755),
            unix_file("installer.desktop", mode=0o100755)])
        code, out, err = run_cli(
            rzmc.main, ["check", str(path)])
        self.assertEqual(code, 0)
        self.assertIn("install.sh", out)
        self.assertIn("installer.desktop", out)
        self.assertIn("0o100755", out)
        self.assertIn("OK:", out)
        self.assertEqual(err, "")

    def test_cli_fail_exit_1_names_entry_and_mode(self):
        path = self.dir / "app.zip"
        make_zip(path, [
            unix_file("installer.desktop", mode=0o100644)])
        code, out, err = run_cli(
            rzmc.main, ["check", str(path)])
        self.assertEqual(code, 1)
        self.assertIn("installer.desktop", out)
        self.assertIn("0o100644", out)
        self.assertIn("FAIL", out)

    def test_cli_fail_no_stored_mode_says_so(self):
        path = self.dir / "app.zip"
        make_zip(path, [dos_file("install.sh")])
        code, out, err = run_cli(
            rzmc.main, ["check", str(path)])
        self.assertEqual(code, 1)
        self.assertIn("no stored mode", out)

    def test_cli_missing_file_exit_2_no_traceback(self):
        code, out, err = run_cli(
            rzmc.main, ["check", str(self.dir / "nope.zip")])
        self.assertEqual(code, 2)
        self.assertIn("no such file", err)
        self.assertNotIn("Traceback", err)
        self.assertNotIn("Traceback", out)

    def test_cli_not_a_zip_exit_2_no_traceback(self):
        path = self.dir / "app.zip"
        path.write_text("nope\n")
        code, out, err = run_cli(
            rzmc.main, ["check", str(path)])
        self.assertEqual(code, 2)
        self.assertIn("not a zip file", err)
        self.assertNotIn("Traceback", err)

    def test_cli_json_output_shape(self):
        path = self.dir / "app.zip"
        make_zip(path, [
            unix_file("install.sh", mode=0o100755),
            unix_file("installer.desktop", mode=0o100644),
            dos_file("run.sh"),
            unix_file("README.md", mode=0o100644)])
        code, out, err = run_cli(
            rzmc.main, ["check", str(path), "--json"])
        self.assertEqual(code, 1)
        data = json.loads(out)
        self.assertFalse(data["ok"])
        self.assertEqual(data["entries"], 4)
        self.assertEqual(data["other_files"], 1)
        by_name = {e["name"]: e for e in data["checked"]}
        self.assertEqual(by_name["install.sh"]["mode"],
                         "0o100755")
        self.assertTrue(by_name["install.sh"]["ok"])
        self.assertEqual(by_name["installer.desktop"]["mode"],
                         "0o100644")
        self.assertFalse(by_name["installer.desktop"]["ok"])
        self.assertIsNone(by_name["run.sh"]["mode"])
        self.assertEqual(sorted(data["failures"]),
                         ["installer.desktop", "run.sh"])

    def test_cli_json_error_output(self):
        code, out, err = run_cli(
            rzmc.main, ["check", str(self.dir / "nope.zip"),
                        "--json"])
        self.assertEqual(code, 2)
        data = json.loads(out)
        self.assertIsNone(data["ok"])
        self.assertIn("no such file", data["error"])


class FixFunctionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_fix_rebuilds_modes_and_check_passes(self):
        src = self.dir / "app.zip"
        make_zip(src, [
            unix_file("install.sh", b"#!/bin/sh\n", 0o100644),
            unix_file("installer.desktop", b"[Desktop]\n",
                      0o100644),
            unix_file("README.md", b"hi\n", 0o100644)])
        dst = self.dir / "fixed.zip"
        changes = rzmc.fix_zip(str(src), str(dst))
        self.assertEqual(
            sorted(name for name, _, _ in changes),
            ["install.sh", "installer.desktop"])
        for name, old, new in changes:
            self.assertEqual(old, 0o100644)
            self.assertEqual(new, 0o100755)
        self.assertTrue(rzmc.check_zip(str(dst))["ok"])
        # The source is untouched by fix_zip itself.
        self.assertFalse(rzmc.check_zip(str(src))["ok"])

    def test_fix_preserves_contents_order_compression_comment(self):
        src = self.dir / "app.zip"
        comment = b"release v1.0"
        make_zip(src, [
            unix_file("b.py", b"bee\n", 0o100644),
            unix_file("a.sh", b"ay\n", 0o100644),
            unix_file("c.md", b"cee\n", 0o100644)],
            comment=comment)
        dst = self.dir / "fixed.zip"
        rzmc.fix_zip(str(src), str(dst))
        with zipfile.ZipFile(src) as zin, \
                zipfile.ZipFile(dst) as zout:
            self.assertEqual(zout.comment, comment)
            self.assertEqual(zout.namelist(), zin.namelist())
            for name in zin.namelist():
                self.assertEqual(zout.read(name), zin.read(name))
                self.assertEqual(
                    zout.getinfo(name).compress_type,
                    zin.getinfo(name).compress_type)
                self.assertEqual(
                    zout.getinfo(name).date_time,
                    zin.getinfo(name).date_time)

    def test_fix_preserves_plain_file_exec_bit(self):
        # A plain file stored 0o100755 keeps it: fix never
        # strips an exec bit something else put there.
        src = self.dir / "app.zip"
        make_zip(src, [unix_file("tool", b"x", 0o100755)])
        dst = self.dir / "fixed.zip"
        changes = rzmc.fix_zip(str(src), str(dst))
        self.assertEqual(changes, [])
        with zipfile.ZipFile(dst) as zf:
            mode = rzmc.stored_mode(zf.getinfo("tool"))
        self.assertEqual(mode, 0o100755)

    def test_fix_gives_modeless_plain_file_644(self):
        src = self.dir / "app.zip"
        make_zip(src, [dos_file("README.md")])
        dst = self.dir / "fixed.zip"
        changes = rzmc.fix_zip(str(src), str(dst))
        self.assertEqual(changes,
                         [("README.md", None, 0o100644)])
        with zipfile.ZipFile(dst) as zf:
            mode = rzmc.stored_mode(zf.getinfo("README.md"))
        self.assertEqual(mode, 0o100644)

    def test_fix_corrects_directory_mode(self):
        src = self.dir / "app.zip"
        make_zip(src, [unix_dir("app", 0o100644),
                        unix_file("app/install.sh", mode=0o100755)])
        dst = self.dir / "fixed.zip"
        changes = rzmc.fix_zip(str(src), str(dst))
        self.assertEqual(changes,
                         [("app/", 0o100644, 0o40755)])
        with zipfile.ZipFile(dst) as zf:
            mode = rzmc.stored_mode(zf.getinfo("app/"))
        self.assertEqual(mode, 0o40755)

    def test_fix_on_clean_zip_changes_nothing(self):
        src = self.dir / "app.zip"
        make_zip(src, [unix_file("install.sh", mode=0o100755)])
        dst = self.dir / "fixed.zip"
        changes = rzmc.fix_zip(str(src), str(dst))
        self.assertEqual(changes, [])
        self.assertTrue(dst.exists())

    def test_fix_missing_file_raises(self):
        with self.assertRaises(rzmc.CheckError):
            rzmc.fix_zip(str(self.dir / "nope.zip"),
                         str(self.dir / "out.zip"))

    def test_fix_not_a_zip_raises(self):
        src = self.dir / "app.zip"
        src.write_text("nope\n")
        with self.assertRaises(rzmc.CheckError):
            rzmc.fix_zip(str(src), str(self.dir / "out.zip"))

    def test_default_fixed_name(self):
        self.assertEqual(
            rzmc.default_fixed_name("/tmp/app-v1.0.zip"),
            "/tmp/app-v1.0-modes-fixed.zip")


class FixCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _bad_zip(self, name="app.zip"):
        path = self.dir / name
        make_zip(path, [
            unix_file("install.sh", mode=0o100644),
            unix_file("installer.desktop", mode=0o100644)])
        return path

    def test_cli_fix_default_out_name(self):
        src = self._bad_zip()
        code, out, err = run_cli(
            rzmc.main, ["fix", str(src)])
        self.assertEqual(code, 0)
        dst = self.dir / "app-modes-fixed.zip"
        self.assertTrue(dst.exists())
        self.assertTrue(rzmc.check_zip(str(dst))["ok"])
        self.assertIn("install.sh: 0o100644 -> 0o100755", out)
        self.assertIn("installer.desktop: 0o100644 -> 0o100755",
                      out)
        self.assertIn("2 entries changed", out)

    def test_cli_fix_explicit_out(self):
        src = self._bad_zip()
        dst = self.dir / "elsewhere.zip"
        code, out, err = run_cli(
            rzmc.main, ["fix", str(src), "--out", str(dst)])
        self.assertEqual(code, 0)
        self.assertTrue(dst.exists())
        self.assertTrue(rzmc.check_zip(str(dst))["ok"])

    def test_cli_fix_refuses_to_overwrite_input(self):
        src = self._bad_zip()
        code, out, err = run_cli(
            rzmc.main, ["fix", str(src), "--out", str(src)])
        self.assertEqual(code, 2)
        self.assertIn("refusing to write over", err)
        self.assertNotIn("Traceback", err)
        # The input is untouched.
        self.assertFalse(rzmc.check_zip(str(src))["ok"])

    def test_cli_fix_out_and_in_place_together_refused(self):
        src = self._bad_zip()
        code, out, err = run_cli(
            rzmc.main, ["fix", str(src), "--out",
                        str(self.dir / "x.zip"), "--in-place"])
        self.assertEqual(code, 2)
        self.assertIn("cannot be used together", err)

    def test_cli_fix_in_place_rewrites_input(self):
        src = self._bad_zip()
        code, out, err = run_cli(
            rzmc.main, ["fix", str(src), "--in-place"])
        self.assertEqual(code, 0)
        self.assertTrue(rzmc.check_zip(str(src))["ok"])
        self.assertIn("-> %s" % src, out)

    def test_cli_fix_in_place_leaves_bad_input_untouched(self):
        src = self.dir / "app.zip"
        src.write_bytes(b"not a zip at all")
        code, out, err = run_cli(
            rzmc.main, ["fix", str(src), "--in-place"])
        self.assertEqual(code, 2)
        self.assertIn("not a zip file", err)
        self.assertEqual(src.read_bytes(), b"not a zip at all")

    def test_cli_fix_missing_file_exit_2(self):
        code, out, err = run_cli(
            rzmc.main, ["fix", str(self.dir / "nope.zip")])
        self.assertEqual(code, 2)
        self.assertIn("no such file", err)
        self.assertNotIn("Traceback", err)

    def test_cli_fix_unwritable_out_exit_2(self):
        src = self._bad_zip()
        code, out, err = run_cli(
            rzmc.main, ["fix", str(src), "--out",
                        str(self.dir / "no-such-dir" / "x.zip")])
        self.assertEqual(code, 2)
        self.assertIn("could not write", err)
        self.assertNotIn("Traceback", err)

    def test_cli_fix_clean_zip_reports_nothing_to_fix(self):
        src = self.dir / "app.zip"
        make_zip(src, [unix_file("install.sh", mode=0o100755)])
        code, out, err = run_cli(
            rzmc.main, ["fix", str(src)])
        self.assertEqual(code, 0)
        self.assertIn("Nothing to fix", out)
        self.assertTrue(
            (self.dir / "app-modes-fixed.zip").exists())


class CliMiscTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_version(self):
        # argparse's version action prints and exits 0.
        out = io.StringIO()
        from contextlib import redirect_stdout
        with redirect_stdout(out):
            with self.assertRaises(SystemExit) as ctx:
                rzmc.main(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("release-zip-mode-checker 0.1.0",
                      out.getvalue())

    def test_no_args_prints_help_exit_2(self):
        code, out, err = run_cli(rzmc.main, [])
        self.assertEqual(code, 2)
        self.assertIn("check", out)
        self.assertIn("fix", out)

    def test_unknown_subcommand_exits_2(self):
        with self.assertRaises(SystemExit) as ctx:
            run_cli(rzmc.main, ["frobnicate"])
        self.assertEqual(ctx.exception.code, 2)

    def test_debug_report_subcommand_writes_file(self):
        report = self.dir / "report.txt"
        code, out, err = run_cli(
            rzmc.main, ["debug-report", "--out", str(report)])
        self.assertEqual(code, 0)
        self.assertTrue(report.exists())
        text = report.read_text(encoding="utf-8")
        self.assertIn("release-zip-mode-checker", text)
        self.assertIn("0.1.0", text)
        self.assertIn("broke.n.bored.studio@gmail.com", out)

    def test_debug_report_on_check_writes_file(self):
        path = self.dir / "app.zip"
        make_zip(path, [unix_file("install.sh", mode=0o100755)])
        report = self.dir / "report.txt"
        code, out, err = run_cli(
            rzmc.main, ["check", str(path), "--debug-report",
                        str(report)])
        self.assertEqual(code, 0)
        self.assertTrue(report.exists())
        self.assertIn("debug report written", err)

    def test_check_without_debug_log_still_works(self):
        # The script copied alone, without debug_log.py: the
        # check still runs (the import is guarded), but a
        # debug report is a plain-words error, not a crash.
        alone = self.dir / "alone"
        alone.mkdir()
        shutil.copy2(TOOL_DIR / "release_zip_mode_checker.py",
                     alone / "release_zip_mode_checker.py")
        path = self.dir / "app.zip"
        make_zip(path, [unix_file("install.sh", mode=0o100755)])
        proc = subprocess.run(
            [sys.executable, "release_zip_mode_checker.py",
             "check", str(path)],
            cwd=str(alone), capture_output=True, text=True,
            timeout=60)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("OK:", proc.stdout)
        proc = subprocess.run(
            [sys.executable, "release_zip_mode_checker.py",
             "check", str(path), "--debug-report",
             str(self.dir / "report.txt")],
            cwd=str(alone), capture_output=True, text=True,
            timeout=60)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("debug_log.py", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_zip_stores_correct_modes(self):
        out = self.dir / "release-zip-mode-checker-v0.1.0.zip"
        proc = subprocess.run(
            [sys.executable, str(TOOL_DIR / "build_zip.py"),
             "--out", str(out)],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with zipfile.ZipFile(out) as zf:
            for info in zf.infolist():
                mode = rzmc.stored_mode(info)
                self.assertIsNotNone(
                    mode, "%s has no stored mode" % info.filename)
                if info.is_dir():
                    self.assertEqual(mode, 0o40755, info.filename)
                elif info.filename in (
                        "release_zip_mode_checker.py",
                        "run_tests.sh", "build_zip.py"):
                    self.assertEqual(mode, 0o100755, info.filename)
                else:
                    self.assertEqual(mode, 0o100644, info.filename)
        # The built zip passes its own check: run_tests.sh is
        # stored executable.
        result = rzmc.check_zip(str(out))
        self.assertTrue(result["ok"])

    def test_no_em_dashes_in_shipped_files(self):
        # The authoritative check: a python byte search. The
        # verbatim T21 debug_log.py is excluded by rule (it
        # carries 5 em-dash bytes of its own, unmodified).
        bad = []
        for path in sorted(TOOL_DIR.rglob("*")):
            if path.is_dir():
                continue
            if path.name in ("debug_log.py",):
                continue
            if path.suffix in (".pyc", ".zip"):
                continue
            if "__pycache__" in path.parts:
                continue
            if b"\xe2\x80\x94" in path.read_bytes():
                bad.append(str(path.relative_to(TOOL_DIR)))
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
