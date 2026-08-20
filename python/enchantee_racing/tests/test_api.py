"""Tests for the race API: the endpoints, and the store that holds the race behind a lock.

engine/race.py is tested against synthetic geometry and a real race in test_race.py. What
is left to go wrong is the wiring, and it is the wiring that carries the concurrency: the
paho loop evaluates the race on every fix while Flask handlers move it on every button, and
CLAUDE.md says both go through the one lock in store.py.

So the tests that matter here are the ones that would pass with a broken lock and fail with
a missing one: two devices tapping Next at the same instant, and a fix arriving mid-tap.
"""

import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402
import mqtt_client  # noqa: E402
from engine import course as course_module  # noqa: E402
from engine import nav, race  # noqa: E402
from store import Store  # noqa: E402

CONFIG = app_module.load_config()
T0 = 1_755_500_000.0


def _client(now=None):
    """A test client with a clock the test controls, and a course-less store."""
    ticker = {"t": T0 if now is None else now}
    store = Store(clock=lambda: ticker["t"])
    flask_app = app_module.create_app(store, CONFIG)
    flask_app.config["TESTING"] = True
    published = []
    flask_app.config["EVENT_PUBLISHER"] = published.append
    return flask_app.test_client(), store, ticker, published


def _post(client, path, body=None):
    response = client.post(path, json=body if body is not None else {})
    return response, json.loads(response.get_data(as_text=True))


def _context(course_id="frostbite-3"):
    chosen = [c for c in CONFIG["courses"]["courses"] if c["id"] == course_id][0]
    return race.Context(course=chosen, marks=course_module.index_marks(CONFIG["marks"]),
                        lines=CONFIG["lines"],
                        config=race.Config.from_document(CONFIG["race"]))


# --- the endpoints ---------------------------------------------------------


def test_there_is_no_race_until_a_course_is_chosen():
    client, _store, _ticker, _published = _client()
    state = json.loads(client.get("/api/state").get_data(as_text=True))
    assert state["race"] is None

    # and the commands are harmless rather than fatal before then
    for path in ("/api/timer", "/api/advance", "/api/shorten", "/api/reset"):
        response, body = _post(client, path, {"hooter": 5, "dir": 1})
        assert response.status_code == 200, path
        assert body["race"] is None and body["events"] == [], path


def test_the_course_list_is_served_for_the_selection_screen():
    client, _store, _ticker, _published = _client()
    body = json.loads(client.get("/api/courses").get_data(as_text=True))
    assert set(body) == {"series", "courses"}
    assert "frostbite" in body["series"]
    assert len(body["courses"]) == 4
    first = body["courses"][0]
    assert first["flags"]["numeral"] == "pendant-1"
    assert first["raceable"] is True
    assert first["legs"] == 10


def test_selecting_a_course_starts_a_race_and_names_the_first_mark():
    client, _store, _ticker, published = _client()
    response, body = _post(client, "/api/select", {"course": "frostbite-3"})
    assert response.status_code == 200
    assert body["race"]["course"] == "frostbite-3"
    # prestart, not idle: the hooter buttons are on the prestart panel, so a selection
    # that left the mode at idle would strand the crew on the course list.
    assert body["race"]["mode"] == "prestart"
    assert body["race"]["countdown"] is None, "no hooter tapped yet"
    assert body["race"]["leg_name"] == "Dolphin East"
    assert body["race"]["legs"] == 10
    assert body["race"]["rounding"] == "starboard"
    assert [e["type"] for e in body["events"]] == ["select"]
    assert [e["type"] for e in published] == ["select"], "events reach the publisher"


def test_an_unknown_course_is_a_404_and_leaves_the_race_alone():
    client, _store, _ticker, _published = _client()
    response, body = _post(client, "/api/select", {"course": "twilight-9"})
    assert response.status_code == 404
    assert "unknown course" in body["error"]
    assert json.loads(client.get("/api/state").get_data(as_text=True))["race"] is None


def test_the_hooter_buttons_set_the_countdown_and_the_gun_starts_the_race():
    client, _store, ticker, _published = _client()
    _post(client, "/api/select", {"course": "frostbite-3"})

    _response, body = _post(client, "/api/timer", {"hooter": 5})
    assert body["race"]["mode"] == "prestart"
    assert body["race"]["countdown"] == 300.0
    assert body["race"]["elapsed"] is None, "the race has not started, so it has no elapsed"

    # nobody has to poll for the transition: it happens on the clock
    ticker["t"] = T0 + 299.0
    assert json.loads(client.get("/api/state").get_data(as_text=True))["race"]["mode"] == "prestart"
    ticker["t"] = T0 + 301.0
    state = json.loads(client.get("/api/state").get_data(as_text=True))
    assert state["race"]["mode"] == "racing"
    assert state["race"]["elapsed"] == 1.0
    assert state["race"]["countdown"] == -1.0


