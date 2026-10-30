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

**Merged into `master` on 27 Oct 2026** (owner's decision, ahead of phase 2's end on 30
Oct). Enchantee's emon_live then moved to run from the production checkout (session
log), and shannstainable's did on 29 Oct 2026, after the Energy page merged (`8fba9df`).
On both Pis nothing runs from a worktree now; a worktree is only where development is
done, never the production checkout (root CLAUDE.md).

**PLAN 2f, the Energy page and its Sankey, written on the laptop on 29 Oct 2026 and not
yet run anywhere** (owner's request). It needs no new image and no broker change: a
restart of emon_live is the whole deployment. Steps and what to compare against are in
"Checking the Energy page at shannstainable" below. Design in DESIGN 6.5.

**Phase 1 deployed at shannstainable on 21 Oct 2026, 14:11. Phase 2 in progress.**
**Phase 3 started on enchantee, 25 Oct 2026** (owner's request; see the session log).
**Phase 3 deployed on enchantee, 27 Oct 2026, 21:24**: http://enchantee.local/ is emon_live,
running from the worktree; Node-RED's dashboard is at /nodered/ui/. Waiting on a day's sailing.
The enchantee deploy and the merge to `master` were to wait until phase 2 was done; the
owner brought both forward (27 Oct).
2a (the emon_live skeleton) is done. 2b's code is done: 62 derived feeds for
shannstainable, seeded from Influx on start. 2b is done, compared over a full day.
2c, the page engine and the house page, is done (owner checked it on a phone, 23 Oct:
fine). 2d is done and deployed: the running Node-RED publishes showers, dog fed and tank days
on `emon/derived/...`. Mosquitto now keeps retained messages (master). 2e: the
`emon_live` container runs at shannstainable since 23 Oct, http://192.168.1.131:5003/
and https://shannstainable.fewings.org/live/ (host nginx, `location /live/`),
publishing `emon/derived/...`; it runs beside Instant Data until at least 6 Nov (owner,
30 Oct: another week), then the Dashboard 1 tabs go. After that, phase 2 is done and the branch can merge (owner).
`emon_serial` and `emon_influx` there run the new images (`:latest` retagged locally,
old ones kept as `:pre-live-ui`). Enchantee runs phase 1 since 25 Oct 2026, 20:59 (step 4 below done; the check, step 5,
is open). On the shannstainable Pi the new images exist locally as
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

## Deploying phase 1 at enchantee

Prepared on shannstainable, 25 Oct 2026. What reaches the boat is phase 1 only: the
bridge publishing `emon/...` envelopes and `emon/config` beside the legacy topics, plus
broker persistence. emon_live and pages for enchantee are phase 3 and do not exist yet.

1. **Images.** `sfewings32/emon_serial_to_mqtt`, `emon_mqtt_to_influx` and
   `emon_gpsd_to_mqtt`, built from this branch on 25 Oct (wheel included, serial crash
   fix included), tagged `:enchantee-candidate` on the shannstainable Pi. Boat A/B
   against the March image enchantee runs, enchantee's config, Frostbite 1: legacy
   topics identical in order (51,504 messages) apart from `gps/position/<n>` (from
   master, August) and the two Unused channels. The owner pushes them:
   ```bash
   for i in emon_serial_to_mqtt emon_mqtt_to_influx emon_gpsd_to_mqtt; do
     docker tag sfewings32/$i:enchantee-candidate sfewings32/$i:latest
     docker push sfewings32/$i:latest
   done
   ```
2. **On enchantee, before anything**: `cd /share/emon_Suite && git status && git log
   --oneline @{u}..` (which branch, uncommitted or unpushed work). That checkout is its
   deployment, and `enchantee_racing` and `event_recorder` run from it. The branch has
   everything on master, including every enchantee branch, and changes nothing under
   `python/enchantee_racing`, `python/event_recorder` or `provisioning/enchantee` beyond
   `mosquitto.conf`. Commit or stash local work first.
3. `git fetch && git checkout emon_live_ui`.
4. Keep the way back, then pull and recreate only the three bridges and the broker:
   ```bash
   cd /share/emon_Suite/provisioning/enchantee
   for i in emon_serial_to_mqtt emon_mqtt_to_influx emon_gpsd_to_mqtt; do
     docker tag sfewings32/$i:latest sfewings32/$i:pre-live-ui; done
   docker compose pull emon_serial_to_mqtt emon_mqtt_to_influx emon_gpsd_to_mqtt
   docker compose up -d --no-deps emon_serial_to_mqtt emon_mqtt_to_influx emon_gpsd_to_mqtt
   docker restart mqtt        # loads persistence; clients reconnect
   ```
   Way back: tag `:pre-live-ui` as `:latest` and the same `up`.
5. **Check** (PLAN 1e): `emon/config` and `emon/#` retained on the broker; the race
   app's HUD live; an event_recorder recording; Node-RED's pages; Grafana. On the
   water if possible, since that is when gps and the anemometer report.

## Deploying phase 3 at enchantee

Prepared on enchantee, 27 Oct 2026, in the worktree, and **run that evening** with the
owner (steps 1 to 5; session log). Backups: `/home/pi/.cache/nginx_default_before_live`
and `/home/pi/.cache/enchantee-dashboard_before_live`. Until the branch merges, emon_live runs from the worktree, as at
shannstainable; the nginx file and launcher are installed from it by hand.

1. **Image.** `sfewings32/emon_live:latest` is built on enchantee (27 Oct, from `803f1b2`),
   local only. Rebuild only when `python/emon_live/requirements.txt` changes:
   `cd /share/emon_Suite-live/python && ./build.sh -m local -c emon_live`.
2. **emon_live**, publishing `emon/derived/...` to the boat's broker and seeding today
   from its Influx (bounded queries; the battery and motor integrals replay since
   midnight):
   ```bash
   cd /share/emon_Suite-live/provisioning/enchantee
   docker compose -p enchantee --env-file /share/emon_Suite/provisioning/enchantee/.env \
       up -d --no-deps emon_live
   curl -s localhost:5003/api/state | head -c 300
   cd /share/emon_Suite-live && /home/pi/.cache/emon_live_venv/bin/python \
       ui/tools/lint_pages.py --broker localhost provisioning/enchantee/emon-ui
   ```
   `--env-file` reads the production `.env` in place, so no secrets are copied. Never
   start another service from the worktree's compose file. Way back: `docker rm -f
   emon_live`; nothing else depends on it until step 3.
3. **nginx**: `/` to emon_live. The installed file equals the repo's (checked 27 Oct).
   ```bash
   cp /etc/nginx/sites-available/default /home/pi/.cache/nginx_default_before_live
   sudo cp /share/emon_Suite-live/provisioning/enchantee/etc/nginx/sites-available/default \
       /etc/nginx/sites-available/default
   sudo nginx -t && sudo systemctl reload nginx
   ```
   Way back: copy the backup over it, `nginx -t`, reload. Node-RED's dashboard is at
   http://enchantee.local/nodered/ui/ throughout.
4. **Kiosk**: `sudo install -m 755
   /share/emon_Suite-live/provisioning/enchantee/usr/local/bin/enchantee-dashboard
   /usr/local/bin/`. It opens `?text=large#weather` from the next login.
5. **Check**: http://enchantee.local/ on the iPad and a phone (every page; Grafana frames
   on Navigation and Motor, which only resolve behind nginx), the kiosk after a login,
   `/hud`, `/race/`, `/events/`, `/nodered/ui/`. PLAN 3 is done after a day's sailing on
   the new pages; then Node-RED's dashboard can go.

## Checking the Energy page at shannstainable (PLAN 2f)

Written on the Windows laptop on 29 Oct 2026, where none of it could be run: `lint_pages.py`
and three of test_ui fail there before they reach this work (`derived.load` raises
`OverflowError: mktime argument out of range` on Windows, from the `reset: year` entry),
and there is no node and no headless browser. So everything below is still to do, in
this order. Design in DESIGN 6.5; the code is `python/emon_live/energy.py`,
`influx.Window`, `/api/energy`, `ui/tiles/sankey.js`.

**It needs no new container, no new image and no broker change.** The page is files in
this checkout and one new route in emon_live, so a restart of emon_live is the whole
deployment. Nothing publishes and nothing is written: `/api/energy` only reads Influx.

1. **Where does emon_live run here?** Since the 27 Oct merge it may be the production
   checkout rather than the worktree. Settle it before editing anything:
   ```bash
   docker inspect emon_live --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}'
   ```
   Work in whichever tree that names; if it is `/share/emon_Suite`, remember that the
   working tree is production (root CLAUDE.md) and prefer a branch.

2. **Tests and the linter**, from `python/emon_live` in that tree, with the venv at
   `/home/pi/.cache/emon_live_venv`:
   ```bash
   python -m pytest -q tests            # test_energy.py is 24 of them
   python ../../ui/tools/lint_pages.py ../../provisioning/shannstainable/emon-ui --broker localhost
   ```
   The linter is the one check this work added that the laptop could not run: it now
   reads the `sankey:` block and errors if a flow names a feed that does not exist, or
   if a flow's `of:` feed has no `influx:` series, which would leave that ribbon blank
   for every past period. Expect it clean.

3. **Restart emon_live and ask it for each period.** `docker restart emon_live`, then:
   ```bash
   for p in now today yesterday week month; do
     echo "== $p"; curl -s "http://127.0.0.1:5003/api/energy?period=$p" | python -m json.tool
   done
   ```
   What to look at in each answer:
   - `"failed": []`. A flow listed there means its Influx query failed or its series is
     missing; the container log says which.
   - `"balance"` near zero. It is sources minus named loads, before `other` takes up the
     slack. Large and positive is normal (the house used it); negative means the named
     loads exceed the sources, which is meters disagreeing and worth understanding.
   - `now` must cost no queries at all. It is read from the live store.

4. **Check the figures against what the House page already shows.** For `period=today`,
   each flow should agree with its `derived/.../today` total:

   | flow | agrees with | how it is found |
   |---|---|---|
   | `solar` | `derived/solar/today` | `integral` of the three inverters' PV |
   | `grid` | `derived/import/today` | `counter` on the import pulse meter |
   | `battery_out` | `derived/battery/out/today` | `counter`, monitor 5 pulseIn (pulseIn is discharge) |
   | `battery_in` | `derived/battery/in/today` | `counter`, monitor 5 pulseOut |
   | `car` | `derived/car/today` | `counter` |
   | `hws` | `derived/hws/today` | `counter` |
   | `export` | `derived/export/today`, **loosely** | `expr`, bucketed |

   The counters and the integral should match closely. **`export` is the one to look at
   properly.** It has no single Influx series (it is Inverter Two's output less the
   average import since midnight), so a past window is rebuilt from one-minute bucketed
   means and trapezoid-integrated, where the live total integrates every reading. It is
   marked `"approx": true` and drawn with "≈". If it is out by more than a few percent
   late in a sunny day, the bucket width is the first thing to change (`energy.STEP_S`).

5. **Look at the page**: `http://<pi>:5003/#energy`, or wherever the site is served.
   Click every tab. Then a phone, then the desktop. `ui/tools/sankey_preview.html` opened
   straight from the filesystem draws the same tile on a fixture, including a month with
   a failed flow, which is the quick way to judge the layout without waiting on queries.
   Headless, as elsewhere in this file:
   ```bash
   chromium --headless=new --no-sandbox --virtual-time-budget=8000 \
            --window-size=390,1900 --screenshot=energy.png 'http://127.0.0.1:5003/#energy'
   ```

6. **Then decide two things** and record them here: whether the Sankey also belongs as a
   tile on the House page, and whether "7 days" and "30 days" should instead be whole
   calendar weeks and months. They are rolling windows back from now (`energy.window`),
   chosen because they are cheap and need no explaining; a calendar month would want its
   own baseline, as `rain/month` does.

Way back: remove the `{"id": "energy"}` line from `site.json` and the page is gone from
the menu. The route and the block are inert without it.

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
- Node-RED user directory `/share/emon-node-red`, on branch `nodeRed`, bind-mounted into
  the running `node_red`: it is production, like `/share/emon_Suite`. Its `flows.json`
  carries changes since Aug 2026 never committed on `nodeRed`. Development is in the
  worktree `/share/emon-node-red-live`, branch `emon_live_ui` (created 23 Oct 2026, from
  a snapshot of the live flows). Node-RED saves `flows.json` compact on one line; keep
  it so (`json.dumps(o, separators=(",", ":"), ensure_ascii=False)` round-trips it
  exactly). Its flow context is in memory only.
- To run Node-RED's function code: there is no `node` on the host; per CLAUDE.md,
  `docker cp` a harness to `node_red:/tmp` and `docker exec node_red node /tmp/...`.
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
- Node-RED changes are deployed through its admin API: GET `/flows` with
  `Node-RED-API-Version: v2`, add the nodes, POST with `Node-RED-Deployment-Type: nodes`
  so only they start. Back up the GET first (`/home/pi/.cache/nodered_backup/`). Node-RED
  then saves the live `flows.json`, which after 2d equals emon-node-red's
  `emon_live_ui` tip.
- **`emon_live` runs as a container from the worktree** until the branch is merged,
  because `master` does not have it yet. Same compose project as the site, so it joins
  its network and reaches `mqtt` and `influxdb` by name; `--no-deps`, so nothing else is
  touched:
  ```bash
  cd /share/emon_Suite-live/provisioning/shannstainable
  docker compose -p shannstainable up -d --no-deps emon_live     # start or recreate
  docker restart emon_live                                       # after a code edit
  ```
  Never run any other service from the worktree's compose file: that would deploy the
  branch's definition of it. After the merge, start it from `/share/emon_Suite` as any
  other service. Page and `derived.yml` edits are read live; Python edits need the
  restart. The image only carries Flask, paho and PyYAML: rebuild it only when
  `requirements.txt` changes.
- **The Pi hard-resets now and then** (hardware watchdog, `RuntimeWatchdogSec=15`): boots
  with no clean shutdown on 10 Aug, 11 Sep, 1 Oct, 21 Oct 07:17 and 20:00, 23 Oct 10:07.
  Cause unknown; the journal loses its last minutes each time, and on 23 Oct its last 30.
  Both October ones in a session came during heavy work (an unbounded Influx query; a
  start-up replay plus headless Chromium beside two VS Code servers), so run those one
  at a time. Since 23 Oct Mosquitto saves retained messages every 5 min, so a reset loses
  at most that; Node-RED's day totals still restart (memory context); emon_live's replay.
  Another session on 23 Oct added zram, `sar` and `/var/log/memtop.log` (top processes by
  memory, every minute): read those first after a stall.
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

- Hostname `enchantee`, aarch64, Python 3.13.5, at 192.168.1.128 at the dock. Its own
  conventions are in the root `CLAUDE.md` and `python/enchantee_racing/CLAUDE.md`. The
  iPad mini 3 (iOS 12) is the browser floor.
- Production checkout `/share/emon_Suite` is back on `master` (25 Oct 2026; nothing the
  boat runs differs from the branch, and its images come from Docker Hub). Development
  worktree `/share/emon_Suite-live` on `emon_live_ui`, as at shannstainable.
- Node-RED user directory `/share/emon-node-red`, branch `Enchantee`, production.
  Its dashboard is the reference for phase 3; INVENTORY 4 lists its widgets and their
  topics, and the gauge ranges are in the flows (`ui_gauge` min, max, seg1, seg2).
- Venv `/home/pi/.cache/emon_live_venv`: `pytest flask paho-mqtt pyyaml`.
- Feed names: the boat is often quiet at the dock (no serial for 10 minutes at a time), so
  names come from decoding a recording. `20260517_Frostbite_1.TXT` (untracked, in
  `python/enchantee_racing/tests/data/` of the production checkout) through the new
  image's `emon_decoder` gives 65 names: docker cp a script, the config and the log to
  `/tmp` in `emon_serial`, run it, remove the three files by name.
- **Test bench** (DESIGN 9.2): a throwaway broker on 127.0.0.1:1884, the Frostbite log
  replayed into it in real time and in a loop through the new bridge image, and emon_live
  from the worktree on port 5003, reachable from the iPad at http://192.168.1.128:5003/.
  `replay_live.py` is kept in `python/pyEmon/tests/ab/`.
  ```bash
  AB=<scratch dir outside /share>; cp python/pyEmon/tests/ab/replay_live.py <frostbite log> $AB/
  docker network create emon_live_test
  docker run -d --name emon_live_test_mqtt --network emon_live_test \
      -p 127.0.0.1:1884:1883 eclipse-mosquitto mosquitto -c /mosquitto-no-auth.conf
  docker run -d --name emon_live_test_replay --network emon_live_test -e TZ=Australia/Perth \
      -v $AB:/ab:ro -v $PWD/provisioning/enchantee/emon_config:/data:ro \
      sfewings32/emon_serial_to_mqtt:latest \
      python /ab/replay_live.py emon_live_test_mqtt /data/20260211-1447.yml /ab/<log>
  cd python/emon_live && /home/pi/.cache/emon_live_venv/bin/python app.py --broker 127.0.0.1 \
      --broker-port 1884 --port 5003 --site ../../provisioning/enchantee/emon-ui --influx none
  # done: stop app.py; docker rm -f emon_live_test_replay emon_live_test_mqtt;
  # docker network rm emon_live_test
  ```
  `--influx none` matters: the default is the boat's production Influx. The replay has
  no `emon_gpsd` (`RaspPi-GPS`), and the Bimini sensor reports only in the first
  minutes, so lint reports those two as missing on the bench.

## Open questions

Decided by the owner on 29 Oct 2026, for PLAN 2f: the Sankey stays on the Energy page
and does not go on the House page; "7 days" and "30 days" stay rolling windows back from
now, not calendar weeks and months.

Decided by the owner on 23 Oct 2026: integrate keeps not bridging gaps over 5 min (no
15 min allowance for the inverters). The owner would rather find out why Inverter 3, and
others, drop out for 5 to 7 minutes at a time, but not as part of this work.

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
- **2026-10-23, shannstainable Pi, later.** Owner: the page is fine on a phone. PLAN 2d
  code: `emon-node-red` worktree and branch (see Machines), first commit a snapshot of
  the live flows, then one function, inject and mqtt out publishing showers, dog fed and
  tank days as retained envelopes, tested under Node in the container. emon-ui gains a
  `time` format; derived.yml gains `external:` and `dog/food/kg`; the house page shows
  the five new feeds, as dashes until Node-RED publishes them. Not done, waiting on the
  owner: deploying the nodes into the running Node-RED, and pushing the Node-RED branch
  (its snapshot carries the August WhatsApp nodes: a group id, no credentials). The
  inverter max_gap question (above, 23 Oct) is still open.
- **2026-10-23, shannstainable Pi, evening.** Owner's answers: deploy and push 2d,
  Mosquitto persistence, no 15 min gap allowance (find the cause later). Done: persistence
  on master (`f1cf77e`, merged here), broker restarted, `mosquitto.db` written at the
  first autosave; the four Node-RED nodes deployed through the admin API, publishing and
  retained; the emon-node-red branch pushed. The live `flows.json` now equals that
  branch's tip; `nodeRed` there still lacks the August changes, as before.
- **2026-10-23, shannstainable Pi, night.** PLAN 2e: Dockerfile, build.sh entry, compose
  service; container up from the worktree, healthy, publishing 61 derived feeds
  retained. Two faults found in the first minutes, both now fixed: PyYAML was missing
  from requirements.txt (the venv had it); and `consumed/today` read 58.6 million,
  because daily_delta took a backward reading for a counter restart. The real data has
  two kinds of backward reading: a corrupted serial line at 13:17:16 (every power-board
  counter a few thousand for one reading, another node's numbers), and relayed copies
  of packets arriving a second after the direct ones with the older count (Consumed
  alternating 8 Wh apart at 20:48 and 20:51). daily_delta now never goes backwards and
  needs three readings in a row from near zero to call a restart (DESIGN 6.3 as built,
  emon_feed tests). All 20 daily counters then equal Influx's last minus first for the
  day. Worth looking at with the inverter dropouts: why lines are corrupted, and that
  relayed duplicates reach MQTT and Influx at all.
- **2026-10-23, shannstainable Pi, late.** Owner asked for the new pages on the public
  site: `location /live/` in the host's `/etc/nginx/sites-available/default`, proxying
  to localhost:5003 with the prefix stripped, and `/live` redirecting to `/live/`
  (relative URLs need the slash). The repo's `LinuxInstall/` copy of that file had
  fallen behind the Pi's (/birds, /grafana2, Grafana's new address); replaced with the
  installed file, on master (merged here). Backup of the file before the change:
  `/home/pi/.cache/nginx_default_before_live`. Note that /live, like Node-RED at /, is
  open to anyone who finds it, and anyone can switch its theme (POST /api/settings).
- **2026-10-25, enchantee.** Deploy steps 1 to 4 of "Deploying phase 1 at enchantee".
  The checkout was already on `emon_live_ui`, clean; a reset-away commit `36fa2ab`
  (nginx default, shannstainable mosquitto.conf) is in `stash@{0}` and equals the
  branch's files, so nothing was lost. Enchantee had been running August images, not
  March; those are now `:pre-live-ui`. At 20:59 the three bridges were recreated from
  the Docker Hub images of 25 Oct 20:14 and the broker restarted: `emon_serial` and
  `emon_gpsd` each restarted once on `Connection refused` while it came back (`restart:
  always` covers it), 10 clients reconnected, `emon/config` is retained and
  `mosquitto.db` was written at the first autosave (21:04). Alongside, the boat's nodes
  were quiet: nothing on `#` in 30 s before the deploy, and `emon_serial` already
  restarting on its 600 s no-serial timeout. So no envelopes yet, and the HUD, a
  recording and Grafana are still to check (PLAN 1e), on the water if possible.
  Already so before the deploy: `event_recorder` unhealthy, its `/health` answering 200
  but in about 5 s, past the health check's timeout.
- **2026-10-25, enchantee, later.** Phase 3 started, ahead of the end of phase 2 at the
  owner's request. The production checkout went back to `master` and the worktree was
  created (see Machines). PLAN 3, first task done: `dial`, `compass`, `cell-bar` and
  `grafana` parts (DESIGN 6.2 as built); `link` menu entries already existed. A first
  draft of enchantee's `site.json` and five pages, from the Node-RED dashboard's widgets
  and ranges. Seen in headless Chromium on the test bench at 1024 px, day theme not yet.
  Learned: a padding-kept aspect box needs its width limit on a parent, because padding
  percentages are of the parent's width; Node-RED's battery voltage gauge (0 to 60,
  segments at 48 and 50) is coloured green below 48 V and red above 50 V, backwards for
  a 16S LiFePO4 pack resting at 52 to 54 V, so the draft has 40 to 60 with 50 warn and
  48 bad, downwards. Owner confirmed it, 27 Oct. Next: the iPad mini 3 check (PLAN 3, second
  task) on the bench; then fit the layout to the iPad and the kiosk.
- **2026-10-27, enchantee.** Owner checked the parts on the iPad mini 3 against the test
  bench: they look OK, to be improved later (PLAN 3 second task ticked). Bench removed.
  PLAN 3 derived.yml done: ops `twa`, `awa`, `leeway`, `heel` in derived.py over emon_feed's
  functions (DESIGN 6.3 as built), and `provisioning/enchantee/emon-ui/derived.yml` with
  them plus battery in and out and motor energy, its Influx series each confirmed on the
  boat's Influx with a bounded count. The draft pages show them. emon_live tests now lint
  enchantee's site against `tests/data/enchantee_feeds.txt`, the 65 names decoded from
  Frostbite 1, since the boat's broker is often empty at the dock. Not yet run against
  live or replayed data in emon_live: do that on the next bench. Next: fit the page
  layout to the iPad and the kiosk, then nginx and the kiosk launcher (PLAN 3).
- **2026-10-27, enchantee, later.** Bench back up with derived.yml loaded (replay at 4x):
  every derived feed live, TWA and leeway equal to a hand calculation from the raw feeds,
  leeway blank under 1 kn as meant. Expr now returns 0.0 for -0.0 (`max(-x, 0)`). Layout:
  pages take `cols`, the boat's pages use 2 with span-1 tiles, Navigation regrouped
  (course and speed with the rose; leeway, heel and an SOG trail; Grafana 180 px), and
  every page fits the iPad's 1024 by 690 and the kiosk's 1280 by 740. The kiosk is the
  Pi's DSI screen, 1280 by 800. Grafana frames read Not Found on the bench, which has no
  `/grafana/`; behind nginx they resolve. Next: serving (PLAN 3, last task), prepared in
  the worktree, deployed only with the owner.
- **2026-10-27, enchantee, night.** PLAN 3 serving prepared, not deployed: enchantee's
  nginx `location /` to emon_live (the repo copy and installed file were equal before),
  the kiosk launcher on `#dials`, an `emon_live` service in its compose file, and the
  image built locally (`build.sh -m local -c emon_live`; not on Docker Hub). Tried on the
  bench: the built image with the compose mounts, and a throwaway nginx with the new
  file in front (syntax-checked, then every page URL, `/api/state` and the theme POST
  through `/`, and the Dials page rendered at the kiosk's size). Learned: Node-RED's
  dashboard is already at `/nodered/ui/` through the `/nodered/` block, so the overlap
  needs no new location. Bench removed. Steps: "Deploying phase 3 at enchantee" above.
- **2026-10-27, enchantee, 21:24.** Phase 3 deployed, owner's go-ahead, steps 2 to 5 of
  "Deploying phase 3 at enchantee". emon_live up from the worktree (compose project
  `enchantee`, `--env-file` the production `.env`), healthy, connected to `mqtt`, 10
  derived feeds loaded. The boat's nodes were off: only `emon/config` retained, nothing
  in Influx since midnight (replayed 0 readings), `emon_serial` at 291 restarts on its
  no-serial timeout, so every tile reads "no data" until they are powered. nginx: backed
  up, replaced, `nginx -t`, reloaded; `/`, the site files and `/api/state` 200 and
  gzipped; `/nodered/ui/`, `/nodered/`, `/race/`, `/events/`, `/grafana/`, `/settings/`
  200; `/hud` 302 to `/race/hud`; Navigation's Grafana frame now resolves. Launcher
  installed; the kiosk's open window (`--app=http://enchantee.local/`) shows the new
  pages on its next reload, `#dials` from the next login. Still open: PLAN 1e's checks
  and this page check with the nodes on, on the water if possible; the owner's look on
  the iPad and the kiosk; whether Navigation should embed Node-RED's choice of panel
  (Power, "Battery Voltage"). The production checkout is still on `master`, so emon_live
  runs from the worktree until the merge (as at shannstainable).
- **2026-10-27, enchantee, 22:05.** Owner's changes to the kiosk pages, made live (the site
  folder and ui/ are mounted from the worktree): Dials page and the HUD and Race links
  removed; menu Motor, Navigation, Weather, Battery, Motor the default; `"menu": "large"`
  doubles the tabs (DESIGN 6.2); Navigation's Grafana panel (Power, "Battery Voltage")
  moved to Battery beside Battery power. The launcher now opens `#motor`, installed in
  /usr/local/bin again. Checked at the kiosk's size through nginx with replay 1's data.
- **2026-10-27, enchantee, 22:10.** Reading colours (DESIGN 6.2, owner): every reading on
  the four boat pages tinted as on Node-RED's pages and in the race app (from the
  Node-RED flows' `className` per widget and the race app's palette, which was copied
  from them). Seen at the kiosk's size in both themes with replay 1's data (the day
  theme on a private read-only instance on :5004, so the boat's screens kept theirs).
  Found, for the owner: in the 13 Sep recording `Anemometer / pressure` reads about
  101,820 "hPa", where May's read 1017: pascals under an hPa label, from the node or the
  config, not the decoder's scaling, which is unchanged. Replay 1 ran 21:36 to 22:10.
- **2026-10-27, enchantee, 22:40.** Owner: Navigation's Course and speed shows
  Enchantee-GPS latitude and longitude to 6 places; Boat's COG − HDG relabelled Leeway
  (it was the leeway already); an All feeds tab (the built-in `_all` page, as at
  shannstainable). The engine now prints a GPS position ({lat, lon}) as "lat, lon" to 6
  places, where `_all` had shown "[object Object]", and `_all` puts such a value on a
  small line; a values item with no feed of its own shows no dash. Replay 2 started 22:19.
- **2026-10-27, enchantee, 22:45.** Owner reordered the pages: Weather, Navigation, Battery,
  Motor, All feeds. Weather is the default and the kiosk launcher opens `#weather`
  (installed in /usr/local/bin).
- **2026-10-27, enchantee, 22:55.** Owner: double the text on the kiosk. `?text=large`
  (DESIGN 6.2), the kiosk launcher opens `?text=large#weather` (installed), the iPad and
  phones unchanged. Weather's roses lose their legends to fit. Learned: headless
  Chromium's `--window-size` includes about 88 px of window, so a shot at 1280x740 shows
  a 652 px viewport; the earlier "fits 1024 by 690" checks were in fact at about 600,
  stricter than meant. To see a 740 px viewport, ask for 828.
- **2026-10-27, enchantee, 23:10.** The owner had installed pages as Chromium web apps,
  which on plain HTTP always show Chromium's "Not secure" origin strip; the Enchantee
  Dashboard launcher (`--app=`) does not, and is what the kiosk uses. To make it always
  open maximised, whatever size Chromium remembers: a labwc window rule (Maximize, app id
  `*enchantee.local*`) in `/home/pi/.config/labwc/rc.xml`, provisioned at
  `provisioning/enchantee/home/pi/.config/labwc/rc.xml`, labwc reloaded with SIGHUP.
  Backup `/home/pi/.cache/labwc_rc.xml_before_maximize`. Learned: no `--` inside an XML
  comment; a first try had `--app=` in one, and labwc briefly held an invalid file.
- **2026-10-27, enchantee, 23:15.** Owner: the race app's font. `"font": "race"` in
  enchantee's site.json (DESIGN 6.2). Replay 3 started 23:11.
- **2026-10-27, enchantee, 23:28.** Owner: black panels at night. `"night": "black"` in
  enchantee's site.json (DESIGN 6.2). Desktop items for /race/gar and /grafana/ added
  (`--app=` windows, provisioned under home/pi/Desktop).
- **2026-10-27, enchantee, 21:36 to 23:33. Replays on the production broker**, at the
  owner's request, to see the deployed pages with data: `20260913_Frostbite_1.TXT` at 5x,
  three times, each a container `emon_replay_<n>` (`replay_live.py ... 5 1` on the
  `enchantee_default` network, broker `mqtt`), EmonLog included, so Influx and the raw
  log stored them. event_recorder's anchor event started two recordings per replay on
  its own (`track_recording`, `anchor_track_recording`; auto_publish off, none posted).
  Race app and emon_live agreed on TWA (-172.3 against -172). Cleaned up with
  `/home/pi/.cache/replay_tonight/cleanup.py --apply`, bounded by each container's start
  and finish (5 s margin), after a baseline taken before the first replay: Influx
  points in the windows deleted (665,339), today's `/share/Input/20261027.TXT` removed
  (it held only replay lines; copy kept there), recordings #104 to #109 deleted (the
  last two stopped and left to finish processing first), containers removed,
  `enchantee_racing`, `node_red` and `emon_live` restarted. Afterwards: 0 Influx points
  since midnight, no raw log, recordings back to #103, the race app's trail empty, so
  tonight's 00:01 email starts from nothing. To do it again: the same script and a new
  baseline; it refuses while a replay runs. event_recorder was unhealthy (slow /health)
  throughout, as before the replays.
