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
    # every series on a course sheet in the fixtures book, not just the first one built
    assert set(body["series"]) == {"frostbite", "friday", "sunday-div-ii", "sunday-div-iii",
                                   "sunday-div-iv", "twilight"}
    # the endpoint offers the whole file rather than a subset of it
    shipped = app_module.load_config()["courses"]["courses"]
    assert len(body["courses"]) == len(shipped) == 23
    assert {c["id"] for c in body["courses"]} == {c["id"] for c in shipped}

    first = body["courses"][0]
    assert first["flags"]["numeral"] == "pendant-1"
    assert first["raceable"] is True
    assert first["legs"] == 10

    # a card needs the numeral to show and a leg count to size the race, for every course
    for c in body["courses"]:
        assert c["flags"]["numeral"], c["id"]
        assert c["legs"] >= 5, c["id"]
        assert c["distance_nm"] > 0, c["id"]
        assert c["raceable"] is True, c["id"]


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


def test_each_event_is_logged_once_however_it_was_drained():
    """One line per transition, whichever thread got to the queue first.

    publish_event logs as it publishes, so logging in the drain as well printed every
    command twice, once as __main__ and once as mqtt_client, while a fix-driven event
    printed once because MqttClient drains and publishes without going through the drain
    at all. Seen in a replay: select, timer, start and both manual advances doubled while
    every automatic rounding did not.

    Worth pinning rather than shrugging at. The original EVENT_PUBLISHER bug was found by
    counting these lines and noticing which kinds appeared twice, so a second and opposite
    asymmetry would mislead the next person doing exactly that.
    """
    import logging

    records = []

    class Collect(logging.Handler):
        def emit(self, record):
            if "race event" in record.getMessage():
                records.append(record)

    handler = Collect()
    logging.getLogger().addHandler(handler)
    try:
        # with a publisher: the publisher is the one that speaks
        client, _store, _ticker, published = _client()
        _post(client, "/api/select", {"course": "frostbite-3"})
        assert len(published) == 1, published
        assert len(records) == 0, "the drain logged an event the publisher will log"

        # without one: the drain speaks, or nothing does
        records[:] = []
        store = Store()
        flask_app = app_module.create_app(store, CONFIG)
        flask_app.config["TESTING"] = True
        flask_app.config["EVENT_PUBLISHER"] = None
        bare = flask_app.test_client()
        _post(bare, "/api/select", {"course": "frostbite-3"})
        assert len(records) == 1, "a transition nobody publishes must still be logged"
    finally:
        logging.getLogger().removeHandler(handler)


def test_the_config_documents_the_map_needs_are_served():
    """The map draws from config/, and nothing served it: DESIGN 12.1, build step 1.

    Sent as files rather than re-serialised, so what the browser draws is byte for byte
    what is in git, and an edited course or mark is picked up without a restart.
    """
    client, _store, _ticker, _published = _client()
    for name in ("marks", "coast", "depth", "lines"):
        response = client.get("/api/config/" + name)
        assert response.status_code == 200, name
        assert response.mimetype == "application/json", (name, response.mimetype)
        body = json.loads(response.get_data(as_text=True))
        assert body, name
        # byte for byte what is on disk
        on_disk = (ROOT / "config" / (name + ".json")).read_bytes()
        assert response.get_data() == on_disk, "%s was re-serialised" % name


def test_the_config_route_is_an_allow_list_and_not_a_path():
    """An allow-list, so it cannot start serving something dropped into config/ later,
    and so the name never reaches a path join unless it matched.

    race.json is the interesting exclusion: it is engine tuning, an arming radius and a
    stale cutoff, and nothing in a browser draws it.
    """
    client, _store, _ticker, _published = _client()
    assert (ROOT / "config" / "race.json").exists(), "the exclusion is only meaningful if it is there"
    assert client.get("/api/config/race").status_code == 404

    for name in ("nonsense", "app", "secrets"):
        assert client.get("/api/config/" + name).status_code == 404, name

    # and nothing that looks like a way out of the directory
    for attempt in ("..%2f..%2fapp", "%2e%2e%2fapp", "marks.json", "marks%00"):
        response = client.get("/api/config/" + attempt)
        assert response.status_code == 404, (attempt, response.status_code)

    # The served set is exactly this, so adding one is a deliberate edit and not a
    # side effect. structures and navaids joined when the basemap grew (DESIGN 12).
    assert app_module.SERVABLE_CONFIG == ("marks", "courses", "lines", "coast", "depth",
                                          "structures", "navaids")


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


def _racing_store(ticker):
    """A store with frostbite-3 selected and the gun gone, ready for a rounding."""
    store = Store(clock=lambda: ticker["t"])
    store.set_race_context(_context())
    store.apply_race(lambda s, c, n: race.select(s, c, "frostbite-3", n))
    store.apply_race(lambda s, c, n: race.set_timer(s, c, 0, n))
    store.apply_race(race.on_clock)
    store.drain_events()          # discard select/timer/start, this is about the fix
    return store


