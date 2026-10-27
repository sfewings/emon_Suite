"""Self-describing emon feeds: the reading, its envelope, a store, and the shared maths.

docs/emon_live_ui/DESIGN.md is the authority for everything here; sections are cited as
DESIGN n.n.

This module imports only the standard library (DESIGN D4). It must stay importable on a
machine with no build of the emonSuite C++ extension and no paho, influxdb_client or yaml,
because enchantee_racing and event_recorder will import it when they migrate, and because
it is where the calculations shared between emon_live, the race app and the recorder live.
tests/test_emon_feed.py checks that this stays true.

Contents:

    Reading                 one value of one feed, with its names and units
    topic_for, feed_key     where a reading is published, and how pages name it
    envelope, envelope_json the payload published on emon/... (DESIGN 4.2)
    parse                   envelope or legacy bare number back into a Reading
    Catalogue               feed key to topic, built from readings seen
    Store                   latest reading per feed, with ages
    norm180 ... integrate_wh the derived maths (DESIGN 6.3, D3)
    DailyDelta ... Expr     the derived.yml operators (DESIGN 6.3)
"""

from __future__ import annotations

import ast as _ast
import json
import math
import re
import threading
import time as _time
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple, Union

ENVELOPE_VERSION = 1
"""The envelope's `s` field. Fields may be added within a version, never renamed or
removed (DESIGN 4.2)."""

TOPIC_ROOT = "emon"
CONFIG_TOPIC = "emon/config"
DERIVED_NODE = "derived"

UNUSED = "Unused"
"""The name emon_config gives a channel that is not connected. Such channels get no
envelope: there is nothing to call them, and several of them would share one name."""

Index = Union[int, str, None]


# --------------------------------------------------------------------------------------
# The reading
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Reading:
    """One value of one feed.

    node    the emon node type as it appears on the serial line: 'pulse', 'temp', 'bms'.
            'derived' for values computed by emon_live or Node-RED.
    sub     the subnode number, or None where there is none.
    field   the quantity within the node: 'power', 'temperature', 'cellVoltage'. For a
            derived feed, its id path, e.g. 'power/consumed/today'.
    value   a number, or for GPS position a {"lat": .., "lon": ..} dict.
    unit    'W', 'degC', 'kn', ... or '' when unitless.
    kind    the physical quantity, for grouping and colour: 'power', 'temperature'.
    idx     the channel within the node, where there are several: an int, or a string
            for an RSSI reading heard via a relay.
    group   the node's name from emon_config, e.g. 'Power board'.
    name    the channel's name, unique within the group, e.g. 'Consumed'.
    t       seconds since the epoch, on the bridge host's clock when the line arrived
            (DESIGN 4.3).
    rssi    signal strength of the packet the reading came in, when known.
    legacy_topic  set only on readings parsed from a legacy bare-number topic, which
            carry no names; they are then keyed by that topic.
    """

    node: str
    sub: Optional[int]
    field: str
    value: Any
    unit: str = ""
    kind: str = ""
    idx: Index = None
    group: str = ""
    name: str = ""
    t: Optional[float] = None
    rssi: Optional[int] = None
    legacy_topic: Optional[str] = None

    @property
    def topic(self) -> str:
        return topic_for(self)

    @property
    def key(self) -> str:
        return feed_key(self)


def topic_for(reading: Reading) -> str:
    """emon/<node>/<sub>/<field>[/<idx>], or emon/derived/<id> (DESIGN 4.2).

    Structural, so it is unique by construction and stable across renames. Names travel in
    the payload instead.
    """
    if reading.legacy_topic is not None:
        return reading.legacy_topic
    if reading.node == DERIVED_NODE:
        return f"{TOPIC_ROOT}/{DERIVED_NODE}/{reading.field}"
    parts = [TOPIC_ROOT, reading.node]
    if reading.sub is not None:
        parts.append(str(reading.sub))
    parts.append(reading.field)
    if reading.idx is not None:
        parts.append(str(reading.idx))
    return "/".join(parts)


