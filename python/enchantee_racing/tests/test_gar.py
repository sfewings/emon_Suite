"""GAR, the wind dial laid out as the boat's Garmin GMI 20 lays it out (DESIGN 9.12).

Two halves. The leeway reading is server state, derived in store.py like TWA, and is
tested the same way, from a fake clock. The page itself is checked here for what can be
checked from Python, which is mostly the rules that reached the boat once on another page
and are pinned for every page since: nothing off-box, relative URLs, an SVG with a size,
the wake-lock video, both row sets pre-rendered. How it looks is checked by eye on a phone.

The cross-page rules, the navigation, the manifest and navigating by script, live with the
other pages' in test_race_screen.py, which GAR has been added to.

Bare asserts and no fixtures, so this runs under pytest and standalone with
`python tests/test_gar.py`, which is the only way to run it on the Pi.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # for standalone runs

import app as app_module  # noqa: E402
import store as store_module  # noqa: E402
from store import Store, derive_leeway  # noqa: E402

T0 = 1_755_500_000.0


def _store(now=T0):
    clock = {"t": now}
    return Store(clock=lambda: clock["t"]), clock


def _client(store=None):
    store = store or Store()
    flask_app = app_module.create_app(store)
    flask_app.config["TESTING"] = True
    return flask_app.test_client(), store


def _page():
    return _client()[0].get("/gar").get_data(as_text=True)


def _bare(text):
    """Markup or code with its comments taken out, so prose naming a thing is not mistaken
    for the thing."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


# --- leeway ------------------------------------------------------------------------------


def _moving(s, cog, hdg, sog=5.0, ts=None):
    s.set("cog", cog, ts=ts)
    s.set("hdg", hdg, ts=ts)
    s.set("sog", sog, ts=ts)


def test_leeway_is_cog_minus_heading_signed_port_negative():
    s, _ = _store()
    _moving(s, cog=95.0, hdg=90.0)
    assert derive_leeway(s.snapshot(), T0)["v"] == 5.0      # set to starboard
    _moving(s, cog=85.0, hdg=90.0)
    assert derive_leeway(s.snapshot(), T0)["v"] == -5.0     # and to port


def test_leeway_is_normalised_across_north():
    s, _ = _store()
    _moving(s, cog=2.0, hdg=355.0)
    assert derive_leeway(s.snapshot(), T0)["v"] == 7.0
    _moving(s, cog=355.0, hdg=2.0)
    assert derive_leeway(s.snapshot(), T0)["v"] == -7.0


def test_leeway_is_blank_below_a_knot_where_cog_is_noise():
    s, _ = _store()
    _moving(s, cog=200.0, hdg=90.0, sog=store_module.LEEWAY_MIN_SOG_KT - 0.1)
    assert derive_leeway(s.snapshot(), T0) is None
    _moving(s, cog=95.0, hdg=90.0, sog=store_module.LEEWAY_MIN_SOG_KT)
    assert derive_leeway(s.snapshot(), T0)["v"] == 5.0


def test_leeway_needs_all_three_inputs():
    for missing in ("cog", "hdg", "sog"):
        s, _ = _store()
        for key, value in (("cog", 95.0), ("hdg", 90.0), ("sog", 5.0)):
            if key != missing:
                s.set(key, value)
        assert derive_leeway(s.snapshot(), T0) is None, missing


def test_leeway_goes_stale_with_its_oldest_input():
    s, _ = _store()
    _moving(s, cog=95.0, hdg=90.0, ts=T0 - 2)
    s.set("hdg", 90.0, ts=T0 - 20)
    leeway = derive_leeway(s.snapshot(), T0)
    assert leeway["age"] == 20.0
    assert leeway["age"] > store_module.STALE_S   # so the page dims it


def test_leeway_is_on_api_state_and_not_on_the_hud_payload():
    s, _ = _store()
    _moving(s, cog=95.0, hdg=90.0)
    client, _ = _client(s)
    state = json.loads(client.get("/api/state").get_data(as_text=True))
    assert state["leeway"]["v"] == 5.0
    assert "leeway" not in state["fields"], "not one of FIELDS, which /hud/data mirrors"
    hud = json.loads(client.get("/hud/data").get_data(as_text=True))
    assert set(hud) == {"now", "motor", "fields"}, "/hud/data keeps its ported shape"


