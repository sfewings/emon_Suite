"""Tests for the race screen: what the server serves it, and what the page must contain.

The display itself gets checked by eye on a phone, which is the only place its constraints
mean anything. What can be tested here is the half that is not visual: that the navigation
numbers the page renders are right and blank when they should, and that the page keeps the
handful of properties the deployment depends on and a careless edit would remove.
"""

import json
import re
import sys
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
FLAGS = ROOT / "static" / "flags"


def _context(course_id="frostbite-3"):
    chosen = [c for c in CONFIG["courses"]["courses"] if c["id"] == course_id][0]
    return race.Context(course=chosen, marks=course_module.index_marks(CONFIG["marks"]),
                        lines=CONFIG["lines"],
                        config=race.Config.from_document(CONFIG["race"]))


def _racing_store(now=T0):
    ticker = {"t": now}
    store = Store(clock=lambda: ticker["t"])
    store.set_race_context(_context())
    store.apply_race(lambda s, c, n: race.select(s, c, "frostbite-3", n))
    store.apply_race(lambda s, c, n: race.set_timer(s, c, 0, n))
    store.apply_race(race.on_clock)
    return store, ticker


def _page():
    store = Store()
    flask_app = app_module.create_app(store, CONFIG)
    flask_app.config["TESTING"] = True
    return flask_app.test_client().get("/").get_data(as_text=True)


# --- the navigation the page renders --------------------------------------


def test_navigation_gives_distance_and_bearing_to_the_current_mark():
    store, _ticker = _racing_store()
    mark = nav.as_latlon(_context().marks["dolphin-east-42b"])
    boat = nav.destination(mark, 250.0, 1200.0)      # 1200 m away, mark bearing 070
    mqtt_client.handle_message(store, "gps/course/0", b"70")
    store.on_position({"lat": boat.lat, "lon": boat.lon})

    block = store.state()["race"]
    assert abs(block["nav"]["distance_m"] - 1200.0) < 1.0
    assert abs(nav.norm180(block["nav"]["bearing"] - 70.0)) < 0.5
    assert abs(block["nav"]["relative"]) < 0.5      # sailing straight at it


def test_the_relative_bearing_is_signed_port_negative():
    store, _ticker = _racing_store()
    mark = nav.as_latlon(_context().marks["dolphin-east-42b"])
    boat = nav.destination(mark, 250.0, 800.0)
    bearing = nav.bearing(boat, mark)

    for offset, expected_sign in ((-30.0, +1), (+30.0, -1)):
        mqtt_client.handle_message(store, "gps/course/0",
                                   str(nav.norm360(bearing + offset)).encode())
        store.on_position({"lat": boat.lat, "lon": boat.lon})
        relative = store.state()["race"]["nav"]["relative"]
        assert abs(abs(relative) - 30.0) < 0.5, relative
        assert (1 if relative > 0 else -1) == expected_sign, (offset, relative)


def test_navigation_blanks_when_the_fix_goes_stale():
    """Blanked rather than dimmed, and the whole block goes rather than one number.

    A bearing computed from a 15 s old fix at 6 knots is 46 m out, and a dimmed number
    still reads as a number to someone glancing at it in spray (DESIGN 9.5).
    """
    store, ticker = _racing_store()
    mark = nav.as_latlon(_context().marks["dolphin-east-42b"])
    boat = nav.destination(mark, 250.0, 800.0)
    store.on_position({"lat": boat.lat, "lon": boat.lon})
    assert store.state()["race"]["nav"] is not None

    ticker["t"] = T0 + 6.0
    assert store.state()["race"]["nav"] is None
    assert store.state()["position"]["stale"] is True
    # and the clock is untouched by it, because it is not the GPS's business
    assert store.state()["race"]["elapsed"] == 6.0


def test_navigation_is_absent_before_any_fix_and_after_the_finish():
    store, _ticker = _racing_store()
    assert store.state()["race"]["nav"] is None

    mark = nav.as_latlon(_context().marks["dolphin-east-42b"])
    store.on_position({"lat": mark.lat, "lon": mark.lon})
    assert store.state()["race"]["nav"] is not None

    store.apply_race(lambda s, c, n: (s._replace(mode=race.FINISHED, finished_at=n), []))
    assert store.state()["race"]["nav"] is None


def test_the_leg_type_comes_free_from_the_wind_direction():
    """Under 40 degrees off the wind is a beat, over 140 a run, otherwise a reach.

    Useful before the rounding rather than after it: it is what says which sail to have
    ready (DESIGN 3).
    """
    store, _ticker = _racing_store()
    mark = nav.as_latlon(_context().marks["dolphin-east-42b"])
    boat = nav.destination(mark, 250.0, 900.0)
    bearing = nav.bearing(boat, mark)

    for offset, expected in ((5.0, "beat"), (90.0, "reach"), (175.0, "run")):
        mqtt_client.handle_message(store, "anemometer/windDirection/2",
                                   str(nav.norm360(bearing + offset)).encode())
        store.on_position({"lat": boat.lat, "lon": boat.lon})
        assert store.state()["race"]["nav"]["leg_type"] == expected, offset

    assert race.leg_type(None, 90.0) is None      # no wind reading, no answer


