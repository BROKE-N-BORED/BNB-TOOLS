# T2 — delta-port-diff-verify

Pairs with skill **S2** (isolated-copy build + delta-port merge with batteries).

Ports only the marked delta from an isolated source copy into the live tree, then verifies the merge. Generalizes `forge-queue-verify/port_queue.py` (a one-off hand-written port) and `port-spec.md` (its hunk table) into a data-driven tool: the port is described by a JSON spec, not code.

## What it does

- `port` — apply the spec: whole-file copies (byte-identical) and anchor splices (line spans from the source file inserted/replaced/deleted at anchor *text* in the tree file — never tree line numbers, the tree moves). Every anchor must match exactly once (or `count` times); any failure aborts **before** anything is written. Anchor ops apply bottom-up so earlier splices never shift later anchors. Backs up every changed file first.
- `verify` — checks whole files are byte-identical to the source copy, every anchor block is present in the tree, `untouched` files are unchanged vs the backup, and marker counts match.

## Port spec format (JSON)

```json
{
  "files": [
    {"path": "pkg/new_module.py", "mode": "whole"},
    {"path": "pkg/main.py", "mode": "anchor", "ops": [
      {"action": "insert_after", "anchor": "self._phone_queue_ws = []",
       "source_lines": [14191, 14227]},
      {"action": "replace", "anchor": "self.send_btn.setEnabled(True)",
       "source_lines": [21773, 21773], "replace_lines": 1},
      {"action": "insert_before", "anchor": "def send_message(self):",
       "source_lines": [20897, 20913]},
      {"action": "delete", "anchor": "self.send_btn.setEnabled(False)"}
    ]}
  ],
  "untouched": ["pkg/providers.py"],
  "markers": {"pkg/main.py": {"_message_queue": 12}}
}
```

- `source_lines` are 1-based inclusive line numbers **in the source copy**.
- `anchor` is a unique substring of the tree file. `count` (default 1) says how many matches to expect for `replace`/`delete`.
- `replace_lines` (default 1) says how many tree lines the anchor line's replacement covers.
- `markers` maps a file to `{marker_text: expected_count}` — the merge verification counts from the Forge queue port.

See `port-spec.example.json` for a complete small example.

## Requirements

Python 3.8+, stdlib only. No network.

## Usage

```bash
python3 port.py --spec port-spec.json --source ./isolated-copy \
    --tree ./live-tree --backup ./backup port

python3 port.py --spec port-spec.json --source ./isolated-copy \
    --tree ./live-tree --backup ./backup verify
```

## Smoke test

```bash
bash smoke_test.sh
```

Builds two small trees, ports a delta, verifies clean, then tampers with the tree and shows verify failing.
