# OCR Reader

OCR Reader reads the text out of a picture: a screenshot, a
scanned page, a photo of notes. Drop in image files or PDFs and
it reads each one with Tesseract, on your own machine, and shows
the text in a window you can copy or save. A Clean step tidies
the text up afterwards: wrapped lines joined, extra spaces
collapsed, nothing rewritten.

**Plain truth:** OCR is approximate: handwriting and
low-contrast images read poorly. Check the text before you use
it.

## Where this came from

Honest origin: this was the weakest signal of the seven
spin-offs. Joshua asked "What is OCR" in the DATAPACKR thread
on 2026-11-13; nobody asked for a build. The case for building
it anyway is his phone-first screenshot habit, saving things as
pictures that then cannot be searched or copied, and feeding
DATAPACKR and ACR with text pulled out of those pictures. If it
earns its place, it earns it by being the fastest way from a
screenshot to usable text.

## Install

Double-click **Install OCR Reader**. It installs everything
the app needs into a private folder, adds OCR Reader to the
app menu and the desktop, and asks if you want to open it. No
terminal needed.

One thing the installer cannot fetch for you: the tesseract
program that does the actual reading. If it is not on the
computer, the installer stops and tells you the command to
install it:

```
sudo apt install tesseract-ocr
```

Then run the installer again. PDFs also need the pdftoppm
program (`sudo apt install poppler-utils`); the installer does
not check for it, and the reader says so plainly if you hand it
a PDF without it.

To remove it, run the uninstaller in the install folder
(`uninstall.sh`). It removes the app, the menu entry, the desktop
icon, and the logs folder. Text files you saved stay exactly
where you saved them.

## How to use the window

1. **Add files:** drag image files (PNG, JPEG, TIFF, BMP, GIF,
   WebP) or PDF files onto the window, or use File, Add files.
   You can add several at once, or drop a whole folder: every
   image or PDF file under it is added.
2. **Press Read.** Each file is read and its text appears on
   the right. Select a file in the list to see its text. A PDF
   is read page by page, with a page marker between pages. A
   file the reader cannot read says so in the list, in plain
   words.
3. **Press Clean** to tidy the text shown: it joins wrapped
   lines and tidies whitespace. Clean only tidies whitespace,
   it never rewrites words.
4. **Copy** copies the text shown. **Save** writes it to a text
   file you pick, next to the picture by default.
5. **Press Cancel** any time to stop a run in progress.

The How to Use window (Help menu) carries the same steps inside
the app.

## The chain: read, clean, view

Each step is its own command and runs alone from the terminal.
The window runs these same commands and shows their results, so
the window and the terminal always agree.

```
ocr-read shot.png              # read: print the text from a picture
ocr-read shot.png --json       # same, as JSON
ocr-read a.png b.png --out text.txt
                               # several files, text to a file
ocr-read --lang fra scan.png   # another language (default eng)
ocr-clean text.txt             # clean: tidy the text, print it
ocr-clean text.txt --json      # same, as JSON with the changes listed
ocr-reader                     # view: open the window
```

The full run in one line, picture to tidied text:

```
ocr-read shot.png | ocr-clean
```

Or through files, keeping the raw text too:

```
ocr-read shot.png --out raw.txt && ocr-clean raw.txt --out clean.txt
```

The full command carries every subcommand, and works while the
window is open:

```
ocrreader-cli read shot.png --json
ocrreader-cli clean text.txt --json
ocrreader-cli debug-report
```

`ocrreader-cli --help` lists every option. Read without
`--json` prints the plain text; several files are joined with a
`--- <file> ---` marker between them. Clean reads a file, or
stdin when no file is given.

## What works

- **Image formats:** PNG, JPEG, TIFF, BMP, GIF, WebP, anything
  Tesseract reads.
- **PDF files:** each page is rendered at 300 dpi and read in
  turn, with a `--- page N ---` marker before each page's text.
  PDFs need pdftoppm (`sudo apt install poppler-utils`); without
  it the reader says so plainly instead of failing silently.
- **Languages:** `--lang` picks the Tesseract language, default
  `eng`. The language needs its Tesseract language data
  installed; English ships with tesseract itself.
- **Plain failures:** a file that cannot be read, a missing
  tesseract, a missing pdftoppm, a read that times out, all
  report in plain words, never a traceback.

## Caveats

- OCR is approximate: handwriting and low-contrast images read
  poorly. Check the text before you use it.
- Clean only tidies whitespace, it never rewrites words. Its
  five rules, in order: strip trailing whitespace per line,
  collapse runs of extra spaces to one, remove a space before
  punctuation, join a wrapped line to the next when the break
  falls mid-sentence, collapse runs of blank lines to one.
  Cleaning is idempotent: cleaning cleaned text changes
  nothing.
- A picture with no text in it reads as empty text. That is the
  honest answer, not a failure.

## Accuracy

Accuracy on clean rendered text: 100% (44/44 words) on a 5-line
paragraph PNG with digits and punctuation, measured 2026-11-14
with Tesseract 5.3.4; the same paragraph as a one-page PDF also
read at 100%. Real photos and scans will read worse. Handwriting
and low-contrast images read poorly. Check the text before you
use it.

## If something breaks

File, Generate debug report (or `debug-report` on the
command line) writes a report file with the app version, the
computer details, the settings, and the recent actions and errors.
It never contains anything from your pictures or your text. Send
it to broke.n.bored.studio@gmail.com.

## What it needs

- Linux Mint (or any Linux with Python 3)
- Tesseract (`sudo apt install tesseract-ocr`), and
  poppler-utils (`sudo apt install poppler-utils`) for PDFs
- Nothing paid, no accounts, and the app never uses the network
  at all. The installer downloads the interface toolkit once,
  then the app works fully offline.

## For advanced users (terminal route, optional)

The installer and the app never need a terminal. If you prefer one
anyway:

```
bash install.sh     # install
bash run.sh         # open the window
bash ocrreader-cli --help
bash ocr-read --help
bash ocr-clean --help
bash ocr-reader --help
bash run_tests.sh   # run the test suite
```
