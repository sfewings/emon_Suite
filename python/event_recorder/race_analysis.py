"""
Race analysis for a race recording (FR-32): the legs of the race, the boat's
position at the gun, and the times to mark on every chart.

Pure functions, no I/O, as enchantee_racing keeps its engine: data_processor
reads the recording and the course documents and hands them in, which is what
lets a recorded race be replayed through this in a test.

Times are epoch seconds (UTC) throughout. That is what race/event carries in
"ts", and the recording's own timestamps are converted to it by the caller.

The race comes from enchantee_racing's race/event messages (its DESIGN 11.9):

    select, timer      before the race; ignored here
    start              the gun: leg 0 begins. A second start (a general recall
                       and a restart) begins the race again
    rounded, back      the leg changed, automatically or by hand. A rounded
                       with no start before it is a race the crew joined late
                       by stepping the leg forward by hand
    finish             the race is over, crossed or stepped through by hand,
                       which is also how the crew abandons one
    reset              the race app went back to idle; the race ends there,
                       unfinished
    shorten, breach    information only

Each payload's "leg" is the leg now being sailed, after the transition.
"""

import bisect
import math
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

METRES_PER_NM = 1852.0
EARTH_RADIUS_M = 6371000.0

# Below this the boat's heading through the wind says nothing about its tack:
# drifting in the pre-start, or head to wind in irons.
MIN_TACK_SOG_KN = 1.0

# How far apart a speed and a wind reading may be and still be paired.
SOG_MATCH_S = 5.0

# How far either side of the gun a fix may be and still place the boat there.
GUN_FIX_S = 10.0

# Point of sail from the angle between the leg's straight-line bearing and the
# true wind direction, 0 being straight into the wind. The crew's words, owner's
# decision 17 Nov 2026: "close-hauled", never "beat". enchantee_racing's race
# screen has its own three-word scale (beat/reach/run, its DESIGN 3), sized for
# a cockpit readout; this one is for a table read ashore.
POINTS_OF_SAIL = (
    (50.0, 'Close-hauled'),
    (75.0, 'Close reach'),
    (105.0, 'Beam reach'),
    (150.0, 'Broad reach'),
    (180.1, 'Run'),
)

# Events that move the leg.
LEG_EVENTS = ('rounded', 'back')


# === Geometry ===

def norm180(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(x, y)) % 360.0


def _enu(origin: Tuple[float, float], point: Tuple[float, float]) -> Tuple[float, float]:
    """Metres east and north of origin. Flat, which is exact enough across a start line."""
    lat0, lon0 = origin
    east = math.radians(point[1] - lon0) * EARTH_RADIUS_M * math.cos(math.radians(lat0))
    north = math.radians(point[0] - lat0) * EARTH_RADIUS_M
    return east, north


def point_of_sail(twd: Optional[float], bearing: Optional[float]) -> Optional[str]:
    if twd is None or bearing is None:
        return None
    off = abs(norm180(twd - bearing))
    for limit, name in POINTS_OF_SAIL:
        if off < limit:
            return name
    return POINTS_OF_SAIL[-1][1]


def circular_mean(degrees: Iterable[float]) -> Optional[float]:
    """Mean of bearings: 350 and 10 average to 0, not 180."""
    s = c = 0.0
    n = 0
    for d in degrees:
        s += math.sin(math.radians(d))
        c += math.cos(math.radians(d))
        n += 1
    if n == 0 or (abs(s) < 1e-9 and abs(c) < 1e-9):
        return None
    return math.degrees(math.atan2(s, c)) % 360.0


# === The course, from enchantee_racing's documents ===

