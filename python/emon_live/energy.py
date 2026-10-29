"""The energy flow a Sankey tile draws, over a chosen period (DESIGN 6.5).

A site's derived.yml may carry a `sankey:` block: the flows into and out of the house,
each one both a live feed (for "now", in W) and a recipe for the energy over a past
window (in Wh). `/api/energy?period=...` answers with the flows and their values, and
`ui/tiles/sankey.js` draws them.

    sankey:
      hub: House
      flows:
        - id: solar
          label: Solar
          side: source                  # source (left) | load (right)
          domain: solar                 # a tile domain, for the colour
          now: derived/solar/now        # the live W feed
          window: {method: integral, of: [Inverter One / pvInputPower, ...]}
      other: {id: other, label: Other, side: load, domain: other}

`other` is not measured: it is what the sources carry that the named loads do not
account for, so the diagram balances by construction. When it would be negative the
named loads already exceed the sources, which the response reports as `balance`.

Three window methods, each one or two **bounded** Influx queries (influx.py says why
that matters):

    counter   last(value) - first(value), summed over `of`. The pulse meters are already
              Wh (derived.py), so this is the energy itself.
    integral  integral(value, 1s) / 3600, summed over `of`. For a feed in W.
    expr      an expression in W over bucketed means of its inputs, trapezoid-integrated.
              This is how the export estimate, which no single series holds, is answered
              for a past window. `scalars` supplies the window-wide aggregates it needs.

The buckets are coarse (a minute for a day, longer for a month), so an `expr` figure is
an estimate, close but not equal to the live `derived/...` total that integrates every
reading. The response says so in `approx`.

Periods are "now", "today" (since midnight), "yesterday" (the whole of it), "week" and
"month" (the last 7 and 30 days, to now).
"""

from __future__ import annotations

import logging
import threading
import time as _time
from typing import Any, Dict, List, Optional, Tuple

from state import emon_feed

log = logging.getLogger(__name__)

PERIODS = ("now", "today", "yesterday", "week", "month")
LABELS = {"now": "Now", "today": "Today", "yesterday": "Yesterday",
          "week": "7 days", "month": "30 days"}

STEP_S = {"today": 60, "yesterday": 60, "week": 300, "month": 900}
"""Bucket width for the `expr` method. A month at 15 min is 2 880 buckets a series."""

MAX_GAP_S = 300.0
"""A gap longer than this is not bridged when integrating, as derived.yml's integrate."""

TTL_S = {"today": 60.0, "yesterday": 3600.0, "week": 600.0, "month": 600.0}
"""How long an answer is reused. Several screens poll; the queries must not be repeated
once a screen. A closed period cannot change, so yesterday is held for an hour."""

SIDES = ("source", "load")


class Flow:
    """One ribbon: where it is, what it is called, and how to value it."""

    def __init__(self, spec: Dict[str, Any]) -> None:
        if not isinstance(spec, dict) or not spec.get("id"):
            raise ValueError(f"a sankey flow needs an id: {spec!r}")
        self.id = str(spec["id"])
        self.label = str(spec.get("label", self.id))
        self.side = str(spec.get("side", "load"))
        if self.side not in SIDES:
            raise ValueError(f"sankey flow {self.id!r}: side must be source or load")
        self.domain = str(spec.get("domain", "other"))
        self.now = spec.get("now")
        self.window = spec.get("window") or {}
        self.method = str(self.window.get("method", "")) if self.window else ""
        self.of: List[str] = list(self.window.get("of") or [])
        self.expr: Optional[emon_feed.Expr] = None
        self.scalars: Dict[str, Dict[str, Any]] = {}
        if self.method == "expr":
            self.scalars = dict(self.window.get("scalars") or {})
            self.expr = emon_feed.Expr(self.window.get("expr", ""), self.window.get("defaults"))
            self.of = [n for n in self.expr.names if n not in self.scalars]
        elif self.method and self.method not in ("counter", "integral"):
            raise ValueError(f"sankey flow {self.id!r}: unknown method {self.method!r}")

    @property
    def approx(self) -> bool:
        return self.method == "expr"

    def feeds(self) -> List[str]:
        """Every feed name this flow refers to, for the page linter."""
        names = list(self.of)
        if self.now:
            names.append(self.now)
        for scalar in self.scalars.values():
            if scalar.get("feed"):
                names.append(scalar["feed"])
        return names


