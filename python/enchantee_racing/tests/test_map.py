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
    wanted = ["layer-bands", "layer-contours", "layer-land",
              "layer-structures", "layer-navaids",
              "layer-lines", "layer-marks", "layer-course", "layer-boat"]
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
    wanted = {"lines", "marks", "coast", "depth", "structures", "navaids"}
    for name in wanted:
        assert 'fetchJson("%s")' % name in js, name
    assert set(re.findall(r'fetchJson\("(\w+)"\)', js)) == wanted
    # and every one of them is servable, or the fetch 404s
    assert wanted <= set(app_module.SERVABLE_CONFIG) | {"lines"}, \
        "the map fetches a document the config route will not serve"
    for name in wanted:
        assert name in app_module.SERVABLE_CONFIG, "%s is not servable" % name


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

    # Five classes on a 2/5/10 split, foreshore among them. An earlier 2/4 cut put 70 per
    # cent of the marks in its top band, which is another way of saying it carried no
    # information (DESIGN 12). If a regeneration changes the set, the night palette and
    # the draw order in map.js both have to move with it, which is what this catches.
    bands = set(f["properties"]["band"] for f in depth["features"]
                if f["properties"]["kind"] == "band")
    assert bands == {"foreshore", "shallow", "mid", "deep", "deepest"}, bands

    # Every band the data carries has a night colour and a place in the draw order.
    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
    code = _map_code()
    order = re.search(r"var order = \{([^}]*)\}", code)
    assert order, "no band draw order"
    for band in bands:
        assert "--band-%s:" % band in css, "%s has no colour token" % band
        # The order object keys on the bare band name, and `deep` is a substring of
        # `deepest`, so this matches the key and not merely the letters.
        assert re.search(r"\b%s\s*:" % re.escape(band), order.group(1)), \
            "%s has no place in the draw order" % band
    # And nothing in the order that the data no longer carries, which would be a band
    # drawn in a position for a class that has gone.
    keys = set(re.findall(r"(\w+)\s*:", order.group(1)))
    assert keys == bands, "draw order and data disagree: %s" % (keys ^ bands)
    # every band carries the colour the map fills it with, so the palette lives in the
    # data and not in two places
    for f in depth["features"]:
        if f["properties"]["kind"] == "band":
            assert re.match(r"^#[0-9a-f]{6}$", f["properties"]["color"]), f["properties"]
        else:
            assert f["properties"]["depth_m"] in (2.0, 5.0, 10.0), f["properties"]

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


def test_an_aid_that_is_also_a_racing_mark_is_drawn_once():
    """DESIGN 12 is explicit: draw it once, and marks.json wins.

    105 of the 785 aids sit within 25 m of a mark in the register, mostly the 67
    club-owned yacht buoys, because DoT records the racing buoys too. marks.json wins
    because it carries the rounding and the course data, which the register does not.

    Verified in a browser: 680 dots drawn, which is 785 minus 105 exactly.
    """
    code = _map_code()
    draw = _function(code, "drawNavaids")
    assert "dup_mark" in draw, "the map does not know about the overlap"
    assert "return" in draw.split("dup_mark")[1][:40], \
        "a duplicated aid is not skipped"

    # and the data still carries the field on every feature, or the filter is silently a
    # no-op
    navaids = json.loads((ROOT / "config" / "navaids.json").read_text(encoding="utf-8"))
    assert all("dup_mark" in f["properties"] for f in navaids["features"]), \
        "not every aid carries dup_mark, so the filter cannot be trusted"
    dups = [f for f in navaids["features"] if f["properties"]["dup_mark"]]
    assert dups, "no aid is flagged as a duplicate, which contradicts DESIGN 12"
    # every id it names is a real mark, or the overlap was computed against something else
    marks = json.loads((ROOT / "config" / "marks.json").read_text(encoding="utf-8"))
    known = set(m["id"] for m in marks["marks"])
    for f in dups:
        assert f["properties"]["dup_mark"] in known, f["properties"]["dup_mark"]


