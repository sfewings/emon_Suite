"""The snail trail: what the store keeps, what /api/trail hands over, and how it is drawn.

The trail is the day's sailed track, decimated on the way in and coloured by speed on the
way out (DESIGN 12.6). Three things here would pass a casual reading and fail on the boat,
and they are what most of this file is about.

The day boundary. The Dockerfile sets TZ=UTC, so anything that asked the process what day
it was would roll the trail over at 08:00 Perth time, in the middle of a Saturday morning
sail. The offset is explicit for that reason and it is tested against a real Perth
midnight rather than against itself.

The cursor. A page left open across a restart of this process holds a `since` from before
the sequence went back to zero. Answered naively, it asks for points beyond the end for
ever and never draws another metre, which is a fault that only appears after an event
nobody reproduces by hand.

The heartbeat. The 60 s rule exists only for a boat at anchor: under way the 3 m rule fires
first every time. A test that only moves the boat would pass with that rule set to any
value at all, so it is tested standing still.

Every file in tests/ also runs standalone (CLAUDE.md).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402
import store as store_module  # noqa: E402
from engine import nav  # noqa: E402
from store import Store  # noqa: E402

DAY_START = 1_787_932_800.0
"""Local midnight in Perth on Saturday 2026-08-29, as an epoch instant. In UTC that is
2026-08-28 16:00, so the two disagree about the date for the whole Perth morning, which is
what these tests need. Held as a literal rather than computed, because zoneinfo on
python:*-slim has no tzdata and a test that skipped there would be a test that never ran
on the machine this ships to."""

UTC_MIDNIGHT = DAY_START + 8 * 3600
"""08:00 Perth on that same day: the instant a trail that trusted the container's TZ=UTC
would wrongly empty itself, which on a Saturday is on the way out to the start line."""

SAILING = DAY_START + 9 * 3600
"""09:00 Perth, mid-morning, after the wrong boundary and well before the right one."""

CLUB = {"lat": -32.0075, "lon": 115.8100}


def _store(t=SAILING):
    ticker = {"t": t}
    return Store(clock=lambda: ticker["t"]), ticker


def _at(metres_north, metres_east=0.0, origin=CLUB):
    """A position a given number of metres from the club, as a fix payload."""
    p = nav.latlon_from_enu(origin, metres_east, metres_north)
    return {"lat": p.lat, "lon": p.lon}


def _client(t=SAILING):
    ticker = {"t": t}
    store = Store(clock=lambda: ticker["t"])
    flask_app = app_module.create_app(store, app_module.load_config())
    flask_app.config["TESTING"] = True
    return flask_app.test_client(), store, ticker


def _get(client, path):
    response = client.get(path)
    assert response.status_code == 200, response.status_code
    return json.loads(response.get_data(as_text=True))


# --- what goes in ----------------------------------------------------------------------

def test_a_fix_is_kept_once_the_boat_has_moved_far_enough():
    """The distance rule, which is the one that fires under way."""
    store, ticker = _store()
    store.set("sog", 5.0)
    store.on_position(_at(0))
    # Well inside 3 m: the same point as far as the trail is concerned.
    ticker["t"] += 1.0
    store.on_position(_at(1.0))
    assert len(store.trail()["points"]) == 1, "a metre of drift is not a new point"
    # Past it.
    ticker["t"] += 1.0
    store.on_position(_at(4.0))
    assert len(store.trail()["points"]) == 2


def test_a_boat_at_anchor_leaves_a_heartbeat_and_not_a_pile():
    """The 60 s rule, tested standing still, which is the only time it fires.

    Under way the distance rule fires every second or two and this one never gets a
    chance, so a test that moved the boat would pass with the interval set to anything.
    """
    store, ticker = _store()
    store.set("sog", 0.0)
    store.on_position(CLUB)
    # An hour swinging on the mooring, a fix a second, never more than a metre off.
    for i in range(3600):
        ticker["t"] += 1.0
        store.on_position(_at(0.5 if i % 2 else -0.5))
    points = store.trail()["points"]
    # One at the start plus one a minute. Not 3601, which is what keeping every fix would
    # give, and not 720, which is what a five second heartbeat would.
    assert 55 <= len(points) <= 65, len(points)


def test_a_fix_with_no_speed_is_kept_rather_than_dropped():
    """Dropping it would draw a straight line between the fixes either side, which claims
    the boat sailed a course it did not."""
    store, ticker = _store()
    store.on_position(_at(0))          # no sog in the store at all
    ticker["t"] += 1.0
    store.set("sog", 4.0)
    store.on_position(_at(10))
    points = store.trail()["points"]
    assert len(points) == 2
    assert points[0][2] is None
    assert points[1][2] == 4.0


def test_the_trail_is_kept_on_a_cruise_with_no_course_selected():
    """The trail is a fact about the day, not about a race.

    on_position returns early when there is no race context, and appending after that
    return is the obvious mistake: it would leave the trail empty exactly when it is the
    only thing on the chart.
    """
    store, ticker = _store()
    assert store.race_state()[1] is None, "this test is meaningless with a course loaded"
    store.set("sog", 3.0)
    for i in range(5):
        ticker["t"] += 2.0
        store.on_position(_at(i * 20))
    assert len(store.trail()["points"]) == 5


def test_a_nonsense_position_is_ignored_and_does_not_break_the_trail():
    store, ticker = _store()
    for junk in (None, "here", {}, {"lat": None, "lon": 115.8},
                 {"lat": float("nan"), "lon": 115.8}, {"lat": True, "lon": 115.8}):
        ticker["t"] += 10.0
        store.on_position(junk)
    assert store.trail()["points"] == []


def test_the_trail_is_bounded():
    """Insurance against a fix source that jitters past the distance rule while moored."""
    store, ticker = _store()
    store.set("sog", 1.0)
    for i in range(store_module.TRAIL_MAX_POINTS + 500):
        ticker["t"] += 1.0
        store.on_position(_at(i * 5.0))
    assert len(store.trail()["points"]) == store_module.TRAIL_MAX_POINTS


# --- the day boundary ------------------------------------------------------------------

def test_the_day_turns_over_at_local_midnight_and_not_at_utc_midnight():
    """The whole reason TRAIL_DAY_OFFSET_S exists.

    UTC midnight falls at 08:00 Perth. A trail that rolled over there would empty itself
    on the way out to the start line.
    """
    # The fixture has to be a real local midnight or the rest of this proves nothing.
    assert (DAY_START + store_module.TRAIL_DAY_OFFSET_S) % 86400 == 0

    store, ticker = _store(t=DAY_START + 7 * 3600)     # 07:00 Perth
    store.set("sog", 4.0)
    store.on_position(_at(0))
    ticker["t"] = UTC_MIDNIGHT + 60                    # 08:01 Perth: UTC has ticked over
    store.on_position(_at(50))
    assert len(store.trail()["points"]) == 2, "the trail was cleared at UTC midnight"

    # And it does turn over at the local one.
    ticker["t"] = DAY_START + 24 * 3600 - 60           # 23:59 Perth, same day
    store.on_position(_at(100))
    assert len(store.trail()["points"]) == 3
    ticker["t"] = DAY_START + 24 * 3600 + 60           # 00:01 Perth, the next day
    store.on_position(_at(150))
    trail = store.trail()
    assert len(trail["points"]) == 1, "the trail should start again at local midnight"
    assert trail["replace"] is True


def test_the_offset_matches_western_australia():
    """+8, with no daylight saving, which is why a constant is exact and not an
    approximation. WA has observed none since the 2009 referendum."""
    assert store_module.TRAIL_DAY_OFFSET_S == 8 * 3600


# --- what comes out --------------------------------------------------------------------

def test_the_cursor_hands_over_only_the_tail():
    store, ticker = _store()
    store.set("sog", 5.0)
    for i in range(10):
        ticker["t"] += 2.0
        store.on_position(_at(i * 20))
    first = store.trail()
    assert first["replace"] is True and len(first["points"]) == 10

    second = store.trail(since=first["next"])
    assert second["replace"] is False
    assert second["points"] == [], "nothing has moved, so there is nothing to send"

    ticker["t"] += 2.0
    store.on_position(_at(1000))
    third = store.trail(since=first["next"])
    assert third["replace"] is False
    assert len(third["points"]) == 1, "only the point that arrived since"
    assert third["next"] == first["next"] + 1


def test_a_cursor_from_before_a_restart_gets_the_whole_trail_back():
    """A page left open across a restart of this process holds a `since` from a sequence
    that no longer exists. Answered naively it asks for points past the end for ever, and
    silently never draws another metre again."""
    store, ticker = _store()
    store.set("sog", 5.0)
    ticker["t"] += 2.0
    store.on_position(_at(0))
    ticker["t"] += 2.0
    store.on_position(_at(50))

    stale = store.trail(since=99999)
    assert stale["replace"] is True
    assert len(stale["points"]) == 2


def test_a_cursor_older_than_what_is_still_held_gets_the_whole_trail_back():
    """Answering with the tail alone would leave a gap in the drawn line, which reads as
    the boat having teleported."""
    store, ticker = _store()
    store.set("sog", 5.0)
    for i in range(store_module.TRAIL_MAX_POINTS + 200):
        ticker["t"] += 1.0
        store.on_position(_at(i * 5.0))
    # Sequence 1 has long since been pruned off the front.
    assert store.trail(since=1)["replace"] is True


def test_the_payload_is_rounded_to_what_can_be_seen():
    """Six decimal places is about 0.1 m, and the full repr of a float is ten figures of
    noise on the largest payload this app sends."""
    store, ticker = _store()
    store.set("sog", 4.123456789)
    store.on_position({"lat": -32.00751234567, "lon": 115.81009876543})
    point = store.trail()["points"][0]
    assert point[0] == round(-32.00751234567, 6)
    assert point[1] == round(115.81009876543, 6)
    assert point[2] == 4.1


def test_an_empty_trail_is_a_replace_and_not_an_error():
    """It is the ordinary state of the app before the first fix of the day."""
    store, _ = _store()
    trail = store.trail()
    assert trail["replace"] is True
    assert trail["points"] == []
    assert trail["next"] == 0


# --- the endpoint ----------------------------------------------------------------------

def test_the_endpoint_serves_the_trail_and_takes_a_cursor():
    client, store, ticker = _client()
    store.set("sog", 5.0)
    for i in range(4):
        ticker["t"] += 2.0
        store.on_position(_at(i * 20))

    first = _get(client, "/api/trail")
    assert first["replace"] is True and len(first["points"]) == 4

    ticker["t"] += 2.0
    store.on_position(_at(500))
    tail = _get(client, "/api/trail?since=%d" % first["next"])
    assert tail["replace"] is False and len(tail["points"]) == 1


def test_an_unusable_cursor_is_not_an_error():
    """`since` comes off a query string, so it can be anything. A 400 here would leave the
    map with no trail until the page was reloaded, and there is nothing the crew could do
    about it."""
    client, store, ticker = _client()
    store.set("sog", 5.0)
    ticker["t"] += 2.0
    store.on_position(CLUB)
    for bad in ("", "abc", "-1", "1.5", "99999999"):
        trail = _get(client, "/api/trail?since=" + bad)
        assert trail["replace"] is True, bad
        assert len(trail["points"]) == 1, bad


def test_the_trail_is_not_on_the_state_payload():
    """/api/state is one small document served to every device twice a second, and two of
    the three pages draw no trail. A day of fixes on that poll would charge them for it."""
    client, store, ticker = _client()
    store.set("sog", 5.0)
    ticker["t"] += 2.0
    store.on_position(CLUB)
    state = _get(client, "/api/state")
    assert "trail" not in state
    assert "trail" not in json.dumps(state)


# --- how it is drawn -------------------------------------------------------------------

def _map_js():
    return (ROOT / "static" / "map.js").read_text(encoding="utf-8")


def test_the_trail_is_one_path_per_band_and_not_one_per_segment():
    """A day is some 20,000 points and a line whose colour changes cannot be one element.
    Sixteen bands plus one for no-reading is a constant seventeen nodes however long the
    day; a path per segment would not survive the boat's iPad (DESIGN 12.6)."""
    js = _map_js()
    assert "buildTrailPaths" in js
    # Built from the generated palette's own length, so adding a band to gen_palette.py
    # cannot leave the drawing code disagreeing about how many there are.
    assert "Palette.BANDS.length" in js
    # One creation loop, at load, not per poll.
    assert js.count('add(el.trail, "path"') == 1


