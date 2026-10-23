# emon live UI redesign: handover

Written so that a fresh Claude Code session, on any machine, can pick this work up after
one read. It records **state**: where the work is, what is open, what only runs where.
It does not repeat the design (`DESIGN.md`) or the task list (`PLAN.md`).

Work on this branch is intermittent, possibly months between sessions, and moves from the
Windows laptop where it started to the shannstainable Raspberry Pi where it finishes.
Assume the previous session's context is gone. Everything that matters is in these four
files and the git history.

## Start of every session

1. Confirm where you are. On a Pi, **never** work in `/share/emon_Suite` itself, which is
   production; use the worktree (DESIGN 9.1).
   ```bash
   git -C /share/emon_Suite-live branch --show-current   # expect emon_live_ui
   git -C /share/emon_Suite-live pull
   ```
2. Read, in order: the root `CLAUDE.md` (container mounts, the 27-Sep-2026 deletion),
   this file, `PLAN.md`, then the `DESIGN.md` sections the next task cites.
3. Merge `master` into the branch if it has moved, so the branch never drifts far:
   `git merge origin/master`. Resolve, run the tests, commit.
4. Pick the first unticked task in `PLAN.md`. Each is sized for one session.

## End of every session

1. Tick the task in `PLAN.md`.
2. Add a dated line to the session log below: what was done, on which machine, anything
   left half-done, and anything learned that the design did not foresee.
3. If a decision changed, edit `DESIGN.md` and say so in the log. Do not leave a
   decision only in a commit message.
4. Commit with the docs in the same commit as the work, then **push**. An unpushed
   commit on a laptop is invisible to the Pi.

## Where it is up to