def test_the_aid_dots_cost_one_declaration_and_not_an_attribute_each():
    """680 dots, and none of them is resized when the view changes.

    Every other symbol on this page has to be written to when the scale changes, because
    the frame is metres. These do not: an aid is a zero-length line with a round cap, and
    #chart line already carries vector-effect: non-scaling-stroke, which makes
    stroke-width mean screen pixels. So one declaration in the stylesheet holds all 680 at
    a constant size.

    This test exists because the first attempt did it the hard way and got it wrong twice
    over: it wrote stroke-width per view in user units, which the non-scaling-stroke rule
    then read as screen pixels, so 3.5 px at 14.43 m per pixel came out as fifty and the
    chart vanished under 680 blobs.
    """
    code = _map_code()
    scale = _function(code, "applyScale")
    assert "NAVAID_PX" not in code, \
        "the aid size is back in the script, where non-scaling-stroke will multiply it"
    assert 'el.navaids.setAttribute("stroke-width"' not in scale, \
        "sizing the aids per view double-applies the scale"

    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
    navaid = re.search(r"#chart \.navaid \{([^}]*)\}", css)
    assert navaid, "no navaid rule"
    assert "stroke-width" in navaid.group(1), "nothing sizes the aid dots"
    assert "stroke-linecap: round" in navaid.group(1), \
        "without a round cap a zero-length line paints nothing"
    # the rule that makes it screen pixels has to still cover line
    shapes = re.search(r"#chart path, #chart line, #chart circle \{([^}]*)\}", css)
    assert shapes and "non-scaling-stroke" in shapes.group(1), \
        "the aid dots depend on this rule covering line"

    # Still gated by zoom, which is the one thing that does need a write, and it is one.
    assert "NAVAID_MAX_MPP" in code
    assert 'el.navaids.setAttribute("display", "none")' in scale


def test_the_structures_and_aids_are_styled_by_the_kinds_the_data_carries():
    """A regenerated document that renamed a kind would draw unstyled shapes, not wrong
    ones, and nothing would raise. This notices instead.

    Every kind in each document needs a rule, and the colours are the ones DESIGN 12
    tabulates.
    """
    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")

    structures = json.loads((ROOT / "config" / "structures.json").read_text(encoding="utf-8"))
    kinds = set(f["properties"]["kind"] for f in structures["features"])
    assert kinds == {"jetty", "bridge", "groyne", "slipway", "marina", "breakwater"}, kinds
    for kind in kinds:
        assert ".structure-%s" % kind in css, "%s is drawn but not styled" % kind
        assert "--st-%s:" % kind in css, "%s has no colour token" % kind

    navaids = json.loads((ROOT / "config" / "navaids.json").read_text(encoding="utf-8"))
    aid_kinds = set(f["properties"]["kind"] for f in navaids["features"])
    for kind in aid_kinds:
        assert ".navaid-%s" % kind in css, "aid kind %s is drawn but not styled" % kind

    # IALA system A, which is what the register uses: port red, starboard green. Getting
    # these the wrong way round on a chart is worse than not drawing them.
    for theme in (r"^body \{(.*?)^\}", r"^body\.night \{(.*?)^\}"):
        block = re.search(theme, css, re.S | re.M)
        assert block, theme
        for token in ("--aid-port", "--aid-starboard", "--aid-leading"):
            assert token + ":" in block.group(1), "%s missing from %s" % (token, theme)


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


