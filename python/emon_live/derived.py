"""derived.yml: values computed from feeds, published as emon/derived/<id> (DESIGN 6.3).

A site's derived.yml has two parts:

    influx:                       # where each input lives in Influx, for replay on start
      Power board / Imported: power power/0/3        # measurement, then the sensor tag
    derived:
      - id: import/today
        op: daily_delta
        feed: Power board / Imported (pulse)
        unit: Wh

Each entry's result is the feed `derived/<id>`, usable as an input by later entries and
by pages. The operators themselves are emon_feed's; this module wires them to feeds.

    op            reads                 options
    daily_delta   feed (a counter)      reset ("00:00", "09:00", "month", "year"), scale
    window_delta  feed (a counter)      reset (window start), end ("09:00"), scale
    integrate     feed (W)              reset, max_gap (s); gives Wh
    daily_max     feed                  reset, abs, ignore_zero
    daily_min     feed                  reset
    mean          feed                  reset, positive_only
    sum           of: [feeds]           a missing input is left out; none at all gives none
    expr          expr: "{a} - {b}"     defaults: {feed: value}

Every entry also takes `unit`, `kind` and `decimals`.

Pulse counters are already in Wh: the nodes apply pN_wPerPulse themselves (checked against
integrated power, 21 Oct 2026), so `scale` defaults to 1, as Node-RED's daily totals did.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from state import emon_feed

log = logging.getLogger(__name__)

PREFIX = emon_feed.DERIVED_NODE + "/"

STATEFUL = {
    "daily_delta": lambda s: emon_feed.DailyDelta(s.get("reset", "00:00"), float(s.get("scale", 1.0))),
    "window_delta": lambda s: emon_feed.WindowDelta(s.get("reset", "00:00"), s.get("end", "09:00"),
                                                    float(s.get("scale", 1.0))),
    "integrate": lambda s: emon_feed.Integrate(s.get("reset", "00:00"),
                                               float(s.get("max_gap", emon_feed.MAX_GAP_S))),
    "daily_max": lambda s: emon_feed.Extreme(s.get("reset", "00:00"), "max", bool(s.get("abs")),
                                             bool(s.get("ignore_zero"))),
    "daily_min": lambda s: emon_feed.Extreme(s.get("reset", "00:00"), "min", bool(s.get("abs")),
                                             bool(s.get("ignore_zero"))),
    "mean": lambda s: emon_feed.Mean(s.get("reset", "00:00"), bool(s.get("positive_only"))),
}
STATELESS = ("sum", "expr")
TOTALS = ("daily_delta", "integrate")
"""Ops whose new period starts from zero, so a boundary publishes 0 at once rather than
leaving yesterday's total up until the first reading of the day."""

DEFAULT_UNITS = {"integrate": "Wh"}

LIVE_S = 900.0
"""Replay depth for an input that only feeds live expressions."""


@dataclass
class Entry:
    id: str
    op: str
    inputs: List[str]
    spec: Dict[str, Any]
    operator: Any = None
    expr: Optional[emon_feed.Expr] = None
    unit: str = ""
    kind: str = ""
    decimals: Optional[int] = None

    @property
    def key(self) -> str:
        return PREFIX + self.id


def parse_series(text: str) -> Tuple[str, str]:
    """"power power/0/3" -> ("power", "power/0/3")."""
    parts = str(text).split()
    if len(parts) != 2:
        raise ValueError(f"influx series must be 'measurement sensor', not {text!r}")
    return parts[0], parts[1]


