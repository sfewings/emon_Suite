"""Thread-safe cache of the latest reading per field, and the payload pages poll.

Two long-lived threads share this state: the paho network loop writing readings and
Flask request handlers reading them. Every mutation goes behind the single lock in
Store. Engine code never touches the store; it is handed values (CLAUDE.md).

Ported from the "Cache HUD values" and "Latest values as JSON" function nodes of the
Sailing HUD tab in docs/reference/flows.json, which is the only current description
of that page: docs/reference/HUD.png predates changes to the colours and the order of
the readings, so it is not a reference for anything.

derive() is a pure function of a snapshot and a timestamp, deliberately, so the
staleness rules, the TWA derivation and the motor hold can be tested without a broker
or a clock. Store holds the lock and the state; derive holds the arithmetic.

Readings leave here wrapped as {v, age} so the page can dim a sensor that has gone
quiet. Wind and motor dim at 15 s. Position, once it is published, blanks rather than
dims at 5 s, and the leg engine stops evaluating advance: a dimmed number still reads
as a number at a glance, which is worse than no number (DESIGN 9.5). Nothing reads
position yet, so nothing here does either.
"""

from __future__ import annotations

import math
import re
import threading
import time
from typing import Any, Callable, Mapping, NamedTuple, Optional

from engine import nav, race

STALE_S = 15.0
"""Wind and motor readings are dimmed past this age (DESIGN 9.5). Applied by the
page, not here: the payload reports age and lets the display decide."""

POSITION_KEY = "position"
"""Where a gps/position/0 fix lands. Its value is a {"lat": .., "lon": ..} dict, not a
number, which is why it is not one of FIELDS and not on the HUD payload."""

POSITION_STALE_S = 5.0
"""Position blanks rather than dims past this age, and the leg engine stops evaluating
advance (DESIGN 9.5). A bearing computed from a 15 s old fix at 6 knots is 46 m out, so
navigation cannot share the 15 s threshold that suits wind and motor readings."""

RPM_DEADBAND = 5.0
"""Rpm this close to zero counts as stopped."""

MOTOR_HOLD_S = 10.0
"""Stay on the motor panels this long after the SevCon stops, so a lumpy idle cannot
flip the panels back and forth. The same hold idiom the leg engine uses after an
advance (DESIGN 9.1, 11.2)."""

PENDING_EVENTS_MAX = 200
"""How many unpublished race events to hold. A race produces a couple of dozen, so this is
only a bound against nothing ever draining them."""

# --- the trail (DESIGN 12.6) -----------------------------------------------------------
#
# Everything sailed since local midnight, held here rather than in the browser because the
# map page is one of three documents and the crew walks between them: a trail accumulated
# client-side would start empty every time the page was opened, which is most of the
# reason for looking at it. It is deliberately NOT persisted to disk. Losing it on a
# restart or a power cycle is acceptable and was specified as such; losing it on a page
# refresh is not, and holding it server-side is what tells those two cases apart.

TRAIL_MIN_MOVE_M = 3.0
"""Keep a fix only once the boat has moved this far from the last one kept. At 5 kt that
is a point every 1.2 s, which is finer than the trail can be seen at any zoom this page
offers, and it collapses a fleet of fixes taken at anchor into one."""

TRAIL_MIN_INTERVAL_S = 60.0
"""...or this long has passed, whichever comes first. This rule only ever fires while the
boat is stationary: under way the distance rule above fires every second or two and this
one never gets a chance. So it is not a sample rate, it is the heartbeat that records
"still here" through a lunch stop, and 60 s rather than a few seconds is the difference
between 60 stacked points in an hour and 720 of them."""

TRAIL_MAX_POINTS = 25000
"""A bound, not a working limit. A long day decimated as above is 15,000 to 20,000 points,
so this is only insurance against a fix source that jitters several metres while moored
and defeats the distance rule. The oldest go first: the near past is what the crew is
looking at."""

TRAIL_DAY_OFFSET_S = 8 * 3600
"""Seconds east of UTC, for deciding which day a fix belongs to.

An explicit offset rather than the process timezone, for two reasons. The Dockerfile sets
TZ=UTC, so localtime() in the deployed container would roll the trail over at 08:00 Perth
time, which is the middle of a morning sail. And zoneinfo on python:*-slim has no tzdata
to read, so naming the zone properly would mean a new runtime dependency for a single
integer. Western Australia has observed no daylight saving since the 2009 referendum, so
a fixed +8 is not an approximation here, it is exact."""

