"""Unit tests for engine/nav.py.

The fixture is the PFSYC start/finish line from DESIGN 6: the inner start mark and
Club Buoy 32A, with the length and orientation the design brief publishes for them.
That one line exercises everything the race engine needs, because it is also the
finish line and the shape of every gate test.

Bare asserts and no fixtures anywhere in this file, so it runs under pytest and
also standalone with `python tests/test_nav.py` on a Pi that has no pytest and no
internet to install one.
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # for standalone runs
sys.path.insert(0, str(Path(__file__).resolve().parent))

import geodesic_reference  # noqa: E402
from engine import nav  # noqa: E402

# DESIGN 6, "Start / finish line". Club Buoy 32A is the outer end and also a
# mid-course mark in almost every course, which is why finish detection is the
# riskiest logic in the project and why these two points are the fixture.
INNER = nav.LatLon(-32.001948, 115.812006)  # user-supplied-2026, worth re-surveying
CLUB_32A = nav.LatLon(-32.002750, 115.812812)  # ywa-srrc-2019

# The figures DESIGN 6 and config/lines.json publish for that line.
DESIGN_LENGTH_M = 117.3
DESIGN_LENGTH_NM = 0.063
DESIGN_BEARING = 139.6
DESIGN_RECIPROCAL = 319.6

# The racing-area bounding box (DESIGN 12), used to check the plane model over the
# full extent rather than only over a 117 m line.
BBOX_SOUTH, BBOX_WEST, BBOX_NORTH, BBOX_EAST = -32.030346, 115.748, -31.959052, 115.856573
BBOX_POINTS = [
    nav.LatLon(BBOX_SOUTH, BBOX_WEST),
    nav.LatLon(BBOX_SOUTH, BBOX_EAST),
    nav.LatLon(BBOX_NORTH, BBOX_WEST),
    nav.LatLon(BBOX_NORTH, BBOX_EAST),
    nav.LatLon((BBOX_SOUTH + BBOX_NORTH) / 2, (BBOX_WEST + BBOX_EAST) / 2),
    INNER,
    CLUB_32A,
]


# --- scale factors ----------------------------------------------------------


def test_metres_per_degree_on_wgs84():
    m_lat, m_lon = nav.metres_per_degree(-32.0)
    assert abs(m_lat - 110886.81) < 0.1, m_lat
    assert abs(m_lon - 94493.14) < 0.1, m_lon


def test_metres_per_degree_at_the_equator():
    m_lat, m_lon = nav.metres_per_degree(0.0)
    assert abs(m_lon - 111319.49) < 0.1, m_lon  # semi-major axis, one degree
    assert abs(m_lat - 110574.28) < 0.1, m_lat  # the published 110.574 km


def test_meridian_scale_grows_toward_the_pole():
    """A single spherical constant cannot be right at two latitudes at once."""
    assert nav.metres_per_degree(0.0)[0] < nav.metres_per_degree(-32.0)[0]
    assert nav.metres_per_degree(-32.0)[0] < nav.metres_per_degree(-60.0)[0]
    assert nav.metres_per_degree(-32.0)[1] < nav.metres_per_degree(0.0)[1]


# --- the DESIGN 6 fixture ---------------------------------------------------


def test_start_line_length_against_design():
    """117.3 m, within the 0.2 m the design's spherical model costs.

    See test_design_figures_come_from_a_spherical_model: the published figure is
    long by 0.22 m, so this asserts agreement to the model difference and the
    geodesic test below pins the exact value.
    """
    length = nav.distance_m(INNER, CLUB_32A)
    assert abs(length - DESIGN_LENGTH_M) < 0.3, length
    assert abs(nav.distance_nm(INNER, CLUB_32A) - DESIGN_LENGTH_NM) < 0.001


def test_start_line_bearing_against_design():
    """139.6 / 319.6 true, within the 0.14 degrees the design's model costs."""
    out = nav.bearing(INNER, CLUB_32A)
    back = nav.bearing(CLUB_32A, INNER)
    assert abs(nav.norm180(out - DESIGN_BEARING)) < 0.25, out
    assert abs(nav.norm180(back - DESIGN_RECIPROCAL)) < 0.25, back