class Derived:
    """Every entry of one derived.yml, fed readings, giving derived readings."""

    def __init__(self, doc: Optional[Dict[str, Any]] = None) -> None:
        doc = doc or {}
        self.influx: Dict[str, Tuple[str, str]] = {
            name: parse_series(series) for name, series in (doc.get("influx") or {}).items()}
        self.entries: Dict[str, Entry] = {}
        for spec in doc.get("derived") or []:
            entry = self._entry(spec)
            if entry.key in self.entries:
                raise ValueError(f"derived id {entry.id!r} appears twice")
            self.entries[entry.key] = entry
        self.order = self._order()
        self.consumers: Dict[str, List[Entry]] = {}
        for key in self.order:
            for name in self.entries[key].inputs:
                self.consumers.setdefault(name, []).append(self.entries[key])
        self.latest: Dict[str, float] = {}
        self.last_t: Dict[str, float] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _entry(spec: Dict[str, Any]) -> Entry:
        if not isinstance(spec, dict) or not spec.get("id") or not spec.get("op"):
            raise ValueError(f"a derived entry needs an id and an op: {spec!r}")
        op, ident = spec["op"], str(spec["id"]).strip("/")
        entry = Entry(id=ident, op=op, inputs=[], spec=spec,
                      unit=spec.get("unit", DEFAULT_UNITS.get(op, "")),
                      kind=spec.get("kind", "energy" if op in TOTALS else ""),
                      decimals=spec.get("decimals"))
        if op in STATEFUL:
            if not spec.get("feed"):
                raise ValueError(f"derived/{ident}: {op} needs a feed")
            entry.inputs = [spec["feed"]]
            entry.operator = STATEFUL[op](spec)
        elif op == "sum":
            entry.inputs = list(spec.get("of") or [])
            if not entry.inputs:
                raise ValueError(f"derived/{ident}: sum needs 'of'")
        elif op == "expr":
            entry.expr = emon_feed.Expr(spec.get("expr", ""), spec.get("defaults"))
            entry.inputs = list(entry.expr.names)
        else:
            raise ValueError(f"derived/{ident}: unknown op {op!r}")
        return entry

    def _order(self) -> List[str]:
        """Entries so that each comes after the derived feeds it reads. A cycle is an
        error in the file, reported by the ids in it."""
        order: List[str] = []
        state: Dict[str, int] = {}

        def visit(key: str, path: List[str]) -> None:
            if state.get(key) == 2:
                return
            if state.get(key) == 1:
                raise ValueError("derived.yml has a cycle: " + " -> ".join(path + [key]))
            state[key] = 1
            for name in self.entries[key].inputs:
                if name in self.entries:
                    visit(name, path + [key])
            state[key] = 2
            order.append(key)

        for key in self.entries:
            visit(key, [])
        return order

    def owns(self, key: str) -> bool:
        """A derived feed computed here, so its echo from the broker is not an input."""
        return key in self.entries

    def inputs_outside(self) -> List[str]:
        """Feeds read that no entry here computes: what has to arrive from MQTT."""
        return sorted({n for e in self.entries.values() for n in e.inputs if n not in self.entries})

    # --- feeding ----------------------------------------------------------------------

    def on_value(self, key: str, value: Any, t: float) -> List[emon_feed.Reading]:
        """One input value arrived; returns every derived reading it changed, in order.

        A value no newer than the last one seen for that feed is ignored. That is what
        happens to every retained message received after the start-up replay: older than
        the replay's last row, and for a counter, smaller, which daily_delta would take
        for a counter reset and count the day twice.
        """
        out: List[emon_feed.Reading] = []
        if key not in self.consumers or not _number(value) or t is None:
            return out
        with self._lock:
            if t <= self.last_t.get(key, float("-inf")):
                return out
            self.last_t[key] = t
            self._propagate(key, float(value), t, out)
        return out

    def _propagate(self, key: str, value: float, t: float, out: List[emon_feed.Reading]) -> None:
        self.latest[key] = value
        for entry in self.consumers.get(key, ()):
            result = self._compute(entry, value, t)
            if result is not None:
                out.append(self._reading(entry, result, t))
                self._propagate(entry.key, result, t, out)

    def _compute(self, entry: Entry, value: float, t: float) -> Optional[float]:
        if entry.operator is not None:
            return entry.operator.update(value, t)
        if entry.op == "sum":
            present = [self.latest[n] for n in entry.inputs if n in self.latest]
            return sum(present) if present else None
        return entry.expr(self.latest)

    def tick(self, now: float) -> List[emon_feed.Reading]:
        """Roll every period that has passed its boundary, with no reading needed, and
        publish what changed: totals go to 0 at midnight, a 09:00 window closes."""
        out: List[emon_feed.Reading] = []
        with self._lock:
            for key in self.order:
                entry = self.entries[key]
                if entry.operator is None or not entry.operator.roll(now):
                    continue
                value = entry.operator.value
                if value is None and entry.op in TOTALS:
                    value = 0.0
                if value is not None:
                    out.append(self._reading(entry, value, now))
                    self._propagate(entry.key, value, now, out)
        return out

    def _reading(self, entry: Entry, value: float, t: float) -> emon_feed.Reading:
        if entry.decimals is not None:
            value = round(value, int(entry.decimals))
        return emon_feed.Reading(node=emon_feed.DERIVED_NODE, sub=None, field=entry.id,
                                 value=value, unit=entry.unit, kind=entry.kind, t=t)

    # --- seeding (influx.py does the querying) ----------------------------------------

    def seed_baseline(self, key: str, first_value: float, t: float) -> None:
        self.entries[key].operator.seed(first_value, t)

    def replay_since(self, key: str, now: float) -> float:
        """How far back an input has to be replayed to rebuild everything it feeds: the
        earliest daily boundary among the operators downstream of it, following chains
        through derived feeds, and for a window_delta still open, the one before. An input that
        feeds only live expressions needs just its latest value: LIVE_S back. Month and
        year deltas are seeded with a baseline instead and do not count here."""
        since, seen, todo = now - LIVE_S, set(), [key]
        while todo:
            for entry in self.consumers.get(todo.pop(), ()):
                if entry.key in seen:
                    continue
                seen.add(entry.key)
                todo.append(entry.key)
                op = entry.operator
                if op is None or entry.spec.get("reset") in emon_feed.PERIODS:
                    continue
                start = emon_feed.period_start(now, op.reset)
                if entry.op == "window_delta" and now < emon_feed.window_end(start, op.end):
                    start = emon_feed.period_start(start - 1.0, op.reset)  # today's still open
                since = min(since, start)
        return since

    def long_periods(self) -> List[Entry]:
        """Entries reset monthly or yearly: seeded from Influx's first value, not replayed."""
        return [e for e in self.entries.values()
                if e.operator is not None and e.spec.get("reset") in emon_feed.PERIODS]


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def load(path) -> Derived:
    import yaml  # here, so state.py and the tests of everything else need no yaml
    with open(path, encoding="utf-8") as f:
        return Derived(yaml.safe_load(f) or {})
