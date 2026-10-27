# emon live UI redesign: design

This is the authoritative design for the work on branch `emon_live_ui`. It records what
was decided, why, and what was rejected. It does not record progress; that is in
`HANDOVER.md`. The task list is in `PLAN.md`. Facts gathered from the existing system
(what Node-RED computes today, how the daily emails differ, known bugs) are in
`INVENTORY.md`.

`proposal.html` is the illustrated proposal this design came from (revision 3,
October 2026), including the page mockups and the three data-age states. Open it in a
browser. Where it and this file disagree, this file wins: the decisions below were
confirmed by the owner after the proposal was written.

Sections are numbered so that code comments and commit messages can cite them, for
example `DESIGN 4.2`.

---

## 1. Problem

The live view of each site is a Node-RED Dashboard 1 page. In order of how much they
matter:

1. Dashboard 1 is deprecated, lays out widgets on a fixed grid, and cannot reflow to a
   phone. It has no way to show that a value is old.
2. Sensor names are typed twice. `emon_config.yml` names every channel, and
   `emon_influx.py` uses those names as Influx tags. `emon_mqtt.py` drops them, so
   Node-RED identifies feeds by the last character of the topic and keeps its own
   `channelNames` arrays.
3. `emon_mqtt.py` (about 390 lines) and `emon_influx.py` (about 760 lines) each decode
   every payload type. Every sensor change is made twice.
4. Everything else that differs between sites lives in `provisioning/<site>/`, but
   Node-RED keeps one git branch per site in the separate `emon-node-red` repository,
   and those branches have drifted. See INVENTORY 3 for what that did to the daily emails.
5. Daily totals live in Node-RED flow context, so a restart corrupts the day.
6. Derived maths exists three times: Node-RED (daily totals), `enchantee_racing`
   (TWA, AWA fallback, leeway, heel) and `event_recorder` (Haversine distance, energy).

---

## 2. Decisions

Confirmed by the owner on 19 October 2026. Each records the rejected alternative,
because that is what a later session will be tempted to reopen.

### D1. Pages poll a small server. Browsers do not subscribe to MQTT.

`emon_live` subscribes to MQTT, holds the latest value of every feed, computes derived
values and serves one JSON state document that pages poll.

Rejected: browsers subscribing to mosquitto over websockets (proposal revision 2). The
race app's design brief (`python/enchantee_racing/docs/DESIGN.md` section 2) weighed the
same choice and chose polling. Its reasons hold here. Polling works unchanged across AP
mode, mDNS, raw IP and nginx prefixes. It needs no broker change and no vendored MQTT
client, and a wifi dropout heals itself on the next request. It also means derived values
are computed once on the server rather than in every open browser, and ages are computed
on the server, so a phone with a wrong clock still dims correctly.

### D2. Pages and config refer to feeds by name, not by topic.

A feed is referenced as `group / name`, exactly as written in emon_config, for example
`Power board / Consumed`. Rules are in section 5.

Rejected: structural topics such as `emon/power/0/2` in page files. They never break on a
rename, but when a sensor is moved to a different channel in a new timestamped settings
file they silently show the wrong sensor. A name breaks loudly instead, and a lint check
(section 9.4) catches it before deployment.

### D3. TWA and the other boat calculations are one function, run in two places.

The maths lives once, in `pyemonlib.emon_feed`. `emon_live` runs it and publishes the
results to MQTT for displays and the recorder. `enchantee_racing`, when it migrates,
imports the same functions and computes for itself rather than reading the published feed.

Why two places: the race app must keep working if `emon_live` is down. On the water that
matters more than saving one subtraction. Because both call the same function with the
same tests, they cannot disagree.

### D4. `emon_feed` lives inside pyemonlib, which outlives `emon_mqtt.py` and `emon_influx.py`.

pyemonlib is already installed in every image, so it is the natural home. But
`emon_mqtt.py` and `emon_influx.py` are expected to be **deleted** once migration is
complete, so nothing new may depend on them. The package is restructured as in
section 4.1. Two consequences:

- `emon_feed.py` imports only the standard library. It must not import `emonSuite`
  (the C++ extension), `paho`, `influxdb_client` or `yaml` at module level. That keeps it
  usable and testable on any machine, including one without a build of the extension,
  and keeps the race app's and recorder's dependency on it light.