def test_the_leg_after_this_one_is_named_with_its_transit_angle_and_type():
    """The secondary row's job: what happens after the rounding (DESIGN 9.2).

    Course 3's first two legs are Dolphin East then Sanders, and the turn from one to the
    other is a real number the crew can check against the chart.
    """
    store, _ticker = _racing_store()
    marks = _context().marks
    mark = nav.as_latlon(marks["dolphin-east-42b"])
    beyond = nav.as_latlon(marks["sanders-99"])
    boat = nav.destination(mark, 250.0, 900.0)          # closing on bearing 070

    mqtt_client.handle_message(store, "gps/course/0", b"70")
    store.on_position({"lat": boat.lat, "lon": boat.lon})
    block = store.state()["race"]["nav"]

    assert block["next_name"] == "Sanders"
    assert abs(nav.norm180(block["next_bearing"] - nav.bearing(mark, beyond))) < 0.5
    # signed to port or starboard, from the direction the boat is closing on the mark
    expected = nav.norm180(nav.bearing(mark, beyond) - nav.bearing(boat, mark))
    assert abs(block["transit"] - expected) < 0.5
    assert -180.0 <= block["transit"] <= 180.0


def test_the_next_leg_type_is_the_leg_after_the_rounding_not_this_one():
    """The point of showing it is sail selection, so it has to be the leg being prepared
    for rather than the one being sailed (DESIGN 9.2)."""
    store, _ticker = _racing_store()
    marks = _context().marks
    mark = nav.as_latlon(marks["dolphin-east-42b"])
    beyond = nav.as_latlon(marks["sanders-99"])
    boat = nav.destination(mark, 250.0, 900.0)
    onward = nav.bearing(mark, beyond)

    # A wind dead against the leg after the rounding: that leg is a beat, and the leg being
    # sailed now is something else entirely.
    mqtt_client.handle_message(store, "anemometer/windDirection/2", str(onward).encode())
    store.on_position({"lat": boat.lat, "lon": boat.lon})
    block = store.state()["race"]["nav"]
    assert block["next_leg_type"] == "beat"
    assert block["leg_type"] != "beat", "the current leg is not the one being reported"


def test_the_last_leg_has_nothing_after_it():
    """On the finish leg there is no next mark, so the row says nothing rather than lying."""
    store, _ticker = _racing_store()
    context = _context()
    store.apply_race(lambda s, c, n: (s._replace(leg=context.last_leg), []))
    inner, outer = course_module.start_line(CONFIG["lines"])
    boat = nav.destination(nav.midpoint(inner, outer), 20.0, 400.0)
    store.on_position({"lat": boat.lat, "lon": boat.lon})

    block = store.state()["race"]["nav"]
    assert block["next_name"] is None
    assert block["transit"] is None
    assert block["next_leg_type"] is None


def test_time_to_line_is_distance_over_speed_made_good_towards_it():
    """The number that wins starts (DESIGN 10)."""
    store, ticker = _racing_store()
    store.apply_race(lambda s, c, n: race.set_timer(s, c, 5, n))

    inner, outer = course_module.start_line(CONFIG["lines"])
    middle = nav.midpoint(inner, outer)
    approach = nav.bearing(inner, outer) + 90.0
    boat = nav.destination(middle, approach, 200.0)

    mqtt_client.handle_message(store, "gps/course/0",
                               str(nav.bearing(boat, middle)).encode())
    mqtt_client.handle_message(store, "gps/speed/0", b"5.0")   # straight at it
    store.on_position({"lat": boat.lat, "lon": boat.lon})

    line = store.state()["race"]["line"]
    assert abs(line["distance_m"] - 200.0) < 2.0
    # 5 knots is 2.572 m/s, so 200 m takes about 78 s
    assert abs(line["seconds"] - 200.0 / (5.0 * 1852.0 / 3600.0)) < 2.0


def test_reaching_along_the_line_is_not_approaching_it():
    """Speed made good, not speed: a boat parallel to the line never reaches it."""
    store, _ticker = _racing_store()
    store.apply_race(lambda s, c, n: race.set_timer(s, c, 5, n))
    inner, outer = course_module.start_line(CONFIG["lines"])
    boat = nav.destination(nav.midpoint(inner, outer), nav.bearing(inner, outer) + 90.0, 150.0)

    mqtt_client.handle_message(store, "gps/course/0", str(nav.bearing(inner, outer)).encode())
    mqtt_client.handle_message(store, "gps/speed/0", b"6.0")
    store.on_position({"lat": boat.lat, "lon": boat.lon})
    assert store.state()["race"]["line"]["seconds"] is None


