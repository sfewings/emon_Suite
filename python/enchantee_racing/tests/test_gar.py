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
from store import Store, derive_heel, derive_leeway  # noqa: E402

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


# --- heel --------------------------------------------------------------------------------


def _heeled(s, degrees, ts=None):
    import math
    s.set("accy", math.sin(math.radians(degrees)), ts=ts)
    s.set("accz", math.cos(math.radians(degrees)), ts=ts)


def test_heel_is_the_angle_of_the_accelerometer_in_the_y_z_plane():
    s, _ = _store()
    _heeled(s, 12.0)
    assert abs(derive_heel(s.snapshot(), T0)["v"] - 12.0) < 1e-9
    _heeled(s, -20.0)
    assert abs(derive_heel(s.snapshot(), T0)["v"] + 20.0) < 1e-9


def test_heel_ignores_pitch():
    """atan2 of y and z, not asin of y: pitching down by the bow scales y and z alike."""
    import math
    s, _ = _store()
    pitch, heel = math.radians(8.0), math.radians(15.0)
    s.set("accy", math.sin(heel) * math.cos(pitch))
    s.set("accz", math.cos(heel) * math.cos(pitch))
    assert abs(derive_heel(s.snapshot(), T0)["v"] - 15.0) < 1e-9


def test_heel_needs_both_axes_and_enough_of_gravity_in_them():
    for missing in ("accy", "accz"):
        s, _ = _store()
        s.set("accz" if missing == "accy" else "accy", 0.2)
        assert derive_heel(s.snapshot(), T0) is None, missing
    s, _ = _store()
    s.set("accy", 0.1)
    s.set("accz", 0.1)
    assert derive_heel(s.snapshot(), T0) is None, "on its end: any angle at all"


def test_heel_goes_stale_with_the_older_axis():
    s, _ = _store()
    _heeled(s, 10.0, ts=T0 - 1)
    s.set("accz", 0.98, ts=T0 - 20)
    assert derive_heel(s.snapshot(), T0)["age"] == 20.0


def test_heel_subscribes_to_the_topics_emon_mqtt_actually_publishes():
    """emon_mqtt names the axes by index, imu/0/acc/0 to 2, not x, y and z. Subscribing to
    acc/y passed every other test here and showed nothing on a replay, so the names are
    held to pyemonlib's source, which runs on the Pi without its compiled half."""
    import mqtt_client
    source = (ROOT.parent / "pyEmon" / "pyemonlib" / "emon_mqtt.py").read_text(encoding="utf-8")
    imu = re.search(r"def imuMessage\(.*?\n    def ", source, re.S)
    assert imu, "no imuMessage in emon_mqtt.py"
    assert re.search(r'for axis in range\(3\):\s*\n\s*self\.mqttClient\.publish\('
                     r'f"imu/\{payload\.subnode\}/acc/\{axis\}"', imu.group(0)), \
        "emon_mqtt no longer publishes the accelerometer as imu/<subnode>/acc/<index>"
    assert mqtt_client.TOPICS["imu/0/acc/1"] == "accy"
    assert mqtt_client.TOPICS["imu/0/acc/2"] == "accz"


