"""derived.py and influx.py: the engine over emon_feed's operators, with a fake clock and a
fake Influx. No broker, no Influx."""

import os
import time

import pytest

from conftest import retained_messages
import derived as dv
import influx
from state import LiveState, handle_message

from pyemonlib import emon_feed

SHANNSTAINABLE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "provisioning",
                              "shannstainable", "emon-ui", "derived.yml")


@pytest.fixture(autouse=True)
def perth(monkeypatch):
    monkeypatch.setenv("TZ", "Australia/Perth")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def local(y, mo, d, h=0, mi=0, s=0):
    return time.mktime((y, mo, d, h, mi, s, 0, 0, -1))


def engine(*entries, influx_map=None):
    return dv.Derived({"derived": list(entries), "influx": influx_map or {}})


def values(readings):
    return {r.key: r.value for r in readings}


def test_the_shannstainable_file_loads_and_every_input_has_a_series():
    d = dv.load(SHANNSTAINABLE)
    assert len(d.entries) > 50
    missing = [n for n in d.inputs_outside() if n not in d.influx]
    assert missing == [], "every input from MQTT can be replayed from Influx"


def test_its_inputs_are_all_feeds_the_retained_capture_has():
    d = dv.load(SHANNSTAINABLE)
    seen = {emon_feed.parse(t, p).key for t, p in retained_messages() if t != "emon/config"}
    assert [n for n in d.inputs_outside() if n not in seen] == []


def test_a_chain_runs_in_order_and_sum_and_expr_follow():
    d = engine(
        {"id": "a/today", "op": "daily_delta", "feed": "P / a (pulse)"},
        {"id": "b/today", "op": "integrate", "feed": "P / b"},
        {"id": "total", "op": "sum", "of": ["derived/a/today", "derived/b/today"]},
        {"id": "cost", "op": "expr", "expr": "{derived/total} / 1000 * 0.25", "decimals": 2},
    )
    t = local(2026, 10, 21, 10)
    d.on_value("P / a (pulse)", 1000, t)
    assert values(d.on_value("P / a (pulse)", 3000, t + 60)) == {
        "derived/a/today": 2000.0, "derived/total": 2000.0, "derived/cost": 0.5}
    d.on_value("P / b", 1000, t + 60)
    out = values(d.on_value("P / b", 1000, t + 60 + 240))
    assert out["derived/b/today"] == pytest.approx(1000 * 240 / 3600)
    assert out["derived/total"] == pytest.approx(2000 + 1000 * 240 / 3600)


def test_definition_errors_are_loud():
    with pytest.raises(ValueError, match="cycle"):
        engine({"id": "x", "op": "expr", "expr": "{derived/y} + 1"},
               {"id": "y", "op": "expr", "expr": "{derived/x} + 1"})
    with pytest.raises(ValueError, match="twice"):
        engine({"id": "x", "op": "sum", "of": ["a"]}, {"id": "x", "op": "sum", "of": ["b"]})
    with pytest.raises(ValueError, match="unknown op"):
        engine({"id": "x", "op": "average", "feed": "a"})
    with pytest.raises(ValueError, match="needs a feed"):
        engine({"id": "x", "op": "daily_delta"})
    with pytest.raises(ValueError):
        engine({"id": "x", "op": "daily_delta", "feed": "a", "reset": "9am"})


def test_an_older_value_is_ignored_so_retained_messages_after_a_replay_do_not_count_twice():
    d = engine({"id": "a/today", "op": "daily_delta", "feed": "P / a (pulse)"})
    t = local(2026, 10, 21, 10)
    d.on_value("P / a (pulse)", 100, t)
    d.on_value("P / a (pulse)", 150, t + 600)
    assert d.on_value("P / a (pulse)", 140, t + 300) == [], "the retained copy, older and smaller"
    assert values(d.on_value("P / a (pulse)", 160, t + 700)) == {"derived/a/today": 60.0}


def test_tick_zeroes_totals_at_midnight_without_a_reading():
    d = engine({"id": "a/today", "op": "daily_delta", "feed": "P / a (pulse)"},
               {"id": "cost", "op": "expr", "expr": "{derived/a/today} * 2"})
    d.on_value("P / a (pulse)", 100, local(2026, 10, 21, 23))
    d.on_value("P / a (pulse)", 150, local(2026, 10, 21, 23, 30))
    assert d.tick(local(2026, 10, 21, 23, 59)) == []
    assert values(d.tick(local(2026, 10, 22, 0, 0, 5))) == {"derived/a/today": 0.0, "derived/cost": 0.0}