def feed_key(reading: Reading) -> str:
    """How pages and derived.yml refer to a feed (DESIGN 5).

    'group / name' for an emon feed, 'derived/<id>' for a derived one, and the topic for
    anything that carries no names.
    """
    if reading.node == DERIVED_NODE and reading.legacy_topic is None:
        return f"{DERIVED_NODE}/{reading.field}"
    if reading.group and reading.name:
        return f"{reading.group} / {reading.name}"
    return reading.topic


# --------------------------------------------------------------------------------------
# The envelope
# --------------------------------------------------------------------------------------

def plain(value: Any) -> Any:
    """A JSON-safe copy of a value: numpy scalars to Python, non-finite numbers to None.

    The C++ bindings hand back numpy scalars for array elements, and json.dumps refuses
    them. NaN and infinity would serialise as tokens that are not JSON.
    """
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if hasattr(value, "item") and callable(value.item):
        value = value.item()
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def envelope(reading: Reading) -> Dict[str, Any]:
    """The envelope as a dict. Absent optional fields are left out rather than null."""
    env: Dict[str, Any] = {"s": ENVELOPE_VERSION, "v": plain(reading.value)}
    if reading.unit:
        env["u"] = reading.unit
    if reading.t is not None:
        env["t"] = round(float(reading.t), 3)
    if reading.kind:
        env["kind"] = reading.kind
    env["node"] = reading.node
    if reading.sub is not None:
        env["sub"] = reading.sub
    env["field"] = reading.field
    if reading.idx is not None:
        env["idx"] = reading.idx
    if reading.group:
        env["group"] = reading.group
    if reading.name:
        env["name"] = reading.name
    if reading.rssi is not None:
        env["rssi"] = reading.rssi
    return env


def envelope_json(reading: Reading) -> str:
    return json.dumps(envelope(reading), separators=(",", ":"), allow_nan=False)


_LEADING_NUMBER = re.compile(r"^\s*[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?\s*$")


def parse_number(payload: Any) -> Optional[float]:
    """A finite number from a bare-number payload, or None."""
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", "replace")
    if isinstance(payload, bool):
        return None
    if isinstance(payload, (int, float)):
        value = float(payload)
    elif isinstance(payload, str) and _LEADING_NUMBER.match(payload):
        value = float(payload)
    else:
        return None
    return value if math.isfinite(value) else None


def parse(topic: str, payload: Any, arrival: Optional[float] = None) -> Optional[Reading]:
    """A Reading from either an envelope or a legacy payload, or None if unusable.

    Lets a consumer switch its parsing before its subscriptions (DESIGN 7). A legacy
    reading has no names and is keyed by its topic. A legacy JSON object that is not an
    envelope, such as gps/position/0, is returned with the object as its value.

    `arrival` becomes `t` when the payload carries none.
    """
    text = payload
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("utf-8", "replace")
    obj = None
    if isinstance(text, str) and text.lstrip().startswith("{"):
        try:
            obj = json.loads(text)
        except ValueError:
            return None
    elif isinstance(text, dict):
        obj = text

    if isinstance(obj, dict):
        if "s" in obj and "v" in obj and "node" in obj:
            return Reading(
                node=str(obj.get("node", "")),
                sub=obj.get("sub"),
                field=str(obj.get("field", "")),
                value=obj["v"],
                unit=obj.get("u", ""),
                kind=obj.get("kind", ""),
                idx=obj.get("idx"),
                group=obj.get("group", ""),
                name=obj.get("name", ""),
                t=obj.get("t", arrival),
                rssi=obj.get("rssi"),
            )
        return Reading(node="", sub=None, field="", value=obj, t=arrival, legacy_topic=topic)

    value = parse_number(text)
    if value is None:
        return None
    return Reading(node="", sub=None, field="", value=value, t=arrival, legacy_topic=topic)


# --------------------------------------------------------------------------------------
# Catalogue and store
# --------------------------------------------------------------------------------------

