"""Export tests: CSV and JSON tables from result dicts."""

import csv
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from songkey.export import (COLUMNS, table_rows, to_csv, to_json,  # noqa: E402
                            write_csv, write_json)

SAMPLE_RESULTS = [
    {"path": "/music/one.wav", "file": "one.wav", "bpm": 120.1,
     "bpm_confidence": "high", "tempo_bpm": 120.4, "key": "A minor",
     "key_confidence": "high", "key_score": 0.93, "key_margin": 0.314,
     "key_runner_up": "C major", "duration": 30.0, "error": None},
    {"path": "/music/two.wav", "file": "two.wav", "bpm": None,
     "bpm_confidence": "unknown", "tempo_bpm": 121.0,
     "key": None, "key_confidence": "unknown", "key_score": 0.21,
     "key_margin": 0.05, "key_runner_up": None, "duration": 8.0,
     "error": None},
]


class ExportTests(unittest.TestCase):
    def test_csv_header_and_rows(self):
        text = to_csv(SAMPLE_RESULTS)
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0], list(COLUMNS))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1][0], "one.wav")
        self.assertEqual(rows[1][1], "120.1")
        self.assertEqual(rows[1][3], "A minor")
        self.assertEqual(rows[2][0], "two.wav")

    def test_csv_unknown_values_are_empty_cells(self):
        text = to_csv(SAMPLE_RESULTS)
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[2][1], "")
        self.assertEqual(rows[2][3], "")
        self.assertEqual(rows[2][5], "")

    def test_csv_round_trips(self):
        text = to_csv(SAMPLE_RESULTS)
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[1][6], "30.0")
        self.assertEqual(rows[2][6], "8.0")

    def test_json_table_parses_and_matches(self):
        rows = json.loads(to_json(SAMPLE_RESULTS))
        self.assertEqual(len(rows), 2)
        self.assertEqual(set(rows[0]), set(COLUMNS))
        self.assertEqual(rows[0]["file"], "one.wav")
        self.assertEqual(rows[0]["bpm"], 120.1)
        self.assertEqual(rows[0]["key"], "A minor")
        self.assertEqual(rows[0]["key_runner_up"], "C major")
        self.assertIsNone(rows[1]["bpm"])
        self.assertIsNone(rows[1]["key"])
        self.assertEqual(rows[1]["duration"], 8.0)

    def test_table_rows_only_carry_table_columns(self):
        rows = table_rows(SAMPLE_RESULTS)
        for row in rows:
            self.assertEqual(set(row), set(COLUMNS))

    def test_write_csv_and_json_to_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = os.path.join(tmp, "table.csv")
            json_path = os.path.join(tmp, "table.json")
            write_csv(SAMPLE_RESULTS, csv_path)
            write_json(SAMPLE_RESULTS, json_path)
            with open(csv_path, encoding="utf-8") as fh:
                rows = list(csv.reader(fh))
            self.assertEqual(rows[0], list(COLUMNS))
            self.assertEqual(len(rows), 3)
            with open(json_path, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 2)
            self.assertEqual(data[0]["file"], "one.wav")


if __name__ == "__main__":
    unittest.main()
