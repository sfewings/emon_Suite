"""Supply to demand: which source fed which load, over a chosen period (DESIGN 6.7).

The Sankey's other view (energy.py draws the house in the middle). Nothing measures which
source fed which load, so this attributes it, slice by slice, from how the site is wired.
derived.yml's `sankey: split:` block describes the wiring: circuits, each with its own
solar, its own battery, the loads on it and what is left over, plus the grid.

    sankey:
      split:
        circuits:
          - id: main
            label: Main
            solar: {id: solar_main, label: Solar Main, power: [Inverter One / pvInputPower]}
            battery:
              id: banks
              label: Banks 1-3
              power: [LiFePO monitor 5 / Battery-510Ah]          # W, + is out of the battery
              out: [LiFePO monitor 5 / Battery-510Ah (pulseIn)]  # Wh counters, optional
              in:  [LiFePO monitor 5 / Battery-510Ah (pulseOut)]
            loads:
              - {id: car, label: Car, domain: car, power: Power board / Car,
                 counter: Power board / Car (pulse)}
            house: {id: house_main, label: House Main}
          - id: office
            solar: ...
            battery: {id: leaf_bank, label: Leaf bank, power: [BMS - Leaf Bank / power]}
            export: {id: export, label: Export, now: derived/export/now}
            house: {id: house_office, label: House Office}
        grid: {id: grid, label: Grid, power: Power board / Imported,
               counter: Power board / Imported (pulse),
               to: {id: grid_direct, label: Direct from grid}}

In each slice (a minute for a day, 15 for a month), on each circuit:

1. Battery charge comes from that circuit's solar; any more than the solar made, from its
   own battery's discharge (one bank charging another), then "Unmatched".
2. Export comes from what solar is left; it never comes from a battery.
3. What solar is left and the battery's discharge feed the loads and the house in the
   same proportion: when the battery is charging that is all solar, when it is
   discharging every load gets the same mix.

The house is the remainder: supply less every measured demand. When the measured demands
exceed the supply (two meters disagreeing, or a manual charge from the grid), the
difference is drawn from an "Unmatched" source rather than hidden. The grid feeds only
"Direct from grid": the site's loads are on the inverters, so an import is something
used straight from the grid.

A counter's energy in a slice is the rise of its last value from the slice before, so the
slices add up to the counter's own total over the period; a W feed's is its mean times the
slice. The export has no meter: it is Inverter Two's solar less the Leaf bank's charge less
the office's load at night, which is the Leaf bank's mean discharge while Inverter Two
makes nothing, since midnight; as derived.yml's derived/export/now computes it live.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

import energy
from state import emon_feed

log = logging.getLogger(__name__)

UNMATCHED = {"id": "unmatched", "label": "Unmatched", "domain": "other"}


def _names(value: Any) -> List[str]:
    if value is None:
        return []
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


class Node:
    def __init__(self, spec: Dict[str, Any], domain: str, where: str) -> None:
        if not isinstance(spec, dict) or not spec.get("id"):
            raise ValueError(f"sankey split: {where} needs an id: {spec!r}")
        self.id = str(spec["id"])
        self.label = str(spec.get("label", self.id))
        self.domain = str(spec.get("domain", domain))
        self.power = _names(spec.get("power"))
        self.counter = _names(spec.get("counter"))


class Battery(Node):
    def __init__(self, spec: Dict[str, Any], where: str) -> None:
        super().__init__(spec, "batt", where)
        self.out = _names(spec.get("out"))
        self.into = _names(spec.get("in"))
        if bool(self.out) != bool(self.into):
            raise ValueError(f"sankey split: battery {self.id!r} needs both in and out counters, or neither")
        if not self.power:
            raise ValueError(f"sankey split: battery {self.id!r} needs its power feeds")
        self.charge_id = f"{self.id}_charge"
        self.charge_label = str(spec.get("charge_label", f"{self.label} charge"))


class Circuit:
    def __init__(self, spec: Dict[str, Any]) -> None:
        if not isinstance(spec, dict) or not spec.get("id"):
            raise ValueError(f"sankey split: a circuit needs an id: {spec!r}")
        self.id = str(spec["id"])
        self.label = str(spec.get("label", self.id))
        where = f"circuit {self.id!r}"
        self.solar = Node(spec.get("solar") or {}, "solar", f"{where} solar")
        battery = spec.get("battery")
        self.battery = Battery(battery, where) if battery else None
        self.loads = [Node(s, "other", f"{where} load") for s in spec.get("loads") or []]
        export = spec.get("export")
        self.export = Node(export, "solar", f"{where} export") if export else None
        self.export_now = str(export.get("now")) if export and export.get("now") else None
        if self.export is not None and self.battery is None:
            raise ValueError(f"sankey split: {where}'s export estimate needs its battery")
        self.house = Node(spec.get("house") or {}, "other", f"{where} house")


class Split:
    """The `split:` block of a derived.yml's `sankey:`."""

    def __init__(self, block: Optional[Dict[str, Any]] = None) -> None:
        block = block or {}
        self.circuits = [Circuit(s) for s in block.get("circuits") or []]
        grid = block.get("grid")
        self.grid = Node(grid, "power", "grid") if grid else None
        self.grid_to = Node((grid or {}).get("to") or {"id": "grid_direct", "label": "Direct from grid"},
                            "power", "grid's load") if grid else None
        ids = [n.id for n in self._nodes()] + [UNMATCHED["id"]]
        for c in self.circuits:
            if c.battery is not None:
                ids.append(c.battery.charge_id)
        doubled = sorted({i for i in ids if ids.count(i) > 1})
        if doubled:
            raise ValueError(f"sankey split: ids appear twice: {doubled}")
        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._lock = threading.Lock()
        self._working = {p: threading.Lock() for p in energy.PERIODS}

    def __bool__(self) -> bool:
        return bool(self.circuits)

    def _nodes(self) -> List[Node]:
        out: List[Node] = []
        for c in self.circuits:
            out.append(c.solar)
            if c.battery is not None:
                out.append(c.battery)
            out.extend(c.loads)
            if c.export is not None:
                out.append(c.export)
            out.append(c.house)
        if self.grid is not None:
            out.extend([self.grid, self.grid_to])
        return out

    def feeds(self) -> List[str]:
        """Every feed this view reads, live or from Influx, for the page linter."""
        names = [c.export_now for c in self.circuits if c.export_now]
        for node in self._nodes():
            names += node.power + node.counter
            if isinstance(node, Battery):
                names += node.out + node.into
        seen = set()
        return [n for n in names if not (n in seen or seen.add(n))]

    def series_feeds(self) -> List[str]:
        """The feeds a past period asks Influx for: each needs an influx: series."""
        watts, counters = self._series_by_kind()
        return watts + counters

    def _series_by_kind(self) -> Tuple[List[str], List[str]]:
        """(W feeds read as bucket means, Wh counters read as each bucket's last value)."""
        watts: List[str] = []
        counters: List[str] = []
        for c in self.circuits:
            watts += c.solar.power
            if c.battery is not None:
                if c.battery.out:
                    counters += c.battery.out + c.battery.into
                if not c.battery.out or c.export is not None:
                    watts += c.battery.power
            for load in c.loads:
                (counters if load.counter else watts).extend(load.counter or load.power)
        if self.grid is not None:
            (counters if self.grid.counter else watts).extend(self.grid.counter or self.grid.power)
        seen = set()
        return ([n for n in watts if not (n in seen or seen.add(n))],
                [n for n in counters if not (n in seen or seen.add(n))])

    # --- answering ---------------------------------------------------------------------

    def document(self, period: str, state, influx=None, now: Optional[float] = None) -> Dict[str, Any]:
        """Every source and load, and the links between them, for one period. A series
        that cannot be read counts as nothing and is named in `failed`."""
        if period not in energy.PERIODS:
            raise ValueError(f"unknown period {period!r}")
        now = state.clock() if now is None else now
        if period == "now":
            return self._finish(period, now, now, "W", [self._live(state)], [])
        cached = self._cached(period, now)
        if cached is not None:
            return cached
        # One computation a period, however many screens ask at once.
        with self._working[period]:
            cached = self._cached(period, now)
            if cached is not None:
                return cached
            start, end = energy.window(period, now)
            failed: List[str] = []
            slices = self._slices(influx, start, end, failed) if influx is not None else []
            if influx is None:
                failed.append("influx")
            doc = self._finish(period, start, end, "Wh", slices, failed)
            with self._lock:
                self._cache[period] = (now, doc)
            return doc

    def _cached(self, period: str, now: float) -> Optional[Dict[str, Any]]:
        with self._lock:
            got = self._cache.get(period)
        if got is None:
            return None
        at, doc = got
        if now - at > energy.TTL_S.get(period, 60.0):
            return None
        return doc if energy.still_same_window(period, doc["from"], now) else None

    # --- one slice ------------------------------------------------------------------------

    def _live(self, state) -> Dict[str, float]:
        """The present moment as one slice, in W."""
        snapshot = state.store.snapshot()

        def value(name: Optional[str]) -> float:
            reading = snapshot.get(name) if name else None
            v = None if reading is None else reading.value
            return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0

        s: Dict[str, float] = {}
        for c in self.circuits:
            s[c.solar.id] = sum(max(0.0, value(n)) for n in c.solar.power)
            if c.battery is not None:
                powers = [value(n) for n in c.battery.power]
                s[c.battery.id] = sum(max(0.0, p) for p in powers)
                s[c.battery.charge_id] = sum(max(0.0, -p) for p in powers)
            for load in c.loads:
                s[load.id] = sum(max(0.0, value(n)) for n in load.power)
            if c.export is not None:
                s[c.export.id] = max(0.0, value(c.export_now))
        if self.grid is not None:
            s[self.grid.id] = sum(max(0.0, value(n)) for n in self.grid.power)
        return s

    def _slices(self, influx, start: float, end: float, failed: List[str]) -> List[Dict[str, float]]:
        """The period cut into buckets, each {node id: Wh}. One bounded query a series."""
        step = float(energy.STEP_S.get(energy._period_of(start, end) or "today", 60))
        hours = step / 3600.0
        cache: Dict[Tuple[str, str], Dict[float, float]] = {}

        def series(name: str, agg: str) -> Dict[float, float]:
            if (name, agg) not in cache:
                try:
                    cache[(name, agg)] = dict(influx.buckets(name, start, end, int(step), agg))
                except Exception as ex:
                    log.error("supply: %s failed: %s", name, ex)
                    failed.append(name)
                    cache[(name, agg)] = {}
            return cache[(name, agg)]

        def rises(names: List[str]) -> Dict[float, float]:
            """A counter's rise into each bucket from the one before; a fall (a reset,
            a relayed old value) is no energy."""
            out: Dict[float, float] = {}
            for name in names:
                last = None
                for t, v in sorted(series(name, "last").items()):
                    if last is not None and v > last:
                        out[t] = out.get(t, 0.0) + v - last
                    last = v
            return out

        # Every series first, so the slices are every bucket any of them has.
        watt_feeds, counter_feeds = self._series_by_kind()
        for name in counter_feeds:
            series(name, "last")
        for name in watt_feeds:
            series(name, "mean")
        times = sorted({t for rows in cache.values() for t in rows})
        hold = max(energy.MAX_GAP_S, step)

        def held(name: str) -> Dict[float, float]:
            """A W feed at every slice: a bucket it has no reading in takes its last mean,
            up to the gap derived.yml's integrate bridges. The inverters report every
            27 s or so, unevenly, so a minute often has one of a pair and not the other;
            read as 0, that took half of Main's solar away (30 Oct 2026)."""
            rows, out, last = series(name, "mean"), {}, None
            for t in times:
                if t in rows:
                    last = (t, rows[t])
                if last is not None and t - last[0] <= hold:
                    out[t] = last[1]
            return out

        def watts(names: List[str]) -> Dict[float, float]:
            out: Dict[float, float] = {}
            for name in names:
                for t, v in held(name).items():
                    out[t] = out.get(t, 0.0) + v
            return out

        def energy_of(names: List[str], sign: float = 1.0) -> Dict[float, float]:
            """Wh a slice of the positive part of each feed (sign -1: the negative part),
            each feed on its own, so one bank charging while another discharges is both."""
            out: Dict[float, float] = {}
            for name in names:
                for t, w in held(name).items():
                    out[t] = out.get(t, 0.0) + max(0.0, sign * w) * hours
            return out

        columns: Dict[str, Dict[float, float]] = {}
        for c in self.circuits:
            columns[c.solar.id] = energy_of(c.solar.power)
            b = c.battery
            if b is not None:
                if b.out:
                    columns[b.id], columns[b.charge_id] = rises(b.out), rises(b.into)
                else:
                    columns[b.id], columns[b.charge_id] = energy_of(b.power), energy_of(b.power, -1.0)
            for load in c.loads:
                columns[load.id] = rises(load.counter) if load.counter else energy_of(load.power)
            if c.export is not None:
                columns[c.export.id] = _export(times, watts(c.solar.power), watts(c.battery.power), hours)
        if self.grid is not None:
            columns[self.grid.id] = rises(self.grid.counter) if self.grid.counter else energy_of(self.grid.power)
        return [{k: col.get(t, 0.0) for k, col in columns.items()} for t in times]

    # --- the attribution ------------------------------------------------------------------

    def allocate(self, s: Dict[str, float]) -> Dict[Tuple[str, str], float]:
        """One slice's {(source id, load id): amount}, by the rules in the docstring."""
        links: Dict[Tuple[str, str], float] = {}

        def give(src: str, dst: str, amount: float) -> None:
            if amount > 1e-9:
                links[(src, dst)] = links.get((src, dst), 0.0) + amount

        for c in self.circuits:
            solar = s.get(c.solar.id, 0.0)
            out = s.get(c.battery.id, 0.0) if c.battery else 0.0
            charge = s.get(c.battery.charge_id, 0.0) if c.battery else 0.0
            export = s.get(c.export.id, 0.0) if c.export else 0.0
            loads = [(n.id, s.get(n.id, 0.0)) for n in c.loads]
            house = max(0.0, solar + out - charge - export - sum(v for _, v in loads))

            if c.battery is not None:
                a = min(charge, solar)
                b = min(charge - a, out)
                give(c.solar.id, c.battery.charge_id, a)
                give(c.battery.id, c.battery.charge_id, b)
                give(UNMATCHED["id"], c.battery.charge_id, charge - a - b)
                solar -= a
                out -= b
            if c.export is not None:
                e = min(export, solar)
                give(c.solar.id, c.export.id, e)
                give(UNMATCHED["id"], c.export.id, export - e)
                solar -= e

            pool = solar + out
            wants = loads + [(c.house.id, house)]
            asked = sum(v for _, v in wants)
            served = min(1.0, pool / asked) if asked > 0 else 0.0
            for dst, v in wants:
                if pool > 0:
                    give(c.solar.id, dst, v * served * solar / pool)
                    give(c.battery.id if c.battery else c.solar.id, dst, v * served * out / pool)
                give(UNMATCHED["id"], dst, v * (1.0 - served))
        if self.grid is not None:
            give(self.grid.id, self.grid_to.id, s.get(self.grid.id, 0.0))
        return links

    def _finish(self, period: str, start: float, end: float, unit: str,
                slices: List[Dict[str, float]], failed: List[str]) -> Dict[str, Any]:
        totals: Dict[Tuple[str, str], float] = {}
        for s in slices:
            for key, v in self.allocate(s).items():
                totals[key] = totals.get(key, 0.0) + v
        sums: Dict[str, float] = {}
        for (src, dst), v in totals.items():
            sums[src] = sums.get(src, 0.0) + v
            sums[dst] = sums.get(dst, 0.0) + v

        def node(n_id: str, label: str, domain: str, side: str, circuit: Optional[str],
                 approx: bool = False) -> Dict[str, Any]:
            return {"id": n_id, "label": label, "domain": domain, "side": side,
                    "circuit": circuit, "value": round(sums.get(n_id, 0.0), 1), "approx": approx}

        sources: List[Dict[str, Any]] = []
        loads: List[Dict[str, Any]] = []
        for c in self.circuits:
            sources.append(node(c.solar.id, c.solar.label, c.solar.domain, "source", c.id))
            b = c.battery
            if b is not None:
                sources.append(node(b.id, b.label, b.domain, "source", c.id))
                loads.append(node(b.charge_id, b.charge_label, b.domain, "load", c.id))
            for n in c.loads:
                loads.append(node(n.id, n.label, n.domain, "load", c.id))
            if c.export is not None:
                loads.append(node(c.export.id, c.export.label, c.export.domain, "load", c.id, True))
            loads.append(node(c.house.id, c.house.label, c.house.domain, "load", c.id, True))
        if self.grid is not None:
            sources.append(node(self.grid.id, self.grid.label, self.grid.domain, "source", "grid"))
            loads.append(node(self.grid_to.id, self.grid_to.label, self.grid_to.domain, "load", "grid"))
        if sums.get(UNMATCHED["id"], 0.0) > 0.05:
            sources.append(node(UNMATCHED["id"], UNMATCHED["label"], UNMATCHED["domain"], "source", None))
        links = [{"source": src, "target": dst, "value": round(v, 1)}
                 for (src, dst), v in totals.items() if round(v, 1) > 0]
        return {"view": "split", "period": period, "label": energy.LABELS[period], "unit": unit,
                "from": start, "to": end, "circuits": [{"id": c.id, "label": c.label} for c in self.circuits],
                "nodes": sources + loads, "links": links, "failed": failed,
                "unmatched": round(sums.get(UNMATCHED["id"], 0.0), 1)}

    def total(self, node_id: str, period: str, state, influx, now: Optional[float] = None) -> Optional[float]:
        """One node's figure for a period, for the other view's ribbon of the same thing."""
        doc = self.document(period, state, influx, now)
        if "influx" in doc["failed"]:
            return None
        for n in doc["nodes"]:
            if n["id"] == node_id:
                return n["value"]
        return None


def _export(times: List[float], solar_w: Dict[float, float], battery_w: Dict[float, float],
            hours: float) -> Dict[float, float]:
    """The export estimate a slice at a time, in Wh: solar less the battery's charge less
    the night load, the battery's mean discharge while the solar made nothing, since the
    slice's midnight (derived/office/nightLoad does the same live)."""
    out: Dict[float, float] = {}
    day, total, count = None, 0.0, 0
    for t in times:
        midnight = emon_feed.period_start(t, "00:00")
        if midnight != day:
            day, total, count = midnight, 0.0, 0
        sun = solar_w.get(t, 0.0)
        w = battery_w.get(t)
        if sun <= 0 and w is not None and w > 0:
            total, count = total + w, count + 1
        night = total / count if count else 0.0
        charge = max(0.0, -(w or 0.0))
        out[t] = max(0.0, sun - charge - night) * hours
    return out
