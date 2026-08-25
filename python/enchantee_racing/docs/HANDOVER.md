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
| 5 Position publishing | done, and now actually deployed. See the deployment note below |
| 6 Race state machine | done, tuned against a real recorded track |
| 7 Countdown and pre-start | done, with voice and horn audio (DESIGN 10.1) |
| 8 Flags and course selection | done; flags corrected against the club's plate |
| 9 Map page | **not started**. The nav item exists and is disabled |
| 10 Config editor | **not started**. `PUT /api/config/...` is designed, not built |

## It is deployed, as of 23 August 2026

Everything below this heading happened on the Pi itself, at the dock, and is live. This
replaces the note that used to sit here saying the nginx block and the Dockerfile were
still to do.

- **Image**: `sfewings32/emon_enchantee_racing:latest`, `python:3.13-slim`, about 226 MB,
  built by `python/build.sh -m push -p arm64 -c enchantee_racing`. The Dockerfile's `COPY`
  list is an **allow-list** and that is deliberate: `docs/reference/` holds the copyright
  Geng chart and this image is public (DESIGN 6). Adding a file at the app root means
  adding it to that list, which has already caught one omission.
- **Compose**: an `enchantee_racing` service in `provisioning/enchantee/docker-compose.yml`,
  host networking, `restart: always`, with **the whole application directory bind-mounted**
  at `/app` from `/share/emon_Suite/python/enchantee_racing`.
- **nginx**: `/race/` proxies to `127.0.0.1:5002`, `/race` 301s to `/race/`, and `/hud`
  **302**s to `/race/hud` so the crew has a short URL for the instruments. The 302 is not
  an oversight: while the Node-RED HUD still exists (step 4) it is useful to be able to
  swing `/hud` between the two, and a 301 cached in every phone on the boat would make
  that a nuisance. Node-RED's own HUD is untouched at `/nodered/hud`.
- **The GPS images were the real blocker, and it was not obvious.** The `gps/position`
  change was in `pyemonlib` source but the arm64 wheel in `pyEmon/dist/` predated it, and
  `platform.sh` installs that wheel, so every image on this Pi was still publishing
  latitude and longitude separately. Rebuilt the wheel, rebuilt and pushed
  `emon_serial_to_mqtt` and `emon_gpsd_to_mqtt`, recreated both containers. `gps/position`
  is now present inside them, verified by grep.

**Still unproven**: `gps/position/0` has never run end to end from the boat's own GPS. The
transmitter was off throughout, so `emon_serial` sat in its no-serial restart loop. The
code and the images are right; the last mile needs the boat powered up.

### Editing it in place

The bind mount means no rebuild to change things, but "no rebuild" is not "no restart",
and the difference was measured:

| Edit | Picked up |
| ---- | --------- |
| `static/` (app.js, app.css, flags, audio, icons) | **live**, no restart |
| `templates/` (index.html, hud.html) | needs `docker restart enchantee_racing` |
| `config/` (marks, courses, lines, race.json) | needs a restart |

Flask serves `static/` from disk per request; Jinja caches templates with debug off, and
`load_config()` runs once at startup. A restart takes about a second, which is the
`STOPSIGNAL SIGINT` in the Dockerfile earning its place.

## Running it

On the development machine:

```
cd python/enchantee_racing
../venv/Scripts/python.exe -m pytest tests -q          # 281 tests, about 2 s
../venv/Scripts/python.exe app.py --demo               # synthetic data, no broker
../venv/Scripts/python.exe app.py --broker localhost   # against a real or replayed broker
```

On the Pi, where there is no pytest and neither interpreter has both dependencies, the
system `python3` has Flask but no paho and `python/venv` has paho but no Flask:

```
cd /share/emon_Suite/python/enchantee_racing
for t in tests/test_*.py; do python3 $t; done          # every test runs standalone
```

That standalone runner is not a curiosity, it is the only way to run the suite on the
boat, and it is why every test file ends with one.

Then <http://localhost:5002/> for the race screen and `/hud` for the instruments. On the
Pi itself it is deployed, so use <http://enchantee.local/race/> and
<http://enchantee.local/hud>.

To run a **second** instance against a replayed race without disturbing the deployed one,
which is how the display gets tested on a phone:

```
REPLAY_MQTT_PORT=1884 docker compose -f tests/replay/docker-compose.yml up -d
docker run -d --name racing_replay --network host \
  -v /share/emon_Suite/python/enchantee_racing:/app \
  -e MQTT_IP=localhost -e MQTT_PORT=1884 \
  -e BIND_HOST=0.0.0.0 -e SERVICE_PORT=5003 -e TZ=Australia/Perth \
  sfewings32/emon_enchantee_racing:latest
```

