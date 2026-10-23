"""emon_feed: needs only the standard library and pytest (DESIGN D4, 9.5)."""

import json
import math
import os
import subprocess
import sys

import pytest

from pyemonlib import emon_feed as ef
from pyemonlib.emon_feed import Reading

PYEMON = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --- isolation --------------------------------------------------------------------------

def test_importing_emon_feed_pulls_in_nothing_beyond_the_standard_library():
    """The race app and the recorder will import this; it must not drag the C++ extension,
    paho, influxdb_client, yaml or numpy in with it."""
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "import pyemonlib.emon_feed;"
        "bad = [m for m in ('pyemonlib.emonSuite', 'paho', 'influxdb_client', 'yaml', 'numpy')"
        "       if m in sys.modules];"
        "print(','.join(bad))"
    )
    out = subprocess.run([sys.executable, "-c", code, PYEMON], capture_output=True, text=True,
                         check=True)
    assert out.stdout.strip() == "", out.stdout


# --- topics and keys --------------------------------------------------------------------

def _r(**kw):
    base = dict(node="pulse", sub=0, field="power", value=2867, unit="W", kind="power", idx=2,
                group="Power board", name="Consumed", t=1757580061.0)
    base.update(kw)
    return Reading(**base)


def test_topic_is_structural():
    assert _r().topic == "emon/pulse/0/power/2"
    assert _r(idx=None).topic == "emon/pulse/0/power"
    assert _r(sub=None, idx=None).topic == "emon/pulse/power"


def test_derived_topic_and_key():
    r = Reading(node="derived", sub=None, field="power/consumed/today", value=18452, unit="Wh")
    assert r.topic == "emon/derived/power/consumed/today"
    assert r.key == "derived/power/consumed/today"


def test_key_is_group_slash_name_and_falls_back_to_topic():
    assert _r().key == "Power board / Consumed"
    assert _r(name="").key == "emon/pulse/0/power/2"


# --- envelope ---------------------------------------------------------------------------

def test_envelope_carries_everything_and_omits_what_is_absent():
    env = ef.envelope(_r(rssi=-61))
    assert env == {"s": 1, "v": 2867, "u": "W", "t": 1757580061.0, "kind": "power",
                   "node": "pulse", "sub": 0, "field": "power", "idx": 2,
                   "group": "Power board", "name": "Consumed", "rssi": -61}
    bare = ef.envelope(Reading(node="x", sub=None, field="f", value=1))
    assert bare == {"s": 1, "v": 1, "node": "x", "field": "f"}


def test_envelope_json_is_compact_and_strict():
    text = ef.envelope_json(_r(value=float("nan")))
    assert ", " not in text and '": ' not in text
    assert json.loads(text)["v"] is None, "NaN is not JSON; it becomes null"


def test_plain_converts_numpy_scalars_when_numpy_is_present():
    np = pytest.importorskip("numpy")
    assert ef.plain(np.float32(1.5)) == 1.5 and type(ef.plain(np.float32(1.5))) is float
    assert type(ef.plain(np.int64(3))) is int
    assert ef.plain({"lat": np.float64(-32.0)}) == {"lat": -32.0}


# --- parse ------------------------------------------------------------------------------

def test_parse_round_trips_an_envelope():
    original = _r(rssi=-61)
    back = ef.parse(original.topic, ef.envelope_json(original).encode())
    assert back == original


def test_parse_accepts_legacy_bare_numbers_keyed_by_topic():
    r = ef.parse("power/0/2", b"2867.0", arrival=100.0)
    assert r.value == 2867.0 and r.t == 100.0
    assert r.key == "power/0/2" and r.topic == "power/0/2"


def test_parse_keeps_a_legacy_json_object_whole():
    r = ef.parse("gps/position/0", '{"lat":-32.0,"lon":115.8,"ts":1}', arrival=5.0)
    assert r.value == {"lat": -32.0, "lon": 115.8, "ts": 1}
    assert r.key == "gps/position/0"


@pytest.mark.parametrize("payload", [b"", b"abc", b"nan", b"inf", b"{not json", b"1.2.3", True])
def test_parse_rejects_what_is_not_a_reading(payload):
    assert ef.parse("t", payload) is None


# --- catalogue and store ----------------------------------------------------------------

def test_catalogue_resolves_names_and_reports_duplicates():
    cat = ef.Catalogue()
    cat.add(_r())
    cat.add(_r(field="pulse", name="Consumed (pulse)"))
    assert cat.topic("Power board / Consumed") == "emon/pulse/0/power/2"
    assert "Power board / Consumed (pulse)" in cat and len(cat) == 2
    cat.add(_r(sub=1))                       # same name, different channel
    assert cat.duplicates == {"Power board / Consumed": {"emon/pulse/0/power/2",
                                                         "emon/pulse/1/power/2"}}


