"""Tests for photo-palette (BNB-TOOLS T35).

All fixtures are generated here with PIL in temp dirs: solid
color blocks, a two-color split, stripes, a gradient. The suite
needs no network and no real photos.

Run from the tool folder: bash run_tests.sh
"""

import hashlib
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent.parent
SCRIPT = HERE / "photo_palette.py"
README = HERE / "README.md"
DEBUG_LOG = HERE / "debug_log.py"

# The T21 debug log layer, copied unmodified. This hash pins it.
DEBUG_LOG_SHA256 = (
    "d304c17e6c607b58d44b201bd4df7b8c355acb796a10bb13029ab69ec19e73a2"
)

RED = (255, 0, 0)
ORANGE = (255, 128, 0)
YELLOW = (255, 255, 0)
LIME = (0, 255, 0)
TEAL = (0, 128, 128)
CYAN = (0, 255, 255)
BLUE = (0, 0, 255)
PURPLE = (128, 0, 255)
MAGENTA = (255, 0, 255)
PINK = (255, 128, 192)
BROWN = (128, 64, 0)
WHITE = (255, 255, 255)

TWELVE = [RED, ORANGE, YELLOW, LIME, TEAL, CYAN, BLUE, PURPLE,
          MAGENTA, PINK, BROWN, WHITE]

HEX_RE = re.compile(r"^#[0-9a-f]{6}$")


def hex_to_rgb(hex_value):
    return (int(hex_value[1:3], 16), int(hex_value[3:5], 16),
            int(hex_value[5:7], 16))


def color_distance(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
            + (a[2] - b[2]) ** 2) ** 0.5


def make_solid(color, path, size=80):
    Image.new("RGB", (size, size), color).save(path)


def make_split(left, right, path, size=100):
    img = Image.new("RGB", (size, size))
    pix = img.load()
    for y in range(size):
        for x in range(size):
            pix[x, y] = left if x < size // 2 else right
    img.save(path)


def make_stripes(colors, path, stripe=10, height=60):
    img = Image.new("RGB", (stripe * len(colors), height))
    pix = img.load()
    for i, color in enumerate(colors):
        for x in range(i * stripe, (i + 1) * stripe):
            for y in range(height):
                pix[x, y] = color
    img.save(path)


def make_gradient(path, width=256, height=16):
    """Horizontal red to blue gradient, one step per column."""
    img = Image.new("RGB", (width, height))
    pix = img.load()
    for x in range(width):
        red = 255 - x
        blue = x
        for y in range(height):
            pix[x, y] = (red, 0, blue)
    img.save(path)


def run_cli(args, cwd=None, env=None):
    """Run the real CLI in a subprocess, return the result."""
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + [str(a) for a in args],
        capture_output=True, text=True, cwd=cwd, env=merged_env,
        timeout=120)


def parse_output(text):
    """(hex list, css values) from one palette run's stdout."""
    lines = text.split("\n")
    hexes = [line for line in lines if HEX_RE.match(line)]
    css = re.findall(r"--color-\d+: (#[0-9a-f]{6});", text)
    return hexes, css


class PaletteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def fixture(self, name, maker, *args):
        path = self.dir / name
        maker(*args, path)
        return path

    # -- help, version, and plain errors --------------------------

    def test_help_exits_zero(self):
        result = run_cli(["--help"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("usage: photo_palette.py", result.stdout)
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        self.assertNotIn("\u2014", result.stdout)

    def test_version(self):
        result = run_cli(["--version"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("0.1.0", result.stdout)

    def test_no_photos_plain_error(self):
        result = run_cli([])
        self.assertEqual(result.returncode, 1)
        self.assertIn("photo", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_missing_file(self):
        missing = self.dir / "no-such-photo.jpg"
        result = run_cli([missing])
        self.assertEqual(result.returncode, 1)
        self.assertIn("no-such-photo.jpg", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_not_an_image(self):
        text_file = self.dir / "notes.txt"
        text_file.write_text("this is not a photo\n")
        result = run_cli([text_file])
        self.assertEqual(result.returncode, 1)
        self.assertIn("notes.txt", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_bad_colors_zero(self):
        photo = self.fixture("solid.png", make_solid, RED)
        result = run_cli([photo, "--colors", "0"])
        self.assertEqual(result.returncode, 1)
        self.assertIn("--colors", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_bad_colors_too_many(self):
        photo = self.fixture("solid.png", make_solid, RED)
        result = run_cli([photo, "--colors", "300"])
        self.assertEqual(result.returncode, 1)
        self.assertIn("--colors", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_bad_sample_zero(self):
        photo = self.fixture("solid.png", make_solid, RED)
        result = run_cli([photo, "--sample", "0"])
        self.assertEqual(result.returncode, 1)
        self.assertIn("--sample", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_out_to_missing_dir(self):
        photo = self.fixture("solid.png", make_solid, RED)
        result = run_cli([photo, "--out",
                          self.dir / "no-dir" / "pal.txt"])
        self.assertEqual(result.returncode, 1)
        self.assertIn("pal.txt", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_missing_pil_regression(self):
        """PIL missing: plain words naming PIL, install hint,
        exit 1, never a traceback (the T31 guard pattern)."""
        photo = self.fixture("solid.png", make_solid, RED)
        stub_dir = self.dir / "no-pil"
        stub_dir.mkdir()
        (stub_dir / "PIL.py").write_text(
            "raise ImportError('PIL blocked for this test')\n")
        env = {"PYTHONPATH": str(stub_dir)}
        result = run_cli([photo], env=env)
        self.assertEqual(result.returncode, 1)
        self.assertIn("PIL", result.stderr)
        self.assertIn("pip install Pillow", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    # -- extraction -----------------------------------------------

    def test_solid_color_returns_that_color(self):
        photo = self.fixture("solid.png", make_solid, RED)
        result = run_cli([photo, "--colors", "3"])
        self.assertEqual(result.returncode, 0)
        hexes, css = parse_output(result.stdout)
        # One distinct color in, one color out: no color invented
        # to fill the other two slots.
        self.assertEqual(hexes, ["#ff0000"])
        self.assertEqual(css, ["#ff0000"])

    def test_two_color_split(self):
        photo = self.fixture("split.png", make_split, RED, BLUE)
        result = run_cli([photo, "--colors", "2"])
        self.assertEqual(result.returncode, 0)
        hexes, _css = parse_output(result.stdout)
        self.assertEqual(set(hexes), {"#ff0000", "#0000ff"})

    def test_twelve_stripes_requested_count(self):
        photo = self.fixture("stripes.png", make_stripes, TWELVE)
        result = run_cli([photo, "--colors", "12"])
        self.assertEqual(result.returncode, 0)
        hexes, _css = parse_output(result.stdout)
        self.assertEqual(len(hexes), 12)
        found = [hex_to_rgb(h) for h in hexes]
        for expected in TWELVE:
            nearest = min(color_distance(c, expected)
                          for c in found)
            self.assertLessEqual(
                nearest, 10,
                "stripe color %s missing from palette" % (expected,))

    def test_defaults_give_twelve(self):
        photo = self.fixture("stripes.png", make_stripes, TWELVE)
        result = run_cli([photo])
        self.assertEqual(result.returncode, 0)
        hexes, css = parse_output(result.stdout)
        self.assertEqual(len(hexes), 12)
        self.assertEqual(len(css), 12)

    def test_every_hex_is_a_fixture_color(self):
        photo = self.fixture("stripes.png", make_stripes, TWELVE)
        result = run_cli([photo, "--colors", "12"])
        hexes, _css = parse_output(result.stdout)
        wanted = {"#%02x%02x%02x" % c for c in TWELVE}
        self.assertEqual(set(hexes), wanted)

    def test_gradient_colors_are_real(self):
        """Every hex in the output is a color present in the
        photo itself, never an average between two colors."""
        photo = self.fixture("gradient.png", make_gradient)
        with Image.open(photo) as img:
            rgb = img.convert("RGB")
            pix = rgb.load()
            real = {pix[x, y] for y in range(rgb.height)
                    for x in range(rgb.width)}
        result = run_cli([photo, "--colors", "6"])
        self.assertEqual(result.returncode, 0)
        hexes, _css = parse_output(result.stdout)
        self.assertEqual(len(hexes), 6)
        for hex_value in hexes:
            self.assertIn(hex_to_rgb(hex_value), real)

    def test_multi_photo_merges(self):
        red = self.fixture("red.png", make_solid, RED)
        blue = self.fixture("blue.png", make_solid, BLUE)
        result = run_cli([red, blue, "--colors", "2"])
        self.assertEqual(result.returncode, 0)
        hexes, _css = parse_output(result.stdout)
        self.assertEqual(set(hexes), {"#ff0000", "#0000ff"})

    def test_determinism(self):
        photo = self.fixture("stripes.png", make_stripes, TWELVE)
        first = run_cli([photo, "--colors", "12"])
        second = run_cli([photo, "--colors", "12"])
        self.assertEqual(first.stdout, second.stdout)

    def test_small_sample_deterministic(self):
        photo = self.fixture("gradient.png", make_gradient)
        first = run_cli([photo, "--colors", "6", "--sample", "100"])
        second = run_cli([photo, "--colors", "6", "--sample", "100"])
        self.assertEqual(first.returncode, 0)
        self.assertEqual(first.stdout, second.stdout)

    # -- output format --------------------------------------------

    def test_css_format_exact(self):
        """--colors 3 gives exactly --color-1..3, in the same
        order as the hex list, in a :root block."""
        photo = self.fixture("three.png", make_stripes,
                             [RED, LIME, BLUE])
        result = run_cli([photo, "--colors", "3"])
        self.assertEqual(result.returncode, 0)
        # Equal stripes, so the tie breaks on the color value:
        # blue, then lime, then red.
        expected = (
            "#0000ff\n"
            "#00ff00\n"
            "#ff0000\n"
            "\n"
            ":root {\n"
            "  --color-1: #0000ff;\n"
            "  --color-2: #00ff00;\n"
            "  --color-3: #ff0000;\n"
            "}\n"
        )
        self.assertEqual(result.stdout, expected)

    def test_hex_lines_match_css(self):
        photo = self.fixture("stripes.png", make_stripes, TWELVE)
        result = run_cli([photo, "--colors", "12"])
        hexes, css = parse_output(result.stdout)
        self.assertEqual(hexes, css)

    def test_hex_format(self):
        photo = self.fixture("stripes.png", make_stripes, TWELVE)
        result = run_cli([photo, "--colors", "12"])
        hexes, _css = parse_output(result.stdout)
        self.assertEqual(len(hexes), 12)
        for hex_value in hexes:
            self.assertRegex(hex_value, r"^#[0-9a-f]{6}$")

    def test_out_file(self):
        photo = self.fixture("split.png", make_split, RED, BLUE)
        out_path = self.dir / "palette.txt"
        to_stdout = run_cli([photo, "--colors", "2"])
        to_file = run_cli([photo, "--colors", "2",
                           "--out", out_path])
        self.assertEqual(to_file.returncode, 0)
        self.assertIn("Wrote", to_file.stdout)
        self.assertEqual(out_path.read_text(), to_stdout.stdout)

    def test_no_em_dash_in_output(self):
        photo = self.fixture("stripes.png", make_stripes, TWELVE)
        result = run_cli([photo, "--colors", "12"])
        self.assertNotIn("\u2014", result.stdout)

    # -- debug log layer ------------------------------------------

    def test_debug_report(self):
        result = run_cli(["--debug-report"], cwd=self.dir)
        self.assertEqual(result.returncode, 0)
        reports = sorted((self.dir / "logs").glob(
            "debug-report-photo-palette-*.txt"))
        self.assertEqual(len(reports), 1)
        self.assertIn("photo-palette", reports[0].read_text())
        self.assertIn("Debug report written to", result.stdout)

    def test_debug_log_unmodified(self):
        digest = hashlib.sha256(DEBUG_LOG.read_bytes()).hexdigest()
        self.assertEqual(digest, DEBUG_LOG_SHA256)

    def test_no_em_dash_in_readme(self):
        self.assertNotIn("\u2014", README.read_text())


if __name__ == "__main__":
    unittest.main()
