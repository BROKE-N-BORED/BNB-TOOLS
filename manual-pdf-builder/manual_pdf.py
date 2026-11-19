#!/usr/bin/env python3
"""T41 manual-pdf-builder: check a MANUAL.md against its project tree,
then render it to a styled A4 PDF.

Pairs with skill S92 (how-to-manual).

Three chainable pieces, each a function and a CLI subcommand:

  1. check   - every file, script, and version the manual cites must
               exist or match in the project tree. Fails with a
               plain-words list of what does not check out.
  2. emdash  - fails the build if the manual contains an em-dash or
               an en-dash (both read as AI slop in a plain-words manual).
  3. render  - MANUAL.md -> styled HTML -> A4 PDF via a headless
               Chromium binary. No Playwright package needed: the
               Chromium shell is driven straight through its
               --print-to-pdf flag, the way the SOLDAR manual was built.

`build` runs all three in order and stops at the first failure.

Standard library only. `check` and `emdash` need nothing but
Python; `render` needs a headless Chromium binary (see
find_chromium). When Chromium is missing, render says so in plain
words, names how to get one, and exits 1 -- never a traceback.

Usage:
  python3 manual_pdf.py check MANUAL.md --tree /path/to/project
  python3 manual_pdf.py emdash MANUAL.md
  python3 manual_pdf.py render MANUAL.md --out Manual.pdf
  python3 manual_pdf.py build MANUAL.md --tree /path/to/project \\
      --out Manual.pdf
  python3 manual_pdf.py --help
  python3 manual_pdf.py --version
"""
import sys

if sys.version_info < (3, 8):
    sys.stderr.write(
        "manual-pdf-builder needs Python 3.8 or newer (you have %s).\n"
        % ".".join(str(p) for p in sys.version_info[:3]))
    sys.exit(1)

import argparse
import datetime
import glob
import html
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

__version__ = "0.1.0"
VERSION = __version__
APP_SLUG = "manual-pdf-builder"

# Built with chr() so no dash byte ever sits in this file's source.
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)

# Exit codes: 0 the step did what it should, 1 the step failed
# (references wrong, dashes found, render failed, Chromium
# missing), 2 the step could not run (manual or tree not found,
# bad input).
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CANNOT_RUN = 2

RENDER_TIMEOUT = 120

CHROMIUM_INSTALL_HINT = (
    "render needs a headless Chromium binary and none was found. "
    "Get one with: pip install playwright, then "
    "playwright install chromium-headless-shell "
    "(or install chromium / google-chrome from your system). "
    "You can also point at one directly with --chromium PATH, "
    "or set MANUAL_PDF_CHROMIUM to its path.")

# ---------------------------------------------------------------- dashes

_DASH_KIND = {EM_DASH: "em-dash", EN_DASH: "en-dash"}


def find_dashes(text):
    """Every em-dash and en-dash in the text, as a list of
    {"line": int, "kind": "em-dash" | "en-dash"}. Line numbers
    start at 1. An empty list means the text is clean."""
    found = []
    for number, line in enumerate(text.split("\n"), start=1):
        for char in line:
            kind = _DASH_KIND.get(char)
            if kind:
                found.append({"line": number, "kind": kind})
    return found


def check_em_dashes(manual_path):
    """Check one manual file for dashes.

    Returns {"status": "pass" | "fail" | "error",
    "problems": [plain-words strings], "checked_lines": int}.
    "error" means the file could not be read at all.
    """
    try:
        text = Path(manual_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"status": "error",
                "problems": ["no such manual file: %s" % manual_path],
                "checked_lines": 0}
    except (OSError, UnicodeDecodeError) as exc:
        return {"status": "error",
                "problems": ["could not read %s: %s" % (manual_path, exc)],
                "checked_lines": 0}
    problems = []
    for hit in find_dashes(text):
        problems.append(
            "line %d: the manual contains an %s; use a plain hyphen "
            "instead" % (hit["line"], hit["kind"]))
    return {"status": "fail" if problems else "pass",
            "problems": problems,
            "checked_lines": len(text.split("\n"))}

# ---------------------------------------------------------------- markdown