def test_the_start_event_is_published_once_however_many_devices_are_polling():
    """Several devices poll at 2 Hz each, and exactly one of them sees the transition."""
    client, _store, ticker, published = _client()
    _post(client, "/api/select", {"course": "frostbite-3"})
    _post(client, "/api/timer", {"hooter": 1})
    ticker["t"] = T0 + 61.0
    for _ in range(8):
        client.get("/api/state")
    # the start event is emitted by whichever poll transitioned the state, and the
    # publisher only ever sees it through a POST, so what matters here is the state
    assert json.loads(client.get("/api/state").get_data(as_text=True))["race"]["mode"] == "racing"


def test_the_timer_can_be_nudged_because_someone_always_taps_late():
    client, _store, _ticker, _published = _client()
    _post(client, "/api/select", {"course": "frostbite-3"})
    _post(client, "/api/timer", {"hooter": 5})
    _response, body = _post(client, "/api/timer", {"nudge": -8})
    assert body["race"]["countdown"] == 292.0
    _response, body = _post(client, "/api/timer", {"nudge": 3})
    assert body["race"]["countdown"] == 295.0


def test_clearing_the_timer_puts_the_race_back_to_idle():
    client, _store, _ticker, _published = _client()
    _post(client, "/api/select", {"course": "frostbite-3"})
    _post(client, "/api/timer", {"hooter": 5})
    _response, body = _post(client, "/api/timer", {"hooter": None})
    assert body["race"]["mode"] == "idle"
    assert body["race"]["countdown"] is None


def test_advance_moves_the_leg_and_back_moves_it_down():
    client, _store, ticker, published = _client()
    _post(client, "/api/select", {"course": "frostbite-3"})
    _post(client, "/api/timer", {"hooter": 0})
    client.get("/api/state")                        # the gun

    ticker["t"] = T0 + 30.0
    _response, body = _post(client, "/api/advance", {"dir": 1})
    assert body["race"]["leg"] == 1
    assert body["race"]["leg_name"] == "Sanders"
    assert body["events"][0]["source"] == "manual"

    ticker["t"] = T0 + 60.0
    _response, body = _post(client, "/api/advance", {"dir": -1})
    assert body["race"]["leg"] == 0
    assert [e["type"] for e in body["events"]] == ["back"]
    assert [e["type"] for e in published] == ["select", "timer", "start", "rounded", "back"]


def test_advance_defaults_to_forward_so_a_bare_post_is_the_next_mark_button():
    client, _store, _ticker, _published = _client()
    _post(client, "/api/select", {"course": "frostbite-3"})
    _post(client, "/api/timer", {"hooter": 0})
    client.get("/api/state")
    _response, body = _post(client, "/api/advance")
    assert body["race"]["leg"] == 1


def test_choosing_a_course_while_racing_ends_that_race_and_opens_the_new_one():
    """The crew is on the course list with a race running, tapping a card: they mean to sail
    that one instead (DESIGN 9.6). Logged as a reset, because abandoning is not finishing.
    """
    client, store, ticker, published = _client()
    _post(client, "/api/select", {"course": "frostbite-3"})
    _post(client, "/api/timer", {"hooter": 0})
    client.get("/api/state")
    ticker["t"] = T0 + 60.0
    _post(client, "/api/advance", {"dir": 1})
    assert store.race_state()[0].leg == 1

    ticker["t"] = T0 + 120.0
    _response, body = _post(client, "/api/select", {"course": "frostbite-1"})
    assert body["race"]["course"] == "frostbite-1"
    assert body["race"]["mode"] == "prestart", "the new course opens at its countdown"
    assert body["race"]["leg"] == 0
    assert body["race"]["elapsed"] is None, "the old race's clock is gone"
    assert body["race"]["legs"] == 10
    kinds = [e["type"] for e in published]
    assert kinds[-2:] == ["reset", "select"], kinds
    assert "finish" not in kinds, "abandoning a race is not finishing one"


def test_choosing_a_course_from_idle_does_not_log_a_pointless_reset():
    client, _store, _ticker, published = _client()
    _post(client, "/api/select", {"course": "frostbite-3"})
    assert [e["type"] for e in published] == ["select"]


