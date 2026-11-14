"""Read text out of images (and PDFs) with Tesseract.

The engine shells out to the `tesseract` binary: no Python
bindings, no network. `tesseract <image> stdout -l <lang>`
writes the extracted text to stdout; stderr is captured
separately so a tesseract complaint never lands in the text.
(The `-l` flag is tesseract's own language option: this build
rejects the `--lang` spelling with "unknown command line
argument".)

The binary is found with shutil.which("tesseract"); the
OCR_TESSERACT environment variable overrides it with an
absolute path (the tests point it at a stub). PDFs go through
pdftoppm at 300 dpi (OCR_PDFTOPPM overrides that path the same
way); each page is OCRed and the pages are joined with a
"--- page N ---" marker.

Every failure is an OCRError with a plain message naming the
file and, where it helps, the install command. No traceback
ever escapes to the user: the CLI prints the message plainly.
"""

import os
import shutil
import subprocess
import tempfile

TESSERACT_TIMEOUT = 120
PDFTOPPM_TIMEOUT = 120

TESSERACT_MISSING = (
    "Tesseract is not installed. "
    "Install it with: sudo apt install tesseract-ocr")
PDFTOPPM_MISSING = (
    "pdftoppm is not installed. "
    "Install it with: sudo apt install poppler-utils")


class OCRError(Exception):
    """A plain, user-readable OCR failure."""


def find_tesseract():
    """The tesseract binary path, or raise OCRError."""
    override = os.environ.get("OCR_TESSERACT")
    if override:
        if os.path.isfile(override) and os.access(override, os.X_OK):
            return override
        raise OCRError(TESSERACT_MISSING)
    path = shutil.which("tesseract")
    if path is None:
        raise OCRError(TESSERACT_MISSING)
    return path


def find_pdftoppm():
    """The pdftoppm binary path, or raise OCRError."""
    override = os.environ.get("OCR_PDFTOPPM")
    if override:
        if os.path.isfile(override) and os.access(override, os.X_OK):
            return override
        raise OCRError(PDFTOPPM_MISSING)
    path = shutil.which("pdftoppm")
    if path is None:
        raise OCRError(PDFTOPPM_MISSING)
    return path


def _check_readable(path):
    """Raise OCRError naming the file when it cannot be read."""
    if not os.path.isfile(path):
        raise OCRError("Could not read %s: not a file" % path)
    try:
        with open(path, "rb") as fh:
            fh.read(1)
    except OSError as exc:
        raise OCRError("Could not read %s: %s" % (path, exc))


def _run(cmd, timeout, path, what):
    """Run a command, returning stdout; failures are OCRError.

    A nonzero exit surfaces the tool's own stderr plainly. A
    timeout names the file and the seconds allowed.
    """
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        raise OCRError("Timed out reading %s after %d seconds"
                       % (path, timeout))
    except OSError as exc:
        raise OCRError("Could not run %s: %s" % (what, exc))
    if proc.returncode != 0:
        detail = proc.stderr.strip()
        if detail:
            raise OCRError(detail)
        raise OCRError("%s failed on %s" % (what, path))
    return proc.stdout


def ocr_image(path, lang="eng", timeout=TESSERACT_TIMEOUT):
    """Extract the text from one image file."""
    _check_readable(path)
    binary = find_tesseract()
    text = _run([binary, path, "stdout", "-l", lang],
                timeout, path, "tesseract")
    return text.replace("\x0c", "")


def ocr_pdf(path, lang="eng", timeout=TESSERACT_TIMEOUT):
    """Extract the text from a PDF; return (text, page count).

    pdftoppm renders each page to PNG at 300 dpi in a temp dir,
    tesseract reads each page, and the pages are joined with a
    "--- page N ---" marker line before each page's text.
    """
    _check_readable(path)
    pdftoppm = find_pdftoppm()
    binary = find_tesseract()
    with tempfile.TemporaryDirectory(prefix="ocr-reader-") as tmp:
        prefix = os.path.join(tmp, "page")
        _run([pdftoppm, "-png", "-r", "300", path, prefix],
             PDFTOPPM_TIMEOUT, path, "pdftoppm")
        pages = sorted(
            name for name in os.listdir(tmp)
            if name.startswith("page-") and name.endswith(".png"))
        if not pages:
            raise OCRError("No pages found in %s" % path)
        parts = []
        for number, name in enumerate(pages, start=1):
            page_path = os.path.join(tmp, name)
            text = _run([binary, page_path, "stdout", "-l",
                         lang], timeout, path, "tesseract")
            parts.append("--- page %d ---\n%s"
                         % (number, text.replace("\x0c", "")
                            .rstrip("\n")))
        return "\n".join(parts) + "\n", len(pages)


def read_file(path, lang="eng", timeout=TESSERACT_TIMEOUT):
    """Read one file; return the result dict the CLI prints.

    Keys: path, file, text, pages, language, error. error is
    None on success, else a plain string; text is "" and pages
    0 when the read failed.
    """
    result = {"path": path, "file": os.path.basename(path),
              "text": "", "pages": 0, "language": lang,
              "error": None}
    try:
        if path.lower().endswith(".pdf"):
            text, pages = ocr_pdf(path, lang=lang, timeout=timeout)
        else:
            text = ocr_image(path, lang=lang, timeout=timeout)
            pages = 1
    except OCRError as exc:
        result["error"] = str(exc)
        return result
    result["text"] = text
    result["pages"] = pages
    return result


def read_files(paths, lang="eng", timeout=TESSERACT_TIMEOUT):
    """Read several files; one result dict per input file."""
    return [read_file(path, lang=lang, timeout=timeout)
            for path in paths]