def test_store_keeps_the_latest_and_ages_it():
    now = [1000.0]
    store = ef.Store(clock=lambda: now[0])
    store.put(_r(t=990.0))
    assert store.age("Power board / Consumed") == 10.0
    stamped = store.put(_r(t=None, value=1))     # no t: stamped on arrival
    assert stamped.t == 1000.0
    now[0] = 1003.0
    assert store.get("Power board / Consumed").value == 1
    assert store.age("Power board / Consumed") == 3.0
    assert store.age("missing") is None and len(store) == 1


# --- maths: the race app's cases (enchantee_racing tests/test_nav.py, test_gar.py) -------

@pytest.mark.parametrize("given,expected", [
    (0, 0), (90, 90), (-90, -90), (179, 179), (181, -179), (190, -170), (-190, 170),
    (359, -1), (360, 0), (180, 180), (-180, 180), (540, 180)])
def test_norm180_is_port_negative(given, expected):
    assert abs(ef.norm180(given) - expected) < 1e-9


def test_twa_and_its_missing_inputs():
    assert ef.twa(84.0, 192.0) == -108.0
    assert ef.twa(None, 192.0) is None and ef.twa(84.0, None) is None


def test_awa_prefers_the_masthead_and_falls_back_to_bearing():
    assert ef.awa(350.0) == -10.0
    assert ef.awa(None, awd=100.0, hdg=90.0) == 10.0
    assert ef.awa(None, awd=None, hdg=90.0) is None


def test_leeway_is_cog_minus_heading_signed_port_negative():
    assert ef.leeway(95.0, 90.0, 5.0) == 5.0
    assert ef.leeway(85.0, 90.0, 5.0) == -5.0
    assert ef.leeway(2.0, 355.0, 5.0) == 7.0
    assert ef.leeway(355.0, 2.0, 5.0) == -7.0


def test_leeway_is_blank_below_a_knot_and_needs_all_three():
    assert ef.leeway(200.0, 90.0, ef.LEEWAY_MIN_SOG_KT - 0.1) is None
    assert ef.leeway(95.0, 90.0, ef.LEEWAY_MIN_SOG_KT) == 5.0
    assert ef.leeway(None, 90.0, 5.0) is None
    assert ef.leeway(95.0, None, 5.0) is None
    assert ef.leeway(95.0, 90.0, None) is None


def test_heel_is_atan2_of_y_and_z_and_ignores_pitch():
    for deg in (12.0, -20.0):
        y, z = math.sin(math.radians(deg)), math.cos(math.radians(deg))
        assert abs(ef.heel(y, z) - deg) < 1e-9
    pitch, heel = math.radians(8.0), math.radians(15.0)
    assert abs(ef.heel(math.sin(heel) * math.cos(pitch), math.cos(heel) * math.cos(pitch)) - 15.0) < 1e-9


def test_heel_needs_both_axes_and_enough_gravity():
    assert ef.heel(None, 0.2) is None and ef.heel(0.2, None) is None
    assert ef.heel(0.1, 0.1) is None


# --- maths: the recorder's ----------------------------------------------------------------

def test_distance_is_a_degree_of_latitude_on_a_sphere():
    assert abs(ef.distance_m(-32.0, 115.8, -31.0, 115.8) - 2 * math.pi * 6371000 / 360) < 1e-6
    assert ef.distance_m(-32.0, 115.8, -32.0, 115.8) == 0.0


def test_integrate_wh_by_trapezoid():
    assert ef.integrate_wh([(0, 100.0), (3600, 100.0)]) == pytest.approx(100.0)
    assert ef.integrate_wh([(0, 0.0), (3600, 200.0)]) == pytest.approx(100.0)
    assert ef.integrate_wh([]) == 0.0 and ef.integrate_wh([(0, 5.0)]) == 0.0


def test_integrate_wh_does_not_bridge_long_gaps():
    samples = [(0, 100.0), (60, 100.0), (60 + 3600, 100.0)]
    assert ef.integrate_wh(samples) == pytest.approx(100.0 * 3660 / 3600)
    assert ef.integrate_wh(samples, max_gap_s=300) == pytest.approx(100.0 * 60 / 3600)


# --- derived operators (DESIGN 6.3) -----------------------------------------------------