def _round_dolphin_east(store, ticker, on_message):
    """Drive the boat through a real rounding, delivering each message via on_message."""
    mark = nav.as_latlon(_context().marks["dolphin-east-42b"])
    ticker["t"] = T0 + 20.0
    on_message("gps/course/0", b"200")
    on_message("gps/speed/0", b"5.0")

    approach = nav.destination(mark, 20.0, 30.0)
    on_message("gps/course/0", str(nav.bearing(approach, mark)).encode())
    on_message("gps/position/0", _fix_payload(approach))

    away = nav.norm360(nav.bearing(approach, mark) + 180.0)
    on_message("gps/course/0", str(away).encode())
    for step in range(3):
        ticker["t"] = T0 + 21.0 + step
        on_message("gps/position/0", _fix_payload(nav.destination(mark, 20.0, 40.0 + step * 10)))


class _StubPahoClient:
    """Stands in for paho, so MqttClient can be exercised without one installed.

    The Pi's system python has no paho and the whole suite runs there, which is why this
    is a stub rather than a real client pointed at a broker.
    """

    def __init__(self):
        self.published = []

    def publish(self, topic, payload=None):
        self.published.append((topic, payload))


def _mqtt_client_without_paho(store):
    """A MqttClient with its paho client stubbed, built without running __init__.

    __init__ imports paho, so it cannot run here. Everything the message path touches is
    set explicitly instead.
    """
    client = mqtt_client.MqttClient.__new__(mqtt_client.MqttClient)
    client.store = store
    client.client = _StubPahoClient()
    return client


def test_a_fix_event_is_published_exactly_once():
    """store.on_position both queues its events and returns them.

    So publishing the returned copy *and* letting app.py drain the queued one sends every
    rounding and finish to the broker twice. The queue is the single delivery path and
    whoever drains publishes; MqttClient drains after each message so a fix-driven event
    still goes out at once rather than waiting for a browser to poll (DESIGN 2).

    This is the test that would have caught the double publish, and it fails if anyone
    reinstates on_events= in MqttClient._on_message.
    """
    ticker = {"t": T0}
    store = _racing_store(ticker)
    client = _mqtt_client_without_paho(store)

    class _Message:
        def __init__(self, topic, payload):
            self.topic, self.payload = topic, payload

    _round_dolphin_east(store, ticker,
                        lambda topic, payload: client._on_message(
                            None, None, _Message(topic, payload)))

    # publish_event hands paho a json.dumps str, not bytes.
    rounded = [p for t, p in client.client.published
               if t == mqtt_client.RACE_EVENT_TOPIC and '"rounded"' in p]
    assert len(rounded) == 1, "one rounding, one message: %r" % client.client.published
    assert store.race_state()[0].leg == 1
    # Nothing left for app.py to publish a second time.
    assert store.drain_events() == []


def test_main_wires_the_event_publisher():
    """The bug this pins: create_app defaults EVENT_PUBLISHER to None and main never set it.

    Every transition that does not come from a fix was therefore logged and dropped:
    select, timer, start, manual advance, reset and shorten never reached race/event.
    The other tests in this file set EVENT_PUBLISHER by hand, which is exactly why none
    of them noticed, so this one goes through main() itself.
    """
    captured = {}
    real_create_app = app_module.create_app
    real_mqtt_client = app_module.MqttClient

    class _StubSource:
        started = False

        def start(self):
            _StubSource.started = True

        def stop(self):
            pass

        def publish_event(self, event):
            pass

    def fake_create_app(store, config=None):
        built = real_create_app(store, config)
        built.run = lambda *a, **k: None       # do not actually serve
        captured["app"] = built
        return built

    stub = _StubSource()
    app_module.create_app = fake_create_app
    app_module.MqttClient = lambda *a, **k: stub
    try:
        assert app_module.main(["--broker", "localhost"]) == 0
    finally:
        app_module.create_app = real_create_app
        app_module.MqttClient = real_mqtt_client

    assert _StubSource.started, "the source is started"
    assert captured["app"].config["EVENT_PUBLISHER"] == stub.publish_event, \
        "main must connect the publisher, or non-fix events go nowhere"


def test_demo_mode_leaves_the_event_publisher_unset():
    """getattr, not source.publish_event: DemoDriver has none and there is no broker.

    A demo run must not raise on startup, and None is the right publisher for it.
    """
    captured = {}
    real_create_app = app_module.create_app
    real_demo = app_module.DemoDriver

    class _StubDemo:
        def start(self):
            pass

        def stop(self):
            pass

    def fake_create_app(store, config=None):
        built = real_create_app(store, config)
        built.run = lambda *a, **k: None
        captured["app"] = built
        return built

    app_module.create_app = fake_create_app
    app_module.DemoDriver = lambda *a, **k: _StubDemo()
    try:
        assert app_module.main(["--demo"]) == 0
    finally:
        app_module.create_app = real_create_app
        app_module.DemoDriver = real_demo

    assert captured["app"].config["EVENT_PUBLISHER"] is None


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
            elif set(payload) != {"now", "motor", "fields", "position", "race",
                                  "theme"}:
                failures.append(payload)
    finally:
        stop.set()
        feeder.join()
    assert failures == [], failures[:1]


