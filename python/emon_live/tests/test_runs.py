"""op runs: an appliance's cycles from its plug's power (emon_feed.Runs), through the
derived engine and the start-up replay. Fake clock, fake Influx."""

import time

import pytest

import derived as dv
import influx

from pyemonlib import emon_feed

PLUG = "Dishwasher plug / Dishwasher"
BASE = {"feed": PLUG, "op": "runs", "start_w": 10, "end_w": 5, "hold_s": 600, "min_s": 300,
        "min_wh": 10, "price": 0.262}


@pytest.fixture(autouse=True)
def perth(monkeypatch):
    monkeypatch.setenv("TZ", "Australia/Perth")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def local(y, mo, d, h=0, mi=0, s=0):
    return time.mktime((y, mo, d, h, mi, s, 0, 0, -1))


def engine(influx_map=None):
    return dv.Derived({"derived": [dict(BASE, id=f"dw/{o}", output=o)
                                   for o in ("running", "count", "today", "yesterday")],
                       "influx": influx_map or {}})


def feed(d, samples):
    """Feeds (t, W) in order; returns the latest value of every derived feed."""
    latest = {}
    for t, w in samples:
        for r in d.on_value(PLUG, w, t):
            latest[r.key] = r.value
    return latest


def every(t0, t1, w, step=30):
    return [(t, w) for t in range(int(t0), int(t1), step)]


def cycle(start, minutes=90, w=1500.0, pause_at=None, pause_min=0):
    """A cycle at w, with an optional pause at 1 W, then idle at 2 W for 30 min."""
    out, t, end = [], start, start + minutes * 60
    while t < end:
        paused = pause_at is not None and pause_at <= (t - start) / 60 < pause_at + pause_min
        out.append((t, 1.0 if paused else w))
        t += 30
    return out + every(end, end + 1800, 2.0)


def test_one_cycle_with_a_pause_is_one_run():
    d = engine()
    start = local(2026, 11, 21, 10)
    got = feed(d, every(local(2026, 11, 21), start, 2.0) + cycle(start, 90, 1500.0, pause_at=40, pause_min=8))
    assert got["derived/dw/running"] == 0.0
    assert got["derived/dw/count"] == 1.0
    today = got["derived/dw/today"]
    assert today["date"] == "2026-11-21" and today["count"] == 1 and today["complete"] is True
    run = today["runs"][0]
    assert run["from"] == "10:00" and run["to"] == "11:29"
    assert run["minutes"] == 90              # to the last reading at power, 89.5 min
    # 82 minutes at 1500 W, the pause near nothing.
    assert run["wh"] == pytest.approx(1500 * 82 / 60, rel=0.02)
    assert run["cost"] == pytest.approx(run["wh"] / 1000 * 0.262, abs=0.01)
    assert today["wh"] == run["wh"] and today["cost"] == run["cost"]


def test_running_while_on_and_through_the_hold():
    d = engine()
    start = local(2026, 11, 21, 10)
    got = feed(d, cycle(start, 30)[:10])
    assert got["derived/dw/running"] == 1.0 and got["derived/dw/count"] == 0.0
    feed(d, cycle(start, 30)[10:60])
    end = start + 30 * 60
    got = feed(d, every(end, end + 540, 2.0))   # the last power reading was end - 30
    assert got["derived/dw/running"] == 1.0, "still in the hold"
    got = feed(d, every(end + 570, end + 700, 2.0))
    assert got["derived/dw/running"] == 0.0 and got["derived/dw/count"] == 1.0


def test_a_pause_longer_than_the_hold_ends_the_run():
    d = engine()
    start = local(2026, 11, 21, 10)
    got = feed(d, cycle(start, 90, pause_at=30, pause_min=15))
    assert got["derived/dw/count"] == 2.0


def test_short_or_small_bursts_are_not_runs():
    d = engine()
    start = local(2026, 11, 21, 10)
    feed(d, cycle(start, 3, 800.0))                             # too short
    got = feed(d, cycle(start + 7200, 20, 25.0))                # 8.3 Wh: too little
    assert got["derived/dw/count"] == 0.0
    assert got["derived/dw/today"]["runs"] == []


def test_readings_from_mid_period_on_are_incomplete():
    d = engine()
    got = feed(d, cycle(local(2026, 11, 21, 10), 60))
    assert got["derived/dw/today"]["complete"] is False, "nothing seen from 00:00 to 10:00"


