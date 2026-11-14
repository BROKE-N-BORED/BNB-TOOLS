# Vision Image Optimizer

Shrink pictures before a local vision model looks at them, so each
look costs fewer vision tokens and less time.

A 1920x1080 screenshot reads 2040 vision tokens. At 512 wide it
reads 144. That is about 14x less vision work for the model, and
smaller picture files too.

**Plain truth:** only the vision part shrinks about 14x. The whole
turn does not get 14x faster.

## Install

Double-click **Install Vision Image Optimizer**. It installs
everything the app needs into a private folder, adds Vision Image
Optimizer to the app menu and the desktop, and asks if you want to
open it. No terminal needed.

To remove it, run the uninstaller in the install folder
(`uninstall.sh`).

## How to use

1. **Add pictures:** drag image files onto the window, or use File,
   Add images. The list shows each picture with its vision tokens
   before and after shrinking.
2. **Pick a size:** 512w is the starting size. 768w and 1024w are
   there too, plus Original (no resize) and a custom width.
3. **Crop if you want:** drag a box on the preview to keep only the
   part that matters, or type numbers in the crop boxes. Full image
   clears the crop.
4. **Optimize:** Optimize selected (or Optimize all) saves a
   shrunken copy next to the original, in an `optimized` folder.
   Your original is never changed or overwritten.
5. **Describe:** Describe saves the shrunken copy first, then asks
   the local model what is in that copy. A small model looks first;
   the careful model only wakes up if the small one cannot see
   enough. If Ollama is not running, describing waits but shrinking
   still works.
6. **Cache:** the same picture with the same settings is answered
   once. A cached answer is marked "from cache". Clear cache
   empties it.
7. **Settings:** size, quality, format, output folder, Ollama
   address, both models, and the prompt are all on the right. They
   are remembered between runs.

The measurements line under each description shows the time for the
fast look and the careful look, the tokens before and after, and the
file sizes before and after.

The How to Use window (Help menu) carries the same steps inside the
app.

## The two models

- **Small model first** (default `minicpm-v`): a quick look. If it
  sees enough, that is the answer.
- **Careful model second** (default `qwen3-vl:2b-instruct`): only
  wakes up when the quick look comes back empty, too short, or
  saying it cannot see. Both models are configurable, and so is the
  Ollama address (default `http://127.0.0.1:11434`).

## The chain: shrink, describe, view

The window is a viewer over three small steps, and each step also
runs on its own from a terminal:

```
vision-shrink photo.png                # shrink one picture
vision-describe photo-512w.jpg         # describe one picture as given
vision-image-optimizer                 # the combined command + window
```

Chain them for the full run, the same thing the Describe button
does:

```
vision-shrink photo.png && vision-describe photo-512w.jpg
```

`vision-shrink` saves the shrunken copy (in an `optimized` folder
next to the original by default) and prints its size, tokens, and
path. `vision-describe` describes the file you hand it, as given:
it does not shrink first, so hand it the shrunken copy when you
want the small-token look. Both take `--json` for one machine
readable result object, and `--help` lists every option.

## Command line

The combined command works while the window is open:

```
vision-image-optimizer optimize photo.png --width 512
vision-image-optimizer describe photo.png
vision-image-optimizer cache-clear
vision-image-optimizer cache-stats
vision-image-optimizer debug-report
```

`vision-image-optimizer --help` lists every option. The `optimize`
and `describe` subcommands do the same work as `vision-shrink`
and `vision-describe`, in one command.

## If something breaks

File, Generate debug report (or `debug-report` on the command
line) writes a report file with the app version, the computer
details, the settings, whether Ollama is running, and the recent
actions and errors. It never contains passwords or keys. Send it to
broke.n.bored.studio@gmail.com.

## What it needs

- Linux Mint (or any Linux with Python 3)
- Ollama running locally, only for describing. Shrinking works
  without it.
- Nothing paid, no accounts, no network beyond your own computer.

## For advanced users (terminal route, optional)

The installer and the app never need a terminal. If you prefer one
anyway:

```
bash install.sh     # install
bash run.sh         # open the window
bash optimizer-cli --help
bash vision-shrink --help
bash vision-describe --help
bash run_tests.sh   # run the test suite
```

## How the token math works

Vision tokens are counted at 1 token per 32x32 pixel block:
tokens = ceil(width / 32) x ceil(height / 32). That is how the
counts in the window are worked out, before and after shrinking.
