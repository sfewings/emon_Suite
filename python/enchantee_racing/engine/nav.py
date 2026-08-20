"""Navigation geometry: ENU projection, distance, bearing, line crossing.

Pure functions. No I/O, no state, no clock, no config. Everything here is a
function of positions and angles, which is what lets engine/race.py be replayed
against recorded GPS tracks (CLAUDE.md, DESIGN 2 and 11).

Model
-----
Positions are WGS84 decimal degrees. Geometry is computed on a local east/north
tangent plane rather than on the ellipsoid. The racing area is a 10.25 by 7.94 km
box on the Swan River (the `bbox` in config/marks.json), where a plane is accurate
enough and, more usefully, linear: line crossing needs a coordinate system in
which a straight line is straight.

Scale comes from the WGS84 meridian and prime-vertical radii of curvature at the
latitude in question, not from one spherical metres-per-degree constant. Checked
against the Vincenty inverse solution in tests/geodesic_reference.py at point
pairs across the bbox: distance agrees to under a millimetre, bearing to under
0.03 degrees. The bearing residual is the difference between a geodesic's initial
azimuth and the plane's mean azimuth, and it is an order of magnitude smaller than
the 0.6 degree grid convergence that DESIGN 6 warns about for MGA zone 50, which
is why bearings are computed here and the grid is only ever a cross-check.

config/lines.json was generated with a flat 111320 m/degree spherical model, so
the figures quoted in DESIGN 6 for the start/finish line (117.3 m on 139.6
degrees) read 0.22 m long and 0.14 degrees off. This module gives 117.09 m on
139.42, which is the geodesic answer. Neither difference is visible at the helm,
but it is why the fixture test in tests/test_nav.py allows a tolerance rather than
asserting equality.

Conventions (CLAUDE.md)
-----------------------
- Bearings are true, never magnetic, in [0, 360) with north 0 and east 90. Do not
  apply variation: every other angle on the display is true and the boat's compass
  heading arrives already resolved (DESIGN 9.3).
- Angles relative to the boat are signed and normalised to +/-180, port negative,
  matching the existing TWA and AWA display.
- Distances are metres. Switching the unit for display, metres under 500 m and
  nautical miles above, is the front end's job.
- A signed offset from a line is in metres, positive to the left of the direction
  of travel along that line. "Left" is an internal label, never shown to the crew:
  the race engine only compares the sign against a remembered sign, which is what
  makes the finish direction self-configuring (DESIGN 11.5).

There are only two lines in this app, and neither is ever a leg target: the
start/finish line, and the two lines it is a rule breach to cross while racing
(Bricklanding, Smith / Lucky Bay). Course legs each target a single mark, so they
need distance and bearing, not the line primitives (DESIGN 6, 11.3).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import NamedTuple, Optional

WGS84_A = 6378137.0
WGS84_F = 1.0 / 298.257223563
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)

METRES_PER_NM = 1852.0

_DEG = math.pi / 180.0


class LatLon(NamedTuple):
    """A WGS84 position in decimal degrees."""

    lat: float
    lon: float


class ENU(NamedTuple):
    """Metres east and north of a local frame origin."""

    e: float
    n: float


class Projection(NamedTuple):
    """Where a position falls relative to the line from a to b."""

    t: float
    """0 at a, 1 at b. Outside [0, 1] the position is past one of the ends."""

    offset_m: float
    """Signed perpendicular offset, positive to the left of a -> b."""

    distance_m: float
    """Perpendicular distance to the infinite line through a and b."""

    length_m: float
    """Length of a -> b."""


class Crossing(NamedTuple):
    """A track segment crossing the line between two marks."""

    t: float
    """Where along a -> b the crossing happened. Always within [0, 1]."""

    u: float
    """Where along previous -> current it happened. Always within [0, 1]."""

    from_side: int
    """-1 or +1, the side the track came from."""

    to_side: int
    """-1 or +1, the side it went to."""

    at: LatLon
    """Interpolated position of the crossing, for the race/event payload."""


def as_latlon(p) -> LatLon:
    """Coerce a position to LatLon.

    Accepts a LatLon, a {"lat": .., "lon": ..} mapping or a (lat, lon) pair.
    Config on disk is JSON objects and gps/position/0 delivers a dict, so the
    engine takes both rather than making every caller convert.
    """
    if isinstance(p, LatLon):
        return p
    if isinstance(p, Mapping):
        return LatLon(float(p["lat"]), float(p["lon"]))
    lat, lon = p
    return LatLon(float(lat), float(lon))


def norm360(deg: float) -> float:
    """Normalise a bearing to [0, 360)."""
    return deg % 360.0


def norm180(deg: float) -> float:
    """Normalise an angle to (-180, 180], port negative.

    The same convention the HUD already uses for TWA and AWA, deliberately: the
    crew is reading two signed relative angles already, so a third in a different
    convention is a trap (DESIGN 9.3).
    """
    d = (deg + 180.0) % 360.0 - 180.0
    return 180.0 if d == -180.0 else d


def metres_per_degree(lat: float) -> tuple[float, float]:
    """Metres per degree of latitude and of longitude at lat, on WGS84.

    The two radii of curvature differ by about 0.5 per cent, and at 32 S the
    parallel is shorter than the meridian by 15 per cent, so a single spherical
    constant is wrong in both components at once.
    """
    s = math.sin(lat * _DEG)
    w = 1.0 - WGS84_E2 * s * s
    m_lat = WGS84_A * (1.0 - WGS84_E2) / w**1.5  # meridian radius of curvature
    m_lon = WGS84_A / math.sqrt(w) * math.cos(lat * _DEG)  # prime vertical, scaled
    return m_lat * _DEG, m_lon * _DEG


def enu(origin, point) -> ENU:
    """Project point onto the east/north plane centred on origin.

    Scale is fixed by the origin's latitude, which makes this a linear map, so
    every point projected against the same origin shares one plane. That is the
    property the crossing tests need. It costs up to about a metre of position
    error 10 km from the origin, which can only ever show up in a distance-to-line
    readout, never in a crossing test: a fix that crosses a line is by definition
    beside it. Use distance_m() and bearing() for pairwise work, since those scale
    at the mean latitude and stay exact across the whole bbox.
    """
    o = as_latlon(origin)
    p = as_latlon(point)
    m_lat, m_lon = metres_per_degree(o.lat)
    return ENU(norm180(p.lon - o.lon) * m_lon, (p.lat - o.lat) * m_lat)


def latlon_from_enu(origin, e: float, n: float) -> LatLon:
    """Inverse of enu(), in the same frame."""
    o = as_latlon(origin)
    m_lat, m_lon = metres_per_degree(o.lat)
    return LatLon(o.lat + n / m_lat, norm180(o.lon + e / m_lon))


def _delta(a, b) -> ENU:
    """East/north from a to b, scaled at the mean latitude of the pair.

    Mean latitude rather than a's latitude: it holds distance to under a
    millimetre of the geodesic right across the bbox, where scaling at a's
    latitude drifts to about 3 m on the diagonal.
    """
    a = as_latlon(a)
    b = as_latlon(b)
    m_lat, m_lon = metres_per_degree((a.lat + b.lat) / 2.0)
    return ENU(norm180(b.lon - a.lon) * m_lon, (b.lat - a.lat) * m_lat)


def distance_m(a, b) -> float:
    """Distance from a to b in metres."""
    d = _delta(a, b)
    return math.hypot(d.e, d.n)


def distance_nm(a, b) -> float:
    """Distance from a to b in nautical miles."""
    return distance_m(a, b) / METRES_PER_NM


def bearing(a, b) -> float:
    """True bearing from a to b, degrees in [0, 360)."""
    d = _delta(a, b)
    return norm360(math.degrees(math.atan2(d.e, d.n)))


def relative_bearing(bearing_true: float, heading: float) -> float:
    """Bearing to a mark as seen from the boat: signed, +/-180, port negative.

    Shown alongside the true bearing, not instead of it, so the helm reads the
    delta to the mark without arithmetic (DESIGN 9.3).
    """
    return norm180(bearing_true - heading)


def destination(origin, bearing_true: float, distance: float) -> LatLon:
    """The position `distance` metres from origin on true bearing bearing_true.

    The inverse of bearing() and distance_m(). Used to build synthetic tracks in
    the tests and to place furniture on the map page; nothing on the boat's data
    path needs it.
    """
    o = as_latlon(origin)
    e = distance * math.sin(bearing_true * _DEG)
    n = distance * math.cos(bearing_true * _DEG)
    m_lat, _ = metres_per_degree(o.lat)
    # One fixed-point step, so this inverts distance_m() and bearing() to the
    # millimetre over a multi-kilometre leg instead of only approximately: those
    # scale at the mean latitude of the pair, which is not known until the
    # destination is.
    m_lat, m_lon = metres_per_degree(o.lat + n / m_lat / 2.0)
    return LatLon(o.lat + n / m_lat, norm180(o.lon + e / m_lon))


def midpoint(a, b) -> LatLon:
    """Midpoint of a and b.

    Used for the start/finish line: it is the point a pre-start distance-to-line
    readout aims at, and the point course distances are measured from and back to
    when reconciling a transcription against the sheet's printed total (DESIGN 7).
    No course leg targets a midpoint; every leg targets a single mark (DESIGN 6).
    """
    a = as_latlon(a)
    b = as_latlon(b)
    return LatLon((a.lat + b.lat) / 2.0, norm180(a.lon + norm180(b.lon - a.lon) / 2.0))


def project(a, b, p) -> Projection:
    """Project p onto the line through a and b.

    a and b are the two ends of a line: the inner and outer ends of the
    start/finish line, or the two marks of a no-cross line.

    Raises ValueError if the ends coincide.
    """
    origin = as_latlon(a)
    ab = enu(origin, b)
    ap = enu(origin, p)
    length_sq = ab.e * ab.e + ab.n * ab.n
    if length_sq == 0.0:
        raise ValueError("line ends coincide; there is no line to project onto")
    length = math.sqrt(length_sq)
    t = (ap.e * ab.e + ap.n * ab.n) / length_sq
    offset = (ab.e * ap.n - ab.n * ap.e) / length
    return Projection(t, offset, abs(offset), length)


def side(a, b, p, tolerance_m: float = 0.0) -> int:
    """Which side of the line a -> b p is on: +1 left, -1 right, 0 on it.

    The race engine records this when the finish becomes the target and then
    watches for a sign change away from it, which is what makes the finish
    direction self-configuring with no per-course constant (DESIGN 11.5).

    A boat sitting on the line returns 0. A caller remembering which side the boat
    is on should keep waiting for a non-zero answer rather than storing the 0,
    since nothing is a sign change away from 0.

    A position that is not finite also returns 0, meaning no side rather than a
    side. Without that, NaN takes the -1 branch, because `nan > 0.0` is False like
    every other comparison with NaN, and a confident -1 about a garbage fix
    followed by a real fix on the other side is a sign change: a false finish.
    Answering 0 fails to advance instead, which is the direction DESIGN 11.4 says
    to fail in.
    """
    offset = project(a, b, p).offset_m
    if not math.isfinite(offset) or abs(offset) <= tolerance_m:
        return 0
    return 1 if offset > 0.0 else -1


def distance_to_line_m(a, b, p) -> float:
    """Distance from p to the segment a..b, not to the infinite line.

    Past either end this is the distance to that end, which is what a
    distance-to-the-start-line readout should show when the boat is outside the
    pin (DESIGN 10).
    """
    pr = project(a, b, p)
    if 0.0 <= pr.t <= 1.0:
        return pr.distance_m
    return min(distance_m(a, p), distance_m(b, p))


def crossing(a, b, previous, current) -> Optional[Crossing]:
    """Did the track from previous to current cross between a and b?

    Returns None unless the two fixes are on opposite sides of the line *and* the
    interpolated crossing point falls within [0, 1] along a -> b. The parameter
    test is the whole point of doing it this way: sailing round the outside of the
    pin end must not finish the race (DESIGN 11.5), and rounding the outside of
    Bricklanding A or B, which is what the course asks for, must not register as
    crossing between them (DESIGN 11.3).

    A fix landing exactly on the line is resolved to the +1 side, so a crossing is
    never missed and a boat parked on the line never produces a stream of them.

    There is no deadband. If GPS scatter puts consecutive fixes either side of a
    line the boat is sitting on, this reports each flip honestly; deciding whether
    that matters is engine/race.py's job, because it is the layer that knows
    whether detection is even armed.

    Raises ValueError if the ends coincide.
    """
    origin = as_latlon(a)
    ab = enu(origin, b)
    length_sq = ab.e * ab.e + ab.n * ab.n
    if length_sq == 0.0:
        raise ValueError("line ends coincide; there is no line to cross")
    length = math.sqrt(length_sq)

    p0 = enu(origin, previous)
    p1 = enu(origin, current)
    o0 = (ab.e * p0.n - ab.n * p0.e) / length
    o1 = (ab.e * p1.n - ab.n * p1.e) / length

    from_side = 1 if o0 >= 0.0 else -1
    to_side = 1 if o1 >= 0.0 else -1
    if from_side == to_side:
        return None

    # The signs differ, so o0 != o1 and this cannot divide by zero.
    u = o0 / (o0 - o1)
    e = p0.e + u * (p1.e - p0.e)
    n = p0.n + u * (p1.n - p0.n)
    t = (e * ab.e + n * ab.n) / length_sq
    if not 0.0 <= t <= 1.0:
        return None
    return Crossing(t, u, from_side, to_side, latlon_from_enu(origin, e, n))
