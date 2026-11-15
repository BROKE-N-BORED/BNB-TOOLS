# Changelog

## v0.1.1 - 2026-11-15

README only, no code change (Delta 6).

- New section: telling an infra-kill from a test failure.
  Compare the job's lifetime against the suite's recorded
  runtime - a run that dies far faster than the suite takes
  never got to the tests (Forge Browser, 2026-11-14: jobs
  dying in 3-4s against an 80s suite were killed at startup
  by the billing lock).
- Wording: "cut the Release" replaced with "update the
  Release" (Joshua, 2026-11-14 - he does not like the word
  cut).

## v0.1.0 - 2026-11-14

First release.

- Pre-push gate (`check`): runs the suite under timeout, builds
  a throwaway Release-shaped zip with stored-mode verification,
  checks named executables carry their exec bit on disk, and
  runs configured doc counts (files, dirs, lines, regex
  matches) with optional expected/min/max assertions. Writes
  the verdict to CI-STATUS.md at the repo root (commit, date,
  per-check pass/fail, counts, timing, repo size) and exits 0
  only when everything passed.
- Setup helper (`setup`): installs the check into any repo as
  ci/local_ci.py (self-contained, stdlib only), ci/check.sh
  (thin wrapper, the J1 invocation shape), and ci/config.json
  (starter config). Refuses to overwrite without --force.
  Wires nothing into GitHub.
- Per-repo config (ci/config.json): suite command, timeout,
  count pattern, zip on/off, top name, executable list and
  globs, manifest file (the Forge Browser EXECUTABLES.txt
  shape), exclude dirs and suffixes, mode check on/off, doc
  counts, status file, work-dir base. Missing config degrades
  to defaults with a plain message; unknown keys are an error;
  keys starting with _ are comments.
- The generic extraction of Forge Browser v0.9 item J1, the
  first proven instance of this pattern (534 checks green).
  Two deliberate differences from J1: no em-dashes in the
  verdict file (U33), and one executable-matching rule for
  build and verify alike (J1 matched the manifest by path in
  the build and by basename in the verify, which disagrees on
  nested scripts).