class Catalogue:
    """Feed key to topic, learned from the readings seen.

    Envelopes are retained, so a consumer that subscribes to emon/# receives one of each
    at once and has a complete catalogue before the first new message (DESIGN 5).
    """

    def __init__(self) -> None:
        self._topics: Dict[str, str] = {}
        self.duplicates: Dict[str, set] = {}

    def add(self, reading: Reading) -> None:
        key, topic = reading.key, reading.topic
        known = self._topics.get(key)
        if known is None:
            self._topics[key] = topic
        elif known != topic:
            self.duplicates.setdefault(key, {known}).add(topic)

    def topic(self, key: str) -> Optional[str]:
        return self._topics.get(key)

    def keys(self) -> List[str]:
        return sorted(self._topics)

    def __contains__(self, key: str) -> bool:
        return key in self._topics

    def __len__(self) -> int:
        return len(self._topics)


class Store:
    """The latest reading of every feed, keyed by feed key, with ages.

    Generalised from enchantee_racing's store.py. A reading with no `t` is stamped with
    the store's clock on arrival. Thread-safe: one lock, held only to read or replace.
    """

    def __init__(self, clock: Callable[[], float] = _time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._values: Dict[str, Reading] = {}

    def put(self, reading: Reading) -> Reading:
        if reading.t is None:
            reading = replace(reading, t=self._clock())
        with self._lock:
            self._values[reading.key] = reading
        return reading

    def get(self, key: str) -> Optional[Reading]:
        with self._lock:
            return self._values.get(key)

    def age(self, key: str, now: Optional[float] = None) -> Optional[float]:
        reading = self.get(key)
        if reading is None or reading.t is None:
            return None
        return (self._clock() if now is None else now) - reading.t

    def snapshot(self) -> Dict[str, Reading]:
        with self._lock:
            return dict(self._values)

    def __len__(self) -> int:
        with self._lock:
            return len(self._values)


# --------------------------------------------------------------------------------------
# Derived maths (DESIGN D3, 6.3)
#
# Plain functions of numbers. Inputs that are missing are passed as None and give None,
# so callers can hand over whatever their store holds without checking it first. Ages are
# the caller's business: the race app and emon_live each apply their own stale rules.
# --------------------------------------------------------------------------------------

LEEWAY_MIN_SOG_KT = 1.0
"""Below this speed over ground, COG is mostly GPS noise and leeway is not reported.
From enchantee_racing store.py, where the reasoning is recorded."""

HEEL_MIN_G = 0.5
"""Below this much gravity across the y and z axes, heel is not reported. From
enchantee_racing store.py."""

EARTH_RADIUS_M = 6371000.0
"""Mean Earth radius, as event_recorder uses for distance sailed."""


def _num(*values: Any) -> bool:
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
               for v in values)


def norm360(deg: float) -> float:
    """A bearing in [0, 360)."""
    return deg % 360.0


def norm180(deg: float) -> float:
    """An angle in (-180, 180], port negative. Identical to enchantee_racing engine/nav.py."""
    d = (deg + 180.0) % 360.0 - 180.0
    return 180.0 if d == -180.0 else d


def twa(twd: Optional[float], hdg: Optional[float]) -> Optional[float]:
    """True wind angle: the true wind direction seen from the bow, norm180(twd - hdg)."""
    if not _num(twd, hdg):
        return None
    return norm180(twd - hdg)


def awa(measured: Optional[float], awd: Optional[float] = None,
        hdg: Optional[float] = None) -> Optional[float]:
    """Apparent wind angle: the masthead's bow-relative reading if there is one, else the
    apparent wind bearing seen from the bow, norm180(awd - hdg). As enchantee_racing."""
    if _num(measured):
        return norm180(measured)
    if _num(awd, hdg):
        return norm180(awd - hdg)
    return None


def leeway(cog: Optional[float], hdg: Optional[float], sog: Optional[float],
           min_sog: float = LEEWAY_MIN_SOG_KT) -> Optional[float]:
    """COG - HDG, signed port negative, or None below min_sog.

    Not leeway alone: with no speed through the water it also carries tidal set and any
    compass error. Named for what the crew asked for (enchantee_racing DESIGN 9.12).
    """
    if not _num(cog, hdg, sog) or sog < min_sog:
        return None
    return norm180(cog - hdg)


