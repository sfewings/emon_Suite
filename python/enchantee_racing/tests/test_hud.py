"""Unit tests for store.py, mqtt_client.py and the HUD routes in app.py.

Build order step 3. What is worth testing here is not the display, which is a verbatim
port and gets checked by eye against /nodered/hud with the boat running, but everything
the flow used to do in function nodes: the topic map, the tolerant number parsing, the
{v, age} envelope, the TWA and AWA derivations, and the motor hold. All of it is pure
or lock-guarded, so all of it can be driven from a fake clock without a broker.

The last test in the routes section is the one that matters for the deployment: the
served page must reference nothing off-box, because the Pi has no internet and a page
that fetches from a CDN is a page that hangs in the cockpit.

Bare asserts and no fixtures, so this runs under pytest and also standalone with
`python tests/test_hud.py`.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # for standalone runs

import app as app_module  # noqa: E402
import mqtt_client  # noqa: E402
import store as store_module  # noqa: E402
from engine import nav  # noqa: E402
from store import Store, derive, parse_number  # noqa: E402

T0 = 1_755_500_000.0  # a fixed epoch, so no test depends on the wall clock


def _store(now=T0):
    """A store whose clock the test controls."""
    clock = {"t": now}
    s = Store(clock=lambda: clock["t"])
    return s, clock


# --- payload parsing -------------------------------------------------------


def test_parse_number_takes_bare_numbers():
    for payload, expected in [("15.9", 15.9), (15.9, 15.9), (b"15.9", 15.9), (" 15.9 ", 15.9),
                              ("-108", -108.0), ("+3.5", 3.5), (".5", 0.5), ("1e3", 1000.0),
                              ("0", 0.0), (0, 0.0)]:
        assert parse_number(payload) == expected, payload


def test_parse_number_tolerates_a_suffix_like_parsefloat_did():
    """Some publishers on this broker append to the value; an RSSI reading among them.

    The flow used JavaScript parseFloat, which takes the leading number and ignores the
    rest. float() would reject the whole reading, so the port keeps the tolerance.
    """
    assert parse_number("1450 rssi=-72") == 1450.0
    assert parse_number("15.9kt") == 15.9
    assert parse_number(b"58.0 degC") == 58.0


def test_parse_number_rejects_what_is_not_a_reading():
    for payload in ["", "   ", "abc", "kt 15", None, "NaN", "Infinity", True, False, [], {}]:
        assert parse_number(payload) is None, payload


# --- the store ------------------------------------------------------------


def test_store_round_trip_and_arrival_time():
    s, clock = _store()
    s.set("sog", 15.9)
    reading = s.get("sog")
    assert reading.v == 15.9 and reading.t == T0
    clock["t"] = T0 + 5
    s.set("sog", 16.2)
    assert s.get("sog") == (16.2, T0 + 5)
    assert s.get("nothing") is None


def test_an_explicit_timestamp_wins_over_the_clock():
    s, _ = _store()
    s.set("sog", 15.9, ts=T0 - 30)
    assert s.get("sog").t == T0 - 30


def test_snapshot_is_a_copy():
    """A request handler reads at leisure while the network loop keeps writing."""
    s, _ = _store()
    s.set("sog", 15.9)
    snap = s.snapshot()
    snap.values["sog"] = "tampered"
    snap.values["hdg"] = "injected"
    assert s.get("sog").v == 15.9
    assert s.get("hdg") is None
    assert "hdg" not in s.snapshot().values


def test_the_store_remembers_when_the_motor_was_last_turning():
    """Once an idle reading replaces it in the cache, that arrival time is gone."""
    s, clock = _store()
    assert s.snapshot().motor_last == 0.0
    s.set("rpm", 1450.0)
    assert s.snapshot().motor_last == T0
    clock["t"] = T0 + 4
    s.set("rpm", 2.0)  # inside the deadband, so not turning
    assert s.snapshot().motor_last == T0, "an idle reading must not restamp the hold"
    clock["t"] = T0 + 6
    s.set("rpm", -900.0)  # astern still counts as turning
    assert s.snapshot().motor_last == T0 + 6


def test_a_reading_inside_the_deadband_never_starts_the_motor_panels():
    s, _ = _store()
    s.set("rpm", store_module.RPM_DEADBAND - 0.1)
    assert derive(s.snapshot(), T0)["motor"] is False


# --- derived values -------------------------------------------------------


def test_an_empty_store_gives_a_full_payload_of_nulls():
    """The page must render dashes on a cold start, not fail."""
    payload = derive(Store().snapshot(), T0)
    assert set(payload["fields"]) == set(store_module.FIELDS)
    assert all(v is None for v in payload["fields"].values())
    assert payload["motor"] is False
    assert payload["now"] == int(T0 * 1000)  # milliseconds, as the Node-RED payload was


def test_twa_is_derived_from_the_wind_direction_and_the_heading():
    """TWA is measured nowhere on this boat: it is norm180(twd - hdg) (DESIGN 3)."""
    s, _ = _store()
    s.set("twd", 90.0)
    s.set("hdg", 180.0)
    assert derive(s.snapshot(), T0)["fields"]["twa"]["v"] == -90.0  # wind to port
    s.set("twd", 270.0)
    assert derive(s.snapshot(), T0)["fields"]["twa"]["v"] == 90.0  # and to starboard


def test_twa_is_signed_port_negative_across_north():
    s, _ = _store()
    s.set("hdg", 10.0)
    s.set("twd", 350.0)
    assert derive(s.snapshot(), T0)["fields"]["twa"]["v"] == -20.0


def test_twa_goes_stale_with_whichever_input_is_older():
    s, _ = _store()
    s.set("twd", 90.0, ts=T0 - 20)
    s.set("hdg", 180.0, ts=T0 - 2)
    twa = derive(s.snapshot(), T0)["fields"]["twa"]
    assert twa["age"] == 20.0, twa
    assert twa["age"] > store_module.STALE_S  # so the page dims it


def test_twa_needs_both_inputs():
    for present in ("twd", "hdg"):
        s, _ = _store()
        s.set(present, 90.0)
        assert derive(s.snapshot(), T0)["fields"]["twa"] is None, present


def test_awa_comes_off_the_masthead_normalised():
    """anemometer/windDirection/0 is already bow relative, just not signed."""
    s, _ = _store()
    s.set("awa", 304.0)
    assert derive(s.snapshot(), T0)["fields"]["awa"]["v"] == -56.0


def test_awa_falls_back_to_the_compass_version():
    """windDirection/1 is a compass bearing, so it needs the heading (DESIGN 3)."""
    s, _ = _store()
    s.set("awd", 304.0)
    s.set("hdg", 192.0)
    assert derive(s.snapshot(), T0)["fields"]["awa"]["v"] == 112.0


def test_the_masthead_reading_wins_over_the_fallback():
    s, _ = _store()
    s.set("awa", 10.0)
    s.set("awd", 304.0)
    s.set("hdg", 192.0)
    assert derive(s.snapshot(), T0)["fields"]["awa"]["v"] == 10.0


def test_awa_is_absent_when_neither_source_is_available():
    s, _ = _store()
    s.set("awd", 304.0)  # no heading to resolve it against
    assert derive(s.snapshot(), T0)["fields"]["awa"] is None


def test_the_motor_panels_are_held_for_ten_seconds_after_the_sevcon_stops():
    """A lumpy idle must not flip the panels back and forth (DESIGN 9.1)."""
    s, _ = _store()
    s.set("rpm", 1450.0)
    hold = store_module.MOTOR_HOLD_S
    assert derive(s.snapshot(), T0)["motor"] is True
    assert derive(s.snapshot(), T0 + hold - 0.1)["motor"] is True
    assert derive(s.snapshot(), T0 + hold + 0.1)["motor"] is False


def test_a_sevcon_that_goes_silent_mid_rev_times_out():
    """Counting from the arrival time, not from now, is what makes this work."""
    s, _ = _store()
    s.set("rpm", 1450.0, ts=T0 - 60)
    assert derive(s.snapshot(), T0)["motor"] is False
    assert derive(s.snapshot(), T0)["fields"]["rpm"]["age"] == 60.0


def test_ages_are_seconds_since_the_reading_arrived():
    s, _ = _store()
    s.set("sog", 15.9, ts=T0 - 3.5)
    assert derive(s.snapshot(), T0)["fields"]["sog"] == {"v": 15.9, "age": 3.5}


def test_a_non_numeric_value_in_the_store_is_not_reported():
    """Nothing should put one there, but the payload must not carry it if it does."""
    s, _ = _store()
    s.set("sog", "fifteen")
    assert derive(s.snapshot(), T0)["fields"]["sog"] is None


# --- the topic map --------------------------------------------------------


def test_every_topic_the_flow_subscribed_to_is_mapped():
    """From the mqtt-in nodes on the Sailing HUD tab, and DESIGN 3."""
    assert mqtt_client.TOPICS == {
        "gps/speed/0": "sog",
        "gps/course/0": "cog",
        "imu/0/heading": "hdg",
        "anemometer/windSpeed/2": "tws",
        "anemometer/windDirection/2": "twd",
        "anemometer/windSpeed/1": "aws",
        "anemometer/windDirection/0": "awa",
        "anemometer/windDirection/1": "awd",
        "sevCon/rpm0": "rpm",
        "sevCon/current0": "cur",
        "sevCon/temperature/controller/0": "ctrl",
        "sevCon/temperature/motor/0": "mot",
    }


def test_position_is_subscribed_and_handled_apart_from_the_bare_numbers():
    """DESIGN build order step 5, done: pyemonlib publishes it, and this reads it."""
    assert mqtt_client.POSITION_TOPIC == "gps/position/0"
    assert mqtt_client.POSITION_TOPIC not in mqtt_client.TOPICS  # not a bare number
    assert mqtt_client.POSITION_TOPIC in mqtt_client.SUBSCRIPTIONS
    assert set(mqtt_client.SUBSCRIPTIONS) == set(mqtt_client.TOPICS) | {mqtt_client.POSITION_TOPIC}


def test_a_position_fix_is_parsed_and_stored():
    """The payload exactly as pyemonlib.emon_mqtt.gpsMessage publishes it."""
    s, _ = _store()
    payload = b'{"lat":-32.0039101,"lon":115.8137589,"ts":1787132108}'
    assert mqtt_client.handle_message(s, "gps/position/0", payload) is True
    assert s.get(store_module.POSITION_KEY).v == {"lat": -32.0039101, "lon": 115.8137589}


def test_a_position_fix_does_not_disturb_the_hud_payload():
    """position is not a HUD field, and /hud/data must keep the shape it was ported at."""
    s, _ = _store()
    mqtt_client.handle_message(s, "gps/position/0", b'{"lat":-32.0,"lon":115.8,"ts":1}')
    payload = derive(s.snapshot(), T0)
    assert set(payload) == {"now", "motor", "fields"}
    assert set(payload["fields"]) == set(store_module.FIELDS)
    assert "position" not in payload["fields"]


def test_a_garbled_fix_is_dropped_rather_than_believed():
    """A wrong position is worse than none: it is what line-crossing tests run on."""
    s, _ = _store()
    for payload in [b"not json", b"[]", b'{"lat":-32.0}', b'{"lat":null,"lon":115.8}',
                    b'{"lat":"south","lon":115.8}', b'{"lat":91.0,"lon":115.8}',
                    b'{"lat":-32.0,"lon":181.0}', b'{"lat":1000.0,"lon":1000.0}', b""]:
        assert mqtt_client.handle_message(s, "gps/position/0", payload) is False, payload
    assert s.get(store_module.POSITION_KEY) is None


def test_a_not_a_number_fix_is_dropped():
    """The one bad value that does not fail a range check.

    json.loads accepts a bare NaN token, float() accepts the result, and every comparison
    with NaN is False, so abs(nan) > 90.0 does not catch it. Left in, a NaN fix makes
    distance_m return nan, which makes both `d < 40` and `d > 40` false so a rounding
    neither arms nor confirms, and makes nav.side() return a confident -1: one NaN fix
    followed by a real one on the other side of the line is a false finish, which is the
    worst failure this app has (DESIGN 11.5).
    """
    for payload in [b'{"lat":NaN,"lon":115.8}', b'{"lat":-32.0,"lon":NaN}',
                    b'{"lat":NaN,"lon":NaN}', b'{"lat":Infinity,"lon":115.8}',
                    b'{"lat":-32.0,"lon":-Infinity}']:
        s, _ = _store()
        assert mqtt_client.handle_message(s, "gps/position/0", payload) is False, payload
        assert s.get(store_module.POSITION_KEY) is None, payload


def test_a_not_a_number_reading_is_dropped():
    """Same trap on the bare-number path: parse_number must reject what it cannot use."""
    for payload in ["nan", "NaN", "inf", "-inf", "Infinity", float("nan"), float("inf")]:
        assert parse_number(payload) is None, payload


def test_zero_zero_is_a_real_coordinate_and_is_kept():
    """Nought degrees by nought is in the Gulf of Guinea, not a no-fix sentinel, and the
    publisher's own comment says so. Filtering it would be inventing a rule."""
    s, _ = _store()
    assert mqtt_client.handle_message(s, "gps/position/0", b'{"lat":0.0,"lon":0.0}') is True
    assert s.get(store_module.POSITION_KEY).v == {"lat": 0.0, "lon": 0.0}


