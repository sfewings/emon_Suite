"""Seed derived values from Influx on start, so a restart mid-day resumes the right totals
(DESIGN 4.4, 6.3).

Two ways, both through derived.Derived:

- **Replay.** Every input that derived.yml maps to an Influx series is read back from the
  earliest daily boundary to now and fed through the operators in time order. That
  rebuilds everything a day's worth of readings would have built, including chains such
  as the export estimate, which no single aggregate query can.
- **Baseline.** A month or year delta is not replayed; its counter's first value since
  the boundary is asked for instead.

**Every query names one series and carries a time bound.** An unbounded query against
this Influx (1.x, data since 2019) once froze the shannstainable Pi until its watchdog
reset it (HANDOVER, 21 Oct 2026). Each input is replayed only as far back as
Derived.replay_since says it must be, never more than 36 hours, and a baseline query
looks in a window that widens only if it finds nothing.

Standard library only: InfluxQL over HTTP, as the 1.x /query endpoint takes it.
"""

from __future__ import annotations

import json
import logging
import time as _time
import urllib.parse
import urllib.request
from typing import List, Optional, Tuple

from derived import Derived
from state import emon_feed

log = logging.getLogger(__name__)

MAX_REPLAY_S = 36 * 3600
"""A replay that would reach further back than this is cut short and logged."""

BASELINE_WINDOWS_S = (6 * 3600, 7 * 86400, 400 * 86400)


def _quote(text: str) -> str:
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _ident(text: str) -> str:
    return '"' + text.replace('"', '\\"') + '"'


class Influx:
    def __init__(self, url: str = "http://localhost:8086", db: str = "sensors",
                 timeout: float = 30.0) -> None:
        self.url, self.db, self.timeout = url.rstrip("/"), db, timeout

    def query(self, q: str) -> List[list]:
        """Rows of the first series, times as epoch milliseconds."""
        params = urllib.parse.urlencode({"db": self.db, "q": q, "epoch": "ms"})
        with urllib.request.urlopen(f"{self.url}/query?{params}", timeout=self.timeout) as r:
            body = json.loads(r.read().decode("utf-8"))
        result = (body.get("results") or [{}])[0]
        if "error" in result:
            raise RuntimeError(result["error"])
        series = result.get("series") or []
        return series[0]["values"] if series else []

    def rows(self, measurement: str, sensor: str, since: float, until: float) -> List[Tuple[float, float]]:
        q = (f"SELECT value FROM {_ident(measurement)} WHERE sensor = {_quote(sensor)} "
             f"AND time >= {int(since * 1000)}ms AND time <= {int(until * 1000)}ms")
        return [(ms / 1000.0, v) for ms, v in self.query(q) if isinstance(v, (int, float))]

    def first(self, measurement: str, sensor: str, since: float, until: float) -> Optional[Tuple[float, float]]:
        for window in BASELINE_WINDOWS_S:
            end = min(until, since + window)
            q = (f"SELECT first(value) FROM {_ident(measurement)} WHERE sensor = {_quote(sensor)} "
                 f"AND time >= {int(since * 1000)}ms AND time <= {int(end * 1000)}ms")
            rows = self.query(q)
            if rows:
                return rows[0][0] / 1000.0, rows[0][1]
            if end >= until:
                break
        return None