CSS = """
@page { size: A4; margin: 20mm 18mm 18mm 18mm; }
body { font-family: -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
       font-size: 11.5pt; line-height: 1.55; color: #1a1a1a; max-width: 100%; }
h1 { font-size: 22pt; margin: 0 0 4pt 0; }
h2 { font-size: 15pt; margin: 20pt 0 6pt 0; padding-top: 10pt;
     border-top: 1px solid #ccc; page-break-after: avoid; }
h3 { font-size: 12.5pt; margin: 14pt 0 4pt 0; page-break-after: avoid; }
p { margin: 0 0 8pt 0; }
ol, ul { margin: 0 0 8pt 0; padding-left: 20pt; }
li { margin-bottom: 3pt; }
code { font-family: "DejaVu Sans Mono", Menlo, Consolas, monospace;
       font-size: 10pt; background: #f0f0f0; padding: 0 3pt; border-radius: 3pt; }
pre { background: #f4f4f4; border: 1px solid #ddd; border-radius: 4pt;
      padding: 8pt 10pt; font-size: 10pt; line-height: 1.45;
      overflow-x: auto; page-break-inside: avoid; }
pre code { background: none; padding: 0; }
a { color: #1a5276; text-decoration: none; word-break: break-all; }
.title-sub { color: #555; font-size: 12pt; margin-bottom: 16pt; }
"""

# The Markdown subset the converter understands. Anything outside
# it renders as plain paragraph text; nothing crashes.
MARKDOWN_SUBSET = ("headings (#, ##, ###), paragraphs, ordered and "
                   "unordered lists, bold, inline code, fenced code "
                   "blocks, bare URLs as links")


def _inline(text):
    """Escape HTML, then apply bold, inline code, and link markup."""
    out = []
    # Split on backtick spans first so code is never re-processed.
    parts = re.split(r"(`[^`]+`)", text)
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            out.append("<code>" + html.escape(part[1:-1]) + "</code>")
            continue
        esc = html.escape(part)
        esc = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", esc)
        esc = re.sub(r"(https?://[^\s)]+)", r'<a href="\1">\1</a>', esc)
        out.append(esc)
    return "".join(out)


def markdown_to_html(md, title=None):
    """Convert the manual's Markdown subset to a styled HTML page.

    The page title comes from the first `# ` heading, or from the
    `title` argument when given. The paragraph right after the
    first heading is styled as a subtitle (that is where the
    version line lives, e.g. "Soldar v0.3.0")."""
    lines = md.split("\n")
    body = []
    page_title = title
    i = 0
    in_code = False
    code_lines = []
    para = []
    list_kind = None  # "ol" or "ul"

    def flush_para():
        nonlocal para
        if para:
            body.append("<p>" + _inline(" ".join(para)) + "</p>")
            para = []

    def flush_list():
        nonlocal list_kind
        if list_kind:
            body.append("</" + list_kind + ">")
            list_kind = None

    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            if in_code:
                body.append("<pre><code>"
                            + html.escape("\n".join(code_lines))
                            + "</code></pre>")
                code_lines = []
                in_code = False
            else:
                flush_para()
                flush_list()
                in_code = True
            i += 1
            continue
        if in_code:
            code_lines.append(line)
            i += 1
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            flush_para()
            flush_list()
            level = len(m.group(1))
            if level == 1 and page_title is None:
                page_title = m.group(2).strip()
            body.append("<h%d>" % level + _inline(m.group(2))
                        + "</h%d>" % level)
            i += 1
            continue
        m = re.match(r"^(\d+)\.\s+(.*)$", line)
        if m:
            flush_para()
            if list_kind != "ol":
                flush_list()
                body.append("<ol>")
                list_kind = "ol"
            body.append("<li>" + _inline(m.group(2)) + "</li>")
            i += 1
            continue
        m = re.match(r"^-\s+(.*)$", line)
        if m:
            flush_para()
            if list_kind != "ul":
                flush_list()
                body.append("<ul>")
                list_kind = "ul"
            body.append("<li>" + _inline(m.group(1)) + "</li>")
            i += 1
            continue
        if line.strip() == "":
            flush_para()
            flush_list()
            i += 1
            continue
        para.append(line.strip())
        i += 1
    flush_para()
    flush_list()
    if in_code:  # an unclosed fence still renders, as a code block
        body.append("<pre><code>" + html.escape("\n".join(code_lines))
                    + "</code></pre>")

    html_body = "\n".join(body)
    # The paragraph right after the h1 is the subtitle.
    html_body = re.sub(
        r"(<h1>[^<]*</h1>)\s*<p>([^<]*)</p>",
        "\\1\n<p class=\"title-sub\">\\2</p>",
        html_body,
        count=1,
    )
    if page_title is None:
        page_title = "Manual"
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<title>" + html.escape(page_title) + "</title>\n<style>\n"
        + CSS + "</style>\n</head>\n<body>\n"
        + html_body
        + "\n</body>\n</html>\n"
    )