def test_position_goes_stale_at_five_seconds_not_fifteen():
    """A bearing off a 15 s old fix at 6 knots is 46 m out (DESIGN 9.5)."""
    s, _ = _store()
    mqtt_client.handle_message(s, "gps/position/0", b'{"lat":-32.0,"lon":115.8}', ts=T0)
    cutoff = store_module.POSITION_STALE_S
    assert cutoff == 5.0 and cutoff < store_module.STALE_S
    assert store_module.derive_position(s.snapshot(), T0 + cutoff - 0.1)["stale"] is False
    assert store_module.derive_position(s.snapshot(), T0 + cutoff + 0.1)["stale"] is True
    assert store_module.derive_position(s.snapshot(), T0 + 9.0)["age"] == 9.0


def test_no_fix_yet_reports_none_rather_than_a_guess():
    """The publisher omits the topic entirely when there is no fix, so this is the
    no-fix path as well as the cold-start one."""
    assert store_module.derive_position(Store().snapshot(), T0) is None


def test_api_state_carries_the_hud_payload_and_the_position():
    store, _ = _store()
    store.set("sog", 5.58)
    mqtt_client.handle_message(store, "gps/position/0",
                               b'{"lat":-32.0039101,"lon":115.8137589,"ts":1787132108}')
    client, _ = _client(store)
    response = client.get("/api/state")
    assert response.status_code == 200
    state = json.loads(response.get_data(as_text=True))
    assert set(state) == {"now", "motor", "fields", "position", "race"}
    assert state["race"] is None, "no course selected yet, so there is no race to report"
    assert state["fields"]["sog"]["v"] == 5.58
    assert state["position"]["v"] == {"lat": -32.0039101, "lon": 115.8137589}
    assert state["position"]["stale"] is False

    # and /hud/data is unchanged by any of it
    hud = json.loads(client.get("/hud/data").get_data(as_text=True))
    assert set(hud) == {"now", "motor", "fields"}


