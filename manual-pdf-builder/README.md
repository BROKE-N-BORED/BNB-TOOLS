# T41 - manual-pdf-builder

Pairs with skill **S92** (how-to-manual).

One small script that builds a project's how-to manual PDF the
S92 way: the manual is written as a plain-words `MANUAL.md`,
every claim the manual makes about files, scripts, and versions
is checked against the real project tree, the manual is checked
for em-dashes, and only then is it rendered to a styled A4 PDF
through a headless Chromium.

## Why it exists

The SOLDAR manual, 2026-11-18 ~13:56-13:58 EST. Joshua ordered
an easy-to-read how-to manual; the thread hand-built it the same
day: an 8-page A4 PDF (156 KB) from a `MANUAL.md` source,
verified against the SOLDAR tree, no em-dashes, rendered with a
headless Chromium. It also shipped with three items named as
unverified: the live v0.3.0 release link, the port-in-use
behaviour, and a Code example that was never executed.

That is the honest shape, and the reason this tool exists:
every BNB tool and every Joshua project eventually needs one of
these manuals, and hand-building each one per thread is how a
manual ends up citing a file that moved or a version that
changed. The check step is what makes the unverified list short
and named instead of silent.

Rebuilt with this tool while it was being written (2026-11-18):
the check passed against the SOLDAR tree (3 paths and 2
versions verified, 1 runtime path, `update/`, exempted by a
skip comment) and the chain produced an 8-page PDF of 156,608
bytes, against the original's 8 pages and 155,837 bytes. The
first check run also caught two things worth knowing: an
extension citation (`.soldar.json`) that is not a file, which
the checker now ignores by rule, and the `update/` runtime
folder, which is what the skip comment is for.

## The three pieces

Small, chainable, each runnable alone, each a function and a
CLI subcommand:

| Piece | Function | What it does |
| --- | --- | --- |
| 1. check | `check_references()` | Every path, script, and version the manual cites must exist or match in the project tree. Fails with a plain-words list of what does not check out. |
| 2. emdash | `check_em_dashes()` | Fails the build if the manual contains an em-dash or an en-dash. |
| 3. render | `render_pdf()` | MANUAL.md -> styled HTML -> A4 PDF via headless Chromium. Runs the emdash check first: a manual with dashes is not rendered. |

`build` is the chain: check, then emdash, then render, stopping
at the first failure and saying which step stopped it.

```bash
python3 manual_pdf.py check MANUAL.md --tree /path/to/project
python3 manual_pdf.py emdash MANUAL.md
python3 manual_pdf.py render MANUAL.md --out Manual.pdf
python3 manual_pdf.py build MANUAL.md --tree /path/to/project --out Manual.pdf
```

## What the check actually checks

- **Paths.** Backtick spans and fenced code lines that name a
  file or folder (`install.sh`, `src/app.py`, `./run.sh`) must
  exist in the tree. Commands are read for the path they name:
  `bash install.sh`, `python3 src/app.py`, `cd tools`,
  `chmod +x install.sh`, `unzip pack.zip`. For `cp` / `mv` only
  the source is checked; a destination need not exist yet.
- **Versions.** A version with a leading `v` (`v0.3.0`) is
  always checked against the tree's own version. A bare version
  (`0.3.0`) is only checked when it directly follows the project
  name ("SampleApp 0.3.0", "SampleApp version 0.3.0"), so
  dependency versions (Node 20.1.0, Python 3.12.1) never trip
  it, even on a line that also names the project. Write another
  project's version without the `v` and it is skipped too.
- **Release zips.** A cited zip whose name carries a version
  (`soldar-v0.3.0.zip`) lives on the Releases page, not in the
  tree, so it is verified by the version check, not by
  existence. A zip with no version in its name is checked for
  existence like any other file.
- **Extensions are not files.** A span that is only an
  extension (`.json`, `.soldar.json`) names a file type, not a
  file, and is never checked.
- **Runtime files.** Files the app creates when it runs (a data
  folder, logs, a downloaded update waiting to install) are
  real but are not in the tree. Exempt them in the manual
  itself with one comment, and the check skips them and says
  how many it skipped:

  ```markdown
  <!-- manual-pdf-skip: update/, cache.db -->
  ```
- **The tree's version** is read from, in order: a
  `--version-file`, a `VERSION` file, the first version heading
  in `CHANGELOG.md`, `pyproject.toml`, `package.json`. When the
  tree names no version anywhere, cited versions are reported
  as a warning ("could not be checked"), never silently passed
  and never a failure.

What the check does **not** verify, by design:

- **URLs** are never fetched (the tool works offline) and are
  not checked at all. A manual's links are the author's to
  confirm.
- **Home paths** (`~/.local/...`) and **absolute system paths**
  (`/usr/...`) are skipped: they do not live in the tree.
- **Live behaviour** (what the app does when a port is busy,
  what a Code example prints) cannot be checked by any file
  check. Name anything like that in an **Unverified** section
  at the end of the manual, the way the SOLDAR manual did. The
  tool keeps the checkable claims honest; the Unverified
  section keeps the rest honest.

## The Markdown subset

