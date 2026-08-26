# Sail racing support app

A web app that supports the crew of a yacht during a race at Perth Flying Squadron
Yacht Club. Pre-start countdown, next mark name / distance / bearing, elapsed race
time, plus a heads-up display of instrument data and a course map.

Read `docs/DESIGN.md` before making architectural changes. It records the decisions
and, more importantly, why the alternatives were rejected.

## Hard constraints

These are properties of the deployment, not preferences. Do not design around
their absence.

- The server is a Raspberry Pi named `enchantee` that lives on the boat and has
  **no internet connection**. No CDNs, no tile servers, no external fonts, no
  package installs at runtime. Vendor every dependency. (At the dock it joins the
  house wifi and does have internet, which is when builds, pulls and pushes happen.
  That changes nothing about what the app may depend on at runtime.)
- Traffic is **plain HTTP only**. There is no TLS. This rules out the Screen Wake
  Lock API, the Geolocation API and service workers, all of which require a secure
  context. Use the hidden looping muted video trick for wake lock. There is no
  phone-GPS fallback; boat GPS over MQTT is the only position source.
- The Pi is reachable three ways and the app must work identically on all of them:
  `http://enchantee.local/` (mDNS), `http://10.42.0.1/` (AP mode) and
  `http://<current-ip>/`. Never hardcode a host.
- The app is served behind an nginx prefix (`/race/`) and must also work when hit
  directly on its own port. **Use relative URLs only.** Build fetch targets from
  `location.pathname`, the way the existing HUD page does. `/hud` is a 302 alias for
  `/race/hud`, for the crew.
- **The browser floor is iOS 12**, set by the iPad mini 3 on the boat. No `clamp()`
  (Safari 13.1), no flexbox `gap` (14.1) and no `dvh` (15.4) without a fallback ahead
  of it. `min()` and `env()` are fine, and so is grid gap. Screen height comes from
  `static/viewport.js` as `--app-h`, because `100vh` on iOS is not the visible height.
  Size the huge readouts by **both** axes: `vh` alone overflows a narrow screen. None of
  these failures is visible on a development machine, all of them reached the boat once,
  and all are now pinned by tests. See DESIGN 9.8.1.

## Operating environment

The user is in a boat cockpit, in sunlight, wet, moving, and busy. Design for
that: large hit targets, high contrast, no scrolling, minimum interaction, no
modal dialogs, nothing that needs two hands.

## Stack

- Python 3 / Flask service on port 5002, behind the existing nginx front door.
- `paho-mqtt` subscribing to the boat's broker.
- Front end is plain HTML/CSS/JS with no build step and no framework. It must be
  editable from a laptop on a jetty.
- Deployed as a Docker container, `sfewings32/emon_enchantee_racing`, with
  `restart: always` and the whole application directory bind-mounted from the working
  tree. Not the systemd unit this section used to specify. `static/` edits are live;
  `templates/` and `config/` need `docker restart enchantee_racing`.

## Layout

```
app.py                  Flask routes, static and template serving
mqtt_client.py          paho subscriptions, writes into the store
store.py                thread-safe {v, ts} cache, one lock
engine/nav.py           ENU projection, distance, bearing, line crossing
engine/course.py        load and validate marks/courses/lines
engine/race.py          mode and leg state machine, pure functions
templates/              index.html, hud.html, map.html
static/                 app.js, app.css, map.js, geo.js, flags/*.svg, audio/, icon*
scripts/                gen_*.py, which regenerate config/ and static/; outputs committed
config/                 marks.json, courses.json, lines.json, coast.json, race.json, depth.json
templates/              index.html, hud.html
static/                 app.js, app.css, flags/*.svg, audio/, icon*, depth.json
scripts/                gen_*.py, which regenerate everything in config/
static/                 app.js, app.css, map.js, geo.js, viewport.js, flags/*.svg,
                        audio/, icon*
scripts/                gen_*.py, which regenerate everything in config/; outputs committed
config/                 marks.json, courses.json, lines.json, race.json,
                        coast.json, depth.json, structures.json, navaids.json
                        (the last four are the map basemap, all gen_*.py output)
manifest.webmanifest    served from the app root, not static/ (DESIGN 9.8.1)
Dockerfile              COPY is an allow-list; a new root file must be added to it
tests/                  pytest, and every file also runs standalone
```

`engine/` must contain **no I/O**. It takes a position, a timestamp and a course,
and returns state. This is what makes replay testing possible, and replay testing
is the main reason the engine lives here rather than in Node-RED.

## Conventions

- MQTT payloads from existing devices are bare numbers, one value per topic.
  Speeds are knots, angles are degrees. Do not change this for existing topics.
- Position is the one exception: `gps/position/0` carries `{"lat":..,"lon":..,"ts":..}`
  as a single atomic payload so lat and lon always come from the same fix.
- Every reading is wrapped as `{v, age}` so the page can dim or blank a stale
  sensor. Wind and motor readings go stale at 15 s. **Position goes stale at 5 s**,
  and when it does, distance and bearing must blank to `---` rather than dim. A
  dimmed number still reads as a number at a glance.
- Angles relative to the boat are signed and normalised to +/-180, port negative,
  matching the existing TWA and AWA display.
- Distance shows metres below 500 m and nautical miles above.
- Config lives in readable JSON on disk, one copy, read by both the server and the
  browser.
- **Anything the crew sets is server state**, held in `store.py` and returned in
  `/api/state`, which all three pages poll anyway. Never a class a page toggles on
  itself and never `localStorage`: there are three separate documents and several
  devices, and a setting in one of them reaches none of the others. The night theme was
  the exception and it came back from the boat as three separate bug reports. See
  DESIGN 9.7 and 9.9.

## Gotchas that will bite

- **Club Buoy 32A is both the outer end of the start/finish line and a mid-course
  mark in almost every course.** Boats cross the finish line repeatedly while
  racing. Finish detection must be armed only after the final leg completes, and
  every earlier crossing ignored silently.
- Courses repeat marks. Track position in the course by leg index, never by mark
  identity. Auto-advance must only test the current target mark.
- Marks are keyed by string id (`bond-38a`), never by number. Number 37 is used by
  two different marks, and 38 vs 38A is inconsistent between the source documents.
- **There are no gates.** Bricklanding A+B, Smith+Lucky Bay and Mosman A+B are
  three pairs of ordinary marks that always appear consecutively, one leg each,
  each rounded on its own. No leg has two marks and nothing targets a midpoint. An
  earlier version of DESIGN.md called them gates completed by sailing between the
  marks, which is both against the sailing instructions for the first two pairs and
  contradicted by the printed course distances. See DESIGN.md section 6.
- Crossing between Bricklanding A and B, or between Smith and Lucky Bay, is
  forbidden while racing, so those two lines live in `lines.json` as
  `no_cross_lines`. Crossing one is a `breach` event to log, never a leg advance.
- Two long-lived threads share state: the paho network loop and Flask request
  handlers. Every mutation goes behind the single lock in `store.py`. Engine code
  never touches the store directly.

## Testing

Replay is the primary test strategy. Feed recorded GPS tracks through
`engine/race.py` and assert on the transitions. At minimum, cover: the four
crossings of the start line during Frostbite Course 1 are ignored; the finish
fires on the correct fix; drifting past 32A on the way to Squadron does not
advance the leg.

Recorded tracks come from the `event_recorder` service and from InfluxDB history.
