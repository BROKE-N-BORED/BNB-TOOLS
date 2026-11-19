#!/usr/bin/env python3
"""Prove each piece of manual_pdf.py standalone and chained.

Builds a fake project tree and a sample MANUAL.md in a temp dir,
then runs the check, the emdash check, and the render against
them, plus the full `build` chain. No network. The render uses
the real headless Chromium when one is installed, and says so
plainly when none is.

  python3 demo.py            # the full chain
  python3 demo.py --pieces   # each piece alone, one at a time
"""
import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import manual_pdf as mp

SAMPLE_MANUAL = """# SampleApp: How to Use It

SampleApp v0.1.0

SampleApp is a small fake program that exists only for this demo.

## 1. Installing

1. Extract the release ZIP.
2. In the extracted folder, run `bash install.sh`.
3. The app's parts live in `src/app.py` and `src/helper.py`.

## 2. Running

Double-click the icon, or run `python3 src/app.py` from the
project folder. The rules the app follows are in `docs/rules.md`.

## 3. Removing

Run `bash uninstall.sh` and the app goes away cleanly.
"""


def make_fixture(root):
    """A fake project tree + manual under `root`. Returns
    (tree_dir, manual_path, pdf_path)."""
    tree = root / "sampleapp"
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
    manual = root / "MANUAL.md"
    manual.write_text(SAMPLE_MANUAL, encoding="utf-8")
    return tree, manual, root / "SampleApp-Manual.pdf"


def run_pieces(root):
    tree, manual, pdf = make_fixture(root)
    print("== piece 1: check ==")
    result = mp.check_references(str(manual), str(tree))
    print("status:", result["status"], "| paths:",
          result["checked_paths"], "| versions:",
          result["checked_versions"])
    for problem in result["problems"]:
        print("  " + problem)
    print("== piece 2: emdash ==")
    result = mp.check_em_dashes(str(manual))
    print("status:", result["status"], "| lines:",
          result["checked_lines"])
    print("== piece 3: render ==")
    result = mp.render_pdf(str(manual), str(pdf))
    print("status:", result["status"], "| pages:", result["pages"],
          "| bytes:", result["bytes"])
    for problem in result["problems"]:
        print("  " + problem)
    return 0


def run_chain(root):
    tree, manual, pdf = make_fixture(root)
    print("== the chain: build ==")
    result = mp.build(str(manual), str(tree), str(pdf))
    print("status:", result["status"], "| step:", result.get("step"))
    if result["status"] == "pass":
        print("paths checked:", result["checked_paths"],
              "| versions checked:", result["checked_versions"],
              "| pages:", result["pages"], "| bytes:", result["bytes"])
        print("PDF:", pdf)
    for problem in result.get("problems", []):
        print("  " + problem)
    return 0 if result["status"] == "pass" else 1


def main():
    parser = argparse.ArgumentParser(
        description="Prove the manual-pdf-builder pieces.")
    parser.add_argument("--pieces", action="store_true",
                        help="run each piece alone instead of the chain")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="mpb-demo.") as tmp:
        root = Path(tmp)
        if args.pieces:
            return run_pieces(root)
        return run_chain(root)


if __name__ == "__main__":
    sys.exit(main())