# --- the page ----------------------------------------------------------------------------


def test_the_page_is_served():
    client, _ = _client()
    response = client.get("/gar")
    assert response.status_code == 200
    assert "<title>Enchantee GAR</title>" in response.get_data(as_text=True)


def test_the_page_references_nothing_off_box_and_everything_relatively():
    body = _bare(_page())
    # The svg namespace is a name, never fetched.
    body = body.replace('xmlns="http://www.w3.org/2000/svg"', "")
    assert "http://" not in body and "https://" not in body
    for attr, target in re.findall(r'\b(href|src)="([^"]+)"', body):
        assert "://" not in target and not target.startswith("/"), \
            "%s=%r breaks behind the /race/ prefix or leaves the box" % (attr, target)
    for needed in ('href="static/app.css"', 'src="static/viewport.js"',
                   'src="static/theme.js"', 'src="static/gar.js"', 'src="static/wake.mp4"'):
        assert needed in body, needed

    script = (ROOT / "static" / "gar.js").read_text(encoding="utf-8")
    code = _bare(script).replace('"http://www.w3.org/2000/svg"', "")
    assert "http" not in code, "gar.js names a host"
    for url in re.findall(r"fetch\((.*?)[,)]", code):
        assert url.startswith("base +"), url
    assert 'location.pathname.replace(/\\/[^\\/]*$/, "")' in code


def test_viewport_js_is_loaded_before_the_app():
    page = _page()
    assert page.index("static/viewport.js") < page.index('<div id="app">')


def test_the_svg_has_a_size_and_not_only_a_viewbox():
    """iOS 12 resolves an svg with a viewBox and no size as 300 px wide (CLAUDE.md)."""
    svg = re.search(r'<svg id="gar"[^>]*>', _page())
    assert svg, "no dial"
    for attr in ("width", "height", "viewBox"):
        assert re.search(r'\b%s="[^"]+"' % attr, svg.group(0)), attr
    # and the script keeps writing a pixel size as attributes when it lays the page out
    code = _bare((ROOT / "static" / "gar.js").read_text(encoding="utf-8"))
    assert 'svg.setAttribute("width"' in code and 'svg.setAttribute("height"' in code


def test_the_screen_is_kept_awake():
    page = _page()
    assert re.search(r'<video id="wake"[^>]*\bmuted\b[^>]*\bloop\b[^>]*\bplaysinline\b', page)
    code = _bare((ROOT / "static" / "gar.js").read_text(encoding="utf-8"))
    assert "wake.play()" in code
    assert 'addEventListener("click", keepAwake)' in code, \
        "the video has to be started from a gesture or it never plays"


def test_both_corner_sets_are_pre_rendered_and_the_wind_is_on_show():
    """The motor swap is the HUD's: both sets in the markup, one hidden by a class
    (DESIGN 9.1). Clockwise from top left, as the Garmin has them."""
    page = _page()
    want = {"c-tl": ("twd", "rpm"), "c-tr": ("awa", "cur"),
            "c-bl": ("tws", "ctrl"), "c-br": ("twa", "mot")}
    for corner, (sail, motor) in want.items():
        block = re.search(r'<g class="corner" id="%s"[^>]*>(.*?)\n        </g>' % corner,
                          page, re.S)
        assert block, corner
        body = block.group(1)
        assert re.search(r'<g data-mode="sail">.*id="%s"' % sail, body), (corner, sail)
        assert re.search(r'<g data-mode="motor" class="off">.*id="%s"' % motor, body), \
            (corner, motor)


def test_the_band_shows_sog_until_the_race_and_the_mark_during_it():
    page = _page()
    band = re.search(r'<g id="band">(.*?)\n        </g>\n      </svg>', page, re.S)
    assert band, "no band"
    body = band.group(1)
    idle = re.search(r'<g data-race="off">(.*?)</g>', body, re.S)
    racing = re.search(r'<g data-race="on" class="off">(.*)', body, re.S)
    assert idle and 'id="b-sog"' in idle.group(1)
    assert racing
    for needed in ("r-mark", "r-sog", "r-dist", "r-dist-lbl", "r-brg"):
        assert 'id="%s"' % needed in racing.group(1), needed