- **2026-10-27, enchantee, 23:43. Merged into `master`** (owner), with master's own
  unpushed race app commit (`a0b3922`, GAR heel). No file was changed on both sides. On
  the merged tree: emon_live 55 and emon_feed 61 tests pass; the race app's
  `test_heel_subscribes_to_the_topics_emon_mqtt_actually_publishes` failed, because it
  read `emon_mqtt.py`'s imuMessage, now a shim; it reads `emon_decoder._imu` instead and
  all 440 pass. Enchantee's emon_live recreated from `/share/emon_Suite` (mounts checked;
  10 derived feeds; 200 through nginx). Branch `emon_live_ui` fast-forwarded to master;
  the worktree stays for development. The decoder regression test was not run here (it
  needs the wheel installed in a venv); it last passed at shannstainable.
- **2026-10-29, Windows laptop.** PLAN 2f, the Energy page and its Sankey, at the owner's
  request: solar, grid, battery, car, hot water and export, over now, today, yesterday,
  the last 7 days and the last 30. Built: `python/emon_live/energy.py`, the `sankey:`
  block in shannstainable's derived.yml, `influx.Window`, `/api/energy`,
  `ui/tiles/sankey.js` with its CSS, `pages/energy.json`, `tests/test_energy.py` (24),
  and the linter now checks the block's feeds. Design in DESIGN 6.5.
  Learned, and not foreseen by the design: the live store answers "now" and nothing else,
  so a period selector needs Influx, which is why this is an endpoint of its own and not
  more of `/api/state`. The export estimate has no single Influx series (it is Inverter
  Two less the average import), so the `expr` method rebuilds it from bucketed means; it
  is an estimate, marked "≈" on the diagram, and wants checking against
  `derived/export/today` on the Pi.
  **Not checked on this machine**: `derived.load` raises `OverflowError: mktime argument
  out of range` on Windows (the `reset: year` entry), so `lint_pages.py`, test_ui's three
  lint tests and all of test_derived cannot run here; they are not affected by this work.
  There is no node and no headless browser on this laptop either, so the tile has not
  been rendered. `ui/tools/sankey_preview.html` draws it on a fixture in any browser,
  and the real check is the page on the Pi. The steps for that are in "Checking the
  Energy page at shannstainable" above.