def course_geometry(course_id: Optional[str], courses_doc: Optional[Dict],
                    marks_doc: Optional[Dict], lines_doc: Optional[Dict]) -> Optional[Dict]:
    """
    Each leg's target, length and bearing, measured as enchantee_racing measures
    them (engine/course.py leg_table): from the middle of the start line, mark to
    mark, and back to the middle of the line for the finish.

    Returns {'legs': [{name, lat, lon, length_m, bearing}], 'line': (inner, outer)},
    or None when the course or any of its marks cannot be found: the table is then
    drawn without lengths or points of sail rather than not at all.
    """
    if not (course_id and courses_doc and marks_doc and lines_doc):
        return None
    courses = courses_doc.get('courses') or []
    if isinstance(courses, dict):
        course = courses.get(course_id)
    else:
        course = next((c for c in courses if c.get('id') == course_id), None)
    if not course:
        return None
    marks = marks_doc.get('marks') or []
    if isinstance(marks, dict):
        marks = list(marks.values())
    by_id = {m.get('id'): m for m in marks if m.get('lat') is not None}

    try:
        sf = lines_doc['start_finish']
        inner = (float(sf['inner']['lat']), float(sf['inner']['lon']))
        outer = (float(sf['outer']['lat']), float(sf['outer']['lon']))
    except (KeyError, TypeError, ValueError):
        return None
    middle = ((inner[0] + outer[0]) / 2, (inner[1] + outer[1]) / 2)

    here = middle
    legs = []
    for leg in course.get('legs', []):
        if leg.get('finish'):
            target, name = middle, 'Finish'
        else:
            mark = by_id.get(leg.get('mark'))
            if mark is None:
                return None
            target = (float(mark['lat']), float(mark['lon']))
            name = mark.get('name') or leg.get('mark')
        legs.append({
            'name': name,
            'lat': target[0], 'lon': target[1],
            'length_m': haversine_m(here[0], here[1], target[0], target[1]),
            'bearing': bearing_deg(here[0], here[1], target[0], target[1]),
        })
        here = target
    return {'legs': legs, 'line': (inner, outer), 'course_name': course.get('name')}


# === The race, from its events ===

def dedupe_events(events: Iterable[Dict]) -> List[Dict]:
    """Ordered by their own ts, each once.

    The message that starts a race recording is written into it by the trigger,
    and may also have reached the recorder by subscription; the payload's own ts
    identifies it either way.
    """
    seen = set()
    out = []
    for e in events:
        if not isinstance(e, dict) or not isinstance(e.get('ts'), (int, float)):
            continue
        key = (e.get('type'), round(float(e['ts']), 3))
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    out.sort(key=lambda e: e['ts'])
    return out


def race_timeline(events: Sequence[Dict], end: float) -> Optional[Dict]:
    """
    The legs as time segments, from the recording's race events.

    Returns {'course', 'gun', 'finished', 'end', 'segments': [(leg, t0, t1)],
    'names': {leg: name}}, or None when no race began in the recording.
    `end` is when the recording stopped, the end of an unfinished race.
    """
    gun = None
    begun = False
    finished = False
    race_end = None
    course = None
    segments: List[Tuple[int, float, float]] = []
    names: Dict[int, str] = {}
    current = None   # (leg, since)

    for e in dedupe_events(events):
        kind = e.get('type')
        ts = float(e['ts'])
        leg = e.get('leg')
        if e.get('leg_name') and isinstance(leg, int):
            names.setdefault(leg, e['leg_name'])

        if kind == 'start':
            # The gun, or a second one after a recall: the race starts here
            gun, begun, segments = ts, True, []
            course = e.get('course')
            current = (int(leg or 0), ts)
        elif kind in LEG_EVENTS and isinstance(leg, int):
            if not begun and kind == 'rounded':
                # Joined late, stepping the leg on by hand: the race is on from here
                begun = True
                course = e.get('course')
                current = (leg, ts)
                continue
            if begun and current is not None and leg != current[0]:
                segments.append((current[0], current[1], ts))
                current = (leg, ts)
        elif kind in ('finish', 'reset') and begun:
            finished = kind == 'finish'
            race_end = ts
            break

    if not begun:
        return None
    if race_end is None:
        race_end = max(end, current[1]) if current else end
    if current is not None and race_end > current[1]:
        segments.append((current[0], current[1], race_end))
    return {'course': course, 'gun': gun, 'finished': finished, 'end': race_end,
            'segments': segments, 'names': names}


def _inside(t: float, spans: Sequence[Tuple[float, float]]) -> bool:
    return any(t0 <= t <= t1 for t0, t1 in spans)


def _within(series: Sequence[Tuple[float, float]], spans) -> List[float]:
    return [v for t, v in series if v is not None and _inside(t, spans)]


