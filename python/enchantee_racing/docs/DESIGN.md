# Design brief

Distilled from a design conversation. Records what was decided, what was rejected,
and the raw data the app depends on.

## 1. Purpose

Support the crew of a yacht racing at Perth Flying Squadron Yacht Club (PFSYC),
Dalkeith, on the Swan River.

Before the start:

- Select the race course from the available list.
- Set the countdown from one of the starting hooters, at 10, 5 or 1 minutes before
  the start, and show the time remaining.

While racing:

- Name of the next course mark.
- Distance to it.
- Bearing to it.
- Total elapsed race time.

The race finishes when the boat crosses the club start/finish line after rounding
the last mark of the course.

Also wanted: the existing instrument HUD, and a course map page.

## 2. Architecture decision

**Chosen: a dedicated Flask service on the Pi that owns the race engine, serves the
pages, and is polled by the browsers over HTTP.**

The split is compute on the server, render on the client.

### Why server-side, not browser-side

1. Multiple devices are expected (helm phone, navigator tablet). With leg advance
   detected independently in each browser, two devices can disagree about which
   leg the boat is on, and reconciling that needs compare-and-swap semantics that
   are unpleasant to debug on the water. One engine and dumb displays makes
   divergence impossible by construction.
2. Detection runs on every GPS fix, not only when a browser happens to poll.
   Nobody watching a phone during a busy rounding must not mean the rounding was
   missed.
3. It matches the pattern already built for the HUD.

### Why a dedicated service, not Node-RED

Node-RED was considered because the existing HUD already lives there and it needs
no new infrastructure. Rejected because race logic in function nodes cannot be
unit tested, cannot be replayed against recorded tracks, and has to be edited in a
browser textarea. Replay testing of line-crossing logic is worth more than the
deployment convenience, because line-crossing code is exactly the kind that looks
obviously correct and is not.

`event_recorder` (Flask, port 5000) was considered as a host. Rejected to keep
concerns separate, but it remains the sink for race event logging.

### Why HTTP polling, not MQTT over websockets

The existing HUD polls a JSON endpoint every 500 ms and works correctly across AP
mode, mDNS, raw IP and proxy prefixes. Polling needs no mosquitto websockets
listener, no broker reconfiguration and no vendored MQTT client. Each request is
independent, so a wifi dropout self-heals with no reconnect logic. Server-sent
events are a small upgrade later if push is ever wanted.

### What Node-RED keeps

Instrument ingest, the other dashboard tabs, and the Grafana embeds. It stops
owning the HUD once the port is verified.

## 3. MQTT topics

Confirmed from the existing `flows.json`. Payloads are bare numbers. Speeds in
knots, angles in degrees.

| Topic                               | Meaning                                         |
| ----------------------------------- | ----------------------------------------------- |
| `gps/speed/0`                     | SOG                                             |
| `gps/course/0`                    | COG                                             |
| `imu/0/heading`                   | HDG                                             |
| `anemometer/windSpeed/2`          | TWS                                             |
| `anemometer/windDirection/2`      | TWD                                             |
| `anemometer/windSpeed/1`          | AWS                                             |
| `anemometer/windDirection/0`      | AWA, already bow relative                       |
| `anemometer/windDirection/1`      | AWD, apparent wind as compass bearing, fallback |
| `sevCon/rpm0`                     | motor RPM                                       |
| `sevCon/current0`                 | motor current                                   |
| `sevCon/temperature/controller/0` | controller temperature                          |
| `sevCon/temperature/motor/0`      | motor temperature                               |

### The position topic, which was the blocking gap and is now published

A search of all 438 nodes across every tab of `flows.json` found no latitude or
longitude anywhere: GPS published speed and course only, and every race feature
depends on position, which made it action item zero.

**Resolved.** `pyemonlib.emon_mqtt.gpsMessage` now publishes it, alongside the
separate `gps/latitude` and `gps/longitude` topics it already had. Verified
arriving at about 1 Hz off a replay of the 16 August 2026 Frostbite recording,
and read by `mqtt_client.py` into the store. The payload is exactly as specified
below.

```
gps/position/0    {"lat":-32.001948,"lon":115.812006,"ts":1755500000}
```

One topic carrying both values, not two. Two separate topics can be sampled
either side of a fix boundary, giving a position that is half of one fix and half
of the next. Near a mark that is a few metres and tolerable; on a line-crossing
test it can put the boat on the wrong side.

Answered: it was a bridge change, not a firmware one. `gps/speed/0` comes from
`pyemonlib.emon_mqtt`, which parses the boat's serial stream through the same
`EmonSerial` C++ code the firmware uses, so the combined topic is assembled there
from the latitude and longitude that were already in `PayloadGPS`.

Two consequences for anything consuming it:

- `ts` in the payload is the **receiving host's clock, not the time of the fix**.
  `PayloadGPS` carries no time field, so nothing better is available at that layer.
  Staleness must therefore count from arrival, like every other reading; using
  `ts` would measure clock skew between publisher and app rather than fix age.
