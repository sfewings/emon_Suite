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
    """Under 40 degrees off the wind is close hauled, over 140 a run, otherwise a reach.

    Useful before the rounding rather than after it: it is what says which sail to have
    ready (DESIGN 3).
    """
    store, _ticker = _racing_store()
    mark = nav.as_latlon(_context().marks["dolphin-east-42b"])
    boat = nav.destination(mark, 250.0, 900.0)
    bearing = nav.bearing(boat, mark)

    for offset, expected in ((5.0, "close hauled"), (90.0, "reach"), (175.0, "run")):
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

    # A wind dead against the leg after the rounding: that leg is close hauled, and the one
    # being sailed now is something else entirely.
    mqtt_client.handle_message(store, "anemometer/windDirection/2", str(onward).encode())
    store.on_position({"lat": boat.lat, "lon": boat.lon})
    block = store.state()["race"]["nav"]
    assert block["next_leg_type"] == "close hauled"
    assert block["leg_type"] != "close hauled", "the current leg is not the one being reported"


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


def _rounding_icon(side):
    """The arc path of one rounding symbol, as its list of (x, y) points.

    The geometry lives in a <symbol> defined once, because it is used in three places now:
    the next mark while racing, the first mark before the start, and every leg of the
    course detail page. The arc is the first path in it; the second is the arrowhead.
    """
    page = _page()
    svg = re.search(r'<symbol id="rnd-%s-sym".*?</symbol>' % side, page, re.S)
    assert svg, side
    body = svg.group(0)
    arc = re.search(r'<path d="([^"]+)"', body)
    assert arc, side
    numbers = [float(n) for n in re.findall(r'-?\d+\.?\d*', arc.group(1))]
    assert len(numbers) % 2 == 0 and len(numbers) >= 8, numbers
    return body, list(zip(numbers[0::2], numbers[1::2]))


def test_the_rounding_geometry_is_defined_once_and_used():
    """One copy of the paths, or the sweep test only guards whichever copy it happens to
    find while another drifts (DESIGN 9.11)."""
    page = _page()
    # the arcs and arrowheads appear once each, inside the symbols
    for marker in ("M4.984 9.956", "M3.926 9.952"):
        assert page.count(marker) == 1, marker
    for side in ("port", "starboard"):
        assert page.count('<symbol id="rnd-%s-sym"' % side) == 1, side
        assert page.count('href="#rnd-%s-sym"' % side) >= 2, \
            "the %s symbol should be used in more than one place" % side
    # and the users carry no geometry of their own
    for use in re.findall(r'<svg class="rnd rnd-\w+"[^>]*>.*?</svg>', page, re.S):
        assert "<path" not in use, use
        assert "<circle" not in use, use
        assert "<use " in use, use


def _rounding_dot(side):
    """The buoy dot of one rounding icon, as (cx, cy, r)."""
    body, _ = _rounding_icon(side)
    dot = re.search(r'<circle cx="([\d.]+)" cy="([\d.]+)" r="([\d.]+)"', body)
    assert dot, "no buoy dot in the %s icon" % side
    return tuple(float(g) for g in dot.groups())


def _sweep(points):
    """Positive for a clockwise sweep on screen, since SVG y runs downwards."""
    return sum(points[i][0] * points[(i + 1) % len(points)][1]
               - points[(i + 1) % len(points)][0] * points[i][1]
               for i in range(len(points))) / 2.0


def test_the_rounding_arrow_turns_the_way_the_boat_turns():
    """Port anticlockwise, starboard clockwise, as on the club's chart (DESIGN 9.2).

    Leaving a mark to port means turning to port around it, so the arrow sweeps
    anticlockwise. This is the one thing about these icons that can be silently wrong:
    swap the two and the page still renders, still looks right, and sends the boat the
    wrong way round the mark. So it is asserted from the geometry rather than trusted.
    """
    _, port = _rounding_icon("port")
    _, starboard = _rounding_icon("starboard")
    assert _sweep(port) < 0, "port must sweep anticlockwise, got %.2f" % _sweep(port)
    assert _sweep(starboard) > 0, "starboard must sweep clockwise, got %.2f" % _sweep(starboard)
    # Mirror images of each other, as they are on the chart, so a hand-edit to one that
    # does not reach the other shows up here.
    assert abs(abs(_sweep(port)) - abs(_sweep(starboard))) < 0.01


