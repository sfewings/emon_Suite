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

    # A wind dead against the leg after the rounding: that leg is a beat, and the one
    # being sailed now is something else entirely.
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


def _page_map():
    store = Store()
    flask_app = app_module.create_app(store, CONFIG)
    flask_app.config["TESTING"] = True
    return flask_app.test_client().get("/map").get_data(as_text=True)


NAV_H = "2.6rem"
"""The height the navigation takes, and the room each page has to leave for it. One number
in two files, which is why the test below checks they still agree."""


def _bare(path):
    """A stylesheet with its comments taken out.

    The rule bodies here are read whole, and this stylesheet explains itself at length
    inside them, so an unstripped comment reads as declarations that are not there.
    """
    return re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)


def _bare_text(text):
    """The same as _bare, for a page that has already been rendered."""
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _nav_rules(css, selector):
    block = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert block, selector
    return " ".join(block.group(1).split())


def _panel_children(page):
    """The direct children of each panel, as the selector that would match them."""
    page = re.sub(r"<!--.*?-->", "", page, flags=re.S)
    out = {}
    for block in re.finditer(r'<section class="panel" id="panel-(\w+)">(.*?)</section>',
                             page, re.S):
        name, body, kids, depth = block.group(1), block.group(2), [], 0
        for tag in re.finditer(r'<(/?)(div|span)\b([^>]*)>', body):
            closing, attrs = tag.group(1), tag.group(3)
            if closing:
                depth -= 1
                continue
            if depth == 0:
                ident = re.search(r'id="([\w-]+)"', attrs)
                cls = re.search(r'class="([^"]+)"', attrs)
                kids.append("#" + ident.group(1) if ident else
                            "." + cls.group(1) if cls else "?")
            depth += 1
        out[name] = kids
    return out


# A panel's children are either the readings, which give way when the screen runs short,
# or the things a hand reaches for, which never do. Every child must be one or the other:
# a child that is neither shrinks by the default flex rules, which shrink everything a
# little and overflow anyway, and then the bottom of the column is lost behind the nav.
GIVES_WAY = {".grow", "#cards", "#detail-legs", ".row"}
NEVER_SHRINKS = {".controls", "#series", "#secondary", "#final-secondary",
                 "#detail-head", "#detail-notes"}


def test_every_panel_child_either_gives_way_or_is_pinned():
    """The rule that keeps the controls and the navigation on the screen.

    This is the check that would have caught it: a row of readings was added to the
    pre-start panel, which already had two rows of controls, and the column ran out of
    room. Buttons carry a minimum height so they stay hittable on a moving boat
    (CLAUDE.md), so when something has to give it must be a reading, and the panel has to
    say which. Add a child that is in neither set and this fails.
    """
    for panel, kids in _panel_children(_page()).items():
        for kid in kids:
            assert kid in GIVES_WAY or kid in NEVER_SHRINKS, (panel, kid)
        # and every panel keeps its controls, or there is no way off it
        assert ".controls" in kids, panel

    css = " ".join((ROOT / "static" / "app.css").read_text(encoding="utf-8").split())
    # the pinned set is declared as one rule, so the intent is in one place
    pinned = re.search(r'([^{}]*\.panel > \.controls[^{]*)\{([^}]*)\}', css)
    assert pinned, "no rule pins the controls"
    assert "flex: 0 0 auto" in pinned.group(2)
    for name in NEVER_SHRINKS - {".controls"}:
        assert name in pinned.group(1), "%s is not pinned with the rest" % name

    # the readings give way, and are clipped inside their own panel when they do
    panel_rule = _nav_rules(css, ".panel")
    assert "overflow: hidden" in panel_rule
    assert "min-height: 0" in panel_rule
    assert "flex: 0 1 auto" in _nav_rules(css, ".panel > .row")


def test_nothing_above_the_app_takes_up_any_room():
    """#app is 100dvh, so anything in the flow above it pushes its bottom off the screen.

    This is what actually sent the navigation half off the bottom of the race page, twice,
    and it was nineteen pixels of nothing: the <svg> holding the rounding symbols is an
    inline element, so at zero width and height it still sat on a line box of its own. The
    symbols are never drawn, only referenced, and the element had no CSS at all while every
    other thing in that part of the page was positioned out of the flow.

    The HUD never showed it because the HUD has no symbols. Half a navigation bar is the
    only symptom, and it needs a phone to see, so the rule is asserted here instead.
    """
    page = _page()
    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")

    before = page[:page.index('<div id="app">')]
    before = re.sub(r"<!--.*?-->", "", before, flags=re.S)

    # Only the top-level elements: the <symbol>s nested inside the defs svg are not in the
    # flow of the page at all, and it is the box around them that had to be taken out of it.
    ids, depth = [], 0
    for tag in re.finditer(r'<(/?)(\w+)([^>]*?)(/?)>', before):
        closing, element, attrs, selfclose = tag.groups()
        # Elements that generate no box, so they cannot make the page taller: the void
        # ones, and <script>, which the UA stylesheet gives display: none. Skipped on
        # both the open and the close tag, so the depth stays balanced.
        if element in ("meta", "title", "link", "br", "script"):
            continue
        if closing:
            depth -= 1
            continue
        if depth == 0:
            ident = re.search(r'\bid="([\w-]+)"', attrs)
            assert ident, "an element above #app with no id: %s" % element
            ids.append(ident.group(1))
        if not selfclose and element not in ("img", "input"):
            depth += 1
    assert ids, "expected some elements before #app"

    # Comments stripped first, then every rule read as selector-list plus body, because
    # the selector may be grouped: #wake and #quiet share one rule, being out of the flow
    # for the same reason and in the same way.
    bare = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rules = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", bare):
        selectors = [part.strip() for part in match.group(1).split(",")]
        rules.append((selectors, match.group(2)))

    for ident in ids:
        bodies = [body for selectors, body in rules if ("#" + ident) in selectors]
        assert bodies, "#%s is in the flow above #app with no CSS to take it out" % ident
        assert any(re.search(r'position:\s*(fixed|absolute)', body) for body in bodies), \
            "#%s must be out of the flow, or it makes the page taller than the screen" \
            % ident

    # and the page must not have grown something new up there unnoticed
    assert set(ids) == {"wake", "quiet", "pip", "notice", "rnd-defs"}, ids