# ---------------------------------------------------------------- references

# A backtick span ending in one of these is treated as a file
# reference even with no slash in it (e.g. `install.sh`).
PATH_EXTENSIONS = frozenset([
    ".py", ".md", ".sh", ".desktop", ".json", ".toml", ".txt",
    ".pdf", ".zip", ".png", ".svg", ".html", ".css", ".js", ".ts",
    ".yaml", ".yml", ".ini", ".cfg", ".deb", ".AppImage", ".mp4",
    ".mp3", ".wav", ".ogg", ".csv", ".lock", ".service",
])

# First words of a code line that introduce a path argument.
# Only the first path-like word after one of these is checked,
# except cp/mv where the first path-like word is the source (the
# destination need not exist yet, so it is never checked).
RUNNER_WORDS = frozenset(["bash", "sh", "python3", "python"])
CD_WORDS = frozenset(["cd"])
CHMOD_WORDS = frozenset(["chmod"])
COPY_WORDS = frozenset(["cp", "mv"])
ARCHIVE_WORDS = frozenset(["unzip", "tar"])
COMMAND_WORDS = (RUNNER_WORDS | CD_WORDS | CHMOD_WORDS
                 | COPY_WORDS | ARCHIVE_WORDS)

_VERSION_RE = re.compile(r"v(\d+)\.(\d+)(?:\.(\d+))?")


def _strip_token(token):
    """Drop surrounding punctuation a token picked up in prose."""
    return token.strip("`\"'(),.;:[]{}<> \t")


def _looks_like_path(token):
    """True when a token names a file or folder, not a word."""
    # A span that is only an extension (`.json`, `.soldar.json`)
    # names a file type, not a file. Tested on the raw token:
    # _strip_token eats the leading dot as punctuation.
    raw = token.strip().strip("`\"'")
    if raw.startswith(".") and "/" not in raw:
        return False
    token = _strip_token(token)
    if not token or "://" in token:
        return False
    if token.startswith("-") or token.startswith("$"):
        return False
    if "*" in token or "?" in token:
        return False
    if "<" in token or ">" in token:
        return False
    if "/" in token:
        return True
    lowered = token.lower()
    return any(lowered.endswith(ext) for ext in PATH_EXTENSIONS)


def _skippable_path(token):
    """True when a path must NOT be checked against the tree:
    home paths (~/...), absolute system paths (/usr/...), and
    URLs. The tree only holds the project's own relative paths."""
    token = _strip_token(token)
    return (token.startswith("~/") or token.startswith("~")
            or token.startswith("/") or "://" in token)


def _code_units(md):
    """Code the manual shows, as (text, line number) pairs: every
    inline backtick span, and every non-empty line of every fenced
    code block. Fenced lines keep their line numbers so a failure
    can point at the exact line."""
    units = []
    lines = md.split("\n")
    in_code = False
    for number, line in enumerate(lines, start=1):
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            if line.strip():
                units.append((line.strip(), number))
            continue
        for match in re.finditer(r"`([^`]+)`", line):
            units.append((match.group(1).strip(), number))
    return units


def _paths_from_unit(text):
    """Path references inside one code span or code line."""
    words = text.split()
    if not words:
        return []
    first = _strip_token(words[0])
    # A bare extension on its own (`.json`, `.soldar.json`) names
    # a file type, not a file. Tested on the raw word: stripping
    # eats the leading dot as punctuation.
    raw_first = words[0].strip("`\"'")
    if raw_first.startswith(".") and "/" not in raw_first:
        return []
    # A bare path on its own: `install.sh`, `./run.sh`, `src/app.py`.
    if first not in COMMAND_WORDS and _looks_like_path(first):
        return [first]
    # A command that names a path: take the first path-like word
    # after the command word, skipping flags and (for chmod) the
    # mode. cp/mv only check the source, never the destination.
    # `cd` is special: its argument is always a folder, even one
    # with no slash and no extension (`cd tools`).
    if first in COMMAND_WORDS:
        for word in words[1:]:
            clean = _strip_token(word)
            if not clean or clean.startswith("-"):
                continue
            if first in CHMOD_WORDS and re.fullmatch(
                    r"[0-7]{3,4}|[ugoa]*[+-=][rwx]+", clean):
                continue
            if _looks_like_path(clean) or first in CD_WORDS:
                return [clean]
            # The first non-flag word is not a path: nothing to check
            # (e.g. `ls -la`, `python3 -m pytest`).
            return []
    return []