- `emon_mqtt.py` and `emon_influx.py` become thin compatibility shims during migration,
  keeping their class names and constructor signatures so the existing runners
  (`emonSerialToMQTT.py`, `emonMQTTToInflux.py`, `emonLogToInflux.py`, `emonCSVToMQTT.py`,
  `emonGPSDToMQTT.py`) and `enchantee_racing/tests/replay/replay.py` keep working
  unchanged. They are removed in the final phase, after those callers have moved.

### D5. Single-site calculations stay in Node-RED for now.

Shower detection, the dog-fed notification, the rolling rain-tank average use and the
daily email stay in Node-RED. Node-RED publishes their results in the new envelope under
`emon/derived/...` so pages can show them like any other feed. Each moves to `emon_live`
only when a second site needs it.

Rejected for now: operators for these in `derived.yml`. They are bespoke state machines
used by one site, and generalising them first would be speculative.

### D6. Data-age thresholds: a site default, overridable per tile.

| Where | Fresh until | Gone after | Treatment when gone |
|---|---|---|---|
| House sites (default) | 60 s | 5 min | blank, dashed tile, last value in small type |
| Boat (enchantee) | 15 s | 2 min | as above |
| Boat position | n/a | 5 s | blank to `---`, never dim (race app DESIGN 9.5) |
| Slow feeds, per tile | e.g. odometer, scale, rain | set in the page file | |

Between fresh and gone the value fades linearly to 40% opacity and its age turns amber.

---

## 3. Architecture

```
radio nodes -> serial -> emonSerialToMQTT
                           |
                     emon_decoder (pyemonlib)  line + settings -> [Reading]
                           |
              +------------+-------------+
              |            |             |
          MQTT sink    Influx sink     log (unchanged)
          legacy topics + emon/... envelope (retained) + emon/config (retained)
              |
              +--> emon_live  (per site: store, derived.yml, /api/state, pages)
              |        publishes emon/derived/...
              +--> Node-RED   (email, backups, single-site state machines; no dashboard)
              +--> enchantee_racing, event_recorder  (later, own projects)
```

Two organising rules:

- **Code lives once in emon_Suite; everything that differs between sites lives in
  `provisioning/<site>/`.** That is already true for emon_config, compose, Grafana and
  mosquitto. This work extends it to pages and derived values, and eventually to the
  Node-RED flows.
- **Calculations live once, in a pure library with no I/O**, the same rule the race app
  applies to its `engine/`. That is what allows replay tests across all three projects.

---

## 4. Components

### 4.1 pyemonlib layout, target

```
pyemonlib/
  emonSuite            C++ extension (unchanged): payload parsers
  emon_settings.py     unchanged: timestamped settings files
  emon_decoder.py      NEW. decode(line, settings) -> list[Reading]. Uses emonSuite.
  emon_feed.py         NEW. Pure, stdlib only. Reading, envelope build/parse, catalogue,
                       Store, derived operators, nav maths.
  sink_mqtt.py         NEW. Publishes legacy topics, envelopes and emon/config.
  sink_influx.py       NEW. Generic Point from a Reading.
  emon_mqtt.py         SHIM during migration, then deleted.
  emon_influx.py       SHIM during migration, then deleted.
```

`Reading` fields: `node, sub, field, value, unit, kind, idx, group, name, t, rssi`
(see `emon_feed.Reading`).

**As built (phase 1, 19 Oct 2026).** The old MQTT and Influx functions turned out to
differ far more than expected: different topic and tag layouts (battery Influx tags put
the shunt before the subnode, MQTT the other way round), different scaling (rain is a tip
count on MQTT and mm in Influx; rain supplyV is mV on MQTT and V in Influx), different
channels skipped, and a different publish order for batteries and the IMU heading. They
also failed differently: a channel missing from emon_config raised `KeyError` part-way
through a message, inside a try that swallowed it, so everything before was published and
nothing after, at a different point for each sink.

So `decode()` returns a list of `Emission`s, each carrying:

- `reading`: the canonical Reading for the envelope, or None;
- `mqtt`: a thunk returning the legacy `(topic, value)`;
- `influx`: a thunk returning the legacy `(measurement, tags, value)`;
- `unused`: the channel is named Unused (section 4.2).

Each sink evaluates its thunks in order and stops at the first exception, which
reproduces each old function's partial-failure behaviour exactly. A thunk returning None
means "skip" (the old `!= "Unused"` gates). Where the two old orders differ, the quantity
is emitted once per sink. The canonical value is the Influx one where Influx had one
(named and scaled), else the MQTT one. Canonical names never raise.