def test_the_buoy_dot_sits_inside_the_turn_with_a_gap_around_it():
    """The mark goes in the arrow's concave side, the way the chart draws it (DESIGN 9.2).

    Put the dot on the convex side and the symbol says the boat passes the mark on the
    other hand, which is the opposite instruction. So the side is asserted, not eyeballed.
    """
    for side in ("port", "starboard"):
        _, arc = _rounding_icon(side)
        cx, cy, r = _rounding_dot(side)
        assert r > 0, side

        # The arrow bulges away from the mark it turns around: port sweeps up the mark's
        # right-hand side, starboard up its left.
        bulge = max(p[0] for p in arc) if side == "port" else min(p[0] for p in arc)
        if side == "port":
            assert bulge > cx, "port arrow must bulge right of the mark"
            assert cx < arc[0][0], "the mark sits left of where the port arrow starts"
        else:
            assert bulge < cx, "starboard arrow must bulge left of the mark"
            assert cx > arc[0][0], "the mark sits right of where the starboard arrow starts"

        # Nestled, not overlapping: the chart leaves clear white between dot and arc.
        nearest = min(((p[0] - cx) ** 2 + (p[1] - cy) ** 2) ** 0.5 for p in arc)
        assert nearest > r, "%s arc comes within the dot (%.2f vs r %.2f)" % (side, nearest, r)

        # Level with the turn rather than above or below it.
        assert min(p[1] for p in arc) < cy < max(p[1] for p in arc), side

    # Mirrored, as on the chart: same dot, same distance in from its own edge.
    px, _, pr = _rounding_dot("port")
    sx, _, sr = _rounding_dot("starboard")
    assert abs(pr - sr) < 0.001
    page = _page()
    widths = [float(re.search(r'viewBox="0 0 ([\d.]+)', m).group(1))
              for m in re.findall(r'<symbol id="rnd-\w+-sym"[^>]*>', page)]
    assert len(widths) == 2 and abs(widths[0] - widths[1]) < 0.01, widths
    assert abs(px - (widths[1] - sx)) < 0.01, "the dot is not mirrored between the two"


def test_the_rounding_arrow_sits_at_the_right_hand_edge():
    """Pushed to the edge so a long mark name cannot crowd it (DESIGN 9.2)."""
    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
    block = re.search(r'#mark-round \{(.*?)\}', css, re.S)
    assert block, "no #mark-round block"
    assert "margin-left: auto" in block.group(1)
    # and the name must be allowed to shrink, or the arrow gets pushed off the screen
    name = re.search(r'#mark-name \{(.*?)\}', css, re.S)
    assert name and "min-width: 0" in name.group(1)
    assert "text-overflow: ellipsis" in name.group(1)


def test_the_rounding_arrow_is_themeable_and_self_contained():
    """currentColor, or the night theme leaves a daylight-coloured arrow on the screen."""
    for side in ("port", "starboard"):
        body, _ = _rounding_icon(side)
        assert 'stroke="currentColor"' in body, side
        assert 'fill="currentColor"' in body, side
        assert not re.search(r'#[0-9a-fA-F]{3,6}', body), "hardcoded colour in %s" % side
        assert "url(" not in body and "http" not in body, side

    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8").replace("\n", " ")
    # Exactly one arrow shows, and hiding the container beats the display that reveals it.
    # The rules are on the .rounding class rather than the id, because the same symbol is
    # shown in three places now (DESIGN 9.11).
    assert ".rounding[hidden] { display: none; }" in css
    assert ".rounding .rnd { display: none;" in css
    for side in ("port", "starboard"):
        assert ".rounding.%s" % side in css, side

    # The JS may only ever set one of the two known sides as the class.
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert 'classList.remove("port", "starboard")' in script
    assert 'value === "port" || value === "starboard"' in script
    # The words are gone from the display but must stay available to a screen reader.
    assert 'aria-label", "round to "' in script


def test_the_course_detail_page_is_reachable_from_the_list_and_from_the_race():
    """Both entry points the crew asked for, and they are different needs.

    From the list, to read a course before choosing it, which selecting cannot offer
    because selecting while racing ends the race. From the race, to see what comes after
    the mark ahead (DESIGN 9.11).
    """
    page = _page()
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

    # from the racing panel
    assert "detail" in _panel_controls(page, "racing")
    assert 'if (latest.race && latest.race.course) openDetail(latest.race.course)' in script

    # from a course card, as a second target on the card rather than instead of selecting
    assert 'info.addEventListener("click", function () { openDetail(course.id); })' in script
    assert 'pick.addEventListener("click"' in script
    assert '"/api/select"' in script
    # the card is a container now, since a button cannot hold a button
    assert 'card = document.createElement("div")' in script
    assert 'pick = document.createElement("button")' in script


