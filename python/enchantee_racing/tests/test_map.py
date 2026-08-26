"""The map page: what it serves, what it draws, and in what order.

The chart itself is drawn by the browser from config/, so what can be checked here is the
contract between the two: that the page is served and self-contained, that the layers exist
in the order DESIGN 12 states, that map.js asks for its data the way this app asks for
everything, and that the data it is going to draw is the shape it expects.

What cannot be checked here is what it looks like. That is done by rendering the real page
in headless chromium at a device viewport, which is how the first draft's two faults were
found: unsurveyed water came out black because nothing was drawn under the depth bands, and
the marks were 1.7 px across because their radius was in metres in a frame 11 km wide.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402
from store import Store  # noqa: E402

CONFIG = app_module.load_config()


def _client():
    store = Store()
    flask_app = app_module.create_app(store, CONFIG)
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def _page():
    return _client().get("/map").get_data(as_text=True)


def _map_js():
    return (ROOT / "static" / "map.js").read_text(encoding="utf-8")


def _function(code, name):
    """The body of one function out of map.js, by brace matching.

    Slicing between two function names was the first approach and it was brittle: it
    depends on which function happens to come next in the file, and the applyScale test
    broke the moment padded() sat before it rather than after.
    """
    start = code.index("function " + name)
    depth, i = 0, code.index("{", start)
    opened = False
    while i < len(code):
        if code[i] == "{":
            depth += 1
            opened = True
        elif code[i] == "}":
            depth -= 1
            if opened and depth == 0:
                return code[start:i + 1]
        i += 1
    raise AssertionError("unbalanced braces reading %s" % name)


def _map_code():
    """map.js with its comments removed.

    The guards below look for names that must not appear, and map.js explains at length
    why they must not: the comment about Pointer Events names pointerdown in order to say
    that every recipe reaches for it. A guard that reads the prose fails on the
    explanation, which is what happened the first time.
    """
    source = _map_js()
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", source)


def test_the_map_is_served_as_its_own_page():
    """DESIGN 12.1: its own page, not a fourth panel on the race screen."""
    response = _client().get("/map")
    assert response.status_code == 200
    assert "text/html" in response.headers["Content-Type"]
    assert 'id="chart"' in response.get_data(as_text=True)


def test_the_layers_are_in_the_order_design_12_states():
    """Depth bands, then the contours that divide them, then land, then marks and course.

    Order in the document is order on the screen for SVG, so this is the whole of the
    draw order and getting it wrong hides the thing underneath. Land over the bands
    matters most: the bands are interpolated to the shore, so without land on top they
    spill over the bank.
    """
    page = _page()
    wanted = ["layer-bands", "layer-contours", "layer-land", "layer-lines", "layer-marks",
              "layer-course", "layer-boat"]
    found = re.findall(r'<g id="(layer-[\w-]+)"', page)
    assert found == wanted, found
    # The course and the boat are last because they are the only things that move and the
    # only ones the crew is looking for once the gun has gone. The boat is above the
    # course: own ship is never hidden by a leg line.


def test_the_page_references_nothing_off_box_and_nothing_absolutely():
    """No internet on the Pi, and a /race/ prefix to survive (CLAUDE.md)."""
    page = re.sub(r"<!--.*?-->", "", _page(), flags=re.S)
    assert "http://" not in page and "https://" not in page
    for absolute in ('src="/', 'href="/', 'url(/'):
        assert absolute not in page, absolute
    # and it takes the shared stylesheet rather than inlining one: hud.html inlines its
    # CSS only because it was a verbatim port to be compared side by side (DESIGN 9.1),
    # and the map has no original (DESIGN 12.1).
    assert 'href="static/app.css"' in page
    assert "<style" not in page, "the map should not carry its own copy of the CSS"
    assert 'src="static/geo.js"' in page and 'src="static/map.js"' in page


def test_the_caveats_are_on_the_page_and_not_only_in_a_comment():
    """DESIGN 12 requires them, and this is the one screen that looks like a chart.

    Crowd-sourced banks, a 2010 survey, and nothing about sandbanks, which is where the
    trouble on Melville Water actually is.
    """
    page = _page()
    caveat = re.search(r'id="map-caveat"[^>]*>(.*?)</p>', page, re.S)
    assert caveat, "no caveat on the map"
    text = " ".join(caveat.group(1).split()).lower()
    assert "not for navigation" in text
    assert "sandbank" in text
    assert "2010" in text
    assert "openstreetmap" in text


def test_the_map_asks_for_its_data_the_way_the_app_asks_for_everything():
    """Relative to location.pathname, so it works behind /race/ and on its own port."""
    js = _map_js()
    assert "location.pathname" in js
    assert 'base + "/api/config/"' in js, "the map does not use the config route"
    assert '"/api/config' not in js.replace('base + "/api/config', ""), \
        "an absolute config path would break behind the prefix"
    # every document it needs, and no more
    for name in ("lines", "marks", "coast", "depth"):
        assert 'fetchJson("%s")' % name in js, name
    assert set(re.findall(r'fetchJson\("(\w+)"\)', js)) == {"lines", "marks", "coast", "depth"}


def test_the_map_projects_through_the_shared_transcription():
    """Not its own copy of the projection: the map and the engine have to agree, and
    geo.js is the transcription that is proved against nav.py (DESIGN 12.1 step 2)."""
    code = _map_code()
    assert "Geo.enu(" in code, "the map is not using geo.js"

    # No second projection hiding in here. Trig on its own is not the tell-tale, and
    # banning it was wrong: drawBoat legitimately uses sin and cos to point a triangle
    # along a bearing, which is rotating a symbol and not projecting a coordinate. What
    # would be a second projection is the geodesy.
    for tell in ("6378137", "WGS84", "metresPerDegree", "Math.pow(w", "298.257"):
        assert tell not in code, "%s in map.js means a second projection" % tell
    # Only project() turns a coordinate into a point, and only geo.js is asked.
    assert code.count("Geo.") == code.count("Geo.enu("), \
        "map.js reaches into geo.js for more than the projection"
    # And the y flip happens exactly once, or the map is mirrored north to south.
    assert code.count("-p.n") == 1, "the y inversion belongs in project() and nowhere else"


def test_the_data_the_map_draws_is_the_shape_it_expects():
    """A guard on the config documents rather than on the page.

    The map keys off property values, so a regenerated document that renamed a band or a
    kind would draw nothing and raise nothing. gen_depth.py and gen_coast.py own these
    names; this notices if they move.
    """
    depth = json.loads((ROOT / "config" / "depth.json").read_text(encoding="utf-8"))
    kinds = set(f["properties"]["kind"] for f in depth["features"])
    assert kinds == {"band", "contour"}, kinds

    bands = set(f["properties"]["band"] for f in depth["features"]
                if f["properties"]["kind"] == "band")
    assert bands == {"shallow", "mid", "deep"}, bands
    # every band carries the colour the map fills it with, so the palette lives in the
    # data and not in two places
    for f in depth["features"]:
        if f["properties"]["kind"] == "band":
            assert re.match(r"^#[0-9a-f]{6}$", f["properties"]["color"]), f["properties"]
        else:
            assert f["properties"]["depth_m"] in (2.0, 4.0), f["properties"]

    coast = json.loads((ROOT / "config" / "coast.json").read_text(encoding="utf-8"))
    assert all(f["properties"]["kind"] == "land" for f in coast["features"]), \
        "coast.json should be land, not water: OSM does not tag the open sea (DESIGN 12)"

    # The no-cross lines carry mark ids, not coordinates, and the map resolves them
    # through the mark index. Number would not do: fourteen numbers belong to two marks.
    lines = json.loads((ROOT / "config" / "lines.json").read_text(encoding="utf-8"))
    marks = json.loads((ROOT / "config" / "marks.json").read_text(encoding="utf-8"))
    known = set(m["id"] for m in marks["marks"])
    for line in lines["no_cross_lines"]:
        assert len(line["marks"]) == 2, line["id"]
        for mark_id in line["marks"]:
            assert mark_id in known, "%s names an unknown mark %s" % (line["id"], mark_id)


def test_the_symbols_are_sized_in_pixels_not_metres():
    """The frame is metres and a chart symbol is a fixed size on the paper.

    The first draft set the radius in metres, and at the racing extent a 25 m mark came
    out at 1.7 px: 131 invisible specks. SVG cannot express "constant on screen" for
    anything but strokes, so the radius and the label size are recomputed against the
    current metres-per-pixel whenever the view changes.
    """
    js = _map_js()
    assert "function metresPerPixel" in js
    assert "function applyScale" in js
    assert "SYMBOL_PX" in js, "the symbol sizes should be named in pixels"
    # applyScale has to be called when the view changes and when the element resizes, or
    # the symbols are right once and wrong afterwards.
    assert js.count("applyScale()") >= 2, "applyScale is not called from setView"
    assert 'addEventListener("resize", applyScale)' in js
    assert "orientationchange" in js, "iOS changes the element size without a resize"


def test_unsurveyed_water_is_drawn_as_water():
    """The survey covers 91.3 per cent of its own footprint and nothing outside it.

    So Matilda Bay, Perth Water, the Canning entrance and the whole ocean west of the
    coast have no depth band. Rendering the real page found them black, which reads as
    land or as nothing; the canvas is now water and everything is drawn over it.
    """
    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
    chart = re.search(r"#chart\s*\{([^}]*)\}", css)
    assert chart, "no #chart rule"
    assert "background: var(--water)" in chart.group(1), \
        "the canvas is not water, so unsurveyed water will read as void"
    # and --water is defined in both themes, and is not one of the three band colours,
    # or it would claim a depth it does not have
    for theme in (r"^body \{([^}]*)\}", r"^body\.night \{([^}]*)\}"):
        block = re.search(theme, css, re.M | re.S)
        assert block, theme
        assert "--water:" in block.group(1), theme
    bands = re.findall(r"--band-\w+:\s*(#[0-9a-f]{6})", css)
    waters = re.findall(r"--water:\s*(#[0-9a-f]{6})", css)
    for water in waters:
        assert water not in bands, "%s is both a band colour and the no-data colour" % water


def test_the_view_has_the_three_levels_design_settled():
    """Fit to the course, out to the racing bbox, out again to the whole coast.

    Two zoom-outs rather than one, because coast.json was generated far wider than the
    racing area for ocean races and the island anchorages, and one level would have to
    choose between making that unreachable and making the ordinary case illegible
    (DESIGN 12.1).

    Measured in a browser against a selected Frostbite course 3: 1967 x 2648 m fitted,
    11080 x 8726 at the racing bbox, 61230 x 55544 at the coast, and Out disabled at the
    last of them.
    """
    js = _map_js()
    assert "levels = [fitted || racing, racing, extentOf(coast.bbox)]" in js, \
        "the three levels are not the ones DESIGN 12.1 settled"
    assert "function showLevel" in js
    assert "el.out.disabled" in js, "Out gives no sign that it has run out of levels"
    page = _page()
    assert 'id="map-fit"' in page and 'id="map-out"' in page
    assert 'id="map-scope"' in page, "nothing names what is on the screen"


def test_the_default_view_is_the_course_and_falls_back_to_the_racing_area():
    """DESIGN 12 says fit to the current course. No course selected is the ordinary idle
    case, and then the racing bbox is the right view, so a missing course must not be
    treated as a failure.
    """
    js = _map_js()
    assert "showLevel(0)" in js, "the map does not open on the fitted level"
    assert "fitted || racing" in js, "no fallback when no course is selected"
    assert "function fetchCourse" in js
    fetch_course = _function(_map_code(), "fetchCourse")
    assert "return null" in fetch_course
    assert ".catch(function () { return null; })" in fetch_course, \
        "a failed course fetch must not reject and block the chart"

    # Both ends of the start line are in the fitted extent: the race begins and ends there
    # and a view that cut the line off would miss what the crew looks at first.
    extent = _function(_map_code(), "courseExtent")
    assert "start_finish.inner" in extent and "start_finish.outer" in extent


def test_panning_and_zooming_are_clamped():
    """A crew that has dragged the chart into empty space with no way back is worse off
    than one with no map. Fit is the recovery, and these are the guard rails."""
    js = _map_js()
    assert "function clampView" in js
    assert "MIN_SPAN_M" in js and "MAX_SLACK" in js
    clamp = _function(_map_code(), "clampView")
    assert "Math.min(maxW / v.w, maxH / v.h)" in clamp, \
        "zoom-out clamp must scale both axes together"
    assert "Math.max(MIN_SPAN_M / v.w, MIN_SPAN_M / v.h)" in clamp
    # Measured in a browser: forty wheel zoom-ins stop at 100 m across.
    assert "MIN_SPAN_M = 100" in js


def test_the_gestures_use_touch_events_and_not_pointer_events():
    """Pointer Events need Safari 13 and the boat's iPad is on 12.

    Same list as clamp() and flexbox gap, and the one every pan-and-zoom recipe gets
    wrong, because they all reach for pointerdown.
    """
    code = _map_code()
    for banned in ("pointerdown", "pointermove", "pointerup", "pointercancel",
                   "onpointer", "PointerEvent", "setPointerCapture"):
        assert banned not in code, "%s needs Safari 13; the iPad is on 12" % banned
    for wanted in ("touchstart", "touchmove", "touchend", "touchcancel"):
        assert wanted in code, wanted
    for wanted in ("mousedown", "mousemove", "mouseup", "wheel"):
        assert wanted in code, wanted


def test_screen_to_user_coordinates_go_through_the_svg_matrix():
    """preserveAspectRatio is meet, so there are letterbox margins whenever the viewBox
    aspect does not match the element's. getScreenCTM accounts for them already;
    computing it from the element's rect is a class of off-by-a-margin bug.
    """
    js = _map_js()
    assert "getScreenCTM" in js
    assert "createSVGPoint" in js
    assert "matrixTransform" in js
    assert "function zoomAbout" in js
    zoom = _function(_map_code(), "zoomAbout")
    assert zoom.count("clientToUser") == 2, \
        "the anchor must be measured before and after the resize"


def test_a_finger_lifted_out_of_a_pinch_becomes_a_pan():
    """Otherwise the map sticks until the crew lets go with both fingers, which feels like
    a hang and is the kind of thing only a real hand finds."""
    js = _map_js()
    end = _function(_map_code(), "onTouchEnd")
    assert "event.touches.length === 1" in end
    assert 'kind: "pan"' in end


def test_the_boat_is_hidden_on_a_stale_or_missing_fix():
    """DESIGN 9.5: blank, never dim. A dimmed boat still reads as a boat, and it would be
    a boat somewhere it is not.

    The server has already applied the 5 s cutoff, so this reads one flag rather than
    forming a second opinion about the age of a fix. Verified in a browser against the
    deployed instance, which has no GPS at all: layer-boat carried hidden.
    """
    code = _map_code()
    guard = _function(code, "drawBoat")
    assert "fix.stale" in guard, "the boat does not check the staleness flag"
    assert "!fix.v" in guard, "a payload with no position at all is not handled"
    assert 'setAttribute("hidden"' in guard, "the boat is not hidden, only styled"
    # Nothing dims it instead.
    assert "opacity" not in guard, "a stale boat must be hidden, not faded"


def test_the_boat_points_along_its_course_over_ground():
    """COG, because that is where the boat is going, and heading only as the fallback for a
    boat that is stopped, where COG is noise. The HUD shows the pair for the same reason
    (DESIGN 9.10, 9.3)."""
    code = _map_code()
    boat = _function(code, "drawBoat")
    assert "fields.cog" in boat, "the boat is not oriented by course over ground"
    assert "fields.hdg" in boat, "no fallback when COG is missing"
    assert boat.index("fields.cog") < boat.index("fields.hdg"), \
        "heading must be the fallback, not the first choice"
    # A bearing is clockwise from north and the screen's y axis points down, so the
    # forward vector is (sin, -cos). Getting this wrong mirrors the boat.
    assert "Math.sin(rad), -Math.cos(rad)" in boat


def test_the_leg_being_sailed_is_the_one_with_weight():
    """DESIGN 9.2 puts the next mark first in the crew's attention; this is that on a
    chart. The leg index comes from the race, so the map and the race screen cannot
    disagree about which leg is being sailed."""
    code = _map_code()
    draw = _function(code, "drawCourse")
    assert "state.race.leg" in draw, "the current leg is not taken from the race state"
    assert "leg-now" in draw, "no emphasis on the leg being sailed"
    assert "target-ring" in draw, "the mark being sailed to is not marked"
    # The finish is the line, not a mark, so the last leg has to end at the line's midpoint
    # rather than nowhere.
    assert "startMid" in draw
    assert "function midOfLine" in code


def test_the_leg_after_this_one_is_marked_too_and_more_lightly():
    """Three states on a course that crosses itself, so weight alone will not separate
    them: Frostbite 3 puts ten legs over the same water.

    --sog and --dist are the same DodgerBlue, so the leg being sailed is already told
    apart by width and opacity alone, and a third step of that would be three widths of
    one line to read at a glance on a wet screen. The next leg therefore differs in kind
    as well as degree, dashed against the current leg's solid, and heavier than the rest.

    Verified in a browser mid-race on leg 3 of Frostbite 3: ten legs, one now at index 3,
    one next at index 4, eight plain, and three distinct computed styles.
    """
    code = _map_code()
    draw = _function(code, "drawCourse")
    assert "legIndex + 1 === i" in draw, "the leg after this one is not marked"
    assert "leg-next" in draw
    # Current wins where both could apply, and the last leg has no next.
    assert draw.index("leg-now") < draw.index("leg-next"), \
        "the current leg must take precedence over the next"

    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
    def rule(selector):
        found = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
        assert found, "no rule for %s" % selector
        return found.group(1)

    plain = rule("#chart .leg-line")
    nxt = rule("#chart .leg-line.leg-next")
    now = rule("#chart .leg-line.leg-now")

    def width(body):
        found = re.search(r"stroke-width:\s*([\d.]+)", body)
        assert found, body
        return float(found.group(1))

    # A strict hierarchy, so the three are ordered and not merely different.
    assert width(plain) < width(nxt) < width(now), (width(plain), width(nxt), width(now))
    # And the next leg is dashed where the other two are not, which is the difference in
    # kind that makes it findable rather than merely thicker.
    assert "stroke-dasharray" in nxt, "the next leg is not distinguishable in kind"
    assert "stroke-dasharray: none" in now, \
        "the current leg must clear the dash, or a later edit to the shared rule dashes it"
    assert "stroke-dasharray" not in plain

    # Not the same dash as the no-cross lines: a glance takes the pattern before the
    # colour, and those mean something entirely different (DESIGN 11.3).
    nocross = rule("#chart .nocross")
    next_dash = re.search(r"stroke-dasharray:\s*([^;]+)", nxt).group(1).strip()
    nocross_dash = re.search(r"stroke-dasharray:\s*([^;]+)", nocross).group(1).strip()
    assert next_dash != nocross_dash, \
        "the next leg and a line it is a breach to cross share a dash pattern"


def test_the_overlay_follows_a_change_of_course():
    """A course change is a deliberate act that just happened, so the map follows it, the
    same principle DESIGN 9.6 applies to a mode change on the race screen.

    Abandoning a course must not leave its legs drawn on the chart.
    """
    code = _map_code()
    on_state = _function(code, "onState")
    assert "id !== have" in on_state, "a change of course is not noticed"
    assert "levels[0]" in on_state, "the fitted level is not updated for the new course"
    assert "drawCourse(state)" in on_state
    # and no course means no legs and the racing bbox back
    assert "if (!id)" in on_state, "abandoning a course is not handled"


def test_the_overlay_is_redrawn_when_the_scale_changes():
    """The boat, its vector and the target ring are sized in pixels like every other
    symbol on this page, so a zoom has to redraw them or they stay the size they were.

    Affordable because it is a dozen nodes, against the chart's sixteen thousand
    coordinate pairs, which is the whole reason the chart is built once and this is not.
    """
    code = _map_code()
    scale = _function(code, "applyScale")
    assert "drawCourse(lastState)" in scale and "drawBoat(lastState)" in scale


def test_panning_does_not_resize_every_symbol():
    """Reported from the boat: pan and pinch slower on the iPad than the iPhone.

    applyScale writes an attribute to all 131 circles and 20 labels, and a pan does not
    change the scale at all, so doing it per touchmove was 151 pointless writes an event
    plus a redraw of the overlay. Gesture updates are also coalesced to one a frame, since
    iOS delivers touchmove faster than it paints.
    """
    code = _map_code()
    set_view = _function(code, "setView")
    assert "previous.w !== view.w" in set_view, \
        "applyScale runs on every pan, which is what made the iPad slow"
    assert "function scheduleView" in code
    assert "requestAnimationFrame" in code
    # the pan path goes through the scheduler, not straight to setView
    pan = _function(code, "panBy")
    assert "scheduleView(" in pan and "setView(" not in pan


def test_the_boat_has_its_own_colour():
    """It is the thing the crew looks for first, and it must not be mistaken for a leg, a
    mark or the start line. The first draft borrowed --time, a pale green, which vanished
    against the >4 m band: that band is most of the water on this page.
    """
    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
    boat = re.search(r"#chart \.boat \{([^}]*)\}", css)
    assert boat, "no boat rule"
    assert "var(--boat)" in boat.group(1), "the boat borrows another colour"
    for theme in (r"^body \{([^}]*)\}", r"^body\.night \{([^}]*)\}"):
        block = re.search(theme, css, re.M | re.S)
        assert block and "--boat:" in block.group(1), "no boat colour for %s" % theme


if __name__ == "__main__":
    import traceback

    count = 0
    for test_name in sorted(dict(globals())):
        test = globals()[test_name]
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
