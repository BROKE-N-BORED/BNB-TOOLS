"""Suitability check tests: cards vs tasks, warnings, bad input.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from preloadchecks import suitability  # noqa: E402

GB = 1024 ** 3

CARD = {"name": "example-7b", "size_gb": 4.5,
        "capabilities": ["chat", "code"],
        "context_tokens": 32768}


class CheckTests(unittest.TestCase):
    def test_suitable_when_everything_fits(self):
        task = {"needs_capabilities": ["code"],
                "min_context_tokens": 8192,
                "max_size_gb": 6}
        ok, problems, warnings = suitability.check_suitability(
            CARD, task)
        self.assertTrue(ok)
        self.assertEqual(problems, [])
        self.assertEqual(warnings, [])

    def test_missing_capability_is_a_problem(self):
        task = {"needs_capabilities": ["vision"]}
        ok, problems, _warnings = suitability.check_suitability(
            CARD, task)
        self.assertFalse(ok)
        self.assertEqual(len(problems), 1)
        self.assertIn("vision", problems[0])
        self.assertIn("example-7b", problems[0])

    def test_capability_match_is_case_insensitive(self):
        task = {"needs_capabilities": ["CODE", "Chat"]}
        ok, problems, _warnings = suitability.check_suitability(
            CARD, task)
        self.assertTrue(ok)
        self.assertEqual(problems, [])

    def test_context_too_small_is_a_problem(self):
        task = {"min_context_tokens": 65536}
        ok, problems, _warnings = suitability.check_suitability(
            CARD, task)
        self.assertFalse(ok)
        self.assertIn("32768", problems[0])
        self.assertIn("65536", problems[0])

    def test_context_exactly_enough_passes(self):
        task = {"min_context_tokens": 32768}
        ok, _problems, _warnings = suitability.check_suitability(
            CARD, task)
        self.assertTrue(ok)

    def test_size_over_limit_is_a_problem(self):
        task = {"max_size_gb": 4}
        ok, problems, _warnings = suitability.check_suitability(
            CARD, task)
        self.assertFalse(ok)
        self.assertIn("4.5 GB", problems[0])

    def test_missing_fields_are_not_checked(self):
        # A card with no capabilities and no size, against an
        # empty task: nothing to check, so nothing blocks.
        ok, problems, warnings = suitability.check_suitability(
            {"name": "mystery"}, {})
        self.assertTrue(ok)
        self.assertEqual(problems, [])
        self.assertEqual(warnings, [])

    def test_missing_capabilities_warns_when_task_needs_them(self):
        ok, problems, warnings = suitability.check_suitability(
            {"name": "mystery"},
            {"needs_capabilities": ["code"]})
        self.assertTrue(ok)  # a warning, not a block
        self.assertEqual(problems, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("cannot prove", warnings[0])

    def test_missing_context_warns(self):
        card = dict(CARD)
        del card["context_tokens"]
        ok, _problems, warnings = suitability.check_suitability(
            card, {"min_context_tokens": 8192})
        self.assertTrue(ok)
        self.assertEqual(len(warnings), 1)
        self.assertIn("8192", warnings[0])

    def test_missing_size_warns(self):
        card = dict(CARD)
        del card["size_gb"]
        ok, _problems, warnings = suitability.check_suitability(
            card, {"max_size_gb": 6})
        self.assertTrue(ok)
        self.assertEqual(len(warnings), 1)

    def test_ram_check_blocks_when_model_will_not_fit(self):
        # 5 GB free, 4.5 GB model, 1 GB reserve: does not fit.
        ok, problems, _warnings = suitability.check_suitability(
            CARD, {}, available_bytes=5 * GB)
        self.assertFalse(ok)
        self.assertIn("will not fit in RAM", problems[0])

    def test_ram_check_passes_when_model_fits(self):
        ok, _problems, _warnings = suitability.check_suitability(
            CARD, {}, available_bytes=8 * GB)
        self.assertTrue(ok)

    def test_ram_check_skipped_without_size(self):
        card = dict(CARD)
        del card["size_gb"]
        ok, _problems, _warnings = suitability.check_suitability(
            card, {}, available_bytes=1 * GB)
        self.assertTrue(ok)

    def test_multiple_problems_all_reported(self):
        task = {"needs_capabilities": ["vision"],
                "min_context_tokens": 65536,
                "max_size_gb": 4}
        ok, problems, _warnings = suitability.check_suitability(
            CARD, task)
        self.assertFalse(ok)
        self.assertEqual(len(problems), 3)

    def test_bad_capability_types_raise(self):
        with self.assertRaises(suitability.BadInput):
            suitability.check_suitability(
                {"capabilities": "chat"}, {})
        with self.assertRaises(suitability.BadInput):
            suitability.check_suitability(
                CARD, {"needs_capabilities": "code"})

    def test_bad_number_types_raise(self):
        with self.assertRaises(suitability.BadInput):
            suitability.check_suitability(
                CARD, {"min_context_tokens": "lots"})
        with self.assertRaises(suitability.BadInput):
            suitability.check_suitability(
                {"context_tokens": True},
                {"min_context_tokens": 100})
        with self.assertRaises(suitability.BadInput):
            suitability.check_suitability(
                {"size_gb": "big"}, {"max_size_gb": 6})

    def test_unnamed_model_gets_plain_fallback(self):
        ok, problems, _warnings = suitability.check_suitability(
            {"capabilities": ["chat"]},
            {"needs_capabilities": ["code"]})
        self.assertFalse(ok)
        self.assertIn("this model", problems[0])


class LoadJsonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name, text):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_loads_valid_json(self):
        path = self._write("card.json", json.dumps(CARD))
        data = suitability.load_json_file(path, "model card")
        self.assertEqual(data["name"], "example-7b")

    def test_missing_file_is_plain_words(self):
        path = os.path.join(self.tmp.name, "nope.json")
        with self.assertRaises(suitability.BadInput) as ctx:
            suitability.load_json_file(path, "model card")
        self.assertIn("cannot read", str(ctx.exception))
        self.assertNotIn("Traceback", str(ctx.exception))

    def test_invalid_json_is_plain_words(self):
        path = self._write("bad.json", "{not json")
        with self.assertRaises(suitability.BadInput) as ctx:
            suitability.load_json_file(path, "model card")
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_non_object_is_plain_words(self):
        path = self._write("list.json", "[1, 2]")
        with self.assertRaises(suitability.BadInput) as ctx:
            suitability.load_json_file(path, "model card")
        self.assertIn("one JSON object", str(ctx.exception))


class ReportTests(unittest.TestCase):
    def test_suitable_report(self):
        text = suitability.plain_report("example-7b", True, [], [])
        self.assertIn("looks able to do this job", text)
        self.assertIn("You can load it", text)

    def test_unsuitable_report_lists_problems(self):
        text = suitability.plain_report(
            "example-7b", False,
            ["example-7b cannot do vision, and the task needs it."],
            [])
        self.assertIn("Do not load example-7b", text)
        self.assertIn("vision", text)
        self.assertIn("Pick a model", text)

    def test_warnings_come_first(self):
        text = suitability.plain_report(
            "mystery", True, [],
            ["The model card does not say what mystery can do."])
        self.assertTrue(text.startswith("Warning:"))
        self.assertIn("looks able", text)


if __name__ == "__main__":
    unittest.main()