`tests/test_decoder_regression.py` holds this to verbatim copies of the old modules in
`tests/legacy/`, for every emon_config in provisioning/ and every line of
`tests/data/emonlog_sample.txt`: legacy MQTT identical in order, Influx line protocol
byte-identical, same exceptions. At phase 1 that compared 20,674 MQTT publishes and 9,318
Influx points across 12 configs with no difference.

### 4.2 The envelope

Published on `emon/<node>/<sub>/<field>[/<idx>]`, retained, QoS 0. For example
`emon/pulse/0/power/2`, `emon/bms/1/cellVoltage/3`, `emon/gps/0/position`.

The field is in the path because one node publishes several quantities of the same kind
(a BMS has a pack voltage and sixteen cell voltages), so the `emon/<kind>/...` layout
first proposed would have collided. Changed while building phase 1.

```json
{
  "s": 1,
  "v": 2867,
  "u": "W",
  "t": 1757580061.0,
  "kind": "power",
  "node": "pulse", "sub": 0, "field": "power", "idx": 2,
  "group": "Power board",
  "name": "Consumed",
  "rssi": -61
}
```

Absent optional fields are omitted, not null. Units are `W`, `Wh`, `V`, `A`, `VA`,
`degC`, `mm`, `L`, `g`, `kn`, `deg`, `hPa`, `%`, `dBm`, `pulse`, `count` and a few more;
`emon_decoder` is the list.

**Unused.** A channel named `Unused`, or a whole node named `Unused`, gets no envelope.
On the owner's instruction (19 Oct 2026) its legacy MQTT topic is also no longer
published; `EMON_SKIP_UNUSED=0` in a container's environment restores it. Influx is
unchanged. This is the only intended change to legacy output. `EMON_ENVELOPES=0` turns
the whole `emon/...` namespace off.

- `s` is the envelope version. Fields may be added within a version, never renamed or
  removed.
- `t` is unix seconds from the bridge host's clock when the line arrived. `PayloadGPS`
  and most payloads carry no time of their own, so nothing better is available.
- `rssi` only when present.
- GPS position keeps its single atomic `{"lat","lon"}` value (race app DESIGN 3): in the
  envelope, `v` is that object.
- `emon/config` (retained): the active settings file as JSON plus its filename, published
  on load, on every reload and on every (re)connect to the broker. The production brokers
  have no persistence, so a broker restart drops every retained message; envelopes come
  back with the next reading, but `emon/config` would otherwise not return until the
  bridge restarted.
- `emon/derived/<id>` (retained): same envelope, `node: "derived"`, published by
  `emon_live` or, per D5, by Node-RED.
- Event payloads such as `race/event` keep their fields and gain `t` and `kind: "event"`
  when their owners migrate.

Two existing topic bugs are fixed in the new namespace and left alone in the legacy one:
`bms/voltage{n}` and `bms/lifetimeCycles{n}`, and `sevCon/voltage{n}`, `sevCon/current{n}`,
`sevCon/rpm{n}`, which all lack the slash before the subnode.

### 4.3 Clocks and age

- Consumers on the same host as the bridge may use `t`, and must for retained messages,
  whose arrival time is only the moment of subscribing.
- The race app counts staleness from arrival, deliberately (its DESIGN 3 and 9.5), and
  keeps doing so.
- Browsers never see `t`. `emon_live` sends `age` in seconds; the page adds the time since
  its last poll, so ages keep counting through a wifi dropout and never depend on the
  device clock.

### 4.4 emon_live

A Flask service, one container per site, `python/emon_live/`. Modelled on the race app
(`store.py`, `app.py`, `mqtt_client.py`), and its store is the race app's `{v, ts}` store
generalised into `emon_feed.Store`.

- Subscribes to `emon/#`.
- Loads `provisioning/<site>/emon-ui/` (mounted read-only): `site.json`, `pages/*.json`,
  `derived.yml`.
- Runs derived operators on each relevant arrival and publishes `emon/derived/...`.
- On start, seeds `daily_delta` baselines from Influx (first value since the reset time)
  so a restart mid-day resumes correct totals.
- Serves `/` (the engine), `/site/...` (the site folder), `/api/state`.
- `/api/state` returns every feed a page uses: `{name: {v, u, age}}` plus `theme`.
  Gzipped. Small enough to poll every second.
- Theme (day/night) is server state, set with a POST, so every screen on a site switches
  together (race app DESIGN 9.7, learned the hard way).