def extract_references(md):
    """Every path the manual cites, as {"path": str, "line": int}
    dicts, in the order they appear. Home paths, absolute paths,
    and URLs are not returned: they do not live in the tree."""
    refs = []
    seen = set()
    for text, number in _code_units(md):
        for path in _paths_from_unit(text):
            path = _strip_token(path)
            if path.startswith("./"):
                path = path[2:]
            if not path or _skippable_path(path):
                continue
            key = (path, number)
            if key in seen:
                continue
            seen.add(key)
            refs.append({"path": path, "line": number})
    return refs


def _normalize_version(match):
    """("0", "3", None) -> "0.3.0"; ("1", "2", "3") -> "1.2.3"."""
    major, minor, patch = match
    return "%s.%s.%s" % (major, minor, patch or "0")


def extract_versions(md, project=None):
    """Version strings the manual cites, as {"version": str,
    "line": int} dicts.

    A version with a leading `v` (v0.3.0) is always checked: project
    releases are tagged that way. A bare version (0.3.0) is only
    checked when it directly follows the project name ("SampleApp
    0.3.0", "SampleApp version 0.3.0"), so dependency versions
    ("Node 20.1.0", "Python 3.12.1") never trip the check, even on
    a line that also names the project. Write another project's
    version without the `v` and it is skipped too."""
    found = []
    seen = set()
    bare_re = None
    if project:
        bare_re = re.compile(
            re.escape(project)
            + r"[\s:]*(?:version\s+|v)?(\d+)\.(\d+)\.(\d+)",
            re.IGNORECASE)
    for number, line in enumerate(md.split("\n"), start=1):
        for match in _VERSION_RE.finditer(line):
            version = _normalize_version(match.groups())
            key = (version, number)
            if key not in seen:
                seen.add(key)
                found.append({"version": version, "line": number})
        if bare_re is not None:
            for match in bare_re.finditer(line):
                version = _normalize_version(match.groups())
                key = (version, number)
                if key not in seen:
                    seen.add(key)
                    found.append({"version": version, "line": number})
    return found


def find_tree_version(tree, version_file=None):
    """The project tree's own version, as (version, source) or
    (None, None) when the tree names no version anywhere.

    Looked for, in order: an explicit --version-file, a VERSION
    file in the tree root, the first version heading in
    CHANGELOG.md, pyproject.toml, package.json."""
    candidates = []
    if version_file:
        candidates.append((Path(version_file), "version file"))
    root = Path(tree)
    candidates.append((root / "VERSION", "VERSION"))
    candidates.append((root / "CHANGELOG.md", "CHANGELOG.md"))
    candidates.append((root / "pyproject.toml", "pyproject.toml"))
    candidates.append((root / "package.json", "package.json"))
    for path, label in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if path.name in ("pyproject.toml", "package.json"):
            match = re.search(r'"version"\s*[:=]\s*"v?([\d.]+)"', text)
            if not match:
                match = re.search(r"version\s*=\s*\"v?([\d.]+)\"", text)
        else:
            match = re.search(r"v?(\d+)\.(\d+)(?:\.(\d+))?", text)
            if match:
                return _normalize_version(match.groups()), label
            continue
        if match:
            parts = match.group(1).split(".")
            while len(parts) < 3:
                parts.append("0")
            return ".".join(parts[:3]), label
    return None, None


_SKIP_RE = re.compile(r"<!--\s*manual-pdf-skip:\s*(.*?)-->")