@pytest.fixture
def perth(monkeypatch):
    """Period boundaries are local time; pin it so these run the same anywhere."""
    import time
    monkeypatch.setenv("TZ", "Australia/Perth")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def local(y, mo, d, h=0, mi=0, s=0):
    import time
    return time.mktime((y, mo, d, h, mi, s, 0, 0, -1))


def test_period_start_daily_nine_am_month_and_year(perth):
    t = local(2026, 10, 21, 8, 59)
    assert ef.period_start(t) == local(2026, 10, 21)
    assert ef.period_start(t, "09:00") == local(2026, 10, 20, 9)
    assert ef.period_start(local(2026, 10, 21, 9), "09:00") == local(2026, 10, 21, 9)
    assert ef.period_start(local(2026, 11, 1, 3), "09:00") == local(2026, 10, 31, 9)
    assert ef.period_start(t, "month") == local(2026, 10, 1)
    assert ef.period_start(t, "year") == local(2026, 1, 1)
    with pytest.raises(ValueError):
        ef.period_start(t, "9am")
    with pytest.raises(ValueError):
        ef.DailyDelta(reset="25:00")


def test_daily_delta_counts_from_the_first_value_and_resets_at_midnight(perth):
    d = ef.DailyDelta(scale=2.5)
    assert d.value is None
    assert d.update(1000, local(2026, 10, 21, 0, 1)) == 0.0
    assert d.update(1040, local(2026, 10, 21, 12)) == 100.0
    assert d.update(1100, local(2026, 10, 22, 0, 2)) == 0.0, "a new day starts from its first value"
    assert d.update(1104, local(2026, 10, 22, 1)) == 10.0


def test_daily_delta_carries_across_a_counter_reset(perth):
    d = ef.DailyDelta()
    d.update(500, local(2026, 10, 21, 1))
    d.update(520, local(2026, 10, 21, 2))
    assert d.update(3, local(2026, 10, 21, 3)) == 20.0, "a node restart zeroes its counter"
    assert d.update(10, local(2026, 10, 21, 4)) == 20.0, "not yet confirmed"
    assert d.update(15, local(2026, 10, 21, 5)) == 32.0, "three in a row from near zero: carried"
    assert d.update(16, local(2026, 10, 21, 6)) == 33.0


def test_daily_delta_ignores_relayed_copies_arriving_late(perth):
    """23 Oct 2026 20:48: the direct and relayed copies of a packet, 8 Wh apart."""
    d = ef.DailyDelta()
    d.update(58_601_260, local(2026, 10, 23, 0, 1))
    seq = [58_620_648, 58_620_640, 58_620_648, 58_620_640, 58_620_640, 58_620_640, 58_620_656]
    for i, v in enumerate(seq):
        d.update(v, local(2026, 10, 23, 20, 48, 28 + i))
    assert d.value == 58_620_656 - 58_601_260


def test_daily_delta_drops_a_corrupted_low_reading(perth):
    """23 Oct 2026 13:17:16: one line put Consumed at 2776 among readings of 58.6 million."""
    d = ef.DailyDelta()
    d.update(58_570_000, local(2026, 10, 23, 0, 1))
    d.update(58_620_000, local(2026, 10, 23, 13, 17, 12))
    assert d.update(2776, local(2026, 10, 23, 13, 17, 16)) == 50_000.0, "set aside"
    assert d.update(58_620_004, local(2026, 10, 23, 13, 17, 20)) == 50_004.0
    assert d.update(58_620_010, local(2026, 10, 23, 13, 17, 24)) == 50_010.0


def test_daily_delta_undoes_a_single_spike_upwards(perth):
    d = ef.DailyDelta()
    for i, v in enumerate((1000, 1010)):
        d.update(v, local(2026, 10, 23, 10, 0, i))
    assert d.update(9_000_000, local(2026, 10, 23, 10, 0, 2)) == 8_999_000.0, "shows until undone"
    d.update(1020, local(2026, 10, 23, 10, 0, 3))
    d.update(1030, local(2026, 10, 23, 10, 0, 4))
    assert d.update(1040, local(2026, 10, 23, 10, 0, 5)) == 40.0


def test_daily_delta_seeded_from_influx_resumes_the_total(perth):
    d = ef.DailyDelta(reset="09:00")
    d.seed(6950.0, local(2026, 10, 21, 9, 3))
    assert d.value == 0.0
    assert d.update(6959.8, local(2026, 10, 21, 15)) == pytest.approx(9.8)