def test_a_fix_is_a_position_engine_nav_can_use_directly():
    """as_latlon takes the stored dict, so nothing has to convert between the two."""
    s, _ = _store()
    mqtt_client.handle_message(s, "gps/position/0", b'{"lat":-32.0039101,"lon":115.8137589}')
    fix = nav.as_latlon(s.get(store_module.POSITION_KEY).v)
    assert fix == nav.LatLon(-32.0039101, 115.8137589)
    # About 250 m from Club Buoy 32A, which is where the boat was at 13:35 that day.
    assert nav.distance_m(fix, nav.LatLon(-32.002750, 115.812812)) < 400.0


def test_handle_message_stores_under_the_mapped_key():
    s, _ = _store()
    assert mqtt_client.handle_message(s, "imu/0/heading", b"192.4") is True
    assert s.get("hdg").v == 192.4


def test_handle_message_drops_what_it_cannot_use():
    """The broker carries far more than this app cares about."""
    s, _ = _store()
    assert mqtt_client.handle_message(s, "battery/soc/0", b"91") is False
    assert mqtt_client.handle_message(s, "gps/speed/0", b"no fix") is False
    assert s.snapshot().values == {}


def test_handle_message_accepts_an_explicit_arrival_time():
    s, _ = _store()
    mqtt_client.handle_message(s, "gps/speed/0", b"15.9", ts=T0 - 9)
    assert s.get("sog").t == T0 - 9


