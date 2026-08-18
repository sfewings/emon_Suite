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


def test_position_is_not_subscribed_yet():
    """DESIGN build order step 5, and still the blocker for every race feature."""
    assert not [t for t in mqtt_client.TOPICS if "position" in t]


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
    mDNS, AP mode or a raw IP alike (CLAUDE.md). An absolute path breaks the prefix."""
    body = _client()[0].get("/hud").get_data(as_text=True)
    assert 'location.pathname.replace(/\\/+$/, "") + "/data"' in body
    assert '"/hud/data"' not in body
    assert "fetch(url" in body


def test_the_served_page_references_nothing_off_box():
    """The Pi has no internet: a page that fetches from a CDN hangs in the cockpit."""
    body = _client()[0].get("/hud").get_data(as_text=True)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)  # the ffmpeg note is a comment
    assert "http://" not in body and "https://" not in body
    assert "<link" not in body.lower()
    assert not re.search(r"""<script[^>]+src=""", body, re.I)
    assert not re.search(r"""\ssrc\s*=\s*["']//""", body)
    assert "url(" not in body  # no @font-face, no background image


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