def test_start_line_against_the_geodesic():
    """The same line, solved independently on the ellipsoid.

    This is the assertion that actually pins nav.py. DESIGN 6 offers the register's
    MGA94 grid columns for this job, but they were not carried into
    config/marks.json and the inner start mark is not in the register at all, so
    the Vincenty reference stands in.
    """
    truth_m, truth_deg = geodesic_reference.vincenty_inverse(INNER, CLUB_32A)
    assert abs(truth_m - 117.086) < 0.01, truth_m  # guards the reference itself
    assert abs(nav.distance_m(INNER, CLUB_32A) - truth_m) < 0.001
    assert abs(nav.norm180(nav.bearing(INNER, CLUB_32A) - truth_deg)) < 0.01


def test_design_figures_come_from_a_spherical_model():
    """Why the two tests above carry a tolerance instead of asserting equality.

    scripts/gen_lines.py used a flat 111320 m/degree sphere, so config/lines.json
    and DESIGN 6 both read 0.22 m long and 0.14 degrees off on this line. Nothing
    at the helm cares, but a future reader comparing nav.py against the design
    brief should find the discrepancy explained rather than have to rediscover it.
    """
    lat0 = math.radians((INNER.lat + CLUB_32A.lat) / 2.0)
    dn = (CLUB_32A.lat - INNER.lat) * 111320.0
    de = (CLUB_32A.lon - INNER.lon) * 111320.0 * math.cos(lat0)
    spherical_m = math.hypot(de, dn)
    spherical_deg = math.degrees(math.atan2(de, dn)) % 360.0

    assert abs(spherical_m - DESIGN_LENGTH_M) < 0.05, spherical_m
    assert abs(nav.norm180(spherical_deg - DESIGN_BEARING)) < 0.05, spherical_deg

    truth_m, truth_deg = geodesic_reference.vincenty_inverse(INNER, CLUB_32A)
    assert 0.15 < spherical_m - truth_m < 0.30
    assert 0.10 < nav.norm180(spherical_deg - truth_deg) < 0.20


def test_plane_model_holds_across_the_racing_area():
    """Distance and bearing anywhere in the bbox, against the geodesic.

    The bbox diagonal is 13 km. Worst case here is under a millimetre of distance
    and 0.03 degrees of bearing, the latter being the difference between a
    geodesic's initial azimuth and the plane's mean azimuth. Both are an order of
    magnitude inside the 0.6 degree MGA grid convergence DESIGN 6 warns about.
    """
    for a in BBOX_POINTS:
        for b in BBOX_POINTS:
            if a == b:
                continue
            truth_m, truth_deg = geodesic_reference.vincenty_inverse(a, b)
            assert abs(nav.distance_m(a, b) - truth_m) < 0.01, (a, b, truth_m)
            assert abs(nav.norm180(nav.bearing(a, b) - truth_deg)) < 0.05, (a, b, truth_deg)


# --- angle conventions ------------------------------------------------------


def test_norm360():
    for given, expected in [(0, 0), (359.9, 359.9), (360, 0), (361, 1), (-1, 359), (-361, 359), (720, 0)]:
        assert abs(nav.norm360(given) - expected) < 1e-9, given


def test_norm180_is_port_negative():
    for given, expected in [
        (0, 0),
        (90, 90),
        (-90, -90),
        (179, 179),
        (181, -179),
        (190, -170),
        (-190, 170),
        (359, -1),
        (360, 0),
        (180, 180),
        (-180, 180),
        (540, 180),
    ]:
        assert abs(nav.norm180(given) - expected) < 1e-9, given


def test_relative_bearing_matches_the_hud_convention():
    """Starboard positive, port negative, same as TWA and AWA (DESIGN 9.3)."""
    assert abs(nav.relative_bearing(139.6, 90.0) - 49.6) < 1e-9  # mark to starboard
    assert abs(nav.relative_bearing(139.6, 200.0) - -60.4) < 1e-9  # mark to port
    assert abs(nav.relative_bearing(10.0, 350.0) - 20.0) < 1e-9  # across north
    assert abs(nav.relative_bearing(350.0, 10.0) - -20.0) < 1e-9


def test_bearing_to_the_mark_from_the_boats_own_position():
    """The pair of numbers the race screen shows: true bearing and the delta."""
    true_bearing = nav.bearing(INNER, CLUB_32A)
    heading = 180.0
    assert abs(nav.relative_bearing(true_bearing, heading) - (true_bearing - 180.0)) < 1e-9
    assert nav.relative_bearing(true_bearing, heading) < 0  # 139 degrees is to port of 180


# --- distance and bearing ---------------------------------------------------