class Sankey:
    """The `sankey:` block of one derived.yml."""

    def __init__(self, doc: Optional[Dict[str, Any]] = None) -> None:
        block = (doc or {}).get("sankey") or {}
        self.hub = str(block.get("hub", "House"))
        self.flows = [Flow(spec) for spec in block.get("flows") or []]
        seen = set()
        for flow in self.flows:
            if flow.id in seen:
                raise ValueError(f"sankey flow id {flow.id!r} appears twice")
            seen.add(flow.id)
        other = block.get("other")
        self.other = Flow(other) if other else None
        self.periods = [p for p in (block.get("periods") or PERIODS) if p in PERIODS]
        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def __bool__(self) -> bool:
        return bool(self.flows)

    def feeds(self) -> List[str]:
        names: List[str] = []
        for flow in self.flows:
            names.extend(flow.feeds())
        return names

    # --- answering ---------------------------------------------------------------------

    def document(self, period: str, state, influx=None, now: Optional[float] = None) -> Dict[str, Any]:
        """The flows and their values for one period. Never raises on a query that fails:
        that flow comes back with no value and is named in `failed`, so the rest of the
        diagram still draws."""
        if period not in PERIODS:
            raise ValueError(f"unknown period {period!r}")
        now = state.clock() if now is None else now
        if period == "now":
            return self._finish(period, now, now, "W", self._live(state, now), [])
        cached = self._cached(period, now)
        if cached is not None:
            return cached
        start, end = window(period, now)
        values: Dict[str, Optional[float]] = {}
        failed: List[str] = []
        for flow in self.flows:
            if influx is None or not flow.method:
                values[flow.id] = None
                failed.append(flow.id)
                continue
            try:
                values[flow.id] = self._over(flow, influx, start, end)
            except Exception as ex:
                log.error("energy %s: flow %s failed: %s", period, flow.id, ex)
                values[flow.id] = None
                failed.append(flow.id)
        doc = self._finish(period, start, end, "Wh", values, failed)
        with self._lock:
            self._cache[period] = (now, doc)
        return doc

    def _cached(self, period: str, now: float) -> Optional[Dict[str, Any]]:
        with self._lock:
            got = self._cache.get(period)
        if got is None:
            return None
        at, doc = got
        if now - at > TTL_S.get(period, 60.0):
            return None
        return doc if still_same_window(period, doc["from"], now) else None

    def _live(self, state, now: float) -> Dict[str, Optional[float]]:
        snapshot = state.store.snapshot()
        values: Dict[str, Optional[float]] = {}
        for flow in self.flows:
            reading = snapshot.get(flow.now) if flow.now else None
            value = None if reading is None else reading.value
            values[flow.id] = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
        return values

    def _finish(self, period: str, start: float, end: float, unit: str,
                values: Dict[str, Optional[float]], failed: List[str]) -> Dict[str, Any]:
        sources = sum(max(0.0, values.get(f.id) or 0.0) for f in self.flows if f.side == "source")
        loads = sum(max(0.0, values.get(f.id) or 0.0) for f in self.flows if f.side == "load")
        out = []
        for flow in self.flows:
            value = values.get(flow.id)
            out.append({"id": flow.id, "label": flow.label, "side": flow.side,
                        "domain": flow.domain, "value": None if value is None else round(value, 1),
                        "approx": flow.approx})
        if self.other is not None:
            out.append({"id": self.other.id, "label": self.other.label, "side": self.other.side,
                        "domain": self.other.domain, "value": round(max(0.0, sources - loads), 1),
                        "approx": True})
        return {"period": period, "label": LABELS[period], "unit": unit, "hub": self.hub,
                "from": start, "to": end, "flows": out, "failed": failed,
                "balance": round(sources - loads, 1)}

    # --- the three methods --------------------------------------------------------------

    def _over(self, flow: Flow, influx, start: float, end: float) -> Optional[float]:
        if flow.method == "counter":
            return _sum_or_none(influx.counter_delta(name, start, end) for name in flow.of)
        if flow.method == "integral":
            return _sum_or_none(influx.integral_wh(name, start, end) for name in flow.of)
        return self._expr_over(flow, influx, start, end)

    def _expr_over(self, flow: Flow, influx, start: float, end: float) -> Optional[float]:
        step = STEP_S[_period_of(start, end)] if _period_of(start, end) else 60
        fixed: Dict[str, float] = {}
        for name, spec in flow.scalars.items():
            value = influx.aggregate(spec["feed"], start, end, str(spec.get("agg", "mean")),
                                     positive_only=bool(spec.get("positive_only")))
            fixed[name] = 0.0 if value is None else value
        series = {name: dict(influx.buckets(name, start, end, step, "mean")) for name in flow.of}
        times = sorted({t for rows in series.values() for t in rows})
        if not times:
            return None
        carried = dict(fixed)
        points: List[Tuple[float, float]] = []
        for t in times:
            for name in flow.of:
                if t in series[name]:
                    carried[name] = series[name][t]
            if any(name not in carried for name in flow.of):
                continue            # not every input has had a first value yet
            value = flow.expr(carried)
            if value is not None:
                points.append((t, float(value)))
        # Consecutive buckets are `step` apart, and for week and month that is wider than
        # MAX_GAP_S: the gap rule must allow one bucket, or a month integrates to nothing.
        # A bucket missing altogether (fill(none)) still leaves a gap that is not bridged.
        return _trapezoid_wh(points, max(MAX_GAP_S, float(step)))


def still_same_window(period: str, start: float, now: float) -> bool:
    """Whether an answer for a window that began at `start` still answers `period` now.

    Today and yesterday are calendar days: held across midnight, an answer would be for
    the wrong day, so their start must not have moved. 7 and 30 days roll back from now,
    so their start moves every second and the cache's TTL alone decides; comparing the
    start there, as this first did, meant the cache never answered them at all.
    """
    if period in ("week", "month"):
        return True
    begun, _end = window(period, now)
    return abs(start - begun) < 1.0


def window(period: str, now: float) -> Tuple[float, float]:
    """(start, end) in seconds since the epoch, in this machine's local day."""
    midnight = emon_feed.period_start(now, "00:00")
    if period == "today":
        return midnight, now
    if period == "yesterday":
        return emon_feed.period_start(midnight - 1.0, "00:00"), midnight
    if period == "week":
        return now - 7 * 86400.0, now
    if period == "month":
        return now - 30 * 86400.0, now
    return now, now


def _period_of(start: float, end: float) -> Optional[str]:
    span = end - start
    if span <= 1.5 * 86400:
        return "today"
    return "week" if span <= 8 * 86400 else "month"


def _sum_or_none(values) -> Optional[float]:
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def _trapezoid_wh(points: List[Tuple[float, float]], max_gap_s: float = MAX_GAP_S) -> Optional[float]:
    """W against time to Wh, a gap over max_gap_s not bridged (derived.yml's integrate)."""
    if not points:
        return None
    total = 0.0
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        dt = t1 - t0
        if 0 < dt <= max_gap_s:
            total += (v0 + v1) / 2.0 * dt
    return total / 3600.0