def extract_skips(md):
    """Paths the manual itself exempts from the existence check,
    from `<!-- manual-pdf-skip: update/, cache.db -->` comments.
    For files the app creates when it runs (data folders, logs,
    downloaded updates): they are real, but they are not in the
    tree. The exemption lives in the manual, where the next
    reader can see it, and the check reports how many it skipped."""
    skips = set()
    for match in _SKIP_RE.finditer(md):
        for item in match.group(1).split(","):
            item = item.strip().strip("`")
            if item.startswith("./"):
                item = item[2:]
            if item:
                skips.add(item)
    return skips


def check_references(manual_path, tree, project=None, version_file=None):
    """Check one manual against one project tree.

    Returns {"status": "pass" | "fail" | "error",
    "problems": [plain-words strings],
    "warnings": [plain-words strings],
    "checked_paths": int, "checked_versions": int,
    "skipped_paths": int}.
    "error" means the manual or the tree could not be read at all.
    A warning never fails the check: it names something the tool
    could not verify, so the author can confirm it by hand."""
    manual = Path(manual_path)
    root = Path(tree)
    if not manual.is_file():
        return {"status": "error",
                "problems": ["no such manual file: %s" % manual_path],
                "warnings": [], "checked_paths": 0,
                "checked_versions": 0, "skipped_paths": 0}
    if not root.is_dir():
        return {"status": "error",
                "problems": ["no such project tree: %s" % tree],
                "warnings": [], "checked_paths": 0,
                "checked_versions": 0, "skipped_paths": 0}
    try:
        md = manual.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {"status": "error",
                "problems": ["could not read %s: %s" % (manual_path, exc)],
                "warnings": [], "checked_paths": 0,
                "checked_versions": 0, "skipped_paths": 0}
    if project is None:
        project = root.name

    problems = []
    warnings = []
    refs = extract_references(md)
    skips = extract_skips(md)
    for ref in refs:
        if ref["path"] in skips:
            continue
        # A cited release zip whose name carries a version
        # (soldar-v0.3.0.zip) lives on the Releases page, not in
        # the tree: it is verified by the version check below,
        # not by existence.
        if (ref["path"].lower().endswith(".zip")
                and re.search(r"\d+\.\d+", ref["path"])):
            continue
        if not (root / ref["path"]).exists():
            problems.append(
                "line %d: the manual names '%s' but there is no such "
                "file or folder in the project tree"
                % (ref["line"], ref["path"]))
    versions = extract_versions(md, project)
    tree_version, source = find_tree_version(tree, version_file)
    if versions and tree_version is None:
        warnings.append(
            "the manual cites %d version(s) but the project tree "
            "names no version (no VERSION file, no version heading "
            "in CHANGELOG.md, no version in pyproject.toml or "
            "package.json), so the versions could not be checked"
            % len(versions))
    elif tree_version is not None:
        for item in versions:
            if item["version"] != tree_version:
                problems.append(
                    "line %d: the manual says v%s but the project "
                    "tree is at v%s (from %s)"
                    % (item["line"], item["version"], tree_version,
                       source))
    cited = {ref["path"] for ref in refs}
    return {"status": "fail" if problems else "pass",
            "problems": problems,
            "warnings": warnings,
            "checked_paths": len(cited - skips),
            "checked_versions": len(versions),
            "skipped_paths": len(cited & skips)}

# ---------------------------------------------------------------- render

_CHROMIUM_PATH_NAMES = ["chromium-headless-shell", "chromium",
                        "chromium-browser", "google-chrome",
                        "google-chrome-stable"]


def find_chromium(explicit=None):
    """Find a headless Chromium binary, or None.

    Search order: the `explicit` argument (a --chromium flag), the
    MANUAL_PDF_CHROMIUM environment variable, the Playwright
    browser cache (~/.cache/ms-playwright -- the headless shell,
    then a full Chromium), then PATH. The Playwright cache is
    searched even though this tool never imports Playwright: that
    cache is where the SOLDAR manual's Chromium already lives."""
    if explicit:
        path = Path(explicit).expanduser()
        if path.is_file() and os.access(str(path), os.X_OK):
            return str(path)
        return None
    env = os.environ.get("MANUAL_PDF_CHROMIUM")
    if env:
        path = Path(env).expanduser()
        if path.is_file() and os.access(str(path), os.X_OK):
            return str(path)
    cache = Path.home() / ".cache" / "ms-playwright"
    patterns = [
        "chromium_headless_shell-*/chrome-headless-shell-linux64/"
        "chrome-headless-shell",
        "chromium-*/chrome-linux/chrome",
    ]
    for pattern in patterns:
        matches = sorted(glob.glob(str(cache / pattern)))
        for candidate in reversed(matches):
            if os.access(candidate, os.X_OK):
                return candidate
    for name in _CHROMIUM_PATH_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return None


