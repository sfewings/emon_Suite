"""Side by side: Node-RED's Instant data figures and derived.yml's, for PLAN 2b.

Reads Node-RED's flow context through its admin API (a GET; Node-RED keeps it in memory
only), and computes derived.yml's figures by the same replay from Influx that emon_live
does on start, so no emon_live needs to be running.

    python tools/compare_nodered.py                  # a full day: Node-RED up since midnight
    python tools/compare_nodered.py --from 20:01     # Node-RED restarted at 20:01 today

--from replays only the rows since that time, which is what Node-RED's figures cover
after a restart: both then take the first reading after it as the day's start.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import derived  # noqa: E402
import influx  # noqa: E402

REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
DEFAULT_DERIVED = os.path.join(REPO, "provisioning", "shannstainable", "emon-ui", "derived.yml")
INSTANT_DATA_TAB = "0be7f1a82e48bfdd"


def nodered_context(url: str, tab: str) -> dict:
    with urllib.request.urlopen(f"{url}/context/flow/{tab}", timeout=10) as r:
        doc = json.loads(r.read().decode("utf-8"))
    ctx = doc.get("memory", doc)
    return {k: (v.get("msg") if isinstance(v, dict) and "msg" in v else v) for k, v in ctx.items()}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def nodered_figures(c: dict) -> dict:
    """Node-RED's figures, under the derived ids they correspond to."""
    g = lambda k: _num(c.get(k))
    diff = lambda kind, b: (g(f"LastCount{kind}{b}") - g(f"DayStartCount{kind}{b}")
                            if g(f"LastCount{kind}{b}") is not None and g(f"DayStartCount{kind}{b}") else None)
    total = lambda kind: (sum(diff(kind, b) for b in range(3))
                          if all(diff(kind, b) is not None for b in range(3)) else None)
    out = {
        "hws/today": g("hwsTotal"), "consumed/today": g("powerTotal"),
        "import/today": g("importTotal"), "car/today": g("carTotal"),
        "solar/today": g("solarTotal"),   # differs: Node-RED's leaves Inverter Two out
        "export/today": g("exportTotal"),
        "foregone/today": g("foregoneProductionTotal"),
        "inverter1/today": g("inverterDailyTotal:inverter/pvInputPower/0"),
        "inverter3/today": g("inverterDailyTotal:inverter/pvInputPower/1"),
        "inverter2/today": g("inverterDailyTotal:inverter/pvInputPower/2"),
        "import/average": (g("importSum") / g("importCount")) if g("importCount") else None,
        "export/now": g("exporting"),
        "battery/rail/max": g("maxVoltage"), "battery/rail/min": g("minVoltage"),
        # Node-RED's "BatteryIn" is monitor 5's pulseIn, which is discharge (derived.yml).
        "battery/out/today": total("BatteryIn"), "battery/in/today": total("BatteryOut"),
        "inverter/in/today": total("InverterIn"), "inverter/out/today": total("InverterOut"),
        # Not compared: Node-RED's TotalBatteryOutTo9AM is morning charge (pulseOut), ours
        # is overnight discharge.
        "car/leaf/kmToday": (g("odometer0") - g("odometerStartOfDay0")) if g("odometerStartOfDay0") else None,
        "car/outlander/kmToday": (g("odometer1") - g("odometerStartOfDay1")) if g("odometerStartOfDay1") else None,
    }
    for ch in ("B2-5", "B2-4", "B2-3", "B2-2", "B2-1"):
        out[f"battery/midpoint/{ch}/max"] = g(ch)
    return out


def ours(derived_file: str, influx_url: str, cutoff: float | None) -> dict:
    d = derived.load(derived_file)
    source = influx.Influx(influx_url)
    if cutoff is not None:
        rows = source.rows
        source.rows = lambda m, s, since, until: rows(m, s, since=max(since, cutoff), until=until)
    return {r.key[len(derived.PREFIX):]: r.value for r in influx.seed(d, source)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--derived", default=DEFAULT_DERIVED)
    ap.add_argument("--nodered", default="http://localhost:1880")
    ap.add_argument("--influx", default="http://localhost:8086")
    ap.add_argument("--tab", default=INSTANT_DATA_TAB)
    ap.add_argument("--from", dest="since", help="HH:MM today: replay only from then")
    args = ap.parse_args(argv)

    since = None
    if args.since:
        hh, mm = (int(x) for x in args.since.split(":"))
        lt = time.localtime()
        since = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hh, mm, 0, 0, 0, -1))

    theirs = nodered_figures(nodered_context(args.nodered, args.tab))
    mine = ours(args.derived, args.influx, since)
    print(f"{'derived id':30} {'Node-RED':>12} {'emon_live':>12} {'diff':>9}")
    for key in theirs:
        a, b = theirs[key], mine.get(key)
        if a is None and b is None:
            continue
        d = "" if a is None or b is None else f"{b - a:+9.2f}"
        fa = "-" if a is None else f"{a:12.2f}"
        fb = "-" if b is None else f"{b:12.2f}"
        print(f"{key:30} {fa:>12} {fb:>12} {d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
