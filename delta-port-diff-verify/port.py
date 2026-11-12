#!/usr/bin/env python3
"""T2 delta-port-diff-verify — port only the marked delta from an isolated
source copy into the live tree, then verify the merge.

Generalizes ~/workspace/forge-queue-verify/port_queue.py (a one-off,
hand-written port script) and port-spec.md (its hunk table) into a
data-driven tool: the port is described by a JSON port spec, not code.

Port spec format (JSON):
{
  "files": [
    {"path": "pkg/new_module.py", "mode": "whole"},
    {"path": "pkg/main.py", "mode": "anchor", "ops": [
      {"action": "insert_after", "anchor": "self._phone_queue_ws = []",
       "source_lines": [14191, 14227]},
      {"action": "replace", "anchor": "self.send_btn.setEnabled(True)",
       "source_lines": [21773, 21773], "count": 1},
      {"action": "insert_before", "anchor": "def send_message(self):",
       "source_lines": [20897, 20913]},
      {"action": "delete", "anchor": "self.send_btn.setEnabled(False)",
       "count": 1}
    ]}
  ],
  "untouched": ["pkg/providers.py"],
  "markers": {"pkg/main.py": {"_message_queue": 12}}
}

Rules, from the Forge queue port:
- "whole" copies a file byte-identical from source to tree.
- "anchor" ops take line spans (1-based inclusive) from the SOURCE file
  and splice them into the TREE file at an anchor TEXT (never a tree
  line number — the tree moves). Every anchor must match exactly once
  (or `count` times for replace/delete with `count`); any failure
  aborts BEFORE anything is written.
- Anchor ops apply bottom-up (highest tree line first) so earlier
  splices never shift later anchors.
- `verify` checks: whole files byte-identical to source; every anchor
  op's lines present in the tree; `untouched` files unchanged vs the
  backup taken at port time; marker counts match.

Stdlib only. Python 3.8+.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys

SPEC_VERSION = 1


def load_spec(path):
    with open(path, encoding="utf-8") as f:
        spec = json.load(f)
    if not isinstance(spec.get("files"), list):
        raise SystemExit("error: spec needs a 'files' list")
    return spec


def read_lines(path):
    with open(path, encoding="utf-8") as f:
        return f.read().splitlines(keepends=True)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_anchor(lines, text, what, expect=1):
    hits = [i for i, ln in enumerate(lines) if text in ln]
    if len(hits) != expect:
        raise SystemExit(
            f"anchor failure [{what}]: {text!r} expected {expect} hit(s), "
            f"got {len(hits)}: {[h + 1 for h in hits]}")
    return hits


def apply_anchor_ops(tree_lines, src_lines, ops, relpath):
    """Apply ops bottom-up. Returns the new tree lines.

    All anchors are resolved against the ORIGINAL tree lines first, so
    a bad anchor anywhere aborts before any splice happens.
    """
    # Resolve every op to concrete line indexes on the original lines.
    resolved = []
    for n, op in enumerate(ops):
        what = f"{relpath} op {n + 1} ({op.get('action')})"
        action = op.get("action")
        if action not in ("insert_after", "insert_before", "replace", "delete"):
            raise SystemExit(f"{what}: unknown action {action!r}")
        anchor = op.get("anchor")
        if not anchor:
            raise SystemExit(f"{what}: missing 'anchor'")
        count = int(op.get("count", 1))
        hits = find_anchor(tree_lines, anchor, what, expect=count)
        block = []
        if action != "delete":
            a, b = op.get("source_lines", [None, None])
            if a is None or b is None or not (1 <= a <= b <= len(src_lines)):
                raise SystemExit(f"{what}: bad source_lines {[a, b]} "
                                 f"of {len(src_lines)}")
            block = src_lines[a - 1:b]
        resolved.append((action, hits, block, int(op.get("replace_lines", 1))
                         if action == "replace" else 0))
    # Apply bottom-up: sort by the highest affected tree index, descending.
    order = sorted(range(len(resolved)),
                   key=lambda i: max(resolved[i][1]), reverse=True)
    lines = list(tree_lines)
    for i in order:
        action, hits, block, nlines = resolved[i]
        if action == "insert_after":
            for h in sorted(hits, reverse=True):
                lines[h + 1:h + 1] = block
        elif action == "insert_before":
            for h in sorted(hits, reverse=True):
                lines[h:h] = block
        elif action == "replace":
            for h in sorted(hits, reverse=True):
                lines[h:h + nlines] = block
        elif action == "delete":
            for h in sorted(hits, reverse=True):
                del lines[h]
    return lines


def do_port(spec, source, tree, backup_dir):
    source, tree = os.path.abspath(source), os.path.abspath(tree)
    # 1. Compute every new file's content in memory first; nothing is
    #    written until every anchor has resolved.
    planned = {}  # relpath -> new bytes
    for entry in spec["files"]:
        rel = entry["path"]
        src_path = os.path.join(source, rel)
        tree_path = os.path.join(tree, rel)
        if not os.path.isfile(src_path):
            raise SystemExit(f"error: source file missing: {src_path}")
        mode = entry.get("mode", "whole")
        if mode == "whole":
            with open(src_path, "rb") as f:
                planned[rel] = f.read()
        elif mode == "anchor":
            if not os.path.isfile(tree_path):
                raise SystemExit(f"error: tree file missing for anchor "
                                 f"port: {tree_path}")
            src_lines = read_lines(src_path)
            tree_lines = read_lines(tree_path)
            new_lines = apply_anchor_ops(tree_lines, src_lines,
                                         entry.get("ops", []), rel)
            planned[rel] = "".join(new_lines).encode("utf-8")
        else:
            raise SystemExit(f"error: {rel}: unknown mode {mode!r}")
    # 2. Back up every file about to change (and the untouched list, so
    #    verify can prove they stayed untouched).
    if backup_dir:
        os.makedirs(backup_dir, exist_ok=True)
        for rel in list(planned) + list(spec.get("untouched", [])):
            src = os.path.join(tree, rel)
            if os.path.isfile(src):
                dst = os.path.join(backup_dir, rel)
                os.makedirs(os.path.dirname(dst) or backup_dir, exist_ok=True)
                shutil.copy2(src, dst)
        print(f"backup: {len(planned)} changed + "
              f"{len(spec.get('untouched', []))} untouched files -> {backup_dir}")
    # 3. Write.
    for rel, data in planned.items():
        dst = os.path.join(tree, rel)
        os.makedirs(os.path.dirname(dst) or tree, exist_ok=True)
        with open(dst, "wb") as f:
            f.write(data)
        print(f"ported: {rel} ({len(data)} bytes)")
    print(f"PORT OK — {len(planned)} file(s) written")
    return 0


def do_verify(spec, source, tree, backup_dir):
    source, tree = os.path.abspath(source), os.path.abspath(tree)
    problems = []
    for entry in spec["files"]:
        rel = entry["path"]
        src_path = os.path.join(source, rel)
        tree_path = os.path.join(tree, rel)
        if not os.path.isfile(tree_path):
            problems.append(f"{rel}: missing from tree")
            continue
        if entry.get("mode", "whole") == "whole":
            if sha256_of(src_path) != sha256_of(tree_path):
                problems.append(f"{rel}: NOT byte-identical to source copy")
            else:
                print(f"ok: {rel} byte-identical to source")
        else:
            src_lines = read_lines(src_path)
            tree_text = "".join(read_lines(tree_path))
            for n, op in enumerate(entry.get("ops", [])):
                if op.get("action") == "delete":
                    continue
                a, b = op["source_lines"]
                block = "".join(src_lines[a - 1:b])
                if block not in tree_text:
                    problems.append(
                        f"{rel} op {n + 1}: ported lines {a}-{b} not "
                        f"found in tree")
            if not any(p.startswith(rel) for p in problems):
                print(f"ok: {rel} all anchor blocks present")
    for rel in spec.get("untouched", []):
        if not backup_dir:
            print(f"skip: {rel} untouched-check needs --backup")
            continue
        bak = os.path.join(backup_dir, rel)
        cur = os.path.join(tree, rel)
        if not os.path.isfile(bak):
            problems.append(f"{rel}: no backup to compare (untouched check)")
        elif not os.path.isfile(cur):
            problems.append(f"{rel}: untouched file was DELETED from tree")
        elif sha256_of(bak) != sha256_of(cur):
            problems.append(f"{rel}: untouched file CHANGED during port")
        else:
            print(f"ok: {rel} untouched")
    for rel, markers in spec.get("markers", {}).items():
        path = os.path.join(tree, rel)
        if not os.path.isfile(path):
            problems.append(f"{rel}: missing (marker check)")
            continue
        text = open(path, encoding="utf-8").read()
        for marker, expected in markers.items():
            got = text.count(marker)
            if got != expected:
                problems.append(f"{rel}: marker {marker!r} count {got}, "
                                f"expected {expected}")
            else:
                print(f"ok: {rel} marker {marker!r} x{got}")
    if problems:
        print(f"VERIFY FAILED: {len(problems)} problem(s)")
        for p in problems:
            print(f"  {p}")
        return 1
    print("VERIFY OK — merged tree matches the port spec exactly")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="port.py",
        description="Delta-port from an isolated source copy into the "
                    "live tree, then verify the merge.")
    ap.add_argument("--spec", required=True, help="port spec JSON file")
    ap.add_argument("--source", required=True, help="isolated source copy")
    ap.add_argument("--tree", required=True, help="live tree")
    ap.add_argument("--backup", default=None,
                    help="backup dir (port writes it; verify reads it)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("port", help="apply the port spec to the tree")
    sub.add_parser("verify", help="verify the tree against the spec")
    args = ap.parse_args(argv)
    spec = load_spec(args.spec)
    if args.cmd == "port":
        return do_port(spec, args.source, args.tree, args.backup)
    return do_verify(spec, args.source, args.tree, args.backup)


if __name__ == "__main__":
    sys.exit(main())
