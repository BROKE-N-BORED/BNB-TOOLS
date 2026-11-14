# Repo Health Board

See the health of every repo in an org at a glance: the last real
commit date, how many files it has, its latest release, whether
it has a CI file, and any health flags. The data comes from
GitHub, no sign-in and no token, ever.

The board is three small pieces that chain together. Each one
runs on its own, and the viewer only displays what the other two
produced.

## The chain: fetch, flag, view

1. Fetch. Checks the org on GitHub and writes repos.json.

   board-fetch --org BROKE-N-BORED

   From the project folder before installing:

   bash board-fetch --org BROKE-N-BORED

   Or the module form, which works anywhere the folder is on the
   path:

   python3 -m board.fetch --org BROKE-N-BORED

2. Flag. Reads repos.json, applies the health rules, and writes
   the flagged board (flagged.json and board.txt).

   board-flag

   From the project folder before installing:

   bash board-flag

   Or: python3 -m board.flag

3. View. Opens the window, which shows flagged.json. The
   Refresh button runs fetch and flag for you, in the
   background, with Cancel if it takes too long.

   Double-click Repo Health Board in the app menu, or run:

   bash run.sh

## The one-command full run

board-cli refresh

That fetches, flags, and prints the board as text. The viewer
does the same job with its Refresh button. Other commands:

board-cli show          print the board from the last fetch
board-cli export FILE   write the board as a text file
board-cli debug-report  write a debug report and print its path

From the project folder before installing, use
bash repo-health-board-cli instead of board-cli.

## What each flag means

- placeholder: the repo has only scaffolding (a README, a
  LICENSE, a .gitignore, a SECURITY.md, or files under .github)
  or is empty. No real code yet.
- no README, no LICENSE, no .gitignore, no SECURITY.md: that
  file is missing from the repo.
- no description: the repo has no description on GitHub.
- no topics: the repo has no topics set on GitHub.
- stale (no commit in 90 days): the last real commit is older
  than 90 days.

The date shown is the real commit date from the repo's commit
history, not the date GitHub lists on the org page. Those two
can disagree, and when they do the commit date is the true one.

Suite status only says whether a CI workflow file exists under
.github/workflows: has CI, no CI file, or unknown when the file
list could not be fetched. It never says whether CI passes.

## The 60 an hour limit, and the cache

GitHub allows 60 unauthenticated checks an hour. Each repo takes
a few checks, so a big org can hit the limit partway through a
refresh. When that happens the board keeps the last good data
and tells you when to try again, in plain words.

The fetch keeps a cache (cache.json in the data folder). When a
repo has not changed since the last check, GitHub says so and
the cached detail is reused, so a second refresh uses far fewer
of the 60 checks. A repo the fetch could not check at all shows
as unchecked, with unknown file count and unknown suite status.
Unknown is never shown as a flag: an unchecked repo is not
called empty, and a repo with no known commit date is not
called stale.

## How to install

Double-click Install Repo Health Board. No terminal needed. The
installer sets up a private tools folder, adds the app menu
entry and a desktop icon, and puts board-cli, board-fetch, and
board-flag on the command line. To remove it, run uninstall.sh
from the folder. The saved board, settings, and logs live in
~/.local/share/repo-health-board and are left alone, so a
reinstall finds them again.

## Files it keeps

All under ~/.local/share/repo-health-board (or $XDG_DATA_HOME):

- settings.json: the org and the last refresh time
- repos.json: the last fetch output
- flagged.json: the flagged board the viewer shows
- board.txt: the same board as plain text
- cache.json: cached repo details, so refreshes reuse them
- logs/: the debug log and any debug reports

## Honest limits

- The checks are mechanical only: missing files, old commits,
  empty repos. The board never judges whether a repo is good.
- Suite status is presence only: it says whether a CI file
  exists, never whether CI passes.
- Only public repos are checked. The board never signs in, so
  private repos are out of reach by design.
- A live run against the real org is unproven until it runs on
  a real PC. Everything so far was verified against a local
  fake GitHub server, never the live API.

## If something breaks

File, Generate debug report (or board-cli debug-report) writes
a report file and shows its path. Send it to
broke.n.bored.studio@gmail.com. The report carries no secrets.