def test_heel_is_positive_to_starboard_in_the_recorded_race():
    """The sign is the recording's, not the axis convention's (store.derive_heel). With the
    wind from port a boat heels to starboard, so over the Frostbite race the heel must
    lean positive on port tack and negative on starboard."""
    path = ROOT / "tests" / "data" / "20260913_Frostbite_1.TXT"
    awa, aws, port, stbd = None, 0.0, [], []
    s, _ = _store()
    with open(path, encoding="latin-1") as f:
        for line in f:
            p = line.strip().split(",")
            if len(p) < 6 or not ("13:35:00" <= p[0][11:19] <= "15:10:00"):
                continue
            if p[1] == "mwv" and p[2] == "0":
                aws, awa = float(p[3]), (float(p[4]) + 180) % 360 - 180
            elif p[1] == "imu" and awa is not None and aws > 8:   # enough wind to heel
                s.set("accy", float(p[4]), ts=T0)
                s.set("accz", float(p[5]), ts=T0)
                heel = derive_heel(s.snapshot(), T0)["v"]
                if -120 < awa < -20:
                    port.append(heel)
                elif 20 < awa < 120:
                    stbd.append(heel)
    assert len(port) > 300 and len(stbd) > 300, (len(port), len(stbd))
    median = lambda xs: sorted(xs)[len(xs) // 2]  # noqa: E731
    assert median(port) > 2, "wind from port, heeled to starboard: %.1f" % median(port)
    assert median(stbd) < -2, "wind from starboard, heeled to port: %.1f" % median(stbd)


def test_heel_is_on_api_state_and_not_on_the_hud_payload():
    s, _ = _store()
    _heeled(s, 9.0)
    client, _ = _client(s)
    state = json.loads(client.get("/api/state").get_data(as_text=True))
    assert abs(state["heel"]["v"] - 9.0) < 1e-6
    assert "heel" not in state["fields"]
    assert "now" in state, "the page keys the fading trail on the poll's clock"
    hud = json.loads(client.get("/hud/data").get_data(as_text=True))
    assert set(hud) == {"now", "motor", "fields"}


def test_the_demo_heels_to_starboard():
    import mqtt_client
    s, _ = _store()
    for topic, value in mqtt_client.demo_readings(0):
        mqtt_client.handle_message(s, topic, str(value))
    assert 5 < derive_heel(s.snapshot(), T0)["v"] < 20


def test_heel_is_a_line_across_the_dial_with_fifteen_seconds_fading_behind():
    page = _page()
    assert re.search(r'<g id="heel-line" class="heel off">', page), "shown before known"
    assert '<g id="heel-trail"' in page
    for over in ('class="hull"', 'class="inner"', 'class="box"'):
        assert page.index('id="heel-line"') < page.index(over), \
            "the heel line is drawn over the %s it is meant to pass under" % over

    code = _bare((ROOT / "static" / "gar.js").read_text(encoding="utf-8"))
    assert 'heel: new Needle("heel-line")' in code
    assert ("needles.heel.set(live(d.heel) ? d.heel.v : null, "
            "d.heel && d.heel.age > STALE_S)") in code
    assert "var HEEL_TRAIL_S = 15;" in code
    assert "paintHeelTrail(d.heel, d.now / 1000)" in code
    trail = re.search(r"function paintHeelTrail\(heel, now\) \{(.*?)\n  \}", code, re.S)
    assert trail, "no trail painter"
    body = trail.group(1)
    assert "var t = now - heel.age;" in body, "a reading must keep its time across polls"
    assert "(1 - (now - h.t) / HEEL_TRAIL_S)" in body, "the trail does not fade with age"

    css = _bare((ROOT / "static" / "app.css").read_text(encoding="utf-8"))
    for rule in (r"#gar \.heel line\s*\{", r"#gar \.heel-trail line\s*\{"):
        assert re.search(rule + r"[^}]*stroke: var\(--heel\)", css), rule
    assert re.search(r"#gar [^{]*\.heel\.stale[^{]*\{[^}]*opacity", css)


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


def test_the_wind_corners_stay_and_the_motor_joins_them():
    """The wind in the four corners always, clockwise from top left as the Garmin has
    them, and never hidden: motoring used to swap them out for the SevCon, and the crew
    wanted both (DESIGN 9.12). The SevCon readings are blocks of their own, pre-rendered
    and hidden by a class until the motor turns, the HUD's idiom (DESIGN 9.1)."""
    page = _page()
    wind = {"c-tl": "twd", "c-tr": "awa", "c-bl": "tws", "c-br": "twa"}
    for corner, reading in wind.items():
        block = re.search(r'<g class="corner" id="%s"([^>]*)>(.*?)\n        </g>' % corner,
                          page, re.S)
        assert block, corner
        assert 'id="%s"' % reading in block.group(2), (corner, reading)
        assert "data-mode" not in block.group(0), "%s is hidden while motoring" % corner

    motor = {"m-tl": "rpm", "m-tr": "cur", "m-bl": "ctrl", "m-br": "mot"}
    for block_id, reading in motor.items():
        block = re.search(r'<g class="motor-corner off" id="%s"[^>]*data-mode="motor">'
                          r'(.*?)</g>' % block_id, page, re.S)
        assert block, "%s is not a hidden motor block" % block_id
        assert 'id="%s"' % reading in block.group(1), (block_id, reading)
    assert len(re.findall(r'data-mode="', page)) == 4, "only the motor blocks swap"

    # Each layout places the motor blocks, and the swap that shows them is the HUD's flag.
    code = _bare((ROOT / "static" / "gar.js").read_text(encoding="utf-8"))
    assert len(re.findall(r"\bmotor: motorBlocks\(", code)) == 3, "a layout has no motor blocks"
    assert 'swap("data-mode", "motor", !!d.motor)' in code


def test_the_motor_blocks_clear_the_dial_when_the_phone_is_upright():
    """Upright on a phone they sit in the dial square's corners, outside the rim, where the
    room is a triangle. Worked out from the numbers in gar.js: the inner end of a value at
    its full width must be further from the dial's centre than the diamond's tip, the
    outermost thing on the dial."""
    import math
    code = _bare((ROOT / "static" / "gar.js").read_text(encoding="utf-8"))
    consts = {k: float(v) for k, v in re.findall(r"\b(DIAL|CH|M_LBL) = (\d+)[;,]", code)}
    assert set(consts) == {"DIAL", "CH", "M_LBL"}, consts
    tall = re.search(r'name: "tall".*?motor: motorBlocks\(8, DIAL - 8, CH \+ 2, '
                     r'CH \+ DIAL - 2, (\d+), (\d+)\)', code, re.S)
    assert tall, "the upright layout's motor blocks have moved; recheck this geometry"
    w, size = float(tall.group(1)), float(tall.group(2))
    r = consts["DIAL"] / 2
    tip = max(float(n) for n in re.findall(
        r"-(\d+)", re.search(r'id="mark-diamond".*?points="([^"]+)"', _page()).group(1)))
    x_inner = -r + 8 + w
    # top block: the value's baseline and its cap top; the bottom block mirrors it
    base = -r + 2 + consts["M_LBL"] + 2 + size * 0.8
    for y in (base, base - size * 0.72):
        assert math.hypot(x_inner, y) > tip + 4, \
            "a %d px motor value reaches the dial (r=%.0f)" % (size, math.hypot(x_inner, y))


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
    for node in ("lwy-line", "awa-needle", "twa-pointer", "mark-diamond"):
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


def test_leeway_is_also_a_line_on_the_dial_in_the_leeway_colour():
    """The track over the ground, out of the bow at the leeway angle (DESIGN 9.12). The
    same number as the digit in the inner circle, so the same colour and the same stale
    rule, and it goes when the server blanks leeway below a knot. Under the needles and
    the diamond, which matter more than it does."""
    code = _bare((ROOT / "static" / "gar.js").read_text(encoding="utf-8"))
    assert 'lwy: new Needle("lwy-line")' in code
    assert ("needles.lwy.set(live(d.leeway) ? d.leeway.v : null, "
            "d.leeway && d.leeway.age > STALE_S)") in code

    page = _page()
    assert page.index('id="lwy-line"') < page.index('id="awa-needle"'), \
        "the leeway line is drawn over the needles"

    css = _bare((ROOT / "static" / "app.css").read_text(encoding="utf-8"))
    digit = re.search(r"#gar \.lwy\s*\{[^}]*fill: (var\(--\w+\))", css).group(1)
    line = re.search(r"#gar \.leeway line\s*\{[^}]*stroke: (var\(--\w+\))", css).group(1)
    assert line == digit, "the line and the digit are one reading in two colours"
    for other in ("needle polygon", "pointer polygon", "diamond polygon"):
        colour = re.search(r"#gar \.%s\s*\{[^}]*fill: (var\(--\w+\))" % other, css).group(1)
        assert colour != line, "the leeway line is the colour of the %s" % other
    assert re.search(r"#gar [^{]*\.leeway\.stale[^{]*\{[^}]*opacity", css), \
        "a stale leeway line does not dim"


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
    for var in ("awa", "aws", "port", "stbd", "heel"):
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
    classes = set(re.findall(r'class="g-val (?:[cm]-val )?([a-z]+)"', page))
    assert {"rpm", "cur", "ctrl", "mot"} <= classes, "the motor readings were not found"
    for cls in classes:
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