# --- demo mode ------------------------------------------------------------


def test_the_demo_drives_every_sail_reading_on_the_page():
    s, _ = _store()
    driver = mqtt_client.DemoDriver(s, motor=False)
    driver.step()
    payload = derive(s.snapshot(), T0)
    for key in ("sog", "cog", "hdg", "tws", "twd", "aws", "twa", "awa"):
        assert payload["fields"][key] is not None, key
    # The sail demo leaves the motor alone, so the wind panels stay on show.
    assert payload["motor"] is False
    for key in ("rpm", "cur", "ctrl", "mot"):
        assert payload["fields"][key] is None, key


def test_the_demo_motor_tick_swaps_the_panels():
    s, _ = _store()
    driver = mqtt_client.DemoDriver(s, motor=True)
    driver.step()
    payload = derive(s.snapshot(), T0)
    assert payload["motor"] is True
    for key in ("rpm", "cur", "ctrl", "mot"):
        assert payload["fields"][key] is not None, key


def test_the_demo_produces_a_position():
    """Without one, nothing downstream of the fix can be developed off the boat."""
    s, _ = _store()
    mqtt_client.DemoDriver(s).step()
    position = s.state()["position"]
    assert position is not None
    assert position["stale"] is False
    assert -33.0 < position["v"]["lat"] < -31.0  # on the Swan, not in the Atlantic
    assert 115.0 < position["v"]["lon"] < 116.0