def test_handle_message_feeds_derived_but_not_its_own_echo(clock):
    state = LiveState(clock=clock)
    state.derived = engine({"id": "a/mean", "op": "mean", "feed": "P / a"})
    published = []
    state.publish = published.append
    env = lambda v, t: emon_feed.envelope_json(emon_feed.Reading(
        node="pulse", sub=0, field="power", idx=0, value=v, unit="W", group="P", name="a", t=t))
    handle_message(state, "emon/pulse/0/power/0", env(100, clock.now - 20))
    handle_message(state, "emon/pulse/0/power/0", env(300, clock.now - 10))
    assert [r.value for r in published] == [100.0, 200.0]
    echo = emon_feed.envelope_json(published[-1])
    handle_message(state, "emon/derived/a/mean", echo)
    assert len(published) == 2, "our own derived feed coming back is not an input"
    assert state.store.get("derived/a/mean").value == 200.0


def test_the_retained_capture_through_the_shannstainable_file(clock):
    state = LiveState(clock=clock)
    state.derived = dv.load(SHANNSTAINABLE)
    for topic, payload in retained_messages():
        handle_message(state, topic, payload)
    feeds = {k: r.value for k, r in state.store.snapshot().items() if k.startswith("derived/")}
    # One retained reading per input: live values are right, totals start at 0.
    assert feeds["derived/consumed/today"] == 0.0
    assert feeds["derived/solar/now"] == sum(
        state.store.get(f"Inverter {n} / pvInputPower").value for n in ("One", "Two", "Three"))
    assert feeds["derived/car/charging"] in (0.0, 1.0)
    assert feeds["derived/battery/midpoint/over1V"] == 0.0


class FakeInflux:
    """Answers rows() and first() from canned series, and records every query's bounds."""

    def __init__(self, series):
        self.series, self.asked = series, []

    def rows(self, measurement, sensor, since, until):
        self.asked.append(("rows", sensor, since, until))
        return [(t, v) for t, v in self.series.get(sensor, []) if since <= t <= until]

    def first(self, measurement, sensor, since, until):
        self.asked.append(("first", sensor, since, until))
        rows = self.rows(measurement, sensor, since, until)
        self.asked.pop()
        return rows[0] if rows else None


def test_seed_replays_today_and_baselines_the_month():
    d = engine(
        {"id": "import/average", "op": "mean", "feed": "P / import", "positive_only": True},
        {"id": "export/now", "op": "expr", "expr": "max(0, {I / pv} - {derived/import/average})",
         "defaults": {"derived/import/average": 0}},
        {"id": "export/today", "op": "integrate", "feed": "derived/export/now"},
        {"id": "rain/month", "op": "daily_delta", "feed": "R / rain", "reset": "month"},
        {"id": "out/to9am", "op": "window_delta", "feed": "B / out", "end": "09:00"},
        influx_map={"P / import": "power power/0/3", "I / pv": "power inverter/pvInputPower/2",
                    "R / rain": "rain rain", "B / out": "pulse battery/pulseOut/0/5"},
    )
    now = local(2026, 10, 21, 12)
    noon = [local(2026, 10, 21, 11) + 60 * i for i in range(61)]
    fake = FakeInflux({
        "power/0/3": [(local(2026, 10, 21, 2), 200.0), (local(2026, 10, 21, 3), 0.0)],
        "inverter/pvInputPower/2": [(t, 1200.0) for t in noon],
        "rain": [(local(2026, 10, 1, 4), 6900.0), (local(2026, 10, 21, 6), 6959.8)],
        "battery/pulseOut/0/5": [(local(2026, 10, 21, 0, 1), 1000.0), (local(2026, 10, 21, 8, 59), 1450.0),
                                 (local(2026, 10, 21, 11), 1600.0)],
    })
    got = values(influx.seed(d, fake, now))
    assert got["derived/export/now"] == 1000.0, "1200 W less the 200 W average import"
    assert got["derived/export/today"] == pytest.approx(1000.0), "an hour at 1000 W"
    assert got["derived/out/to9am"] == 450.0
    assert d.entries["derived/rain/month"].operator.base == 6900.0, "baseline from the 1st"
    # Every query was bounded; no replay reached back more than a day and a half, and the
    # month baseline no further than the 1st.
    for kind, sensor, since, until in fake.asked:
        assert until <= now, (kind, sensor)
        floor = local(2026, 10, 1) if kind == "first" else now - influx.MAX_REPLAY_S
        assert since >= floor, (kind, sensor)
    pv_since = [s for k, sensor, s, u in fake.asked if sensor == "inverter/pvInputPower/2"][0]
    assert pv_since == local(2026, 10, 21), "replayed from midnight, the integral's period"


def test_seed_carries_on_when_influx_fails():
    class Broken:
        def rows(self, *a, **k):
            raise OSError("connection refused")

        def first(self, *a, **k):
            raise OSError("connection refused")

    d = engine({"id": "a/today", "op": "daily_delta", "feed": "P / a"},
               {"id": "r/year", "op": "daily_delta", "feed": "R / r", "reset": "year"},
               influx_map={"P / a": "pulse pulse/0/0", "R / r": "rain rain"})
    assert influx.seed(d, Broken(), local(2026, 10, 21, 12)) == []