def test_runs_in_the_same_band_are_merged():
    """Speed changes slowly, so most segments continue the band before them. Appending one
    "L" rather than a fresh "M..L.." halves the coordinate pairs in the layer, and the
    chart underneath is only 16,000 of them."""
    js = _map_js()
    assert 'trailD[slot] += "L"' in js


def test_the_trail_is_polled_apart_from_the_state_and_more_slowly():
    js = _map_js()
    assert "/api/trail" in js
    match = __import__("re").search(r"TRAIL_POLL_MS\s*=\s*(\d+)", js)
    assert match, "the trail's own interval should be named"
    trail_ms = int(match.group(1))
    match = __import__("re").search(r"\bPOLL_MS\s*=\s*(\d+)", js)
    state_ms = int(match.group(1))
    assert trail_ms > state_ms, "the trail is history; the boat is what has to be live"


def test_one_trail_request_at_a_time():
    """The first response can be a whole day of points. Without this, a slow first fetch
    on the boat's wifi stacks a second and a third request behind it, and they arrive in
    an order that appends the same points twice."""
    js = _map_js()
    assert "trailBusy" in js


def test_the_palette_is_generated_and_not_hand_copied():
    """It has to agree with the colormap event_recorder draws its route maps with, which is
    what makes the same speed the same colour in both places. static/geo.js is the same
    kind of file for the same kind of reason."""
    palette = (ROOT / "static" / "palette.js").read_text(encoding="utf-8")
    assert "GENERATED by scripts/gen_palette.py" in palette
    assert (ROOT / "scripts" / "gen_palette.py").exists()
    # A fixed domain: a colour is a speed, not a rank.
    assert "MIN_KT = 0" in palette and "MAX_KT = 8" in palette
    # Sixteen bands, and every one a hex colour.
    swatches = __import__("re").findall(r'"(#[0-9a-f]{6})"', palette)
    assert len(swatches) == 17, swatches   # 16 bands plus the no-reading colour


def test_the_page_loads_the_palette_before_the_map():
    """map.js builds one path per band at load, so the palette has to be there already."""
    page = (ROOT / "templates" / "map.html").read_text(encoding="utf-8")
    # The script tags, not the bare filenames: both are named in the comments above them.
    assert (page.index('<script src="static/palette.js">')
            < page.index('<script src="static/map.js">'))


def test_the_trail_takes_its_colour_from_the_data_and_not_the_stylesheet():
    """One source of truth for what a colour means. A copy of the scale in the CSS would
    be a second, and the two would drift."""
    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
    block = css[css.index("#chart .trail"):]
    block = block[:block.index("}")]
    assert "stroke:" not in block, "the band colours come from palette.js, per path"
    assert "stroke-width" in block


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
