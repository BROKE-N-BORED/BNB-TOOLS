# AppImage Runner

Run an AppImage by clicking. No terminal.

An AppImage is a program that ships as one file. On Linux Mint,
a downloaded AppImage usually will not start when you double
click it: the file is not marked runnable yet. The manual fix
is four steps: right-click the file, Properties, Permissions,
tick "Allow executing file as program", then double-click. Miss
the tick and nothing happens, with no explanation.

AppImage Runner removes the four steps. Drop the AppImage on
the window (or pick the file) and press **Run it**. The tool
makes the file runnable and then runs it. The app opens in its
own window and keeps running after this tool closes.

## Where this came from

On 2026-11-18, Joshua photographed a downloaded Android File
Transfer AppImage and asked "How do I run this". He was walked
through the manual flow: right-click, Properties, Permissions,
tick "Allow executing file as program", double-click. The app
then could not see the phone, because the phone was plugged in
after the app opened. Both lessons became this tool: the tool
does the Permissions tick for you, and the window carries the
phone-first checklist so the phone is plugged in and set to
File Transfer before the app opens.

## Install

1. Extract the zip (right-click, Extract Here).
2. Open the `appimage-run-helper` folder.
3. Double-click **Install AppImage Runner**.
4. When it finishes, **AppImage Runner** is in your menu and on
   the desktop.

The installer does everything itself: it sets up a private
Python environment, downloads the interface library, draws the
icon, and puts the commands on your PATH. You never open a
terminal. Re-running the installer upgrades in place, and if an
upgrade fails the previous install is put back.

One warning may appear during install: if the FUSE library is
missing, the installer says so in plain words and keeps going.
The tool still installs and files still get made runnable. Some
AppImages need FUSE to start; if one will not start, install
FUSE in the Software Manager (search for libfuse2). The debug
report (below) also checks whether FUSE is on the computer.

## How to use the window

1. **Pick a file**: press **Pick a file** and choose the
   AppImage, or drag the AppImage onto the window. A file that
   does not end in .AppImage still works: the tool tries it
   anyway and says so in plain words.
2. **Run it**: press **Run it**. The status line says what
   happened in plain words: "Made X runnable, and it is running
   now", "X is running now", "X ran and finished", or why it
   did not start.

### The phone-first checklist

The window shows this note under the buttons, because a phone
app only sees the phone when the phone is ready first:

- Plug the phone into the PC with the USB cable and unlock it.
- Pull down the phone notifications, tap the USB notice, and
  pick File Transfer.
- Open the app AFTER the phone is set to File Transfer, or the
  app will not see it.
- If the phone still does not show up, try another USB port or
  cable. Some cables only charge and cannot move files.

## The chain

Three small tools, each runnable alone:

| Piece | What it does |
|---|---|
| `appimage-make-runnable` | Sets the exec bit on one file (the Permissions tick, as a command) |
| `appimagehelper-cli launch` | Makes a file runnable, then runs it detached |
| `appimage-run` | The window: a thin view over `launch` |

The window does no work itself: it runs
`appimagehelper-cli launch --json <file>` as a subprocess and
shows the result, so the window and the terminal always agree.
Chain them in scripts if you want: make-runnable first when you
only need the bit set, launch when you want the app open.

## What works (v0.1.0)

- **Make runnable**: adds the exec bit to any regular file. A
  file that is already runnable is a success, not an error.
  Missing files, folders, and unwritable files fail with plain
  words, never a traceback.
- **Launch**: makes the file runnable, runs it detached, and
  waits a moment to catch the app dying the instant it starts
  (the usual sign of a missing library). An app that runs and
  finishes quickly is reported as finished, not failed.
- **The window**: pick or drop a file, Run it, plain-words
  status, the phone-first checklist, a How to Use window, and a
  debug report under the File menu.
- **Debug report**: the T21 debug log layer. The report checks
  whether FUSE is on the computer, the first thing to check
  when an AppImage will not start.

## Caveats

- **This tool has never launched a real AppImage on Joshua's
  Mint PC.** Every test runs in the build sandbox with fake
  AppImage scripts. The first real check is clicking Run it on
  his PC with a real AppImage.
- **FUSE**: most AppImages need the FUSE library to start. If
  it is missing, the AppImage stops right away and the status
  line says so. Installing libfuse2 (Software Manager) fixes
  it.
- **Not a file manager**: the tool runs the one file you pick.
  It does not browse, organize, or update AppImages.
- **No arguments to the app**: v0.1.0 runs the AppImage with no
  extra arguments. An AppImage that needs flags (like
  --appimage-extract) is out of scope for now.

## If something breaks

Open **File, Generate debug report** in the window (or run
`appimagehelper-cli debug-report`). The report lands in
`~/.local/share/appimage-run-helper/logs/` and includes the FUSE
check. Send it to broke.n.bored.studio@gmail.com.

To remove the tool, double-click `uninstall.sh` (or run it):
it removes the menu entry, the desktop icon, the command
links, the environment, and the logs. It leaves this folder and
your settings in `~/.local/share/appimage-run-helper` in place;
delete those by hand if you want them gone. It never touches
any AppImage file.

## What it needs

- Linux Mint (or another Debian-family Linux) with Python 3.
- An internet connection for the first install only (the
  interface library download).
- The FUSE library (libfuse2) for most AppImages to start. The
  tool itself works without it; the AppImages may not.

## Advanced users

Everything also runs from the terminal:

```
appimagehelper-cli make-runnable file.AppImage
appimagehelper-cli launch file.AppImage
appimagehelper-cli launch --json file.AppImage
appimage-make-runnable file.AppImage
appimage-run
```

Every command takes `--help`. The exit codes are 0 (success),
1 (a plain-words failure), and 2 (a usage error). The CLI uses
the standard library only, so make-runnable works even before
the window is installed.