def test_the_demo_starts_where_it_is_told():
    s, _ = _store()
    driver = mqtt_client.DemoDriver(s, start={"lat": -32.002349, "lon": 115.812409})
    assert driver.position == nav.LatLon(-32.002349, 115.812409)
    driver.step()  # and the first fix has moved off the start, not landed on it
    assert nav.distance_m(driver.position, nav.LatLon(-32.002349, 115.812409)) > 1.0


def test_the_demo_position_agrees_with_the_speed_and_course_it_publishes():
    """A demo boat whose track contradicts its own SOG and COG makes every bearing and
    distance-to-mark look wrong for reasons that have nothing to do with the code under
    test, which is the opposite of what a demo is for."""
    s, _ = _store()
    driver = mqtt_client.DemoDriver(s, interval_s=1.0)
    start = driver.position
    for _ in range(60):
        driver.step()

    state = s.state()
    sailed = nav.distance_m(start, nav.as_latlon(state["position"]["v"]))
    expected = state["fields"]["sog"]["v"] * nav.METRES_PER_NM / 3600.0 * 60.0
    assert abs(sailed - expected) < 0.05 * expected, (sailed, expected)
    assert abs(nav.norm180(nav.bearing(start, nav.as_latlon(state["position"]["v"]))
                           - state["fields"]["cog"]["v"])) < 5.0


def test_the_demo_interval_scales_the_distance_sailed():
    """interval_s is the tick length, so it has to reach the dead reckoning."""
    fast, _ = _store()
    slow, _ = _store()
    quick = mqtt_client.DemoDriver(fast, interval_s=1.0)
    tenth = mqtt_client.DemoDriver(slow, interval_s=0.1)
    origin = quick.position
    quick.step()
    tenth.step()
    assert nav.distance_m(origin, quick.position) > 8 * nav.distance_m(origin, tenth.position)


def test_demo_readings_only_use_real_topics():
    """The demo goes in through the same topic map a real message does."""
    for tick in (1, 7, 40):
        for topic, value in mqtt_client.demo_readings(tick) + mqtt_client.demo_motor_readings(tick):
            assert topic in mqtt_client.TOPICS, topic
            assert isinstance(value, float)


def test_the_demo_looks_like_a_boat_beating_upwind():
    """Values a crew would recognise, so a wrong unit or a wrong sign shows up."""
    s, _ = _store()
    mqtt_client.DemoDriver(s).step()
    fields = derive(s.snapshot(), T0)["fields"]
    assert 14.0 < fields["sog"]["v"] < 18.0
    assert 15.0 < fields["tws"]["v"] < 25.0
    assert -180.0 <= fields["twa"]["v"] <= 180.0
    assert abs(fields["twa"]["v"]) > 90.0  # this demo sails with the wind aft of the beam