def test_the_dial_carries_the_needle_the_pointer_and_the_mark_hidden_until_known():
    page = _page()
    for node in ("awa-needle", "twa-pointer", "mark-diamond"):
        assert re.search(r'<g id="%s" class="[a-z]+ off">' % node, page), node
    for reading in ("lwy", "aws"):
        assert 'id="%s"' % reading in page, reading


def test_every_relative_angle_is_signed_and_nothing_says_magnetic():
    """The crew's choice over the Garmin's S/P suffix and its M (DESIGN 9.12)."""
    code = _bare((ROOT / "static" / "gar.js").read_text(encoding="utf-8"))
    for key in ("awa", "twa"):
        assert re.search(r"\b%s: fmtSigned" % key, code), key
    assert 'reading($("lwy"), d.leeway, fmtSigned' in code
    page = _bare(_page())
    labels = re.findall(r'class="g-lbl[^"]*">([^<]*)<', page)
    assert labels, "no labels found"
    for label in labels:
        assert not re.search(r"\b[MT]\b", label), "label %r says true or magnetic" % label


def test_the_mark_is_placed_off_the_heading_and_blanks_with_the_fix():
    """Off the heading, because the wind on this dial is: the mark then sits from the TWA
    pointer by exactly the angle the leg type is computed from. And gone, not dimmed,
    when the fix is (DESIGN 9.5)."""
    code = _bare((ROOT / "static" / "gar.js").read_text(encoding="utf-8"))
    assert "norm180(nav.bearing - hdg.v)" in code
    assert "var nav = (racing && r.nav) || null;" in code
    assert "needles.mark.set(markAngle, false)" in code


def test_the_needles_take_the_short_way_round():
    code = _bare((ROOT / "static" / "gar.js").read_text(encoding="utf-8"))
    step = re.search(r"Needle\.prototype\.step = function \(\) \{(.*?)\n  \};", code, re.S)
    assert step, "no easing step"
    assert "norm180(this.target - this.at)" in step.group(1), \
        "a needle crossing the stern would swing the long way, through the bow"


def test_the_theme_comes_from_the_poll():
    code = _bare((ROOT / "static" / "gar.js").read_text(encoding="utf-8"))
    assert "window.Theme.apply(d.theme)" in code


def test_every_gar_colour_has_a_night_value_and_it_is_red():
    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
    day = re.search(r":root \{(.*?)\n\}", css, re.S).group(1)
    night = re.search(r"body\.night \{(.*?)\n\}", css, re.S).group(1)
    for var in ("awa", "aws", "port", "stbd"):
        assert re.search(r"--%s:\s*#" % var, day), "--%s has no day value" % var
        value = re.search(r"--%s:\s*(#[0-9a-fA-F]{6})" % var, night)
        assert value, "--%s has no night value" % var
        r, g, b = (int(value.group(1)[i:i + 2], 16) for i in (1, 3, 5))
        assert r >= 1.5 * g and r >= 1.5 * b, "--%s is not a red at night" % var
    port = re.search(r"--port:\s*(#\w+)", night).group(1)
    stbd = re.search(r"--stbd:\s*(#\w+)", night).group(1)
    assert port != stbd, "the two sectors merge at night"

    # The apparent wind keeps the HUD's colours, day and night.
    hud = (ROOT / "templates" / "hud.html").read_text(encoding="utf-8")
    hud_night = re.search(r"body\.night \{(.*?)\}", hud, re.S).group(1)
    for var in ("awa", "aws"):
        for app_block, hud_block in ((day, hud), (night, hud_night)):
            want = re.search(r"--%s:\s*(#[0-9a-fA-F]{6})" % var, hud_block).group(1)
            got = re.search(r"--%s:\s*(#[0-9a-fA-F]{6})" % var, app_block).group(1)
            assert got.lower() == want.lower(), (var, got, want)


def test_every_reading_class_on_the_page_has_a_colour():
    page = _bare(_page())
    css = _bare((ROOT / "static" / "app.css").read_text(encoding="utf-8"))
    for cls in set(re.findall(r'class="g-val (?:c-val )?([a-z]+)"', page)):
        assert re.search(r"#gar [^{]*\.%s\b[^{]*\{[^}]*fill: var\(--" % cls, css), \
            ".%s has no colour" % cls


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