def test_the_line_reading_is_gone_once_racing_starts():
    """It is a pre-start number, and the screen it belongs to is not on show any more."""
    store, _ticker = _racing_store()
    inner, outer = course_module.start_line(CONFIG["lines"])
    boat = nav.destination(nav.midpoint(inner, outer), 20.0, 300.0)
    store.on_position({"lat": boat.lat, "lon": boat.lon})
    assert store.state()["race"]["mode"] == "racing"
    assert store.state()["race"]["line"] is None


# --- the page --------------------------------------------------------------


def test_the_page_has_all_four_panels_in_the_dom_at_once():
    """Pre-rendered and switched by a class, never rebuilt (DESIGN 9.6)."""
    page = _page()
    for panel in ("panel-idle", "panel-prestart", "panel-racing", "panel-finished"):
        assert 'id="%s"' % panel in page, panel
    assert "mode-racing" not in page, "the mode class is set by the script, not baked in"


def test_the_page_asks_for_its_data_relative_to_where_it_is_served():
    page = _page()
    assert 'href="static/app.css"' in page
    assert 'src="static/app.js"' in page
    assert 'src="static/wake.mp4"' in page
    for absolute in ('href="/static', 'src="/static', '"/api/'):
        assert absolute not in page, absolute


def test_the_script_builds_every_url_from_the_current_path():
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert 'location.pathname.replace(/\\/+$/, "")' in script
    # every fetch goes through `base`, so none of them may start with a slash
    for url in re.findall(r'fetch\((.*?)[,)]', script):
        assert url.startswith("base +"), url


def _panel_controls(page, panel):
    """The ids inside one panel, so a test can ask what is reachable in a given mode."""
    body = re.search(r'id="panel-%s"(.*?)</section>' % panel, page, re.S)
    assert body, panel
    return set(re.findall(r'id="([a-z0-9-]+)"', body.group(1)))


def test_every_mode_can_be_left_by_something_on_its_own_panel():
    """Reachability, which a screenful of passing tests did not catch.

    An early version stranded the crew: selecting a course left the mode at idle, and the
    hooter buttons that start a race are on the prestart panel, so the only route to the
    buttons that start a race was to have already started one. Every panel needs the
    controls that carry the race forward, and this is the test that says so. The navigation
    is checked separately, because it is outside the panels and serves all of them.
    """
    page = _page()
    exits = {
        "idle": {"cards"},                          # tapping a course card selects it
        "prestart": {"hooter-10", "hooter-5", "hooter-1", "cancel"},
        "racing": {"next", "back", "shorten"},
        "finished": {"reset"},
    }
    for panel, needed in exits.items():
        controls = _panel_controls(page, panel)
        assert needed <= controls, (panel, needed - controls)


def test_both_pages_carry_the_same_five_screen_navigation():
    """No screen is a dead end, which took two goes to get right: the HUD had no way back
    to anything, and the racing screen had no way to the HUD, which is the one a crew
    actually wants mid-race (DESIGN 9.6).
    """
    store = Store()
    flask_app = app_module.create_app(store, CONFIG)
    flask_app.config["TESTING"] = True
    client = flask_app.test_client()

    for path in ("/", "/hud"):
        page = client.get(path).get_data(as_text=True)
        nav = re.search(r"<nav[^>]*id=\"nav\"(.*?)</nav>", page, re.S)
        assert nav, path
        labels = [text.strip() for text in re.findall(r">([A-Za-z]+)<", nav.group(1))]
        assert labels == ["HUD", "Course", "Race", "Finish", "Map"], (path, labels)
        # Map is named so its absence is visible, and disabled so it cannot be tapped.
        assert 'class="off"' in nav.group(1), path

    # Every navigation target is relative, so the whole set works behind the /race/ prefix
    # and on the app's own port alike.
    hud_nav = re.search(r"<nav[^>]*id=\"nav\"(.*?)</nav>",
                        client.get("/hud").get_data(as_text=True), re.S).group(1)
    assert 'href="."' in hud_nav
    assert 'href="/' not in hud_nav
    race_nav = re.search(r"<nav[^>]*id=\"nav\"(.*?)</nav>",
                         client.get("/").get_data(as_text=True), re.S).group(1)
    assert 'href="hud"' in race_nav
    assert 'href="/' not in race_nav