# --- the routes -----------------------------------------------------------


def _client(store=None):
    store = store or Store()
    flask_app = app_module.create_app(store)
    flask_app.config["TESTING"] = True
    return flask_app.test_client(), store


def test_the_hud_page_is_served():
    client, _ = _client()
    response = client.get("/hud")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "<title>Enchantee HUD</title>" in body
    assert "--sog:   #1e90ff" in body  # the colours the crew already reads


def test_the_race_screen_is_served_even_though_it_is_a_skeleton():
    client, _ = _client()
    assert client.get("/").status_code == 200


def test_the_data_endpoint_returns_the_payload_the_page_expects():
    store, _ = _store()
    store.set("sog", 15.9)
    store.set("hdg", 192.0)
    store.set("twd", 84.0)
    client, _ = _client(store)
    response = client.get("/hud/data")
    assert response.status_code == 200
    payload = json.loads(response.get_data(as_text=True))
    assert set(payload) == {"now", "motor", "fields"}
    assert set(payload["fields"]) == set(store_module.FIELDS)
    assert payload["fields"]["sog"]["v"] == 15.9
    assert payload["fields"]["twa"]["v"] == -108.0  # 84 - 192
    assert payload["fields"]["cog"] is None


def test_the_data_endpoint_tracks_the_store():
    client, store = _client()
    assert json.loads(client.get("/hud/data").get_data(as_text=True))["fields"]["sog"] is None
    store.set("sog", 7.5)
    assert json.loads(client.get("/hud/data").get_data(as_text=True))["fields"]["sog"]["v"] == 7.5


def test_the_page_asks_for_its_data_relative_to_where_it_is_served():
    """The one line that makes the page work behind /race/, on its own port, and under
    mDNS, AP mode or a raw IP alike (CLAUDE.md). An absolute path breaks the prefix.

    The page polls /api/state rather than the original's /data, because the racing panel
    needs race state (DESIGN 9.10), but it is still derived from location.pathname.
    """
    body = _client()[0].get("/hud").get_data(as_text=True)
    assert 'location.pathname.replace(/\\/+$/, "")' in body
    assert '"/api/state"' in body
    assert "fetch(url" in body
    for absolute in ('"/hud/data"', 'fetch("/'):
        assert absolute not in body, absolute


def _hud_url(pathname):
    """Work the page's own URL arithmetic on a given pathname, as the browser would."""
    trimmed = pathname.rstrip("/")
    if trimmed.endswith("/hud"):
        trimmed = trimmed[:-len("/hud")]
    return trimmed + "/api/state"


def test_the_hud_data_url_resolves_under_a_proxy_prefix_and_without_one():
    """Both deployments, since the app is hit on its own port and behind /race/."""
    body = _client()[0].get("/hud").get_data(as_text=True)
    # the page must be doing what _hud_url models: strip trailing slashes, then the
    # /hud segment, then append the endpoint
    assert 'replace(/\\/hud$/, "") + "/api/state"' in body
    assert _hud_url("/hud") == "/api/state"
    assert _hud_url("/hud/") == "/api/state"
    assert _hud_url("/race/hud") == "/race/api/state"
    assert _hud_url("/nodered/hud/") == "/nodered/api/state"

    # and the endpoint it lands on has to exist and carry the race block
    client = _client()[0]
    for url in ("/api/state", "/hud/data"):
        assert client.get(url).status_code == 200, url
    payload = json.loads(client.get("/api/state").get_data(as_text=True))
    assert "race" in payload and "fields" in payload and "motor" in payload


