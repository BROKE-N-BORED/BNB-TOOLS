# T28 - local-ci

Pairs with skill **S1** (ship pipeline - verify, push, Release,
hash-match).

A repo-agnostic pre-push check: one script that runs the full
suite plus the zip build, stored-mode checks, and doc counts
before a push, and writes the verdict to a `CI-STATUS.md` file
at the repo root, so the repo page itself shows the last result.

## Why it exists

GitHub Actions is billing-locked account-wide, so every repo's
CI is dead and the fix sits in billing settings. Joshua's order
(Forge Browser DEV, 2026-11-13): build a free version or
workaround that works better than it can. The first instance
was Forge Browser v0.9 item J1 (`ci/check.sh` + `CI-STATUS.md`),
proven live with 534 checks green. This tool is the generic
extraction of that pattern, so any repo can adopt it.

It checks more than Actions ever did: Actions ran only the
suite. This also builds the zip, checks stored modes, and
counts docs. It runs locally, no runners, no account, nothing
that can be billing-locked.

## Where it sits in the ship pipeline (S1)

After the build, before the push. The order is: build and
verify the tree, run this check, push only when it passes, then
update the Release. `CI-STATUS.md` rides in the push, so the repo
page shows the last verdict.

It does not overlap T1 or T24:

- **T1 ship-pipeline-scripts** packs the real Release zip, checks
  its stored modes, and hash-compares the local zip against the
  downloaded Release asset. Local CI builds only a throwaway
  zip to prove the tree packs clean - the shipped Release zip
  is still made by T1 (or the project's own builder) at Release
  time.
- **T24 staging-guard** checks a publish staging dir against a
  manifest of required files before the Release zip is built.
  Local CI checks the repo tree itself before the push.
- Local CI is the gate that ties them together: suite green,
  tree packs clean, modes right, doc counts right, or the push
  does not happen.

## Requirements

Python 3.8+, standard library only. No network, no account, no
GPU. Runs on his 8 GB Mint PC as a plain script. This is a
script tool, not a GUI app: it runs in the terminal and from
the agent, like T1 and T24.

## Install it into a repo

```bash
python3 local_ci.py setup /path/to/repo
```

That installs three files into the repo, nothing else:

- `ci/local_ci.py` - the check itself, self-contained (one file,
  stdlib only, no network). The installed copy is the whole
  tool, so the repo needs nothing from BNB-TOOLS to run it.
- `ci/check.sh` - thin wrapper, the J1 invocation shape:
  `sh ci/check.sh` from the repo root (or anywhere - the check
  finds the repo from its own path).
- `ci/config.json` - starter config: project name from the dir,
  suite command only when a `tests/` dir exists, manifest file
  only when `EXECUTABLES.txt` exists.

`setup` refuses to overwrite an existing install unless you
pass `--force`. It wires nothing into GitHub.

Then, before every push:

```bash
sh ci/check.sh
```

Exit 0 means green, 1 means red, 2 means the check could not
run (bad config, missing repo). A red repo never ships: fix it,
re-run, push only on green.

## What it checks

1. **Suite.** Runs the suite command under a timeout (default
   280 seconds, the J1 value), with `TMPDIR` pointed at the
   throwaway work dir - the sandbox `/tmp` is a small tmpfs
   and a suite run can fill it. Parses the test count from the
   log (`Ran N tests` by default). On failure it prints the
   failing test names to the terminal. When the repo has no
   `tests/` dir and no suite command is configured, the suite
   check SKIPs honestly instead of failing.
2. **Release zip.** Builds a throwaway zip of the tree with
   T1's mode rules (0o100755 for executables, 0o100644 for
   plain files, 0o40755 for directories, file-type bits
   included), reopens it, and proves every entry carries the
   mode it should. Records files, dirs, bytes, and SHA-256.
   The zip is a throwaway - the check is the point, not the
   artifact.
3. **Modes on disk.** Every named executable (config list plus
   manifest file, when one is configured) must carry its exec
   bit in the tree. Names the repo itself declares are
   required: missing is a failure. Default-list names that are
   absent are fine - the default list is candidates, not
   requirements. Glob-matched files (`*.sh`, `*.desktop`) are
   not checked on disk: a script invoked only via `sh file.sh`
   needs no exec bit, and the zip stores 100755 for it either
   way.
4. **Doc counts.** Configured counts with optional assertions:
   `files` (recursive count under a path matching a glob),
   `dirs` (immediate subdirs), `lines` (lines in a file),
   `matches` (regex matches in a file). `expected`, `min`, or
   `max` turns a count into a gate; without one the count is
   recorded only and always passes. This is how a repo proves
   its docs' numbers - for example, that the README's skill
   count matches the skill dirs on disk.

The verdict file also carries the performance envelope: suite
time per check, total time, test counts, and repo size (files
and bytes).

## The verdict file

