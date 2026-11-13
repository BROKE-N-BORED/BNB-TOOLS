"""Smoke tests for coverage_check.py — run from the tool folder:

    python3 -m unittest discover -s tests -v
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "coverage_check.py")
sys.path.insert(0, os.path.join(HERE, ".."))

import coverage_check  # noqa: E402


def write(tmp, name, text):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


FINDINGS = """\
# verdict findings
V-01: probe loads the base model twice
V-02: maternion typo in the README
V-03: torch.load pickle risk on import
"""

TASKS_CLEAN = """\
# Task list

## T11 — probe loads the base model twice
Covers: V-01

## T12 — maternion typo
Covers: V-02

## T13 — torch.load pickle risk
Covers: V-03
"""


class CoverageCheckTests(unittest.TestCase):
    def test_clean_merge_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "findings.txt", FINDINGS)
            t = write(tmp, "tasks.md", TASKS_CLEAN)
            result = coverage_check.check(f, t)
            self.assertTrue(result["pass"])
            self.assertEqual(result["findings_total"], 3)
            self.assertEqual(result["tasks_total"], 3)
            self.assertEqual(result["uncovered"], [])

    def test_uncovered_finding_fails_and_is_named(self):
        tasks = TASKS_CLEAN.replace("## T13 — torch.load pickle risk\nCovers: V-03\n", "")
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "findings.txt", FINDINGS)
            t = write(tmp, "tasks.md", tasks)
            result = coverage_check.check(f, t)
            self.assertFalse(result["pass"])
            self.assertEqual(result["uncovered"], ["V-03"])

    def test_unknown_reference_fails(self):
        tasks = TASKS_CLEAN + "\n## T14 — mystery\nCovers: V-99\n"
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "findings.txt", FINDINGS)
            t = write(tmp, "tasks.md", tasks)
            result = coverage_check.check(f, t)
            self.assertFalse(result["pass"])
            self.assertEqual(result["unknown_references"], {"T14": ["V-99"]})

    def test_duplicate_task_id_fails(self):
        tasks = TASKS_CLEAN + "\n## T11 — same ID again\nCovers: V-01\n"
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "findings.txt", FINDINGS)
            t = write(tmp, "tasks.md", tasks)
            result = coverage_check.check(f, t)
            self.assertFalse(result["pass"])
            self.assertEqual(result["duplicate_task_ids"], ["T11"])

    def test_double_coverage_passes(self):
        # Two tasks covering the same finding is allowed (a fold
        # recorded twice is untidy, not a dropped finding).
        tasks = TASKS_CLEAN + "\n## T14 — also fixes the typo\nCovers: V-02\n"
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "findings.txt", FINDINGS)
            t = write(tmp, "tasks.md", tasks)
            result = coverage_check.check(f, t)
            self.assertTrue(result["pass"])

    def test_empty_findings_file_is_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "findings.txt", "# nothing here\n\n")
            t = write(tmp, "tasks.md", TASKS_CLEAN)
            proc = subprocess.run(
                [sys.executable, TOOL, f, t],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertIn("no findings parsed", proc.stderr)

    def test_malformed_finding_line_warned_not_failed(self):
        findings = FINDINGS + "this line has no ID shape\n"
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "findings.txt", findings)
            t = write(tmp, "tasks.md", TASKS_CLEAN)
            result = coverage_check.check(f, t)
            self.assertTrue(result["pass"])
            self.assertEqual(len(result["warnings"]), 1)
            self.assertIn("no 'ID:' shape", result["warnings"][0])

    def test_json_output_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "findings.txt", FINDINGS)
            t = write(tmp, "tasks.md", TASKS_CLEAN)
            proc = subprocess.run(
                [sys.executable, TOOL, f, t, "--json"],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(proc.returncode, 0)
            data = json.loads(proc.stdout)
            self.assertTrue(data["pass"])
            self.assertEqual(data["findings_total"], 3)
            self.assertEqual(data["uncovered"], [])

    def test_no_tasks_all_uncovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "findings.txt", FINDINGS)
            t = write(tmp, "tasks.md", "# Task list\n\nNothing here yet.\n")
            result = coverage_check.check(f, t)
            self.assertFalse(result["pass"])
            self.assertEqual(result["uncovered"], ["V-01", "V-02", "V-03"])

    def test_covers_mixed_separators(self):
        tasks = "# Task list\n\n## T1 — everything\nCovers: V-01,V-02 V-03\n"
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "findings.txt", FINDINGS)
            t = write(tmp, "tasks.md", tasks)
            result = coverage_check.check(f, t)
            self.assertTrue(result["pass"])
            self.assertEqual(result["covered"], ["V-01", "V-02", "V-03"])

    def test_duplicate_finding_id_fails(self):
        findings = FINDINGS + "V-01: same ID, different words\n"
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "findings.txt", findings)
            t = write(tmp, "tasks.md", TASKS_CLEAN)
            result = coverage_check.check(f, t)
            self.assertFalse(result["pass"])
            self.assertEqual(result["duplicate_finding_ids"], ["V-01"])

    def test_cli_exit_code_fail(self):
        tasks = "# Task list\n\n## T1 — only one\nCovers: V-01\n"
        with tempfile.TemporaryDirectory() as tmp:
            f = write(tmp, "findings.txt", FINDINGS)
            t = write(tmp, "tasks.md", tasks)
            proc = subprocess.run(
                [sys.executable, TOOL, f, t],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("V-02", proc.stdout)
            self.assertIn("FAIL", proc.stdout)


if __name__ == "__main__":
    unittest.main()