- Bind-mounts its code from the checkout so edits are live, matching
  "the checkout is the deployment" in `../../CLAUDE.md`.

**As built (phase 2a, 21 Oct 2026).** `python/emon_live/`: `state.py` (no Flask, no paho:
`LiveState`, `handle_message`, `state_document`, `Site`), `mqtt_client.py`, `app.py`.

- `emon_feed` is imported from `python/pyEmon/` in the source tree, not from the wheel.
  It is standard library only, so emon_live needs no numpy and no C++ extension, and an
  edit to it is live without a wheel rebuild. The container must therefore mount
  `python/` whole (or at least `emon_live/` and `pyEmon/` side by side).
- `/api/state` is `{"theme": .., "feeds": {name: {v, u, age}}}`: feeds under their own
  key, so no feed name can collide with `theme`. It carries the feeds named anywhere in
  the site's pages (a `"feed"` value or a `{name}` placeholder in a string), or every
  feed with `?all=1` or when the site has no pages. A whole-site document is about 2.4 KB
  gzipped (217 feeds at shannstainable).
- `age` is rounded to 0.1 s and never negative. A feed that has never arrived is absent,
  not null.
- Also `/api/feeds` (every name known, and any name two topics share) and `/api/config`
  (the last `emon/config`), for page writing and lint.
- The site folder is re-read when a file in it changes; a file that does not parse is
  logged and its last good version kept.
- Default port 5003 (free at shannstainable; 5002 is the race app on the boat).

### 4.5 emon-ui engine

`emon_Suite/ui/`: `index.html`, `emon-ui.js`, `emon-ui.css`, `tiles/*.js`, shared
`theme.js` and `viewport.js`. No build step, no framework, no CDN.

Tile types: `value`, `gauge` (bar), `trail` (sparkline), `led`/pill, then for the boat
`dial`, `compass`, `cell-bar`, `grafana` (iframe), and `html` (a site fragment using the
engine's data client, the escape hatch).

Browser floor, from the race app's CLAUDE.md, because the boat's iPad mini 3 runs iOS 12:
no `clamp()`, no flexbox `gap`, no `dvh` without a fallback, no container queries, every
SVG given `width` and `height`, relative URLs only, screen height from `viewport.js`.
Grid `gap` and media queries are fine.

**As built (phase 2c).** `ui/index.html`, `emon-ui.js` (engine), `emon-ui.css`,
`theme.js`, `viewport.js`, `tiles/{values,gauge,trail,leds,lines}.js`. `viewport.js`
sets `min-height`, not the race app's `height`, because a house page scrolls. Night is
the proposal's dark palette; the boat may want its own (phase 3). Desktop 4 columns,
3 under 1100 px, 2 under 760 px, 1 under 360 px. `python/emon_live/tests/test_ui.py`
pins the iOS 12 rules statically.

Visual design (proposal "The page" section): one hue per domain on a top stripe and the
tile heading, never a filled background; values in a monospace face with tabular figures;
"today" figures smaller beneath the live value. Domain hues: power orange, solar yellow,
batteries green, heat red, water blue, rain slate, cars violet. Desktop 4 columns, phone
2 columns, hero tiles span 2.

### 4.6 Node-RED, residual role

Daily email, log backups, the single-site state machines of D5, and Grafana embeds where
still wanted. No Dashboard 1 pages once each site's emon-ui reaches parity. In the final
phase, each site's flows move to `provisioning/<site>/node-red/flows.json`, `flowFile` is
read from an environment variable in a shared `settings.js`, the dashboard packages are
dropped, and the per-site branches of `emon-node-red` are archived.

---

## 5. Naming feeds

- **Channels named in emon_config**: `group / name`, where group is
  `settings[node][sub]["name"]` and name is the channel key's value (`p2`, `t1`, `f0`,
  `h0`, `s0`, `v3` and so on). Example `Power board / Consumed`.
- **Fields with no name in config** (bms, gps, imu, pth, mwv, leaf, inv, svc, air, bee):
  `group / field`, for example `Main Battery / batterySoC`, `True wind / windDirection`.
  Indexed unnamed fields add the index: `Main Battery / cellVoltage 3`, `IMU Sensor / acc 1`.
- **A named channel with no name in config**: `group / field idx`, e.g.
  `House temperatures / temperature 3`.