`BIND_HOST=0.0.0.0` is the easy one to forget: the image defaults to `127.0.0.1` because
nginx fronts the deployed copy, and without the override the page loads on the Pi and not
on a phone. Then <http://enchantee.local:5003/>, and drive it with the replay below.

`REPLAY_MQTT_PORT` exists because the provisioned stack holds 1883. Replaying into that
broker works but is not free: `emon_mqtt_to_influx` writes the race into InfluxDB under
today's timestamps, `emon_mqtt_to_log` and `emon_logtojson` write it into `/share/Input`,
and `event_recorder`'s `track_recording` event triggers on 20 m of movement and opens a
spurious vessel track.

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

**`gps/position/0` has never been seen from the boat's own GPS.** The wheel, both images
and the subscription are all right and verified in isolation, but the transmitter was off
for the whole deployment session. Until a fix arrives from `emon_serial`, everything on
the race screen that depends on position shows `---`, which is correct behaviour and
indistinguishable from a fault. Power the boat up and watch `/race/api/state`.

**No apple-touch-icon is a solved problem, but the icon is only eyeballed.** It is the
chart's rounding symbol on black with the buoy in the app's DodgerBlue, generated by
`scripts/gen_icon.sh`. It uses the **starboard** form arbitrarily; on the race screen that
side is an instruction and the tests assert it, whereas on the icon it is a logo. If that
ever reads as an instruction, change it, but do not mirror it half way.

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
- Files in this repo are CRLF **in the Windows checkout**. `.gitattributes` sets
  `* text=auto`, so on the Pi they are LF. String-replacement edits that assume the wrong
  one fail silently, and which one is wrong depends on the machine.
- **The browser floor is iOS 12**, because the boat carries an iPad mini 3 and that is as
  far as it goes. The phone is current. Two features that shipped and did not work on the
  iPad, both invisible on anything modern:
  - `clamp()` needs Safari 13.1. Every clamped `font-size` was dropped and every reading
    rendered at the inherited 16 px, against the 132 px the distance computes to at that
    viewport. Each clamp now carries a plain fallback before it, the same idiom the file
    already used for `height: 100vh; height: 100dvh`.
  - flexbox `gap` needs Safari 14.1. Margins on the children instead. Grid gap is fine.
    Note that margins reach element children only while `gap` also spaces the anonymous
    items flexbox makes from bare text, so **a line of prose must not be a flex
    container**: `#secondary` is a plain block for exactly that reason.

  Both are pinned by tests, because neither can be seen on a development machine.
- **iOS decides standalone-versus-browser by the manifest's scope.** Added to the Home
  Screen with no manifest, iOS infers a scope from the one URL that was saved, so tapping
  between HUD and Race threw the crew into an overlay browser with a Done button whichever
  way round they saved it. `manifest.webmanifest` declares the scope, and it is served
  from the **app root** rather than `static/` because `scope` resolves against its own URL:
  from `static/` it would have resolved to `/race/static/` and covered neither screen.
  `location.assign` on the nav links is kept as well, because iOS 12 predates scope
  enforcement and needs it. Confirmed working on both devices.

## A note on where to develop

The Pi has no internet **on the water**. At the dock it joins the house wifi and has
internet like anything else, which is when every `pip install`, `docker compose pull`,
wheel build and image push has to happen. Reading the no-internet rule as "the box can
never fetch anything" makes deployment look impossible when it is only time-boxed. Once
it is off the dock, treat the box as sealed.

Developing on the laptop and deploying here is still the path of least friction for the
app itself: the replay framework exercises the engine fully off-boat, and two of the
generator scripts only run on Windows. But the deployment, and everything that turned out
to be wrong about it, could only be done on the Pi, and a session on the Pi has two tools
a laptop does not:

- **The real stack.** The stale GPS wheel, the missing `EVENT_PUBLISHER` wiring and the
  nginx routing were all found by running against the actual containers.
- **A browser.** `sfewings32/emon_event_recorder` bundles chromium and selenium, so a
  page can be rendered at an exact viewport and its computed geometry read back. That is
  how the iOS layout faults were diagnosed and how `scripts/gen_icon.sh` renders the
  icon. There is no iOS anywhere, though, so anything about standalone mode or Safari's
  own chrome has to be checked on a real device.
