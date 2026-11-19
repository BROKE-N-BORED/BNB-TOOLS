"""Shared fixtures for the manual-pdf-builder tests.

The sample manual and fake project tree live here so the test
file stays readable. No em-dash bytes anywhere in this file:
dashes are built with chr() where a test needs one.
"""
from pathlib import Path

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)

SAMPLE_MANUAL = """# SampleApp: How to Use It

SampleApp v0.1.0

SampleApp is a small fake program used by the tests.

## 1. Installing

1. Extract the release ZIP.
2. In the extracted folder, run `bash install.sh`.
3. The app's parts live in `src/app.py` and `src/helper.py`.

## 2. Running

Double-click the icon, or run `python3 src/app.py` from the
project folder. The rules are in `docs/rules.md`. Your data
stays in `~/.local/sampleapp`, which is your home folder, not
the project tree. More at https://example.com/sampleapp

## 3. Removing

Run `bash uninstall.sh` and the app goes away cleanly.
"""


def make_tree(root):
    """Build the fake project tree the sample manual describes.
    Returns the tree dir (named sampleapp so the default project
    name matches the manual's version line)."""
    tree = Path(root) / "sampleapp"
    (tree / "src").mkdir(parents=True)
    (tree / "docs").mkdir()
    (tree / "install.sh").write_text("#!/bin/sh\necho install\n",
                                     encoding="utf-8")
    (tree / "uninstall.sh").write_text("#!/bin/sh\necho remove\n",
                                       encoding="utf-8")
    (tree / "src" / "app.py").write_text("print('app')\n",
                                         encoding="utf-8")
    (tree / "src" / "helper.py").write_text("print('help')\n",
                                            encoding="utf-8")
    (tree / "docs" / "rules.md").write_text("# Rules\n",
                                            encoding="utf-8")
    (tree / "CHANGELOG.md").write_text("## 0.1.0\n\nFirst release.\n",
                                       encoding="utf-8")
    return tree


def write_manual(root, text=SAMPLE_MANUAL, name="MANUAL.md"):
    path = Path(root) / name
    path.write_text(text, encoding="utf-8")
    return path