- **One channel, two kinds** (pulse publishes `power` and `pulse` for each channel;
  battery shunts publish `power`, `pulseIn`, `pulseOut`): the second kind is appended in
  brackets, `Power board / Consumed (pulse)`, `Bank 2 (pulseIn)`. The natural reading
  (power) takes the bare name.
- **RSSI**: `group / rssi (<node>)`, or `rssi (<node> via <relay>)` when heard through a
  relay. The node type is in the name because one place often has several node types
  under one group name: shannstainable's config has a `Kitchen` display and a `Kitchen`
  air sensor. Found by the phase 1 envelope test.
- **Derived feeds**: `derived/<id>`, for example `derived/power/consumed/today`.
- **Feeds outside emon** (ecowitt, pantech): the raw topic is accepted.
- The names travel in every envelope, and envelopes are retained, so a consumer builds
  its `emon_feed.Catalogue` from the readings it receives on subscribing; it does not
  need to interpret `emon/config`. `emon/config` is still published, for tools and lint.
  The phase 1 test asserts no two channels share a name across all 452 sample lines, for
  every site config. Duplicate names are a lint error.

---

## 6. Provisioning a site

```
provisioning/<site>/
  emon_config/            unchanged; the source of every name
  emon-ui/
    site.json
    pages/<page>.json
    derived.yml
  node-red/flows.json     final phase only
  docker-compose.yml      + emon_live service
```

### 6.1 site.json

```json
{
  "title": "Enchantee",
  "theme": "night",
  "state": "api/state",
  "fresh": 15, "gone": 120,
  "pages": [
    {"title": "HUD",  "link": "../race/hud", "for": "phone"},
    {"title": "Race", "link": "../race/"},
    {"id": "dials", "title": "Dials", "for": "kiosk"},
    {"id": "navigation", "title": "Navigation"}
  ],
  "default": "dials"
}
```

Pages are addressed as `/#<id>`. A `link` entry puts another app in the menu without
owning it. A site with one page shows no menu.

### 6.2 Page files

A page is a list of tiles. A tile names its feeds:

```json
{
  "title": "Hot water", "domain": "heat", "span": 1,
  "fresh": 60, "gone": 300,
  "hero":  [ {"feed": "Hot water system / Water (T3)", "label": "Tank", "decimals": 0},
             {"feed": "derived/hws/showersRemaining", "label": "Showers left"} ],
  "gauge": {"feed": "derived/hws/showersRemaining", "max": 27},
  "line":  "Today {derived/hws/showers} showers · {derived/hws/showerMinutes} min"
}
```

**As built (phase 2c, 21 Oct 2026).** A tile is a frame and up to five parts, drawn in
this order; the four tile types planned in 4.5 became parts so that one tile can carry
several, as the mockup's tiles do:

| Key | Part | Shape |
|---|---|---|
| `values` | a grid of readings | `[{feed, label, big, decimals, unit, domain, sub}]`, with `cols` (1 to 4) on the tile |
| `gauge` | a bar | `{feed, min, max}` |
| `trail` | a sparkline | `{feed, minutes}`; kept by the page since it opened (no history endpoint yet) |
| `leds` | pills in the heading | `[{feed, on, off, test, bad}]`; `test` `"value"` (on at 1 or more) or `"fresh"` (on while reporting) |
| `lines` | small text | `["template", ...]` |

**As built (phase 3, 25 Oct 2026).** The boat's four tile types are parts too, drawn
between `values` and `leds` in the order `dial`, `compass`, `cell-bar`, `gauge`, `trail`,
`grafana`:

| Key | Part | Shape |
|---|---|---|
| `dial` | a round gauge, or a list of them side by side | `{feed, min, max, warn, bad, decimals, unit, label}`; fills from 0; `warn` above `bad` means the bottom is bad (a battery voltage) |
| `compass` | needles on a rose | `{needles: [{feed, label}], relative}`; the first needle is the one read; `relative` is bow-up, signed, port negative, with the race app's 30 to 60 degree sectors |
| `cell-bar` | a bar per battery cell | `{min, max, spread, decimals, cells: [{feed, label}]}`; lowest, highest and the spread, in the warning colour past `spread` |
| `grafana` | a Grafana panel | `{src, height}`; `src` relative; follows day and night unless it names a theme |

Cells are listed one by one, not generated from a count, so that every feed is a
`"feed"` in the page where the server and the linter look (4.4, 9.4). A tile that names
no feeds, such as a frame alone, shows no age. The `deg` unit is shown as °.