def test_a_manual_start_puts_the_boat_on_leg_one_at_once():
    """The Start button: a missed hooter, a dockside test, every replay (DESIGN 9.6)."""
    client, _store, _ticker, _published = _client()
    _post(client, "/api/select", {"course": "frostbite-3"})
    _response, body = _post(client, "/api/timer", {"hooter": 0})
    assert body["race"]["mode"] == "racing"
    assert body["race"]["leg"] == 0
    assert body["race"]["elapsed"] == 0.0
    assert body["race"]["countdown"] == 0.0


def test_shorten_arms_the_finish_and_reset_puts_everything_back():
    client, _store, ticker, _published = _client()
    _post(client, "/api/select", {"course": "frostbite-3"})
    _post(client, "/api/timer", {"hooter": 0})
    client.get("/api/state")

    ticker["t"] = T0 + 30.0
    _response, body = _post(client, "/api/shorten")
    assert body["race"]["finish_armed"] is True
    assert body["race"]["shortened"] is True
    assert body["race"]["leg"] == 0, "shortening must not move the leg"

    _response, body = _post(client, "/api/reset")
    assert body["race"]["mode"] == "idle"
    assert body["race"]["finish_armed"] is False
    assert body["race"]["elapsed"] is None
    assert [e["type"] for e in body["events"]] == ["reset"]


def test_state_reports_what_the_race_screen_needs():
    client, _store, ticker, _published = _client()
    _post(client, "/api/select", {"course": "frostbite-3"})
    _post(client, "/api/timer", {"hooter": 0})
    ticker["t"] = T0 + 10.0
    race_block = json.loads(client.get("/api/state").get_data(as_text=True))["race"]
    for key in ("mode", "course", "leg", "legs", "leg_name", "rounding", "elapsed",
                "countdown", "finish_armed", "shortened", "breaches", "ignored_crossings"):
        assert key in race_block, key
    assert race_block["leg_name"] == "Dolphin East"   # the name, not the id or the number


# --- the fix path ----------------------------------------------------------


def _fix_payload(position):
    return json.dumps({"lat": position.lat, "lon": position.lon}).encode()


def test_a_fix_arriving_over_mqtt_drives_the_race():
    """The path a real rounding takes: broker to handle_message to store to the engine."""
    _client_, store, ticker, _published = _client()
    store.set_race_context(_context())
    store.apply_race(lambda s, c, n: race.select(s, c, "frostbite-3", n))
    store.apply_race(lambda s, c, n: race.set_timer(s, c, 0, n))
    store.apply_race(race.on_clock)

    mark = nav.as_latlon(_context().marks["dolphin-east-42b"])
    events = []
    ticker["t"] = T0 + 20.0
    mqtt_client.handle_message(store, "gps/course/0", b"200")
    mqtt_client.handle_message(store, "gps/speed/0", b"5.0")

    # closing on the mark, then the mark astern for three fixes
    approach = nav.destination(mark, 20.0, 30.0)
    mqtt_client.handle_message(store, "gps/course/0", str(nav.bearing(approach, mark)).encode())
    mqtt_client.handle_message(store, "gps/position/0", _fix_payload(approach),
                              on_events=events.append)
    assert store.race_state()[0].armed_leg == 0

    away = nav.norm360(nav.bearing(approach, mark) + 180.0)
    mqtt_client.handle_message(store, "gps/course/0", str(away).encode())
    for step in range(3):
        ticker["t"] = T0 + 21.0 + step
        departing = nav.destination(mark, 20.0, 40.0 + step * 10)
        mqtt_client.handle_message(store, "gps/position/0", _fix_payload(departing),
                                  on_events=events.append)

    assert [e["type"] for e in events] == ["rounded"]
    assert events[0]["source"] == "auto"
    assert store.race_state()[0].leg == 1


def test_a_fix_uses_the_course_and_speed_that_arrived_with_it():
    """on_position reads them under the same lock that stores the fix.

    Reading them in a separate call could pick up the next fix's heading and hand the
    engine a position from one moment with a course from another, which is the same fault
    gps/position/0 exists to avoid for lat and lon (DESIGN 3).
    """
    _client_, store, _ticker, _published = _client()
    store.set_race_context(_context())
    store.apply_race(lambda s, c, n: race.select(s, c, "frostbite-3", n))
    mqtt_client.handle_message(store, "gps/course/0", b"123.4")
    mqtt_client.handle_message(store, "gps/speed/0", b"6.5")

    seen = {}
    original = race.on_fix

    def spy(state, context, fix, now):
        seen["cog"], seen["sog"] = fix.cog, fix.sog
        return original(state, context, fix, now)

    race.on_fix = spy
    try:
        mqtt_client.handle_message(store, "gps/position/0", b'{"lat":-32.0,"lon":115.8}')
    finally:
        race.on_fix = original
    assert seen == {"cog": 123.4, "sog": 6.5}