def count_pdf_pages(pdf_path):
    """Page count of a PDF file, read from its own bytes: one
    /Type /Page object per page, minus the /Type /Pages tree
    object. Returns 0 when the file cannot be read."""
    try:
        data = Path(pdf_path).read_bytes()
    except OSError:
        return 0
    return data.count(b"/Type /Page") - data.count(b"/Type /Pages")


def render_pdf(manual_path, out_path, chromium=None, title=None,
               keep_html=False, timeout=RENDER_TIMEOUT):
    """Render one manual to a PDF.

    Runs the em-dash check first (the SOLDAR builder did the same):
    a manual with dashes is not rendered. Returns {"status":
    "pass" | "fail" | "error", "problems": [...], "pages": int,
    "bytes": int, "chromium": str | None}. "error" means the step
    could not run (missing or unreadable input); "fail" means
    it ran and something was wrong (dashes, Chromium missing,
    Chromium errored, the PDF came out wrong)."""
    manual = Path(manual_path)
    if not manual.is_file():
        return {"status": "error",
                "problems": ["no such manual file: %s" % manual_path],
                "pages": 0, "bytes": 0, "chromium": None}
    dashes = check_em_dashes(manual_path)
    if dashes["status"] == "error":
        return {"status": "error", "problems": dashes["problems"],
                "pages": 0, "bytes": 0, "chromium": None}
    if dashes["status"] == "fail":
        return {"status": "fail",
                "problems": ["the manual has dashes to fix before "
                             "it can be rendered:"] + dashes["problems"],
                "pages": 0, "bytes": 0, "chromium": None}
    chrome = find_chromium(chromium)
    if chrome is None:
        return {"status": "fail",
                "problems": [CHROMIUM_INSTALL_HINT],
                "pages": 0, "bytes": 0, "chromium": None}
    try:
        md = manual.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {"status": "error",
                "problems": ["could not read %s: %s" % (manual_path, exc)],
                "pages": 0, "bytes": 0, "chromium": chrome}
    out = Path(out_path)
    try:
        if out.parent and str(out.parent) != "":
            out.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"status": "error",
                "problems": ["could not create the folder for %s: %s"
                             % (out_path, exc)],
                "pages": 0, "bytes": 0, "chromium": chrome}
    page = markdown_to_html(md, title=title)
    with tempfile.TemporaryDirectory(prefix="manual-pdf.") as tmp:
        html_path = Path(tmp) / "manual.html"
        html_path.write_text(page, encoding="utf-8")
        cmd = [chrome, "--headless", "--no-sandbox", "--disable-gpu",
               "--no-pdf-header-footer",
               "--print-to-pdf=%s" % out,
               "file://%s" % html_path]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"status": "fail",
                    "problems": ["Chromium did not finish the PDF "
                                 "within %d seconds" % timeout],
                    "pages": 0, "bytes": 0, "chromium": chrome}
        except OSError as exc:
            return {"status": "error",
                    "problems": ["could not run Chromium at %s: %s"
                                 % (chrome, exc)],
                    "pages": 0, "bytes": 0, "chromium": chrome}
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            tail = "\n".join(detail.split("\n")[-3:]) if detail else ""
            return {"status": "fail",
                    "problems": ["Chromium could not print the PDF"
                                 + (": " + tail if tail else "")],
                    "pages": 0, "bytes": 0, "chromium": chrome}
    if not out.is_file():
        return {"status": "fail",
                "problems": ["Chromium said it printed, but no PDF "
                             "appeared at %s" % out_path],
                "pages": 0, "bytes": 0, "chromium": chrome}
    head = out.read_bytes()[:4]
    if head != b"%PDF":
        return {"status": "fail",
                "problems": ["the file at %s is not a PDF" % out_path],
                "pages": 0, "bytes": out.stat().st_size,
                "chromium": chrome}
    if keep_html:
        out.with_suffix(".html").write_text(page, encoding="utf-8")
    return {"status": "pass", "problems": [],
            "pages": count_pdf_pages(out),
            "bytes": out.stat().st_size, "chromium": chrome}