- **2026-10-29, shannstainable Pi.** Pulled: the production checkout fast-forwarded to
  master (`e01dacb`; only the compose file's new `emon_live` service touched anything a
  container mounts, and it is not applied); master merged into the branch. emon_live
  here still runs from the worktree, on purpose: PLAN 2f was only on the branch. 2f
  checked on the Pi (PLAN): one bug, the month's export integrated to nothing because
  its buckets are 900 s apart and the trapezoid refused any step over 300 s; now it may
  bridge one bucket. Today's figures: solar 49,480 against 49,313 Wh (Influx's
  `integral()` bridges inverter dropouts, derived.yml does not), export 17,712 against
  17,784 Wh, every counter exact. The Today tile's five-digit Wh no longer fit half a
  phone: Solar and Consumed are in kWh via a new `scale` on values. Next: the owner's
  two 2f decisions, then merge to master and move emon_live onto the production checkout.
- **2026-10-29, later.** Owner's 2f decisions (Open questions): Sankey on the Energy page
  only; rolling 7 and 30 days. 2f is done.
- **2026-10-29, evening.** The Energy page merged to master (`8fba9df`, no-ff, as the
  earlier merges). shannstainable's production checkout pulled it and emon_live was
  recreated from `/share/emon_Suite/provisioning/shannstainable` (`up -d --no-deps
  emon_live`): healthy, mounts read-only from `/share/emon_Suite`, /live/ and
  /api/energy answering. No container on this Pi mounts `/share/emon_Suite-live` or
  `/share/emon-node-red-live` any more.