def heel(acc_y: Optional[float], acc_z: Optional[float],
         min_g: float = HEEL_MIN_G) -> Optional[float]:
    """Heel in degrees, positive heeled to starboard, from the IMU's y and z in g.

    atan2(y, z). The sign was measured on a recorded race, not taken from the axis
    convention (enchantee_racing store.derive_heel).
    """
    if not _num(acc_y, acc_z) or math.hypot(acc_y, acc_z) < min_g:
        return None
    return math.degrees(math.atan2(acc_y, acc_z))


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres, haversine on a sphere. As event_recorder."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def integrate_wh(samples: Iterable[Tuple[float, float]],
                 max_gap_s: Optional[float] = None) -> float:
    """Energy in Wh from (seconds, watts) samples in time order, by the trapezoid rule.

    As event_recorder's energy statistics. With max_gap_s, an interval longer than that is
    not bridged: a sensor that went quiet for an hour contributes nothing for that hour
    rather than its last two readings' average (DESIGN 6.3).
    """
    total = 0.0
    prev: Optional[Tuple[float, float]] = None
    for t, w in samples:
        if prev is not None:
            dt = t - prev[0]
            if dt > 0 and (max_gap_s is None or dt <= max_gap_s):
                total += (w + prev[1]) / 2.0 * dt / 3600.0
        prev = (t, w)
    return total


# --------------------------------------------------------------------------------------
# Derived operators (DESIGN 6.3)
#
# The stateful ones accumulate over a period that restarts at a local-time boundary:
# midnight by default, "09:00" for rain and battery out, "month" or "year". Each is fed
# (value, t) pairs in time order and can be seeded with what Influx says happened since
# the boundary, so a restart mid-day resumes the right figure. No I/O here: emon_live
# does the feeding, the seeding queries and the publishing.
#
# Local time is the process's (TZ in the container), as Node-RED's crontab resets were.
# --------------------------------------------------------------------------------------

MAX_GAP_S = 300.0
"""integrate does not bridge a gap longer than this (DESIGN 6.3)."""

PERIODS = ("month", "year")


def _hhmm(reset: str) -> Tuple[int, int]:
    try:
        hh, mm = reset.split(":")
        hh, mm = int(hh), int(mm)
    except (AttributeError, ValueError):
        raise ValueError(f"reset must be 'HH:MM', 'month' or 'year', not {reset!r}") from None
    if not (0 <= hh < 24 and 0 <= mm < 60):
        raise ValueError(f"reset out of range: {reset!r}")
    return hh, mm


def period_start(t: float, reset: str = "00:00") -> float:
    """The most recent period boundary at or before t, in local time.

    "HH:MM" is a daily boundary at that time; "month" and "year" start at local midnight
    on the 1st. mktime normalises day 0 to the last day of the month before, which is how
    "yesterday's 09:00" is found on the 1st.
    """
    lt = _time.localtime(t)
    if reset in PERIODS:
        month = lt.tm_mon if reset == "month" else 1
        return _time.mktime((lt.tm_year, month, 1, 0, 0, 0, 0, 0, -1))
    hh, mm = _hhmm(reset)
    start = _time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hh, mm, 0, 0, 0, -1))
    if start > t:
        start = _time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday - 1, hh, mm, 0, 0, 0, -1))
    return start


class PeriodOperator:
    """Base for the operators that restart at a boundary. `value` is None until there is
    something to report."""

    def __init__(self, reset: str = "00:00") -> None:
        period_start(0.0, reset)          # validate now, not at the first reading
        self.reset = reset
        self.start: Optional[float] = None

    def roll(self, t: float) -> bool:
        """Start a new period if t is past the boundary. True when one was started, so a
        caller ticking the clock knows to republish the zeroed figure."""
        start = period_start(t, self.reset)
        if start == self.start:
            return False
        rolled = self.start is not None
        self.start = start
        self.clear()
        return rolled

    def clear(self) -> None:
        raise NotImplementedError

    def update(self, value: float, t: float) -> Optional[float]:
        raise NotImplementedError

    @property
    def value(self) -> Optional[float]:
        raise NotImplementedError