def test_distance_to_self_is_zero():
    assert nav.distance_m(INNER, INNER) == 0.0
    assert nav.distance_m(CLUB_32A, dict(lat=CLUB_32A.lat, lon=CLUB_32A.lon)) == 0.0


def test_distance_is_symmetric():
    assert nav.distance_m(INNER, CLUB_32A) == nav.distance_m(CLUB_32A, INNER)


def test_bearings_are_reciprocal():
    out = nav.bearing(INNER, CLUB_32A)
    back = nav.bearing(CLUB_32A, INNER)
    assert abs(abs(nav.norm180(out - back)) - 180.0) < 1e-9


def test_bearing_cardinals():
    origin = nav.LatLon(-32.0, 115.8)
    assert abs(nav.bearing(origin, nav.LatLon(-31.99, 115.8)) - 0.0) < 1e-9  # north
    assert abs(nav.bearing(origin, nav.LatLon(-32.0, 115.81)) - 90.0) < 1e-9  # east
    assert abs(nav.bearing(origin, nav.LatLon(-32.01, 115.8)) - 180.0) < 1e-9  # south
    assert abs(nav.bearing(origin, nav.LatLon(-32.0, 115.79)) - 270.0) < 1e-9  # west


def test_as_latlon_accepts_config_and_mqtt_shapes():
    """config/*.json gives dicts, gps/position/0 gives a dict, tests give tuples."""
    assert nav.as_latlon({"lat": -32.0, "lon": 115.8}) == nav.LatLon(-32.0, 115.8)
    assert nav.as_latlon({"lat": -32.0, "lon": 115.8, "ts": 1755500000}) == nav.LatLon(-32.0, 115.8)
    assert nav.as_latlon((-32.0, 115.8)) == nav.LatLon(-32.0, 115.8)
    assert nav.as_latlon(nav.LatLon(-32.0, 115.8)) == nav.LatLon(-32.0, 115.8)
    assert nav.distance_m({"lat": INNER.lat, "lon": INNER.lon}, CLUB_32A) == nav.distance_m(INNER, CLUB_32A)


# --- the local plane --------------------------------------------------------


def test_enu_axes():
    north = nav.enu(INNER, nav.LatLon(INNER.lat + 0.001, INNER.lon))
    east = nav.enu(INNER, nav.LatLon(INNER.lat, INNER.lon + 0.001))
    assert abs(north.e) < 1e-9 and north.n > 100.0
    assert abs(east.n) < 1e-9 and east.e > 90.0
    assert nav.enu(INNER, INNER) == nav.ENU(0.0, 0.0)


def test_enu_magnitude_matches_distance():
    """The plane and the pairwise helpers agree to well under a millimetre."""
    e, n = nav.enu(INNER, CLUB_32A)
    assert abs(math.hypot(e, n) - nav.distance_m(INNER, CLUB_32A)) < 0.001


def test_enu_round_trip():
    for point in BBOX_POINTS:
        e, n = nav.enu(INNER, point)
        back = nav.latlon_from_enu(INNER, e, n)
        assert abs(back.lat - point.lat) < 1e-12, point
        assert abs(back.lon - point.lon) < 1e-12, point


def test_destination_inverts_bearing_and_distance():
    for brg in [0, 45, 90, 139.6, 180, 225, 270, 319.6, 359]:
        for metres in [10.0, 117.3, 1000.0, 4000.0]:
            there = nav.destination(INNER, brg, metres)
            assert abs(nav.distance_m(INNER, there) - metres) < 0.01, (brg, metres)
            assert abs(nav.norm180(nav.bearing(INNER, there) - brg)) < 0.001, (brg, metres)


def test_midpoint_is_the_gate_target():
    """A gate leg targets the midpoint, not either mark (DESIGN 11.3)."""
    mid = nav.midpoint(INNER, CLUB_32A)
    half = nav.distance_m(INNER, CLUB_32A) / 2.0
    assert abs(nav.distance_m(INNER, mid) - half) < 0.001
    assert abs(nav.distance_m(CLUB_32A, mid) - half) < 0.001


# --- projection onto a line -------------------------------------------------


def test_project_at_the_line_ends():
    at_inner = nav.project(INNER, CLUB_32A, INNER)
    at_outer = nav.project(INNER, CLUB_32A, CLUB_32A)
    assert abs(at_inner.t) < 1e-12 and abs(at_inner.offset_m) < 1e-9
    assert abs(at_outer.t - 1.0) < 1e-12 and abs(at_outer.offset_m) < 1e-9
    assert abs(at_inner.length_m - nav.distance_m(INNER, CLUB_32A)) < 0.001