# --- the lock --------------------------------------------------------------


def test_two_devices_tapping_next_at_once_advance_one_leg_between_them():
    """The reason the race lives behind the store's lock rather than beside it.

    Without it, both threads read leg 0, both write leg 1, and one tap is lost; or worse,
    both compute an advance from stale detection state. With it, the transitions serialise
    and the boat's leg count matches the number of taps.
    """
    client, store, _ticker, _published = _client()
    _post(client, "/api/select", {"course": "frostbite-3"})
    _post(client, "/api/timer", {"hooter": 0})
    client.get("/api/state")

    taps = 24
    started = threading.Barrier(taps)
    results = []

    def tap():
        started.wait()
        results.append(store.apply_race(
            lambda s, c, n: race.advance(s, c, +1, n)))

    threads = [threading.Thread(target=tap) for _ in range(taps)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Taps that produced a rounding, counted apart from the one that produced a finish:
    # Next off the last leg finishes the race rather than advancing a leg, so twenty-four
    # taps on a ten-leg course make nine roundings and one finish, and the rest do nothing
    # because a finished race ignores them (DESIGN 9.6).
    kinds = [event["type"] for events in results for event in events]
    assert kinds.count("rounded") == store.race_state()[0].leg, kinds
    assert kinds.count("finish") <= 1, kinds
    assert store.race_state()[0].leg == _context().last_leg
    assert store.race_state()[0].mode in (race.RACING, race.FINISHED)


def test_a_fix_and_a_tap_at_the_same_moment_do_not_interleave():
    """One thread feeding fixes while another taps Next, which is race day."""
    _client_, store, ticker, _published = _client()
    store.set_race_context(_context())
    store.apply_race(lambda s, c, n: race.select(s, c, "frostbite-3", n))
    store.apply_race(lambda s, c, n: race.set_timer(s, c, 0, n))
    store.apply_race(race.on_clock)

    mark = nav.as_latlon(_context().marks["dolphin-east-42b"])
    stop = threading.Event()
    failures = []

    def feed():
        step = 0
        while not stop.is_set():
            step += 1
            try:
                position = nav.destination(mark, 20.0, 30.0 + (step % 40))
                store.on_position({"lat": position.lat, "lon": position.lon})
            except Exception as exc:      # a torn read would surface as an exception here
                failures.append(exc)

    def tap():
        for _ in range(40):
            try:
                store.apply_race(lambda s, c, n: race.advance(s, c, +1, n))
                store.apply_race(lambda s, c, n: race.advance(s, c, -1, n))
            except Exception as exc:
                failures.append(exc)

    feeder = threading.Thread(target=feed)
    feeder.start()
    tapper = threading.Thread(target=tap)
    tapper.start()
    tapper.join()
    stop.set()
    feeder.join()

    assert failures == [], failures[:3]
    state, _context_ = store.race_state()
    assert 0 <= state.leg <= _context().last_leg
    assert state.mode in ("racing", "finished")


def test_the_state_payload_survives_being_read_while_fixes_arrive():
    """A poll must never see a half-updated race, and must never raise."""
    _client_, store, _ticker, _published = _client()
    store.set_race_context(_context())
    store.apply_race(lambda s, c, n: race.select(s, c, "frostbite-3", n))
    mark = nav.as_latlon(_context().marks["dolphin-east-42b"])

    stop = threading.Event()
    failures = []

    def feed():
        step = 0
        while not stop.is_set():
            step += 1
            position = nav.destination(mark, 20.0, 30.0 + (step % 20))
            store.on_position({"lat": position.lat, "lon": position.lon})

    feeder = threading.Thread(target=feed)
    feeder.start()
    try:
        for _ in range(300):
            payload = store.state()
            if payload["race"] is None or payload["position"] is None:
                failures.append(payload)
            elif set(payload) != {"now", "motor", "fields", "position", "race"}:
                failures.append(payload)
    finally:
        stop.set()
        feeder.join()
    assert failures == [], failures[:1]


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