class DailyDelta(PeriodOperator):
    """A counter's increase since the boundary, times `scale` (op daily_delta).

    The baseline is the first value seen in the period, as Node-RED's DayStartPulse was,
    or the seeded one. The total never goes backwards. A reading below the last one is
    set aside, because three different things produce one, all seen at shannstainable:

    - a relayed copy of a packet, arriving a second after the direct one with the count
      it had when it left: Consumed alternated 58620648, 58620640, 58620648 on 23 Oct;
    - a corrupted line: at 13:17:16 that day one serial line carried another node's
      numbers, putting every power-board counter at a few thousand for one reading;
    - a node restarting, whose counter begins again from zero.

    Only the last is a change to act on. It is recognised by CONFIRM readings in a row
    below the last, rising among themselves, the first of them under half the old value:
    then what had accumulated is carried and counting goes on from the new value (where
    Node-RED's figure went negative). The same run of readings carrying on from the one
    before the last instead means the last was a spike upwards, and it is undone. Any
    other reading below the last is ignored. Readings that go forwards are never delayed.
    """

    CONFIRM = 3

    def __init__(self, reset: str = "00:00", scale: float = 1.0) -> None:
        super().__init__(reset)
        self.scale = scale
        self.clear()

    def clear(self) -> None:
        self.base: Optional[float] = None
        self.last: Optional[float] = None
        self.prev: Optional[float] = None     # the accepted reading before last
        self.below: List[float] = []          # readings in a row lower than last
        self.carry = 0.0

    def seed(self, first_value: float, t: float) -> None:
        """The counter's first value since the boundary, from Influx."""
        self.roll(t)
        self.base = self.last = float(first_value)

    def update(self, value: float, t: float) -> Optional[float]:
        self.roll(t)
        value = float(value)
        if self.base is None:
            self.base = self.last = value
            return self.value
        if value >= self.last:
            self.below = []
            self.prev, self.last = self.last, value
            return self.value
        self.below.append(value)
        run = self.below
        if len(run) >= self.CONFIRM and all(a <= b for a, b in zip(run, run[1:])):
            if self.prev is not None and run[0] >= self.prev:
                self.prev, self.last = self.prev, run[-1]       # last was a spike: undo it
            elif run[0] < self.last / 2:
                self.carry += self.last - self.base             # a restart: carry the day
                self.base, self.prev, self.last = run[0], None, run[-1]
            self.below = []
        return self.value

    @property
    def value(self) -> Optional[float]:
        if self.base is None or self.last is None:
            return None
        return (self.last - self.base + self.carry) * self.scale


class Integrate(PeriodOperator):
    """Power to energy since the boundary, by the trapezoid rule (op integrate).

    W in, Wh out with the default `per_s` of 1/3600. A gap over `max_gap_s` is not
    bridged, as integrate_wh. The interval across a boundary is dropped rather than
    split: at most one sample interval, and it keeps yesterday's energy out of today.
    """

    def __init__(self, reset: str = "00:00", max_gap_s: float = MAX_GAP_S,
                 per_s: float = 1.0 / 3600.0) -> None:
        super().__init__(reset)
        self.max_gap_s = max_gap_s
        self.per_s = per_s
        self.clear()

    def clear(self) -> None:
        self.total: Optional[float] = None
        self.prev: Optional[Tuple[float, float]] = None

    def seed(self, total: float, t: float) -> None:
        self.roll(t)
        self.total = float(total)

    def update(self, value: float, t: float) -> Optional[float]:
        self.roll(t)
        value = float(value)
        if self.total is None:
            self.total = 0.0
        if self.prev is not None:
            dt = t - self.prev[0]
            if 0 < dt <= self.max_gap_s:
                self.total += (value + self.prev[1]) / 2.0 * dt * self.per_s
        if self.prev is None or t >= self.prev[0]:
            self.prev = (t, value)
        return self.total

    @property
    def value(self) -> Optional[float]:
        return self.total