def test_the_racing_panel_replaces_hdg_and_cog_only_while_racing():
    """Panel 4 trades HDG for the mark while racing, keeping COG beside the bearing.

    Pre-rendered and swapped by a class, the way the motor rows are, so a transition
    mid-race costs no relayout (DESIGN 9.10).
    """
    body = _client()[0].get("/hud").get_data(as_text=True)

    # both sets present in the DOM at once
    hdg_rows = re.findall(r'<div class="row" data-race="off">', body)
    assert len(hdg_rows) == 2, "HDG and COG should be the non-racing set"
    racing_rows = re.findall(r'<div class="row multi[^"]*" data-race="on">', body)
    assert len(racing_rows) == 2, "next mark / distance, then bearing / cog / off the bow"

    # the racing set starts hidden: the page loads with no race running
    for row in racing_rows:
        assert " off" in row, row

    # every value the racing rows show, and nothing extra
    for ident in ("r-mark", "r-dist", "r-dist-unit", "r-brg", "r-cog", "r-rel"):
        assert 'id="%s"' % ident in body, ident

    # the labels the crew reads, in the words the race screen uses (DESIGN 9.2)
    for label in ("next mark", "distance", "bearing", "cog", "off the bow"):
        assert ">%s<" % label in body, label

    # racing only: idle, prestart and finished keep the heading
    assert 'd.race && d.race.mode === "racing"' in body
    # HDG has no place in the racing set
    assert 'id="r-hdg"' not in body


def test_the_racing_panel_gets_every_value_it_needs_from_one_poll():
    """The contract behind the markup: one GET carries all five readings and the mode.

    Worth asserting on the payload rather than the page, because the panel is only as
    good as what arrives, and it is the reason the HUD polls /api/state (DESIGN 9.10).
    """
    from engine import course as course_module, race

    store, clock = _store()
    config = app_module.load_config()
    chosen = [c for c in config["courses"]["courses"] if c["id"] == "frostbite-3"][0]
    store.set_race_context(race.Context(
        course=chosen, marks=course_module.index_marks(config["marks"]),
        lines=config["lines"], config=race.Config.from_document(config.get("race"))))
    store.apply_race(lambda s, c, t: race.select(s, c, "frostbite-3", t))
    store.apply_race(lambda s, c, t: race.set_timer(s, c, 0.0, t))     # start now
    store.set("cog", 214.0, ts=clock["t"])
    store.on_position({"lat": -32.0125, "lon": 115.8250}, ts=clock["t"] - 2)
    store.on_position({"lat": -32.0120, "lon": 115.8256}, ts=clock["t"])

    flask_app = app_module.create_app(store, config)
    flask_app.config["TESTING"] = True
    payload = json.loads(flask_app.test_client().get("/api/state").get_data(as_text=True))

    # the swap is driven by this exact value
    assert payload["race"]["mode"] == "racing"
    # and the motor swap still has what it needs from the same poll
    assert "motor" in payload

    assert payload["race"]["leg_name"] == "Dolphin East"
    got = payload["race"]["nav"]
    for key in ("distance_m", "bearing", "relative"):
        assert key in got and got[key] is not None, key
    assert payload["fields"]["cog"]["v"] == 214.0

    # once the fix ages past the 5 s cutoff there is nothing to show, which is what
    # blanks distance, bearing and off the bow rather than dimming them (DESIGN 9.5)
    clock["t"] += 30
    stale = json.loads(flask_app.test_client().get("/api/state").get_data(as_text=True))
    assert stale["race"]["nav"] is None
    assert stale["race"]["mode"] == "racing", "the race is still on, only the fix is old"


def test_the_racing_panel_blanks_rather_than_dims_a_stale_fix():
    """Distance, bearing and off the bow come from nav, which is null once the fix is
    older than 5 s, and a blank is what DESIGN 9.5 requires there. COG is an instrument
    reading and keeps its 15 s dim."""
    body = _client()[0].get("/hud").get_data(as_text=True)
    race_block = re.search(r'function paintRace\(data\) \{(.*?)\n  \}', body, re.S)
    assert race_block, "paintRace not found"
    block = race_block.group(1)
    assert 'nav ? fmt3(nav.bearing) : "---"' in block
    assert 'nav ? fmtSigned(nav.relative) : "---"' in block
    # only COG may be dimmed in this panel
    assert block.count('classList.toggle("stale"') == 1
    assert 'race["r-cog"].classList.toggle("stale"' in block


def test_the_served_page_references_nothing_off_box():
    """The Pi has no internet: a page that fetches from a CDN hangs in the cockpit."""
    body = _client()[0].get("/hud").get_data(as_text=True)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)  # the ffmpeg note is a comment
    assert "http://" not in body and "https://" not in body
    assert "<link" not in body.lower()
    assert not re.search(r"""<script[^>]+src=""", body, re.I)
    assert not re.search(r"""\ssrc\s*=\s*["']//""", body)
    assert "url(" not in body  # no @font-face, no background image