# --- the course detail endpoint (DESIGN 9.11) ------------------------------


def test_the_course_detail_endpoint_describes_a_whole_course():
    client, _store, _ticker, _published = _client()
    body = json.loads(client.get("/api/course/frostbite-3").get_data(as_text=True))

    assert body["id"] == "frostbite-3"
    assert body["series"] == "frostbite"
    assert body["series_name"] == "Frostbite Invitation Series"
    assert body["course_no"] == 3
    assert body["distance_nm"] == 6.93
    assert body["raceable"] is True
    assert body["flags"]["numeral"] == "pendant-3"

    legs = body["legs"]
    assert len(legs) == 10
    assert [leg["leg"] for leg in legs] == list(range(1, 11))
    assert legs[0]["name"] == "Dolphin East"
    assert legs[0]["number"] == "42B"
    assert legs[0]["rounding"] == "starboard"
    assert legs[-1]["finish"] is True

    # the running total ends at the summed distance the page shows beside the printed one
    assert abs(legs[-1]["cumulative_nm"] - body["summed_nm"]) < 1e-9
    for leg in legs:
        assert leg["distance_nm"] >= 0.0
        assert 0.0 <= leg["bearing"] < 360.0


def test_the_course_detail_endpoint_works_for_a_course_nobody_is_sailing():
    """The point of it: the crew reads courses before choosing one, and reading must not
    require selecting, because selecting while racing ends the race (DESIGN 9.11)."""
    client, store, _ticker, published = _client()
    assert store.race_payload() is None            # no course chosen at all
    response = client.get("/api/course/sunday-div-ii-1")
    assert response.status_code == 200
    assert json.loads(response.get_data(as_text=True))["course_no"] == 1
    # and reading changed nothing
    assert store.race_payload() is None
    assert published == []


def test_the_course_detail_endpoint_carries_the_shortened_figures():
    client, _store, _ticker, _published = _client()
    body = json.loads(client.get("/api/course/sunday-div-ii-1").get_data(as_text=True))
    assert body["shortened_distance_nm"] == 8.85
    assert body["shortened_at"] == 10                     # the eleventh leg, back at the line
    assert body["legs"][body["shortened_at"]]["mark"] == "club-32a"
    assert body["shortened_note"]

    # and says so plainly where the figure resolved to nothing
    unresolved = json.loads(
        client.get("/api/course/sunday-div-iv-1").get_data(as_text=True))
    assert unresolved["shortened_distance_nm"] == 8.96
    assert unresolved["shortened_at"] is None
    assert "not resolved" in unresolved["shortened_note"]


def test_the_course_detail_endpoint_reports_a_distance_that_does_not_reconcile():
    """So the page can say the printed total is in doubt rather than leaving the crew to
    notice two numbers that disagree (DESIGN 7)."""
    client, _store, _ticker, _published = _client()
    body = json.loads(client.get("/api/course/frostbite-1").get_data(as_text=True))
    assert body["notes"], "the known mismatch should be reported"
    assert any("per cent" in note for note in body["notes"])
    assert abs(body["summed_nm"] - body["distance_nm"]) > 0.1

    clean = json.loads(client.get("/api/course/frostbite-3").get_data(as_text=True))
    assert clean["notes"] == []


def test_the_course_detail_endpoint_names_the_leg_types_when_the_wind_is_known():
    client, store, _ticker, _published = _client()
    without = json.loads(client.get("/api/course/frostbite-3").get_data(as_text=True))
    assert without["twd"] is None
    assert all(leg["leg_type"] is None for leg in without["legs"])

    store.set("twd", 200.0)
    with_wind = json.loads(client.get("/api/course/frostbite-3").get_data(as_text=True))
    assert with_wind["twd"] == 200.0
    assert all(leg["leg_type"] in ("close hauled", "reach", "run")
               for leg in with_wind["legs"])


def test_the_course_detail_endpoint_404s_on_an_unknown_course():
    client, _store, _ticker, _published = _client()
    assert client.get("/api/course/nope").status_code == 404


def test_every_shipped_course_can_be_shown_in_detail():
    """Any card the crew taps has to open, including the ones whose distances are in doubt."""
    client, _store, _ticker, _published = _client()
    for c in CONFIG["courses"]["courses"]:
        response = client.get("/api/course/" + c["id"])
        assert response.status_code == 200, c["id"]
        body = json.loads(response.get_data(as_text=True))
        assert len(body["legs"]) == len(c["legs"]), c["id"]
        assert body["legs"][-1]["finish"] is True, c["id"]


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