def _sog_at(track: Sequence[Tuple[float, float, float, Optional[float]]],
            times: List[float], t: float) -> Optional[float]:
    i = bisect.bisect_left(times, t)
    best = None
    for j in (i - 1, i):
        if 0 <= j < len(times) and abs(times[j] - t) <= SOG_MATCH_S:
            if best is None or abs(times[j] - t) < abs(times[best] - t):
                best = j
    return track[best][3] if best is not None else None


def _wind(spans, twd, tws, awa, track, track_times) -> Dict:
    directions = _within(twd, spans)
    speeds = _within(tws, spans)
    port, starboard = [], []
    for t, v in awa:
        if v is None or not _inside(t, spans):
            continue
        sog = _sog_at(track, track_times, t) if track_times else None
        if sog is not None and sog < MIN_TACK_SOG_KN:
            continue
        a = norm180(v)
        if a < 0:
            port.append(-a)
        elif a > 0:
            starboard.append(a)
    return {
        'twd': circular_mean(directions),
        'tws_min': min(speeds) if speeds else None,
        'tws_mean': sum(speeds) / len(speeds) if speeds else None,
        'tws_max': max(speeds) if speeds else None,
        'awa_port': sum(port) / len(port) if port else None,
        'awa_starboard': sum(starboard) / len(starboard) if starboard else None,
    }


def _distance_m(track, spans) -> float:
    """Each step between fixes counts to the span its later fix lies in.

    Open at the start of a span: the step that arrives at the gun was sailed before it.
    """
    total = 0.0
    for prev, fix in zip(track, track[1:]):
        if any(t0 < fix[0] <= t1 for t0, t1 in spans):
            total += haversine_m(prev[1], prev[2], fix[1], fix[2])
    return total


def position_at(track, track_times, t: float) -> Optional[Tuple[float, float]]:
    """Where the boat was at t, between the fixes either side of it."""
    if not track:
        return None
    i = bisect.bisect_left(track_times, t)
    if i < len(track) and abs(track_times[i] - t) < 1e-6:
        return track[i][1], track[i][2]
    if 0 < i < len(track):
        a, b = track[i - 1], track[i]
        if b[0] - a[0] <= 2 * GUN_FIX_S:
            f = (t - a[0]) / (b[0] - a[0]) if b[0] > a[0] else 0.0
            return a[1] + f * (b[1] - a[1]), a[2] + f * (b[2] - a[2])
    for j in (i - 1, i):
        if 0 <= j < len(track) and abs(track_times[j] - t) <= GUN_FIX_S:
            return track[j][1], track[j][2]
    return None


def start_position(position: Tuple[float, float], geometry: Optional[Dict]) -> Dict:
    """The boat at the gun, and how far it was from the line and on which side.

    'over' means on the course side, the side the first mark is on.
    """
    out = {'lat': position[0], 'lon': position[1],
           'distance_to_line_m': None, 'side': None}
    if not geometry:
        return out
    inner, outer = geometry['line']
    bx, by = _enu(inner, outer)
    px, py = _enu(inner, position)
    length2 = bx * bx + by * by
    if length2 <= 0:
        return out
    f = max(0.0, min(1.0, (px * bx + py * by) / length2))
    out['distance_to_line_m'] = math.hypot(px - f * bx, py - f * by)
    if geometry['legs']:
        first = geometry['legs'][0]
        mx, my = _enu(inner, (first['lat'], first['lon']))
        boat_side = bx * py - by * px
        course_side = bx * my - by * mx
        if boat_side != 0 and course_side != 0:
            out['side'] = 'over' if (boat_side > 0) == (course_side > 0) else 'behind'
    return out