FIELDS = ("sog", "cog", "hdg", "tws", "twd", "aws", "twa", "awa", "rpm", "cur", "ctrl", "mot")
"""Every key the payload carries, in the order the Node-RED flow emitted them. twa and
awa are derived; the rest arrive on their own topic."""

_LEADING_NUMBER = re.compile(r"^\s*[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


class Reading(NamedTuple):
    """A value and the time it arrived, in seconds since the epoch."""

    v: Any
    t: float


class Snapshot(NamedTuple):
    """A consistent copy of the store, taken under the lock."""

    values: dict
    motor_last: float


def parse_number(payload: Any) -> Optional[float]:
    """Parse a bare-number MQTT payload, or None if there is no number in front.

    Mirrors the JavaScript parseFloat the flow used, which takes the leading numeric
    prefix and ignores the rest. That tolerance is not incidental: some publishers on
    this broker append a suffix to the value, an RSSI reading among them, and float()
    would reject the lot.
    """
    if isinstance(payload, (int, float)) and not isinstance(payload, bool):
        value = float(payload)
    else:
        if isinstance(payload, (bytes, bytearray)):
            try:
                payload = payload.decode("utf-8", "replace")
            except Exception:
                return None
        match = _LEADING_NUMBER.match(str(payload))
        if not match:
            return None
        value = float(match.group(0))
    if not math.isfinite(value):  # NaN or infinity
        return None
    return value


class Store:
    """The latest reading for each field, and the race. One lock, held for every access.

    The race state lives here rather than in a runner of its own because CLAUDE.md says
    there is one lock and it is this one. Both threads touch the race: the paho loop
    evaluates it on every fix, and Flask handlers move it on every button. Two locks would
    be two chances to take them in the wrong order.

    What lives here is the state; the rules live in engine/race.py and stay pure. This
    class never decides anything about a race, it only holds the current answer and swaps
    it for the next one under the lock.
    """

    def __init__(self, clock: Callable[[], float] = time.time,
                 day_offset_s: float = TRAIL_DAY_OFFSET_S) -> None:
        self._lock = threading.Lock()
        self._values: dict = {}
        self._motor_last = 0.0
        self._clock = clock
        self._race = race.initial()
        self._context: Optional[race.Context] = None
        self._pending: list = []
        # The trail: (seq, lat, lon, sog, t) per kept fix, oldest first. seq is contiguous
        # and only ever increases, which is what lets a caller ask for "everything after
        # n" and be answered by index arithmetic rather than a scan.
        self._trail: list = []
        self._trail_seq = 0
        self._trail_day: Optional[int] = None
        self._day_offset_s = day_offset_s
        # The theme, which is server state for the reason DESIGN 9.9 gives about all the
        # rest of it: every device renders the same state and any device can drive it. The
        # sun sets on the whole boat at once, so a theme held per browser would have to be
        # set three times and would still be lost by walking between screens.
        self._theme = "day"

    def set(self, key: str, value: Any, ts: Optional[float] = None) -> None:
        """Record a reading. ts defaults to now, and is the arrival time, not fix time."""
        with self._lock:
            t = self._clock() if ts is None else ts
            self._values[key] = Reading(value, t)
            # Remember when the SevCon was last actually turning. It has to be tracked
            # on the way in: once an idle reading replaces it in the cache, the arrival
            # time of the last turning one is gone, and that time is what the hold
            # below counts from.
            if key == "rpm" and isinstance(value, (int, float)) and abs(value) > RPM_DEADBAND:
                self._motor_last = t

    def get(self, key: str) -> Optional[Reading]:
        with self._lock:
            return self._values.get(key)

    def snapshot(self) -> Snapshot:
        """A copy of everything, taken atomically.

        Callers get their own dict, so a request handler can read at leisure while the
        network loop keeps writing.
        """
        with self._lock:
            return Snapshot(dict(self._values), self._motor_last)

    def payload(self, now: Optional[float] = None) -> dict:
        """The {now, motor, fields} document the HUD polls for."""
        return derive(self.snapshot(), self._clock() if now is None else now)

    def state(self, now: Optional[float] = None) -> dict:
        """The HUD payload, position and race state, for /api/state.

        Kept separate from payload() so /hud/data stays the exact shape the Node-RED
        flow served, which is what makes the two comparable side by side during the port
        (DESIGN 13 step 3). Race state joins this one, not that one (DESIGN 4).
        """
        now = self._clock() if now is None else now
        snapshot = self.snapshot()
        state = derive(snapshot, now)
        state["position"] = derive_position(snapshot, now)
        state["race"] = self.race_payload(now)
        state["theme"] = self.theme()
        return state

    # --- settings ----------------------------------------------------------

    THEMES = ("day", "night")
    """The only two, and the whole of the allowed set. Named here rather than checked at
    the route, because the value ends up as a class on the body of three pages and an
    arbitrary string out of a request has no business going there."""

    def theme(self) -> str:
        with self._lock:
            return self._theme

    def set_theme(self, name: str) -> str:
        """Set the theme, ignoring anything that is not one of the two. Returns the theme
        in force afterwards, so a caller never has to guess whether it took."""
        with self._lock:
            if name in Store.THEMES:
                self._theme = name
            return self._theme

    # --- the race ----------------------------------------------------------

    def set_race_context(self, context: Optional[race.Context]) -> None:
        """Install the course, marks, lines and tuning the engine works against."""
        with self._lock:
            self._context = context

    def race_state(self):
        """The current race state and its context. Both immutable, so no copy is needed."""
        with self._lock:
            return self._race, self._context

    def apply_race(self, action: Callable) -> list:
        """Run one race transition under the lock. Returns the events, and queues them.

        action(state, context, now) -> (state, events), which is the shape every command
        in engine/race.py already has. Passing the function in rather than naming the
        transition keeps the rules in the engine: this method knows about locking and
        nothing else.

        Doing it under the lock is what makes a race single-writer. Two devices tapping
        Next at the same moment produce one advance, and a fix arriving mid-tap cannot
        interleave with it.
        """
        with self._lock:
            if self._context is None:
                return []
            state, events = action(self._race, self._context, self._clock())
            self._race = state
            self._queue(events)
            return events

    def _queue(self, events) -> None:
        """Hold events for whoever drains next. Call with the lock held.

        Every transition has to be published for event_recorder to log (DESIGN 11.9), and
        a transition can be caused by any of three things: a command, a fix, or the clock
        reaching T-0 while a page happens to poll. Queueing rather than returning to the
        caller is what stops the third one being dropped, which is exactly what happened
        when race_payload evaluated on_clock and threw the result away.
        """
        if not events:
            return
        self._pending.extend(events)
        # Bounded, so a long race with nothing polling cannot grow this without limit.
        # Losing the oldest is the right end to lose from: they are already stale.
        if len(self._pending) > PENDING_EVENTS_MAX:
            del self._pending[:-PENDING_EVENTS_MAX]

    def drain_events(self) -> list:
        """Take the queued events. Called by whoever is in a position to publish them."""
        with self._lock:
            events, self._pending = self._pending, []
            return events

    def on_position(self, position: Any, ts: Optional[float] = None) -> list:
        """Record a fix and evaluate the race against it, atomically.

        One lock acquisition for both, because the engine needs the course and speed that
        arrived with this fix: reading them in a separate call could pick up the next
        fix's values and hand the engine a position from one moment with a heading from
        another. That is the same reason gps/position/0 carries lat and lon together
        (DESIGN 3).
        """
        with self._lock:
            now = self._clock() if ts is None else ts
            self._values[POSITION_KEY] = Reading(position, now)

            # Before the context check below, deliberately. The trail is a record of where
            # the boat has been, which is a fact about the day and not about a race, and
            # the crew wants it on a cruise with no course selected at all. Putting it
            # after that early return is the obvious mistake and it would leave the trail
            # empty exactly when it is the only thing on the chart.
            self._append_trail(position, now)

            if self._context is None:
                return []

            cog = self._values.get("cog")
            sog = self._values.get("sog")
            fix = race.Fix(
                position=nav.as_latlon(position),
                ts=now,
                cog=cog.v if cog and isinstance(cog.v, (int, float)) else None,
                sog=sog.v if sog and isinstance(sog.v, (int, float)) else None,
            )
            evaluated = self._clock()
            state, events = race.on_clock(self._race, self._context, evaluated)
            state, more = race.on_fix(state, self._context, fix, evaluated)
            self._race = state
            self._queue(events + more)
            return events + more

    # --- the trail ---------------------------------------------------------

    def _append_trail(self, position: Any, now: float) -> None:
        """Record this fix on the day's trail, if it is far enough from the last one kept.

        Call with the lock held. Reads sog out of the cache rather than taking it as an
        argument, for the same reason on_position reads cog and sog there: this is the one
        moment when the speed in the cache is known to belong to the fix being recorded.

        A fix with no usable speed is still kept, with sog None. The alternative, dropping
        it, would put a straight line across the chart between the fixes either side, which
        claims the boat sailed a course it did not.
        """
        if not isinstance(position, dict):
            return
        lat, lon = position.get("lat"), position.get("lon")
        if not isinstance(lat, (int, float)) or isinstance(lat, bool):
            return
        if not isinstance(lon, (int, float)) or isinstance(lon, bool):
            return
        if not (math.isfinite(lat) and math.isfinite(lon)):
            return

        # Which day this fix belongs to, in local terms. See TRAIL_DAY_OFFSET_S for why
        # the offset is a constant and not the process timezone.
        day = int((now + self._day_offset_s) // 86400)
        if day != self._trail_day:
            self._trail_day = day
            del self._trail[:]

        if self._trail:
            last = self._trail[-1]
            moved = nav.distance_m({"lat": last[1], "lon": last[2]},
                                   {"lat": lat, "lon": lon})
            if moved < TRAIL_MIN_MOVE_M and (now - last[4]) < TRAIL_MIN_INTERVAL_S:
                return

        sog = self._values.get("sog")
        speed = sog.v if sog and isinstance(sog.v, (int, float)) and not isinstance(sog.v, bool) else None
        self._trail_seq += 1
        self._trail.append((self._trail_seq, float(lat), float(lon), speed, now))
        if len(self._trail) > TRAIL_MAX_POINTS:
            del self._trail[:len(self._trail) - TRAIL_MAX_POINTS]

    def trail(self, since: Optional[int] = None) -> dict:
        """The day's trail, or the part of it the caller has not already got.

        `since` is the `next` from the caller's previous response. The reply says
        `replace` when what comes back is the whole trail and the caller must drop what it
        holds, rather than the tail it can append. Three things cause that, and the map
        page cannot tell them apart and does not need to: a first load, local midnight
        emptying the trail, and a restart of this process putting the sequence back to
        zero under a browser still holding a high `since`. That last one is the reason for
        the `since > newest` test, without which a page left open across a restart would
        ask for points beyond the end for ever and silently never draw another metre.

        Coordinates are rounded to six decimal places, about 0.1 m, and speed to one. The
        full repr of a float is 17 significant figures of which the last ten are noise
        here, and this payload is the largest thing the app sends: a whole day is some
        20,000 points, so the rounding is worth about 300 kB on a first load.
        """
        with self._lock:
            newest = self._trail_seq
            oldest = self._trail[0][0] if self._trail else None
            # Contiguous by construction, so the tail the caller is missing starts at a
            # known index and needs no scan. A `since` older than what is still held would
            # leave a gap in the drawn line, so that is a replace too.
            replace = (since is None or oldest is None
                       or since < oldest - 1 or since > newest)
            points = self._trail if replace else self._trail[since - oldest + 1:]
            return {
                "day": self._trail_day,
                "next": newest,
                "replace": replace,
                "points": [[round(p[1], 6), round(p[2], 6),
                            None if p[3] is None else round(p[3], 1)]
                           for p in points],
            }

    def _fix_now(self, now: float) -> Optional[race.Fix]:
        """The current fix as the engine wants it, or None if there is not a usable one.

        Call with the lock held. Returns None past the staleness cutoff, so everything
        downstream blanks rather than showing a bearing computed from an old position
        (DESIGN 9.5).
        """
        reading = self._values.get(POSITION_KEY)
        if reading is None or not isinstance(reading.v, dict):
            return None
        if (now - reading.t) > POSITION_STALE_S:
            return None
        cog = self._values.get("cog")
        sog = self._values.get("sog")
        return race.Fix(
            position=nav.as_latlon(reading.v),
            ts=reading.t,
            cog=cog.v if cog and isinstance(cog.v, (int, float)) else None,
            sog=sog.v if sog and isinstance(sog.v, (int, float)) else None,
        )

    def _wind_direction(self) -> Optional[float]:
        """The true wind direction, or None. Call with the lock already held.

        Not stale-checked: the leg type it feeds is a statement about the course rather
        than a reading on a dial, and a wind that was there a minute ago is a better guide
        to which legs are close hauled than nothing at all.
        """
        twd = self._values.get("twd")
        return twd.v if twd and isinstance(twd.v, (int, float)) else None

    def wind_direction(self) -> Optional[float]:
        """The true wind direction for a caller that holds no lock."""
        with self._lock:
            return self._wind_direction()

    def race_payload(self, now: Optional[float] = None) -> Optional[dict]:
        """What the pages need to render the race, or None before a course is chosen.

        on_clock runs here as well as on every fix, so prestart still becomes racing at
        T-0 when the boat is sitting still and no fix has moved. It is idempotent and
        under the lock, so several devices polling at once produce one transition between
        them, and whichever gets there first is the one that sees the start event.
        """
        with self._lock:
            now = self._clock() if now is None else now
            if self._context is None:
                return None
            self._race, events = race.on_clock(self._race, self._context, now)
            self._queue(events)
            state, context = self._race, self._context
            fix = self._fix_now(now)
            twd = self._wind_direction()

        return {
            "mode": state.mode,
            "course": state.course_id,
            "leg": state.leg,
            "legs": len(context.legs),
            "leg_name": race.target_name(state, context),
            "rounding": (context.legs[state.leg].get("rounding")
                         if state.leg < len(context.legs) else None),
            "elapsed": race.elapsed(state, now),
            "countdown": race.countdown(state, now),
            "finish_armed": state.finish_armed,
            "shortened": state.shortened,
            "breaches": state.breaches,
            "ignored_crossings": state.ignored_crossings,
            "nav": race.navigation(state, context, fix, twd),
            "line": race.line_approach(state, context, fix),
        }


def derive(snapshot: Snapshot, now: float) -> dict:
    """Build the payload from a snapshot. Pure: no clock, no lock, no I/O.

    Ported from the "Latest values as JSON" function node.
    """
    values = snapshot.values

    def live(key: str) -> Optional[Reading]:
        """A reading only counts if it is present and numeric."""
        reading = values.get(key)
        if reading is None or not isinstance(reading.v, (int, float)):
            return None
        return reading

    hdg = live("hdg")
    twd = live("twd")

    # TWA is measured nowhere on this boat: it is the true wind direction seen from
    # the bow. Timestamped with the older of its two inputs, so it goes stale as soon
    # as either does (DESIGN 3).
    twa = None
    if twd and hdg:
        twa = Reading(nav.norm180(twd.v - hdg.v), min(twd.t, hdg.t))

    # AWA comes straight off the masthead unit on anemometer/windDirection/0, already
    # bow relative. If that topic is not being published, derive it from the compass
    # version on windDirection/1 instead (DESIGN 3).
    awa = live("awa")
    if awa:
        awa = Reading(nav.norm180(awa.v), awa.t)
    else:
        awd = live("awd")
        if awd and hdg:
            awa = Reading(nav.norm180(awd.v - hdg.v), min(awd.t, hdg.t))

    # The page swaps the wind panels for the SevCon readings while the motor turns.
    # Counting from the arrival time rather than from now is what makes a SevCon that
    # goes silent mid-rev time out instead of pinning the panels on for good.
    motor = (now - snapshot.motor_last) < MOTOR_HOLD_S

    latest = {key: live(key) for key in FIELDS}
    latest["twa"] = twa
    latest["awa"] = awa

    fields = {}
    for key in FIELDS:
        reading = latest[key]
        fields[key] = None if reading is None else {"v": reading.v, "age": now - reading.t}

    # now is milliseconds, matching the Node-RED payload exactly so the two /data
    # responses can be diffed side by side during the port (DESIGN 13 step 3).
    return {"now": int(now * 1000), "motor": motor, "fields": fields}


def derive_position(snapshot: Snapshot, now: float) -> Optional[dict]:
    """The latest fix as {v: {lat, lon}, age, stale}, or None if none has arrived.

    `stale` carries the 5 s cutoff rather than leaving each caller to apply it. It is
    server state on purpose: every device must agree about whether the fix is good, and
    the leg engine's rule that it stops evaluating advance past the cutoff has to be the
    same rule the display uses to blank the numbers (DESIGN 9.5, 11.2).

    Blanking, not dimming, is the display treatment. A dimmed number still reads as a
    number to someone glancing at it in spray.
    """
    reading = snapshot.values.get(POSITION_KEY)
    if reading is None or not isinstance(reading.v, dict):
        return None
    age = now - reading.t
    return {"v": dict(reading.v), "age": age, "stale": age > POSITION_STALE_S}