class Window:
    """Bounded window queries over feeds named as derived.yml names them (energy.py).

    Every query here carries both time bounds and one sensor, for the reason the module
    docstring gives. A feed with no Influx series answers None rather than raising: the
    Sankey draws the ribbons it can.
    """

    def __init__(self, influx: Influx, series_of: dict) -> None:
        self.influx, self.series_of = influx, series_of

    def _where(self, name: str, since: float, until: float, extra: str = "") -> Optional[str]:
        series = self.series_of.get(name)
        if series is None:
            log.warning("no influx series for %r, so it has no energy over a window", name)
            return None
        measurement, sensor = series
        return (f"FROM {_ident(measurement)} WHERE sensor = {_quote(sensor)}{extra} "
                f"AND time >= {int(since * 1000)}ms AND time <= {int(until * 1000)}ms")

    def _scalar(self, q: Optional[str]) -> Optional[float]:
        if q is None:
            return None
        rows = self.influx.query(q)
        value = rows[0][1] if rows else None
        return float(value) if isinstance(value, (int, float)) else None

    def counter_delta(self, name: str, since: float, until: float) -> Optional[float]:
        """last - first of a counter. A counter that rolled over or was reset inside the
        window would read negative; that is clamped to 0, as a lost reading, not a
        negative energy."""
        where = self._where(name, since, until)
        if where is None:
            return None
        rows = self.influx.query(f"SELECT first(value), last(value) {where}")
        if not rows or not isinstance(rows[0][1], (int, float)) or not isinstance(rows[0][2], (int, float)):
            return None
        return max(0.0, float(rows[0][2]) - float(rows[0][1]))

    def integral_wh(self, name: str, since: float, until: float) -> Optional[float]:
        """A feed in W, integrated over the window, in Wh."""
        value = self._scalar(self._maybe(f"SELECT integral(value, 1s) ", name, since, until))
        return None if value is None else value / 3600.0

    def aggregate(self, name: str, since: float, until: float, agg: str = "mean",
                  positive_only: bool = False) -> Optional[float]:
        if agg not in ("mean", "max", "min", "sum", "first", "last"):
            raise ValueError(f"unknown aggregate {agg!r}")
        extra = " AND value > 0" if positive_only else ""
        where = self._where(name, since, until, extra)
        return self._scalar(None if where is None else f"SELECT {agg}(value) {where}")

    def buckets(self, name: str, since: float, until: float, step: int,
                agg: str = "mean") -> List[Tuple[float, float]]:
        """(time, value) a bucket, empty buckets left out, so a gap stays a gap."""
        where = self._where(name, since, until)
        if where is None:
            return []
        q = f"SELECT {agg}(value) {where} GROUP BY time({int(step)}s) fill(none)"
        return [(ms / 1000.0, float(v)) for ms, v in self.influx.query(q)
                if isinstance(v, (int, float))]

    def _maybe(self, select: str, name: str, since: float, until: float) -> Optional[str]:
        where = self._where(name, since, until)
        return None if where is None else select + where


def seed(derived: Derived, influx: Influx, now: Optional[float] = None) -> List[emon_feed.Reading]:
    """Baselines, then the replay. Returns the derived readings as they stand at the end,
    one per feed, to publish. A failure is logged and seeding carries on without that
    feed: emon_live must start, with today's totals counting from now if need be."""
    now = _time.time() if now is None else now

    for entry in derived.long_periods():
        series = derived.influx.get(entry.inputs[0])
        if series is None:
            log.warning("derived/%s: no influx series for %r, so it counts from now",
                        entry.id, entry.inputs[0])
            continue
        start = emon_feed.period_start(now, entry.spec["reset"])
        try:
            found = influx.first(*series, since=start, until=now)
        except Exception as ex:
            log.error("derived/%s: baseline query failed: %s", entry.id, ex)
            continue
        if found is not None:
            derived.seed_baseline(entry.key, found[1], found[0])

    events: List[Tuple[float, str, float]] = []
    for name in derived.inputs_outside():
        series = derived.influx.get(name)
        if series is None:
            log.warning("no influx series for %r: what depends on it counts from now", name)
            continue
        since = derived.replay_since(name, now)
        if now - since > MAX_REPLAY_S:
            log.warning("replay of %r cut to %d h", name, MAX_REPLAY_S // 3600)
            since = now - MAX_REPLAY_S
        try:
            rows = influx.rows(*series, since=since, until=now)
        except Exception as ex:
            log.error("replay of %r failed: %s", name, ex)
            continue
        events.extend((t, name, v) for t, v in rows)
        log.debug("replay %s: %d rows", name, len(rows))
    events.sort(key=lambda e: e[0])

    latest = {}
    for t, name, value in events:
        for reading in derived.on_value(name, value, t):
            latest[reading.key] = reading
    for reading in derived.tick(now):
        latest[reading.key] = reading
    log.info("replayed %d readings into %d derived feeds", len(events), len(latest))
    return list(latest.values())
