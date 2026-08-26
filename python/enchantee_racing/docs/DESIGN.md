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

Leg type comes free from `norm180(twd - bearingToMark)`: under about 40 degrees is a
**beat**, over 140 is a **run**, otherwise a **reach**. Showing the next leg type before
rounding is useful for sail selection.

One short word each, and that is a constraint rather than a preference. The label was
changed to "close hauled" for a while and changed back, because it is read in two places
that are short of width, neither of which is obvious from the value's own definition:

- The race screen's secondary row, where it comes last after the leg number, the next
  mark's name and the transit angle. Measured on the longest realistic row, "leg 10 of 10
  - then Bricklanding B -147 <type>": 224 px against 265 at a 320 px viewport, so the
  short word returns 41 px, rising to 67 on the iPad.
- The leg table's right-hand column, which is sized to its content, so the long word does
  not clip: it takes width off the mark name beside it instead. That column is 50 px wide
  with "beat" and 83 with "close hauled" at 320 px, 67 against 111 at 375.

Neither was actually overflowing at the current font sizes, so this is headroom and not a
repair. It is headroom in the two places where a longer mark name or a larger font is most
likely to spend it. A test asserts each type is one word of five characters or fewer, so
"broad reach" or "downwind run" cannot arrive later and undo it silently.

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

**Done**, and with one addition: `/hud` as a shortcut to the instruments.

```nginx
    location = /hud { return 302 /race/hud; }
```

Claiming `/hud` costs nothing. The catch-all `location /` rewrites the root onto
`:1880/ui/`, so `/hud` resolved to `:1880/ui/hud`, which does not exist, and an
exact-match location outranks a prefix one. Node-RED's own HUD is served at its
root and stays reachable at `/nodered/hud`, which is where step 3 of section 13
does its side-by-side comparison.

It is a **302 and not a 301**, unlike the trailing-slash redirects above. Those are
structural and permanent; this is an alias that is expected to be repointed. Until
the Node-RED tab is retired (13.4) it is useful to be able to swing `/hud` between
the two implementations, and a 301 cached in every phone on the boat would make
that a nuisance to undo.

The app needed no change for either layout, which is worth knowing before anyone
reorganises the URLs: the navigation is relative links (`href="hud"` and
`href="."`), and `hud.html` derives its API base by stripping a trailing `/hud`
from `location.pathname`. A prefix of `/race/` and a prefix of `/hud/` both work.

### Deployment

A container, not the systemd unit section 13 and CLAUDE.md assumed:
`sfewings32/emon_enchantee_racing`, on `python:3.13-slim` rather than the
`python:3.13` base the other `python/*.Dockerfile` images share, because this app
installs neither numpy nor the pyemonlib wheel. Host networking, so mosquitto is on
`localhost` and Flask lands on the host's 5002 where nginx expects it, matching
`event_recorder`. `restart: always`.

Two things about that image are load-bearing rather than incidental:

- **The `COPY` list is an allow-list**, naming each thing the app serves. It is not
  `COPY enchantee_racing/ ./`. `docs/reference/` holds the Geng chart, which section
  6 keeps as internal reference while keeping it out of anything the app publishes,
  and this image goes to a public registry. An allow-list also cannot leak a file
  added to `docs/` later. The cost is that a new file at the app root has to be added
  to it, which has already been forgotten once.
- **`STOPSIGNAL SIGINT`.** The Werkzeug development server installs no SIGTERM
  handler, so `docker stop` waited out the full ten-second timeout and then killed
  it. SIGINT raises `KeyboardInterrupt` out of `app.run()`, which is what the
  `finally: source.stop()` in `app.py` is written to catch, so paho shuts down rather
  than being killed mid-publish. Measured: 10.2 s before, 0.4 s after. An exec-form
  CMD is needed as well, so python is PID 1 and receives the signal at all, but on its
  own it changed nothing.