- The topic is **skipped entirely when there is no fix**, rather than carrying a
  sentinel. TinyGPS returns 1000.0 for an unknown angle and the transmitter sends
  whether or not it has a position, so the publisher range-checks and stays quiet.
  A lost fix therefore ages out past the 5 s cutoff on its own, which is exactly
  the wanted behaviour and means no consumer needs a sentinel check.

### Derived values

TWA is not measured. It is `norm180(twd - hdg)`. AWA comes from
`anemometer/windDirection/0` if present, else `norm180(awd - hdg)`. Port the
existing implementations rather than rewriting them.

Leg type comes free from `norm180(twd - bearingToMark)`: under about 40 degrees is
a beat, over 140 is a run, otherwise a reach. Showing the next leg type before
rounding is useful for sail selection.

## 4. API

```
GET  /api/state     HUD fields + race state in one payload
POST /api/select    {course: "sun4-3"}
POST /api/timer     {hooter: 10 | 5 | 1 | null}
POST /api/advance   {dir: +1 | -1}
POST /api/reset
PUT  /api/config/{marks|courses|lines}
```

One GET per 500 ms carries both HUD and race state, so a single page can show
both and all devices converge within half a second.

## 5. nginx

The Pi already runs a catch-all server block proxying `/` to the Node-RED
dashboard, plus `/nodered/`, `/grafana/`, `/portainer/`, `/events/` and
`/settings/`. Add:

```nginx
    # race support app
    location /race/ {
        proxy_pass http://127.0.0.1:5002/;
        proxy_http_version 1.1;
        proxy_set_header Host              $http_host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    location = /race { return 301 /race/; }
```

The trailing-slash redirect matters for the same reason it does for `/events/`:
relative asset paths only resolve correctly from a directory-style URL.

## 6. Mark and line data

### Authoritative source

**Positions: `docs/qgis/Swan River Marks/Swan_marks_YWA_SRRC_Sep2019.shp`**, the
September 2019 register redigitized by hand in QGIS. GDA94 geographic coordinates,
one point per mark, 142 of them. This is the truth for where a mark is.

**Everything else: `YWA SRRC VERSION Sept19`**, the Yachting WA / Department of
Transport navaid register, whose columns the QGIS layer carries as attributes:
`YWA_NAME` (number, name and rounding packed into one irregular string),
`NAV_NAME`, `NAV_TYPE`, `OWNER`, `MARK_CLS`, and the register's original `LAT` and
`LON`.

`config/marks.json` is generated by `scripts/gen_marks.py` from the layer, and
`config/lines.json` from `marks.json`. All twenty marks used by the 2026-27 PFSYC
course sheets resolve cleanly by their exact `YWA_NAME`, including Mosman A (14),
which was absent from every other source consulted.

#### Why the register's own coordinates are no longer read

They are not all accurate. The layer keeps the register's `LAT` and `LON` alongside
the digitized geometry, so the two can be compared directly: **61 of 142 marks
moved, by a median of 15 m and up to 135 m.** Among the twenty course marks,
Dolphin East (42B) moved 134 m, Squadron (37) 64 m, Club Buoy (32A) 62 m, Mosman B
(13) 38 m and Sanders (99) 35 m.

The recorded GPS track settles which set is right, independently of any document.
Walking the 16 August 2026 Frostbite recording through course 3 and measuring the
closest approach to each of the ten roundings:

| | register positions | digitized positions |
| --- | --- | --- |
| median closest approach | 21 m | **5 m** |
| worst | 65 m (Dolphin East) | 23 m (the finish line midpoint) |

A boat rounds a buoy within a few metres. The 65 m was the register's error, not the
boat's distance. Every mark got closer, none got further, and the two marks that
moved furthest improved the most.

This has one counter-intuitive consequence, recorded so nobody reads it as a
regression. The printed course distances now reconcile *less* closely: courses 2, 3
and 4 went from 0.0, 0.0 and -0.1 per cent to +0.5, +0.5 and +1.1. That is expected.
The club computed those printed figures from the register, so agreement with them
measured "using the same coordinates the club used", not accuracy. The check in
section 7 remains a transcription check and is no longer a precision check.

The `.xls` stays in `docs/reference/` as provenance and is not read by anything.

#### Datum

The layer is GDA94, which differs from present-epoch WGS84 by roughly 1.8 m in this
part of Australia, since GDA94 was pinned in 1994 and the continent has moved
north-east about 7 cm a year since. GPS gives WGS84. The offset is well below GPS
scatter, applies to every mark alike so relative geometry is unaffected, and is
therefore recorded rather than corrected. It matters only if these positions are
ever compared against a survey to better than a couple of metres.

### Sources superseded, do not re-import