def test_integrate_is_trapezoidal_skips_gaps_and_resets(perth):
    i = ef.Integrate()
    t0 = local(2026, 10, 21, 10)
    assert i.update(100, t0) == 0.0
    assert i.update(300, t0 + 60) == pytest.approx(200 * 60 / 3600)
    assert i.update(300, t0 + 60 + 600) == pytest.approx(200 * 60 / 3600), "10 min gap not bridged"
    assert i.update(300, t0 + 720) == pytest.approx((200 * 60 + 300 * 60) / 3600)
    assert i.update(50, local(2026, 10, 22, 0, 0, 30)) == 0.0
    i.seed(1234.5, local(2026, 10, 22, 0, 1))
    assert i.value == 1234.5


def test_extreme_by_magnitude_ignoring_zero(perth):
    e = ef.Extreme(kind="max", by_abs=True, ignore_zero=True)
    t = local(2026, 10, 21, 10)
    for v in (0.0, 0.3, -1.2, 0.9, 0.0):
        e.update(v, t)
    assert e.value == -1.2
    assert ef.Extreme(kind="min").update(5, t) == 5
    m = ef.Extreme(kind="min")
    for v in (53.1, 52.4, 54.0):
        m.update(v, t)
    assert m.value == 52.4
    assert m.update(55, local(2026, 10, 22, 1)) == 55, "and resets at the boundary"


def test_mean_of_positive_values(perth):
    m = ef.Mean(positive_only=True)
    t = local(2026, 10, 21, 10)
    assert m.value is None
    for v in (0, 100, 0, 300):
        m.update(v, t)
    assert m.value == 200.0
    m.seed(50.0, 4, t)
    assert m.update(250, t) == 90.0


def test_roll_reports_a_new_period_so_totals_can_drop_to_zero_without_input(perth):
    d = ef.DailyDelta()
    d.update(1, local(2026, 10, 21, 23))
    d.update(5, local(2026, 10, 21, 23, 30))
    assert not d.roll(local(2026, 10, 21, 23, 59))
    assert d.roll(local(2026, 10, 22, 0, 0, 10)) and d.value is None


def test_expr_reads_feeds_in_braces():
    e = ef.Expr("{derived/import/today} / 1000 * 0.262")
    assert e.names == ["derived/import/today"]
    assert e({"derived/import/today": 5000}) == pytest.approx(1.31)
    assert e({}) is None and e({"derived/import/today": None}) is None
    assert ef.Expr("max(0, {Inverter Two / pvInputPower} - {derived/a})")(
        {"Inverter Two / pvInputPower": 100, "derived/a": 140}) == 0.0
    assert ef.Expr("{Power board / Car} >= 200")({"Power board / Car": 250}) == 1.0
    assert ef.Expr("({t} - 45) / 0.7 if {t} >= 40 else 0")({"t": 66.0}) == pytest.approx(30.0)
    assert ef.Expr("norm180({a} - {b})")({"a": 10, "b": 350}) == 20.0
    assert ef.Expr("{a} / {b}")({"a": 1, "b": 0}) is None, "division by zero is no value"
    assert ef.Expr("{a}\n  + {b}")({"a": 1, "b": 2}) == 3.0, "folded over lines, as YAML >- can"


@pytest.mark.parametrize("bad", [
    "__import__('os').system('true')", "{a}.real", "open('x')", "[1, 2]", "'text'",
    "lambda: 1", "{a", "x + 1",
])
def test_expr_refuses_anything_but_arithmetic(bad):
    with pytest.raises((ValueError, SyntaxError)):
        ef.Expr(bad)


def test_window_delta_reports_out_to_nine_am_and_holds_it(perth):
    w = ef.WindowDelta(reset="00:00", end="09:00")
    w.update(100, local(2026, 10, 21, 0, 5))
    assert w.update(160, local(2026, 10, 21, 8, 55)) is None, "not reported while open"
    assert w.update(175, local(2026, 10, 21, 9, 1)) == 60.0
    assert w.update(300, local(2026, 10, 21, 23)) == 60.0, "held after the close"
    w.update(310, local(2026, 10, 22, 0, 1))
    assert w.value == 60.0, "yesterday's figure until today's window closes"
    assert w.roll(local(2026, 10, 22, 9, 0, 5)) and w.value == 0.0, "closed by the clock alone"


def test_expr_defaults_stand_in_for_a_missing_input():
    e = ef.Expr("max(0, {inv2} - {avg})", defaults={"avg": 0})
    assert e({"inv2": 400}) == 400.0
    assert e({"inv2": 400, "avg": 150}) == 250.0
    assert e({"avg": 150}) is None, "only the named input has a default"