def build(manual_path, tree, out_path, project=None, version_file=None,
          chromium=None, title=None, keep_html=False):
    """The full chain: check, then emdash, then render. Stops at
    the first failure. Returns the failing step's result dict,
    plus "step" naming which step it was; on success, the render
    result plus the check counts."""
    checked = check_references(manual_path, tree, project=project,
                               version_file=version_file)
    if checked["status"] != "pass":
        checked = dict(checked)
        checked["step"] = "check"
        return checked
    dashes = check_em_dashes(manual_path)
    if dashes["status"] != "pass":
        dashes = dict(dashes)
        dashes["step"] = "emdash"
        return dashes
    rendered = render_pdf(manual_path, out_path, chromium=chromium,
                          title=title, keep_html=keep_html)
    rendered = dict(rendered)
    rendered["step"] = "render"
    rendered["checked_paths"] = checked["checked_paths"]
    rendered["checked_versions"] = checked["checked_versions"]
    rendered["skipped_paths"] = checked["skipped_paths"]
    rendered["warnings"] = checked["warnings"]
    return rendered

# ---------------------------------------------------------------- debug log

def _logger(log_dir):
    """A DebugLogger wired to this app, or None when the layer is
    unavailable. Imported here, not at module top, so the check
    path never pays the debug layer's import cost (the T36
    pattern). The log dir is a temp dir owned by the caller, so
    no logs/ directory is left behind."""
    try:
        from debug_log import DebugLogger
    except ImportError:  # the module copied without its debug_log.py
        return None
    try:
        logger = DebugLogger(APP_SLUG, VERSION, log_dir=log_dir)
    except Exception:
        return None
    logger.set_setting("app_version", VERSION)
    return logger


def _close_logger(logger):
    for handler in list(logger.logger.handlers):
        try:
            handler.close()
        finally:
            logger.logger.removeHandler(handler)


def write_debug_report(out=None):
    """Write a T21 debug report; returns the path, or None when
    the debug layer is not available."""
    if out is None:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        out = "debug-report-%s-%s.txt" % (APP_SLUG, stamp)
    with tempfile.TemporaryDirectory(prefix="mpb-debug.") as tmp:
        logger = _logger(tmp)
        if logger is None:
            return None
        try:
            logger.info("debug report requested")
            return logger.generate_report(out)
        finally:
            _close_logger(logger)

# ---------------------------------------------------------------- CLI

def _print_problems(problems):
    for problem in problems:
        print(problem)


def cmd_check(args):
    result = check_references(args.manual, args.tree,
                              project=args.project,
                              version_file=args.version_file)
    if result["status"] == "error":
        _print_problems(result["problems"])
        return EXIT_CANNOT_RUN
    for warning in result["warnings"]:
        print("warning: " + warning)
    if result["status"] == "fail":
        _print_problems(result["problems"])
        print("check FAILED: %d problem(s); %d path(s) and %d "
              "version(s) were checked"
              % (len(result["problems"]), result["checked_paths"],
                 result["checked_versions"]))
        return EXIT_FAILED
    print("OK: %d path(s) and %d version(s) checked against %s; "
          "everything the manual cites is in the tree"
          % (result["checked_paths"], result["checked_versions"],
             args.tree))
    if result["skipped_paths"]:
        print("note: %d path(s) skipped, exempted by the manual's "
              "own manual-pdf-skip comment" % result["skipped_paths"])
    return EXIT_OK


def cmd_emdash(args):
    result = check_em_dashes(args.manual)
    if result["status"] == "error":
        _print_problems(result["problems"])
        return EXIT_CANNOT_RUN
    if result["status"] == "fail":
        _print_problems(result["problems"])
        print("emdash check FAILED: %d dash(es) to fix"
              % len(result["problems"]))
        return EXIT_FAILED
    print("OK: no em-dashes or en-dashes in %s (%d lines checked)"
          % (args.manual, result["checked_lines"]))
    return EXIT_OK


def cmd_render(args):
    result = render_pdf(args.manual, args.out, chromium=args.chromium,
                        title=args.title, keep_html=args.keep_html)
    if result["status"] == "error":
        _print_problems(result["problems"])
        return EXIT_CANNOT_RUN
    if result["status"] == "fail":
        _print_problems(result["problems"])
        return EXIT_FAILED
    print("Wrote %s (%d pages, %d bytes)"
          % (args.out, result["pages"], result["bytes"]))
    return EXIT_OK