def test_labels_are_thinned_by_collision_and_not_only_by_zoom():
    """A threshold alone would leave the racing extent with no names on it at all.

    That is the view the crew uses to see the whole race area, and at it the twenty course
    marks overlap into an unreadable mat, so a rule that showed labels above some zoom and
    nothing below would trade one unusable view for another. Thresholds decide who is
    eligible; collision thins the eligible down to what fits.

    Measured in a browser at 375 wide, on leg 3 of Frostbite 3, counting real getBBox
    overlaps rather than intended ones: 10 labels fitted to the course, 18 at the racing
    extent, 0 at the coast extent, and no overlapping pair at any of them. Nothing placed
    outside the view either.
    """
    code = _map_code()
    assert "function layoutLabels" in code
    layout = _function(code, "layoutLabels")

    # Eligibility by zoom, in both directions.
    assert "LABEL_MAX_MPP" in code, "nothing stops labels at the coast extent"
    assert "LABEL_CONTEXT_MPP" in code, "context marks are never eligible"
    assert "showContext" in layout and "showAny" in layout

    # And thinning by collision on top, which is the half a threshold cannot do.
    assert "function overlaps" in code
    assert "placed.push" in layout, "nothing remembers what has already been placed"


def test_the_label_that_matters_most_never_loses_a_collision():
    """Priority is the mark being sailed to, then the rest of the course, then context.

    Ordering is what makes thinning safe: without it, which twenty of a hundred and
    thirty-one names survive would be an accident of array order, and the one the crew
    actually needs could be the one dropped.
    """
    code = _map_code()
    rank = _function(code, "rank")
    assert "targetId" in rank and "return 0" in rank, "the target is not ranked first"
    assert "sym.used ? 1 : 2" in rank, "course marks do not outrank context marks"
    assert "function targetMarkId" in code, "nothing works out which mark is the target"

    # A stable tie-break, or labels flicker between two poll ticks as equal-ranked marks
    # swap places.
    layout = _function(code, "layoutLabels")
    assert "order.sort" in layout


def test_a_blocked_label_tries_the_other_side_before_giving_up():
    """Four placements, so a name blocked on one side goes to the other rather than
    vanishing. It is also what keeps labels off the edge of the screen: an off-screen
    placement is rejected like any other collision, and measured in a browser no shown
    label falls outside the view at either zoom level."""
    code = _map_code()
    layout = _function(code, "layoutLabels")
    assert layout.count('anchor: "start"') == 2 and layout.count('anchor: "end"') == 2, \
        "fewer than four placements are tried"
    assert "bounds.left" in layout and "bounds.right" in layout, "no edge rejection"
    assert "text-anchor" in layout, "an end-anchored placement needs the attribute set"


def test_the_label_width_is_estimated_with_the_halo_modelled_separately():
    """Measured, and the first attempt was wrong.

    0.58 of the font size per character let seven pairs overlap at the racing extent. The
    real ratio runs 0.66 for a long name to 0.72 for a short one, and the spread is the
    halo: mark-label paints a 3 px stroke behind the text, a constant that is
    proportionally far larger for "Bond" than for "Bricklanding A". Folding it into the
    per-character figure cannot fit both ends, so it is modelled on its own.

    Estimated rather than measured with getBBox because measuring 131 text nodes would
    force a layout on every view change, and this page has already had to be made faster
    for the iPad once. An estimate a few pixels wide only ever costs a label that could
    have fitted.
    """
    code = _map_code()

    # Whole-token matching, not substring. Renaming LABEL_HALO_PX to LABEL_HALO_PX_UNUSED
    # left the substring in place and this test passed with the halo out of the estimate,
    # which is the same shape of hole as the guard that matched pointerdown inside a
    # comment.
    def token(name, text):
        return re.search(r"\b%s\b" % re.escape(name), text) is not None

    # 0.66 is the measured median ratio of rendered width to characters times font size.
    assert "LABEL_CHAR_W = 0.66" in code
    layout = _function(code, "layoutLabels")
    for name in ("LABEL_HALO_PX", "LABEL_AIR_PX", "LABEL_CHAR_W"):
        assert re.search(r"\bvar %s = [\d.]+;" % name, code), \
            "%s is not declared as a number" % name
        assert token(name, layout), \
            "%s is declared but never used in the layout" % name
    assert "getBBox" not in code, "measuring every label would cost a layout per view"

    # One source of truth for the halo: LABEL_HALO_PX both paints the stroke and pads the
    # estimate, so the estimate is always modelling the halo that is drawn. This used to
    # cross-check a stroke-width in the stylesheet, and that stroke-width is exactly where
    # the blur came from, so there is nothing there to disagree with any more.
    assert token("LABEL_HALO_PX", _function(code, "applyScale")), \
        "the halo the estimate models is not the halo being drawn"