- **PFSYC "GPS Coordinates" table.** It is a rounded copy of this same register,
  agreeing to under one metre on fifteen of sixteen shared marks, but its Club
  Buoy (32A) longitude is wrong by 168 m: it reads `115.81459`, which is exactly
  the longitude of Armstrong (32) in the row above it. A copy-paste error. It also
  omits Sanders (99), Robins (59), Dee Rd (38) and Mosman A (14).
- **"Swan River Marks Co-ordinates Ver 3"** PDF, based on SRRC DoT River Marks
  from September 2015. Stale: it disagrees with the 2019 register by up to 173 m
  on marks in daily use, and its two internal tables (DMS and decimal minutes)
  disagree with each other by up to 46 m. Its rounding column is correct and
  matched the course sheets on all fifteen shared marks, but the 2019 register
  covers that too.

### Still needed alongside the register

- **Fixtures & Courses 2026-2027 PDF.** The courses themselves, the sailing
  instructions, and the flag definitions. Irreplaceable.
- **Course Marks Map, July 2026 (Geng), PDF.** Human-readable visual reference and
  a name cross-check, seven years newer than the register. **Not a coordinate
  source**: it is marked not for navigational use, and the register is the only
  thing positions come from. Use the PDF, not the AVIF; the PDF has a text layer.

  It is copyright Geng Pty Ltd and carries a notice against redistribution. It is
  tracked in `docs/reference/` anyway, as a deliberate decision by the repository
  owner: the same PDF is offered as a public download by several sailing clubs, and
  the copy here is internal reference material for building this app. Keep it out
  of anything the app serves to a browser, and do not treat its presence here as
  permission to publish it further.
- ~~**The PFSYC inner start position.**~~ Resolved. The register has inner start
  marks for RPYC and SoPYC but no row for PFSYC, so this was `-32.001948,
  115.812006`, supplied by hand and flagged `user-supplied-2026`. The QGIS layer
  now carries a digitized `PFSYC Start Inner Start`, 71 m from that guess, and it
  is in `marks.json` as `pfsyc-start-inner` like any other mark. `gen_lines.py`
  reads it from there rather than holding a constant.

### Start / finish line

| End                   | lat         | lon         | mark id             |
| --------------------- | ----------- | ----------- | ------------------- |
| Inner (start box)     | -32.0024720 | 115.8124380 | `pfsyc-start-inner` |
| Outer (Club Buoy 32A) | -32.0031847 | 115.8132302 | `club-32a`          |

**Length 109.0 m (0.059 nm), orientation 136.7 / 316.7 degrees true.**

Both ends are digitized, so both moved: the inner end by 71 m from the hand-supplied
guess, the outer by 62 m from the register. The line is 8 m shorter and swung 3
degrees.

Two earlier sets of figures for this line are wrong and anything built against
either of them is wrong with it. 259.8 m on 110.1 / 290.1 came from the bad 32A
longitude in the club table. 117.3 m on 139.6 / 319.6 came from the register
position for 32A and the hand-supplied inner end.

### Mark pairs, which are not gates

Three pairs of marks always appear consecutively on the course sheets, close
together, and an earlier version of this document called them gates: one leg with
two mark refs, targeting the midpoint, completed by crossing between them.

**That was wrong. Each of these six marks is an independent mark, rounded on its
own, and each is its own leg.**

| Pair              | Marks    | Separation | Rounding  | Crossing between them |
| ----------------- | -------- | ---------- | --------- | --------------------- |
| Bricklanding      | 33A, 33B | 210.3 m    | starboard | forbidden while racing |
| Smith / Lucky Bay | 35A, 35B | 103.7 m    | port      | forbidden while racing |
| Mosman            | 14, 13   | 160.5 m    | port      | permitted, no rule     |

Two independent lines of evidence, either of which is sufficient:

1. **The sailing instructions forbid it.** Under Navigation Marks: "Boats that are
   racing are not permitted to cross an imaginary line between; Bricklanding A and
   Bricklanding B; Smith Buoy and Lucky Bay Buoy." A completion test that requires
   the boat to sail between the two marks would require it to break a rule in order
   to advance the leg.
2. **The printed distances say so.** Sunday Div II Course 1 contains all three
   pairs, Smith / Lucky Bay twice. Summing its legs with every mark rounded in turn
   reproduces the printed 10.98 nm to within 0.00 per cent. Treating the three
   pairs as midpoints instead gives 10.76 nm, 2.0 per cent under. Frostbite Course
   2 is the same story on its own: 9.07 nm exactly with both Bricklanding marks
   rounded, 8.83 nm and 2.7 per cent under through the midpoint.

So there is no gate concept anywhere in this app. Every leg targets exactly one
mark, except the last, which targets the finish line. This removes the midpoint
targeting, the between-the-marks completion test, and the special-case leg shape.

What survives from the old gate model, and is still needed:

- The Bricklanding and Smith / Lucky Bay lines exist in `lines.json` as
  `no_cross_lines`, because crossing one while racing is a rule breach worth
  logging and showing. They are never leg targets.