class Extreme(PeriodOperator):
    """The largest (or smallest) value since the boundary (ops daily_max, daily_min).

    With `by_abs`, the value of largest magnitude, sign kept: a battery mid-point
    voltage is as bad 1.2 V low as 1.2 V high (Node-RED's Battery Voltage node).
    `ignore_zero` skips readings of exactly 0, which that node also did, since a monitor
    channel reads 0 when its tap is disconnected.
    """

    def __init__(self, reset: str = "00:00", kind: str = "max", by_abs: bool = False,
                 ignore_zero: bool = False) -> None:
        super().__init__(reset)
        if kind not in ("max", "min"):
            raise ValueError(f"kind must be max or min, not {kind!r}")
        self.kind, self.by_abs, self.ignore_zero = kind, by_abs, ignore_zero
        self.clear()

    def clear(self) -> None:
        self.best: Optional[float] = None

    def _better(self, a: float, b: float) -> bool:
        ka, kb = (abs(a), abs(b)) if self.by_abs else (a, b)
        return ka > kb if self.kind == "max" else ka < kb

    def seed(self, value: float, t: float) -> None:
        self.roll(t)
        self.best = float(value)

    def update(self, value: float, t: float) -> Optional[float]:
        self.roll(t)
        value = float(value)
        if not (self.ignore_zero and value == 0.0):
            if self.best is None or self._better(value, self.best):
                self.best = value
        return self.best

    @property
    def value(self) -> Optional[float]:
        return self.best


class Mean(PeriodOperator):
    """The mean of the readings since the boundary (op mean), optionally of positive ones
    only: Node-RED's "average import" behind its export estimate."""

    def __init__(self, reset: str = "00:00", positive_only: bool = False) -> None:
        super().__init__(reset)
        self.positive_only = positive_only
        self.clear()

    def clear(self) -> None:
        self.total = 0.0
        self.count = 0

    def seed(self, mean: float, count: int, t: float) -> None:
        self.roll(t)
        self.total, self.count = float(mean) * int(count), int(count)

    def update(self, value: float, t: float) -> Optional[float]:
        self.roll(t)
        value = float(value)
        if not self.positive_only or value > 0:
            self.total += value
            self.count += 1
        return self.value

    @property
    def value(self) -> Optional[float]:
        return self.total / self.count if self.count else None


def window_end(start: float, end: str) -> float:
    """The first local time `end` ("HH:MM") strictly after `start`."""
    hh, mm = _hhmm(end)
    lt = _time.localtime(start)
    t = _time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hh, mm, 0, 0, 0, -1))
    if t <= start:
        t = _time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + 1, hh, mm, 0, 0, 0, -1))
    return t


class WindowDelta(PeriodOperator):
    """A counter's increase over a daily window, reported once the window has closed and
    held until the next one closes (op window_delta).

    Node-RED's "battery out to 9am": out from 00:00 to 09:00 today, shown from 09:00
    until 09:00 tomorrow. `reset` is the window's start; `end` its close.
    """

    def __init__(self, reset: str = "00:00", end: str = "09:00", scale: float = 1.0) -> None:
        super().__init__(reset)
        _hhmm(end)
        self.end, self.scale = end, scale
        self.held: Optional[float] = None
        self.clear()

    def clear(self) -> None:
        self.base: Optional[float] = None
        self.last: Optional[float] = None

    def _close(self, t: float) -> bool:
        """Report the open window if t is past its close. True when the value changed."""
        if self.start is None or self.base is None or t < window_end(self.start, self.end):
            return False
        self.held = (self.last - self.base) * self.scale
        self.clear()
        return True

    def roll(self, t: float) -> bool:
        closed = self._close(t)
        start = period_start(t, self.reset)
        if start != self.start:
            self.start = start
            self.clear()
        return closed

    def update(self, value: float, t: float) -> Optional[float]:
        self.roll(t)
        if t < window_end(self.start, self.end):
            value = float(value)
            if self.base is None:
                self.base = value
            self.last = value
        return self.held

    @property
    def value(self) -> Optional[float]:
        return self.held


# --------------------------------------------------------------------------------------
# Expressions (op expr)
#
# Arithmetic over named feeds, written with the feed names in braces, the same as a
# page's placeholders: "{derived/import/today} / 1000 * 0.262". Parsed once with ast and
# checked against a short list of node types, so a settings file cannot run code.
# --------------------------------------------------------------------------------------

EXPR_FUNCTIONS: Dict[str, Callable[..., Any]] = {
    "min": min, "max": max, "abs": abs, "round": round,
    "norm180": lambda d: norm180(d), "norm360": lambda d: norm360(d),
}