def test_the_course_detail_page_goes_back_where_it_came_from():
    """Its only navigation, and it cannot be a fixed destination.

    Opened from the course list during a race, Back has to return to the list, not to the
    racing panel; opened from the race, the other way about. So the page remembers
    (DESIGN 9.11).
    """
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "cameFrom = viewing" in script, "opening must record where it came from"
    assert "viewing = cameFrom" in script, "back must restore it"
    # and a mode change closes it, or Back could point at a panel the race has left
    set_mode = re.search(r'function setMode\(next\) \{(.*?)\n  \}', script, re.S)
    assert set_mode and "cameFrom = null" in set_mode.group(1)

    # nothing on that page may change the race: no posts from it
    detail = re.search(r'function drawDetail\(d\) \{(.*?)\n  \}\n', script, re.S)
    assert detail, "drawDetail not found"
    assert "post(" not in detail.group(1)
    assert 'on("detail-back", function () { closeDetail(); });' in script


def test_the_course_detail_page_shows_every_leg_and_scrolls():
    """Fifteen legs will not fit a phone at a readable size, so this one panel scrolls.

    A deliberate exception to the no-scrolling rule, which is about the racing display:
    this page is read at rest with two hands free (CLAUDE.md).
    """
    page = _page()
    assert 'id="panel-detail"' in page
    for ident in ("detail-flags", "detail-series", "detail-title", "detail-distance",
                  "detail-notes", "detail-legs", "detail-back"):
        assert 'id="%s"' % ident in page, ident

    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
    legs = re.search(r'#detail-legs \{(.*?)\}', css, re.S)
    assert legs and "overflow-y: auto" in legs.group(1)
    # and it is the only scrolling surface besides the course cards
    scrollers = re.findall(r'#([a-z-]+) \{[^}]*overflow-y: auto', css)
    assert set(scrollers) <= {"detail-legs", "cards"}, scrollers


def test_the_prestart_panel_shows_the_first_mark():
    """The engine steers at leg 1 from the moment a course is chosen, so the reading is
    already there before the gun, and it is what decides which end of the line to start
    at (DESIGN 9.2)."""
    page = _page()
    controls = _panel_controls(page, "prestart")
    for ident in ("pre-mark", "pre-round", "pre-distance", "pre-bearing"):
        assert ident in controls, ident

    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert 'el["pre-mark"].textContent = r.leg_name || BLANK' in script
    assert 'setRounding(el["pre-round"], r.rounding)' in script
    # blanked on a stale fix, like everywhere else (DESIGN 9.5)
    assert 'el["pre-distance"].textContent = BLANK' in script
    assert 'el["pre-bearing"].textContent = BLANK' in script


def test_the_first_mark_before_the_start_is_the_mark_the_race_will_steer_to():
    """Not a separate calculation: the same nav block the racing panel reads."""
    # a real pre-start: a course chosen and the T-5 hooter tapped, gun not yet gone
    ticker = {"t": T0}
    store = Store(clock=lambda: ticker["t"])
    store.set_race_context(_context())
    store.apply_race(lambda s, c, n: race.select(s, c, "frostbite-3", n))
    store.apply_race(lambda s, c, n: race.set_timer(s, c, 5, n))
    marks = _context().marks
    first = nav.as_latlon(marks["dolphin-east-42b"])
    boat = nav.destination(first, 250.0, 1500.0)
    store.on_position({"lat": boat.lat, "lon": boat.lon})

    block = store.state()["race"]
    assert block["mode"] == "prestart"
    assert block["leg_name"] == "Dolphin East", block["leg_name"]
    assert block["rounding"] == "starboard"
    assert abs(block["nav"]["distance_m"] - 1500.0) < 2.0


