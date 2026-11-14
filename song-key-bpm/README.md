# Song Key BPM

Song Key BPM finds the key and the tempo of your songs, on your
own machine. Drop in audio files (WAV, MP3, FLAC, OGG) and it
measures each one: BPM from the beat, key from the notes. The
results land in a table you can read at a glance or export as a
CSV for a spreadsheet.

**Plain truth:** BPM is a measurement and key is an estimate.
Key detection is approximate: relative major and minor pairs,
like C major and A minor, share the same notes, so a close call
between them is normal. Check by ear.

## Install

Double-click **Install Song Key BPM**. It installs everything
the app needs into a private folder, adds Song Key BPM to the
app menu and the desktop, and asks if you want to open it. No
terminal needed.

To remove it, run the uninstaller in the install folder
(`uninstall.sh`). It removes the app, the menu entry, the desktop
icon, and the logs folder. The app keeps nothing else of yours.

## How to use the window

1. **Add files:** drag audio files onto the window, or use File,
   Add files. You can add several at once, or drop a whole
   folder: every audio file under it is added.
2. **Press Analyze.** Each file is measured for BPM and key, and
   the table fills in: BPM, key, confidence, and duration.
3. **Read the table.** A key with low confidence shows its close
   second choice too, like "A minor (or C major?)". BPM unknown
   means the file has no beat to measure, like a chord pad with
   no drums. That is the honest answer, not a failure. A file
   the tool cannot read says "Could not read".
4. **Press Export** to write the table as a CSV file, next to
   your songs or wherever you pick. Open it in any spreadsheet.
5. **Press Cancel** any time to stop a run in progress.

The How to Use window (Help menu) carries the same steps inside
the app.

## The chain: analyze, export, view

Each step is its own command and runs alone from the terminal.
The window runs these same commands and shows their results, so
the window and the terminal always agree.

```
song-key-analyze song.mp3        # analyze: measure BPM and key,
                                 # print one line per file
song-key-analyze song.mp3 --json # same, as JSON
song-key-analyze folder/         # every audio file under it
song-key-export results.json --format csv --out table.csv
                                 # export: turn an analyze JSON
                                 # file into a CSV table
song-key-bpm                     # view: open the window
```

The full run in one line: analyze a folder to a JSON file, then
export the table:

```
song-key-analyze folder/ --out results.json && song-key-export results.json --format csv --out table.csv
```

The full command carries every subcommand, and works while the
window is open:

```
songkey-cli analyze song.mp3 --json
songkey-cli export results.json --format both --out table
songkey-cli debug-report
```

`songkey-cli --help` lists every option. `--format both` writes
two files, `table.csv` and `table.json`.

## Check it against songs you know

Try the tool on your own copies of these and see if it agrees:

- Tomorrow (Silverchair): D major, about 147 BPM
- Alive (Pearl Jam): B minor, 75 BPM (150 double-time)
- Plush (Stone Temple Pilots): G minor, 145 BPM

A close call between relative major and minor (D major vs
B minor, for example) is normal: the two keys share the same
notes. The table shows the runner-up so you can judge by ear.

## What the table means

- **BPM:** the tempo, measured from the gaps between beats. A
  "(low)" mark means the two tempo checks disagreed, so treat
  the number with care. "Unknown" means no beat was found.
  Very short clicks (under about 30 ms, like a bare metronome
  blip) may read as unknown; real drum hits are longer and
  measure fine.
- **Key:** the best-matching key from the notes in the file.
  "(or X?)" names the close second choice when confidence is
  low.
- **Confidence:** Confident means the winner stood clear of the
  rest. Low means the call was close. Unknown means the file
  had no usable pitch content, like a drums-only track.
- **Duration:** the length of the file in seconds.

## If something breaks

File, Generate debug report (or `debug-report` on the
command line) writes a report file with the app version, the
computer details, the settings, and the recent actions and errors.
It never contains anything from your songs. Send it to
broke.n.bored.studio@gmail.com.

## What it needs

- Linux Mint (or any Linux with Python 3)
- Nothing paid, no accounts, and the app never uses the network
  at all. The installer downloads the interface toolkit and the
  audio tools once, then the app works fully offline.

## For advanced users (terminal route, optional)

The installer and the app never need a terminal. If you prefer one
anyway:

```
bash install.sh     # install
bash run.sh         # open the window
bash songkey-cli --help
bash song-key-analyze --help
bash song-key-export --help
bash song-key-bpm --help
bash run_tests.sh   # run the test suite
```