- Mosman has no line at all. Nothing prohibits crossing between 14 and 13, so
  there is nothing to detect. That the two are always sailed as a pair is a
  property of how the courses are written, not a rule the app enforces.
- `engine/nav.py`'s line-crossing primitives, which the finish line needs anyway.

### Mark numbers are not unique

Fourteen numbers are shared by two marks each within the racing area:

```
11  blackwall-11 / rocks-spit-11          32  armstrong-32 / tawarri-spit-32
13  mosman-b-13 / university-spit-13      36  armstrong-spit-36 / dunn-mark-36
14  knot-spit-14 / mosman-a-14            37  deepwater-spit-37 / squadron-37
16  inner-dolphin-16 / roe-16             39  applecross-spit-39 / bartlett-39
17  outer-dolphin-17 / parker-17          45  attadale-spit-45 / crawley-45
23  college-23 / heathcote-outer-black-23 52  bricklanding-spit-52 / north-point-walter-spit-52
28  dalkeith-spit-28 / miller-28          55  foam-55 / middle-spit-55
```

Several of these collide inside PFSYC's own courses: 37 is both Deepwater Spit and
Squadron, and 38 is both Bond and Dee Rd. **Key every lookup on `id`.** `number`
is a display string only.

### Naming

The course sheets, the chart and the register all use different names for the same
marks, so `aliases` carries the variants. Notable ones:

- Course sheets say "Bond Buoy (38A)"; the register says "38 BOND SPIT"; the chart
  says "BOND 38A". Frostbite Course 4 says "Bond Buoy (38)" once, a typo.
- Course sheets say "Mosman B Buoy (13)"; the register says "13 Suicide".
- Course sheets say "Mosman A Buoy (14)"; the register says "14 Mosman".
- Course sheets say "Hallmark Buoy (41A)"; the 2015 guide says "Hall Mark".
- Minor: Sunday Div III Course 2 reads "8.30nnm".

### Rounding direction is a free lint check

The register's rounding column agrees with the PFSYC course sheets on **all twenty
marks**. Add a test that validates every leg in `courses.json` against the mark's
registered rounding and flags mismatches. With twenty out of twenty agreement, a
mismatch is almost certainly a transcription error rather than a deliberate course
design.

### Parsing the register

Marks are identified by the "Yachting WA Number/Name" column (column C), which
packs number, name and rounding into one string. The format is irregular:

- Mixed case in numbers: `33a` against `42B`.
- Inconsistent whitespace: `35b Lucky Bay  Port`.
- `#` in place of a number for unnumbered start marks.
- Free-text status appended after the rounding word: `38 Dee Rd Port as of 1Sep19`,
  `44A RPYC outer Start Check location`, `36 Dunn Mark Port removed`.
- Rounding vocabulary is `Port`, `Starboard` or `Start`.
- Eight rows carry a name but no position at all.

`scripts/gen_marks.py` handles this, but the twenty course marks are mapped
explicitly by their exact source string rather than by regex, and the generator
fails loudly if any of them stops resolving. Do not relax that.

### Currency of the data

The register is dated September 2019; the chart is July 2026. Marks may have moved
in the interval, and the register's own author flagged two entries as uncertain.
Validate against recorded GPS tracks: a rounding shows up unmistakably as a tight
curve, and the vertex of that curve is the mark. That gives a current survey for
free from data already being collected.

### Free unit-test fixtures

The register's MGA94 easting/northing columns validate `engine/nav.py`: project two
marks from lat/lon and compare the distance against the grid difference. Note that
grid north in MGA zone 50 differs from true north by roughly 0.6 degrees at
115.8 E, so compute bearings geodetically and use the grid only as a cross-check.

## 7. Course data model

```
courses.json   series, division, course_no, distance_nm, wind_note,
               flags: {division, numeral}, legs[], shortened_at
```

Series: Frostbite, Twilight, Friday, Sunday Div II, Sunday Div III, Sunday Div IV.
Four numbered courses in each. Courses change year to year, so this must be
editable.

**Legs are an ordered list allowing repeats.** Club Buoy 32A appears up to four
times in one course. Course position is a leg index, never a mark identity.

**The printed distance validates the whole transcription.** Every course sheet
prints a total in nautical miles. Summing the leg distances from `marks.json`,
mark to mark in the printed order, measuring the start and the finish from the
midpoint of the start line, reproduces it to about a per cent. Tolerance is 2 per
cent.

It used to reproduce it to within 0.1 per cent, and it stopped once mark positions
were redigitized. That is the expected direction, not a regression: the club
computed its printed figures from the September 2019 register, so agreement with
them measures "using the same coordinates the club used" rather than accuracy, and
section 6 has the evidence that the digitized positions are the better ones. Treat
this as a check on the leg list, which is what it is good for, and not as a check on
the coordinates.

A course that does not reconcile has a leg in the wrong order, a missing leg, or
the wrong mark. This single check catches most transcription errors without anyone
reading the PDF twice, and it should run in CI over every course. It is also what
disproved the gate model in section 6, so it earns its keep twice over.