def test_the_manifest_scopes_both_screens_into_one_web_app():
    """Modern iOS decides standalone-versus-browser by the manifest's scope.

    With no manifest it infers one from the single URL saved to the Home Screen, so
    whichever page was saved stayed full screen and the other always opened in an overlay
    browser with a Done button, with the saved one going full screen again on the way
    back. That was reported from the phone. The iPad, on iOS 12, predates scope
    enforcement and behaved correctly throughout, which is why the two disagreed and why
    navigating by script was not enough on its own.

    Everything here has to be relative, and it has to be served from the app root. scope
    and start_url resolve against the manifest's own URL, so from /race/manifest.webmanifest
    the scope is /race/, which covers /race/ and /race/hud; from static/ it would have been
    /race/static/ and covered neither.
    """
    import json as _json

    doc = _json.loads((ROOT / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert doc["display"] == "standalone", "iOS has no fullscreen display mode"
    for field in ("scope", "start_url"):
        value = doc[field]
        assert not value.startswith("/"), \
            "%s is root-relative and would break behind the /race/ prefix" % field
        assert "://" not in value, "%s must not name a host (CLAUDE.md)" % field
        assert value == "./", \
            "%s must resolve to the app root to cover both screens, got %r" % (field, value)

    # Served from the app root, not from static/, or the relative scope resolves wrong.
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert '@app.get("/manifest.webmanifest")' in source, \
        "the manifest must be served from the app root for its relative scope to work"

    # Every page links it, relatively, and keeps the meta that iOS 12 reads instead.
    for what, page in (("index.html", _page()), ("hud.html", _page_hud()),
                       ("map.html", _page_map())):
        link = re.search(r'<link[^>]*rel="manifest"[^>]*>', page)
        assert link, "%s does not link the manifest" % what
        href = re.search(r'href="([^"]+)"', link.group(0))
        assert href and href.group(1) == "manifest.webmanifest", \
            "%s must link the manifest relatively, got %r" % (what, link.group(0))
        assert 'name="apple-mobile-web-app-capable" content="yes"' in page, \
            "%s dropped the meta iOS 12 uses, which ignores the manifest" % what

    # It has to reach the image too, and that COPY list is an allow-list.
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "manifest.webmanifest" in dockerfile, \
        "the manifest is not copied into the image, so only the bind mount would have it"

    # Icons: declared relatively, present on disk, and real PNGs of the size claimed.
    # iOS reads apple-touch-icon rather than the manifest for the Home Screen, so both
    # pages carry that too, and it cannot be the SVG because iOS will not take one.
    assert doc["icons"], "no icons declared"
    for icon in doc["icons"]:
        src = icon["src"]
        assert not src.startswith("/") and "://" not in src, \
            "icon src %r must be relative to the manifest" % src
        path = ROOT / src
        assert path.exists(), "%s is declared but missing" % src
        header = path.read_bytes()[:24]
        assert header.startswith(b"\x89PNG\r\n\x1a\n"), "%s is not a PNG" % src
        width = int.from_bytes(header[16:20], "big")
        height = int.from_bytes(header[20:24], "big")
        assert "%dx%d" % (width, height) == icon["sizes"], \
            "%s is %dx%d but declares %s" % (src, width, height, icon["sizes"])

    for what, page in (("index.html", _page()), ("hud.html", _page_hud()),
                       ("map.html", _page_map())):
        touch = re.search(r'<link[^>]*rel="apple-touch-icon"[^>]*>', page)
        assert touch, "%s has no apple-touch-icon, so iOS uses a screenshot" % what
        href = re.search(r'href="([^"]+)"', touch.group(0)).group(1)
        assert href.endswith(".png"), "iOS will not take %r as a touch icon" % href
        assert not href.startswith("/"), \
            "%s icon href is root-relative and breaks behind /race/" % what
        assert (ROOT / href).exists(), "%s points at a missing icon: %s" % (what, href)


def test_both_pages_navigate_by_script_so_ios_keeps_them_in_the_web_app():
    """Added to the Home Screen, a plain anchor to the other page leaves the web app.

    The pages ask for iOS's standalone context with apple-mobile-web-app-capable, which
    is what gets the crew a display with no browser chrome. From there, following a real
    anchor to a different document is treated as navigating away: iOS reopens it in an
    in-app browser with a Done button and a toolbar top and bottom. Assigning location
    from script stays inside the standalone context.

    Both pages have to do it. Fixing one direction and not the other is worse than
    fixing neither, because the crew is thrown out of the app going one way only, which
    reads as an intermittent fault rather than a missing feature. Hence one test over
    both files.

    The href is deliberately left on the anchor and only its default action cancelled,
    so the target still resolves relatively against the document. That is what keeps the
    link correct behind the /race/ prefix and on the app's own port alike (CLAUDE.md),
    and it is why this asserts preventDefault rather than an href that was replaced by a
    click handler.
    """
    race_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    hud = _page_hud()
    map_js = (ROOT / "static" / "map.js").read_text(encoding="utf-8")

    for what, source in (("static/app.js", race_js), ("templates/hud.html", hud),
                         ("static/map.js", map_js)):
        code = re.sub(r"^\s*//.*$", "", source, flags=re.M)
        assert "location.assign(" in code, "%s does not navigate by script" % what
        assert "preventDefault()" in code, "%s does not cancel the anchor" % what

    # Every cross-page nav link is a real anchor carrying a real href, on every page, so
    # the handler has something to intercept and the link degrades to a plain one.
    for what, page in (("index.html", _page()), ("hud.html", hud),
                       ("map.html", _page_map())):
        nav = re.search(r'<nav id="nav">(.*?)</nav>', page, re.S)
        assert nav, "%s has no nav" % what
        hrefs = re.findall(r'<a[^>]*\bhref="([^"]+)"', nav.group(1))
        assert hrefs, "%s nav has no links to intercept" % what
        for href in hrefs:
            assert not href.startswith("/"), \
                "%s nav link %r is root-relative and breaks behind /race/" % (what, href)
            assert "://" not in href, \
                "%s nav link %r is absolute and would leave the app" % (what, href)


def test_the_navigation_is_never_pushed_off_or_covered():
    """Two pages, two mechanisms, and the reason they differ.

    The race page keeps the nav in the flow as the last item, so the browser reserves
    exactly the height it takes. Reserving that height by hand instead was tried and it
    covered the controls: a hand-written height either overlaps what is above it or floats
    above the bottom, and nothing in the code can tell which.

    The HUD does reserve it by hand, because its nav has been out of flow since the port
    and its fit() sizes digits against the row heights of that column. Putting the nav
    into it would resize every reading on the page. So there the height is duplicated, and
    the two copies are checked against each other.
    """
    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
    hud = _page_hud()
    page = _page()

    # --- the race page: in the flow, last, and nothing above it can overflow ---
    nav = _nav_rules(css, "#nav")
    assert "flex: 0 0 auto" in nav
    assert "position: fixed" not in nav, "in the flow, so no height has to be guessed"
    assert "padding-bottom" not in _nav_rules(css, "#app"), \
        "an in-flow nav needs no reserved height, and a stale one would cover the controls"
    # last in the column, so the flow puts it at the bottom
    assert page.rindex('id="nav"') > page.rindex('id="panel-')

    # --- the HUD: out of flow, and the reserved height must match the real one ---
    hud_nav = _nav_rules(hud, "#nav")
    assert "position: fixed" in hud_nav
    # Hard against the bottom of the glass. Where the home indicator's height is taken
    # instead is the subject of its own test below.
    assert "bottom: 0" in hud_nav
    assert "background:" in hud_nav, "it sits over the panels, so it needs one"
    # The two copies of the row's height, checked against each other. What is below the
    # label as well as the label itself, since the reserve has to be the whole row: the
    # clearance is the subject of its own test.
    reserved = "padding-bottom: calc(%s + var(--nav-pad))" % NAV_H
    assert reserved in " ".join(hud.split()), "hud.html reserves no room for its nav"
    assert "min-height: calc(%s + var(--nav-pad))" % NAV_H in \
        _nav_rules(hud, "#nav a, #nav button"), \
        "the reserved height no longer matches what the HUD nav takes"


# The three screens, and the path each is served at. DESIGN 9.6: no screen is a dead end,
# so every one of them carries the same navigation and can reach the other two.
SCREENS = {"/": "Race", "/hud": "HUD", "/map": "Map"}


def _navs():
    """The nav block of each of the three pages, keyed by path."""
    store = Store()
    flask_app = app_module.create_app(store, CONFIG)
    flask_app.config["TESTING"] = True
    client = flask_app.test_client()
    out = {}
    for path in SCREENS:
        page = client.get(path).get_data(as_text=True)
        nav = re.search(r"<nav[^>]*id=\"nav\"(.*?)</nav>", page, re.S)
        assert nav, path
        out[path] = nav.group(1)
    return out


def test_every_page_carries_the_same_three_screen_navigation():
    """No screen is a dead end, which took two goes to get right: the HUD had no way back
    to anything, and the racing screen had no way to the HUD, which is the one a crew
    actually wants mid-race (DESIGN 9.6).

    Three names, not five. Course and Finish are things that happen to a race rather than
    places to browse to, so they are reached by the controls that mean something and have no
    navigation entry of their own.

    Three pages now rather than two, which is the cost DESIGN 12.1 accepted when the map
    became its own page instead of a fourth panel.
    """
    for path, nav in _navs().items():
        labels = [text.strip() for text in re.findall(r">([A-Za-z]+)<", nav)]
        assert labels == ["HUD", "Race", "Map"], (path, labels)
        # Nothing is disabled any more: Map used to carry class="off" because there was no
        # map, and DESIGN 9.6 said to show it disabled until there was.
        assert 'class="off"' not in nav, "%s still disables an entry" % path
        # Exactly one entry is marked as where you already are, and it is this page.
        here = re.findall(r'class="here"[^>]*>([A-Za-z]+)<', nav)
        assert here == [SCREENS[path]], (path, here)

    # Every navigation target is relative, so the whole set works behind the /race/ prefix
    # and on the app's own port alike. href="." is the race screen from anywhere else.
    navs = _navs()
    for path, nav in navs.items():
        assert 'href="/' not in nav, "%s has a root-relative nav target" % path
        assert "://" not in nav, "%s names a host" % path
    assert 'href="hud"' in navs["/"] and 'href="map"' in navs["/"]
    assert 'href="."' in navs["/hud"] and 'href="map"' in navs["/hud"]
    assert 'href="."' in navs["/map"] and 'href="hud"' in navs["/map"]


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


def test_each_page_can_reach_both_others():
    """A phone that lands on any screen must be able to get to the other two.

    It could not, for a while: the race screen had a HUD button and the HUD had nothing,
    so anyone who opened /hud was stuck with no indication that a race screen existed at
    all. Every direction is pinned here because none is discoverable from the code.

    href="." is how the race screen is reached from the other two: it resolves to /race/
    behind the prefix and to / on the app's own port, where a leading slash would work on
    the port and break behind nginx.
    """
    navs = _navs()
    # what each page must be able to reach, and by which relative href
    wanted = {
        "/":    {"hud": "the race screen cannot reach the HUD",
                 "map": "the race screen cannot reach the map"},
        "/hud": {".": "the HUD cannot get back to the race screen",
                 "map": "the HUD cannot reach the map"},
        "/map": {".": "the map cannot get back to the race screen",
                 "hud": "the map cannot reach the HUD"},
    }
    for path, targets in wanted.items():
        for href, complaint in targets.items():
            assert 'href="%s"' % href in navs[path], complaint
        assert 'href="/"' not in navs[path]


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
    # Comments stripped first: the block explains why the map's bands change colour at
    # night, and a declaration parser that does not strip comments reads the prose as a
    # declaration and fails on it.
    css = re.sub(r"/\*.*?\*/", "",
                 (ROOT / "static" / "app.css").read_text(encoding="utf-8"), flags=re.S)
    night = re.search(r"body\.night\s*\{(.*?)\}", css, re.S)
    assert night, "no night theme"
    for declaration in night.group(1).split(";"):
        declaration = declaration.strip()
        if declaration:
            assert declaration.startswith("--"), declaration


# The boat carries an iPad mini 3, which stops at iOS 12. Safari there has no clamp()
# (13.1) and no flexbox gap (14.1), and neither failure is visible on a modern browser,
# which is why both shipped. On the iPad every clamped font-size was dropped and the
# readings rendered at the default 16 px, against the 132 px the distance computes to at
# that viewport when clamp works; and the secondary line came out as
# "leg5of10· thenHallmark-147°close hauled". The leg type is the shorter "beat" now, but
# this is what the iPad actually showed at the time and the record is left as it was.
CSS_FILES = ("static/app.css",)
HTML_WITH_CSS = ("templates/hud.html",)


def _stylesheets():
    for rel in CSS_FILES + HTML_WITH_CSS:
        yield rel, (ROOT / rel).read_text(encoding="utf-8")


def test_every_clamp_has_a_plain_fallback_before_it():
    """clamp() needs Safari 13.1, so on iOS 12 the whole declaration is dropped.

    A dropped font-size falls back to the inherited one, which is how a 132 px reading
    became 16 px on the boat's iPad. The fallback is the clamp's middle term, which is
    the value that actually applies at every real viewport size anyway: the min and max
    only bite at extremes, so this costs nothing on a browser that does support clamp.
    """
    for rel, text in _stylesheets():
        for match in re.finditer(r"([a-z-]+):\s*clamp\(", text):
            prop = match.group(1)
            before = text[max(0, match.start() - 120):match.start()]
            assert re.search(re.escape(prop) + r":\s*[^;{}]+;\s*$", before), (
                "%s: %s: clamp(...) has no plain fallback before it, so iOS 12 drops it"
                % (rel, prop))


def test_no_flex_container_relies_on_gap():
    """Flexbox gap needs Safari 14.1. Grid gap is fine: Safari 12 has that.

    Margins on the children instead, which have worked since flexbox shipped. Note that
    margins reach element children only, while gap also spaces the anonymous items
    flexbox makes out of bare text, so a line of prose must not be a flex container at
    all: #secondary is a plain block for exactly that reason.
    """
    for rel, text in _stylesheets():
        stripped = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        for body in re.finditer(r"\{([^{}]*)\}", stripped):
            decls = body.group(1)
            if "gap:" not in decls:
                continue
            assert "display: grid" in decls, (
                "%s: gap on a non-grid container, which iOS 12 ignores: %s"
                % (rel, " ".join(decls.split())))


def test_the_controls_are_big_enough_to_hit_on_a_moving_boat():
    # Comments stripped first: a rule's explanation sits directly above it, and a
    # selector regex that does not strip them swallows the comment as part of the
    # selector.
    css = re.sub(r"/\*.*?\*/", "", (ROOT / "static" / "app.css").read_text(encoding="utf-8"),
                 flags=re.S)
    button = re.search(r"\nbutton\s*\{(.*?)\}", css, re.S)
    assert button, "no button rule"
    # calc() allowed, the rem term being what matters: the navigation's height is 2.6rem
    # of label plus a clearance that is zero on anything without a home indicator.
    height = re.search(r"min-height:\s*(?:calc\()?([\d.]+)rem", button.group(1))
    assert height and float(height.group(1)) >= 3.0, button.group(1)

    # Every override of that height is listed here, so shrinking a control is a decision
    # someone takes on purpose rather than something that leaks in. This test used to
    # read the generic rule alone, which meant the series buttons could be made smaller
    # without it noticing, and they were.
    #
    # The series buttons are the one exception, deliberately. 2.75rem is 44 px, the
    # platform minimum rather than below it, and a series is chosen once before the
    # start and then not touched, whereas at the inherited size six names as long as
    # "Sunday Afternoon Div III" wrapped to three lines each and pushed the course cards
    # into a scroller.
    # 2.75rem is 44 px, the platform minimum. Each entry is pinned to its exact value, so
    # changing one means changing this test and saying why.
    allowed = {
        # A series is chosen once before the start and then not touched. At the inherited
        # height six names as long as "Sunday Afternoon Div III" wrapped to three lines
        # each and pushed the course cards into a scroller on a phone.
        "#series button": 2.75,
        # The bottom navigation's label band, 41.6 px, a shade under the 44 px minimum.
        # The button is taller than its label band by --nav-pad, so on a phone with a home
        # indicator the thing you actually hit clears 44 px; this is the floor on a device
        # with no indicator, where there is no gesture area to be crowded by either. Left
        # as it is rather than quietly changed: NAV_H pins this number and hud.html carries
        # its own copy of it, which another test checks the two against, so raising it is
        # a deliberate two-file change and not a tidy-up.
        "#nav a, #nav button": 2.6,
    }
    for selector, expected in allowed.items():
        rule = re.search(re.escape(selector) + r"\s*\{(.*?)\}", css, re.S)
        assert rule, "no rule for %s" % selector
        override = re.search(r"min-height:\s*(?:calc\()?([\d.]+)rem", rule.group(1))
        assert override and float(override.group(1)) == expected, \
            "%s changed height without changing this test: %s" % (selector, rule.group(1))
        assert float(override.group(1)) >= 2.5, \
            "%s is too small to hit on a moving boat" % selector

    # And nothing else undercuts it. Any other rule setting a button min-height must be
    # added above with its reason.
    for match in re.finditer(r"([^{}]*button[^{}]*)\{([^}]*)\}", css):
        override = re.search(r"min-height:\s*(?:calc\()?([\d.]+)rem", match.group(2))
        if not override:
            continue
        selector = " ".join(match.group(1).split())
        if selector == "button" or selector in allowed:
            continue
        raise AssertionError("undeclared button min-height on %r: %s"
                             % (selector, match.group(2)))


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



def test_the_app_is_as_tall_as_the_screen_actually_is():
    """100vh is not the visible height on iOS, and that showed as a clipped navigation.

    In a standalone web app with a translucent status bar, iOS counts the area under the
    status bar in 100vh, so #app was taller than what could be seen and the bottom of it,
    the navigation, hung off the screen. 100dvh is the correct answer and arrived in
    Safari 15.4; the iPad on the boat is on 12. window.innerHeight is right on every
    version of everything, so viewport.js measures it.

    Three declarations in ascending order of correctness, because a browser takes the last
    one it understands and ignores the rest. Dropping either of the first two would leave
    a no-JavaScript browser with nothing.
    """
    # Comments stripped: _nav_rules keeps the whole rule body, and #app's carries a long
    # note that mentions every one of the three heights by name.
    css = _bare(ROOT / "static" / "app.css")
    app_rule = _nav_rules(css, "#app")

    heights = re.findall(r"height:\s*([^;]+)", app_rule)
    assert heights == ["100vh", "100dvh", "var(--app-h, 100dvh)"], \
        "the three heights must all be there, worst first: %r" % (heights,)

    script = (ROOT / "static" / "viewport.js").read_text(encoding="utf-8")
    code = re.sub(r"//[^\n]*", "", script)
    assert "window.innerHeight" in code, "the point of the file is to measure, not assume"
    assert "--app-h" in code and "documentElement" in code, \
        "the property has to land on an ancestor of #app"
    # It has to be re-measured, or a rotation or a split-screen leaves a stale height.
    for event in ("resize", "orientationchange", "visibilitychange"):
        assert event in code, "no listener for %s, so the height goes stale" % event

    # Loaded by the two pages built from app.css, and loaded before #app so the height is
    # set before the first layout rather than after a visible reflow.
    for path, page in (("/", _page()), ("/map", _page_map())):
        assert "static/viewport.js" in page, "%s never measures its height" % path
        assert page.index("static/viewport.js") < page.index('<div id="app">'), \
            "%s loads viewport.js too late to matter" % path

    # The HUD is deliberately self-contained, no external script and no external
    # stylesheet (DESIGN 9.1), and reserves its nav height by hand. Left alone.
    assert "viewport.js" not in _page_hud(), \
        "the HUD has no external script, and its nav is out of the flow anyway"


def test_the_navigation_reaches_the_bottom_of_the_screen():
    """The bottom of the phone gives up --nav-pad and nothing else.

    Three goes at this. On #app the inset padded the whole column and left a band of page
    background below the navigation. Moved to #nav, the row's background reached the glass
    but its buttons still stopped short of it, so the band was still there in the nav's
    colour and was reported again. Both of those reserved the full 34pt iOS calls the
    bottom safe area, which is the swipe-up gesture region and much larger than the
    indicator it is there to avoid: the pill is 5pt tall and 8pt off the edge, so 13pt
    clears it. --nav-pad is that clearance, and it is all the screen loses.

    Three things have to hold together, and each of them has failed once:

    - Only the buttons carry the padding. On #app or #nav it reserves a band above the
      glass instead of below the label.
    - The label band is 2.6rem plus the padding, not 2.6rem including it. box-sizing is
      border-box here, so a bare min-height let the padding eat the label's own room and
      the visible row collapsed to the height of the text.
    - It is a clearance, not the whole inset, which is the point of the exercise.
    """
    css = _bare(ROOT / "static" / "app.css")

    app_rule = _nav_rules(css, "#app")
    padding = re.search(r"padding:\s*([^;]+)", app_rule)
    assert padding, "#app still needs the other three insets, for a landscape notch"
    sides = padding.group(1).split()
    assert len(sides) == 4, "four sides, so the bottom one is named and can be checked"
    assert sides[2] == "0", "the bottom inset moved to #nav; #app must not claim it twice"
    for side in (sides[0], sides[1], sides[3]):
        assert side.startswith("env(safe-area-inset-"), side

    assert "padding-bottom" not in _nav_rules(css, "#nav"), \
        "on the row this reserves a band of nav-coloured nothing along the bottom"

    hud = _bare_text(_page_hud())
    hud_nav = _nav_rules(hud, "#nav")
    assert "bottom: 0" in hud_nav, \
        "the HUD's nav is fixed; above the inset it floats and leaves a band behind it"
    assert "padding" not in hud_nav, hud_nav

    # Both stylesheets define the clearance, and both define it twice: a browser with no
    # min() drops the second and gets the 0px it had before any of this.
    for name, sheet in (("app.css", css), ("hud.html", hud)):
        root = re.findall(r":root\s*\{([^}]*)\}", sheet)
        assert root, name
        pads = re.findall(r"--nav-pad:\s*([^;]+)", " ".join(root))
        assert pads == ["0px", "min(env(safe-area-inset-bottom), 0.9rem)"], \
            "%s: the fallback and the clearance, in that order, got %r" % (name, pads)

    # The buttons carry it, and their label band is 2.6rem on top of it rather than
    # including it, which border-box would otherwise do.
    for name, rule in (("app.css", _nav_rules(css, "#nav a, #nav button")),
                       ("hud.html", _nav_rules(hud, "#nav a, #nav button"))):
        # The bottom of a four-sided padding, the sides having to be zeroed as well so a
        # button measures the same as a link. See the theme test for why.
        assert "padding: 0 0 var(--nav-pad) 0" in rule, \
            "%s: the buttons stop short of the bottom of the screen" % name
        assert "min-height: calc(%s + var(--nav-pad))" % NAV_H in rule, \
            "%s: border-box lets the padding eat the label's own room" % name

    # And the HUD reserves exactly what its out-of-flow nav now takes.
    assert "padding-bottom: calc(%s + var(--nav-pad))" % NAV_H in " ".join(hud.split()), \
        "hud.html no longer reserves the room its nav takes"


# The readouts with no natural width limit, and the widest string each ever shows.
# Every one of these is sized off the viewport, and a font sized by height alone runs off
# the side of a narrow screen: #countdown at 22vh measured 409px of glyphs in 375px.
BIG_READOUTS = {
    "#countdown": "09:55",
    "#final-elapsed": "0:11:21",
}

# The widest digit in the stack's first font, as a fraction of the font size, measured in
# chromium at three viewports and rounded up. Digits are tabular here, so one number does.
GLYPH_EM = 0.56


def test_the_big_readouts_fit_the_narrowest_screen():
    """A font sized in vh overflows a tall narrow screen, and the phone is one.

    The countdown is the largest thing the app draws and the one reading the crew cannot
    afford to lose a digit from. At 22vh on the phone it came out at 147px and its five
    characters needed 409px of a 375px screen, so the seconds ran off the edge. It looked
    right on the iPad and on a desktop, both of which are wider than they are tall.

    The cap is a vw term, so it scales with the dimension that was actually short. min()
    is Safari 11.1 and clamp() is 13.1, so the plain vw declaration ahead of the clamp is
    what the iPad on iOS 12 uses; the clamp is what keeps a wide desktop from taking the
    vw term literally and drawing something enormous.
    """
    css = _bare(ROOT / "static" / "app.css")

    for selector, widest in BIG_READOUTS.items():
        rule = _nav_rules(css, selector)
        sizes = re.findall(r"font-size:\s*([^;]+)", rule)
        assert len(sizes) == 2, \
            "%s needs a plain fallback and then a capped size, got %r" % (selector, sizes)
        fallback, capped = sizes

        vw = re.fullmatch(r"([\d.]+)vw", fallback)
        assert vw, "%s: the iOS 12 fallback must be sized by width: %r" % (selector, fallback)
        assert "min(" in capped and "vw" in capped, \
            "%s: the modern size must be capped by width too: %r" % (selector, capped)

        # The narrowest screen the app is used on, an iPhone SE in portrait, and the
        # widest reading that selector ever holds.
        width = 320.0
        font = float(vw.group(1)) / 100.0 * width
        glyphs = font * GLYPH_EM * len(widest)
        assert glyphs < width, \
            "%s overflows a %dpx screen: %r needs %dpx of %dpx" % (
                selector, width, widest, round(glyphs), width)


# --- the theme, which is shared state and not a class this page toggles on itself ------


def test_the_theme_is_server_state_and_reaches_every_screen():
    """Three faults came back from the boat at once and they are one fault.

    Night could only be set from the course-selection panel, because that is where the
    button was; it did not reach the HUD or the map, because a class on this document
    cannot; and walking to either of those and back lost it, because nothing remembered.
    A setting held in a document cannot survive leaving that document, and these are three
    separate documents by decision (DESIGN 9.1 and 12.1).

    So it is server state, which is what DESIGN 9.9 already says about everything else
    here: every device renders the same state and any device can drive it. It rides in
    /api/state, which all three pages poll twice a second anyway.
    """
    store = Store()
    flask_app = app_module.create_app(store, CONFIG)
    flask_app.config["TESTING"] = True
    client = flask_app.test_client()

    # In the state document every page already fetches, so no page polls twice for it.
    assert client.get("/api/state").get_json()["theme"] == "day", "day by default"

    got = client.post("/api/settings", json={"theme": "night"}).get_json()
    assert got == {"theme": "night"}, "the response must say what is in force"
    assert client.get("/api/state").get_json()["theme"] == "night", \
        "a setting that does not reach the state document reaches no other device"

    # It ends up as a class on the body of three pages, so nothing else may get through.
    for bad in ("rubbish", "", None, "Night", "day night", 7, {"a": 1}):
        assert client.post("/api/settings", json={"theme": bad}).get_json() == \
            {"theme": "night"}, bad
    assert client.get("/api/state").get_json()["theme"] == "night", \
        "a rejected value changed the theme anyway"
    # The answer is what is in force, not what was asked for, so a page never has to
    # assume its own post took.
    import inspect
    body = inspect.getsource(Store.set_theme)
    assert "return self._theme" in body and "return name" not in body, body
    assert Store.THEMES == ("day", "night"), \
        "the allowed set is the two, and it is named in the store"

    # And back, since a toggle has to work in both directions.
    assert client.post("/api/settings", json={"theme": "day"}).get_json() == {"theme": "day"}


def test_every_screen_can_set_the_theme_and_none_of_them_keeps_its_own():
    """The toggle is the fourth cell of the navigation, which is the one piece of furniture
    all three screens share, so it is one tap from anywhere and in the same place.

    Its label is the theme one tap will switch to, not the one in force: a control that
    names its own state needs a second affordance to say it is a control, and the theme in
    force is already obvious from the whole screen being red.
    """
    navs = _navs()
    assert len(navs) == 3
    for path, nav in navs.items():
        assert "data-theme-toggle" in nav, "%s cannot set the theme" % path
        # Empty in the markup: whichever theme is in force decides the word, and only the
        # script knows which that is.
        assert re.search(r"<button data-theme-toggle>\s*</button>", nav), path

    # Four equal cells, on all three screens. A user agent gives a button its own font,
    # border, background and 6px of side padding, and under border-box a flex-basis of 0
    # cannot absorb that padding, so an unreset button measures wider than the links
    # beside it: the race page came out 85, 73, 73, 85 and the HUD's toggle, which its
    # rule did not select at all, came out 52 against 238. The row is hit by feel.
    for name, sheet in (("app.css", _bare(ROOT / "static" / "app.css")),
                        ("hud.html", _bare_text(_page_hud()))):
        rule = _nav_rules(sheet, "#nav a, #nav button")
        assert "flex: 1 1 0" in rule, name
        assert "padding: 0 0 var(--nav-pad) 0" in rule, \
            "%s: the sides must be zeroed, not only the bottom set" % name
    hud_rule = _nav_rules(_bare_text(_page_hud()), "#nav a, #nav button")
    for reset in ("background: none", "border: none", "font: inherit"):
        assert reset in hud_rule, \
            "hud.html: a button needs %s or it does not look like a link" % reset

    # Gone from the panel it used to live on, or there are two controls for one setting.
    page = _page()
    assert 'id="night"' not in page, "the old panel button is still there"
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert 'on("night"' not in js, "the old handler still toggles this document only"

    # Applied from the poll on all three, so a change made anywhere arrives everywhere
    # within half a second.
    for name in ("app.js", "map.js"):
        text = (ROOT / "static" / name).read_text(encoding="utf-8")
        assert "window.Theme.apply(state.theme)" in text, \
            "%s never applies the theme it is told" % name
        assert 'src="static/theme.js"' in (_page() if name == "app.js" else _page_map()), \
            "%s's page does not load theme.js" % name
    # In the poll, not merely somewhere in the file: postTheme applies the server's
    # answer too, and matching that one would pass with the poll's line deleted.
    hud = _page_hud()
    assert re.search(r"paintRace\(d\);\s*\n\s*applyTheme\(d\.theme\);", hud), \
        "the HUD never applies the theme its poll is told"
    # Self-contained is the actual invariant: no external script at all, not merely no
    # mention of the shared one, which its comments name in order to say it is a copy.
    assert "<script src=" not in hud, "the HUD is self-contained (DESIGN 9.1)"


def test_the_huds_copy_of_the_theme_switch_matches_the_shared_one():
    """hud.html is self-contained by decision, no external script and no external
    stylesheet, so the port could be compared against the Node-RED tab side by side
    (DESIGN 9.1). That means a second copy of this, and two copies drift.
    """
    shared = (ROOT / "static" / "theme.js").read_text(encoding="utf-8")
    hud = _page_hud()

    # The same two directions and the same two labels, or one screen offers Night while
    # another offers Day for the same state.
    for text in (shared, hud):
        assert re.search(r"day:\s*\"night\",\s*night:\s*\"day\"", text), text[:0] or "OTHER"
        assert re.search(r"day:\s*\"Night\",\s*night:\s*\"Day\"", text), "LABEL"

    # Both post to /api/settings, both take the server's answer as final, and both apply
    # at once rather than waiting for the next poll.
    for name, text in (("theme.js", shared), ("hud.html", hud)):
        assert "/api/settings" in text, name
        # The server is the authority: whatever it answers is what the page shows, so a
        # refused value puts the page back rather than leaving it lying.
        assert re.search(r"if \(d && d\.theme\) appl\w*\(d\.theme\)", text), \
            "%s does not take the server's answer as final" % name
        assert '{ theme: want }' in text or "{ theme: want }" in text, name
        assert "location.pathname" in text, "%s hardcodes a host" % name
        assert text.count("classList.toggle(\"night\"") == 1, name


def test_the_hud_has_a_night_palette_of_its_own():
    """It had none. The gap was invisible while the toggle lived on one panel of one page,
    since nothing could ask this page to go dark, and DESIGN 9.7 has asked for it since
    the beginning.

    Every reading is a red. Nothing may be blue, green or yellow: the point of the theme is
    that no other wavelength reaches the eye, and this page's four colour pairs give up
    being told apart by hue for the night, tint being what is left.
    """
    hud = _page_hud()
    block = re.search(r"body\.night \{(.*?)\}", hud, re.S)
    assert block, "hud.html has no night theme"
    night = dict(re.findall(r"--([a-z]+):\s*(#[0-9a-fA-F]{6})", block.group(1)))

    day_block = re.search(r":root \{(.*?)\n  \}", hud, re.S)
    day = dict(re.findall(r"--([a-z]+):\s*(#[0-9a-fA-F]{6})", day_block.group(1)))
    assert set(night) == set(day), \
        "every colour needs a night value: missing %s" % (set(day) - set(night),)

    # Red-dominant, and not by a little: red at least half again either other channel.
    for name, value in night.items():
        r, g, b = (int(value[i:i + 2], 16) for i in (1, 3, 5))
        assert r >= 1.5 * g and r >= 1.5 * b, \
            "--%s is %s, which is not a red" % (name, value)

    # Each pair still has to be two colours, or the night theme silently merges the true
    # and apparent readings into one.
    for a, b in (("twa", "awa"), ("tws", "aws"), ("hdg", "cog")):
        assert night[a] != night[b], \
            "--%s and --%s are the same red, so the pair cannot be read apart" % (a, b)

    # The same reading is the same colour on every screen, day or night, so the three
    # copies of each value have to agree. --brg is app.css's name for the HUD's --hdg.
    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
    shared = re.search(r"body\.night \{(.*?)\n\}", css, re.S)
    assert shared
    app_night = dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6})", shared.group(1)))
    for hud_name, app_name in (("sog", "sog"), ("cog", "cog"), ("hdg", "brg"),
                               ("mark", "mark"), ("twa", "twa"), ("tws", "tws"),
                               ("rpm", "rpm"), ("cur", "cur"), ("ctrl", "ctrl"),
                               ("mot", "mot"), ("rule", "rule"), ("label", "label")):
        assert hud_name in night and app_name in app_night, (hud_name, app_name)
        assert night[hud_name].lower() == app_night[app_name].lower(), \
            "--%s is %s at night on the HUD and %s on the other two screens" % (
                hud_name, night[hud_name], app_night[app_name])


