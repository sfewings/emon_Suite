"""A single waypoint dropped on the chart, steered to like a race mark (DESIGN 15).

Pure functions over an immutable value, the same contract as race.py: no I/O, no clock,
no store access. The store holds the current Waypoint, or None, and swaps it for whatever
these functions return.

The shape of it:

    wp = drop(position, name, now)                      # hold on the chart
    payload = navigation(wp, fix, twd)                   # what the race panel draws
    wp, arrived = on_fix(wp, fix, config)                # every GPS fix; None once arrived

There is one waypoint and no list of them. Dropping another replaces it, and arriving
clears it: the crew asked for exactly that, and it means there is nothing to manage, no
order to get wrong and nothing to remember between passages.

Arrival is the race engine's rounding test with one addition. A race mark is passed, so
"within the arming radius and then abaft the beam for a few fixes" is the whole rule, and
it is the rule tuned against two recorded races (DESIGN 11.2). A waypoint may instead be
where the boat stops, a mooring in Thomson Bay, and a boat that stops never puts it
astern: below min_sog the astern test declines by design. So reaching within
waypoint_arrival_radius_m also counts.
"""

from __future__ import annotations

from typing import Iterable, NamedTuple, Optional, Tuple

from . import course as course_module
from . import nav


NAME_RADIUS_M = 250.0
"""How close a charted feature must be to lend the waypoint its name. A hold on the chart
lands within a few tens of metres of what the finger was aiming at, and a name from half a
mile away would say the boat is heading for something it is not."""


class Waypoint(NamedTuple):
    position: nav.LatLon
    name: Optional[str]
    set_at: float
    armed: bool = False
    astern_fixes: int = 0


def drop(position, name: Optional[str], now: float) -> Waypoint:
    """A new waypoint. Replaces any previous one wholesale, arming included."""
    return Waypoint(position=nav.as_latlon(position), name=name, set_at=now)


def name_for(position, candidates: Iterable[Tuple[str, object]],
             radius_m: float = NAME_RADIUS_M) -> Optional[str]:
    """The name of the nearest charted feature within radius_m, or None.

    candidates is (name, position) pairs: the navaids and the course marks. Display only,
    so the crew reads "Kingston Reef North Cardinal Buoy" rather than a pair of numbers.
    The waypoint itself stays exactly where it was dropped, never snapped to the feature:
    a cardinal buoy marks a hazard, and the stand-off point chosen beside it is the point.
    """
    best = None
    for name, where in candidates:
        if not name:
            continue
        d = nav.distance_m(position, where)
        if d <= radius_m and (best is None or d < best[0]):
            best = (d, name)
    return best[1] if best else None


def navigation(wp: Optional[Waypoint], fix, twd: Optional[float] = None) -> Optional[dict]:
    """Distance and bearing to the waypoint, in the exact shape race.navigation returns.

    The same shape so the race screen draws it with the same code: "exactly like a race
    mark" is a property of sharing that code, not of copying it. None when the numbers
    must blank, for the same reasons as a race: no waypoint, or no usable fix (the store
    hands over None past the 5 s cutoff, DESIGN 9.5). There is no mark after a waypoint,
    so the next_* fields are always None and the panel's onward line stays empty.
    """
    if wp is None or fix is None:
        return None
    bearing = nav.bearing(fix.position, wp.position)
    return {
        "distance_m": nav.distance_m(fix.position, wp.position),
        "bearing": bearing,
        "relative": None if fix.cog is None else nav.relative_bearing(bearing, fix.cog),
        "leg_type": course_module.leg_type(twd, bearing),
        "next_name": None,
        "next_bearing": None,
        "transit": None,
        "next_leg_type": None,
    }


def on_fix(wp: Optional[Waypoint], fix, config) -> Tuple[Optional[Waypoint], bool]:
    """Evaluate one fresh fix. Returns (waypoint or None, arrived).

    config is race.Config, for the tuning this shares with rounding a mark. The caller
    passes fresh fixes only; a stale one must not clear a waypoint any more than it may
    advance a leg.
    """
    if wp is None or fix is None:
        return wp, False

    distance = nav.distance_m(fix.position, wp.position)
    if distance <= config.waypoint_arrival_radius_m:
        return None, True

    if not wp.armed:
        if distance > config.arming_radius_m:
            return wp, False
        return wp._replace(armed=True, astern_fixes=0), False

    # Passed it: abaft the beam for astern_fixes fixes running, COG trusted only above
    # min_sog. The same test, for the same reasons, as _check_rounding in race.py.
    if fix.cog is None:
        return wp, False
    if fix.sog is not None and fix.sog < config.min_sog_for_cog_kt:
        return wp._replace(astern_fixes=0), False
    relative = nav.relative_bearing(nav.bearing(fix.position, wp.position), fix.cog)
    if abs(relative) <= 90.0:
        return wp._replace(astern_fixes=0), False
    astern = wp.astern_fixes + 1
    if astern < config.astern_fixes:
        return wp._replace(astern_fixes=astern), False
    return None, True


def payload(wp: Optional[Waypoint], fix, twd: Optional[float] = None) -> Optional[dict]:
    """What /api/state carries: where it is, what it is called, and the race-panel numbers."""
    if wp is None:
        return None
    return {
        "lat": wp.position.lat,
        "lon": wp.position.lon,
        "name": wp.name,
        "set_at": wp.set_at,
        "nav": navigation(wp, fix, twd),
    }
