# emon live UI redesign: plan

The phased task list for branch `emon_live_ui`. Design and rationale are in `DESIGN.md`;
cite it by section. Progress is recorded by ticking boxes here **and** adding a line to
the session log in `HANDOVER.md`, in the same commit.

Work is expected to be intermittent, over several sessions and months, on more than one
machine. So:

- Every task is sized to finish in one session and leave the branch working.
- Every phase ends with something deployable and a way back.
- Nothing in a phase depends on a later phase. Phases 1 to 3 can each be merged to
  `master` on their own.
- Where a task needs a particular machine, it says so.

Machine key: **any** (Windows laptop or Pi), **Pi** (shannstainable Pi, worktree per
DESIGN 9.1), **boat** (enchantee Pi or the boat's iPad).

---

## Phase 0. Branch and handover (done 19 Oct 2026, Windows laptop)

- [x] Branch `emon_live_ui` from `master` in emon_Suite.
- [x] `docs/emon_live_ui/`: DESIGN, PLAN, HANDOVER, INVENTORY, proposal.html.
- [x] Pointer in the root `CLAUDE.md`.
- [x] Push the branch to origin so the Pi can fetch it.

---

## Phase 1. Self-describing MQTT and emon_feed

Goal: the bridge publishes the envelope and `emon/config` alongside every legacy topic,
and `emon_feed` exists with tests. **No consumer changes.** Legacy topics are
byte-identical.

### 1a. emon_feed core (done 19 Oct 2026, laptop)
- [x] `pyemonlib/emon_feed.py`, standard library only (DESIGN D4): `Reading`,
      `envelope(reading) -> str`, `parse(topic, payload) -> Reading | None` accepting
      envelopes and bare numbers, `Catalogue` (built from the names in the envelopes
      themselves, DESIGN 5).
- [x] `tests/test_emon_feed.py`, runnable with only pytest. Include a test that importing
      `emon_feed` imports none of `emonSuite`, `paho`, `influxdb_client`, `yaml`.

### 1b. Ported calculations (done 19 Oct 2026, laptop)
- [x] Copy `norm180` (`python/enchantee_racing/engine/nav.py`) and the TWA, AWA
      fallback, leeway and heel derivations (`store.py`: `derive`, `derive_leeway`,
      `derive_heel`) into `emon_feed`, **with their tests**. Do not change the race app;
      it keeps its own copies until it migrates (DESIGN 7).
- [x] Distance between fixes (`event_recorder/live_summary.py` `_metres`, and the
      Haversine sum in `data_processor.py`) and trapezoidal W to Wh integration
      (`data_processor.py` `_calculate_energy_statistics`). Same rule.
- [x] `Store` with `{v, t}` and age, generalised from the race app's `store.py`.

### 1c. Decoder (done 19 Oct 2026, laptop, using the cp314 Windows wheel)
- [x] `pyemonlib/emon_decoder.py`: `decode(line, settings) -> list[Emission]` for all 18
      payload types, each Emission carrying the canonical Reading plus the legacy MQTT
      and Influx forms as thunks (DESIGN 4.1, as built).
- [x] Regression harness `tests/test_decoder_regression.py`: for each
      `provisioning/<site>/emon_config`, run recorded `EmonLog` lines through the old
      `emon_mqtt` and `emon_influx` (with mocked clients capturing every publish and
      Point) and through decoder plus new sinks, and assert identical legacy publishes
      and identical Points. Fixture `tests/data/emonlog_sample.txt` (452 lines, made by
      `make_emonlog_sample.py`): synthetic house lines for every subnode with RSSI and
      relay variants, real boat lines from the Frostbite recordings, rejected lines.
- [x] **Add a real shannstainable log to the fixture** (done 19 Oct 2026, Pi): 138 lines
      from `/share/Input/20261018.TXT`, six per node type and subnode. Regenerate only on
      the shannstainable Pi; the command is in the script's docstring.

### 1d. Sinks and shims (done 19 Oct 2026, laptop)
- [x] `sink_mqtt.py`: legacy topics unchanged except channels named Unused (owner's
      decision, DESIGN 4.2), plus retained envelope on `emon/<node>/<sub>/<field>[/<idx>]`,
      plus retained `emon/config` on load, on every settings reload and on reconnect.
- [x] `sink_influx.py`: generic Point from a Reading, tags as today.
- [x] `emon_mqtt.py` and `emon_influx.py` reduced to shims over decoder and sinks, same
      class names and constructor signatures (DESIGN D4). Regression test passes.

### 1e. Deploy (Pi, then boat)
- [x] Check no consumer subscribes to `#` and would be flooded by retained envelopes.
      Checked 19 Oct 2026: emonMQTTToLog and emonMQTTToInflux take `EmonLog/#`;
      event_recorder and the race app subscribe to named topics; Node-RED's
      subscriptions on `nodeRed` and `Enchantee` are all specific. Recheck harvey-farm's.
- [x] Test against a dev mosquitto on 1884 with a replayed log (DESIGN 9.2). Done 19 Oct
      2026 on the Pi with `python/pyEmon/tests/ab/` (production image vs new image, same
      replay, same broker, capture compared in order). Result in HANDOVER's session log.
- [x] Rebuild the wheel for arm64 and armv7 (DESIGN 9.3), then the
      serial_to_mqtt, mqtt_to_influx and gpsd images. Wheels cp313 for both, committed;
      images built on the Pi as `:live-test`, **not pushed** to Docker Hub.
      mqtt_to_log only imports pyemonlib, so it was not rebuilt.
- [x] Deploy at shannstainable. Watch Node-RED Instant Data and Grafana for a day.
      Deployed 21 Oct 2026 14:11 (local images, see HANDOVER).
- [ ] **Deferred until after phase 2** (owner, 21 Oct 2026). Deploy at enchantee. Check the race app HUD and an event_recorder recording still
      work.

Done when: both sites publish `emon/#` and `emon/config` and nothing downstream noticed.
Way back: redeploy the previous image tags (`:pre-live-ui` at shannstainable).
**Owner, 21 Oct 2026:** phase 1 is not merged on its own. The branch merges to `master`
at the end of phase 2 at the earliest, and the enchantee deploy waits until then; push
the rebuilt images (with the `emonSerialToMQTT` fix) to Docker Hub at that point.

---

## Phase 2. emon_live and emon-ui at shannstainable

Goal: a phone-friendly replacement for Instant Data, running beside it.

### 2a. emon_live skeleton (done 21 Oct 2026, Pi)
- [x] `python/emon_live/`: Flask app, MQTT client into `emon_feed.Store`, `/api/state`
      (DESIGN 4.4), serving `ui/` and the site folder. Relative URLs only.
- [x] Tests using a fake clock and injected messages, no broker. Input is a capture of
      every retained `emon/#` message at shannstainable (`tests/data/`).

### 2b. derived.yml (code done 21 Oct 2026, Pi; the full-day comparison remains)
- [x] Operators `daily_delta`, `integrate`, `sum`, `expr` (DESIGN 6.3) in `emon_feed`,
      wired up in emon_live, publishing `emon/derived/...` (with `--publish`). Also
      `daily_max`, `daily_min`, `mean`, `window_delta`; see DESIGN 6.3 as built.
- [x] Influx seeding on start (Pi to test): a bounded replay of each input, and a
      `first()` baseline for month and year.
- [x] `provisioning/shannstainable/emon-ui/derived.yml`, covering INVENTORY 2 rows marked
      `derived.yml`: 62 feeds.
- [ ] Compare each against the Node-RED figure for a full day:
      `python tools/compare_nodered.py` late in a day Node-RED has run since midnight
      (from `python/emon_live`). Matched exactly on 21 Oct for 20:01 to 20:30 (after a
      reboot, `--from 20:01`), but at night: solar, export and foregone untested.

### 2c. UI engine (any, check on a phone)
- [ ] `ui/`: engine, `value`, `gauge`, `trail`, `led` tiles, age states (DESIGN D6),
      theme as server state, domain colours (DESIGN 4.5). iOS 12 rules from the start.
- [ ] `ui/tools/lint_pages.py` (DESIGN 9.4).
- [ ] `provisioning/shannstainable/emon-ui/site.json` and `pages/house.json`, laid out as
      the proposal mockup.

### 2d. Node-RED publishes its single-site results (Pi, emon-node-red repo)
- [ ] In `emon-node-red`, branch `emon_live_ui` from `nodeRed`. Add function nodes that
      publish shower count and minutes, showers remaining, dog last fed and food
      remaining, tank days remaining, as envelopes on `emon/derived/...` (DESIGN D5,
      INVENTORY 2 rows marked `Node-RED`).

### 2e. Deploy (Pi)
- [ ] `emon_live` service in `provisioning/shannstainable/docker-compose.yml`, code
      bind-mounted, site folder read-only.
- [ ] Run beside Instant Data for a week. Then disable the Dashboard 1 tabs.

Done when: the family uses the new page on phones and the desktop, and daily totals
survive a restart. Way back: Instant Data is untouched until the last step.

---

## Phase 3. enchantee

Goal: the boat's Node-RED pages replaced, on the iPad mini 3 and the Waveshare kiosk.

- [ ] Tiles `dial`, `compass`, `cell-bar`, `grafana`, page menu with `link` entries (any).
- [ ] **Check on the iPad mini 3 before anything else** (boat).
- [ ] `provisioning/enchantee/emon-ui/`: `site.json`, pages `dials`, `navigation`,
      `weather`, `motor`, `battery`; HUD and Race as links to the race app (INVENTORY 4).
- [ ] `derived.yml` with `twa`, `awa`, `leeway`, `heel`, battery energy (DESIGN D3).
- [ ] nginx and kiosk launcher changes in `provisioning/enchantee/etc/...` (DESIGN 6.4).
      Keep Node-RED's UI at `/nodered/ui/` until a sail has been done on the new pages.

Done when: a day's sailing on the new pages. Way back: restore the nginx `/` location.

---

## Phase 4. Consolidation

- [ ] office-temperature and harvey-farm `emon-ui/` folders. office-temperature is the
      proof that a new site needs no code.
- [ ] Move each site's flows to `provisioning/<site>/node-red/flows.json`; shared
      `settings.js` takes `flowFile` from the environment; drop dashboard packages;
      archive the per-site `emon-node-red` branches (DESIGN 4.6).
- [ ] Update the runners to use decoder and sinks directly; delete the `emon_mqtt.py`
      and `emon_influx.py` shims (DESIGN D4). Only after `replay.py` in the race app has
      moved too, or been given its own shim.

---

## Later, separate projects (not this branch)

- `enchantee_racing`: names instead of its `TOPICS` map; import emon_feed operators.
- `event_recorder`: snapshot `emon/config` per recording; label plots from it; plots by
  kind; record derived feeds; emon_feed for distance and energy.
- Generic daily email (DESIGN 8).
- Stop publishing legacy topics (DESIGN 8).