def test_selecting_a_course_lands_on_the_panel_with_the_hooters():
    """The other half of the same bug: the mode after a selection has to be the mode whose
    panel carries the buttons that come next."""
    store = Store()
    flask_app = app_module.create_app(store, CONFIG)
    flask_app.config["TESTING"] = True
    client = flask_app.test_client()

    body = json.loads(
        client.post("/api/select", json={"course": "frostbite-3"}).get_data(as_text=True))
    landed = body["race"]["mode"]
    controls = _panel_controls(client.get("/").get_data(as_text=True), landed)
    assert {"hooter-10", "hooter-5", "hooter-1"} <= controls, (landed, controls)
    assert body["race"]["countdown"] is None, "the countdown reads dashes until a hooter"


def test_each_page_can_reach_the_other():
    """A phone that lands on one of the two screens must be able to get to the other.

    It could not, for a while: the race screen had a HUD button and the HUD had nothing,
    so anyone who opened /hud was stuck with no indication that a race screen existed at
    all. Both directions are pinned here because neither is discoverable from the code.
    """
    store = Store()
    flask_app = app_module.create_app(store, CONFIG)
    flask_app.config["TESTING"] = True
    client = flask_app.test_client()

    race_screen = client.get("/").get_data(as_text=True)
    assert 'href="hud"' in race_screen, "the race screen has no way to the HUD"

    hud = client.get("/hud").get_data(as_text=True)
    # href="." resolves to /race/ behind the prefix and to / on the app's own port. A
    # leading slash would work on the port and break behind nginx, which is the whole
    # reason every path in these pages is relative.
    assert 'href="."' in hud, "the HUD has no way back to the race screen"
    assert 'href="/"' not in hud


def test_the_page_references_nothing_off_box():
    """The Pi has no internet: a page that fetches from a CDN hangs in the cockpit."""
    page = re.sub(r"<!--.*?-->", "", _page(), flags=re.S)
    assert "http://" not in page and "https://" not in page
    assert not re.search(r"""\ssrc\s*=\s*["']//""", page)
    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
    assert "@import" not in css and "http" not in css
    assert "url(" not in css, "no font or image fetched from anywhere"


def test_the_page_keeps_the_cockpit_handling():
    page = _page()
    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
    for needed in ("apple-mobile-web-app-capable", "viewport-fit=cover"):
        assert needed in page, needed
    for needed in ("env(safe-area-inset-top)", "overscroll-behavior: none",
                   "touch-action: manipulation", "user-select: none"):
        assert needed in css, needed


def test_the_night_theme_only_changes_colours():
    """The layout has to be identical between themes so muscle memory survives (9.7)."""
    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
    night = re.search(r"body\.night\s*\{(.*?)\}", css, re.S)
    assert night, "no night theme"
    for declaration in night.group(1).split(";"):
        declaration = declaration.strip()
        if declaration:
            assert declaration.startswith("--"), declaration


def test_the_controls_are_big_enough_to_hit_on_a_moving_boat():
    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
    button = re.search(r"\nbutton\s*\{(.*?)\}", css, re.S)
    assert button, "no button rule"
    height = re.search(r"min-height:\s*([\d.]+)rem", button.group(1))
    assert height and float(height.group(1)) >= 3.0, button.group(1)


def test_every_flag_the_courses_name_exists_and_is_self_contained():
    """A card shows the flags so the crew matches what is flying (DESIGN 8)."""
    named = set()
    for c in CONFIG["courses"]["courses"]:
        for flag in c.get("flags", {}).values():
            if flag:
                named.add(flag)
    for start in CONFIG["courses"]["series"]["frostbite"]["starts"]:
        named.add(start["flag"])
    assert named, "no flags named in courses.json"

    for flag in sorted(named):
        path = FLAGS / ("%s.svg" % flag)
        assert path.exists(), flag
        svg = path.read_text(encoding="utf-8")
        assert "<svg" in svg and "</svg>" in svg
        # Two things look like fetches and are not: the xmlns, which is a namespace name
        # that is never resolved, and url(#id), which points inside the same document.
        # Both are stripped before looking for anything that would leave the box.
        body = svg.replace('xmlns="http://www.w3.org/2000/svg"', "")
        body = re.sub(r"url\(#[^)]*\)", "", body)
        for fetching in ("http", "url(", "<image", "<use", "xlink"):
            assert fetching not in body, (flag, fetching)
        assert "<title>" in svg, "each flag names itself, for the alt text and for editing"
        assert path.stat().st_size < 4096, (flag, path.stat().st_size)


def test_the_flags_are_provisional_and_say_so():
    """They are drawn from memory of the code flags, and the crew matches them against a
    real halyard. The README records that they need checking rather than leaving a future
    reader to assume they were verified."""
    readme = (FLAGS / "README.md").read_text(encoding="utf-8")
    assert "provisional" in readme.lower()
    assert "Fixtures & Courses" in readme


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