# The three leg types, and the whole of the set. One word each.
LEG_TYPES = ("beat", "reach", "run")


def test_a_leg_type_is_one_short_word():
    """"beat", not "close hauled", which it was for a while.

    Four characters against twelve, and it is read in two places with no room for twelve:
    the race screen's secondary row, where it comes last after the leg number, the next
    mark's name and the transit angle, and the leg table's right-hand column beside the
    cumulative distance. It is also the crew's own word for the leg.

    The length is the point, so it is asserted rather than left to the string. A future
    "close hauled", "downwind run" or "broad reach" would each undo the fix silently, the
    row not breaking so much as quietly eating the mark name beside it.
    """
    from engine import course as course_module

    produced = set()
    for twd in range(0, 360, 5):
        for bearing in range(0, 360, 5):
            got = course_module.leg_type(float(twd), float(bearing))
            assert got in LEG_TYPES, (twd, bearing, got)
            produced.add(got)
    assert produced == set(LEG_TYPES), "a type that can never occur: %s" % (
        set(LEG_TYPES) - produced,)

    for word in LEG_TYPES:
        assert len(word) <= 5, "%r is too long for the row it is read in" % word
        assert " " not in word, "%r is two words, and it is read where one fits" % word

    # Both modules answer the same, race.py delegating to course.py, so the briefing sheet
    # and the race screen cannot disagree about what a leg is.
    assert race.leg_type(0.0, 10.0) == "beat"
    assert race.BEAT_MAX == course_module.BEAT_MAX == 40.0
    assert race.RUN_MIN == course_module.RUN_MIN == 140.0
    # One definition, not two that happen to hold the same number today: equality alone
    # passes right up until someone edits one of them.
    import inspect
    source = inspect.getsource(race)
    for name in ("BEAT_MAX", "RUN_MIN"):
        assert "%s = course_module.%s" % (name, name) in source, \
            "race.py keeps its own %s, so the two can drift" % name
    assert "return course_module.leg_type(" in inspect.getsource(race.leg_type), \
        "race.py has its own copy of the arithmetic"

    # And nothing anywhere still emits the long form. The prose is left alone, "sailing
    # close hauled" being the sailing term and course.py's docstring naming the old label
    # in order to say it is the old label; what may not come back is a value.
    for rel in ("engine/course.py", "engine/race.py", "static/app.js", "static/map.js",
                "templates/hud.html", "templates/index.html"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        for emit in ('return "close hauled"', '= "close hauled"',
                     "return 'close hauled'", 'textContent = "close hauled"'):
            assert emit not in text, "%s still produces the long form" % rel


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
