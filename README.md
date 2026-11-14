# BNB TOOLS

Working scripts and CLIs: the executable halves of BNB SKILLS playbooks, plus standalone utilities — and, since 2026-11-13, standalone PROJECTS spun off from chat threads as ideas (Joshua, 2026-11-13 23:39: BNB-TOOLS is also for projects, like WinLinx — surfacing ideas from the threads and building them, almost like the dream feature). Where a skill is a playbook an agent follows, a tool is a script the agent runs, or a full program the user runs. Each tool is a folder with its own README; a script or CLI tool answers `--help` with its usage.

Built from `~/workspace/bnb-skills-tools/AUDIT.md` (2026-11-12, all 67 chats read: main chat plus 66 side chats, 73 raw workflow candidates deduped to 52 skills and 17 tools). First delta scan the same evening (scan window ~17:54–19:00 EST) added 3 more tools (T18–T20) and an update to T11. T21 (debug-log-layer) was added later the same evening from his main-chat order for a debug layer in every project build. Second delta scan (2026-11-13, window ~19:13 EST 2026-11-12 → ~10:00 EST) added 2 more tools (T22–T23) and updates to 3 tool READMEs. Third delta scan the same evening (2026-11-13, window ~10:00–19:53 EST) added 2 more tools (T24–T25) and updates to 3 tool READMEs. Fifth delta scan the same evening (2026-11-13, window ~20:24–23:17 EST) added no new tools and changed the definition of a tool: BNB-TOOLS now also holds standalone projects spun off from threads, and the sweep collects spin-off candidates each delta (7 in Delta 5). The companion repo, BNB SKILLS, holds the playbooks these tools pair with.

## Requirements

- Python 3, standard library preferred. A tool should run with no extra installs unless its own README says otherwise.
- Linux Mint. Tools are built for Joshua's Mint PC and the sandbox, not for other platforms.
- $0. No paid services, no API keys, no subscriptions.

## How to run a tool

- Each folder has its own README. Read it first.
- Every script or CLI tool answers `--help` with its usage, flags, and an example. A spun-off project tool is run the way its own README says.
- Run from the tool's own folder unless its README says otherwise.

## Smoke tests

- Each tool ships a smoke test that runs without network access and without touching a live repo, unless its README says the test needs one.
- Run the smoke test before first use and after any change to the tool.
- A smoke test that needs a live service says so in the tool README and is skipped by default.

## All 25 tools

| # | Tool | Description | Paired skill |
|---|---|---|---|
| T1 | `ship-pipeline-scripts` | Zip builder with correct stored modes, SHA-256 of local zip vs downloaded Release asset, read-back checks of pushed files | S1 |
| T2 | `delta-port-diff-verify` | Port only the marked delta from an isolated copy into the live tree, then verify the merged tree against the source copy | S2 |
| T3 | `post-merge-battery-runner` | Wait for a stable window, run targeted classes plus the full suite, diff the failure list against baseline, report only the delta | S8 |
| T4 | `name-check` | Batch GitHub exact-name search plus web check per candidate name; outputs clean/dead with evidence | S7 |
| T5 | `model-sweep-harness` | Scripted benchmark and compatibility table builder feeding the sweep report | S13 |
| T6 | `linux-release-packager` | From a tree plus icon SVG: render PNGs, generate GUI installer and .desktop, uninstaller, installer self-verification | S6 |
| T7 | `overlay-match` | Lay a render over a reference sheet at the same scale, measure silhouette and dimension deltas, report residual offsets | S18 |
| T8 | `logo-test-battery` | Render a mark at 16/32/48px, silhouette, grayscale, invert, crop, pasted into a real product screenshot; pass/fail per test | S21 |
| T9 | `brand-scrub-rename` | Grep-driven whole-tree substitution with straggler catch and migration scaffolding for user state keys | S30 |
| T10 | `repo-identity-check` | GitHub existence, empty, and description check for a repo name; handles the get_file_contents ok plus isError trap | S20 |
| T11 | `fresh-unzip-verification` | Unzip the shipped zip into a clean directory, run the full suite there, run smoke checks, screenshot GUI tabs, report | Standalone |
| T12 | `qt-verification-harness` | One command that sets the known-good Qt test environment and runs a launch, screenshot, and render-grab check | Standalone |
| T13 | `headless-play-render-harness` | Puppeteer and screenshot harness at phone viewport: simulated input, live state reads, screenshots, numeric measurement | S24 |
| T14 | `video-capture-ffmpeg-pipeline` | Drive the real app and capture it, cut to the 15s structure, LUFS loudness-normalize, fresh filenames per cut | S26 |
| T15 | `compress-to-size` | Bitrate math from duration plus target size with a safety margin; emits the ffmpeg command, plus an audio-only alternative | Standalone |
| T16 | `token-burn-rate-tracker` | Baseline snapshot, scheduled recheck, tokens per day plus pool-lifetime estimate | S40 |
| T17 | `song-key-bpm-lookup` | Key and BPM data lookup plus mashup-compatibility math; tentative, depends on a scriptable key/BPM data source | S41 |
| T18 | `dual-model-relay-harness` | CLI relay runner mirroring DUO RelaySession semantics: blind/aware framing, turn cap, stop phrases | S55 |
| T19 | `fake-provider-servers` | Fake Ollama plus fake OpenAI-compatible servers with failure modes and request recording | S58 |
| T20 | `org-repo-inventory` | Live user/org repo listing; JSON inventory plus markdown queue, --diff for new/changed repos | S56 |
| T21 | `debug-log-layer` | Drop-in logging + error handling + scrubbed debug report, on demand and on crash | S61 |
| T22 | `task-list-combine-verify` | Verify a combined task list against its source lists: every source task traced exactly once, IDs unique and contiguous, statuses adding up | S64 |
| T23 | `task-list-coverage-check` | Check a task list covers every audit finding: uncovered findings, unknown references, duplicate IDs, count reconciliation | S65 |
| T24 | `staging-guard` | Pre-build check for a publish staging dir: manifest of required files from a trusted source, verify presence and hashes before building the Release zip | S1 |
| T25 | `desktop-launch-sim` | Simulate a double-click on an installed .desktop launcher from another folder and cwd; reports STARTED / FAILED, catches %k-relative lookups | S6 |

## How to add a new tool

- Make a folder named with the tool slug (lowercase, hyphenated).
- Write a README in the folder: what it does, requirements, usage with `--help`, how to run its smoke test, and what it does not do.
- Keep it Python 3 standard library unless the job genuinely needs more, and say so in the README if it does.
- Give it a smoke test that runs without network access and without touching a live repo.
- Add a row to the table above, in number order, with the paired skill or Standalone.
- Ground the tool in work actually done. Do not invent a workflow. If a tool depends on a data source that does not exist yet, mark it tentative, as T17 does.

License: MIT — see the LICENSE file.