def cmd_build(args):
    result = build(args.manual, args.tree, args.out,
                   project=args.project, version_file=args.version_file,
                   chromium=args.chromium, title=args.title,
                   keep_html=args.keep_html)
    for warning in result.get("warnings", []):
        print("warning: " + warning)
    if result["status"] != "pass":
        print("build stopped at the %s step:" % result.get("step", "?"))
        _print_problems(result["problems"])
        return (EXIT_CANNOT_RUN if result["status"] == "error"
                else EXIT_FAILED)
    print("Built %s (%d pages, %d bytes). %d path(s) and %d "
          "version(s) checked, no dashes, PDF rendered."
          % (args.out, result["pages"], result["bytes"],
             result["checked_paths"], result["checked_versions"]))
    if result.get("skipped_paths"):
        print("note: %d path(s) skipped, exempted by the manual's "
              "own manual-pdf-skip comment" % result["skipped_paths"])
    return EXIT_OK


def cmd_debug_report(args):
    path = write_debug_report(args.out)
    if path is None:
        print("error: the debug log layer is not available "
              "(debug_log.py is missing).", file=sys.stderr)
        return EXIT_CANNOT_RUN
    print("debug report: %s" % path)
    return EXIT_OK


def build_parser():
    parser = argparse.ArgumentParser(
        prog="manual_pdf.py",
        description="Check a MANUAL.md against its project tree, "
                    "then render it to a styled A4 PDF. The three "
                    "pieces: check, emdash, render. `build` runs "
                    "all three in order.")
    parser.add_argument("--version", action="version",
                        version="manual-pdf-builder %s" % VERSION)
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("check", help="verify every path, script, and "
                                     "version the manual cites "
                                     "against the project tree")
    p.add_argument("manual", help="path to MANUAL.md")
    p.add_argument("--tree", required=True,
                   help="the project tree to check against")
    p.add_argument("--project", default=None,
                   help="project name (default: the tree folder's "
                        "name); bare versions are only checked on "
                        "lines that name the project")
    p.add_argument("--version-file", default=None,
                   help="file holding the project's version, if it "
                        "is not in VERSION / CHANGELOG.md / "
                        "pyproject.toml / package.json")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("emdash", help="fail if the manual contains "
                                      "an em-dash or an en-dash")
    p.add_argument("manual", help="path to MANUAL.md")
    p.set_defaults(func=cmd_emdash)

    p = sub.add_parser("render", help="render MANUAL.md to a styled "
                                      "A4 PDF via headless Chromium")
    p.add_argument("manual", help="path to MANUAL.md")
    p.add_argument("--out", required=True, help="the PDF to write")
    p.add_argument("--chromium", default=None,
                   help="path to a headless Chromium binary "
                        "(default: search the Playwright cache and "
                        "PATH)")
    p.add_argument("--title", default=None,
                   help="page title (default: the first heading)")
    p.add_argument("--keep-html", action="store_true",
                   help="also write the styled HTML next to the PDF")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("build", help="check, then emdash, then "
                                     "render; stops at the first "
                                     "failure")
    p.add_argument("manual", help="path to MANUAL.md")
    p.add_argument("--tree", required=True,
                   help="the project tree to check against")
    p.add_argument("--out", required=True, help="the PDF to write")
    p.add_argument("--project", default=None,
                   help="project name (default: the tree folder's "
                        "name)")
    p.add_argument("--version-file", default=None,
                   help="file holding the project's version")
    p.add_argument("--chromium", default=None,
                   help="path to a headless Chromium binary")
    p.add_argument("--title", default=None,
                   help="page title (default: the first heading)")
    p.add_argument("--keep-html", action="store_true",
                   help="also write the styled HTML next to the PDF")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("debug-report", help="write a T21 debug report")
    p.add_argument("--out", default=None,
                   help="report path (default: a timestamped file "
                        "in the current folder)")
    p.set_defaults(func=cmd_debug_report)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return EXIT_CANNOT_RUN
    try:
        return func(args)
    except Exception as exc:  # never a traceback, always plain words
        print("error: %s could not run: %s"
              % (getattr(args, "command", "the step"), exc))
        return EXIT_CANNOT_RUN


if __name__ == "__main__":
    sys.exit(main())
