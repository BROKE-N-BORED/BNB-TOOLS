#!/usr/bin/env python3
"""T5 model-sweep-harness — scripted benchmark/compat table builder.

Pairs with skill S13 (model sweep + roster audit, hardware-graded).
Takes a JSON list of model candidates and produces a graded Markdown
table + ranked trial list with exact pull tags.

Vendor benchmarks are flagged as UNREPRODUCED — they come from the
vendor's own card, not from a run on the target machine, and must
never be presented as measured fact.

RAM ceiling: models whose size exceeds the machine's usable RAM
(default 8 GB, configurable with --ram-gb) are flagged OVER CEILING
and excluded from the trial list — they cannot load on the machine.

Candidate JSON format (see candidates.sample.json):
{
  "machine": {"ram_gb": 8, "cpu_only": true},
  "candidates": [
    {"name": "qwen3-vl", "tag": "qwen3-vl:2b-instruct",
     "params_b": 2, "quant": "Q4_K_M", "size_gb": 1.9,
     "licence": "Apache-2.0",
     "runtimes": ["ollama", "llama.cpp"],
     "seats": ["vision"],
     "vendor_benchmarks": [
       {"name": "MMMU", "score": 62.1, "source": "vendor model card"}],
     "notes": "vision seat"}
  ]
}

Grading: each candidate gets a grade (A/B/C/D) from fit + licence +
evidence, and a verdict (TRIAL / WATCH / REJECT with reason). No
network needed — everything comes from the input file.

Stdlib only. Python 3.8+.
"""
import argparse
import json
import os
import sys

OPEN_LICENCES = {"apache-2.0", "mit", "bsd-3-clause", "bsd-2-clause",
                 "cc-by-4.0", "mpl-2.0", "gpl-3.0", "lgpl-3.0"}


def grade_candidate(c, ram_gb):
    """Return (grade, verdict, reasons)."""
    reasons = []
    size = c.get("size_gb")
    over = size is not None and size > ram_gb
    if over:
        reasons.append(f"OVER CEILING: {size} GB > {ram_gb} GB RAM")
    licence = (c.get("licence") or "unknown").lower()
    open_lic = licence in OPEN_LICENCES
    if not open_lic:
        reasons.append(f"licence {c.get('licence') or 'unknown'} is not "
                       "a recognised open licence")
    runtimes = c.get("runtimes") or []
    if not runtimes:
        reasons.append("no runtime compat listed")
    benches = c.get("vendor_benchmarks") or []
    if not benches:
        reasons.append("no vendor benchmarks listed")
    if over:
        return ("D", "REJECT", reasons)
    if not runtimes:
        return ("D", "REJECT", reasons)
    if not open_lic and not benches:
        return ("C", "WATCH", reasons)
    if not open_lic:
        return ("B", "TRIAL", reasons)
    if not benches:
        return ("B", "TRIAL", reasons)
    return ("A", "TRIAL", reasons)


def render_table(candidates, ram_gb):
    lines = [
        "# Model sweep — graded table",
        "",
        f"Machine: {ram_gb} GB RAM ceiling, CPU-only. "
        "Vendor benchmarks are UNREPRODUCED (vendor's own numbers, "
        "not measured on this machine).",
        "",
        "| Model | Params | Quant | Size | Licence | Runtimes | "
        "Vendor benchmarks (unreproduced) | Grade | Verdict |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for c in candidates:
        size = c.get("size_gb")
        size_s = f"{size} GB" + (" ⚠ OVER" if size and size > ram_gb else "")
        benches = c.get("vendor_benchmarks") or []
        bench_s = "; ".join(f"{b['name']} {b['score']}" for b in benches) \
            or "—"
        grade, verdict, _ = grade_candidate(c, ram_gb)
        lines.append(
            f"| {c.get('name','?')} | {c.get('params_b','?')}B | "
            f"{c.get('quant','?')} | {size_s} | {c.get('licence','?')} | "
            f"{', '.join(c.get('runtimes') or ['?'])} | {bench_s} | "
            f"{grade} | {verdict} |")
    return "\n".join(lines)


def render_trial_list(candidates, ram_gb):
    trials = []
    for c in candidates:
        grade, verdict, reasons = grade_candidate(c, ram_gb)
        if verdict == "TRIAL":
            trials.append((grade, c, reasons))
    trials.sort(key=lambda t: (t[0], -(t[1].get("size_gb") or 0)))
    lines = ["", "## Ranked trial list", ""]
    if not trials:
        lines.append("No candidates cleared the bar for a trial.")
        return "\n".join(lines)
    for i, (grade, c, reasons) in enumerate(trials, 1):
        tag = c.get("tag") or c.get("name")
        lines.append(f"{i}. **{c.get('name')}** (grade {grade}) — "
                     f"`ollama pull {tag}`")
        seats = c.get("seats") or []
        if seats:
            lines[-1] += f" — seat(s): {', '.join(seats)}"
        if c.get("notes"):
            lines.append(f"   {c['notes']}")
        for r in reasons:
            lines.append(f"   - note: {r}")
    return "\n".join(lines)


def render_rejects(candidates, ram_gb):
    lines = ["", "## Rejects (do not re-propose without new evidence)", ""]
    any_reject = False
    for c in candidates:
        grade, verdict, reasons = grade_candidate(c, ram_gb)
        if verdict == "REJECT":
            any_reject = True
            lines.append(f"- **{c.get('name')}**: {'; '.join(reasons)}")
    if not any_reject:
        lines.append("None.")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="sweep.py",
        description="Grade model candidates against the machine and "
                    "emit a Markdown sweep table + ranked trial list.")
    ap.add_argument("candidates", help="JSON candidates file")
    ap.add_argument("--ram-gb", type=float, default=None,
                    help="RAM ceiling in GB (default: from the file's "
                         "machine.ram_gb, else 8)")
    ap.add_argument("--out", default=None,
                    help="write the Markdown report here (default: stdout)")
    args = ap.parse_args(argv)
    with open(args.candidates, encoding="utf-8") as f:
        data = json.load(f)
    candidates = data.get("candidates", [])
    ram_gb = args.ram_gb
    if ram_gb is None:
        ram_gb = (data.get("machine") or {}).get("ram_gb", 8)
    if not candidates:
        print("error: no candidates in file", file=sys.stderr)
        return 1
    report = "\n".join([
        render_table(candidates, ram_gb),
        render_trial_list(candidates, ram_gb),
        render_rejects(candidates, ram_gb),
        "",
    ])
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"report -> {args.out}")
    else:
        print(report)
    n_trial = sum(1 for c in candidates
                  if grade_candidate(c, ram_gb)[1] == "TRIAL")
    n_reject = sum(1 for c in candidates
                   if grade_candidate(c, ram_gb)[1] == "REJECT")
    n_over = sum(1 for c in candidates
                 if (c.get("size_gb") or 0) > ram_gb)
    print(f"{len(candidates)} candidates: {n_trial} trial, "
          f"{n_reject} reject, {n_over} over the {ram_gb} GB ceiling",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
