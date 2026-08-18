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

import re
import threading
import time
from typing import Any, Callable, Mapping, NamedTuple, Optional

from engine import nav

STALE_S = 15.0
"""Wind and motor readings are dimmed past this age (DESIGN 9.5). Applied by the
page, not here: the payload reports age and lets the display decide."""

POSITION_STALE_S = 5.0
"""Position blanks rather than dims past this age, and the leg engine stops
evaluating advance (DESIGN 9.5). Here for when position is wired up."""

RPM_DEADBAND = 5.0
"""Rpm this close to zero counts as stopped."""

MOTOR_HOLD_S = 10.0
"""Stay on the motor panels this long after the SevCon stops, so a lumpy idle cannot
flip the panels back and forth. The same hold idiom the leg engine uses after an
advance (DESIGN 9.1, 11.2)."""

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
    if value != value or value in (float("inf"), float("-inf")):  # NaN or infinity
        return None
    return value


class Store:
    """The latest reading for each field. One lock, held for every access."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._lock = threading.Lock()
        self._values: dict = {}
        self._motor_last = 0.0
        self._clock = clock

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
        """The {now, motor, fields} document the pages poll for."""
        return derive(self.snapshot(), self._clock() if now is None else now)


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
