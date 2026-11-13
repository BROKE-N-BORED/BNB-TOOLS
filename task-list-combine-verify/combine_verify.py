#!/usr/bin/env python3
"""Verify a combined task list against the source lists it was built from.

When several per-item audits each produce their own task list, the lists get
combined into one prioritized list (dedupe, re-tier, re-number). This checker
proves the combine lost nothing and invented nothing:

- every source task is traced to exactly one combined entry;
- every combined entry references only source tasks that exist;
- combined IDs are unique and contiguous (prefix + 1..N, no gaps);
- every tier value is one of the allowed tiers and no tier is skipped
  (e.g. P0/P1/P2 with all three present, in order);
- status counts add up to the combined total.

Input format (JSON). Sources file: a list of source lists, each with a
"name" and "tasks" (each task: "id", "title"; optional "tier", "status").
Combined file: a list of entries, each with "id", "title", "tier",
"status", and "sources" (list of source task ids it covers).

Exit code 0 = all checks pass. Exit code 1 = at least one check failed,
with every failure named on stdout. Exit code 2 = the inputs could not
be read or parsed.

Pairs with BNB SKILLS audit-each-one-combine (the workflow that produces
the combined list this tool checks).
"""

import argparse
import json
import re
import sys

ALLOWED_TIERS = ("P0", "P1", "P2")
ALLOWED_STATUSES = ("not started", "queued", "in flight", "done", "blocked")


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def check(sources_data, combined_data, id_prefix="C"):
    """Run every check. Returns (failures, summary dict)."""
    failures = []

    # --- gather source tasks -------------------------------------------------
    source_ids = {}
    for src in sources_data:
        name = src.get("name", "?")
        for task in src.get("tasks", []):
            tid = task.get("id")
            if tid is None:
                failures.append(f"source list {name!r}: a task has no id")
                continue
            if tid in source_ids:
                failures.append(
                    f"source task id {tid!r} appears in both "
                    f"{source_ids[tid]!r} and {name!r}"
                )
            source_ids[tid] = name
    n_sources = len(source_ids)

    # --- combined ids: unique, contiguous ------------------------------------
    seen = {}
    id_re = re.compile(r"^" + re.escape(id_prefix) + r"(\d+)$")
    numbers = []
    for entry in combined_data:
        eid = entry.get("id")
        if eid is None:
            failures.append("combined entry has no id")
            continue
        if eid in seen:
            failures.append(f"combined id {eid!r} appears twice")
        seen[eid] = True
        m = id_re.match(str(eid))
        if not m:
            failures.append(
                f"combined id {eid!r} does not match {id_prefix}N numbering"
            )
        else:
            numbers.append(int(m.group(1)))
    if numbers:
        numbers.sort()
        expected = list(range(1, len(numbers) + 1))
        if numbers != expected:
            missing = sorted(set(expected) - set(numbers))
            extra = sorted(set(numbers) - set(expected))
            if missing:
                failures.append(
                    f"combined ids skip numbers: missing "
                    + ", ".join(f"{id_prefix}{n}" for n in missing)
                )
            if extra:
                failures.append(
                    f"combined ids run past the count: unexpected "
                    + ", ".join(f"{id_prefix}{n}" for n in extra)
                )

    # --- traceability ---------------------------------------------------------
    traced = {}
    for entry in combined_data:
        for sid in entry.get("sources", []):
            if sid not in source_ids:
                failures.append(
                    f"combined {entry.get('id')!r} references unknown "
                    f"source task {sid!r}"
                )
            elif sid in traced:
                failures.append(
                    f"source task {sid!r} is traced to both "
                    f"{traced[sid]!r} and {entry.get('id')!r}"
                )
            traced[sid] = entry.get("id")
    untraced = sorted(set(source_ids) - set(traced))
    if untraced:
        failures.append(
            f"{len(untraced)} source task(s) traced to no combined entry: "
            + ", ".join(untraced[:10])
            + (" ..." if len(untraced) > 10 else "")
        )
    for entry in combined_data:
        if not entry.get("sources"):
            failures.append(
                f"combined {entry.get('id')!r} covers no source task "
                "(invented entry?)"
            )

    # --- tiers: valid values, none skipped ------------------------------------
    tiers_seen = []
    for entry in combined_data:
        tier = entry.get("tier")
        if tier not in ALLOWED_TIERS:
            failures.append(
                f"combined {entry.get('id')!r} has tier {tier!r}, "
                f"expected one of {', '.join(ALLOWED_TIERS)}"
            )
        elif tier not in tiers_seen:
            tiers_seen.append(tier)
    if tiers_seen:
        highest = max(ALLOWED_TIERS.index(t) for t in tiers_seen)
        expected_tiers = list(ALLOWED_TIERS[: highest + 1])
        if sorted(tiers_seen, key=ALLOWED_TIERS.index) != expected_tiers:
            failures.append(
                "tiers are not contiguous: present "
                + ", ".join(sorted(tiers_seen, key=ALLOWED_TIERS.index))
                + f", expected {', '.join(expected_tiers)}"
            )

    # --- statuses: valid values, counts sum -----------------------------------
    status_counts = {}
    for entry in combined_data:
        status = entry.get("status")
        if status not in ALLOWED_STATUSES:
            failures.append(
                f"combined {entry.get('id')!r} has status {status!r}, "
                f"expected one of {', '.join(ALLOWED_STATUSES)}"
            )
        else:
            status_counts[status] = status_counts.get(status, 0) + 1
    if sum(status_counts.values()) != len(combined_data):
        failures.append("status counts do not add up to the combined total")

    summary = {
        "source_tasks": n_sources,
        "combined_entries": len(combined_data),
        "traced": len(traced),
        "tiers": {t: sum(1 for e in combined_data if e.get("tier") == t)
                  for t in ALLOWED_TIERS},
        "statuses": status_counts,
    }
    return failures, summary


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Verify a combined task list against its source lists."
    )
    parser.add_argument("--sources", required=True,
                        help="JSON file: list of source lists")
    parser.add_argument("--combined", required=True,
                        help="JSON file: combined task list")
    parser.add_argument("--id-prefix", default="C",
                        help="combined id prefix (default: C)")
    args = parser.parse_args(argv)

    try:
        sources_data = load_json(args.sources)
        combined_data = load_json(args.combined)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: could not read inputs: {exc}")
        return 2
    if not isinstance(sources_data, list) or not isinstance(combined_data, list):
        print("ERROR: both inputs must be JSON lists")
        return 2

    failures, summary = check(sources_data, combined_data, args.id_prefix)
    print(f"source tasks: {summary['source_tasks']}, "
          f"combined entries: {summary['combined_entries']}, "
          f"traced: {summary['traced']}")
    print("tiers: " + ", ".join(
        f"{t}={summary['tiers'][t]}" for t in ALLOWED_TIERS))
    print("statuses: " + ", ".join(
        f"{s}={n}" for s, n in sorted(summary["statuses"].items())))
    if failures:
        print(f"\nFAIL: {len(failures)} problem(s)")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("\nPASS: every source task traced exactly once, ids contiguous, "
          "tiers contiguous, statuses add up")
    return 0


if __name__ == "__main__":
    sys.exit(main())