A page may take `cols` (1 to 4): its columns from 761 px up, in place of 4, 3 and 2 by
width. The boat's pages use 2, so the iPad mini 3 (1024 by about 690 in Safari, 768
wide upright) and the kiosk (the Pi's own 1280 by 800 DSI screen, less a taskbar) lay
them out alike: tiles span 1, side by side, and a span-2 tile is a full-width strip.
Every enchantee page fits 1024 by 690 without scrolling (headless Chromium, 27 Oct 2026).

`site.json` also takes `"menu": "large"`: the page tabs at twice the size (30 px), each a
finger-sized target, for the boat's kiosk. The owner's pages there, 27 Oct 2026: Weather,
Navigation, Battery, Motor, All feeds, in that order, Weather the default; no HUD or Race links and
no Dials page (the `dial` part stays in the engine).

**The race app's face** (27 Oct 2026, owner): `site.json` `"font": "race"` sets every
word and number in enchantee_racing's stack, `"Helvetica Neue", Helvetica, Arial,
sans-serif`, readings at weight 500 with tabular figures and -0.02em tracking, as its
`static/app.css` does; nothing is downloaded (the Pi resolves it to Nimbus Sans, iOS has
Helvetica Neue). enchantee uses it; shannstainable keeps the proposal's faces.

**Large text** (27 Oct 2026, owner): `?text=large` in a page's URL doubles every reading
and label on that screen (values 44 px, big ones 60, labels 20; compass, cell bars and
sparklines grown to match; four-across value grids in a half-width tile go to two).
Per screen by URL, because it answers to the screen's size and distance, not to the
site: the kiosk is small and read from across the cabin, the iPad is held. `site.json`
`"text": "large"` would set it for every screen. A compass takes `"legend": false` to
leave off the readings beneath it; Weather does, to fit at double size, since the first
needle's reading is in the middle of the rose and the tints tell the needles apart.
Every page fits the kiosk's viewport (1280 by about 740) at double size, checked in
headless Chromium with a window 88 px taller than the viewport it is meant to show.

**Reading colours** (27 Oct 2026, owner): a value, a dial's number and a compass needle
take `tint`, and a cell bar `tint_low` and `tint_high`, naming a reading: `sog tws aws
hdg cog leeway twa awa rpm power cur cellmin ctrl cellmax mot temp volt soc hum heel
press`.
Each is the colour that quantity has on the boat's Node-RED pages and in enchantee_racing
(its `static/app.css`, `templates/hud.html`), so the same reading is the same colour on
every boat screen. Pressure is green, as the GPS Banner shows it (`emon_GPS_Banner.ino`,
`displayTypeColor`); `emon-ui.css` has the table. Those values suit a black background and
are the night theme's exactly; the day theme has darker shades of the same hues, since
yellow, pale green and cyan cannot be read on white. The race app's red-only night theme
is not reproduced. A tint wins over a value's `domain`.

Tile keys: `title`, `domain` (`power solar batt heat water rain car other`), `span`
(1 or 2), `fresh` and `gone` (seconds; tile, then page, then site, then 60 and 300),
`headline` (a template shown in the heading, which moves the age to the foot).
Templates anywhere take `{feed}`, `{feed|N}` for N decimal places, or `{feed|time}` for
seconds since the epoch shown as "Today 18:54" (`"format": "time"` on a value); `unit: ""` hides a
unit. A tile's age is its newest feed's; a value whose own feed is past `gone` shows a
dash. `site.json` takes `title`, `theme`, `poll` (s), `fresh`, `gone`, `pages`,
`default`; a page id `_all` is built in: every feed known, one tile per group, which is
what a page is written from.

### 6.3 derived.yml operators

| op | Meaning |
|---|---|
| `daily_delta` | counter value minus its value at the reset time (default local midnight, `reset: "09:00"` for rain). Seeded from Influx on start. |
| `integrate` | W to Wh, trapezoidal, gaps over 5 min not bridged. |
| `sum` | sum of named feeds. |
| `expr` | arithmetic over named feeds, with `norm180` available. |
| `twa`, `awa`, `leeway`, `heel` | the race app's functions, moved into emon_feed (D3). |

Example lines for both shannstainable and enchantee are in `proposal.html`, section
"Derived values in provisioning".

**As built (phase 2b, 21 Oct 2026).** Operators in `emon_feed` (pure, stdlib), wired by
`python/emon_live/derived.py`, seeded by `influx.py`. The file's own header is the
reference; the decisions behind it:

- **No `wPerPulse` scaling.** The plan above was wrong: pulse counters are already Wh,
  because the nodes apply `pN_wPerPulse` themselves. Checked on 21 Oct 2026: over 30 min
  `Consumed` rose 1,176 pulses while its power integrated to 1,159 Wh (`p2_wPerPulse` is
  2.5). Node-RED's 1 pulse = 1 Wh was right. `scale` defaults to 1.
- **More operators than planned**, each one a Node-RED calculation: `daily_max` and
  `daily_min` (battery rail and mid-points, by magnitude with `abs`, `ignore_zero`),
  `mean` (the export estimate's average import, `positive_only`), `window_delta`
  (battery out from 00:00 to 09:00, held until the next 09:00). `daily_delta` also takes
  `reset: month | year`, which is how month and year rain come from Influx.
- **Expressions name feeds in braces**, as pages do: `"{derived/import/today} / 1000 *
  0.262"`. Parsed with `ast` and checked node by node: numbers, arithmetic, comparisons
  (true is 1), `x if c else y`, and `min max abs round norm180 norm360`. A missing input
  gives no value unless `defaults` names one.
- **Seeding is a replay, not a baseline.** Each input is read back from Influx from the
  earliest boundary of the operators it feeds and run through them in time order, which
  rebuilds chains (the export estimate) that no aggregate can. Month and year deltas
  take a bounded `first()` instead. Every query names one series and a time window
  (HANDOVER: an unbounded query froze the Pi). shannstainable: about 340,000 rows,
  30 s, 77 MB at 20:30.
- **Influx series are named in derived.yml** (`influx:`: feed to `measurement sensor`),
  not derived from feed names: Influx's `sensorGroup`/`sensorName` tags do not always
  match the envelope names (rain is `rain gauge / Rain gauge` there, `Rain gauge / rain`
  here).
- A value no newer than the last seen for a feed is ignored, so retained messages
  arriving after the replay do not look like counter resets; and emon_live's own
  `emon/derived/...` echo from the broker is not fed back in.
- A `daily_delta` total never goes backwards. A reading below the last is set aside:
  relayed copies of a packet arrive late with an older count, and a corrupted serial
  line can carry another node's numbers (both seen 23 Oct 2026). A node restart is
  recognised by three readings in a row below the last, rising, from under half the old
  value, and is then carried, not subtracted; three readings carrying on from before the
  last undo a spike upwards.
- **Battery monitor counters count by sign, not by direction.** `pulseIn` accumulates
  positive current and `pulseOut` negative. Whether positive means into or out of the
  battery depends on how the shunt is mounted: on shannstainable's monitor 5 (the
  batteries) positive is out, so `pulseIn` is discharge; on monitor 4 (the inverter
  shunts) positive is in. Checked against integrated power, 21 Oct 2026. derived.yml
  names derived feeds from the battery's side (`battery/in` is charge) and says per
  monitor which counter that is.