Two courses transcribed so far do not reconcile, and in both the legs were checked
against the sheet row by row and the printed total is the value in doubt:

- **Frostbite Course 1**: legs sum to 7.30 nm against a printed 7.11, 2.7 per cent
  over. No single substitution or deletion from the twenty course marks lands
  within 1 per cent of 7.11. Through the pair midpoints it gives 7.14, which
  suggests whoever totalled this one course did it that way.
- **Sunday Div II Course 2**: 12.21 nm against a printed 11.92, 2.4 per cent over.
  Not yet investigated; that series is not transcribed yet.

The same arithmetic solves for `shortened_at`, as described in section 11.6.

## 8. Flags

Courses are signalled from the start box by a naval numeral flag for the division
and a numeral pendant for the course number. The course selection UI shows both
flags on each card so the crew can match what is flying rather than reading text.

Hand-write these as SVG rather than cropping from the PDF. Four naval numeral
flags and four numeral pendants are needed, all simple geometry, a few kB total.
Store the flag codes in `courses.json` as `{division: "naval-3", numeral: "pendant-2"}`.

## 9. Display

### 9.1 Port the existing HUD

The existing HUD is a hand-written standalone page served by a Node-RED `http in`
node at `/hud`, polling `/hud/data` every 500 ms. It is good. Port it close to
verbatim and keep:

- The `{v, age}` envelope and stale handling.
- `location.pathname.replace(/\/+$/, "") + "/data"` for proxy-prefix safety.
- `env(safe-area-inset-*)`, `apple-mobile-web-app-capable`,
  `overscroll-behavior: none`, `user-select: none`, `touch-action: manipulation`.
- The `fit()` function that sizes digits to their cell.
- The motor-mode panel swap: pre-render both row sets, toggle a class, 10 s hold
  so a lumpy idle cannot flip the panels back and forth.
- The colour variables, so the crew does not have to relearn the display.

Colours in use: SOG and TWS DodgerBlue `#1e90ff`, AWS `#8fc9ff`, TWA Orange
`#ffa500`, AWA `#ffcc80`, HDG Yellow `#ffff00`, COG `#ffff99`, RPM PaleGreen
`#98fb98`, current Cyan `#00ffff`, controller temp Red `#ff0000`, motor temp
FireBrick `#b22222`, rules `#262626`, labels `#767676`.

Also port the demo inject nodes as a demo mode. Being able to drive the display
without the boat is how finish detection gets tested.

### 9.2 Race screen layout

One screen, no scrolling, no modal dialogs, nothing needing two hands. Four
things dominate, in this priority order:

1. **Next mark name.** Largest text on the screen after the numbers. Use the
   display `name` from `marks.json`, not the id and not the number, because the
   crew calls it "Squadron", not "37".
2. **Distance to it.**
3. **Bearing to it**, with the boat's COG immediately alongside so the helm reads
   the delta without arithmetic.
4. **Elapsed race time.**

Secondary, smaller: leg number and total (`leg 4 of 11`), next leg type, rounding
side, rounding angle to next mark (degrees to port or starboard), time limit remaining, position source and staleness.

Rounding side should be shown as a word or arrow next to the mark name, sourced
from the leg rather than from the mark default, so a course that deviates from the
registered rounding still displays correctly.

### 9.3 Bearing presentation

Show two numbers, not one:

- **True bearing** to the mark, `000` to `359`.
- **Relative bearing**, signed and normalised to +/-180 with port negative, using
  the same `norm180` helper the HUD already uses for TWA and AWA. The crew is
  already reading two signed relative angles on this display, so a third in a
  different convention is a trap.

Do not apply magnetic variation. Every other angle on this display is true, and
the boat's compass heading arrives already resolved.

### 9.4 Distance presentation

Metres below 500 m, nautical miles above. Nobody wants to read `0.08 nm` on final
approach to a mark, and nobody wants `4830 m` on a long leg. Switch the unit
label with the value, and do not animate the transition.

Resolution: whole metres under 500 m, two decimals of a nautical mile above.

### 9.5 Staleness rules

The HUD's 15 s stale threshold is right for wind and motor readings. It is wrong
for navigation.

**Position gets a 5 s cutoff, and the treatment is blanking, not dimming.** A
bearing computed from a 15 s old position at 6 knots is 46 m out. Past the
cutoff, distance and bearing show `---`, and the leg engine stops evaluating
advance. A dimmed number still reads as a number when someone glances at it in
spray; an em-dash placeholder does not.

Show a persistent **position source and age indicator**. There is only one source
(boat GPS over MQTT, no phone fallback is possible over plain HTTP), so this is
not a chooser, it is a health light. It matters most in the case where the fix has
quietly stopped updating while every other field on the screen is still live.

Elapsed race time and the countdown are computed from the server clock and are
never blanked by sensor staleness. They remain correct when the GPS does not.

### 9.6 Modes

Three modes, plus the existing motor overlay:

| Mode         | Screen                                                               |
| ------------ | -------------------------------------------------------------------- |
| `idle`     | Course selection: series list, then four cards per series with flags |
| `prestart` | Countdown, time to line, distance to line, start line bearing        |
| `racing`   | Next mark, distance, bearing, elapsed                                |
| `finished` | Elapsed at finish, course sailed, reset button                       |

Implement the transitions with the HUD's existing panel-swap technique: pre-render
each panel, toggle a class. Do not rebuild the DOM, and do not animate. Mode is
server state, so every device switches together.

### 9.7 Night theme

Twilight races start at 1820 and the Parmelia Night Race at 1850, so a meaningful
part of the season is sailed in the dark. Provide a red-on-black theme that
preserves night vision, switched manually rather than automatically, since an
automatic switch during a race is worse than a stale one. Keep the layout
identical between themes so muscle memory survives the change.

### 9.8 Keeping the screen alive

Screen Wake Lock requires a secure context and is unavailable over plain HTTP.
Use a hidden looping muted video element instead. Roughly 2 kB, works on iOS and
Android, and must start on a user gesture. Start it on the first tap of any
control, and restart it on `visibilitychange` when the page comes back to the
foreground.

### 9.9 Multiple devices

Every device renders the same server state and any device can drive it. There is
no primary and no pairing step. A device that reloads mid-race picks up the
current state on its first poll.

## 10. Pre-start behaviour

- Three large buttons set T-0 from the moment of the hooter: T-10, T-5, T-1.
- A plus/minus one second nudge and a "sync to next whole minute" control, because
  someone always taps late.
- Audio alert at each minute and the final ten seconds. Unlock the AudioContext on
  the first hooter button tap, which is a free user gesture. Vibration works on
  Android and never on iOS, so audio is primary.
- Show **time to line**: distance to the start line divided by VMG toward it,
  against the countdown. That is the number that wins starts and all the inputs
  are available.

## 11. Leg progression

The engine is a state machine over `idle -> prestart -> racing -> finished`,
evaluated on every position fix. All of it lives in `engine/race.py` as pure
functions so it can be replayed against recorded tracks.

### 11.1 Start

All PFSYC races except programmed handicap starts are a **flying start**, and a
boat may be up to ten minutes late and still be scored. So:

- **Elapsed race time counts from T-0, the gun, not from the boat crossing the
  line.** This is how the club scores it, and a boat that starts late must still
  see its true elapsed time.
- Crossing the line is therefore not a required transition. `prestart` becomes
  `racing` on the clock, at T-0.
- Optionally flag an early crossing in the minute before the gun (Rule 30.1) as a
  warning only. Do not act on it, do not change state, and do not attempt to
  adjudicate a recall. The start box does that.

Handicap starts (Sunday, programmed twice in the 2026-27 season) have per-boat
start times displayed on the regatta board. Out of scope for now: the crew sets
the countdown from their own handicap fall time using the same T-10 / T-5 / T-1
controls.

### 11.2 Rounding a single mark

Auto-advance, with these guards:

1. Only the **current target** is tested. Courses repeat marks, so a naive
   proximity test against all marks will fire when the boat sails past 32A on the
   way to Squadron.
2. Arm when within **40 m** of the target.
3. Confirm on **three consecutive fixes of increasing distance** after arming.
   Departure confirms a rounding; proximity alone does not, since the boat may be
   drifting or becalmed near a mark.
4. Do not evaluate at all when position is stale (over the 5 s cutoff) or when
   mode is not `racing`.
5. After any advance, manual or automatic, **suppress auto-advance for 10 s**.
   This is the same hold idiom the HUD uses for motor mode, and it prevents a
   single rounding being counted twice when consecutive legs share a mark.

40 m is a starting value, not a fixed constant. Put it in config and tune it from
replayed tracks. It needs to be larger than GPS scatter and smaller than the
closest approach the boat makes to the target while not rounding it.

#### What the first replayed track says

`tests/replay/tune_rounding.py` runs this against a recording. On the 16 August 2026
Frostbite course 3 race:

- **40 m arms all ten roundings**, with closest approaches from 1 m to 8 m at the
  nine buoys and 23 m at the finish line midpoint, which is a line rather than a
  point and is expected to be looser. So the stated radius is sound.

  Worth knowing how nearly this went the other way: measured against the *register*
  positions, before they were redigitized, three of the ten closest approaches were
  40 m or more and a 40 m radius missed them. The conclusion "the radius is too
  small" was wrong, and the mark data was.

- **"Three consecutive fixes of increasing distance" does not work.** At Hallmark it
  confirms 88 fixes early, and no radius changes that, because the radius is not the
  problem. The boat approached Hallmark to 36 m, turned, sailed 100 m away with the
  mark astern for fifty seconds, turned back, and rounded properly two minutes
  later. Requiring a 30 m departure from the closest approach fires 66 fixes early
  on the same manoeuvre.