def test_the_page_carries_the_wake_lock_video():
    """Screen Wake Lock needs a secure context and there is no TLS, so the screen is
    kept awake by a hidden looping muted video instead (DESIGN 9.8)."""
    body = _client()[0].get("/hud").get_data(as_text=True)
    video = re.search(r"<video[^>]*id=\"wake\"[^>]*>", body)
    assert video, "no wake-lock video element"
    tag = video.group(0)
    for attribute in ("muted", "loop", "playsinline"):
        assert attribute in tag, attribute
    # Relative, not root-relative: /static/... would break behind the /race/ prefix.
    assert 'src="static/wake.mp4"' in tag, tag

    # Hidden, but not display:none or visibility:hidden. A browser that considers the
    # element invisible may stop decoding it, and a video that is not being decoded is
    # not a reason to keep the backlight on. (.row.off legitimately uses display:none
    # for the motor panel swap, so this looks at the #wake rule alone.)
    rule = re.search(r"#wake\s*\{(.*?)\}", body, re.S)
    assert rule, "no #wake style rule"
    assert "display" not in rule.group(1) and "visibility" not in rule.group(1)
    assert "opacity: 0" in rule.group(1)

    assert "wake.play()" in body  # and it is started from the tap handler, a user gesture
    assert "wakeLock" in body  # the real API is still there for the day there is TLS


def test_the_wake_lock_video_is_served():
    client, _ = _client()
    response = client.get("/static/wake.mp4")
    assert response.status_code == 200
    assert response.mimetype == "video/mp4"
    assert 500 < len(response.get_data()) < 20000  # a couple of kB of black


def test_the_wake_lock_video_is_still_baseline_h264_with_no_audio():
    """The one thing about this file that matters, and it fails silently if wrong.

    iOS plays H.264 baseline inline and refuses other profiles without saying so, and
    the symptom is a screen that sleeps mid-race rather than anything visible at the
    dock. So the codec is pinned here rather than trusted to whoever regenerates it.
    Generated with the ffmpeg command recorded at the end of templates/hud.html.
    """
    data = (ROOT / "static" / "wake.mp4").read_bytes()
    assert data[4:8] == b"ftyp"
    assert b"avc1" in data[8:32], "not an H.264 file"
    assert data.find(b"moov") < data.find(b"mdat"), "not faststart, so it may not begin"
    assert b"soun" not in data, "there must be no audio track"

    avcc = data.find(b"avcC")
    assert avcc > 0, "no H.264 configuration record"
    profile, _compat, level = data[avcc + 5], data[avcc + 6], data[avcc + 7]
    assert profile == 66, "profile %d is not Baseline (66)" % profile
    assert level <= 30, "level %.1f is above 3.0" % (level / 10.0)


def test_the_page_keeps_the_ios_and_safe_area_handling():
    """Ported deliberately, per DESIGN 9.1: the display lives on a phone in a cockpit."""
    body = _client()[0].get("/hud").get_data(as_text=True)
    for needed in ("env(safe-area-inset-top)", "apple-mobile-web-app-capable",
                   "overscroll-behavior: none", "touch-action: manipulation",
                   "user-select: none"):
        assert needed in body, needed


def test_load_config_reads_the_real_files_and_validates_them():
    """app.py owns every file read; engine/ is handed the parsed documents."""
    config = app_module.load_config()
    assert set(config) >= {"marks", "courses", "lines", "problems", "unraceable"}
    assert len(config["courses"]["courses"]) == 4
    assert config["unraceable"] == set()  # nothing in the shipped config blocks racing


if __name__ == "__main__":
    import traceback

    failures = 0
    for test_name, test in sorted(globals().items()):
        if not test_name.startswith("test_") or not callable(test):
            continue
        try:
            test()
        except Exception:
            failures += 1
            print("FAIL  " + test_name)
            traceback.print_exc()
        else:
            print("ok    " + test_name)
    print("%d failed" % failures if failures else "all passed")
    raise SystemExit(1 if failures else 0)