- Boundaries are checked every 5 s, so totals go to 0 at midnight without a reading.
- **The boat angles (phase 3, 27 Oct 2026)** are ops `twa`, `awa`, `leeway` and `heel`,
  each naming its inputs by role (`twd`, `hdg`; `measured` or `awd` and `hdg`; `cog`,
  `hdg`, `sog`; `y`, `z`) and calling emon_feed's functions, which phase 1 ported from the
  race app. As the race app does, a result is stamped with the time of the oldest input
  it used, so it ages when any input stops (AWA from the masthead reads only that). When
  one stops being knowable while its inputs still arrive (leeway under `min_sog`, heel
  without enough gravity), it is published once with `v` null, so pages blank it rather
  than show the last value as current. Battery and motor energy are `expr` and
  `integrate`; no new operator was needed.
- `external:` lists derived feeds that another publisher computes, Node-RED under D5,
  so the page linter knows them; derived.py ignores it. Node-RED republishes them every
  minute with `t` = now, which is what keeps a count that has not changed for hours fresh
  on the pages.


### 6.4 Serving

- **enchantee**: host nginx maps `/` to emon_live in place of Node-RED's `/ui/`, which
  moves to `/nodered/ui/` during the overlap. `/race/`, `/events/`, `/grafana/` unchanged.
  The kiosk launcher (`usr/local/bin/enchantee-dashboard`) keeps `http://enchantee.local/`
  and gains `#dials`.
- **shannstainable, harvey-farm, office-temperature**: emon_live publishes a port, or
  sits behind the existing reverse proxy for https.