The whole application directory is bind-mounted from the working tree, so course data
and the front end are editable in place (section 7, and CLAUDE.md's jetty rule). Note
that no rebuild is not the same as no restart: `static/` is served from disk per
request and is live, while `templates/` are cached by Jinja and `config/` is read once
by `load_config()`, so both need a container restart.

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

|                         | register positions  | digitized positions             |
| ----------------------- | ------------------- | ------------------------------- |
| median closest approach | 21 m                | **5 m**                   |
| worst                   | 65 m (Dolphin East) | 23 m (the finish line midpoint) |

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
- ~~**The PFSYC inner start position.**~~ Resolved, and the hand-supplied guess was
  right. The register has inner start marks for RPYC and SoPYC but no row for
  PFSYC, so this was `-32.001948, 115.812006`, flagged `user-supplied-2026` and
  marked worth re-surveying. The QGIS layer now carries a digitized `PFSYC Start Inner Start` 1.6 m from it, in `marks.json` as `pfsyc-start-inner` like any other
  mark, and `gen_lines.py` reads it from there rather than holding a constant.

### Start / finish line

| End                   | lat         | lon         | mark id               |
| --------------------- | ----------- | ----------- | --------------------- |
| Inner (start box)     | -32.0019611 | 115.8120142 | `pfsyc-start-inner` |
| Outer (Club Buoy 32A) | -32.0031847 | 115.8132302 | `club-32a`          |

**Length 178.1 m (0.096 nm), orientation 139.9 / 319.9 degrees true.**

The line is 61 m longer than previously thought, and that is 32A having moved 62 m
from its register position. The inner end is within 1.6 m of the hand-supplied
guess it replaced, so that guess was right all along.

It took a replay to establish that. The first digitizing pass put the inner mark 71 m
along the line towards 32A, which shortened the line to 109 m, and replaying the 16
August 2026 race through it produced no finish at all: the boat's last crossing fell
at parameter -0.34, which is 38 m outside the inner end. The recorded track brackets
the answer from both sides, and it is worth writing down how, because the same
reasoning applies to any club's line:

- The **15:16:05 finish crossing** is the lower bound. The line has to reach past it.
- The boat's **transits to and from the pen**, at 13:13 and 15:27, cross the same
  extension 146 m out. The line must *not* reach past those, or leaving the pen
  registers as a finish.

Anything between 37 m and 146 m out satisfies both, and the redigitized mark sits at
69 m.

The method is worth keeping even though the answer is now settled, because it applies
to any line and will be wanted again after a re-survey: project every fix of a
recorded track onto the line, find the sign changes, and sort them into crossings
made while racing and crossings made getting to and from the pen. The racing ones are
lower bounds on how far the line must reach and the pen ones are upper bounds. Which
is which comes from the clock, not the geometry: a crossing before the gun or after
the finish is not a race crossing however close to the line it looks.

Three earlier sets of figures for this line are wrong, and anything built against any
of them is wrong with it: 259.8 m on 110.1 / 290.1 from the bad 32A longitude in the
club table; 117.3 m on 139.6 / 319.6 from the register position for 32A with the
hand-supplied inner end; and 109.0 m on 136.7 / 316.7 from the first digitizing pass.

### Mark pairs, which are not gates

Three pairs of marks always appear consecutively on the course sheets, close
together, and an earlier version of this document called them gates: one leg with
two mark refs, targeting the midpoint, completed by crossing between them.

**That was wrong. Each of these six marks is an independent mark, rounded on its
own, and each is its own leg.**

| Pair              | Marks    | Separation | Rounding  | Crossing between them  |
| ----------------- | -------- | ---------- | --------- | ---------------------- |
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
               flags: {division, numeral}, legs[],
               shortened_distance_nm, shortened_at, shortened_note
```

Series: Frostbite, Friday, Sunday Div II, Sunday Div III, Sunday Div IV, Twilight.
Four numbered courses in each except Twilight, which prints three. Twenty-three
courses in all, and all of them are in `courses.json`. Courses change year to year,
so this must be editable.

The Frostbite four were transcribed by hand. The rest were extracted from the same
PDF by `scripts/extract_courses.py`, which parses the Frostbite page as well and
refuses to write anything unless what it reads there matches the hand transcription
leg for leg. Using the hand-checked series as a control caught three parser faults
that would each have produced plausible, wrong courses: a rounding swallowed by the
printed dotted leaders, a finish leg with no name in front of its number, and the
flare and torch counts in the Twilight prose read as marks 2 and 7. The Frostbite
entries are then copied through untouched, because they carry judgements a parser
will not reproduce, such as which of two marks a printed "(38)" meant.

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

Six of the twenty-three do not reconcile inside the 2 per cent tolerance. In every
one the legs have been checked against the sheet row by row, and the printed total is
the value in doubt:

- **Frostbite Course 1**: legs sum to 7.26 nm against a printed 7.11, 2.1 per cent
  over. No single substitution or deletion from the twenty course marks lands
  within 1 per cent of 7.11. Through the pair midpoints it gives 7.14, which
  suggests whoever totalled this one course did it that way.
- **Sunday Div II Course 2**: 12.25 nm against a printed 11.92, 2.8 per cent over.
  This section predicted 12.21 and 2.4 per cent before the series was transcribed,
  from a route read off the sheet by eye; the extracted legs put it slightly further
  out. The prediction was close enough to confirm it is the same discrepancy.
- **Sunday Div IV Course 1**: 9.47 nm against a printed 10.51, **9.9 per cent
  under**, and much the worst of the six. The parse is not the suspect: legs 1 to 9
  are identical to Sunday Div III Course 1, which reconciles to +0.3 per cent, and
  the four legs where they diverge are ordinary ones with nothing degenerate in them.
  Its printed shortened figure of 8.96 nm does not resolve to a leg either, which is
  consistent with the full figure being the thing that is wrong.
- **Sunday Div IV Course 2**: 9.49 nm against a printed 9.11, 4.2 per cent over.
- **Twilight Course 1**: 5.79 nm against a printed 5.64, 2.6 per cent over.
- **Twilight Course 3**: 5.68 nm against a printed 5.83, 2.6 per cent under.

They are pinned in `tests/test_courses.py`, so a *new* mismatch fails the build while
these do not. Both Twilight ones sit just outside a 2 per cent tolerance and would
pass a 3 per cent one; that is not a reason to move the tolerance, because the check
earns its keep by being tight enough to catch a wrong mark.

The same arithmetic solves for `shortened_at`, as described in section 11.6.

## 8. Flags

Courses are signalled from the start box by a naval numeral flag for the division
and a numeral pendant for the course number. The course selection UI shows both
flags on each card so the crew can match what is flying rather than reading text.

Hand-write these as SVG rather than cropping from the PDF. Four naval numeral
flags and four numeral pendants are needed, all simple geometry, a few kB total.
Store the flag codes in `courses.json` as `{division: "naval-3", numeral: "pendant-2"}`.

**Draw them from the plate, not from memory.** Page 27 of the fixtures PDF is a plate
captioned "NAVAL NUMERAL FLAGS" and "NUMERAL PENDANTS" which shows all ten of each.
The first eight here were drawn from the code of signals as best I knew it, and five
of them were wrong: naval 1, 2, 3 and 4, and the numeral 3 pendant, which had its
red, white and blue stripes horizontal instead of vertical. The crew found them by
holding the screen up beside a halyard, which is the only test that was ever going to
find it, and exactly the failure the whole idea of showing flags is meant to avoid.

The lesson is not "check the flags", it is that a picture whose entire job is to be
matched against a physical object has to be drawn from a picture of that object. The
authority was on disk the whole time. `static/flags/README.md` now records the page,
how to render it, what each flag is, and which details are still only eyeballed;
`tests/test_race_screen.py` pins every arrangement so a later edit fails rather than
quietly shipping.

## 9. Display

### 9.1 Port the existing HUD

The existing HUD is a hand-written standalone page served by a Node-RED `http in`
node at `/hud`, polling `/hud/data` every 500 ms. It is good. Port it close to
verbatim and keep:

- The `{v, age}` envelope and stale handling.
- A data URL built from `location.pathname`, for proxy-prefix safety. The original
  polled `+ "/data"`; the port polls `/api/state` from the same derived base, since
  the racing panel needs race state (9.10). No absolute path either way.
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
   crew calls it "Squadron", not "37". Show the rounding side as a small turn arrow adjacent to the Next mark name.
2. **Distance to it.**
3. **Bearing to it**, with the boat's COG immediately alongside so the helm reads
   the delta without arithmetic.
4. **Elapsed race time.**

Secondary, smaller: leg number and total (`leg 4 of 11`), next-next leg name, transit angle to reach next-next mark (degrees to port or starboard), next-next leg type, time limit remaining, position source and staleness.

The **pre-start panel shows the first mark too**: its name, rounding side, distance
and bearing. These are not a separate calculation. The engine steers at leg 1 from the
moment a course is selected, so the same three readings the racing panel shows already
exist before the gun, and before the gun is when they decide which end of the line to
start at. They blank on a stale fix like everything else (9.5).

Rounding side is shown as an arrow next to the mark name, sourced from the leg
rather than from the mark default, so a course that deviates from the registered
rounding still displays correctly.

The arrow is the one the club's own chart uses: a semicircular arrow curling around
a buoy dot, its sweep the boat's turn. The arrow comes from the "port / starboard
rounding" row of the legend on page 1 of `docs/reference/Swan River course
marks-Jul26.pdf`; the dot in its concave side, and the gap left around it, are
measured off mark 33A, where the chart draws the pair together. Sweeping the whole
chart finds that same pairing about eighty times, mirrored between the two sides,
so what the screen shows is the chart's composite symbol and not an assembly of
ours. Port sweeps anticlockwise, starboard clockwise.

Copying the chart's symbol rather than drawing a fresh one is the whole point: the
crew has already read it beside every mark on the chart, so there is nothing new to
learn at the moment it matters, and a shape is taken in faster than a five-letter
word on a wet screen in sunlight.

Which side the dot goes on is not decoration. On the convex side the symbol says the
boat passes the mark on the other hand, which is the opposite instruction, so the
side is asserted in the tests rather than left to the eye.

The arrow sits at the right-hand edge of the mark name's line, against the panel
padding rather than the glass so it lines up with every other edge on the screen.
At the edge it has a fixed place to look for and a long mark name cannot crowd it;
the name ellipsises instead.

Both icons live in the DOM and the CSS shows one, the same way the panels do. They
are inline SVG rather than `<img>`, so they inherit `currentColor` and the night
theme recolours them with everything else, and so they cost no extra request. They
are drawn in the mark's colour rather than the label grey the word used, because a
glyph carries less ink than a word and this one is the difference between rounding
correctly and rounding the wrong way; the hierarchy under the mark name is kept by
size instead, at roughly half its height.

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

### 9.6 Modes, screens and getting between them

The app has **three** screens, named along the bottom of every one of them:

| Screen | What it is                                                          |
| ------ | ------------------------------------------------------------------- |
| `HUD`  | The instrument display, its own page at `/hud`                      |
| `Race` | Everything about a race: course selection, countdown, marks, finish |
| `Map`  | The course map. Not built yet, and shown disabled until it is       |

Every screen carries that navigation, so no screen is a dead end. Worth stating
because it was got wrong twice: the HUD had no way back to anything, and the racing
screen had no way to the HUD, which is the one a crew wants mid-race.

A third time, differently, and it took three attempts because the first two fixed
things that were not broken. The record of that is the useful part.

**The symptom.** The navigation sat half off the bottom of the race screen, and only
that screen.

**The cause**, eventually: the `<svg>` holding the rounding symbols. An `<svg>` is an
inline element, so at zero width and height it still sits on a line box of its own, and
that was about nineteen pixels of empty space above `#app`. `#app` is `100dvh`, so
anything above it puts its bottom below the fold, where `html, body { overflow: hidden }`
clips it. The navigation is about forty pixels tall, so half of it disappeared. The HUD
was never affected because the HUD has no symbols. Every other thing in that part of the
page, the wake video, the pip and the notice, is positioned out of the flow; the symbol
block had no CSS at all.

**The two wrong fixes**, both plausible, neither the cause:

1. Taking the navigation out of the flow and reserving its height as padding, which is
   what the HUD does. It stopped the navigation being pushed off and started it covering
   the controls, because the page was still nineteen pixels too tall and now the
   navigation was pinned to the real bottom of the screen while the controls were not.
   A hand-written height that has to match a rendered one is not a fix in any case:
   it either overlaps what is above it or floats above the bottom, and nothing in the
   code can say which.
2. Declaring which panel children give way when a column runs short. That work is kept,
   because it is correct and the panels genuinely could overflow on a short enough
   screen: the readings are flexible, the controls are pinned, and a panel clips its own
   overflow rather than drawing over what is below it. But it was not why the navigation
   moved, and the explanation first written here, that the pre-start panel had run out of
   room, was invented rather than measured.

**What the episode is worth.** Two fixes were reasoned from a plausible story about flex
layout, and the actual cause was nineteen pixels of nothing in a place nobody was
looking. The lesson is to find the element that is the wrong size before theorising about
which rule resized it. A test now asserts that everything in the flow above `#app` is
positioned out of it, which is the check that would have found this in the first minute
rather than the third attempt.

The HUD keeps its out-of-flow navigation, because its `fit()` sizes the digits against
the row heights of that column and putting the navigation into it would resize every
reading on the page. So that one page duplicates the navigation's height, and a test
checks its two copies against each other.

**Race is one screen with four faces**, and which face shows is the race's business
rather than the navigation's. There is no nav entry for Course or Finish, because
choosing a course and finishing are things that happen *to* a race, not places to
browse to. The four faces are the four modes below.

Moving between them is done by the controls that already mean something, which is
what stops the navigation and the state machine disagreeing:

| From                | Control       | Goes to                                       |
| ------------------- | ------------- | --------------------------------------------- |
| Course              | a course card | the countdown for that course                 |
| Countdown           | T-10/5/1      | the countdown, running                        |
| Countdown           | Start         | racing, leg 1, immediately                    |
| Countdown           | Course        | the course list, timer cleared                 |
| Racing, leg 1       | Back          | the course list, **race still running**       |
| Racing, any leg     | Back          | the leg before                                |
| Racing, last leg    | Finish        | finished, elapsed frozen                      |
| Racing              | Next mark     | the next leg                                  |
| Finish              | Course        | the course list, race reset                   |
| Course, race live   | Race          | back to whatever the race is doing            |
| Course              | a card's Details | that course, leg by leg (9.11)             |
| Racing              | Details       | the course being sailed, leg by leg           |
| Course detail       | Back          | wherever it was opened from                   |

Three of those need saying out loud.

**Back off leg 1 is a view change, not a race command.** There is no leg before the
first, so the button goes to the course list instead, and the race carries on
running behind it. That is why the course list grows a Race button whenever a race
is live: it is the way back, and without it the crew would have to abandon a race to
stop looking at the list.

**Choosing a course while a race is live ends that race.** The crew is on the course
list, with a race running, tapping a card: they mean to sail that one instead. It is
logged as a `reset` rather than a `finish`, because abandoning a race is not
finishing one, and the new course opens at its countdown.

**The course detail page is a face, not a screen, and its Back is not a fixed
destination.** It is reachable from two places and returns to whichever one it came
from, so it remembers rather than assumes (9.11). It is also the reason a card is two
targets: reading a course cannot go through selecting it, because selecting is the
thing that ends a running race.

The mode still decides which face shows *by default*, and a mode change still
switches every device together, which is the property that matters (DESIGN 2). A
device whose crew has tapped away to the course list follows the mode again the
moment it changes.

#### The modes underneath

Three modes, plus the existing motor overlay:

| Mode         | Screen                                                               |
| ------------ | -------------------------------------------------------------------- |
| `idle`     | The Course screen: series list, then a card per course with flags    |
| `prestart` | The Race screen before the gun: countdown, time and distance to line |
| `racing`   | The Race screen after it: next mark, distance, bearing, elapsed      |
| `finished` | The Finish screen: elapsed and course, both large, and a Course button |

Implement the transitions with the HUD's existing panel-swap technique: pre-render
each panel, toggle a class. Do not rebuild the DOM, and do not animate. Mode is
server state, so every device switches together.

#### The Finish screen

The elapsed time at the finish and the course sailed are the two things anyone wants
off this screen, and they are read across a cockpit by someone who has just stopped
concentrating. Both are set large, at the same weight as the racing numbers rather
than the secondary text.

Its one button is **Course**, not Reset. It does reset the race, but what the crew
is doing when they press it is going back to pick the next one, and the label should
say where it goes rather than what it clears. Nothing on this screen resets itself
and nothing times out (DESIGN 11.5).

### 9.7 Night theme

Twilight races start at 1820 and the Parmelia Night Race at 1850, so a meaningful
part of the season is sailed in the dark. Provide a red-on-black theme that
preserves night vision, switched manually rather than automatically, since an
automatic switch during a race is worse than a stale one. Keep the layout
identical between themes so muscle memory survives the change.

**The setting is server state, not browser state.** It began as a class the race page
toggled on its own document, with the button on the course-selection panel, and three
faults came back from the boat at once: it could only be set from that one panel, it
never reached the HUD or the map, and walking to either of those and back lost it. Those
are one fault. A setting held in a document cannot survive leaving that document, and
these are three separate documents by decision, the HUD being self-contained (9.1) and
the map being its own page (12.1).

So it lives in the store and rides in `/api/state`, which all three pages poll twice a
second anyway, and `POST /api/settings` sets it. That is what 9.9 already says about
everything else here: every device renders the same server state and any device can drive
it. It is the right answer for this setting rather than a convenient one, because the sun
sets on the whole boat at once; a per-browser preference would have to be set on the
phone, the iPad and the laptop separately. The store accepts only its two values, since
the value becomes a class on the body of three pages.

The **toggle is the fourth cell of the navigation**, the one piece of furniture all three
screens share, so it is one tap from anywhere and in the same place. Its label is the
theme one tap will switch to, not the one in force: a control that names its own state
needs a second affordance to say it is a control, and the theme in force is already
obvious from the whole screen being red. The three screen names keep their learned
positions and the toggle is appended after them.

Two things fell out of doing this. **The HUD had no night theme at all**, which nothing
had noticed because nothing could ask it to go dark; it has one now, and every reading in
it is a red. That costs the page's colour language for the night: its four pairs are true
and apparent readings told apart by hue, and at night they are told apart by tint alone,
the second of each pair being three quarters of the first. Going paler was not available,
red already being at the top of its channel, so a lighter tint could only be made by
adding green and blue, which is the one thing this theme may not do.

And the toggle has to be a `<button>` in a row of links. A user agent gives a button its
own font, border, background and 6px of side padding, and under `border-box` a
`flex-basis` of 0 cannot absorb that padding, so the unreset buttons measured 85px against
their neighbours' 73, and the HUD's, which its rule did not select at all, measured 52
against 238. Four equal cells is the point: the row is hit by feel.

**What was not done.** The obvious reading of these three faults is that the screens
should be one document sharing one scope. They should not. Both separations are load-
bearing and recorded: 12.1 rejected the map as a fourth panel because it is 88 kB of chart
data plus projection and gesture code that a crew watching a countdown never needs, and
9.1 keeps `hud.html` self-contained so the port can still be compared against the
Node-RED tab side by side. What was missing was never shared documents, it was shared
settings, and there is exactly one of those. `/api/settings` is where the next one goes.

### 9.8 Keeping the screen alive

Screen Wake Lock requires a secure context and is unavailable over plain HTTP.
Use a hidden looping muted video element instead. Roughly 2 kB, works on iOS and
Android, and must start on a user gesture. Start it on the first tap of any
control, and restart it on `visibilitychange` when the page comes back to the
foreground.

### 9.8.1 Home Screen, and the browser floor the boat sets

The pages are added to the iOS Home Screen and run in the standalone context, which is
what `apple-mobile-web-app-capable` asks for and what gets the crew a display with no
browser chrome on it. Two things had to be true for that to hold, and neither was
obvious from a development machine.

**A manifest, declaring a scope over both screens.** Modern iOS decides
standalone-versus-browser by the manifest's scope, and with no manifest it infers one
from the single URL that was saved. So tapping between HUD and Race threw the crew into
an overlay browser with a Done button, whichever of the two they had saved, and going
back went full screen again. `manifest.webmanifest` fixes it, and two details are
load-bearing:

- It is served from the **app root**, not from `static/`. `scope` and `start_url`
  resolve against the manifest's own URL, so from `/race/manifest.webmanifest` the
  scope is `/race/` and covers both screens; from `static/` it would have been
  `/race/static/` and covered neither.
- Every URL in it is **relative**, so one file is correct behind the nginx prefix and
  on the app's own port alike, with no host written down (CLAUDE.md).

**Script navigation on the nav links.** `location.assign` rather than letting the
anchor do it, because iOS 12 predates scope enforcement and needs it. Both are kept;
they cover different iOS generations, which is why the fault appeared on the phone and
not on the iPad and why fixing only one of them looked correct on one device.

**The browser floor is iOS 12**, because the boat carries an iPad mini 3 and that is as
far as it goes. Two features shipped that do not exist there, and neither failure is
visible on anything modern, which is why both got as far as the boat:

- `clamp()` needs Safari 13.1. Every clamped `font-size` was dropped and every reading
  fell back to the inherited 16 px, against the 132 px the distance computes to at that
  viewport. Each clamp now carries a plain fallback ahead of it, which is the idiom this
  file already used for `height: 100vh; height: 100dvh`. The fallback is the clamp's
  middle term, because that is the value which actually applies at every real viewport
  size; the min and max only bite at extremes.
- Flexbox `gap` needs Safari 14.1. Margins on the children instead; grid gap is fine,
  Safari 12 has that. The substitution is not mechanical, because margins reach element
  children only while `gap` also spaces the anonymous items flexbox makes out of bare
  text. So **a line of prose must not be a flex container**: the secondary row is built
  as `leg <b>2</b> of <b>10</b> · then ...` with real spaces in it, `display: flex` was
  collapsing them, and the gap was only ever putting them back. It is a plain block now
  and needs no gap on any browser.

A third arrived once the map page had joined the navigation, and it is the same shape:

- `100vh` on iOS is **not the visible height**. In a standalone app with a translucent
  status bar it counts the area the status bar sits over, so `#app` was taller than the
  screen and the bottom of it, the navigation, hung half off the iPad. `100dvh` is the
  right answer and needs Safari 15.4. `window.innerHeight` is right on every version of
  everything, so `static/viewport.js` measures it and hands it over as `--app-h`, and
  `#app` declares all three heights in ascending order of correctness: a browser takes
  the last one it understands, and one with no JavaScript still gets the best of the
  other two. The script re-measures on `resize`, on `orientationchange` after the delay
  9.6 already needed, and on becoming visible again, since a device rotated while in the
  background reports the old size otherwise.

  `hud.html` is left out of this. It is self-contained by decision (9.1), no external
  script and no external stylesheet, and its nav has been out of the flow since the port
  anyway.

  The height goes on `#app` as an inline pixel value rather than through a custom
  property, and that is a simplification, **not a fix for anything**. It is recorded here
  with the wrong theory it came from, because the wrong theory is the useful part.

  Two faults were reported from the iPad mini and nowhere else, both on the
  course-selection screen: the panel went blank a moment after appearing, and the course
  list ran past the bottom of the screen. The theory was that they were one fault, that on
  iOS 12 a `var()`-derived height is not a *definite* height, so the flex chain below
  `#app` had nothing to resolve against and a re-measure restyled without re-laying out.
  It was a tidy explanation that fitted both symptoms and the crew's own workaround.

  It is wrong. `static/layout-check.html` puts all three ways of setting the height in
  front of the device with a re-measure button and a restyle button, and on the iPad all
  three are identical: `#app` 1024 against an `innerHeight` of 1024, no page scroll, every
  Details button on screen, and re-measuring blanks nothing. So `var()` was never the
  problem, the custom property was never the problem, and the two faults are still open.
  The inline height is kept because one mechanism is simpler than two, and the two CSS
  declarations stay ahead of it for a browser with no JavaScript.

  What the probe then found, on the real screen, settled both:

  - **The blanking is a paint fault, not a layout fault.** Restyling brought the picture
    back with the geometry byte-for-byte identical, so the boxes were right throughout and
    the pixels were simply not drawn. That rules out every height, every flex basis and
    every grid track at a stroke, and points at the compositor. Both scrolling surfaces
    carried `-webkit-overflow-scrolling: touch`, which asks iOS for a composited scroller
    and whose best-known failure is exactly this. Removed from both. It costs nothing on
    iOS 13 and later, where the property was removed and momentum is the default; on
    iOS 12 it costs momentum in two lists and buys lists that are visible.

  - **The course list needs 922px in a 764px box**, with four courses in it, on a screen
    755px wide with a 144px minimum track. That is about 221px a card in a single column,
    so the grid had collapsed to one track and was ignoring three quarters of the width.
    The cause is in the flag files: an SVG with a `viewBox` and no `width` or `height` has
    an intrinsic **ratio** but no intrinsic **size**, and the cards draw the flags
    `height: 100%; width: auto`, which needs the ratio. An engine that does not use the
    ratio of a viewBox-only image falls back to the CSS default width for a replaced
    element, 300px, and two of those make a card 600px wide at min-content, four times its
    track. All eight flags now carry `width` and `height` matching their viewBox. The probe
    prints the natural size, so the device says whether it took: 120x60 or 90x60 rather
    than 300x150.

  Neither is confirmed from the boat yet, and both are stated as what the measurements
  point at rather than as settled. The probe keeps two switches for the confirmation: one
  puts the composited scroller back, because a page that stops blanking has to be made to
  blank again before the cause is established, and one stops the wake-lock video, which is
  the only other composited layer on the page and the next suspect if the scroller is not
  the one.

  The lesson is the one 9.6 and 9.8.1 keep relearning, and it cost a release to learn it
  again: **a theory that explains every symptom is not evidence.** The replica could not
  show the fault, which should have been the first thing checked about the replica rather
  than read as the fault being absent. `static/probe.js`, loaded onto the real screen by
  `?probe=1`, measures the real thing instead: it logs every change to the geometry as it
  happens, so the moment the screen goes blank is in the log, and its restyle button
  answers the one question that decides what kind of fault this is. If the geometry is
  unchanged when the picture comes back, the layout was right all along and the pixels
  were simply not painted, which is a compositing fault and has nothing to do with
  heights.

And one that is not a missing feature but a wrong axis:

- **A font sized only in `vh` overflows a tall narrow screen.** The countdown at `22vh`
  came out at 147 px on the phone, and its five characters wanted 409 px of a 375 px
  screen, so the seconds ran off the edge. It looked correct on the iPad and on a
  desktop, both of which are wider than they are tall, which is why it took a phone to
  see. The two readings with no natural width limit are now capped by a `vw` term as
  well: `min(22vh, 26vw)` inside the clamp, with a plain `26vw` ahead of it for iOS 12,
  since `min()` is Safari 11.1 while `clamp()` is 13.1. The plain fallback alone would
  draw something enormous on a wide desktop, so both lines earn their place, and the
  height term is still what applies on every device the boat carries.

The home indicator's inset took three passes, and the first two were the same mistake
twice. It began on `#app`, where it padded the whole column and left a band of page
background below the navigation. Moved to `#nav`, the row's background reached the glass
but its buttons still stopped short of it, so the band was still there in the nav's
colour and came straight back from the boat. Both reserved the whole of what iOS reports,
and that is the point: `env(safe-area-inset-bottom)` is 34pt on a phone, which is the
system's swipe-up gesture region, not the indicator. The indicator is a 5pt pill sitting
8pt off the bottom edge, so 13pt clears it.

So `--nav-pad` is `min(env(safe-area-inset-bottom), 0.9rem)`, about 14px, and it is the
whole of what the bottom of the screen gives up. It sits on the buttons rather than on
anything above them, so their background and their hit area both run to the glass while
the label stays above the pill, and it is **added to** the 2.6rem label band rather than
taken out of it: `box-sizing` is `border-box` here, and a bare `min-height` let the
padding eat the label's own room, collapsing the visible row to the height of the text.
That was caught by measuring, not by looking at it.

Measured at the phone's viewport with the inset simulated, all three pages agree: a 42px
label band, the button reaching the glass, the label 15px clear of the pill, and 20px
returned to the panels. `--nav-pad` is declared twice, `0px` and then the `min()`, so a
browser without `min()` gets what it had before; the floor is Safari 12 and `min()` is
11.1, so nothing real takes the fallback. `hud.html` carries its own copy of all of this,
being self-contained, and the tests check the two against each other.

All of these are pinned by tests, since none can be observed on a development machine. The
general lesson is the one section 9.6 already records in a different form: on this
project, a layout fault is worth measuring before it is theorised about. Rendering the
real page at the device's viewport and reading back computed sizes distinguished "the
caps are too small" from "the declaration is being dropped", and those wanted opposite
fixes.

### 9.9 Multiple devices

Every device renders the same server state and any device can drive it. There is
no primary and no pairing step. A device that reloads mid-race picks up the
current state on its first poll.

This governs settings as well as race state, which 9.7 records the app having to learn
once. Anything the crew sets goes in the store and comes back in `/api/state`; nothing
that matters is remembered by a browser. The theme is the whole of the settings so far.

### 9.10 The HUD while racing

While the race is in the racing mode, the HUD's fourth panel stops showing HDG and
COG and shows the mark the boat is sailing to instead:

- **Next mark name**, and **distance** to it.
- **Bearing**, **COG**, **off the bow**.

The reason is that a phone on the HUD is a phone that cannot see the race screen,
and the two things the crew wants at once are the instruments and the mark. Trading
the fourth panel for it costs the least: HDG is the reading least missed while
racing, because COG stands in for it whenever the boat is moving, and a compass
heading does not answer any question being asked on a close-hauled leg. So HDG goes and
COG stays, and it stays because bearing is only useful next to the number you compare
it against (9.3).

Only in the racing mode. Idle, pre-start and finished keep HDG and COG, because
before the gun the heading is what you sit on while you wait for it, and after the
finish there is no mark to show.

Distance, bearing and off the bow follow the same rules as on the race screen: the
distance switches from metres to nautical miles at 500 m (9.4), the angles are true
and the relative one is signed with port negative (9.3), and a position older than
5 s blanks all three rather than dimming them (9.5). COG keeps the 15 s dim it has
always had, because it is an instrument reading rather than a derived one.

Both row sets are pre-rendered and swapped by a class, which is the idiom the motor
panels already use (9.1): no DOM rebuilding, and a transition mid-race costs no
relayout of the screen.

This is the one thing the HUD needs that `/hud/data` does not carry, so the page
polls `/api/state` instead, which is where race state lives (section 4). The
prefix-relative URL is unchanged in spirit, built from `location.pathname` so the
page still works behind `/race/` and on its own port alike. `/hud/data` stays
exactly the shape the Node-RED flow served, because that is what makes the port
comparable side by side, and nothing needs it to change.

### 9.11 Course detail

A page showing one whole course: every leg in order, with the mark's name and number,
which side to round it, the leg's length and bearing, the running total, and each leg's
type, beat, reach or run, when the wind direction is known. Served by `GET /api/course/<id>`,
which composes `engine.course.leg_table()` with the series metadata.

It is **not a screen** and is not in the navigation. It is a panel like the others,
reached from two places, and its only way out is back to whichever of them it was
opened from:

- **From a course card**, to read a course before committing to it. This is the case
  selecting cannot serve: choosing a course while a race is running ends that race
  (9.6), so "let me look at course 3" must not go through selection. Each card is
  therefore two targets, the body to sail it and a strip beneath to read it.
- **From the racing panel**, to see what comes after the mark ahead. The leg being
  sailed is marked in the list, so the page answers "where am I up to" as well as
  "what is this course".

Because there are two ways in, Back cannot be a fixed destination: opened from the
course list mid-race it must return to the list, not to the racing panel. So the page
records where it came from. A mode change clears that and closes the page, on the same
principle as everywhere else, that the race outranks whatever someone is reading, and
because a remembered destination goes stale the moment the race leaves it.

Nothing on the page changes the race. It issues no commands at all, which is what
makes it safe to open at any moment, including mid-race with the finish armed.

**It scrolls, and it is the only thing that does.** Fifteen legs will not fit a phone
at a size worth reading. The no-scrolling rule in CLAUDE.md is about the racing
display, where the reader is wet, busy and one-handed; this page is read at rest, and
a scroll here is not the failure it would be there.

Where the printed distance and the marks disagree the page says so in words, rather
than showing two numbers and leaving the crew to notice. Same for a printed shortened
distance that resolved to no crossing of the line (11.6). The data has these
imperfections (section 7) and a briefing sheet is exactly where they should be visible.

The rounding symbol is now shown in three places: the next mark while racing, the
first mark before the start, and every leg here. So the geometry is defined once as an
SVG `<symbol>` and used, rather than copied. That matters because the test that
guards the sweep direction can only guard the copy it finds, and a second copy drifting
the other way would send the boat round a mark backwards.

## 10. Pre-start behaviour

- Three large buttons set T-0 from the moment of the hooter: T-10, T-5, T-1.
- A plus/minus one second nudge and a "sync to next whole minute" control, because
  someone always taps late.
- Audio alert at each minute and through the final ten seconds, described below.
  Unlock the AudioContext on the first hooter button tap, which is a free user
  gesture. Vibration works on Android and never on iOS, so audio is primary.
- Show **time to line**: distance to the start line divided by VMG toward it,
  against the countdown. That is the number that wins starts and all the inputs
  are available.

### 10.1 The countdown audio

A voice, not a tone. At each minute it says the minute: "Ten minutes", "Nine
minutes", down to "One minute", singular. Through the final ten seconds it counts
the seconds down and ends with a horn at T-0.

A tone tells you something happened and leaves you to work out what. A voice saying
"Four minutes" is checkable against the screen without looking at the screen, which
is the situation the crew is actually in: hands full, eyes on the line and the boats
around it.

The last ten seconds are **one recording**, not ten cues. Ten separately scheduled
clips can drift apart, and the gap between "one" and the gun is the part that has to
be exact, so it is fixed once when the file is built rather than assembled live on a
phone. The horn sits at a known offset into that file, and `static/app.js` starts the
file so that instant lands on T-0. The offset lives in three places, which a test
holds together: the generator that writes the file, the manifest beside it, and the
constant the page schedules against.

**Scheduled, not triggered.** This is the part worth being careful about. The page
polls at 2 Hz, so noticing T-0 and playing a sound at that moment puts the gun up to
half a second out, and half a second on a start line is a boat length. Instead every
clip is handed to the audio clock with the time it should start, which is
sample-accurate. Three things follow from that:

- A clip that is already due is started **part-way in**, at the offset it has
  already reached, so a phone picked up at T-4 still hears the horn on T-0.
- A nudge or a re-sync moves T-0, so the schedule is torn up and rebuilt. A deadline
  that moves by less than 0.3 s is poll jitter rather than the crew, and is ignored,
  because rescheduling would restart a clip mid-word.
- T-0 is both the horn and the moment the mode becomes racing, so the transition out
  of pre-start must **not** stop the audio. A reset must. Those are different exits
  from the same state and the code distinguishes them, because cutting the gun off at
  the instant it fires would lose the one cue nobody can miss.
- The audio clock **stops while the page is in the background**, which iOS does as
  soon as the phone locks. Everything already scheduled is then late by however long
  the phone was away, so coming back to the page throws the plan away and rebuilds it
  against the clock as it now stands. A phone in a pocket from T-8 to T-2 still gets
  its gun on time.

The clips are generated by `scripts/gen_audio.py` into `static/audio/`, as mono AAC in
an MP4 container: the same choice as `wake.mp4`, for the same reason, which is that it
is what iOS will play without argument. The whole set is about 140 kB. They are
committed, because the Pi has no internet and no TTS engine (CLAUDE.md), and generated
rather than recorded only because no one has recorded them; the manifest records the
timings so real recordings can replace them as long as the numbers stay on the second
and the horn stays at its offset. The voice is whatever the generating machine has,
which is an American one, there being no en-AU voice installed. Numbers survive the
accent.

The horn is synthesised rather than sampled, so there is nothing to licence: a
fundamental with three harmonics, fast attack, slow release, which is the shape of
something with a diaphragm in it and does not sound like a test tone.

If a clip fails to load or decode, the page falls back to the tone at each minute and
each of the last ten seconds. A start with a crude beep is a start; a silent gun is
not, and a codec that one phone refuses is exactly the failure that would otherwise
show up for the first time on the water.

### 10.2 The ringer switch, and the audio session

iOS plays Web Audio in the **ambient** audio session, which the hardware ringer switch
mutes. A media element plays in the **playback** session, which ignores it. A phone in a
pocket on silent is the normal case on a boat, so as first built the countdown could be
lost with nothing on the screen to say so, which 10.1 is explicit is the one outcome not
worth having.

Measured on the two devices the boat actually carries, with the switch set to silent
each time, using `static/audio-check.html`:

| | iPhone | iPad mini 3, iOS 12.5.7 |
| --- | --- | --- |
| `window.AudioContext` | present | **absent**, prefixed only |
| `navigator.audioSession` | present | absent |
| Web Audio alone | silent | silent |
| media element alone | audible | audible |
| after `audioSession.type = "playback"` | **audible** | silent, nothing to set |
| after looping near-silence | **audible** | **audible** |

Two conclusions, and the implementation is the shorter of them:

1. **Both routes out of the ambient session work where they exist**, so prefer the
   official one and fall back: `navigator.audioSession.type = "playback"` from Safari
   16.4, otherwise a looping media element playing real audio. The iPad has no
   `audioSession` at all, which is why the fallback is not optional.
2. The iPad reporting no `window.AudioContext` is a separate finding and a more basic
   one. Before that was fixed the context was never constructed there at all, so the
   countdown was silent regardless of any session, and so was the tone that 10.1
   promises as the fallback. The switch and the constructor were two faults wearing the
   same symptom, which is why the first fix looked like it had not worked.

**The session is held only while a countdown is armed.** Leaving the ambient session
interrupts whatever else the phone is playing, so the app takes it when the timer is set
and gives it back once the horn has finished: ten minutes of no music before a start
rather than an afternoon of it. The release deliberately does not happen on the mode
change, because T-0 is both the horn and the moment the mode becomes racing (10.1), so
releasing there would cut off the one cue nobody can miss. It waits out the tail of the
final clip, taken from the decoded buffer rather than guessed. An abandoned countdown
releases at once.

Scheduling is untouched by any of this. The clips still go to the audio clock, because
the horn has to land on T-0 to the sample and a media element cannot be scheduled that
finely (10.1). Only the session they play into changes.

`static/silence.wav` is half a second at one least-significant bit, about -90 dBFS.
Near-silence rather than silence, because some iOS versions decline to promote the
session for a stream of digital zeros, and hand-written from the standard library
because there is no ffmpeg on the Pi and a WAV header needs no encoder. It carries no
`muted` attribute, which is the whole point and the reason `wake.mp4` cannot do this
job: that one is muted on purpose, for the screen lock, and a muted element promotes
nothing.

`static/audio-check.html` is kept. It is not a screen and not in the navigation, just a
URL, and it exists because there is no Apple device anywhere near the Pi: it reports
which `AudioContext` the device has, the state it reaches, the fetch status and
Content-Type, the decoded duration, and then plays one clip through Web Audio and
through a media element so the two can be compared. The table above came out of it in
one pass, after three rounds of guessing had not settled it.

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

Test coverage for this is non-negotiable. At minimum, replay a course that crosses
the line while racing and confirm exactly one finish fires, on the correct fix.

**Done, for Frostbite Course 3.** `tests/test_race.py` replays the 16 August 2026
recording fix by fix. The engine makes all nine leg advances in printed order,
ignores three crossings of the line while racing (the 13:30 start and both roundings
of 32A, which is the outer end of this line as well as a course mark), and finishes
once, at 15:16:01, at parameter 0.17 along the line, for an elapsed time of 1:46:01
counted from the gun. Course 1, with more crossings again, is still worth adding when
it is transcribed.

Two things that test earned, both of them corrections to this document rather than to
the code:

- It is what caught the misplaced inner start mark, by failing to finish a race that
  plainly finished. A detection rule that looks wrong is worth suspecting the data
  over: here the engine, the rule and the parameter test were all correct.
- Only three crossings, not four. The count is a property of the course and the day,
  not of Course 1 specifically, so do not read the number in an earlier draft of this
  section as a requirement.

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
`shortened_at` in `courses.json`.

**Done**, for eleven of the twelve Sunday courses, by `scripts/extract_courses.py`.
One correction to the method as first written: the candidate legs are not all of
them. Flag S means the next pass through the **line** ends the race, so only legs
that target `club-32a`, the line's outer end, can be where a shortened race
finishes. Solving by nearest running total across every leg instead put Div II
Course 2's shortened finish at Sanders, out in the middle of Melville Water, purely
because that course's full distance is 2.8 per cent out and the error moved the
nearest total by one leg. Constrained to line crossings it resolves cleanly, or
declines to.

Where the printed figure matches no line crossing within 3 per cent, the figure is
recorded in `shortened_distance_nm` and `shortened_at` is left null, with the
residual written into `shortened_note`. Three do not resolve, and all three are
courses whose full distance does not reconcile either, which is the expected
correlation rather than a separate mystery. A guess about where a race ends is worse
than an admission that it is not known, and the crew has the Shorten control either
way.

One course in the document, Sunday Div III Course 2, never returns to the line
before finishing. It is also the only Sunday course with no printed shortened
figure, which is the same fact from the other side: there is no crossing to shorten
it at.

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

**How this is wired, because getting it wrong is silent.** There is one queue, in
`store.py`, and whoever drains it publishes. `_queue` holds every transition whatever
caused it, which is the point: a transition can come from a command, from a fix, or from
the clock reaching T-0 while a page happens to poll, and the third was being dropped
before the queue existed. `MqttClient` drains after each message, so a fix-driven event
publishes at once on the paho thread rather than waiting for a browser to poll (section
2); `app.py` drains on every request. Because the drain empties the queue, each event is
published exactly once no matter which gets there first.

Two ways that has already been wrong, both worth stating because neither shows up as an
error anywhere:

- **`EVENT_PUBLISHER` was never connected.** `create_app` defaulted it to `None` and
  `main` never set it, so `app.py` logged every queued transition and published none of
  them. Only fix-driven events reached the broker, down a second path. That silently
  emptied this section of most of its value: `select`, `timer`, `start`, manual
  `advance`, `reset` and `shorten` went nowhere, and the manual ones are the most
  diagnostic of the lot. Every other test in `test_api.py` set the publisher by hand,
  which is exactly why none of them noticed; the test that pins it now goes through
  `main` itself.
- **Publishing from both paths sends everything twice.** `store.on_position` queues its
  events *and* returns them, so handing the returned copy straight to `publish_event`
  while `app.py` also drained the queued one would double every rounding and finish.
  That is why `MqttClient` drains rather than passing `on_events` to `handle_message`.
  The parameter stays on `handle_message` because it is how a test observes the events
  one fix produced with no drain and no broker.

One consequence for the API: a POST reports the events it caused from `apply_race`'s own
return, not from the drain. The paho thread drains roughly once a second, so it can
legitimately empty the queue between a command and its response, and `app.js` feeds that
array to `announce()`, so an empty one would silently lose the crew's notice.

## 12. Map page

No internet means no tile server. Draw it as SVG from the app's own data: marks,
the current course legs with rounding side, the start line, and the boat with a
heading vector. Generated from `marks.json`, so a new mark appears automatically.

Three config files feed the map, all EPSG:4326 GeoJSON, all regenerable from the
scripts named below and all safe to ship to the browser:

| file | what | raw | gzipped |
| --- | --- | --- | --- |
| `marks.json` | marks, the start line, course legs | 62 kB | 7 kB |
| `coast.json` | land polygons under everything | 133 kB | 34 kB |
| `depth.json` | contours, four depth bands, and the foreshore | 767 kB | 168 kB |
| `structures.json` | jetties, marinas, bridges, groynes | 216 kB | 26 kB |
| `navaids.json` | the DoT navigation aid register | 220 kB | 23 kB |

nginx gzips them, so the whole map costs 258 kB over the wire. If `depth.json`
ever hurts on the iPad, split the region stage into its own file and load it only
when zoomed out; which stage a feature came from is recoverable from `coverage`.

Draw order, bottom to top: depth bands, depth contours, land, structures, navaids,
then marks and course.

Every one of them is regenerated by a `scripts/gen_*.py` that caches its download,
so a rerun needs no internet. They share one extent and one licence story, and the
generated outputs are committed while the downloaded inputs are gitignored.

Default view is fit-to-current-course, with zoom out to full extent as the
deliberate gesture rather than the default. At full extent the marks cannot be
labelled legibly on a phone.

`marks.json` contains 131 marks inside the racing-area bounding box, of which 20
are used by current PFSYC courses. The rest carry `used_in_courses: false` and are
map context, and also mean a course-sheet change next season is unlikely to need
new mark data.

### 12.1 The page, and the three decisions behind it

The data was finished before the page was started, so these were settled first rather
than discovered.

**Its own page at `/map`, not a fourth panel on the race screen.** The panel would have
come free: the race page already polls `/api/state` at 2 Hz, which is where the boat's
position is, and it already carries the navigation, the theme, the wake lock and the
mode-follows-server behaviour. Against that, a map is 90 kB of chart data and a body of
projection and gesture code that a crew watching the countdown never needs, and the race
page's own weight is the thing that keeps that screen honest. A separate page it is.

That has a cost, and it should be paid deliberately rather than discovered: **it is the
third document that has to agree with the other two.** The pair already do, and there are
tests holding them to it: `test_both_pages_carry_the_same_three_screen_navigation`,
`test_each_page_can_reach_the_other`,
`test_both_pages_navigate_by_script_so_ios_keeps_them_in_the_web_app`, and the two halves
of `test_the_navigation_is_never_pushed_off_or_covered`. Each of those becomes a
three-way check. So do the things a page needs to be part of the app at all: the
`apple-mobile-web-app-capable` meta, the manifest link, the apple-touch-icon, the
`location.assign` navigation, and a `clamp()` fallback on every sized thing.

`map.html` should therefore **not** copy `hud.html`'s self-containment. That page inlines
its CSS and JS for one reason, recorded in 9.1: it was ported from Node-RED close to
verbatim so the two could be compared side by side. The map has no original to be
compared against, so it takes `static/app.css` and a new `static/map.js`, and only the
head block and the navigation are duplicated markup.

**Zoom out has two steps: the racing bbox first, the coast extent second.** The default
is fit-to-current-course. One gesture out gives the `marks.json` bbox, 10.3 by 7.9 km,
which is PFSYC and the other Swan clubs and the scale every course is sailed at. A second
gives the whole `coast.json` extent, about 56 by 51 km, Guildford to past Rottnest and
south over Garden Island. Two levels rather than one because the coast data was
deliberately generated wider than the racing area for ocean races and the island
anchorages, and a single zoom-out would have to pick between making that data unreachable
and making the ordinary case illegible: at full coast extent the river is a thin line and
no mark can be labelled.

**At night the depth bands go to dark red, keeping shallowest-darkest.** The chart blues
cannot stay: a pale `>4 m` at `#d8e9f5` covering most of the screen is the opposite of
what a night theme is for, and this page is mostly water. Hiding the bands and keeping
only the contours was the alternative and loses the at-a-glance sense of where the deep
water is, which is most of the value. So three dark reds in the same order, which keeps
the one property that carries meaning. It does diverge from the chart convention exactly
where a crew might compare against paper, and that is the accepted cost, mitigated by the
ordering being preserved and by the theme being a deliberate manual switch (9.7) rather
than something that happens to them.

### Build order for the page

1. **Plumbing.** Nothing serves `config/*.json` to a browser today; `/race/config/...`,
   `/race/api/map` and `/race/static/coast.json` are all 404. A route serving the four
   documents by whitelisted name, and `gzip_types` turned on in nginx, which is off:
   `gzip on` is set but the types list is commented out, so nginx's default of `text/html`
   alone applies and JSON goes out uncompressed. The 88 kB in the table above is real
   only once that line is uncommented. Until then it is 431 kB.
2. **The projection, and it has to be exact.** A JS mirror of `nav.py`'s `enu()`: WGS84
   meridian and prime-vertical radii, scale fixed at the origin's latitude so the map
   stays linear. Project differently from the engine and the boat sits off the marks and
   the start line stops agreeing with the geometry finish detection uses. Test it against
   a fixture generated from `nav.py` itself, the same way section 6 uses the register's
   MGA94 columns as free fixtures for the same function.
3. **The static chart.** One `<svg>`, viewBox in projected metres, path data built once so
   zoom never re-projects, `vector-effect: non-scaling-stroke` for the strokes. Draw order
   as above: bands, contours, land, then marks and course. Fetch the three documents on
   first show rather than on load.
4. **View control.** Fit-to-course by default, the two zoom-outs above, pan and zoom by
   moving the viewBox alone. **Touch events, not Pointer Events**: those need Safari 13
   and the boat's iPad is on 12, which is the same list `clamp()` and flexbox `gap` are
   already on, and the one every pan-and-zoom recipe will get wrong.
5. **The live overlay.** Boat and heading vector off `/api/state`, course legs with the
   next mark emphasised, the rounding symbols reused rather than redrawn. A fix older
   than 5 s hides the boat rather than drawing it where it is not (9.5).

   **Three leg states, not two.** The leg being sailed, the leg after it, and the rest.
   The middle one was asked for after watching a replay, and it is the same thing 9.2
   already puts in the secondary row with its transit angle and leg type, because that is
   what decides sail selection and which way to round before the crew gets there.

   It differs in kind as well as in degree, dashed where the current leg is solid, and
   that is not decoration. `--sog` and `--dist` are the same DodgerBlue, so the current
   leg is told apart by width and opacity alone; a third step of the same treatment would
   be three widths of one line to read at a glance on a wet screen, on a course that
   crosses itself ten times. The dash is longer than the one on the no-cross lines, since
   a glance takes the pattern before the colour and those two mean nothing like each
   other (11.3).

   **The map does not follow the boat**, and that was decided rather than overlooked. Fit
   returns to the course, and a chart that re-centres itself under a finger mid-pinch is
   worse than one that stays where it was put.
6. **Legibility.** Caveats in the document rather than only in a loader comment:
   crowd-sourced banks, nothing about sandbanks, the datum and which way its error runs,
   orientation only and not for navigation. On the page at first and now the chart's own
   description, for the reason 12.2 gives.

   Labels turned out to need two mechanisms, not one. **A zoom threshold alone is not
   enough**, and that is the thing worth carrying forward. At the racing extent the twenty
   course marks overlap into an unreadable mat, so a rule that showed labels above some
   zoom and nothing below it would trade one unusable view for another, and the view it
   would have sacrificed is the one the crew uses to see the whole race area.

   So thresholds decide who is *eligible* and collision thins the eligible to what fits.
   Nothing is labelled beyond 50 m per pixel, which is the coast extent; the 111 context
   marks become eligible below 1 m per pixel; course marks are always eligible and are
   simply thinned. Four placements are tried per label, so one blocked on a side goes to
   the other, and an off-screen placement is rejected like any other collision, which is
   what keeps names off the edge.

   Priority decides who survives: the mark being sailed to, then the rest of the course,
   then context. Without an order, which twenty of a hundred and thirty-one names survive
   would be an accident of array order and the one the crew needs could be the one
   dropped. The sort is stable, or labels flicker between poll ticks.

   Widths are **estimated, not measured**. getBBox on 131 text nodes forces a layout on
   every view change, and this page had already to be made faster for the iPad once. The
   estimate models the halo separately from the characters, because `mark-label` paints a
   3 px stroke behind the text and that constant is proportionally far larger for "Bond"
   than for "Bricklanding A": one per-character figure cannot fit both ends, and the first
   attempt at 0.58 let seven pairs overlap.

   Measured at 375 wide, counting real overlaps rather than intended ones: 10 labels
   fitted to a course, 18 at the racing extent, none at the coast extent, no overlapping
   pair at any zoom, and nothing placed outside the view.

   **Two things about the labels then went wrong on the water at once**, reported as the
   names going blurry as you zoom in, on all three devices, which is what said it was not
   one machine's rendering.

   `stroke-width: 3px` inside an `<svg>` is three **user units**, not three screen pixels.
   So the halo was three metres wide and fixed to the ground: measured at 0.82 px across
   at the fitted view and growing without limit as you zoom, until it swallowed the
   eleven-pixel glyphs. It is set as an attribute on the layer now, against the current
   scale, exactly as the font size already was, and measures 3 px across a nine-fold zoom
   range. It cannot go back into CSS even as a fallback, because CSS beats a presentation
   attribute and would override the inherited value. `vector-effect: non-scaling-stroke`
   is how the paths and circles stay constant and is deliberately not used here: its
   support on `<text>` has never been dependable in Safari, which is what the boat runs.

   The larger half was colour. The label used `--ink`, which is white because the race
   screen is a black screen, and the halo is white because the chart is pale. White text
   with a white halo over a `>4 m` band of `#d8e9f5` is a smear and not a name, and this
   was true from the moment the labels were drawn; widening the halo to its proper size
   only made it impossible to miss. The map has its own `--map-label` now, dark by day and
   light by night, and a test asserts the pair can never collapse in either theme.

### Shoreline

Done, in `config/coast.json`, generated by `scripts/gen_coast.py`. 133 kB raw,
34 kB gzipped, one MultiPolygon of 57 parts, EPSG:4326 at 5 decimal places.

Do not trace the shoreline off the Geng course marks chart, even though section 6
now keeps a copy in `docs/reference/`. Two reasons, and the first is the one that
matters: it is marked not for navigational use, so a coastline derived from it
would carry that caveat into the one place on the display that looks like a chart.
The second is that a derived shoreline shipped to the browser is redistribution of
a copyright work, which internal reference use is not. OSM is the source.

**It emits land, not water.** An earlier version of this section said to dissolve
`natural=water`. That works inside the river and fails the moment you leave it,
because OSM does not tag the open sea: everything west of the Fremantle coastline
would come out as a hole in the map. Instead the extent is split by the coastline
and the resulting faces are classified from six known open-water seed points. Land
is whatever no seed reaches, which picks up every island for free.

Two things that will waste a morning if rediscovered the hard way:

- Coastline ways are individually short and none of them crosses the extent alone,
  so splitting the extent by them one at a time does nothing. Dissolve and merge
  first. Merged, the mainland coast is a single 109 km string that enters north of
  the extent and leaves south of it, which does cut the extent in two.
- Islands arrive in two different OGR layers. Open coastline ways land in `lines`;
  closed ones (Rottnest, Garden Island, Carnac) are auto-polygonised into
  `multipolygons`. Both have to go into the cutting set or the sea swallows the
  islands.

The extent is deliberately wider than the `marks.json` racing bbox, so ocean races
and the island anchorages need no regeneration:

```
south -32.32   west 115.40   north -31.86   east 116.00
```

That reaches Guildford at the top of the navigable Swan, out past Rottnest, and
south over Garden Island and Cockburn Sound. Simplified with Douglas-Peucker at
10 m in EPSG:7850; the tolerance is set for a zoomed-in single-bay view at roughly
8 m per pixel, not for the full extent. Water polygons under 5000 m squared are
dropped, which removes swimming pools and ornamental ponds but also punches out the
Rottnest salt lakes.

Validation that is worth keeping: every one of the marks in `marks.json` must fall
in water. `gen_coast.py` asserts it and exits non-zero otherwise.

Caveats to keep in the loader comment: OSM banks are crowd-sourced and this is
orientation only, not navigation. It says nothing about sandbanks, which is where
the actual trouble is on Melville Water. Point Walter spit is submerged at higher
tides and its presence in OSM depends entirely on which imagery the mapper traced,
so it must not be read as reliable.

### Depth contours

Done, in `config/depth.json`, generated by `scripts/gen_depth.py`. The 2 m, 5 m and
10 m contours, the four bands they divide the water into, and a fifth class for
water the survey never reached. 767 kB, 927 features, covering the whole mapped
region. This is the line that actually changes how a leg is sailed.

Two stages, because the river deserves more resolution than the ocean and the whole
extent at 2 m would be 727 million cells:

| stage | source | source res | grid | where |
| --- | --- | --- | --- | --- |
| `river` | SC2010 multibeam BAG | 1 m | 2 m | Melville Water, Freshwater Bay, Blackwall Reach, the Canning |
| `region` | 5 DoT composite surfaces | 5 m | 10 m | Rottnest, Gage Roads, Owen Anchorage, Cockburn Sound, Warnbro, the northern beaches |

The river wins where they overlap, and the region is clipped out of the river
footprint so nothing is drawn twice. The region tiles are Rottnest, Perth,
CockburnSound, Warnbro and OceanReef; they abut rather than overlap and between
them tile the metro coast. Nothing extends further up the Swan or Canning than the
BAG already reaches.

Feature thresholds are per stage. The river is looked at zoomed in, so it keeps
detail down to 400 m squared and 40 m of line. At 10 m the region generator emits
thousands of short offshore fragments that are noise at the scale anyone will view
them, so it drops anything under 8000 m squared or 250 m, which took the file from
3.7 MB to 1.9.

#### Swath-edge cleanup

Multibeam outer beams are noisier than the middle of a swath, by more than the gap
between two contour levels. Where a band boundary crossed a swath edge it came out
as a row of comb teeth, and the survey footprint itself came out fringed with thin
fingers of coverage. Three cleanups fixed it and took the file from 1.9 MB to 767 kB,
so roughly 60% of that file was artefact:

- **A small median, 3 cells**, for isolated spikes.
- **A Gaussian**, sigma 4 cells on the river (8 m) and 2 on the region (20 m). This
  does the actual smoothing.
- **Opening then closing of the surveyed footprint**, radius 4 cells on the river
  and 2 on the region. Opening drops the thin fingers, closing then fills the pits
  opening leaves behind. The river footprint went from 3 polygons to 1 and the
  region from 39 to 14.

**Do not widen the median instead of using the Gaussian.** A median is
edge-preserving, which on a gentle gradient means it does not smooth, it
*terraces*: it turns a slope into a staircase of plateaus, and contouring a plateau
edge gives a boundary that is a regular sawtooth. Going from 9 to 13 cells made the
gentle slope south of the Melville channel visibly worse, which is how this was
found. The Gaussian preserves the gradient.

Guard against over-smoothing: the marks-by-band tally barely moves. Before any of
this it was foreshore 35, mid 37, deep 43, deepest 16; after, 36 / 38 / 40 / 17.

One thing that is **not** an artefact and was left alone. The band boundary along
the south edge of the Melville channel stays intricate. A transect across it shows,
after removing the broad slope, a residual of 1.08 m standard deviation and 4.5 m
peak to peak at roughly a 300 m wavelength: that is real bed structure, not noise.
The local mean depth is -8.83 m, so the 10 m level sits only 1.17 m below it and the
bed genuinely crosses that level back and forth. An intricate boundary there is the
data telling the truth about a marginal channel.

Bands are shallowest-darkest, which is the chart convention and puts the emphasis
on the water that can hurt you:

| band | depth below AHD | colour |
| --- | --- | --- |
| `foreshore` | unsurveyed | `#a8c66c` |
| `shallow` | 0-2 m | `#1f5c8b` |
| `mid` | 2-5 m | `#4e8fbd` |
| `deep` | 5-10 m | `#92c0dc` |
| `deepest` | >10 m | `#d8e9f5` |

Four bands, not three. An earlier cut used 2 m and 4 m only, and its top band held
70% of the marks, which is another way of saying it carried no information. On the
2/5/10 split the marks land 4 shallow, 62 mid, 48 deep, 16 deepest, which does
separate Melville Water from the Blackwall Reach channel.

Contour lines are carried separately from the bands so they can be stroked on their
own: 2 m solid and heaviest because it is the one that matters, 5 m dashed, 10 m
dotted.

**Not from the AHO ENC**, which an earlier version of this section assumed. Four
sources were tried and three cannot work, so do not spend the day again:

- `AHOENCSeries` is a cached S-52 tile package. Its own service description says it
  is published from a static tile package. It is a picture. There is no vector in
  it.
- The DoT rasters in the QGIS project are pictures too, named `..._Image_...img`
  literally. Identifying a pixel returns RGB, and the legend is three raw bands
  with no published depth mapping to invert.
- `Perth_5m.tif` is a real value grid, reachable because the SLIP WA_Bathymetry
  MapServer carries the DoT survey index as actual feature layers with download
  URLs. But it is the *coastal* survey: 74% of the racing box is nodata, with
  Freshwater Bay, Mosman Bay, Perth Water, Point Walter and Matilda Bay all empty.
- `SC.zip` PointData is singlebeam track lines hugging the foreshore. Gridding it
  alone invents shallow water in the channel: it puts Blackwall Reach, really 22 m,
  at 1.9 m.

What works is `SC20100413_Mean.bag`, 1 m multibeam of the Swan and Canning, CC BY
4.0, unrestricted, found through the survey index behind the DoT bathymetry web app
(`services6.arcgis.com/.../Survey_index_linkedbagfiles`). All 131 marks fall inside
it. Reading it needs `GDAL_DRIVER_PATH` pointed at QGIS's `gdalplugins`, because
QGIS ships the BAG/HDF5 driver but does not put it on the driver path.

**Vertical datum: AHD, roughly mean sea level. NOT chart datum.**

An earlier version of this section said Low Water Mark, 0.756 m below AHD, and
called the contours conservative. That was wrong in the unsafe direction, so the
evidence is recorded here rather than the conclusion alone:

- The DoT survey index records SC20100413 as `VertDatTyp` "Low Water Mark" with
  `AHD_Diff` 0.756 `AHD_Rel` BELOW. Read naively, that says the grid is on LWM.
- It is not. `SC.zip`'s README states in words that its singlebeam text files are
  metres relative to AHD. BAG minus those points is a median of **-0.042 m** over
  16561 shared cells. On LWM it would be near +0.756.
- BAG minus `Perth_5m` is **+0.002 m** over 627364 cells, and the four region tile
  seams agree to within **0.011 m**, so every source in this product shares one
  datum.
- So `VertDatTyp` names the datum the survey was *observed* against. `AHD_Diff` is
  the correction that has already been applied to the delivered grid.

**Consequence, and it is the unsafe direction: at low water there is LESS water
than these contours say, by up to about 0.76 m at LAT.** A charted 2 m contour is
not the same line as this 2 m contour. Set `DATUM_SHIFT` to `+0.756` in
`gen_depth.py` to move everything onto approximately LAT and get the
chart-conservative version instead.

The lesson worth keeping: a datum field in a metadata table describes the survey,
not necessarily the file. Two independent numeric comparisons settled it where
reading the metadata did not.

**`foreshore` is not a depth, and it is green on purpose.** The multibeam stops
where the survey vessel could float: the shallowest sounding in the BAG is -1.10 m,
so the strip between that and the bank was never measured, and neither were the
flats at Alfred Cove, Pelican Point and Matilda Bay. That is 2.55 km squared, 8.7%
of the water in the footprint.

An earlier cut interpolated across the gap and let the 0-2 m band run to the bank,
which drew invented data in the darkest, most alarming blue. The cut before that
left it as bare canvas, which was worse: unsurveyed rendered almost identically to
the palest `deepest` band, so "we have no idea" and "plenty of water" looked the
same. Both are the wrong failure on a boat.

It is now its own class, coloured the way a paper chart and every commercial
plotter colour an intertidal area; `docs/reference/NavigationMapExample.png` is the
plotter screenshot this was matched against. That is also what the water actually is here:
shallower than a survey vessel can float is, on the Swan, the drying fringe. The
gap is still interpolated internally, because contours drawn against a cliff edge
kink badly, but the interpolated area is pulled back out afterwards and emitted as
`foreshore`.

The rule differs by stage, and it has to:

- **river**: everything unsurveyed inside the BAG footprint. The BAG box hugs the
  river, so unsurveyed-inside-the-box *is* the fringe and the flats.
- **region**: within 400 m of the coastline AND within 1500 m of real soundings.
  Two constraints because each alone failed. Buffering the survey edge drew green
  rectangles and straight lines across open ocean, since a survey edge is partly
  just where a 25 km raster tile stops. Anchoring to the coastline alone then
  painted Herdsman and Lake Monger green, being unsurveyed water within 400 m of
  their own shores. Requiring both leaves the coastal fringe and drops the inland
  lakes, while keeping the Rottnest salt lakes, which are a few hundred metres from
  a sounding and are at least water you can see from a boat.

Two things this forces, both worth knowing:

- The survey edge is simplified **once** and both sides are cut with that same
  line. Simplifying the bands and the foreshore separately after clipping leaves
  hairline white slivers along the shared boundary, because each side rounds it
  its own way.
- 35 marks fall in `foreshore`. Under the interpolating version they showed as
  0-2 m, which was a number the data never supported.

`coverage` in the file gives both stage footprints: `river_2m` 115.7533 to
115.8594 E, -32.0431 to -31.9589 S, and `region_10m` the full mapped extent.
Outside a footprint there is no depth product at all, which is a different thing
from `foreshore`, and the map should not imply coverage there. Perth Water above
about 115.859 E is outside the river stage, and the region tiles do not reach up
the Swan, so the upper river has no depth and correctly shows none.

Validation, and it is independent of both datasets: marks named SPIT sit in
foreshore or water under 5 m 79% of the time, against 48% for every other mark, and
not one of them reaches the `deepest` band where 16 of the others sit. 12 of the 29
are in `foreshore`, which is the expected place for a mark on a spit. If a
regeneration ever breaks that relationship, distrust it before you trust it.

Caveats for the loader comment: surveyed 2010, BAG uncertainty 0.25 to 0.30 m, and
Swan sandbanks move. Orientation only, not for navigation.

### Jetties and water structures

Done, in `config/structures.json`, generated by `scripts/gen_structures.py`. 216 kB,
1022 features. OSM again, same extent and licence as `coast.json`, so the two line
up exactly and the loader can treat them as one basemap.

These are what the crew actually steers by. A jetty is a better landmark than a
buoy: big, fixed, and lit at night. `marks.json` covers the racing marks and a few
navigation piles and says nothing about the built edge of the river.

| kind | n | source tag | colour |
| --- | --- | --- | --- |
| `jetty` | 871 | `man_made=pier`, lines and areas | `#6b5b45` |
| `bridge` | 66 | see below | `#3f3f3f` |
| `groyne` | 37 | `man_made=groyne` | `#7a7a6a` |
| `slipway` | 18 | `leisure=slipway` | `#8a7f6a` |
| `marina` | 16 | `leisure=marina`, as areas | `#9aa7b1` |
| `breakwater` | 14 | `man_made=breakwater` | `#5a5a5a` |

The marina layer is quietly the most useful thing in here: it resolves to the club
register, PFSYC, RPYC, RFBYC, SoPYC, Nedlands, Claremont and East Fremantle.

**Bridges cannot be selected by tag.** OSM has 1886 bridge ways in this extent and
almost all are freeway overpasses. Intersecting them against the water from
`coast.json` still leaves 152, because every culvert over a drain counts. A bridge
also has to span at least 30 m of water, which lands on 66 and keeps the Narrows,
Canning, Stirling, Matagarup, Queen Victoria Street, Garratt Road and the rail
crossings. Note OSM names those by the road, so the Narrows is `Kwinana Freeway`.

Jetties are **not** clipped to the waterline. A jetty that stops at the water stops
being recognisable from a boat.

Simplify is 1 m here, against 10 m for `coast.json`. A jetty is 3 m wide and 40 m
long, so the coast tolerance would erase it. This is also why `gen_structures.py`
uses plain `QgsGeometry` rather than the processing framework: one layer holding
points, lines and polygons cannot be fed to `native:reprojectlayer`, which fails
with "Could not create memory layer".

Deliberately excluded: `seamark:type=mooring` (183 mooring buoys, clutter and not
fixed structure), `wreck`, and `berth`. Lights and beacons were briefly here too,
as OSM `man_made=lighthouse` plus a handful of seamarks, and have moved to
`navaids.json`; see below for why.

Same caveat as the shoreline: crowd-sourced, orientation only, not for navigation,
and a private jetty may have been rebuilt or removed since it was mapped.

### Navigation aids

Done, in `config/navaids.json`, generated by `scripts/gen_navaids.py`. 220 kB,
**785 aids** across the whole mapped region, not just the river.

Source is **Navigation Aids DoT (DOT-004)**, the authoritative WA register, CC BY
4.0, IALA buoyage system A. The project already carried this layer as a WMS
picture; the same service exposes it as a real point feature layer. Note the REST
layer id is **5**, not the 13 the WMS uses.

**Not OSM.** Its seamark coverage here is threadbare: the whole extent, Fremantle
and Rottnest and Cockburn Sound included, yields 9 lateral beacons, 11 minor
lights, 3 major lights and 1 cardinal. DoT has 435 beacons, 329 buoys, 5
lighthouses and 52 leading marks. For the aid network specifically OSM is not a
serious source, which is the opposite of the finding for jetties.

| kind | n | | kind | n |
| --- | --- | --- | --- | --- |
| `beacon_port` | 148 | | `buoy_starboard` | 36 |
| `beacon_starboard` | 126 | | `buoy_port` | 26 |
| `buoy_other` | 123 | | `beacon_other` | 26 |
| `buoy_yacht` | 67 | | `beacon_cardinal` | 25 |
| `leading` | 52 | | `buoy_cardinal` | 22 |
| `buoy_special` | 45 | | `ais` | 19 |
| `light_major` | 37 | | `light_minor` | 18 |
| `lighthouse` | 5 | | rest | 10 |

510 of the 785 are lit, carried as a `lit` boolean.

**Leading marks are why this has the shape it does.** 52 of them, and **42 are on
land**: `Beacon Lead Front Land Lit` and `Beacon Lead Rear Land Lit` are transits
you line up and steer down, so nothing here is clipped to water and the land ones
are kept deliberately. They are orange in the styling because they are the marks
you line up rather than pass. Longreach, Parakeet and Parker Point on Rottnest,
Fremantle Inner Harbour, Kwinana and Careening Bay all have them.

The five lighthouses are North Mole, South Mole, Woodman Point, Bathurst Point on
Rottnest, and the Woodman Channel directional light.

**Overlap with `marks.json` is real and is flagged, not dropped.** 105 aids sit
within 25 m of a mark in the register, mostly the 67 club-owned `Buoy Yacht`
entries, since DoT records the racing buoys too. Every feature carries `dup_mark`,
the mark id or null. The map page should draw an aid with `dup_mark` set only once,
and `marks.json` should win because it carries the rounding and course data.

ORIENTATION ONLY, NOT FOR NAVIGATION. This is a register extract, not a chart: no
light characteristics, no sectors, no ranges. Temporary Notice to Mariners is a
separate DoT dataset, DOT-034, and is not consulted.

### Styling the QGIS copies

`scripts/apply_qgis_styles.py` writes a default style into each GeoPackage's
`layer_styles` table, so adding a layer in QGIS comes up correctly coloured with no
hand-styling, and the desktop colours stay identical to the ones the app draws
with. Both come from the same dicts in the generators.

A layer already in an open project keeps the renderer the project saved, so after
changing the bands, an existing layer needs Properties, Style, Load Style, From
database, or simply removing and re-adding it.

### 12.2 What the strip says, and the one zoom control

Two changes after a season of using the page, and both come from the same observation:
the map was the screen the crew sat on, and the reason they left it was always a single
number.

**Four readings, in the space the caveat had.** The disclaimer had been read. It is the
same sentence every time the screen is opened, it never changes, and it was taking the
one strip of the page that could carry data. So it moved from a paragraph under the chart
to the chart's own `<desc>`, pointed at by `aria-describedby`: still in the document,
still saying exactly what 12 and the two source sections say, still there for anything
reading the page out. None of the data changed and none of the caveats are withdrawn.
That was the crew's call to make about their own boat, and it is recorded here because the
next person to read section 12 will wonder where the line went.

Which four depends on what the boat is doing, and the sets are the crew's, in the order
they are tested in:

| state | the four readings |
|---|---|
| racing | distance to the next mark, off the bow, TWA, TWS |
| motoring | RPM, current, motor temperature, controller temperature |
| otherwise | SOG, COG, TWA, TWS |

Racing is tested **before** motoring, so motoring inside a race still shows the race.
That ordering is the point of having one: the two conditions are not exclusive, the boat
having an engine and a rule book that permits using it.

Two details worth writing down. The third set's second reading is COG, not a bearing:
outside a race there is no mark to take a bearing to, and the boat's own course is the
only bearing there is, so it is labelled COG and not BRG. And every reading keeps the
colour it has on the other two screens. The wind and motor variables only existed inside
`hud.html`, which is self-contained, so they are copied into `app.css` rather than chosen
again, and the night theme defines all of them in reds; a fifth palette on a third page
would undo the whole colour language. A test holds the copies to each other.

The strip is `flex: 0 0 auto` and never wraps or scrolls. The chart is the flexible thing
on this page and four numbers are not, and a reading that has to be hunted for is no use
on a moving boat. The cells are in the markup rather than built, so the strip is the same
height before the first poll as after it and the chart is never resized by data arriving.
Measured at 320, 375, 768 and 1400 px: nothing overflows, no label clips, and the strip
is 42 to 64 px.

**One button where there were two.** `Fit` and `Out` became a single control that names
the extent it is showing and cycles to the next:

| name | what it is | span |
|---|---|---|
| Race course | the course being sailed, or a race-sized region around the boat | ~2 to 5 km |
| River | `marks.json`'s bbox, every mark the club races to | 10.3 x 7.9 km |
| Everything | `coast.json`'s bbox, the ocean races and the island anchorages | 57 x 51 km |

Once the chart has been pinched or dragged the button says `Fit` and comes back to the
extent it names before it will advance. That keeps the one property of the old pair worth
keeping, that the tap which recovers a map dragged somewhere useless is always the next
tap, and it is also the only text on the page that says the view is no longer any of the
three, which is what the old `map-scope` label was for. It wraps at the outermost: with
one button there is no other way back in, and a control that does nothing when tapped is
worse on a wet screen than one that moves.

With no race selected, the innermost extent is a race-sized square with the boat in the
middle. It used to be the racing bbox, which is the wrong view by a factor of three: 10 km
across, where the twenty-three courses in `config` run 1856 m to 5349 m with a median of
3082. So the span is 3000 m, measured rather than felt, and a test recomputes that median
from `config` and fails if the courses change enough to move it.

The boat is centred when that extent is asked for and not followed after that. Following
was considered and dropped, as it was in 12.1: a view that recentres itself fights the
hand that just panned it. For the same reason, a course change refits the view only when
the view is on the inner extent **and** has not been dragged by hand.

### 12.3 Two fingers pan as well as pinch

Asked for from the boat. A two-finger drag did nothing at all, so moving the chart meant
changing grip to one finger, and the crew is wearing gloves and holding on with the other
hand.

The cause is worth recording because the code looked right. `zoomAbout` scales and then
puts the user-space point that was under the finger back under the finger, which is what
makes a pinch feel anchored. The pinch handler passed it the midpoint the fingers had just
arrived at, for both. Hold the spread and the factor is 1, and a point put back under
itself does not move: the pan was computed and then discarded, every frame.

It is one transform, not two modes. Scale about where the fingers **were**, then put
whatever was under them where the fingers **are**. Hold the spread and that is a pure pan;
change it and both happen at once; there is no mode to be in and nothing to switch. The
destination is a defaulted parameter, so the mouse wheel is the same call with two
arguments fewer, which is the pure zoom it always was.

Two fingers landing on the same pixel give no scale to divide by. That used to abandon the
gesture; it now falls back to a pure pan, because two fingers touching should still drag
the chart.

Measured with real TouchEvents at the iPad viewport, from the Race course extent at 4.2 m
per pixel: two fingers moved 120 px left and 90 up with the spread held panned 548 m and
411 with the size unchanged to four decimal places; spread apart about a held midpoint
scaled by 0.4545 and moved the centre 174 m out of a 27.8 km view; both together did both.
One finger still pans, 411 m and 274 for 90 px and 60.

No new cost on the machine that is slowest at this. Single-finger pan is still coalesced to
one view per frame and the two-finger path still applies at once, which it must, since it
reads the CTM back between its two writes. Two-finger panning is the cheaper half of a
pinch: the size does not change, so `applyScale` does not run.

### 12.4 The region depths, and what they changed on the page

`depth.json` grew from the river to the whole mapped extent: Rottnest, Gage Roads, Owen
Anchorage, Cockburn Sound, Warnbro and the northern beaches. Two stages, the SC2010
multibeam at 2 m for the river and the five DoT composite surfaces at 10 m for the rest,
declared in the document's `coverage`. The generator's side of that is above; this is what
it cost the page, which is less than expected in one way and more in another.

**Nothing about the drawing had to change.** The schema went to `pfsyc-depth/2` but the
feature contract did not move: two kinds, `band` and `contour`, keyed by `properties.band`
and `properties.depth_m`, the same five band ids and the same three levels.
`drawDepth` reads all of that as literals and validates none of it, so a regeneration that
renamed a property would draw an empty chart and report nothing. That contract is now
asserted against the real `config/depth.json` in `tests/test_map.py`, along with the day
palette matching the colours the generator writes into the document for QGIS.

**It costs 392 kB on the wire, not 1.9 MB.** nginx gzips `application/json` and the file
is repetitive coordinate text, so it compresses 4.8:1. All six config documents together
are 487 kB compressed. On the Pi's own browser the page is ready 0.62 s after the request
with 2427 paths and 78,174 coordinate pairs, against about 16,000 before. The iPad mini 3
is the machine that decides whether that is acceptable and it cannot be measured from
here; the thresholds that already existed do most of the work, the aid register being
hidden past 25 m per pixel and every mark label past 50.

**The canvas is no longer water, and that is the real change.** `#chart`'s background was
a grey-blue called `--water`, and the reasoning was sound while the survey covered the
river alone: every gap in it was somewhere a person could see was water, and rendering the
page with a black canvas had found those gaps reading as land. The region surveys inverted
it. The map now extends well past its own data, about a third of the Everything extent is
off the chart, and that third includes real open ocean north and west of Rottnest. Painted
water-blue it said "sea" about places holding no information at all, which is precisely
the mistake `gen_depth.py` refuses to make *inside* the region when it paints unsurveyed
water green rather than deep.

So the token is `--nodata`, a neutral grey by day, deliberately outside the four chart
blues and the foreshore green, and the edge of the data is now visible. A test holds it
15 luma clear of every band and under 20 of channel spread, so it cannot drift into being
a blue.

At night it is the darkest thing on the page and **off the chart is hard to tell from the
deepest water**. That is accepted rather than solved. A brighter red-grey was tried first
and landed between the mid and deep bands in brightness, which on a palette that has given
up hue is the same as landing on them; the five bands already spend the usable range and
the theme forbids reaching outside red for a sixth tone. What makes it survivable is that
the night theme is used in the river, on the Race course extent, where nothing off the
chart is on the screen, and that the coastline is drawn bright for exactly this reason.

**The caveat was wrong on the page after the datum correction.** It said "depths below low
water from a 2010 survey", which reads as conservative, and the correction above is that
they are on AHD and the error runs the other way. The page said the unsafe thing for as
long as it took to notice, which is the argument for the caveat being asserted rather than
merely written: the test now requires it to name AHD, to say "not chart datum", and to say
which direction the error runs, and to not contain the old wording. Naming a datum without
saying what it costs leaves the crew to work it out, which is not a caveat.

## 13. Build order

1. `engine/nav.py` with unit tests, using the MGA94 grid columns as fixtures.
2. `courses.json` for one series, linted against the rounding column.
3. Port the HUD, serve it at `/race/hud`, compare side by side against
   `/nodered/hud` with the boat running.
4. Disable the Node-RED Sailing HUD tab, leaving it in the flow as a fallback for
   one season. **Not done**, and it needs the boat running to compare side by side.
   The tab is still enabled and still served at `/nodered/hud`.
5. ~~Add position publishing to the GPS source.~~ Done: `pyemonlib.emon_mqtt`
   publishes `gps/position/<subnode>`, and `mqtt_client.py` reads it. No longer
   blocking, which unblocks 6.
6. Race state machine, driven by replayed tracks before it is driven by the boat.
7. Countdown and pre-start.
8. Flags and course selection UI.
9. Map page. Data done (`coast.json`, `depth.json`); the page not started and the nav
   entry still disabled. Decisions and build order in 12.1.
10. Config editor. Not started. `PUT /api/config/...` is designed, not built, which is
    why the deployment bind-mounts `config/` read-write: landing it should not need a
    compose change.

Not in the original list, and done: the nginx block and the container in section 5, and
the Home Screen work in 9.8.1. Both were driven by the boat rather than by this document,
which is the pattern to expect from here: the engine was finished off replays, and
everything still outstanding needs either the boat powered up or a device in hand.

## 14. Deferred

- A local CA issuing a cert for `enchantee.local` with `10.42.0.1` as an IP SAN
  would buy back the wake lock API and phone GPS as a position fallback, at the
  cost of installing and trusting a root certificate on each device. Not worth it
  initially.
- Server-sent events instead of polling.
- ~~Depth contours.~~ Done, see section 12. What is left is the 9% of the survey
  footprint the 2010 multibeam missed: Matilda Bay, Perth Water and the Canning
  entrance. The DoT survey index lists `SC20251114_Mean`, November 2025, covering
  exactly those gaps plus PFSYC, but its `S3_path` is null so there is no public
  download yet. Worth asking DoT for.
- Re-surveying the PFSYC inner start mark.