def test_midnight_rolls_today_into_yesterday():
    d = engine()
    feed(d, every(local(2026, 11, 21), local(2026, 11, 21, 20), 2.0) + cycle(local(2026, 11, 21, 20), 60))
    got = {r.key: r.value for r in d.tick(local(2026, 11, 22, 0, 0, 5))}
    assert got["derived/dw/count"] == 0.0
    assert got["derived/dw/today"]["runs"] == [] and got["derived/dw/today"]["date"] == "2026-11-22"
    y = got["derived/dw/yesterday"]
    assert y["date"] == "2026-11-21" and y["count"] == 1 and y["complete"] is True
    assert y["runs"][0]["from"] == "20:00"


def test_a_run_across_midnight_belongs_to_the_day_it_ends():
    d = engine()
    feed(d, cycle(local(2026, 11, 21, 23, 30), 60))
    d.tick(local(2026, 11, 22, 1))
    got = {k: e.operator.value for k, e in d.entries.items()}
    assert got["derived/dw/yesterday"]["count"] == 0
    assert got["derived/dw/today"]["runs"][0]["from"] == "23:30"


def test_readings_that_stop_end_the_run_at_the_last_one():
    d = engine()
    start = local(2026, 11, 21, 10)
    feed(d, cycle(start, 40)[:80])           # 40 min of power, then the plug falls silent
    assert d.entries["derived/dw/running"].operator.value == 1.0
    assert d.tick(start + 40 * 60 + 600) == [], "not stale yet"
    got = {r.key: r.value for r in d.tick(start + 40 * 60 + 1900)}
    assert got["derived/dw/running"] == 0.0 and got["derived/dw/count"] == 1.0
    assert got["derived/dw/today"]["runs"][0]["to"] == "10:39"


class FakeInflux:
    def __init__(self, rows):
        self.data, self.asked = rows, []

    def rows(self, kind, sensor, since, until):
        self.asked.append((sensor, since, until))
        return [(t, v) for t, v in self.data.get(sensor, []) if since <= t <= until]

    def first(self, *a, **k):
        return None


def test_seed_rebuilds_yesterday_for_the_email():
    d = engine({PLUG: "power power/1/0"})
    rows = (every(local(2026, 11, 21), local(2026, 11, 21, 9), 2.0) + cycle(local(2026, 11, 21, 9), 90) + cycle(local(2026, 11, 21, 19), 60)
            + cycle(local(2026, 11, 22, 0, 5), 0))
    rows = sorted(set(rows))
    now = local(2026, 11, 22, 0, 30)
    got = {r.key: r.value for r in influx.seed(d, FakeInflux({"power/1/0": rows}), now)}
    y = got["derived/dw/yesterday"]
    assert y["date"] == "2026-11-21" and y["count"] == 2 and y["complete"] is True
    assert [r["from"] for r in y["runs"]] == ["09:00", "19:00"]
    since = d.replay_since(PLUG, now)
    assert since == local(2026, 11, 21), "from yesterday's midnight"


def test_a_late_restart_marks_yesterday_incomplete():
    d = engine({PLUG: "power power/1/0"})
    rows = every(local(2026, 11, 20, 0), local(2026, 11, 22, 23), 2.0, step=300)
    now = local(2026, 11, 22, 22)      # replay is cut to 36 h: from 10:00 yesterday
    got = {r.key: r.value for r in influx.seed(d, FakeInflux({"power/1/0": rows}), now)}
    assert got["derived/dw/yesterday"]["complete"] is False
    assert got["derived/dw/today"]["complete"] is True


def test_bad_output_is_refused():
    with pytest.raises(ValueError):
        emon_feed.Runs(output="sometimes")


def test_shannstainable_derived_yml_finds_a_dishwasher_cycle():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "provisioning",
                        "shannstainable", "emon-ui", "derived.yml")
    d = dv.load(path)
    start = local(2026, 11, 21, 19)
    got = feed(d, every(local(2026, 11, 21), start, 2.0) + cycle(start, 100, 1800.0, pause_at=50, pause_min=10))
    assert got["derived/dishwasher/running"] == 0.0
    assert got["derived/dishwasher/runs/today"]["count"] == 1
    assert got["derived/dishwasher/runs/today"]["runs"][0]["from"] == "19:00"
    assert "derived/washingmachine/running" not in got, "only the dishwasher's feed arrived"
    rolled = {r.key: r.value for r in d.tick(local(2026, 11, 22, 0, 0, 5))}
    assert rolled["derived/dishwasher/runs/yesterday"]["count"] == 1