def test_project_at_the_middle_of_the_line():
    pr = nav.project(INNER, CLUB_32A, nav.midpoint(INNER, CLUB_32A))
    assert abs(pr.t - 0.5) < 1e-6, pr.t
    assert pr.distance_m < 0.001


def test_offset_is_positive_to_the_left_of_the_line():
    line_bearing = nav.bearing(INNER, CLUB_32A)
    mid = nav.midpoint(INNER, CLUB_32A)
    left = nav.destination(mid, line_bearing - 90.0, 50.0)
    right = nav.destination(mid, line_bearing + 90.0, 50.0)

    assert abs(nav.project(INNER, CLUB_32A, left).offset_m - 50.0) < 0.05
    assert abs(nav.project(INNER, CLUB_32A, right).offset_m + 50.0) < 0.05
    assert nav.side(INNER, CLUB_32A, left) == 1
    assert nav.side(INNER, CLUB_32A, right) == -1
    # Reversing the line reverses the sign, which is why the engine records the
    # side it saw rather than assuming one.
    assert nav.side(CLUB_32A, INNER, left) == -1


def test_side_tolerance_treats_a_near_miss_as_on_the_line():
    line_bearing = nav.bearing(INNER, CLUB_32A)
    just_off = nav.destination(nav.midpoint(INNER, CLUB_32A), line_bearing + 90.0, 0.5)
    assert nav.side(INNER, CLUB_32A, just_off) == -1
    assert nav.side(INNER, CLUB_32A, just_off, tolerance_m=1.0) == 0


def test_distance_to_line_clamps_past_the_ends():
    """Outside the pin, the useful number is the distance to the pin (DESIGN 10)."""
    line_bearing = nav.bearing(INNER, CLUB_32A)
    beyond = nav.destination(CLUB_32A, line_bearing, 100.0)
    pr = nav.project(INNER, CLUB_32A, beyond)
    assert pr.t > 1.0
    assert pr.distance_m < 0.01  # on the infinite line, just not on the segment
    assert abs(nav.distance_to_line_m(INNER, CLUB_32A, beyond) - 100.0) < 0.01

    before = nav.destination(INNER, line_bearing + 180.0, 30.0)
    assert nav.project(INNER, CLUB_32A, before).t < 0.0
    assert abs(nav.distance_to_line_m(INNER, CLUB_32A, before) - 30.0) < 0.01

    abeam = nav.destination(nav.midpoint(INNER, CLUB_32A), line_bearing + 90.0, 40.0)
    assert abs(nav.distance_to_line_m(INNER, CLUB_32A, abeam) - 40.0) < 0.01


def test_project_rejects_a_zero_length_line():
    try:
        nav.project(INNER, INNER, CLUB_32A)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for coincident line ends")


# --- line crossing ----------------------------------------------------------


def _across(line_a, line_b, at, offset_m=30.0):
    """A two-fix track crossing the line square on, `at` metres along it."""
    line_bearing = nav.bearing(line_a, line_b)
    point = nav.destination(line_a, line_bearing, at)
    return (
        nav.destination(point, line_bearing - 90.0, offset_m),
        nav.destination(point, line_bearing + 90.0, offset_m),
    )


def test_crossing_through_the_middle_of_the_line():
    length = nav.distance_m(INNER, CLUB_32A)
    previous, current = _across(INNER, CLUB_32A, length / 2.0)
    x = nav.crossing(INNER, CLUB_32A, previous, current)
    assert x is not None
    assert abs(x.t - 0.5) < 0.001, x.t
    assert abs(x.u - 0.5) < 0.001, x.u
    assert (x.from_side, x.to_side) == (1, -1)
    assert nav.distance_m(x.at, nav.midpoint(INNER, CLUB_32A)) < 0.05


def test_crossing_reports_where_along_the_line_it_happened():
    """An oblique track: the crossing point is interpolated, not snapped to a fix."""
    length = nav.distance_m(INNER, CLUB_32A)
    line_bearing = nav.bearing(INNER, CLUB_32A)
    previous = nav.destination(nav.destination(INNER, line_bearing, 0.2 * length), line_bearing - 90.0, 20.0)
    current = nav.destination(nav.destination(INNER, line_bearing, 0.8 * length), line_bearing + 90.0, 20.0)
    x = nav.crossing(INNER, CLUB_32A, previous, current)
    assert x is not None
    assert abs(x.t - 0.5) < 0.005, x.t


