"""Export analysis results as a CSV table or a JSON table.

Both tables carry the same columns: file, bpm, bpm_confidence,
key, key_confidence, key_runner_up, duration. Unknown values are
empty cells in CSV and null in JSON. CSV is written with the
plain csv module, UTF-8, with a header row.
"""

import csv
import io
import json

COLUMNS = ("file", "bpm", "bpm_confidence", "key",
           "key_confidence", "key_runner_up", "duration")


def table_rows(results):
    """Results as a list of plain dicts with the table columns."""
    rows = []
    for result in results:
        rows.append({column: result.get(column) for column in COLUMNS})
    return rows


def to_csv(results):
    """Results as CSV text (header row, one row per result)."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(COLUMNS)
    for row in table_rows(results):
        writer.writerow([
            "" if row[column] is None else row[column]
            for column in COLUMNS
        ])
    return buffer.getvalue()


def to_json(results):
    """Results as indented JSON text (a list of row dicts)."""
    return json.dumps(table_rows(results), indent=2) + "\n"


def write_csv(results, path):
    """Write the CSV table to a file (UTF-8)."""
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(to_csv(results))


def write_json(results, path):
    """Write the JSON table to a file (UTF-8)."""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(to_json(results))