**Phase 1 deployed at shannstainable on 21 Oct 2026, 14:11. Phase 2 in progress.**
The enchantee deploy and the merge to `master` both wait until phase 2 is done (owner).
2a (the emon_live skeleton) is done. 2b's code is done: 62 derived feeds for
shannstainable, seeded from Influx on start. 2b is done, compared over a full day.
2c, the page engine and the house page, is done and needs the owner's look on a real
phone; 2d (Node-RED's own results) is next.
`emon_serial` and `emon_influx` there run the new images (`:latest` retagged locally,
old ones kept as `:pre-live-ui`). Enchantee is untouched. On the shannstainable Pi the new images exist locally as
`sfewings32/emon_serial_to_mqtt:live-test`, `emon_mqtt_to_influx:live-test` and
`emon_gpsd_to_mqtt:live-test`, built from `a008c56` plus the reconnect fix; none is
pushed to Docker Hub. Outside `python/pyEmon/` and these docs the branch changes only
`python/platform.sh` (armv7 now names the cp313 wheel).

How it was deployed, local only so enchantee cannot pull it by accident:

```bash
for i in emon_serial_to_mqtt emon_mqtt_to_influx; do
  docker tag sfewings32/$i:latest    sfewings32/$i:pre-live-ui   # the way back
  docker tag sfewings32/$i:live-test sfewings32/$i:latest
done
cd /share/emon_Suite/provisioning/shannstainable
docker compose up -d --no-deps emon_serial_to_mqtt emon_mqtt_to_influx
docker exec mqtt mosquitto_sub -v -t 'emon/config' -C 1 | cut -c1-120   # read only
```

Way back: the same loop tagging `:pre-live-ui` as `:latest`, then the same `up`. A
`docker compose pull` there would also put the old images back. Push to Docker Hub only
after a day of watching, at the merge, and before the enchantee deploy.

What exists, all in `python/pyEmon/`:

| File | What |
|---|---|
| `pyemonlib/emon_feed.py` | Reading, envelope, parse, Catalogue, Store, the shared maths. Stdlib only. |
| `pyemonlib/emon_decoder.py` | `decode(line, settings) -> [Emission]` for all 18 payload types |
| `pyemonlib/sink_mqtt.py`, `sink_influx.py` | the two sinks |
| `pyemonlib/emon_mqtt.py`, `emon_influx.py` | now shims over the above, same interfaces |
| `tests/legacy/` | the old two modules verbatim: the regression oracle. Never edit. |
| `tests/test_emon_feed.py` | 40 tests, need only pytest |
| `tests/test_decoder_regression.py` | old vs new for every site config; skipped without the extension |
| `tests/data/` | `emonlog_sample.txt` fixture and the script that makes it |

Behaviour changes a deploy will bring, both switchable per container:

- `emon/...` envelopes (retained) and `emon/config` are published. `EMON_ENVELOPES=0` off.
- Legacy MQTT topics of channels named Unused are no longer published (owner's decision).
  `EMON_SKIP_UNUSED=0` restores them. Influx unchanged.

## Machines

### Windows laptop (where this started)

- Repo at `C:\Users\StephenFewings\OneDrive - terra15 technologies\Documents\Home\emon\emon_Suite`,
  inside OneDrive. The sibling `..\emon-node-red` is the Node-RED repository.
- No `node`, no `python` on PATH: use the `py` launcher (`py -3`). Claude Code's
  PowerShell tool intermittently failed to spawn here; the Bash tool worked.
- Good for everything except deploying. The decoder regression test runs here too: the
  `pyEmon/dist` folder has a cp314 win_amd64 wheel matching this laptop's Python 3.14.
- Test setup used on 19 Oct 2026 (a throwaway venv outside the repo):
  ```bash
  py -3 -m venv <scratch>/venv
  <scratch>/venv/Scripts/python -m pip install pytest paho-mqtt influxdb-client pyyaml numpy pytz       python/pyEmon/dist/pyemonlib-0.1.0-cp314-cp314-win_amd64.whl
  cd python/pyEmon && <scratch>/venv/Scripts/python -m pytest -q tests
  ```
  Run pytest from `python/pyEmon`, not from inside `pyemonlib`; `tests/conftest.py` uses
  the source and borrows the compiled extension from the installed wheel. Expect 69
  passed: the regression test runs once per `emon_config/*.yml` in the working tree, so
  untracked config snapshots add cases (the laptop had 3 more and saw 78).

### shannstainable Pi (where this finishes)

- Hostname `raspberrypi`, aarch64, Python 3.11.2. Production checkout
  `/share/emon_Suite`, kept on `master`; development worktree `/share/emon_Suite-live`
  on `emon_live_ui` (created 19 Oct 2026). To pick up the branch here, `git -C
  /share/emon_Suite-live pull`; never `git checkout emon_live_ui` in production, which
  also stops the worktree being created (a branch can be checked out in one place only).
- Node-RED user directory `/share/emon-node-red`, on branch `nodeRed`.
- Compose for the site runs from `provisioning/shannstainable/` in the **production**
  checkout. A dev emon_live container should mount the worktree instead and publish a
  port that is free (5000, 1880, 1883, 3000, 8002, 8086, 9000 and 9443 are taken).
- Recorded serial logs for regression fixtures are in `/share/Input/`. The owner will
  supply a shannstainable sample; see PLAN 1c.
- `docker pull --platform linux/arm/v7 python:3.13` replaces the local arm64
  `python:3.13`, and the next image build then fails installing the aarch64 wheel. After
  any armv7 work, `docker pull --platform linux/arm64 python:3.13`.
- The venv used on 21 Oct is `/home/pi/.cache/emon_live_venv` (outside `/tmp`, which a
  reboot wipes): `pytest flask paho-mqtt pyyaml`. It serves both test suites.
- emon_live tests need only `flask`, `paho-mqtt`, `pyyaml` and `pytest` in a venv; run
  `python -m pytest -q tests` from `python/emon_live` (46 pass). To try it against the
  live broker, which is read-only for 2a: `python app.py --host 127.0.0.1 --port 5003`,
  then `curl 'http://127.0.0.1:5003/api/state?all=1'`.
- To see the pages: `python app.py --host 0.0.0.0 --port 5003 --site
  ../../provisioning/shannstainable/emon-ui` from `python/emon_live` (no `--publish`),
  then `http://<pi>:5003/` on a phone. Headless screenshots: `chromium --headless=new
  --no-sandbox --virtual-time-budget=8000 --window-size=390,1900 --screenshot=x.png URL`.
- **Every Influx query must be time-bounded** (`WHERE time > ...`), and never `SELECT *`
  without one; `ORDER BY time DESC LIMIT n` does not limit the scan. On 21 Oct 2026 an
  unbounded `SELECT * FROM rain|pulse ORDER BY time DESC LIMIT 3` was followed by the Pi
  stalling and the hardware watchdog (`RuntimeWatchdogSec=15`) resetting it, most likely
  Influx reading all of history since 2019 into memory. emon_live's seeding queries only
  ever ask for the period since a reset.
- Tests: a venv outside the repo with the same packages as the laptop and
  `python/pyEmon/dist/pyemonlib-0.1.0-cp311-cp311-linux_aarch64.whl`, then as above.
  No `mosquitto_sub`/`mosquitto_pub` on the host; use the `mqtt` container's, or paho.
- Test publishers against a separate mosquitto, never the live one (DESIGN 9.2).

### enchantee Pi (the boat)

- Only for phase 3 checks and deploys. Its own conventions are in the root `CLAUDE.md`
  and `python/enchantee_racing/CLAUDE.md`. The iPad mini 3 (iOS 12) is the browser floor.

## Open questions

Decided by the owner on 21 Oct 2026, for PLAN 2b:

- The "export" estimate (inverter 2 output minus the average import) is carried into
  `derived.yml` as Node-RED computes it.
- Month and year rainfall come from Influx, not Node-RED's text files.
- Battery mid-point maximum voltages are computed in emon_live (a `daily_max` operator),
  not Node-RED.

## Session log

- **2026-10-19, Windows laptop.** Design agreed (proposal revision 3, decisions D1 to D6
  confirmed by the owner). Branch `emon_live_ui` created from `master` at `5fc8975`.
  Wrote DESIGN, PLAN, HANDOVER, INVENTORY; copied `proposal.html`.
- **2026-10-19, Windows laptop, later the same day.** Phase 1a to 1d built and tested.
  Learned while building, now in DESIGN 4.1, 4.2 and 5: the two old publishers differ in
  layout, scaling, order and failure point far more than expected, hence the Emission
  design; the topic layout became `emon/<node>/<sub>/<field>[/<idx>]` because one node
  publishes several quantities of a kind; RSSI names carry the node type because
  shannstainable has a `Kitchen` display and a `Kitchen` air sensor. Owner decided: no
  legacy MQTT for channels named Unused; synthetic house data until they supply a log.
  Regression: 20,674 MQTT publishes and 9,318 Influx points identical across 12 configs.
  Branch not yet pushed.
- **2026-10-19, shannstainable Pi.** Found the production checkout switched to
  `emon_live_ui` (harmless: no container reads `python/pyEmon` or these docs). Put it
  back on `master` and created the worktree. Tests pass on the Pi (69). Added real house
  lines to the fixture (PLAN 1c), still identical old vs new. Learned:
  `make_emonlog_sample.py` read its GPS-with-RSSI line from an uncommitted file, so a
  regeneration anywhere but the laptop dropped it; the line is now in the script. `rain`
  and `hws` have no subnode, so the sampler keys them on type alone. Next: PLAN 1e.
- **2026-10-19, shannstainable Pi, later.** PLAN 1e test and build done; deploy not
  done, because the session's permissions stopped a production change; the owner runs
  the commands under "Where it is up to". A/B on a dev broker (`tests/ab/`), production
  image vs new, same replay of the fixture plus two hours of 18 Oct (house) and the
  Frostbite 1 recording (boat): legacy MQTT identical in order (133,415 messages)
  except 37 house and 2 boat topics, every one a channel named Unused; Influx line
  protocol byte-identical (129,821 and 41,133 lines); envelopes and `emon/config`
  retained. Boat also gains `gps/position/<sub>`, which is `master` (599e59e) against a
  March image, not this branch. Checked the Unused drop against Node-RED: Instant
  Data's `power/0/#`, `pulse/0/#` and `battery/voltage/0/#` functions already ignore
  channel 5 and voltages 2 to 4. Learned: production mosquitto has no persistence, so
  `emon/config` is now also published on reconnect (DESIGN 4.2, test added); the
  armv7 wheel was cp311 while the images are 3.13, so armv7 builds had been broken
  since Feb 2026 (now cp313, smoke-tested; nothing runs armv7); the exception lines the
  bridge prints are now named by node (`airException`, was `airQualityException`) and
  no longer appear for two-hop relayed lines of unconfigured subnodes. Wire output is
  unaffected. After the deploy, watch Instant Data and Grafana for a day, then tick it.
- **2026-10-21, shannstainable Pi.** Deployed at 14:11 as above. Checked against a
  minute of live traffic taken just before: `emon/config` and about 200 envelope topics
  retained; the legacy topics that stopped are the 21 Unused channels that were
  transmitting; Influx points per minute unchanged (power about 245, voltage about 330).
  `emon_serial` restarted 4 times on start with `UnicodeDecodeError` in
  `emonSerialToMQTT.py`'s `readline().decode('utf-8')`: opening the port mid-packet
  gives a partial line. That runner is unchanged from master, so the old image does the
  same on every restart; `restart: always` hides it. Fixed on the branch the same day
  (escape bad bytes; a garbled `RSSI` line and an empty subnode field also crashed it),
  so it reaches shannstainable with the next image rebuild. Next: watch for a day, then tick, then PLAN 1e enchantee
  (push the images to Docker Hub first, which is what enchantee pulls).
- **2026-10-21, shannstainable Pi, later.** Owner: phase 1 counts as deployed here; the
  enchantee deploy and the merge to master wait for the end of phase 2. PLAN 2a done:
  `python/emon_live/`, 18 tests on a capture of the 218 retained `emon/#` messages, and
  a run against the live broker (217 feeds by name, no duplicates, 2.4 KB gzipped).
  Decided while building, now in DESIGN 4.4: emon_feed from the source tree, feeds
  under a `feeds` key, `?all=1`, `/api/feeds` and `/api/config`, port 5003. Not yet
  done: no Dockerfile or compose service (PLAN 2e); feeds outside emon (ecowitt,
  pantech) are parsed by topic but not subscribed to.
- **2026-10-21, shannstainable Pi, evening.** The Pi froze and was reset by its hardware
  watchdog at 20:00, most likely by my unbounded Influx query (see Machines; now a rule,
  and in the seeding code). Owner decided the three 2b questions (Open questions). PLAN
  2b code done: operators in emon_feed (58 tests), `derived.py` and `influx.py` in
  emon_live (28 tests), `derived.yml` with 62 feeds, `tools/compare_nodered.py`. Matched
  Node-RED exactly from its restart at 20:01 to 20:30. Found, for the owner: the Schneider
  pulse meter (`pulse/0/1`) did not move all day, so Node-RED's and our "solar today"
  leave out Inverter Two (16.9 kWh against about 32 kWh with all three integrated);
  Node-RED's foregone figure is low because it rounds every 2-second step to whole Wh
  (ours does not); at night "battery in" rises while the batteries discharge, so the
  monitors' pulseIn may be discharge (names kept as Node-RED had them); mains and bore
  water (wtr 1) are not reporting; the tank height reads 0. Node-RED keeps its context in
  memory only, so every restart zeroes its day; ours resumes. Next: the full-day compare,
  then 2c.
- **2026-10-21, shannstainable Pi, later.** Owner's answers to the 2b findings, applied
  to derived.yml: the Schneider pulse meter no longer works, so solar today integrates
  all three inverters; the unrounded foregone figure is wanted (Node-RED's was long
  suspect); mains, bore and tank height sensors are not working. On the batteries: owner
  said current is positive out of the battery; Influx confirmed monitor 5's `pulseIn`
  counts that, so it is discharge, and Node-RED had battery in and out, and "out to
  9am", the wrong way round. Not a sensor offset: `pulseIn` stayed flat all day. Monitor
  4 (inverter shunts) is mounted the other way and Node-RED was right there (DESIGN 6.3).
  `compare_nodered.py` maps Node-RED's figures accordingly and still matches.
- **2026-10-21, shannstainable Pi, night.** PLAN 2c done: `ui/` engine with five tile
  parts, age states, server theme, menu and an `_all` page; `site.json` and
  `house.json` from the mockup; `ui/tools/lint_pages.py`, clean; 46 emon_live tests,
  including static iOS 12 checks. Rendered with live data in headless Chromium at 1280
  and 390 px, day and night. Decided while building, in DESIGN 6.2, 4.5 and 9.4 as built:
  tile types are parts of one tile; templates take `{feed|N}`; the linter checks against
  published names, not emon_config. Not yet seen on a phone or the iPad; the trail starts
  empty each time a page opens.
- **2026-10-23, shannstainable Pi.** The full-day comparison (PLAN 2b). emon_live ran
  from 21 Oct 21:33 by hand (not a container yet); Node-RED had not restarted since 21
  Oct 20:00. 22 Oct, replayed for that day, against Node-RED's midnight email
  (`/share/DailyEmail/Archive/DailyEmail-20261022.html`): consumed, import, HWS, car,
  hot water, rain, rail min and max, battery and inverter in and out, Leaf km all exact
  (within 2 Wh); export 16,242 against 16,237 Wh; mid-points within the email's
  rounding. Expected differences: solar 35.4 against 18.7 kWh (Inverter Two included);
  foregone +2 %; Node-RED's "out to 9am" (2,901 Wh) is exactly the batteries' charge
  from 00:00 to 09:00, confirming the swap, and ours is the discharge (3,147 Wh).
  Inverter 3's PV read 1.5 % low because it dropped out six times for 5 to 7 min in
  daylight and integrate does not bridge gaps over 5 min (Node-RED bridged 233 Wh); a
  longer max_gap for the inverters is the owner's call. Today to 09:46, against Node-RED's
  live context: the same. Fixed a bug in compare_nodered.py that hid the export row.