def test_only_one_panel_can_be_shown_at_a_time():
    """One mode class on the body, because two means two panels stacked on each other.

    This was a real bug, and an ugly one to look at in a cockpit: `showPanel` cleared the
    old class with a pattern that had been mangled into a literal control character, so it
    matched nothing. The old class stayed, the new one was added next to it, and tapping
    Back showed the course list and the race screen at once.

    The fix is structural rather than a corrected pattern: remove every known mode class,
    then add one. So this asserts the shape, not the behaviour of an expression.
    """
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert 'classList.remove("mode-" + name)' in script
    assert 'classList.add("mode-" + panel)' in script
    # Nothing may assemble the class attribute by hand: that is the family of bugs above,
    # and it is also how two writers of one string got there in the first place. Comments
    # go first, because the comment recording that history says the words too.
    code = re.sub(r'^\s*//.*$', '', script, flags=re.M)
    assert "body.className" not in code

    # Every mode the script can set must be in the list that gets cleared, or leaving that
    # mode leaves its class behind.
    listed = re.search(r'var PANELS = \[(.*?)\];', script)
    assert listed, "PANELS list not found"
    panels = set(re.findall(r'"([a-z]+)"', listed.group(1)))
    # "detail" is the course detail page: a panel, but not a mode and not a screen, so it
    # is reached and left by its own controls rather than by the race changing (DESIGN 9.11)
    assert panels == {"idle", "prestart", "racing", "finished", "detail"}, panels

    page = _page()
    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
    for panel in panels:
        assert "body.mode-%s" % panel in css.replace("\n", " "), panel
        assert 'id="panel-%s"' % panel in page, panel


def test_no_source_file_carries_a_stray_control_character():
    """An escape written as the character it stands for is invisible and silently wrong.

    `\\b` in a JS regex became a backspace byte in app.js during editing. It reads
    correctly in every viewer, matches nothing at all, and cost a bug hunt. Cheap to check
    for, so it is checked for across the project rather than in the one file it bit.
    """
    suffixes = {".py", ".js", ".css", ".html", ".json", ".md", ".yml", ".conf", ".svg"}
    offenders = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        if any(part in (".git", "venv", "__pycache__") for part in path.parts):
            continue
        text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
        for number, line in enumerate(text.split("\n"), 1):
            stray = [c for c in line if ord(c) < 32 and c != "\t"]
            if stray:
                offenders.append("%s:%d %s" % (path.relative_to(ROOT), number,
                                               [hex(ord(c)) for c in stray]))
    assert not offenders, offenders


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
        "detail": {"detail-back"},                  # its only way out, by design (9.11)
    }
    for panel, needed in exits.items():
        controls = _panel_controls(page, panel)
        assert needed <= controls, (panel, needed - controls)


def _page_hud():
    store = Store()
    flask_app = app_module.create_app(store, CONFIG)
    flask_app.config["TESTING"] = True
    return flask_app.test_client().get("/hud").get_data(as_text=True)


NAV_H = "2.6rem"
"""The height the navigation takes, and the room each page has to leave for it. One number
in two files, which is why the test below checks they still agree."""


def _nav_rules(css, selector):
    block = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert block, selector
    return " ".join(block.group(1).split())


def test_the_navigation_cannot_be_pushed_off_the_bottom_of_either_page():
    """It was, on the race page, and only there.

    Left as the last item in a fixed-height flex column, the navigation is whatever room
    is left over, and a panel's .controls will not give any up: its buttons carry a minimum
    height so they stay hittable on a moving boat (CLAUDE.md). The pre-start panel, two
    rows of controls and then a row of readings, ran out first and pushed the navigation
    half off the screen. The HUD never showed it because its navigation has always been
    out of flow.

    So both pages now fix it to the bottom and reserve the height above it, and this
    checks the reserved height still matches what the navigation actually takes. Nothing
    here can be seen without a phone, which is exactly why it is asserted.
    """
    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
    hud = _page_hud()

    # out of flow on both, anchored to the bottom edge inside the safe area
    for source, name in ((css, "app.css"), (hud, "hud.html")):
        rules = _nav_rules(source, "#nav")
        assert "position: fixed" in rules, name
        assert "bottom: env(safe-area-inset-bottom)" in rules, name
        # it sits over the panel now, so it needs its own background
        assert "background:" in rules, name
        assert "flex: 0 0 auto" not in rules, "%s still treats the nav as a column item" % name

    # and each page leaves exactly that much room, so the nav never covers a control
    reserved = "padding-bottom: calc(env(safe-area-inset-bottom) + %s)" % NAV_H
    assert reserved in " ".join(css.split()), "app.css reserves no room for the nav"
    assert reserved in " ".join(hud.split()), "hud.html reserves no room for the nav"

    # the reserved height has to be the height the nav takes, or it overlaps or floats
    for source, name in ((css, "app.css"), (hud, "hud.html")):
        entry = _nav_rules(source, "#nav a, #nav button") if name == "app.css" \
            else _nav_rules(source, "#nav a")
        assert "min-height: %s" % NAV_H in entry, (name, entry)


