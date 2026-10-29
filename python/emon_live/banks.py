"""Battery bank health and status, over a chosen period (DESIGN 6.6).

A site's derived.yml may carry a `banks:` block: each battery bank's cells (or series),
its state of charge and other readings, and the counters of the energy into and out of
it. `/api/banks?period=...` answers for every bank at once, and `ui/tiles/banks.js`
draws a card for each.

    banks:
      periods: [now, today, yesterday, week, month]
      list:
        - id: bank1
          title: Bank 1
          note: LiFePO4, 280 Ah
          soc: BMS - Bank 1 / batterySoC
          cells:
            feed: "BMS - Bank 1 / cellVoltage {n}"     # {n} from 0 to count - 1
            influx: "voltage bms/cellVoltage/0/{n}"     # the same, for the series map
            count: 16
            label: "{n1}"                              # {n1} counts from 1
            decimals: 3
            spread: 0.05                               # a wider spread is a warning
            # or warn_abs: 1.0, a cell further than this from 0 (a mid-point tap's offset)
          values:
            - {label: Voltage, feed: BMS - Bank 1 / batteryVoltage, decimals: 2}
            - {label: Power, feed: LiFePO monitor 5 / Battery-280Ah, decimals: 0}
          energy:
            in:  LiFePO monitor 5 / Battery-280Ah (pulseOut)
            out: LiFePO monitor 5 / Battery-280Ah (pulseIn)

`cells` may instead be a list, `[{feed, label}, ...]`, for a bank whose cells are not
numbered feeds (Bank 3's series mid-points). A value's `scale` multiplies it, -1 to turn
a BMS's sign round to the site's (positive out of the battery). A value's `range: [lo,
hi]` drops readings outside it as faults, live and in a period's statistics; the state of
charge has 0 to 100 unless it says otherwise (the Leaf BMS sent 610 and 354 among its
98s on 29 Oct 2026).

"now" is read from the live store and costs nothing. A past period is answered from
Influx with bounded queries, every one naming its series and both time bounds (influx.py
says why that matters): one grouped query for all of a bank's cells, giving each cell's
lowest, highest and mean, and its last reading in the window; one per other reading for
its lowest, highest and last; and last minus first for each energy counter. The series
are the derived.yml `influx:` map's. 30 days of a 16-cell bank is about 4 million points,
8 s on the shannstainable Pi with no growth in memory (29 Oct 2026), so answers are
cached and a period being answered is answered once, however many screens ask.

"Low" and "high" are the cells that went lowest and highest over the period, the weak
and the strong ends of the bank; for "now", the lowest and highest at this moment, with
the spread between them.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

import energy
from state import emon_feed

log = logging.getLogger(__name__)

PERIODS = energy.PERIODS
LABELS = energy.LABELS
TTL_S = {"today": 120.0, "yesterday": 3600.0, "week": 1800.0, "month": 3600.0}
"""Longer than the Sankey's: cell statistics move slowly, and a month costs ~25 s."""