`CI-STATUS.md` at the repo root, in J1's shape:

```markdown
# My Project CI status

Free CI (`ci/check.sh`) - GitHub Actions is billing-locked
account-wide, so this file is the verdict record. Last checked:

- Commit: a1b2c3d
- Date (UTC): 2026-11-14T16:00:00Z
- Verdict: PASS
- Suite: 534 checks - PASS (12.3s)
- Release zip: OK: 98 files, 8 dirs, 1361891 bytes, modes verified, SHA-256 de04a92a... (4.1s)
- Modes: 6 executables on disk OK - PASS
- Doc counts: 2 count(s) - PASS
  - skills: 72 (expected 72) - PASS
  - test files: 14 (min 1) - PASS
- Repo: 214 files, 1832402 bytes
- Total: 16.8s

Run `sh ci/check.sh` from the repo root to re-check.
```

A broken config still writes a red verdict: a stale green
`CI-STATUS.md` is worse than a red one. `--no-status` skips
writing the file (dry run).

## Telling an infra-kill from a test failure

When a CI run fails, compare how long the job lived against how
long the suite takes to run. A run that dies far faster than the
suite takes never got to the tests - it was killed at startup,
which means infrastructure, not code.

The case that proved it (Forge Browser, 2026-11-14): Actions
jobs were dying in 3-4 seconds against a suite that takes about
80 seconds to run. A suite cannot fail in 3 seconds when it
needs 80 to run at all - the jobs were killed at startup by the
billing lock, before any test ran. Chasing test failures there
would have been chasing nothing.

The verdict file records the suite time on every run, so the
comparison is always available: if the job's lifetime is a small
fraction of the recorded suite time, look at the infrastructure
(billing, runners, startup) before looking at the tests.

## Config

`ci/config.json`. Missing config degrades to defaults with a
plain message, so a repo with a standard layout needs almost
no config. See `config.example.json` (every key, documented)
and `config.schema.json` (JSON Schema). The keys:

| Key | Default | What it does |
| --- | --- | --- |
| `project` | repo dir name | Project name in the verdict file |
| `suite_command` | `python3 -m unittest discover -s tests` when `tests/` exists | Suite command, list or string |
| `suite_timeout` | 280 | Seconds before the suite is killed and marked FAIL |
| `suite_count_pattern` | `Ran (\d+) tests?` | Regex (one group) for the test count; last match wins |
| `zip` | true | Build and verify the throwaway zip |
| `zip_top` | repo dir name | Top folder name inside the throwaway zip |
| `zip_executables` | run.sh, install.sh, browser-setup.sh, install-gui.py, uninstall.sh | Root-relative paths that ship executable (T1's list) |
| `zip_executable_globs` | `*.sh`, `*.desktop` | Globs that also ship executable |
| `zip_executables_file` | none | Manifest file in the repo, the Forge Browser `EXECUTABLES.txt` shape (one root-relative path per line, `#` comments) |
| `zip_exclude_dirs` | `__pycache__`, `.git`, `.venv`, `node_modules`, `.forge` | Dirs skipped by the zip, the repo-size count, and files doc counts |
| `zip_exclude_suffixes` | `.pyc`, `.pyo`, `.zip` | Filename suffixes skipped the same way |
| `mode_check` | true | Check named executables carry their exec bit on disk |
| `doc_counts` | none | Counts to record, each with an optional `expected`/`min`/`max` |
| `status_file` | `CI-STATUS.md` | Verdict file at the repo root |
| `tmp_base` | `$LOCAL_CI_TMP`, then `~/workspace/tmp`, then system temp | Where throwaway work dirs live |

Unknown keys are an error, not a silent skip: a mistyped key
would mean the check you think is running is not the check
running. Keys starting with `_` are comment keys and are
ignored.

## Smoke test

```bash
bash run_tests.sh
```

50 tests, no network, fixture repos in temp dirs. Covers
help/version, config defaults/overrides/errors, passing and
failing suites, timeout, suite skip, zip counts and mode
verification (including a hand-built wrong-mode zip), on-disk
mode failures, all four doc-count kinds, verdict shape and the
no-em-dash rule, setup install/refusal/force, and the installed
copy running green via `sh ci/check.sh`.

## What it does not do

- It does not push and does not make a Release - those stay
  manual, after this script passes.
- It does not pack the real Release zip - that is T1 (or the
  project's own builder). The zip it builds is a throwaway.
- It does not check publish staging - that is T24.
- It does not run on a schedule or watch for changes. It runs
  when you run it, before a push.
- It does not verify the pushed repo or the Release asset -
  S1's read-back and hash-match steps still apply after the
  push.
- It cannot run a suite the machine cannot run: a suite that
  needs a display, a GPU, or a venv the config does not point
  at will fail the same way it fails by hand. Point
  `suite_command` at the right interpreter for the repo.
