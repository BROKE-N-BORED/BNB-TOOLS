#!/usr/bin/env python3
"""T16 — token-burn-rate-tracker (pairs with BNB SKILLS S40).

Baseline snapshot -> scheduled recheck -> tokens/day + pool-lifetime
estimate. For any metered resource, but built for the 1-billion-token pool
case: record a baseline (Oct 31), recheck days later (Nov 3), compute the
burn rate and how long the pool lasts at the measured pace.

    snapshot  record date + total tokens used + pool size + source note
              into a JSON log
    report    tokens/day since baseline, per-day breakdown between
              snapshots, remaining-pool lifetime at the measured pace

Caveat, printed on every report: the pool may still be untouched if the
weekly limit hasn't been exhausted — the tracker measures what the
snapshots say, and says plainly when the numbers imply no pool draw yet.

No network. The log is a plain JSON file (default: token-log.json next to
the script; override with --log).

Usage:
    token_tracker.py snapshot --used 123456789 --pool 1000000000 \\
        --source "subscription status page" --date 2026-10-31
    token_tracker.py snapshot --used 162800000 --pool 1000000000
    token_tracker.py report
    token_tracker.py report --json
    token_tracker.py list

Exit 0 = done, 1 = bad input / not enough snapshots for a report.
"""
import argparse
import datetime
import json
import os
import sys

DEFAULT_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "token-log.json")

CAVEAT = ("CAVEAT: the pool may still be untouched if the weekly limit "
          "hasn't been exhausted — these numbers measure what the "
          "snapshots say, not the pool's internal state.")


def today():
    return datetime.date.today().isoformat()


def parse_date(s):
    return datetime.date.fromisoformat(s)


def load_log(path):
    if not os.path.isfile(path):
        return {"snapshots": []}
    with open(path) as f:
        data = json.load(f)
    if "snapshots" not in data:
        raise ValueError("log file %s has no 'snapshots' key" % path)
    return data


def save_log(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def add_snapshot(path, used, pool, source, date):
    data = load_log(path)
    snap = {"date": date, "used_total": used, "pool_size": pool,
            "source": source or ""}
    data["snapshots"].append(snap)
    data["snapshots"].sort(key=lambda s: s["date"])
    save_log(path, data)
    return snap


def compute_report(data):
    snaps = data["snapshots"]
    if len(snaps) < 2:
        raise ValueError("need at least 2 snapshots for a report "
                         "(have %d)" % len(snaps))
    first, last = snaps[0], snaps[-1]
    d0, d1 = parse_date(first["date"]), parse_date(last["date"])
    days = (d1 - d0).days
    if days <= 0:
        raise ValueError("snapshots span %d days — need snapshots on "
                         "different dates" % days)
    used_delta = last["used_total"] - first["used_total"]
    per_day = used_delta / days
    pool = last["pool_size"]
    remaining = pool - last["used_total"]
    lifetime_days = (remaining / per_day) if per_day > 0 else None
    # Per-day breakdown between consecutive snapshots.
    legs = []
    for a, b in zip(snaps, snaps[1:]):
        span = (parse_date(b["date"]) - parse_date(a["date"])).days
        delta = b["used_total"] - a["used_total"]
        legs.append({
            "from": a["date"], "to": b["date"], "days": span,
            "used_delta": delta,
            "per_day": (delta / span) if span > 0 else None,
        })
    return {
        "baseline": first, "latest": last, "days": days,
        "used_delta": used_delta, "per_day": per_day,
        "pool_size": pool, "remaining": remaining,
        "lifetime_days": lifetime_days,
        "legs": legs,
    }


def fmt(n):
    return "{:,}".format(n)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Token burn-rate tracker: snapshot usage, report "
                    "tokens/day + pool lifetime.")
    ap.add_argument("--log", default=DEFAULT_LOG,
                    help="JSON log file (default: token-log.json next to "
                         "the script)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("snapshot", help="record a usage snapshot")
    p.add_argument("--used", type=int, required=True,
                   help="total tokens used so far")
    p.add_argument("--pool", type=int, required=True,
                   help="pool size in tokens")
    p.add_argument("--source", default="",
                   help="where the numbers came from (e.g. 'subscription "
                        "status page')")
    p.add_argument("--date", default=today(),
                   help="snapshot date YYYY-MM-DD (default: today)")

    p = sub.add_parser("report", help="burn rate + lifetime report")
    p.add_argument("--json", action="store_true")

    sub.add_parser("list", help="list all snapshots")

    args = ap.parse_args(argv)

    if args.cmd == "snapshot":
        try:
            parse_date(args.date)
        except ValueError:
            print("error: bad date %r (want YYYY-MM-DD)" % args.date,
                  file=sys.stderr)
            return 1
        snap = add_snapshot(args.log, args.used, args.pool,
                            args.source, args.date)
        print("snapshot recorded: %s used=%s pool=%s source=%r"
              % (snap["date"], fmt(snap["used_total"]),
                 fmt(snap["pool_size"]), snap["source"]))
        return 0

    if args.cmd == "list":
        data = load_log(args.log)
        if not data["snapshots"]:
            print("no snapshots in %s" % args.log)
            return 0
        for s in data["snapshots"]:
            print("%s  used=%s  pool=%s  %s"
                  % (s["date"], fmt(s["used_total"]),
                     fmt(s["pool_size"]), s.get("source", "")))
        return 0

    # report
    try:
        data = load_log(args.log)
        rep = compute_report(data)
    except (ValueError, KeyError, OSError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(rep, indent=2))
        return 0
    print("TOKEN BURN-RATE REPORT")
    print("-" * 60)
    print("baseline: %s  used=%s"
          % (rep["baseline"]["date"], fmt(rep["baseline"]["used_total"])))
    print("latest:   %s  used=%s"
          % (rep["latest"]["date"], fmt(rep["latest"]["used_total"])))
    print("span:     %d days, +%s tokens"
          % (rep["days"], fmt(rep["used_delta"])))
    print()
    print("per-day breakdown:")
    for leg in rep["legs"]:
        print("  %s -> %s: %d day(s), +%s tokens, %s/day"
              % (leg["from"], leg["to"], leg["days"],
                 fmt(leg["used_delta"]),
                 fmt(round(leg["per_day"])) if leg["per_day"] is not None
                 else "n/a"))
    print()
    print("burn rate: %.1f tokens/day (%s/day)"
          % (rep["per_day"], fmt(round(rep["per_day"]))))
    print("pool: %s tokens, %s remaining"
          % (fmt(rep["pool_size"]), fmt(rep["remaining"])))
    if rep["lifetime_days"] is None:
        print("lifetime: usage is flat (0/day) — pool not draining at the "
              "measured pace")
    else:
        end = parse_date(rep["latest"]["date"]) + datetime.timedelta(
            days=int(rep["lifetime_days"]))
        print("lifetime at measured pace: %.1f days (pool runs out ~%s)"
              % (rep["lifetime_days"], end.isoformat()))
    print()
    print(CAVEAT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