def analyse(events: Sequence[Dict], end: float,
            track: Sequence[Tuple[float, float, float, Optional[float]]],
            twd: Sequence[Tuple[float, float]] = (),
            tws: Sequence[Tuple[float, float]] = (),
            awa: Sequence[Tuple[float, float]] = (),
            geometry_for=None) -> Optional[Dict]:
    """
    The race in a recording, leg by leg.

    Args:
        events: race/event payloads, parsed, in any order
        end: when the recording stopped (epoch seconds)
        track: (t, lat, lon, sog_kn) fixes, oldest first
        twd, tws: true wind direction (degrees) and speed (knots), as (t, value)
        awa: apparent wind angle, signed port negative, or 0-360 bow-relative
        geometry_for: course_id -> course_geometry(...) result or None

    Returns:
        None when no race began. Otherwise a JSON-ready dict: course, gun,
        finish, finished, start (the boat at the gun), legs, total and marks,
        the (t, label) lines to draw on the charts.
    """
    timeline = race_timeline(events, end)
    if timeline is None:
        return None
    geometry = geometry_for(timeline['course']) if geometry_for else None
    geo_legs = geometry['legs'] if geometry else []
    track = list(track)
    track_times = [f[0] for f in track]

    by_leg: Dict[int, List[Tuple[float, float]]] = {}
    for leg, t0, t1 in timeline['segments']:
        by_leg.setdefault(leg, []).append((t0, t1))
    last_leg = timeline['segments'][-1][0] if timeline['segments'] else None

    legs = []
    for leg in sorted(by_leg):
        spans = by_leg[leg]
        geo = geo_legs[leg] if 0 <= leg < len(geo_legs) else None
        duration = sum(t1 - t0 for t0, t1 in spans)
        distance = _distance_m(track, spans)
        wind = _wind(spans, twd, tws, awa, track, track_times)
        row = {
            'leg': leg + 1,
            'name': (geo['name'] if geo else None) or timeline['names'].get(leg)
                    or f'Leg {leg + 1}',
            'start': min(t0 for t0, _ in spans),
            'end': max(t1 for _, t1 in spans),
            'length_m': geo['length_m'] if geo else None,
            'bearing': geo['bearing'] if geo else None,
            'point_of_sail': point_of_sail(wind['twd'], geo['bearing'] if geo else None),
            'distance_m': distance,
            'duration_s': duration,
            'avg_speed_kn': (distance / METRES_PER_NM) / (duration / 3600.0)
                            if duration > 0 else None,
            'unfinished': leg == last_leg and not timeline['finished'],
        }
        row.update(wind)
        legs.append(row)

    all_spans = [(t0, t1) for _, t0, t1 in timeline['segments']]
    duration = sum(t1 - t0 for t0, t1 in all_spans)
    distance = sum(r['distance_m'] for r in legs)
    lengths = [r['length_m'] for r in legs]
    total = {
        'length_m': sum(lengths) if lengths and None not in lengths else None,
        'distance_m': distance,
        'duration_s': duration,
        'avg_speed_kn': (distance / METRES_PER_NM) / (duration / 3600.0)
                        if duration > 0 else None,
    }
    total.update(_wind(all_spans, twd, tws, awa, track, track_times))

    start = None
    if timeline['gun'] is not None:
        gun_event = next((e for e in dedupe_events(events)
                          if e.get('type') == 'start' and float(e['ts']) == timeline['gun']), {})
        if gun_event.get('lat') is not None and gun_event.get('lon') is not None:
            where = (float(gun_event['lat']), float(gun_event['lon']))
        else:
            where = position_at(track, track_times, timeline['gun'])
        if where is not None:
            start = start_position(where, geometry)

    # The lines on every chart: the gun, each rounding, and the finish
    marks = []
    first = timeline['segments'][0][1] if timeline['segments'] else None
    if first is not None:
        marks.append({'t': first, 'label': 'Start' if timeline['gun'] is not None
                      else 'Joined', 'kind': 'start'})
    for row in legs[:-1]:
        marks.append({'t': row['end'], 'label': row['name'], 'kind': 'leg'})
    if legs:
        marks.append({'t': timeline['end'],
                      'label': 'Finish' if timeline['finished'] else 'End',
                      'kind': 'finish'})

    return {
        'course': timeline['course'],
        'course_name': geometry.get('course_name') if geometry else None,
        'gun': timeline['gun'],
        'finish': timeline['end'] if timeline['finished'] else None,
        'finished': timeline['finished'],
        'start': start,
        'legs': legs,
        'total': total,
        'marks': marks,
    }