def test_both_pages_carry_the_same_three_screen_navigation():
    """No screen is a dead end, which took two goes to get right: the HUD had no way back
    to anything, and the racing screen had no way to the HUD, which is the one a crew
    actually wants mid-race (DESIGN 9.6).

    Three names, not five. Course and Finish are things that happen to a race rather than
    places to browse to, so they are reached by the controls that mean something and have no
    navigation entry of their own.
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
        assert labels == ["HUD", "Race", "Map"], (path, labels)
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


def test_the_flags_record_what_was_checked_and_what_was_not():
    """They were drawn from memory and five of the eight were wrong, which is what the
    crew found when they looked at the screen beside a halyard.

    They are now checked against the plate on page 27 of the fixtures PDF. The README
    records which page, how to render it, and which parts are still only eyeballed, so a
    later reader neither assumes they were verified nor re-checks what already was.
    """
    readme = (FLAGS / "README.md").read_text(encoding="utf-8")
    assert "page 27" in readme, "the README must name the authority"
    assert "Fixtures & Courses" in readme
    assert "still not verified" in readme.lower(), "the remaining doubt has to stay recorded"


# What the plate on page 27 of the fixtures PDF shows. Pinned so that an edit which
# changes an arrangement fails here rather than quietly shipping a flag the crew cannot
# match against a halyard (DESIGN 8).
FLAG_DESIGNS = {
    # three horizontal bands, top to bottom
    "naval-1": ["#c8102e", "#ffd200", "#c8102e"],
    "naval-2": ["#ffd200", "#c8102e", "#ffd200"],
    "naval-3": ["#14509b", "#c8102e", "#14509b"],
    # three vertical bands, hoist to fly
    "pendant-3": ["#c8102e", "#ffffff", "#14509b"],
}


def _bands(name, axis):
    """The fill colours of a flag's bands, in order along the given axis."""
    body = (FLAGS / (name + ".svg")).read_text(encoding="utf-8")
    found = []
    for rect in re.findall(r'<rect[^>]*>', body):
        fill = re.search(r'fill="(#[0-9a-f]{6})"', rect)
        at = re.search(r'\b%s="([\d.]+)"' % axis, rect)
        if not fill or at is None:
            continue          # the outline rect carries fill="none"
        found.append((float(at.group(1)), fill.group(1)))
    return [colour for _, colour in sorted(found)]


def test_every_flag_is_drawn_the_way_the_plate_shows_it():
    for name, expected in FLAG_DESIGNS.items():
        axis = "x" if name.startswith("pendant") else "y"
        assert _bands(name, axis) == expected, (name, _bands(name, axis))

    # naval 4 is a saltire, not bands: two crossing lines on a red field
    naval4 = (FLAGS / "naval-4.svg").read_text(encoding="utf-8")
    assert naval4.count("<line") == 2, "a saltire is two lines"
    assert 'stroke="#ffffff"' in naval4 and 'fill="#c8102e"' in naval4
    corners = set()
    for line in re.findall(r'<line[^>]*>', naval4):
        pts = dict(re.findall(r'(x1|y1|x2|y2)="([\d.]+)"', line))
        corners.add((pts["x1"], pts["y1"]))
        corners.add((pts["x2"], pts["y2"]))
    assert corners == {("0", "0"), ("90", "60"), ("90", "0"), ("0", "60")}, corners

    # and the two that carry a disc still carry one
    for name, fill in (("pendant-1", "#c8102e"), ("pendant-2", "#ffffff")):
        body = (FLAGS / (name + ".svg")).read_text(encoding="utf-8")
        assert re.search(r'<circle[^>]*fill="%s"' % fill, body), name


def test_the_pendants_all_taper_and_the_naval_flags_do_not():
    """The shape is half of what the eye matches, and it is the same clip in all four
    pendants: pendant-3 was rewritten and must keep the mechanism the others use."""
    for name in ("pendant-1", "pendant-2", "pendant-3", "pendant-4"):
        body = (FLAGS / (name + ".svg")).read_text(encoding="utf-8")
        assert 'viewBox="0 0 120 60"' in body, name
        assert body.count('points="0,0 120,18 120,42 0,60"') == 2, \
            "%s needs the taper as both a clip and an outline" % name
        assert 'clip-path="url(#p)"' in body, name
    for name in ("naval-1", "naval-2", "naval-3", "naval-4"):
        body = (FLAGS / (name + ".svg")).read_text(encoding="utf-8")
        assert 'viewBox="0 0 90 60"' in body, name
        assert "polygon" not in body, "%s is rectangular" % name


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
