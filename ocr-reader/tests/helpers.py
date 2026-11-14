"""Fixture generators for the ocr-reader tests.

Every fixture is generated on the fly with PIL; no binary
fixtures live in the tree. The paragraph fixture is the same
text the live accuracy test measures against. The stub scripts
stand in for the tesseract and pdftoppm binaries so most tests
never touch the real ones.
"""

import os

from PIL import Image, ImageDraw, ImageFont

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_AVAILABLE = os.path.isfile(FONT_PATH)
FONT_SIZE = 36

PARAGRAPH_LINES = (
    "The quick brown fox jumps over the lazy dog.",
    "Pack my box with five dozen liquor jugs, please.",
    "How vexingly quick daft zebras jump! 12345 67890.",
    "Bright vixens jump; dozy fowl quack. Call (555) 867-5309.",
    "The five boxing wizards jump quickly at 3:30 pm.",
)

PROBE_LINES = (
    "The quick brown fox jumps",
    "over the lazy dog. 12345",
)


def render_text_image(lines, path, font_size=FONT_SIZE):
    """Render lines of black text on white; return the path.

    Raises RuntimeError when DejaVuSans is missing; tests that
    need this fixture skip on FONT_AVAILABLE instead.
    """
    if not FONT_AVAILABLE:
        raise RuntimeError("DejaVuSans is not installed")
    font = ImageFont.truetype(FONT_PATH, font_size)
    sizes = [font.getbbox(line) for line in lines]
    widths = [box[2] - box[0] for box in sizes]
    heights = [box[3] - box[1] for box in sizes]
    pad = 20
    line_gap = 12
    width = max(widths) + 2 * pad
    height = sum(heights) + line_gap * (len(lines) - 1) + 2 * pad
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    y = pad
    for line, h in zip(lines, heights):
        draw.text((pad, y), line, font=font, fill="black")
        y += h + line_gap
    image.save(path, "PNG")
    return path


def render_paragraph_pdf(path):
    """Render the paragraph fixture as a one-page PDF."""
    image_path = path + ".png"
    render_text_image(PARAGRAPH_LINES, image_path)
    with Image.open(image_path) as image:
        image.save(path, "PDF", resolution=300.0)
    os.remove(image_path)
    return path


def word_accuracy(expected_text, got_text):
    """Words matching in order / total expected words."""
    expected = expected_text.split()
    got = got_text.split()
    if not expected:
        return 1.0 if not got else 0.0
    matches = sum(1 for a, b in zip(expected, got) if a == b)
    return matches / len(expected)


def _shell_quote(text):
    """Single-quote a string for a shell script."""
    return "'" + text.replace("'", "'\\''") + "'"


def _write_script(path, lines):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(path, 0o755)
    return path


def make_fake_tesseract(directory, text="hello world\n",
                        fail_langs=None, sleep_seconds=0,
                        exit_code=0, stderr_text=""):
    """Write a stub `tesseract` script; return its path.

    The stub prints canned text for `tesseract <img> stdout
    -l <lang>`. fail_langs maps a language to the stderr the
    stub prints (and exit 1) when asked for it. stderr_text is
    printed to stderr even on success, to prove the engine keeps
    stderr out of the extracted text.
    """
    fail_langs = fail_langs or {}
    canned = os.path.join(directory, "canned.txt")
    with open(canned, "w", encoding="utf-8") as fh:
        fh.write(text)
    lines = ["#!/bin/sh"]
    if sleep_seconds:
        lines.append("sleep %d" % sleep_seconds)
    lines.append("lang=\"\"")
    lines.append("prev=\"\"")
    lines.append("for arg in \"$@\"; do")
    lines.append("  if [ \"$prev\" = \"-l\" ]; then lang=\"$arg\"; fi")
    lines.append("  prev=\"$arg\"")
    lines.append("done")
    for lang, message in sorted(fail_langs.items()):
        lines.append("if [ \"$lang\" = %s ]; then" % _shell_quote(lang))
        lines.append("  printf '%%s\\n' %s >&2"
                     % _shell_quote(message))
        lines.append("  exit 1")
        lines.append("fi")
    if stderr_text:
        lines.append("printf '%%s\\n' %s >&2"
                     % _shell_quote(stderr_text))
    if exit_code:
        lines.append("exit %d" % exit_code)
    lines.append("cat %s" % _shell_quote(canned))
    return _write_script(os.path.join(directory, "tesseract"), lines)


def make_fake_pdftoppm(directory, pages=2):
    """Write a stub `pdftoppm`; return its path.

    The stub ignores its input and creates <prefix>-01.png ...
    <prefix>-NN.png (empty files: the stub tesseract never looks
    at the image bytes). Called as `pdftoppm -png -r 300 <pdf>
    <prefix>`, so the prefix is $5.
    """
    lines = ["#!/bin/sh",
             "prefix=\"$5\"",
             "i=1",
             "while [ $i -le %d ]; do" % pages,
             "  : > \"$prefix-$(printf %02d $i).png\"",
             "  i=$((i + 1))",
             "done"]
    return _write_script(os.path.join(directory, "pdftoppm"), lines)
