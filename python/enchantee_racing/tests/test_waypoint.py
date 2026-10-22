"""Tests for the chart waypoint: engine/waypoint.py, its place in the store, and its API.

The feature as asked for (DESIGN 15): hold on the chart to drop a waypoint, steer to it on
the race screen exactly like a race mark, see a straight line to it on the chart, have it
clear itself on arrival, and have a new hold replace the old one with nothing remembered.
Each of those is a test below, and so are the two rules that keep it out of a race's way.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402
from engine import course as course_module  # noqa: E402
from engine import nav, race  # noqa: E402
from engine import waypoint as wpm  # noqa: E402
from store import Store  # noqa: E402

CONFIG = app_module.load_config()
TUNING = race.Config.from_document(CONFIG["race"])
T0 = 1_755_500_000.0

KINGSTON_N = nav.LatLon(-31.98083, 115.5663)
"""Kingston Reef North Cardinal Buoy, from config/navaids.json. The example the feature was
asked for: a passage to Rottnest that has to clear Kingston Reef to the north."""

STANDOFF = nav.destination(KINGSTON_N, 0.0, 150.0)
"""Where a crew would actually drop the waypoint: 150 m north of the cardinal, since a
north cardinal is passed on its north side and steering at the buoy is steering at the
reef."""


def _fix(position, cog=None, sog=None, ts=T0):
    return race.Fix(position=nav.as_latlon(position), ts=ts, cog=cog, sog=sog)


def _client():
    ticker = {"t": T0}
    store = Store(clock=lambda: ticker["t"])
    flask_app = app_module.create_app(store, CONFIG)
    flask_app.config["TESTING"] = True
    flask_app.config["EVENT_PUBLISHER"] = [].append
    return flask_app.test_client(), store, ticker


def _post(client, path, body):
    response = client.post(path, json=body)
    return response, json.loads(response.get_data(as_text=True))


def _state(client):
    return json.loads(client.get("/api/state").get_data(as_text=True))


def _sail(store, ticker, start, bearing, metres, step_m=10.0, sog=5.0):
    """Feed fixes along a straight line, one a second, with COG and SOG to match."""
    store.set("cog", bearing)
    store.set("sog", sog)
    travelled = 0.0
    while travelled <= metres:
        p = nav.destination(start, bearing, travelled)
        ticker["t"] += 1.0
        store.set("cog", bearing)
        store.set("sog", sog)
        store.on_position({"lat": p.lat, "lon": p.lon})
        travelled += step_m


# --- the engine --------------------------------------------------------------


def test_the_panel_numbers_have_the_same_shape_as_a_race_mark():
    """"Exactly like a race mark" is the race screen drawing both with the same code, which
    it can only do if the two payloads have the same keys."""
    marks = course_module.index_marks(CONFIG["marks"])
    chosen = [c for c in CONFIG["courses"]["courses"] if c["id"] == "frostbite-3"][0]
    context = race.Context(course=chosen, marks=marks, lines=CONFIG["lines"], config=TUNING)
    state, _ = race.select(race.initial(), context, "frostbite-3", T0)
    here = nav.destination(nav.as_latlon(marks["dolphin-east-42b"]), 0.0, 500.0)
    racing = race.navigation(state, context, _fix(here, cog=90.0), twd=200.0)

    wp = wpm.drop(STANDOFF, "x", T0)
    passage = wpm.navigation(wp, _fix(here, cog=90.0), twd=200.0)
    assert set(passage) == set(racing)
    assert passage["next_name"] is None and passage["transit"] is None


def test_bearing_and_distance_are_to_the_dropped_point():
    origin = nav.destination(STANDOFF, 75.0, 5000.0)    # ENE of it, towards Fremantle
    payload = wpm.navigation(wpm.drop(STANDOFF, None, T0), _fix(origin, cog=270.0))
    assert abs(payload["distance_m"] - 5000.0) < 1.0
    assert abs(payload["bearing"] - 255.0) < 0.1
    # signed, port negative, like TWA: 255 seen from a heading of 270 is 15 to port
    assert abs(payload["relative"] - -15.0) < 0.1


def test_the_numbers_blank_without_a_fix():
    """The store hands over no fix past the 5 s cutoff, and then the panel shows dashes."""
    assert wpm.navigation(wpm.drop(STANDOFF, None, T0), None) is None
    payload = wpm.payload(wpm.drop(STANDOFF, None, T0), None)
    assert payload["nav"] is None and payload["lat"] == STANDOFF.lat


def test_the_name_comes_from_a_nearby_charted_feature_and_never_moves_the_point():
    names = CONFIG["waypoint_names"]
    assert wpm.name_for(STANDOFF, names) == "Kingston Reef North Cardinal Buoy"
    wp = wpm.drop(STANDOFF, wpm.name_for(STANDOFF, names), T0)
    assert wp.position == STANDOFF, "a cardinal marks a hazard; the stand-off is the point"
    # open water between Fremantle and Rottnest borrows no name at all
    gage_roads = nav.LatLon(-32.03, 115.66)
    assert wpm.name_for(gage_roads, names) is None


def test_arriving_within_the_radius_clears_it_even_when_the_boat_stops():
    """A mooring is never put astern: the boat stops, and below min SOG COG means nothing."""
    wp = wpm.drop(STANDOFF, None, T0)
    near = nav.destination(STANDOFF, 90.0, TUNING.waypoint_arrival_radius_m - 5.0)
    after, arrived = wpm.on_fix(wp, _fix(near, cog=None, sog=0.0), TUNING)
    assert after is None and arrived


def test_passing_it_clears_it_like_rounding_a_mark():
    wp = wpm.drop(STANDOFF, None, T0)
    # pass 50 m south of it heading west: inside the arming radius, outside arrival
    for x in range(200, -201, -10):
        p = nav.destination(nav.destination(STANDOFF, 180.0, 50.0), 90.0, float(x))
        wp, arrived = wpm.on_fix(wp, _fix(p, cog=270.0, sog=5.0), TUNING)
        if arrived:
            break
    assert arrived, "abeam and then astern for astern_fixes fixes is a rounding"
    assert x < 0, "and not before it was abeam"


def test_sailing_past_well_wide_does_not_clear_it():
    """Wide of the arming radius it was not reached, so the bearing stays up."""
    wp = wpm.drop(STANDOFF, None, T0)
    for x in range(1000, -1001, -20):
        p = nav.destination(nav.destination(STANDOFF, 180.0, 400.0), 90.0, float(x))
        wp, arrived = wpm.on_fix(wp, _fix(p, cog=270.0, sog=5.0), TUNING)
        assert not arrived
    assert wp is not None


# --- the store and the API ----------------------------------------------------


def test_hold_on_the_chart_drops_it_and_every_device_sees_it():
    client, _store, _ticker = _client()
    response, body = _post(client, "/api/waypoint", {"lat": STANDOFF.lat, "lon": STANDOFF.lon})
    assert response.status_code == 200
    assert body["waypoint"]["name"] == "Kingston Reef North Cardinal Buoy"
    state = _state(client)
    assert state["waypoint"]["lat"] == STANDOFF.lat
    assert state["waypoint"]["nav"] is None, "no fix yet, so dashes"


def test_the_race_panel_numbers_appear_once_there_is_a_fix():
    client, store, _ticker = _client()
    _post(client, "/api/waypoint", {"lat": STANDOFF.lat, "lon": STANDOFF.lon})
    here = nav.destination(STANDOFF, 75.0, 8000.0)
    store.set("cog", 255.0)
    store.on_position({"lat": here.lat, "lon": here.lon})
    nav_ = _state(client)["waypoint"]["nav"]
    assert abs(nav_["bearing"] - 255.0) < 0.1 and abs(nav_["relative"]) < 0.1


def test_a_new_hold_replaces_the_old_one_and_forgets_it():
    client, store, ticker = _client()
    _post(client, "/api/waypoint", {"lat": STANDOFF.lat, "lon": STANDOFF.lon})
    # get it armed, so a leftover arming would show up as an early clear of the new one
    start = nav.destination(STANDOFF, 90.0, 70.0)
    store.set("cog", 270.0)
    store.on_position({"lat": start.lat, "lon": start.lon})
    other = nav.LatLon(-31.9960, 115.5420)              # Thomson Bay
    _post(client, "/api/waypoint", {"lat": other.lat, "lon": other.lon})
    wp = _state(client)["waypoint"]
    assert (wp["lat"], wp["lon"]) == (other.lat, other.lon)
    # sail on past Kingston: the old point is gone, so nothing clears
    _sail(store, ticker, start, 270.0, 300.0)
    assert _state(client)["waypoint"] is not None


def test_arrival_clears_it_and_the_bearing_goes_away():
    client, store, ticker = _client()
    _post(client, "/api/waypoint", {"lat": STANDOFF.lat, "lon": STANDOFF.lon})
    _sail(store, ticker, nav.destination(STANDOFF, 90.0, 1000.0), 270.0, 2000.0)
    assert _state(client)["waypoint"] is None


def test_clear_removes_it():
    client, _store, _ticker = _client()
    _post(client, "/api/waypoint", {"lat": STANDOFF.lat, "lon": STANDOFF.lon})
    response, body = _post(client, "/api/waypoint", {"clear": True})
    assert response.status_code == 200 and body["waypoint"] is None
    assert _state(client)["waypoint"] is None


def test_a_hold_during_a_race_does_nothing():
    """The crew steers to the course while racing. A stray hold on the chart must not put a
    second target on the race screen."""
    client, _store, _ticker = _client()
    _post(client, "/api/select", {"course": "frostbite-3"})
    _post(client, "/api/timer", {"hooter": 5})
    response, _body = _post(client, "/api/waypoint", {"lat": STANDOFF.lat, "lon": STANDOFF.lon})
    assert response.status_code == 409
    assert _state(client)["waypoint"] is None


def test_choosing_a_course_clears_it():
    client, _store, _ticker = _client()
    _post(client, "/api/waypoint", {"lat": STANDOFF.lat, "lon": STANDOFF.lon})
    _post(client, "/api/select", {"course": "frostbite-3"})
    assert _state(client)["waypoint"] is None


def test_bad_positions_are_refused():
    client, _store, _ticker = _client()
    for body in ({}, {"lat": "x", "lon": 1}, {"lat": 95.0, "lon": 115.0}):
        response, _ = _post(client, "/api/waypoint", body)
        assert response.status_code == 400, body


# --- the map's half of it ------------------------------------------------------


def test_geo_js_inverts_its_projection_the_way_nav_does():
    """A hold on the chart becomes a lat/lon through Geo.fromEnu, a transcription of
    nav.latlon_from_enu. Checked numerically where there is a JavaScript engine, which there
    is on a bench and is not on the Pi, so on the Pi this checks the transcription exists."""
    import shutil
    import subprocess
    geo = (ROOT / "static" / "geo.js").read_text(encoding="utf-8")
    assert "function fromEnu(origin, e, n)" in geo and "fromEnu: fromEnu" in geo
    node = shutil.which("node")
    if not node:
        return
    origin = {"lat": -32.0031847, "lon": 115.8120142}
    cases = [(-24000.0, 2500.0), (0.0, 0.0), (1500.0, -3200.0)]
    script = ("var window = {};" + geo +
              "var o=%s; console.log(JSON.stringify(%s.map(function(c){"
              "return window.Geo.fromEnu(o, c[0], c[1]);})));"
              % (json.dumps(origin), json.dumps(cases)))
    out = json.loads(subprocess.run([node, "-e", script], capture_output=True,
                                    text=True, check=True).stdout)
    for (e, n), got in zip(cases, out):
        want = nav.latlon_from_enu(nav.LatLon(origin["lat"], origin["lon"]), e, n)
        assert abs(got["lat"] - want.lat) < 1e-12 and abs(got["lon"] - want.lon) < 1e-12


def test_the_map_drops_a_waypoint_on_a_hold_and_draws_the_line_from_the_boat():
    code = (ROOT / "static" / "map.js").read_text(encoding="utf-8")
    page = (ROOT / "templates" / "map.html").read_text(encoding="utf-8")
    assert 'id="layer-waypoint"' in page and 'id="map-notice"' in page
    # a hold, not a tap: a tap on this chart is the start of a pan
    assert "HOLD_MS" in code and "setTimeout(function () { fireHold(" in code
    # relative, like every fetch in this app (CLAUDE.md)
    assert 'base + "/api/waypoint"' in code
    # two fingers are a pinch, never a hold
    start = code.index("function onTouchStart")
    assert "cancelHold();" in code[start:code.index("function onTouchMove")]
    assert "waypoint-line" in code
    # iOS 12 has no Pointer Events; the gestures are touch events and so is the hold
    assert '"pointerdown"' not in code and '"contextmenu"' not in code


def test_the_gar_dial_shows_the_waypoint_as_wpt():
    """GAR puts a waypoint in the race band and on the diamond, labelled WPT not NEXT."""
    code = (ROOT / "static" / "gar.js").read_text(encoding="utf-8")
    page = (ROOT / "templates" / "gar.html").read_text(encoding="utf-8")
    assert 'id="r-lbl"' in page
    assert '"WPT' in code and "d.waypoint" in code
    # the band is switched on by a waypoint as well as by a race
    assert '|| d.waypoint))' in code


def test_the_classic_hud_shows_the_waypoint_in_its_racing_rows():
    """Panel 4 swaps to the racing rows for a waypoint, labelled "waypoint" not "next mark"."""
    page = (ROOT / "templates" / "hud.html").read_text(encoding="utf-8")
    assert 'id="r-mark-lbl"' in page
    assert '"waypoint" : "next mark"' in page
    assert "|| !!d.waypoint)" in page


if __name__ == "__main__":
    import traceback

    count = 0
    for test_name, test in sorted(globals().items()):
        if not test_name.startswith("test_") or not callable(test):
            continue
        try:
            test()
        except Exception:
            count += 1
            print("FAIL  " + test_name)
            traceback.print_exc()
        else:
            print("ok    " + test_name)
    print("%d failed" % count if count else "all passed")
    raise SystemExit(1 if count else 0)