def _number(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


class Item:
    """One reading of a bank: a cell, or a value such as the state of charge."""

    def __init__(self, feed: str, label: str, decimals: Optional[int] = None,
                 scale: float = 1.0, unit: Optional[str] = None,
                 valid: Optional[Tuple[float, float]] = None) -> None:
        self.feed, self.label, self.decimals = feed, label, decimals
        self.scale, self.unit = float(scale), unit
        self.valid = valid

    def ok(self, value: Optional[float]) -> Optional[float]:
        """The raw reading, or None if it is outside the item's valid range."""
        if value is None or self.valid is None:
            return value
        return value if self.valid[0] <= value <= self.valid[1] else None

    def scaled(self, low: Optional[float], high: Optional[float]) -> Tuple[Optional[float], Optional[float]]:
        """A negative scale turns a range round: the lowest becomes the highest."""
        lo = None if low is None else low * self.scale
        hi = None if high is None else high * self.scale
        return (hi, lo) if self.scale < 0 else (lo, hi)


class Bank:
    def __init__(self, spec: Dict[str, Any]) -> None:
        if not isinstance(spec, dict) or not spec.get("id"):
            raise ValueError(f"a bank needs an id: {spec!r}")
        self.id = str(spec["id"])
        self.title = str(spec.get("title", self.id))
        self.note = str(spec.get("note", ""))
        self.soc = (Item(spec["soc"], "State of charge", 0, valid=_range(spec.get("soc_range"), (0.0, 100.0)))
                    if spec.get("soc") else None)
        cells = spec.get("cells") or {}
        self.cell_decimals = cells.get("decimals", 3) if isinstance(cells, dict) else 3
        self.spread = _number(cells.get("spread")) if isinstance(cells, dict) else None
        self.warn_abs = _number(cells.get("warn_abs")) if isinstance(cells, dict) else None
        cells_valid = _range(cells.get("range")) if isinstance(cells, dict) else None
        self.cells: List[Item] = []
        self.cells_valid = cells_valid
        self.series: Dict[str, Tuple[str, str]] = {}
        if isinstance(cells, dict) and cells.get("feed"):
            count = int(cells.get("count", 0))
            if count <= 0:
                raise ValueError(f"bank {self.id!r}: cells with a feed pattern need a count")
            label = str(cells.get("label", "{n1}"))
            pattern = cells.get("influx")
            for n in range(count):
                feed = str(cells["feed"]).replace("{n}", str(n))
                self.cells.append(Item(feed, label.replace("{n1}", str(n + 1)).replace("{n}", str(n)),
                                       self.cell_decimals, valid=cells_valid))
                if pattern:
                    measurement, sensor = str(pattern).replace("{n}", str(n)).split()
                    self.series[feed] = (measurement, sensor)
        else:
            items = cells.get("list") if isinstance(cells, dict) else cells
            for i, c in enumerate(items or []):
                self.cells.append(Item(c["feed"], str(c.get("label", i + 1)), self.cell_decimals,
                                       valid=cells_valid))
        self.values = [Item(v["feed"], str(v.get("label", v["feed"])), v.get("decimals"),
                            float(v.get("scale", 1.0)), v.get("unit"), _range(v.get("range")))
                       for v in spec.get("values") or []]
        energy_spec = spec.get("energy") or {}
        self.energy_in = energy_spec.get("in")
        self.energy_out = energy_spec.get("out")

    def feeds(self) -> List[str]:
        """Every feed this bank names, for the page linter."""
        names = [c.feed for c in self.cells] + [v.feed for v in self.values]
        if self.soc:
            names.append(self.soc.feed)
        names += [n for n in (self.energy_in, self.energy_out) if n]
        return names


class Banks:
    """The `banks:` block of one derived.yml."""

    def __init__(self, doc: Optional[Dict[str, Any]] = None) -> None:
        block = (doc or {}).get("banks") or {}
        self.list = [Bank(spec) for spec in block.get("list") or []]
        ids = [b.id for b in self.list]
        if len(ids) != len(set(ids)):
            raise ValueError("a bank id appears twice")
        self.periods = [p for p in (block.get("periods") or PERIODS) if p in PERIODS]
        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._lock = threading.Lock()
        self._working: Dict[str, threading.Lock] = {p: threading.Lock() for p in PERIODS}

    def __bool__(self) -> bool:
        return bool(self.list)

    def feeds(self) -> List[str]:
        names: List[str] = []
        for bank in self.list:
            names.extend(bank.feeds())
        return names

    def series(self) -> Dict[str, Tuple[str, str]]:
        """The cells' Influx series, from their patterns, to add to derived.yml's map."""
        out: Dict[str, Tuple[str, str]] = {}
        for bank in self.list:
            out.update(bank.series)
        return out

    # --- answering ---------------------------------------------------------------------

    def document(self, period: str, state, window=None, now: Optional[float] = None) -> Dict[str, Any]:
        """Every bank for one period. Never raises on a query that fails: that part of
        the bank comes back empty and is named in `failed`."""
        if period not in PERIODS:
            raise ValueError(f"unknown period {period!r}")
        now = state.clock() if now is None else now
        if period == "now":
            snapshot = state.store.snapshot()
            return self._doc(period, now, now, [self._live(b, snapshot) for b in self.list], [])
        cached = self._cached(period, now)
        if cached is not None:
            return cached
        # One set of queries a period, however many screens ask at once: the rest wait
        # here and are answered from the cache it fills.
        with self._working[period]:
            cached = self._cached(period, now)
            if cached is not None:
                return cached
            start, end = energy.window(period, now)
            failed: List[str] = []
            banks = [self._over(b, window, start, end, failed) for b in self.list]
            doc = self._doc(period, start, end, banks, failed)
            with self._lock:
                self._cache[period] = (now, doc)
            return doc

    def _cached(self, period: str, now: float) -> Optional[Dict[str, Any]]:
        with self._lock:
            got = self._cache.get(period)
        if got is None:
            return None
        at, doc = got
        if now - at > TTL_S.get(period, 120.0):
            return None
        return doc if energy.still_same_window(period, doc["from"], now) else None

    @staticmethod
    def _doc(period: str, start: float, end: float, banks: List[Dict[str, Any]],
             failed: List[str]) -> Dict[str, Any]:
        return {"period": period, "label": LABELS[period], "from": start, "to": end,
                "banks": banks, "failed": failed}

    # --- now ----------------------------------------------------------------------------

    def _live(self, bank: Bank, snapshot) -> Dict[str, Any]:
        def now(item: Item) -> Tuple[Optional[float], str]:
            r = snapshot.get(item.feed)
            v = item.ok(None if r is None else _number(r.value))
            unit = item.unit if item.unit is not None else ("" if r is None else r.unit)
            return (None if v is None else v * item.scale), unit

        cells = []
        unit = ""
        for c in bank.cells:
            v, u = now(c)
            unit = unit or u
            cells.append({"label": c.label, "now": v})
        values = []
        for v in bank.values:
            value, u = now(v)
            values.append({"label": v.label, "unit": u, "decimals": v.decimals, "now": value})
        soc = None
        if bank.soc:
            soc_now, _u = now(bank.soc)
            soc = {"now": soc_now}
        return self._bank(bank, soc, cells, unit, values, None, "now")

    # --- a past period ------------------------------------------------------------------

    def _over(self, bank: Bank, window, start: float, end: float, failed: List[str]) -> Dict[str, Any]:
        def fail(what: str, ex: Exception) -> None:
            log.error("banks %s: %s failed: %s", bank.id, what, ex)
            failed.append(f"{bank.id}/{what}")

        cells = [{"label": c.label} for c in bank.cells]
        unit = ""
        if window is not None and bank.cells:
            try:
                stats = window.stats_many([c.feed for c in bank.cells], start, end, bank.cells_valid)
                for cell, c in zip(cells, bank.cells):
                    s = stats.get(c.feed)
                    if s:
                        cell.update(min=s["min"], max=s["max"], mean=s["mean"], now=s["last"])
                unit = "V"
            except Exception as ex:
                fail("cells", ex)
        values = []
        for v in bank.values:
            entry = {"label": v.label, "unit": v.unit or "", "decimals": v.decimals}
            if window is not None:
                try:
                    s = window.stats(v.feed, start, end, v.valid)
                    if s:
                        lo, hi = v.scaled(s["min"], s["max"])
                        entry.update(min=lo, max=hi, now=None if s["last"] is None else s["last"] * v.scale)
                except Exception as ex:
                    fail(v.label, ex)
            values.append(entry)
        soc = None
        if bank.soc and window is not None:
            try:
                s = window.stats(bank.soc.feed, start, end, bank.soc.valid)
                soc = {"now": s["last"], "min": s["min"], "max": s["max"]} if s else None
            except Exception as ex:
                fail("soc", ex)
        energy_doc = None
        if window is not None and (bank.energy_in or bank.energy_out):
            energy_doc = {}
            for key, name in (("in", bank.energy_in), ("out", bank.energy_out)):
                if not name:
                    continue
                try:
                    energy_doc[key] = window.counter_delta(name, start, end)
                except Exception as ex:
                    fail(f"energy {key}", ex)
                    energy_doc[key] = None
        return self._bank(bank, soc, cells, unit, values, energy_doc, "period")

    # --- shaping ------------------------------------------------------------------------

    def _bank(self, bank: Bank, soc, cells: List[Dict[str, Any]], unit: str,
              values: List[Dict[str, Any]], energy_doc, kind: str) -> Dict[str, Any]:
        """Picks out the low and high cells. For "now", the lowest and highest readings
        and the spread between them; for a period, the cell that went lowest and the cell
        that went highest at any time in it."""
        low = high = None
        key_low, key_high = ("now", "now") if kind == "now" else ("min", "max")
        known_low = [c for c in cells if _number(c.get(key_low)) is not None]
        known_high = [c for c in cells if _number(c.get(key_high)) is not None]
        if known_low:
            c = min(known_low, key=lambda c: c[key_low])
            low = {"label": c["label"], "value": c[key_low]}
        if known_high:
            c = max(known_high, key=lambda c: c[key_high])
            high = {"label": c["label"], "value": c[key_high]}
        nows = [c["now"] for c in cells if _number(c.get("now")) is not None]
        spread = (max(nows) - min(nows)) if len(nows) > 1 else None
        return {"id": bank.id, "title": bank.title, "note": bank.note, "soc": soc,
                "cells": {"unit": unit or ("V" if bank.cells else ""), "decimals": bank.cell_decimals,
                          "warn_spread": bank.spread, "warn_abs": bank.warn_abs, "items": cells, "low": low, "high": high,
                          "spread": spread},
                "values": values, "energy": energy_doc}


def _range(spec: Any, default: Optional[Tuple[float, float]] = None) -> Optional[Tuple[float, float]]:
    if spec is None:
        return default
    if not (isinstance(spec, (list, tuple)) and len(spec) == 2 and all(_number(x) is not None for x in spec)):
        raise ValueError(f"a range is [low, high], not {spec!r}")
    return float(spec[0]), float(spec[1])


def load(doc: Dict[str, Any]) -> Banks:
    return Banks(doc)