- **Confirm on the mark passing astern instead**, that is
  `abs(relative_bearing) > 90` for three consecutive fixes. On nine of the ten legs
  that lands within three fixes of the true rounding, against three to six for the
  distance rule, and it is the rule that means something: a mark that has gone
  behind you has been rounded. It needs COG, so it must not be evaluated when COG is
  stale, which matters because COG is unreliable at the low speeds a boat drifts at
  near a mark.

- **The Hallmark case is irreducible.** That first pass is rounding-shaped: approach,
  turn, depart with the mark to port, which is exactly what the real rounding looks
  like a minute later. No proximity or departure rule distinguishes them, and a
  human reading the track would not either. This is the case 11.4 exists for.

### 11.3 The paired marks, and the lines it is a breach to cross

There is no gate handling, and no leg has two marks. Section 6 has the evidence.
Bricklanding A and B, Smith and Lucky Bay, and Mosman A and B are six ordinary
marks in three consecutive-leg pairs, each rounded on its own under the rules of
11.2. A pair 110 m to 206 m apart means two legs whose targets are close together,
which the 40 m arming radius and the 10 s post-advance hold already handle: that
hold is what stops the second mark's arming from being satisfied by the boat still
departing the first.

Separately, and not a leg mechanism at all, `lines.json` carries
`no_cross_lines` for Bricklanding and for Smith / Lucky Bay, because the sailing
instructions forbid crossing between those two pairs while racing. Mosman has no
entry: nothing prohibits crossing between 14 and 13.

Detecting a breach uses the same crossing primitive as the finish:

- Project each fix onto the segment joining the two marks. It only counts when the
  projection parameter is within `[0, 1]`, so sailing round the outside of either
  mark, which is exactly what the course requires, is not a breach.
- The crossing direction is irrelevant here. Either way across is a breach.

When the boat crosses one of those lines while racing, log a `breach` event and
show a brief non-blocking notice. Never advance the leg on it, and do not nag: the
crew knows, and the penalty is theirs to take. The value is in the log, which is
how a course sailed with an inadvertent breach gets noticed after the race rather
than argued about during it.

### 11.4 Manual override

Auto-advance is a convenience. Manual is the contract.

- A large, always-visible **Next mark** button, and a smaller **Back**.
- Manual advance sets the leg index authoritatively and immediately, overriding
  any pending auto-advance state.
- Because leg index is server state, a tap on any device moves every device.
- The app must never be wrong in a way the crew cannot fix in one tap. If in
  doubt about a detection rule, choose the version that fails to advance rather
  than the version that advances early: a missed advance costs one tap, a false
  advance points the helm at the wrong buoy.

### 11.5 Finish detection

**This is the highest-risk logic in the project.** Club Buoy 32A is the outer end
of the start/finish line and also a mid-course mark in most courses, appearing up
to four times in one course. Boats cross the finish line repeatedly while racing.

Rules:

1. Finish detection is **disarmed** until the final leg completes. Every crossing
   before that is ignored silently, with no notice and no log entry beyond a debug
   counter.
2. Once armed, record which side of the line the boat is on. A finish is a sign
   change away from that side, with the projection parameter within `[0, 1]` of
   the 117.3 m segment.
3. On finish: freeze elapsed time, switch to `finished`, publish the event.
4. Never auto-reset. The crew resets when they are ready.

Test coverage for this is non-negotiable. At minimum, replay Frostbite Course 1
(four crossings of the line while racing) and confirm exactly one finish fires,
on the correct fix.

### 11.6 Shortened course

The start box signals a shortened course with International Code Flag S. It has
two meanings depending on when it is flown:

- **At the start**, under the course numeral pendant: the finish is the first
  crossing of the line after the start.
- **During the race**: the next pass through the line ends the race.

Both reduce to the same thing in the engine: a **Shorten** control that arms
finish detection immediately, regardless of leg index. Make it a deliberate action
with a confirm, since an accidental tap ends the race.

The Sunday Div II, III and IV course sheets also print a shortened distance
alongside the full distance (for example 10.98 nm full, 8.85 nm shortened). The
truncation point is not stated in words, but it can be **solved for**: compute
cumulative leg distances plus the run to the finish, and find the leg index whose
truncation matches the printed shortened figure. Store the result as
`shortened_at` in `courses.json`. If no leg index matches within tolerance, that
is a signal the leg transcription is wrong, not that the arithmetic is.

### 11.7 Time limits

From the sailing instructions:

- **Sunday**: three hours, extended by thirty minutes if the first boat completes
  within three hours.
- **Friday afternoon**: 1730 hrs, no extensions.
- Boats not finishing are recorded DNF.

Hold the limit per series in config. Display remaining time against the limit once
inside the final thirty minutes, and only then, so it does not occupy screen space
for most of the race. Do not change state when the limit passes: whether a boat is
DNF is the race committee's call, not the app's.

### 11.8 Motor

