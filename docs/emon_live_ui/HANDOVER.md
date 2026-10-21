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

**Phase 1 deployed at shannstainable on 21 Oct 2026, 14:11; being watched for a day.**
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
- Tests: a venv outside the repo with the same packages as the laptop and
  `python/pyEmon/dist/pyemonlib-0.1.0-cp311-cp311-linux_aarch64.whl`, then as above.
  No `mosquitto_sub`/`mosquitto_pub` on the host; use the `mqtt` container's, or paho.
- Test publishers against a separate mosquitto, never the live one (DESIGN 9.2).

### enchantee Pi (the boat)

- Only for phase 3 checks and deploys. Its own conventions are in the root `CLAUDE.md`
  and `python/enchantee_racing/CLAUDE.md`. The iPad mini 3 (iOS 12) is the browser floor.

## Open questions

- Whether the "export" estimate in Node-RED (inverter 2 output minus average night-time
  import) is worth carrying into `derived.yml` or should be replaced with something
  simpler. Decide in PLAN 2b with a day of numbers side by side.
- Whether month and year rainfall should come from an Influx query in emon_live or stay
  with Node-RED's text files. PLAN 2b.
- Whether a `daily_max` operator is needed for battery mid-point voltages, or whether
  that stays in Node-RED. PLAN 2b.

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