The renderer understands the subset a plain-words manual uses:
headings (`#`, `##`, `###`), paragraphs, ordered and unordered
lists, bold, inline code, fenced code blocks, and bare URLs as
links. Anything outside that subset renders as plain paragraph
text; nothing crashes. The paragraph right after the `#` title
is styled as a subtitle (that is where the version line lives).
Pages are A4 with the same styling the SOLDAR manual shipped
with.

## The renderer: headless Chromium, no Playwright package

The SOLDAR manual was built with Playwright's headless Chromium
shell, driven straight through its `--print-to-pdf` flag by a
stdlib-only script, with no Playwright Python package involved.
This tool does exactly the same thing. `find_chromium()` looks,
in order:

1. a `--chromium PATH` flag,
2. the `MANUAL_PDF_CHROMIUM` environment variable,
3. the Playwright browser cache (`~/.cache/ms-playwright`),
   headless shell first, then a full Chromium,
4. `chromium-headless-shell`, `chromium`, `chromium-browser`,
   `google-chrome` on PATH.

When none is found, render stops with a plain message naming
what is missing and how to get it (exit 1, never a traceback):

```text
render needs a headless Chromium binary and none was found.
Get one with: pip install playwright, then
playwright install chromium-headless-shell
(or install chromium / google-chrome from your system).
You can also point at one directly with --chromium PATH,
or set MANUAL_PDF_CHROMIUM to its path.
```

`check` and `emdash` never need Chromium at all.

## CLI

```bash
python3 manual_pdf.py check MANUAL.md --tree DIR [--project NAME] [--version-file FILE]
python3 manual_pdf.py emdash MANUAL.md
python3 manual_pdf.py render MANUAL.md --out PDF [--chromium PATH] [--title TEXT] [--keep-html]
python3 manual_pdf.py build MANUAL.md --tree DIR --out PDF [same options as check + render]
python3 manual_pdf.py debug-report [--out PATH]
python3 manual_pdf.py --help
python3 manual_pdf.py --version
```

Exit codes: 0 the step did what it should, 1 the step failed
(references wrong, dashes found, render failed, Chromium
missing), 2 the step could not run (manual or tree not found,
bad input). Errors are plain words naming the missing thing,
never a traceback. The Python version guard (3.8+) is the same
shape: a plain message naming the Python version, exit 1.

## The demo

`demo.py` builds a fake project tree and a sample manual in a
temp dir and proves the pieces: each one alone with `--pieces`,
or the full chain by default. The render uses the real Chromium
when one is installed and says so plainly when none is.

```bash
python3 demo.py
python3 demo.py --pieces
```

## Requirements

Python 3.8+, standard library only. `render` and `build` also
need a headless Chromium binary (see above). No network, no
account, no token, anywhere in the tool.

The debug log layer is imported lazily: importing the module
for a check never pays the debug layer's import cost. Only
`debug-report` touches it.

## Debug report

```bash
python3 manual_pdf.py debug-report [--out PATH]
```

Writes a debug report through the T21 debug log layer
(`debug_log.py`, copied unmodified, SHA-256 pinned in the
tests). The log dir is a temp dir, so no `logs/` directory is
left behind.

## Smoke test

```bash
bash run_tests.sh
```

No live network. Covers the dash check (found with line numbers,
em and en), the Markdown converter (headings, subtitle, lists,
bold, code, links, escaping, unclosed fence, A4 rule), reference
extraction (inline spans, fenced blocks, chmod, cp source only,
flags ignored, home paths and URLs skipped), the check (pass,
missing file named, version match and mismatch, unverifiable
versions as warnings), Chromium discovery (explicit path, env
var), the render end to end (a real PDF with real pages, a long
manual over multiple pages, dashes refused), the build chain
(stops at the failing step), the CLI (help, version, exit codes,
plain-word errors), the missing-Chromium guard in a scrubbed
environment (exit 1, plain words, no traceback), the unmodified
debug log layer (SHA-256 pinned), stdlib-only imports, the
no-em-dash rule over the whole tree, and the release zip modes.
The live render tests skip, with a clear reason, on a machine
with no Chromium.

## Packaging note

This is a CLI/script tool like T28, T33, and T34: there is
nothing to install, so there is no installer.desktop and no
install.sh. Copy the folder (or just `manual_pdf.py`, plus
`debug_log.py` if you want the debug report) and run it. See
BUILD_REPORT.md for the full decision record.

## What it does not do

- It does not write the manual. MANUAL.md is still written by a
  person (or a thread) who knows the project; this tool checks
  it and renders it.
- It does not fetch or verify URLs, run the app, or execute any
  example in the manual. Behaviour claims belong in the
  manual's Unverified section until someone checks them live.
- It does not support full Markdown. The subset above is the
  whole list; tables and images are not rendered.
- It does not check home paths or system paths against anything.
- It does not upload or publish the PDF. Shipping the manual
  stays with the project's own ship flow.

## Unproven

- Never run on Joshua's PC. The chain was run end to end
  against the real SOLDAR manual and tree in the sandbox (see
  "Why it exists" above), but not on his machine.
- Chromium discovery on his Mint PC is unproven: the search
  covers the Playwright cache and the usual PATH names, but his
  PC's exact Chromium install has not been seen by this tool.