def test_no_crossing_when_both_fixes_are_the_same_side():
    line_bearing = nav.bearing(INNER, CLUB_32A)
    mid = nav.midpoint(INNER, CLUB_32A)
    a = nav.destination(mid, line_bearing - 90.0, 60.0)
    b = nav.destination(mid, line_bearing - 90.0, 20.0)
    assert nav.crossing(INNER, CLUB_32A, a, b) is None
    assert nav.crossing(INNER, CLUB_32A, b, a) is None


def test_a_track_parallel_to_the_line_never_crosses():
    line_bearing = nav.bearing(INNER, CLUB_32A)
    previous = nav.destination(INNER, line_bearing - 90.0, 25.0)
    current = nav.destination(CLUB_32A, line_bearing - 90.0, 25.0)
    assert nav.crossing(INNER, CLUB_32A, previous, current) is None


def test_crossing_outside_the_pin_end_is_not_a_crossing():
    """The whole reason for the [0, 1] parameter test.

    Sailing round the outside of Club Buoy 32A, on the way to Squadron, crosses the
    infinite line through the two ends but not the 117 m segment between them. If
    this ever returned a crossing, the finish would fire mid-race (DESIGN 11.5) and
    a boat passing outside a gate mark would complete the gate (DESIGN 11.3).
    """
    length = nav.distance_m(INNER, CLUB_32A)
    for at in [length + 5.0, length + 60.0, length + 500.0, -5.0, -60.0]:
        previous, current = _across(INNER, CLUB_32A, at)
        assert nav.crossing(INNER, CLUB_32A, previous, current) is None, at
        assert nav.crossing(INNER, CLUB_32A, current, previous) is None, at


def test_crossing_just_inside_an_end_still_counts():
    length = nav.distance_m(INNER, CLUB_32A)
    for at, expected_t in [(1.0, 1.0 / length), (length - 1.0, 1.0 - 1.0 / length)]:
        previous, current = _across(INNER, CLUB_32A, at)
        x = nav.crossing(INNER, CLUB_32A, previous, current)
        assert x is not None, at
        assert abs(x.t - expected_t) < 0.001, (at, x.t)


def test_crossing_direction_is_reported_both_ways():
    length = nav.distance_m(INNER, CLUB_32A)
    previous, current = _across(INNER, CLUB_32A, length / 2.0)
    there = nav.crossing(INNER, CLUB_32A, previous, current)
    back = nav.crossing(INNER, CLUB_32A, current, previous)
    assert (there.from_side, there.to_side) == (1, -1)
    assert (back.from_side, back.to_side) == (-1, 1)
    assert nav.distance_m(there.at, back.at) < 0.001


def test_a_fix_exactly_on_the_line_does_not_hide_the_crossing():
    """Exactly zero offset resolves to the +1 side, so nothing is lost.

    Built on a meridian line so the longitude difference is exactly zero and the
    offset is exactly 0.0 rather than a few femtometres of float noise.
    """
    a = nav.LatLon(-32.0, 115.8)
    b = nav.LatLon(-31.99, 115.8)
    on_line = nav.LatLon(-31.995, 115.8)
    west = nav.LatLon(-31.995, 115.7995)  # left of a -> b
    east = nav.LatLon(-31.995, 115.8005)  # right of a -> b

    assert nav.project(a, b, on_line).offset_m == 0.0
    assert nav.side(a, b, on_line) == 0
    assert nav.side(a, b, west) == 1 and nav.side(a, b, east) == -1

    # Sitting on the line produces no crossings.
    assert nav.crossing(a, b, on_line, on_line) is None
    # Arriving at the line is not yet a crossing; leaving it on the far side is.
    assert nav.crossing(a, b, west, on_line) is None
    leaving = nav.crossing(a, b, on_line, east)
    assert leaving is not None and abs(leaving.u) < 1e-12
    assert abs(leaving.t - 0.5) < 1e-6
    # And from the other side the crossing lands on the on-line fix itself.
    arriving = nav.crossing(a, b, east, on_line)
    assert arriving is not None and abs(arriving.u - 1.0) < 1e-12


def test_crossing_rejects_a_zero_length_line():
    try:
        nav.crossing(INNER, INNER, INNER, CLUB_32A)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for coincident line ends")


if __name__ == "__main__":
    # Standalone runner for a Pi with no pytest. Every test above is a bare
    # assert with no fixtures, so pytest is a convenience, not a dependency.
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