def test_the_label_halo_is_sized_per_view_and_not_in_css():
    """Reported from all three devices: names go blurry as you zoom in, then disappear.

    stroke-width: 3px inside an svg is three *user units*, not three screen pixels, so the
    halo was three metres wide and fixed to the ground. Measured: 0.82 px across at the
    fitted view and growing without limit as you zoom, until it swallowed the
    eleven-pixel glyphs. Now set as an attribute on the layer against the current scale,
    the way the font size already was, and measured at exactly 3 px across a nine-fold
    zoom range.

    It cannot be a CSS declaration even as a fallback: CSS beats a presentation attribute,
    so a stroke-width here would override the value the layer inherits down. That is the
    trap this test exists to hold shut.
    """
    code = _map_code()
    scale = _function(code, "applyScale")
    assert 'setAttribute("stroke-width"' in scale, \
        "the halo is not sized against the view, so it will grow as you zoom in"
    assert "LABEL_HALO_PX" in scale

    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
    label = re.search(r"#chart \.mark-label \{(.*?)\}", css, re.S)
    assert label, "no mark-label rule"
    body = re.sub(r"/\*.*?\*/", "", label.group(1), flags=re.S)
    assert "stroke-width" not in body, \
        "a stroke-width in CSS overrides the inherited attribute and the blur comes back"

    # vector-effect would be the other way to do it, and is deliberately not used on text:
    # Safari's support for it there has never been dependable, and Safari is what the boat
    # runs. So the paths and circles use it and the labels do not.
    shapes = re.search(r"#chart path, #chart line, #chart circle \{([^}]*)\}", css)
    assert shapes and "non-scaling-stroke" in shapes.group(1)
    assert "text" not in shapes.group(1)


def test_a_label_and_its_halo_are_different_colours():
    """The other half of the same report, and the larger half.

    --ink is white because the race screen is a black screen, and --mark-halo is white
    because the chart is pale. The label used --ink, so on this page it was white text
    with a white halo over a >4 m band of #d8e9f5: a smear rather than a name. Widening
    the halo to its proper 3 px made a contrast fault that was always there impossible to
    miss.

    So the map has its own label colour, dark by day and light by night, and this asserts
    the pairing can never collapse again in either theme.
    """
    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")

    def tokens(selector):
        block = re.search(r"(?m)^%s \{(.*?)^\}" % re.escape(selector), css, re.S)
        assert block, selector
        found = {}
        for name, value in re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})", block.group(1)):
            found[name] = value.lower()
        return found

    day = tokens("body")
    night = tokens("body.night")

    label = re.search(r"#chart \.mark-label \{(.*?)\}", css, re.S).group(1)
    assert "var(--map-label)" in label, "the label does not use the map's own colour"
    assert "var(--ink)" not in label, \
        "--ink is white for the black race screen and is wrong on a pale chart"

    for theme, values in (("day", day), ("night", night)):
        assert "--map-label" in values, "no label colour for %s" % theme
        assert "--mark-halo" in values, "no halo colour for %s" % theme
        assert values["--map-label"] != values["--mark-halo"], \
            "%s: label and halo are both %s, which is a smear and not a name" % (
                theme, values["--map-label"])


def test_every_mark_carries_a_label_node():
    """Including the 111 no current course visits, because a zoom past the context
    threshold makes them eligible and making text nodes on every view change would be
    worse than keeping them. They cost nothing hidden."""
    code = _map_code()
    draw = _function(code, "drawMarks")
    assert "chars:" in draw, "the name length is not kept for the width estimate"
    # no condition on `used` around creating the label any more
    assert "if (used) {" not in draw, "only course marks get a label node"


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
