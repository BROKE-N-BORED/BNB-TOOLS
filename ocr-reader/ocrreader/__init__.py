"""OCR Reader: text out of screenshots and scans.

Reads the text out of a picture (screenshot, scanned page, photo
of notes) with Tesseract, on the machine, with no network and no
account. The chain is small tools: read extracts text, clean
tidies it, view shows it in a window.
"""

__version__ = "0.1.0"
APP_NAME = "OCR Reader"
APP_SLUG = "ocr-reader"