- **2026-10-29, night.** PLAN 2g, battery banks on the Energy page (DESIGN 6.6), built
  and checked against the real Influx in a development emon_live on port 5004 (the
  worktree, no `--publish`). Every period answers; 30 days ~30 s the first time, cached
  after. Found on the way: the Sankey's cache never answered 7 or 30 days (it compared a
  rolling window's start), fixed in both; the Leaf BMS has 12 wired cells of 16 slots and
  sends impossible SoC (610, 354), Bank 3's S5 read 107.49 V once, both now filtered by
  `range`; the Main battery monitor's own bank shunts are dead (frozen counters), so the
  banks use LiFePO monitor 5. Bank 2's cell 16 went both lowest and highest over 30 days,
  and Bank 3's S1 sagged to -1.355 V: worth the owner's eye. Waiting on the owner's look
  before merging.
- **2026-10-29, night, later.** Owner approved the banks card. Merged to master
  (`ab3f560`), production's emon_live restarted: 4 banks loaded, /live/api/banks answers
  now and today through nginx with nothing failed. The development instance on 5004 is
  stopped.

- **2026-10-30, shannstainable Pi.** PLAN 2h, supply to demand on the Sankey (DESIGN 6.7),
  after the owner described the two circuits and chose export option 2, a switch on the
  tile, and House Main / House Office. Built and checked against the real Influx in a
  development emon_live on port 5004 (worktree, no `--publish`): 0.7 s a day, 3.2 s for
  30 days, Unmatched under 0.1 %, counter totals equal to the house view's. Found on the
  way: the inverters' PV buckets are sparse at a minute, so W feeds are held forward (5 min
  gap rule); the banks card showed the Leaf bank's power with the wrong sign (its BMS
  already reports + as out), fixed. The new export estimate reads ~3 kWh a day lower than
  Node-RED's (14.9 against 18.1 kWh on 30 Oct). Each inverter also reports `power` (AC
  out, `inverter/power/N`), not used yet. Waiting on the owner's look before merging.
- **2026-10-30, the same session. A development instance knocks production off the
  broker.** Both connected as MQTT client `emon-live`, and the broker drops a client when
  another connects with its id: production's emon_live was disconnected every 1-2 s for
  the 40 s the 5004 instance ran (20:16:20 to 20:16:59), and its log shows the same 525
  times in the 19:00 hour of 29 Oct, the 2g development instance. Fixed in app.py:
  `--client-id` / `MQTT_CLIENT_ID`, defaulting to `emon-live` when publishing and
  `emon-live-view-<port>` otherwise, so a read-only instance can no longer collide.
- **2026-10-30, 21:16.** Owner approved supply to demand. Merged to master (`d8e4406`),
  production's emon_live restarted: healthy, replay rebuilt today's export with the new
  estimate (14.96 kWh against Node-RED's 18.05), `derived/office/nightLoad` 166 W, and
  /live/api/energy answers both views, now and today, through nginx with nothing failed;
  Unmatched 59 Wh today. The development instance on 5004 is stopped.