**As built (phase 3, prepared 27 Oct 2026).** nginx's `location /` proxies to
`127.0.0.1:5003/`. Node-RED's dashboard needed no new block: the existing `/nodered/`
location already serves it at `/nodered/ui/`. emon_live runs on the compose network and
publishes 5003, like shannstainable's, and its image is built on the Pi, not pulled. The
kiosk opens `http://enchantee.local/?text=large#weather` (`#dials`, then `#motor`, as
the owner reordered the pages on 27 Oct) and waits on the URL without the fragment.

---

## 7. The wider family

`enchantee_racing` and `event_recorder` are **not** changed by this work. They have their
own design documents, CLAUDE.md files and tests, and migrate when each is next worked on.
This work owes them a stable contract:

- Legacy topics keep publishing until the last consumer has moved.
- The envelope is versioned (section 4.2).
- `emon_feed.parse(topic, payload)` returns a Reading from an envelope **or** a bare
  number, so either app can switch parsing first and subscriptions later.
- `emon_feed` has no I/O, so all three projects can replay-test against the recorded
  Frostbite tracks.

What each gains is listed in `proposal.html`, section "The wider family", including the
overlap table of which project computes what today.

---

## 8. Deferred, with reasons

- **Generic daily email** (`provisioning/<site>/email.yml` rendered by emon_live). Would
  remove the per-branch drift in INVENTORY 3. Deferred until emon_live exists and
  computes the daily totals the email reports.
- **Shower detection, dog-fed, tank average as operators** (D5).
- **Server-sent events instead of polling.** A small upgrade if push is ever wanted.
- **Stopping the legacy topics.** Only after Node-RED, both apps and every Grafana
  dashboard have moved.

---

## 9. Engineering rules for this branch

### 9.1 Development never touches a production checkout

On a Pi, `/share/emon_Suite` **is** production: containers bind-mount provisioning and
code from it. Never switch its branch. Develop in a separate worktree:

```bash
cd /share/emon_Suite
git fetch origin
git worktree add /share/emon_Suite-live emon_live_ui
```

Read `../../CLAUDE.md` on container mounts before any `docker exec`. Container scratch
work goes in `/tmp` inside the container, never under `/share`.

### 9.2 Development never disturbs the production broker

A second publisher of legacy topics on the production broker would double every
message that Node-RED counts. Test the new publisher against a separate mosquitto
(for example a dev container on port 1884) fed by replaying logs, never alongside the
live `emon_serial` on 1883. Reading from the production broker is fine.

### 9.3 Rebuild the wheel before the images

Images install the prebuilt wheel from `python/pyEmon/dist/` via `platform.sh`. A source
change in pyemonlib reaches no container until the wheel is rebuilt for the target
platform. The race app lost time to exactly this (`python/enchantee_racing/docs/HANDOVER.md`).

### 9.4 Lint

`ui/tools/lint_pages.py` checks every feed named in a site's pages and derived.yml
against that site's emon_config. Run it in `build.sh` and before deploying a settings
file.

**As built (phase 2c).** It checks against the names the bridge publishes, read from the
broker's retained `emon/#` (`--broker`, read only) or a capture of them (`--capture`),
not by working names out from emon_config: that would need the decoder and so a build of
the C++ extension, and the published names are the ones pages must match. It also
checks derived.yml loads, that every replayable input has an Influx series, duplicate
names and unbalanced braces. Not yet wired into `build.sh`.

### 9.5 Tests

- `emon_feed` has unit tests that run anywhere with only the standard library and pytest.
- The decoder regression test compares old and new output, per site config, over
  `tests/data/emonlog_sample.txt`. It needs a build of the C++ extension and is skipped
  without one. Any installed pyemonlib wheel matching the Python version will do:
  `tests/conftest.py` puts the source first on the path and borrows the compiled
  `emonSuite` from the installed package. On the Windows laptop the cp314 win_amd64 wheel
  in `pyEmon/dist` works; on a Pi, the arm wheel.
- The sample is synthetic for house nodes until a real shannstainable log is available,
  and real for boat nodes (Frostbite recordings). `tests/data/make_emonlog_sample.py
  --house <log>` adds a real log's lines.
- Ported race app functions bring their tests with them.

### 9.6 Commits

Conventional style, `scope: summary`, with a body saying why. Scopes in use:
`pyemonlib`, `emon_live`, `ui`, `provisioning`, `docs`. Stage only the files of the
change; the working tree has unrelated untracked files.
