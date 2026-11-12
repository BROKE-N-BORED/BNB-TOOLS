#!/bin/bash
# Smoke test for T2 delta-port-diff-verify.
# Two small trees, port a delta, verify clean; tamper, verify must fail.
set -u
cd "$(dirname "$0")"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$WORK/source/pkg" "$WORK/tree/pkg"

# Source copy: new file + main.py with the new feature block.
cat > "$WORK/source/pkg/new_feature.py" <<'EOF'
def feature():
    return 42
EOF
cat > "$WORK/source/pkg/main.py" <<'EOF'
class App:
    def __init__(self):
        self._phone_queue_ws = []
        self._message_queue = []
        self._queue_seq = 0
    def send(self):
        self.send_btn.setEnabled(True); self.stop_btn.setEnabled(False)
    def run(self):
        pass
EOF
cat > "$WORK/source/pkg/providers.py" <<'EOF'
PROVIDERS = ["a"]
EOF

# Live tree: same shape but WITHOUT the feature; providers identical.
cat > "$WORK/tree/pkg/main.py" <<'EOF'
class App:
    def __init__(self):
        self._phone_queue_ws = []
    def send(self):
        self.send_btn.setEnabled(True); self.stop_btn.setEnabled(False)
    def run(self):
        pass
EOF
cp "$WORK/source/pkg/providers.py" "$WORK/tree/pkg/providers.py"

# Port spec: whole-copy the new file; anchor-insert the queue state
# (source lines 4-5) after the phone-queue line; replace the setEnabled
# line with the source's identical line (proves replace works); marker
# count for _message_queue is 1 after the port.
cat > "$WORK/spec.json" <<'EOF'
{
  "files": [
    {"path": "pkg/new_feature.py", "mode": "whole"},
    {"path": "pkg/main.py", "mode": "anchor", "ops": [
      {"action": "insert_after", "anchor": "self._phone_queue_ws = []",
       "source_lines": [4, 5]},
      {"action": "replace",
       "anchor": "self.send_btn.setEnabled(True); self.stop_btn.setEnabled(False)",
       "source_lines": [7, 7], "replace_lines": 1}
    ]}
  ],
  "untouched": ["pkg/providers.py"],
  "markers": {"pkg/main.py": {"_message_queue": 1}}
}
EOF

python3 port.py --help >/dev/null || { echo "SMOKE FAIL: --help"; exit 1; }

python3 port.py --spec "$WORK/spec.json" --source "$WORK/source" \
  --tree "$WORK/tree" --backup "$WORK/backup" port \
  || { echo "SMOKE FAIL: port"; exit 1; }

python3 port.py --spec "$WORK/spec.json" --source "$WORK/source" \
  --tree "$WORK/tree" --backup "$WORK/backup" verify \
  || { echo "SMOKE FAIL: verify after clean port"; exit 1; }

# Tamper: change a ported file and an untouched file; verify must fail.
printf '# tampered\n' >> "$WORK/tree/pkg/new_feature.py"
printf '# tampered\n' >> "$WORK/tree/pkg/providers.py"
if python3 port.py --spec "$WORK/spec.json" --source "$WORK/source" \
  --tree "$WORK/tree" --backup "$WORK/backup" verify; then
  echo "SMOKE FAIL: verify passed on a tampered tree"; exit 1
else
  echo "tamper detection OK (verify failed as expected)"
fi

# Anchor failure must abort before writing: bad anchor, fresh tree.
sed 's/self._phone_queue_ws = \[\]/self._NO_SUCH_ANCHOR/' "$WORK/spec.json" \
  > "$WORK/bad-spec.json"
cp -r "$WORK/source" "$WORK/tree2"
if python3 port.py --spec "$WORK/bad-spec.json" --source "$WORK/source" \
  --tree "$WORK/tree2" --backup "$WORK/backup2" port; then
  echo "SMOKE FAIL: port with a bad anchor succeeded"; exit 1
else
  echo "bad-anchor abort OK"
fi

echo "T2 SMOKE TEST PASSED"
