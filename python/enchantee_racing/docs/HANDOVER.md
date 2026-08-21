# Handover

Written so that a fresh session, on this machine or on the Pi, can be useful after one
read. It records **state**: what is built, what is open, what only runs on one machine.
It deliberately does not repeat the design, which is in `DESIGN.md`, or the constraints,
which are in `../CLAUDE.md`.

## Read these first, in this order

1. `../CLAUDE.md` — the hard constraints. No internet on the Pi, plain HTTP, relative
   URLs only, `engine/` holds no I/O, one lock in `store.py`. These are properties of the
   deployment, not preferences, and most of them have already caught something.
2. `DESIGN.md` — every decision and, more usefully, the alternatives that were rejected
   and why. When something looks odd, the reason is almost always in here. Sections worth
   knowing by number, because the code cites them: 6 (there are no gates), 7 (course data
   and the printed distances that do not reconcile), 9.x (the screens), 11.x (the race
   rules), 13 (build order).
3. The tests. 274 of them, and they are written to say why a rule exists rather than only
   that it holds. `tests/test_courses.py` and `tests/test_race.py` are the substantive
   ones; `tests/test_race_screen.py` guards the things only a phone would reveal.

## Where it is up to

Build order is DESIGN 13. Steps 1 to 8 are done:

| Step | State |
| ---- | ----- |
| 1 `engine/nav.py` | done, checked against a Vincenty reference |
| 2 `courses.json` | done, and **all 23 courses** across all six series, not just one |
| 3 HUD port | done, served at `/hud`, with a racing panel added (DESIGN 9.10) |
| 4 Disable the Node-RED HUD tab | **not done** — needs a side-by-side comparison on the boat first |
| 5 Position publishing | done in `pyemonlib.emon_mqtt`, verified off a replay |
| 6 Race state machine | done, tuned against a real recorded track |
| 7 Countdown and pre-start | done, with voice and horn audio (DESIGN 10.1) |
| 8 Flags and course selection | done; flags corrected against the club's plate |
| 9 Map page | **not started**. The nav item exists and is disabled |
| 10 Config editor | **not started**. `PUT /api/config/...` is designed, not built |

Not in the build order and also not done: the nginx `/race/` block from DESIGN 5, and a
Dockerfile. The user has said Docker will handle `Restart=always`, so the systemd unit in
CLAUDE.md's stack section is likely moot.

## Running it

```
cd python/enchantee_racing
../venv/Scripts/python.exe -m pytest tests -q          # 274 tests, about 2 s
../venv/Scripts/python.exe app.py --demo               # synthetic data, no broker
../venv/Scripts/python.exe app.py --broker localhost   # against a real or replayed broker
```

Then <http://localhost:5002/> for the race screen and `/hud` for the instruments. Every
test also runs standalone (`python tests/test_nav.py`) because the Pi may have no pytest.

Replay is the primary test strategy and `tests/replay/README.md` is the guide to it. The
short version: bring up the broker in Docker, start the app against it, and push
`tests/data/20260816_Frostbite_3.TXT` at it.

One thing the replay README does not say, because it was only ever measured in a
conversation: `--speed` above about 10x stops being faithful to the **race engine**. The
engine has wall-clock guards, a suppression window after each advance among them, and at
15x only 4 of 9 leg advances fired. High multipliers are still fine for watching the
instruments, where nothing depends on elapsed time; the README's `--speed 60` example is
for exactly that. Use 10x or less when what you are testing is the legs.

## What only works on Windows

Two dev-time scripts will not run on the Pi, and neither is needed to run the app:

- `scripts/gen_audio.py` — generates the countdown audio. Needs Windows SAPI for the
  voice and ffmpeg for assembly. ffmpeg is not on `PATH`; the script finds it under
  `%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*`, or takes `$FFMPEG`.
- `scripts/extract_courses.py` — extracts the course sheets from the fixtures PDF. Needs
  PyMuPDF, which is **not** a project dependency; it was installed ad hoc. `pip install
  pymupdf` when you need it.

Their outputs are committed, so neither has to run again unless the source documents
change. `scripts/gen_marks.py` and `gen_lines.py` need only the shapefile and the stdlib.

## The reference documents, and what is in them

`docs/reference/` holds the club's own paperwork. Which page has what, because finding it
took longer than reading it:

- `Sailing Fixtures & Courses 2026 - 2027.pdf` — course sheets on **pages 15 to 20**
  (0-indexed 14 to 19: Frostbite, Friday, Sunday Div II, III, IV, Twilight). The flag
  plate is **page 27** (0-indexed 26), and it is the authority on flag designs.
- `Swan River course marks-Jul26.pdf` — the Geng chart. The rounding symbol on screen is
  lifted from the legend on page 1, and the buoy dot beside it from mark 33A.
- `Swan_marks_YWA_SRRC_Sep2019.shp` and friends — the QGIS redigitization, which is the
  truth for mark positions, better than the 2019 register.

Text extracts cleanly from both PDFs with PyMuPDF. Rendering pages to look at them is
often faster than parsing, and for anything visual it is the only honest way.

## Open issues

**The countdown audio is clipped and hard to make out.** The user reported it and it is
not fixed. `trim()` in `gen_audio.py` cuts silence at a `-45 dB` peak threshold, which
will be eating the soft onset of a fricative; "seven", "six" and "four" are the likely
sufferers, and their measured onsets did sit 0.1 to 0.2 s later than the others. Try a
quieter threshold, or keep a few milliseconds of lead-in rather than trimming hard to the
first sound. `MAX_NUMBER_S` fails loudly if a slower `--rate` pushes a word past its
second.

**Six courses do not reconcile with their printed distance** (DESIGN 7, pinned in
`tests/test_courses.py`). The parse has been checked leg by leg in each case; what is in
doubt is which side is wrong. **Sunday Div IV course 1 is the outlier at 9.9 per cent
under**, and worth holding against the paper sheet: its first nine legs are identical to
Div III course 1, which reconciles to +0.3 per cent.

**Three printed shortened distances resolve to no crossing of the line** (DESIGN 11.6),
and all three belong to courses whose full distance is also out, which is probably the
same underlying problem rather than a second one.

**The flags are right but not measured.** The arrangements are checked against the plate
and pinned by tests. The pendant taper, and the size and position of the discs and the
cross, are eyeballed. See `static/flags/README.md`.

## Conventions that have already bitten

- **Club Buoy 32A is both the outer end of the finish line and a mid-course mark in 22 of
  the 23 courses.** Finish detection arms only after the last leg. This is the single
  most dangerous fact in the data.
- **There are no gates.** Bricklanding, Smith/Lucky Bay and Mosman are pairs of ordinary
  marks, one leg each. An earlier design said otherwise and was wrong (DESIGN 6).
- **Marks resolve on name *and* number, never number alone.** Fourteen numbers belong to
  two marks each, and the sheets use both sides of one of them: bare 38 is Dee Rd, 900 m
  from Bond.
- **The engine takes documents, never paths.** `app.py` is the only module that reads a
  file. That is what lets the whole of the course validation run without a filesystem.
- Everything the front end shows is server state. Two devices must not be able to
  disagree about which leg the boat is on.
- Files in this repo are CRLF. String-replacement edits that assume LF fail silently.

## A note on where to develop

The Pi has no internet, which is a constraint on the app and also on running an agent
there. The replay framework means the engine can be exercised fully on a laptop, the two
generator scripts only work on Windows, and the deployment target is a service behind
nginx rather than an editor workspace. Developing here and deploying to the Pi is the
path of least friction; a remote window is still the right tool for looking at the
service once it is running.
