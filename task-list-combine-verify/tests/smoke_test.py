#!/usr/bin/env python3
"""Smoke test for combine_verify.py. No network, stdlib only.

Builds small fixture lists in the shape of the real combine that proved
this tool's worth (six security-cluster audits combined into one list)
and asserts the checker passes the good combine and catches each defect
class: an untraced source task, a duplicated combined id, a gap in the
id sequence, a reference to an unknown source task, a bad tier, a
skipped tier, a combined entry covering nothing, and a source task
traced twice. Also runs the CLI end to end on temp files.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from combine_verify import check, main  # noqa: E402

PASSED = 0


def ok(condition, label):
    global PASSED
    assert condition, f"FAILED: {label}"
    PASSED += 1
    print(f"  ok: {label}")


def good_fixtures():
    """3 source lists, 12 source tasks -> 10 combined entries (2 deduped)."""
    sources = [
        {"name": "S2-secrets", "tasks": [
            {"id": "S2-T1", "title": "rclone protection"},
            {"id": "S2-T2", "title": "history scrub"},
            {"id": "S2-T3", "title": "startup health check"},
            {"id": "S2-T4", "title": "vault perms"},
        ]},
        {"name": "S3-channels", "tasks": [
            {"id": "S3-T1", "title": "trust-dialog re-entrancy guard"},
            {"id": "S3-T2", "title": "hooks containment"},
            {"id": "S3-T3", "title": "dialog copy"},
            {"id": "S3-T4", "title": "scheduler stacking"},
        ]},
        {"name": "S4-deck", "tasks": [
            {"id": "S4-T1", "title": "honest deck copy"},
            {"id": "S4-T2", "title": "filename sanitization"},
            {"id": "S4-T3", "title": "deck-feed scrub"},
            {"id": "S4-T4", "title": "auth-failure visibility"},
        ]},
    ]
    combined = [
        {"id": "C1", "title": "rclone protection", "tier": "P0",
         "status": "in flight", "sources": ["S2-T1"]},
        {"id": "C2", "title": "trust-dialog re-entrancy guard", "tier": "P0",
         "status": "queued", "sources": ["S3-T1", "S3-T4"]},
        {"id": "C3", "title": "filename sanitization", "tier": "P0",
         "status": "not started", "sources": ["S4-T2"]},
        {"id": "C4", "title": "history scrub", "tier": "P1",
         "status": "not started", "sources": ["S2-T2"]},
        {"id": "C5", "title": "hooks containment", "tier": "P1",
         "status": "not started", "sources": ["S3-T2"]},
        {"id": "C6", "title": "deck-feed scrub", "tier": "P1",
         "status": "not started", "sources": ["S4-T3"]},
        {"id": "C7", "title": "startup health check", "tier": "P2",
         "status": "not started", "sources": ["S2-T3"]},
        {"id": "C8", "title": "vault perms", "tier": "P2",
         "status": "not started", "sources": ["S2-T4"]},
        {"id": "C9", "title": "dialog copy", "tier": "P2",
         "status": "not started", "sources": ["S3-T3"]},
        {"id": "C10", "title": "deck copy + auth visibility", "tier": "P2",
         "status": "not started", "sources": ["S4-T1", "S4-T4"]},
    ]
    return sources, combined


def test_good_combine_passes():
    sources, combined = good_fixtures()
    failures, summary = check(sources, combined)
    ok(failures == [], "good combine passes with no failures")
    ok(summary["source_tasks"] == 12, "summary counts 12 source tasks")
    ok(summary["combined_entries"] == 10, "summary counts 10 combined entries")
    ok(summary["traced"] == 12, "summary counts 12 traced tasks")
    ok(summary["tiers"] == {"P0": 3, "P1": 3, "P2": 4},
       "tier counts are P0=3, P1=3, P2=4")
    ok(summary["statuses"]["in flight"] == 1
       and summary["statuses"]["queued"] == 1
       and summary["statuses"]["not started"] == 8,
       "status counts add up (1 in flight, 1 queued, 8 not started)")


def test_untraced_source_task():
    sources, combined = good_fixtures()
    combined[6]["sources"] = []  # C7 covers nothing; S2-T3 untraced
    failures, _ = check(sources, combined)
    ok(any("S2-T3" in f and "no combined entry" in f for f in failures),
       "untraced source task is named")
    ok(any("C7" in f and "no source task" in f for f in failures),
       "combined entry covering nothing is named")


def test_duplicate_combined_id():
    sources, combined = good_fixtures()
    combined[1]["id"] = "C1"
    failures, _ = check(sources, combined)
    ok(any("C1" in f and "twice" in f for f in failures),
       "duplicated combined id is caught")


def test_gap_in_id_sequence():
    sources, combined = good_fixtures()
    combined[4]["id"] = "C11"  # C5 missing, C11 past the count
    failures, _ = check(sources, combined)
    ok(any("missing C5" in f for f in failures),
       "missing id in the sequence is named")
    ok(any("unexpected C11" in f for f in failures),
       "id past the count is named")


def test_unknown_source_reference():
    sources, combined = good_fixtures()
    combined[0]["sources"] = ["S9-T99"]
    failures, _ = check(sources, combined)
    ok(any("S9-T99" in f and "unknown" in f for f in failures),
       "reference to an unknown source task is caught")


def test_source_traced_twice():
    sources, combined = good_fixtures()
    combined[1]["sources"] = ["S3-T1", "S3-T4", "S2-T1"]  # S2-T1 also in C1
    failures, _ = check(sources, combined)
    ok(any("S2-T1" in f and "both" in f for f in failures),
       "source task traced to two entries is caught")


def test_bad_tier_and_skipped_tier():
    sources, combined = good_fixtures()
    combined[3]["tier"] = "P9"
    failures, _ = check(sources, combined)
    ok(any("P9" in f for f in failures), "invalid tier value is caught")

    sources, combined = good_fixtures()
    for entry in combined:
        if entry["tier"] == "P1":
            entry["tier"] = "P2"  # P1 gone, P0+P2 remain: tier skipped
    failures, _ = check(sources, combined)
    ok(any("not contiguous" in f for f in failures),
       "skipped tier is caught")


def test_bad_status():
    sources, combined = good_fixtures()
    combined[0]["status"] = "almost done"
    failures, _ = check(sources, combined)
    ok(any("almost done" in f for f in failures),
       "invalid status value is caught")


def test_duplicate_source_id():
    sources, combined = good_fixtures()
    sources[1]["tasks"][0]["id"] = "S2-T1"  # collides with S2's T1
    failures, _ = check(sources, combined)
    ok(any("S2-T1" in f and "both" in f for f in failures),
       "source id appearing in two lists is caught")


def test_cli_end_to_end():
    sources, combined = good_fixtures()
    with tempfile.TemporaryDirectory() as tmp:
        src_path = Path(tmp) / "sources.json"
        cmb_path = Path(tmp) / "combined.json"
        src_path.write_text(json.dumps(sources), encoding="utf-8")
        cmb_path.write_text(json.dumps(combined), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(HERE.parent / "combine_verify.py"),
             "--sources", str(src_path), "--combined", str(cmb_path)],
            capture_output=True, text=True)
        ok(proc.returncode == 0, "CLI exits 0 on the good combine")
        ok("PASS" in proc.stdout, "CLI prints PASS on the good combine")

        bad = [dict(e) for e in combined]
        bad[0] = dict(bad[0], sources=["S9-T99"])
        cmb_path.write_text(json.dumps(bad), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(HERE.parent / "combine_verify.py"),
             "--sources", str(src_path), "--combined", str(cmb_path)],
            capture_output=True, text=True)
        ok(proc.returncode == 1, "CLI exits 1 on the bad combine")
        ok("FAIL" in proc.stdout and "S9-T99" in proc.stdout,
           "CLI names the failure on the bad combine")

        proc = subprocess.run(
            [sys.executable, str(HERE.parent / "combine_verify.py"),
             "--sources", str(Path(tmp) / "missing.json"),
             "--combined", str(cmb_path)],
            capture_output=True, text=True)
        ok(proc.returncode == 2, "CLI exits 2 when an input is unreadable")


def main():
    tests = [
        test_good_combine_passes,
        test_untraced_source_task,
        test_duplicate_combined_id,
        test_gap_in_id_sequence,
        test_unknown_source_reference,
        test_source_traced_twice,
        test_bad_tier_and_skipped_tier,
        test_bad_status,
        test_duplicate_source_id,
        test_cli_end_to_end,
    ]
    for test in tests:
        print(f"{test.__name__}:")
        test()
    print(f"\n{PASSED}/{PASSED} smoke checks OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
