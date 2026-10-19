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
