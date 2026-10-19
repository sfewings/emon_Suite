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
- [ ] Push the branch to origin so the Pi can fetch it.

---

## Phase 1. Self-describing MQTT and emon_feed

Goal: the bridge publishes the envelope and `emon/config` alongside every legacy topic,
and `emon_feed` exists with tests. **No consumer changes.** Legacy topics are
byte-identical.

### 1a. emon_feed core (any)
- [ ] `pyemonlib/emon_feed.py`, standard library only (DESIGN D4): `Reading`,
      `envelope(reading) -> str`, `parse(topic, payload) -> Reading | None` accepting
      envelopes and bare numbers, `Catalogue` (name resolution from an `emon/config`
      document, DESIGN 5).
- [ ] `tests/test_emon_feed.py`, runnable with only pytest. Include a test that importing
      `emon_feed` imports none of `emonSuite`, `paho`, `influxdb_client`, `yaml`.

### 1b. Ported calculations (any)
- [ ] Copy `norm180` (`python/enchantee_racing/engine/nav.py`) and the TWA, AWA
      fallback, leeway and heel derivations (`store.py`: `derive`, `derive_leeway`,
      `derive_heel`) into `emon_feed`, **with their tests**. Do not change the race app;
      it keeps its own copies until it migrates (DESIGN 7).
- [ ] Distance between fixes (`event_recorder/live_summary.py` `_metres`, and the
      Haversine sum in `data_processor.py`) and trapezoidal W to Wh integration
      (`data_processor.py` `_calculate_energy_statistics`). Same rule.
- [ ] `Store` with `{v, t}` and age, generalised from the race app's `store.py`.

### 1c. Decoder (Pi, needs the C++ extension)
- [ ] `pyemonlib/emon_decoder.py`: `decode(line, settings) -> list[Reading]` for all 18
      payload types in `emon_mqtt.dispatch`. Reproduce scaling and special cases exactly
      (DESIGN 4.1).
- [ ] Regression harness `tests/test_decoder_regression.py`: for each
      `provisioning/<site>/emon_config`, run recorded `EmonLog` lines through the old
      `emon_mqtt` and `emon_influx` (with mocked clients capturing every publish and
      Point) and through decoder plus new sinks, and assert identical legacy publishes
      and identical Points. Fixture lines: a day from `/share/Input/` at shannstainable;
      an enchantee recording exported from event_recorder for bms, gps, mwv, imu, svc, pth.
      Commit a trimmed fixture (a few hundred lines per type), not whole days.

### 1d. Sinks and shims (Pi)
- [ ] `sink_mqtt.py`: legacy topic unchanged, plus retained envelope on
      `emon/<kind>/<node>-<sub>/<idx>`, plus retained `emon/config` on load and on every
      settings reload.
- [ ] `sink_influx.py`: generic Point from a Reading, tags as today.
- [ ] `emon_mqtt.py` and `emon_influx.py` reduced to shims over decoder and sinks, same
      class names and constructor signatures (DESIGN D4). Regression test passes.

### 1e. Deploy (Pi, then boat)
- [ ] Test against a dev mosquitto on 1884 with a replayed log (DESIGN 9.2). Confirm with
      `mosquitto_sub -v -t 'emon/#'` and that legacy topics match.
- [ ] Rebuild the wheel for arm64 and armv7 (DESIGN 9.3), then the
      serial_to_mqtt, mqtt_to_influx and gpsd images.
- [ ] Deploy at shannstainable. Watch Node-RED Instant Data and Grafana for a day.
- [ ] Deploy at enchantee. Check the race app HUD and an event_recorder recording still
      work.

Done when: both sites publish `emon/#` and `emon/config`, nothing downstream noticed,
and the branch is merged to `master`. Way back: redeploy the previous image tags.

---

## Phase 2. emon_live and emon-ui at shannstainable

Goal: a phone-friendly replacement for Instant Data, running beside it.

### 2a. emon_live skeleton (any)
- [ ] `python/emon_live/`: Flask app, MQTT client into `emon_feed.Store`, `/api/state`
      (DESIGN 4.4), serving `ui/` and the site folder. Relative URLs only.
- [ ] Tests using a fake clock and injected messages, no broker.

### 2b. derived.yml (any)
- [ ] Operators `daily_delta`, `integrate`, `sum`, `expr` (DESIGN 6.3) in `emon_feed`,
      wired up in emon_live, publishing `emon/derived/...`.
- [ ] Influx seeding of `daily_delta` baselines on start (Pi to test).
- [ ] `provisioning/shannstainable/emon-ui/derived.yml`, covering INVENTORY 2 rows marked
      `derived.yml`. Compare each against the Node-RED figure for a full day.

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