_EXPR_NODES = (
    _ast.Expression, _ast.BinOp, _ast.UnaryOp, _ast.BoolOp, _ast.Compare, _ast.IfExp,
    _ast.Call, _ast.Name, _ast.Load, _ast.Constant,
    _ast.Add, _ast.Sub, _ast.Mult, _ast.Div, _ast.FloorDiv, _ast.Mod, _ast.Pow,
    _ast.USub, _ast.UAdd, _ast.Not, _ast.And, _ast.Or,
    _ast.Lt, _ast.LtE, _ast.Gt, _ast.GtE, _ast.Eq, _ast.NotEq,
)


class Expr:
    """A compiled expression. `names` are the feeds it reads; call it with a mapping
    from name to value. Any input missing or None gives None, never a guess, unless
    `defaults` names a value for it: Node-RED's `flow.get(..) || 0`, where that was the
    intended behaviour (the export estimate's average import before the first import)."""

    def __init__(self, text: str, defaults: Optional[Mapping[str, float]] = None) -> None:
        self.text = text
        self.defaults = dict(defaults or {})
        self.names: List[str] = []
        source, pos = [], 0
        while True:
            start = text.find("{", pos)
            if start == -1:
                source.append(text[pos:])
                break
            end = text.find("}", start)
            if end == -1:
                raise ValueError(f"unclosed {{ in expression {text!r}")
            name = text[start + 1:end].strip()
            if name not in self.names:
                self.names.append(name)
            source.append(text[pos:start])
            source.append(f"_v{self.names.index(name)}")
            pos = end + 1
        # Whitespace collapsed outside the braces, so an expression may be folded over
        # several lines in YAML; the feed names have already become _vN.
        tree = _ast.parse(" ".join("".join(source).split()), mode="eval")
        for node in _ast.walk(tree):
            if not isinstance(node, _EXPR_NODES):
                raise ValueError(f"{type(node).__name__} not allowed in expression {text!r}")
            if isinstance(node, _ast.Constant) and not isinstance(node.value, (int, float)):
                raise ValueError(f"only numbers are allowed as constants in {text!r}")
            if isinstance(node, _ast.Name) and not (
                    node.id.startswith("_v") or node.id in EXPR_FUNCTIONS):
                raise ValueError(f"unknown name {node.id!r} in {text!r}; feeds go in braces")
            if isinstance(node, _ast.Call) and not (
                    isinstance(node.func, _ast.Name) and node.func.id in EXPR_FUNCTIONS):
                raise ValueError(f"only {sorted(EXPR_FUNCTIONS)} may be called in {text!r}")
        self._code = compile(tree, "<expr>", "eval")

    def __call__(self, values: Mapping[str, Any]) -> Optional[float]:
        env: Dict[str, Any] = {"__builtins__": {}}
        env.update(EXPR_FUNCTIONS)
        for i, name in enumerate(self.names):
            v = values.get(name)
            if v is None:
                v = self.defaults.get(name)
            if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
                return None
            env[f"_v{i}"] = v
        try:
            result = eval(self._code, env)  # noqa: S307  (checked node by node above)
        except (ArithmeticError, ValueError, TypeError):
            return None
        if isinstance(result, bool):
            return 1.0 if result else 0.0
        # + 0.0 turns the -0.0 of max(-0.0, 0) into 0.0.
        return float(result) + 0.0 if isinstance(result, (int, float)) else None


__all__ = [
    "ENVELOPE_VERSION", "TOPIC_ROOT", "CONFIG_TOPIC", "DERIVED_NODE", "UNUSED",
    "Reading", "topic_for", "feed_key", "plain", "envelope", "envelope_json",
    "parse_number", "parse", "Catalogue", "Store",
    "LEEWAY_MIN_SOG_KT", "HEEL_MIN_G", "EARTH_RADIUS_M",
    "norm360", "norm180", "twa", "awa", "leeway", "heel", "distance_m", "integrate_wh",
    "MAX_GAP_S", "period_start", "PeriodOperator", "DailyDelta", "Integrate", "Extreme",
    "Mean", "WindowDelta", "window_end", "Expr", "EXPR_FUNCTIONS",
]
