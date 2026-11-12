# T13 — headless-play-render-harness

Drive a real page in headless Chrome at a phone viewport, run scripted
interactions, read live state, take screenshots, measure numbers, and report
pass/fail per step. Pairs with BNB SKILLS **S24** (sandbox-first sim build +
headless verification).

## What it does

- Phone viewports: 360×800 / 430×950 (configurable, with device scale factor
  and mobile emulation)
- Scripted input the way a person uses a phone: clicks at coordinates, typed
  text, key presses — not machine sweeps
- Live state reads via JS evaluation (`window.__state.…` — keep simulation
  state separate from the render so the harness can read it)
- Assertions on live state, numeric measurement (ball rest position, leg
  ground penetration, counters…), screenshots per step
- Report: `report.txt` + `report.json` + PNGs in the output dir

## How it drives the browser

The DevTools Protocol (CDP) over a WebSocket, with a minimal WebSocket
client written on the Python standard library — **no puppeteer, no
playwright, no pip install**. Chrome is launched with
`--remote-debugging-port` and the harness talks to its page target directly.
`--cdp-url` connects to an already-running browser instead of launching one.

## Browser requirement — read this first

The real path needs a working headless Chrome/Chromium binary. The harness
searches `CHROME_BIN`, then `PATH` (`chromium`, `chromium-browser`,
`google-chrome`), then common install paths including
`/opt/meta-chromium/chrome`. `--check-deps` reports exactly what is present
and what is missing — and it actually *starts* the binary headless to prove
it runs, because a binary existing is not the same as a binary working.

**Sandbox limitation, verified 2026-11-12:** this sandbox's bundled
Chromium (`/opt/meta-chromium/chrome`, a Hatch CVM build) refuses to start
— every flag combination fails with `Hatch WebGL domain policy is required
for browser startup`. The real-Chrome path therefore could **not** be
exercised in this sandbox. What *was* verified here:

1. the driver code (WebSocket client + CDP message flow) against a fake CDP
   server in the smoke test, and
2. the plan/assert/measure/report logic via `--mock`.

On a normal Linux machine with stock chromium/chrome, run without `--mock`.

## Usage

```bash
python3 harness.py --check-deps
python3 harness.py --plan examples/counter-plan.json --out out/
python3 harness.py --plan examples/counter-plan.json --mock --out out/
python3 harness.py --plan plan.json --chrome /usr/bin/chromium --out out/
```

The example plan's `url` contains `EXAMPLES_DIR` — replace it with the
absolute path to `examples/` (the smoke test does this automatically).

Exit code 0 = all assertions passed, 1 = any failed / driver error.

## Plan format

See `examples/counter-plan.json` and the docstring at the top of
`harness.py`. Step actions: `navigate`, `wait`, `click`, `type`, `key`,
`evaluate`, `assert`, `measure`, `screenshot`. The optional `mock` section
holds canned `evaluate` results so `--mock` runs exercise the same plan.

## Requirements

Python 3 stdlib only. A Chrome/Chromium binary for the real path.