The SevCon turning during a race means the boat is not racing. Show the existing
motor indicator, and treat it as a signal not to trust an auto-advance. Do not
suppress advance automatically, since motoring briefly to clear an obstruction is
not the same as retiring.

### 11.9 Events published

Every transition is published for `event_recorder` to log, which is what makes the
next season's replay tests possible:

```
race/event  {type: "select"|"timer"|"start"|"rounded"|"breach"
                   |"shorten"|"finish"|"reset",
             course, leg, leg_name, ts, lat, lon, source: "auto"|"manual"}
```

Recording `source` matters. A season of races where auto-advance fired correctly
and was not overridden is the evidence needed to tighten the 40 m threshold, and a
cluster of manual overrides at one mark points straight at a bad coordinate.

## 12. Map page

No internet means no tile server. Draw it as SVG from the app's own data: marks,
the current course legs with rounding side, the start line, and the boat with a
heading vector. Generated from `marks.json`, so a new mark appears automatically.

Default view is fit-to-current-course, with zoom out to full extent as the
deliberate gesture rather than the default. At full extent the marks cannot be
labelled legibly on a phone.

`marks.json` contains 102 marks inside the racing-area bounding box, of which 20
are used by current PFSYC courses. The rest carry `used_in_courses: false` and are
map context, and also mean a course-sheet change next season is unlikely to need
new mark data.

### Shoreline (optional, stage two)

Do not trace the shoreline off the Geng course marks chart, even though section 6
now keeps a copy in `docs/reference/`. Two reasons, and the first is the one that
matters: it is marked not for navigational use, so a coastline derived from it
would carry that caveat into the one place on the display that looks like a chart.
The second is that a derived shoreline shipped to the browser is redistribution of
a copyright work, which internal reference use is not. Use OSM as below.

Extent covering PFSYC plus the other Swan River clubs, matching the `bbox` in
`marks.json`:

```
south -32.030346   west 115.748   north -31.959052   east 115.856573
```

10.25 km by 7.94 km, 81 km squared.

Overpass Turbo query:

```
[out:json][timeout:120];
(
  way["natural"="water"](-32.030346,115.748,-31.959052,115.856573);
  relation["natural"="water"](-32.030346,115.748,-31.959052,115.856573);
  way["waterway"="riverbank"](-32.030346,115.748,-31.959052,115.856573);
  way["natural"="coastline"](-32.030346,115.748,-31.959052,115.856573);
);
out geom;
```

Then in mapshaper:

```
-proj +proj=utm +zone=50 +south +datum=WGS84
-filter 'this.area > 5000'
-dissolve
-simplify interval=10 keep-shapes
-proj wgs84
-o precision=0.00001 format=geojson coast.json
```

The 10 m tolerance is set for a zoomed-in single-bay view at roughly 8 m per
pixel, not for the full extent. The area filter drops swimming pools and
ornamental ponds. Expect 50 to 90 kB.

QGIS equivalent: QuickOSM, clip to extent
`115.748,115.856573,-32.030346,-31.959052 [EPSG:4326]` (note the different
ordering), select and delete `$area > 5000` inverted, dissolve, reproject to
EPSG:7850 or EPSG:32750, Douglas-Peucker simplify at 10 m, reproject to EPSG:4326,
export GeoJSON with COORDINATE_PRECISION 5.

Caveats to keep in the loader comment: OSM banks are crowd-sourced and this is
orientation only, not navigation. It says nothing about sandbanks, which is where
the actual trouble is on Melville Water. Point Walter spit is submerged at higher
tides and its presence in OSM depends entirely on which imagery the mapper traced,
so it must not be read as reliable. If the coastline query returns anything, note
that coastline ways are open lines and will produce garbage if dissolved together
with water polygons.

Higher value than the shoreline, for a later stage: the 2 m depth contour for
Melville Water from the AHO ENC. That is the line that actually changes how a leg
is sailed.

## 13. Build order

1. `engine/nav.py` with unit tests, using the MGA94 grid columns as fixtures.
2. `courses.json` for one series, linted against the rounding column.
3. Port the HUD, serve it at `/race/hud`, compare side by side against
   `/nodered/hud` with the boat running.
4. Disable the Node-RED Sailing HUD tab, leaving it in the flow as a fallback for
   one season.
5. ~~Add position publishing to the GPS source.~~ Done: `pyemonlib.emon_mqtt`
   publishes `gps/position/<subnode>`, and `mqtt_client.py` reads it. No longer
   blocking, which unblocks 6.
6. Race state machine, driven by replayed tracks before it is driven by the boat.
7. Countdown and pre-start.
8. Flags and course selection UI.
9. Map page.
10. Config editor.

## 14. Deferred

- A local CA issuing a cert for `enchantee.local` with `10.42.0.1` as an IP SAN
  would buy back the wake lock API and phone GPS as a position fallback, at the
  cost of installing and trusting a root certificate on each device. Not worth it
  initially.
- Server-sent events instead of polling.
- Depth contours.
- Re-surveying the PFSYC inner start mark.
