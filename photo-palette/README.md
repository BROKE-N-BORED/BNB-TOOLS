# T35 - photo-palette

Sample pixels from photos and pull out a palette of real
colors: a hex list plus CSS variables, on stdout or in a file.
Small, single-purpose, chainable: one script, PIL only, no
network, no GUI.

## Why it exists

Main chat, Sat 2026-11-14 ~16:54. Joshua sent two photos and
said "Brother I love these colors can you make a full pallet
for me". The answer sampled 30,000 pixels, pulled 12 colors
(hero red down to near-black), every hex a real color from the
photos, with a full list plus CSS variables. This tool automates
that answer: same sampling, same palette, same output, as a
command he can run on any photos.

## Usage

```bash
python3 photo_palette.py photo.jpg
python3 photo_palette.py one.jpg two.png --colors 12 --sample 30000
python3 photo_palette.py photo.jpg --out palette.css
python3 photo_palette.py --debug-report
```

| Option | Default | What it does |
| --- | --- | --- |
| `PHOTO...` | (required) | One or more photos to sample from |
| `--colors N` | 12 | Palette size, 1 to 256 |
| `--sample N` | 30000 | Pixels to sample across all photos |
| `--out FILE` | stdout | Write the palette to this file |
| `--debug-report` | off | Write a debug report instead of a palette |
| `--version` | | Print the version |
| `--help` | | Print usage, exit 0 |

Output is a hex list, a blank line, then a `:root` block with
one `--color-N` variable per palette color, in the same order:

```
#d7263d
#f46036
#2e294e

:root {
  --color-1: #d7263d;
  --color-2: #f46036;
  --color-3: #2e294e;
}
```

## Worked example: the 30,000-pixel, 12-color case

The original answer, as a command:

```bash
python3 photo_palette.py photo1.jpg photo2.jpg --colors 12 --sample 30000
```

30,000 pixels are sampled across the two photos (15,000 each),
clustered into 12 colors, and printed as 12 hex lines plus
`--color-1` through `--color-12`. The palette is ordered most
common first, so the first color is the one the photos hold the
most of, the hero color of the set.

## Method

Honestly stated, step by step:

1. **Sampling.** Each photo is read as RGB and sampled at
   evenly spaced positions across the whole image. The sample
   budget (`--sample`, default 30000) is split evenly across
   the photos, so no one photo crowds out the rest. Sampling is
   deterministic: positions are computed from the pixel count,
   no random numbers anywhere, so two runs on the same photos
   give the same palette. Pixels are read by position, never by
   copying the whole image into memory, so a large photo costs
   the sample budget of reads, not millions of tuples.
2. **Clustering.** The pooled samples are clustered with
   median-cut, via PIL `quantize`. Median-cut splits the color
   space into boxes holding roughly equal numbers of samples
   and reports one color per box.
3. **Snapping to real colors.** A median-cut box color is an
   average of its box, so it is usually not a color the photos
   actually hold. Each cluster color is therefore snapped to
   the nearest color that was actually sampled, in RGB space.
   That is what makes the promise true: every hex in the output
   is a real sampled color from the photos, never an average or
   a guess. When two clusters snap to the same color, the
   duplicate is dropped and the slot is filled from the most
   frequent sampled colors not already in the palette.
4. **Ordering.** Each sampled pixel is assigned to its nearest
   palette color, and the palette is ordered by those counts,
   most common first, ties broken by the color value. The order
   is deterministic.

Two honest limits:

- The palette holds **up to** the requested number of colors.
  When the photos hold fewer distinct colors than requested
  (a solid red photo asked for 12 colors gives 1), the palette
  holds what there is. No color is ever invented to fill a slot.
- Transparency is dropped: photos are read as RGB, so a
  transparent pixel reads as its RGB value, not as see-through.

## Known failure modes

Two failure modes found in the field, documented honestly
here. The code fixes for both are a future T35 version; the
current code does not do them yet.

**Cluster contamination.** A color cluster can be dragged by
neighboring pixels: the median-cut box holds a mix, and the
snapped color lands somewhere between the real color and its
neighbors instead of on the real color. The case that proved
it: Campbell's Chunky v1, where the reds came out brown. The
fix is brightest-pixel anchoring: anchor each cluster on its
brightest sampled pixel instead of the box average, so the
palette color is the color the eye actually sees in the photo,
not the average of the color and everything next to it.

**Neon and fluorescent colors.** A photo cannot measure neon:
the camera records the dull version of a fluorescent color,
and the palette ships dull. The fix is a neon/fluorescent
boost option: keep the real hues from the photo, but push
them to full fluorescent saturation and brightness, instead
of shipping the dull recorded color as if it were the real
one. The hues stay honest (they come from the photo); only
the saturation and brightness are boosted, and only when the
option is on.

## One filename per version

Every version of a palette file gets its own filename. A new
version that reuses the old filename can be served stale from
a cache, and the person opening it sees the old palette while
believing it is the new one (the COLOR PALLETS cache incident,
proven twice). The rule is the same one S1 and S6 carry for
releases: new version, new filename, no exceptions.

## Errors

Plain words, exit 1, never a traceback:

- No photo given: "give at least one photo to sample from".
- A photo that is not there: "cannot find photo: <path>".
- A file Pillow cannot read as a photo: "<path> is not a photo
  Pillow can read".
- `--colors` outside 1 to 256, or `--sample` below 1: the flag
  and the value are named.
- `--out` to a place that cannot be written: "cannot write
  <path>: <reason>".
- PIL (Pillow) not installed: the message names PIL and says
  how to install it (`python3 -m pip install Pillow`). `--help`,
  `--version`, and `--debug-report` still work without Pillow,
  because the check runs only when a palette is being built.

## Debug report

```bash
python3 photo_palette.py --debug-report
```

Writes a debug report through the T21 debug log layer
(`debug_log.py`, copied unmodified) and prints where it went
(`logs/debug-report-photo-palette-<date>.txt`). Normal palette
runs never touch the log layer and never create a `logs/` dir,
so the tool stays side-effect free for chaining. The report
carries the Pillow version, the app version, and a note that
the tool has no network and no services.

## Requirements

Python 3.8+ and Pillow (PIL). No network, no account, no GPU.
Install Pillow with:

```bash
python3 -m pip install Pillow
```

## Smoke test

```bash
bash run_tests.sh
```

27 tests, no network, no real photos: every fixture is
generated with PIL at test time (solid color blocks, a
two-color split, stripes, a gradient). Covers help/version,
the extraction itself (solid, split, 12 stripes at the
requested count, gradient colors all real, multi-photo merge),
the exact CSS format (`--colors 3` gives `--color-1..3`),
determinism (same input twice, small sample twice), `--out`,
all plain-word errors, the missing-PIL regression (a stub PIL
that raises ImportError), the debug report, the unmodified
debug log layer (SHA-256 pinned), and the no-em-dash rule.

## What it does not do

- It does not pick colors by taste or by trend: the palette is
  what the photos hold, ordered by how much of each they hold.
- It does not name colors ("crimson", "sage"): hex only.
- It does not edit photos, crop, or resize: it reads pixels
  and reports colors.
- It does not watch a folder or run on a schedule: it runs
  when you run it, on the photos you name.
