"""static/geo.js against engine/nav.py, as far as Python alone can check it.

The map and the engine have to place a point identically. The engine decides which leg the
boat is on and whether it has crossed the line; the map draws the marks, the line, the
course and the boat. If the browser's projection differs from the engine's, the boat sits
off the marks and the start line stops agreeing with the geometry the finish is detected
against, and it would look like bad mark data (DESIGN 12.1, build step 2).

The numbers themselves are compared in a browser, by static/geo-check.html against
static/geo-fixture.json, because there is no JavaScript engine here. What this file does
is guard the two ways that arrangement rots when nobody is looking:

- the fixture going stale, so the browser check passes against an old nav.py;
- the constants drifting, which is the transcription error most likely to survive review
  because a plausible-looking radius is still a radius.

Neither needs a browser, so both run in the ordinary suite on the boat.
"""

import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import nav  # noqa: E402

FIXTURE = ROOT / "static" / "geo-fixture.json"
GEO_JS = ROOT / "static" / "geo.js"


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_the_fixture_still_says_what_nav_says():
    """Recompute every value from nav.py and compare with the committed fixture.

    Without this the browser check could pass for ever against a fixture generated from a
    nav.py that has since changed: the two would agree with each other and both be wrong
    about where the boat is. Regenerate with scripts/gen_geo_fixture.py.
    """
    fix = _fixture()
    origin = fix["origin"]

    for case in fix["metres_per_degree"]:
        m_lat, m_lon = nav.metres_per_degree(case["lat"])
        assert m_lat == case["m_lat"], case["lat"]
        assert m_lon == case["m_lon"], case["lat"]

    for case in fix["enu"]:
        e, n = nav.enu(origin, {"lat": case["lat"], "lon": case["lon"]})
        assert e == case["e"], case["id"]
        assert n == case["n"], case["id"]

    for case in fix["norm180"]:
        assert nav.norm180(case["deg"]) == case["want"], case["deg"]


def test_the_fixture_covers_every_mark_and_reaches_past_the_racing_area():
    """A fixture that only samples the middle of the river proves very little.

    Every mark, because those are the things the map draws, and the corners of both
    bounding boxes, because the error in a local plane grows with distance from the
    origin and coast.json deliberately reaches far beyond the racing bbox (DESIGN 12).
    """
    fix = _fixture()
    marks = json.loads((ROOT / "config" / "marks.json").read_text(encoding="utf-8"))
    covered = set(case["id"] for case in fix["enu"])

    for mark in marks["marks"]:
        assert mark["id"] in covered, "%s is drawn but not checked" % mark["id"]

    for label in ("marks", "coast"):
        for ns in ("south", "north"):
            for ew in ("west", "east"):
                corner = "%s-bbox-%s-%s" % (label, ns, ew)
                assert corner in covered, corner

    # and the origin is the start line's inner end, which is the frame the map centres on
    lines = json.loads((ROOT / "config" / "lines.json").read_text(encoding="utf-8"))
    inner = lines["start_finish"]["inner"]
    assert fix["origin"]["lat"] == inner["lat"]
    assert fix["origin"]["lon"] == inner["lon"]


def test_the_constants_in_the_javascript_are_the_ones_in_nav():
    """A transcription check, and the one that does not need a browser.

    A wrong radius is the error most likely to survive review, because it still looks
    like a radius. The literals are compared as text against nav.py's, so a rounded copy
    or a spherical stand-in fails here rather than on the water.
    """
    source = GEO_JS.read_text(encoding="utf-8")
    py = (ROOT / "engine" / "nav.py").read_text(encoding="utf-8")

    for name in ("WGS84_A", "WGS84_F"):
        py_value = re.search(r"^%s = (.+)$" % name, py, re.M)
        assert py_value, "nav.py no longer defines %s" % name
        js_value = re.search(r"var %s = (.+);" % name, source)
        assert js_value, "geo.js does not define %s" % name
        assert js_value.group(1).strip() == py_value.group(1).strip(), (
            "%s differs: nav.py %s, geo.js %s"
            % (name, py_value.group(1), js_value.group(1)))

    # E2 is derived in both, rather than written out, so that it cannot be rounded.
    assert "WGS84_F * (2.0 - WGS84_F)" in source
    # And the two radii of curvature are both present: one spherical constant is wrong in
    # both components at once at this latitude (nav.py metres_per_degree).
    assert "Math.pow(w, 1.5)" in source, "the meridian radius is not being computed"
    assert "Math.sqrt(w)" in source, "the prime vertical is not being computed"
    assert "Math.cos" in source, "the parallel is not being scaled by latitude"


def test_the_javascript_handles_the_modulo_difference_between_the_languages():
    """The one place the transcription cannot be character for character.

    Python's % takes the sign of the divisor and JavaScript's takes the sign of the
    dividend, so a faithful-looking copy of norm180 is wrong for every negative input.
    Nothing on the Swan needs a negative angle normalised, which is exactly why this
    would sit there unnoticed.
    """
    source = GEO_JS.read_text(encoding="utf-8")
    assert "d += 360.0" in source, "no correction for JavaScript's modulo sign"

    # The fixture has to exercise it, or the correction is untested where it matters.
    negatives = [c for c in _fixture()["norm180"] if c["deg"] <= -180.0]
    assert len(negatives) >= 4, "the fixture barely exercises the negative branch"
    # and at least one case where an uncorrected copy would be a full turn out
    assert any(abs(nav.norm180(c["deg"]) - (((c["deg"] + 180.0) % 360.0) - 180.0)) < 1e-9
               for c in negatives)


def test_the_check_page_is_served_and_self_contained():
    """It is opened by URL on a device, so it has to be reachable and reference nothing
    off-box: the Pi has no internet (CLAUDE.md)."""
    page = (ROOT / "static" / "geo-check.html").read_text(encoding="utf-8")
    body = re.sub(r"<!--.*?-->", "", page, flags=re.S)
    assert "http://" not in body and "https://" not in body
    assert 'src="geo.js"' in body, "must load the file it is checking, relatively"
    assert '"geo-fixture.json"' in body, "must load the fixture, relatively"
    for absolute in ('src="/', 'href="/', '"/static/'):
        assert absolute not in body, "root-relative breaks behind the /race/ prefix"


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
