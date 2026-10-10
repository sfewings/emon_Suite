"""
What the event page offers rather than asks for (FR-30): the categories a
recording probably belongs in, and the names of the people who sail.

Category rules are config, under `post.categories` in the service config.
Each names a category and a rule type; the types are the code here. So a new
rule of an existing type, a second island or another club, needs no code:

    post:
      categories:
        - {name: "Track Logs", when: always}
        - {name: "Ship's Log", when: moved, metres: 200}
        - {name: "Twilight",   when: weekday_evening, after: "16:00"}
        - {name: "Club event", when: race_started}
        - {name: "Rottnest",   when: track_enters, bbox: [-32.03, 115.44, -31.98, 115.56]}

Crew names come from the first paragraph of past Ship's Log posts, which is
the crew line ("Henry, Steve") in nearly every one, and from earlier drafts.
"""

import html
import json
import logging
import math
import re
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

# The boat's offset, explicit as in the racing app: Perth has no daylight
# saving, and the container's TZ is not to be trusted with it
BOAT_OFFSET = timedelta(hours=8)

POSITION_TOPIC = 'gps/position/0'


# === Categories ===

def suggest_categories(rules: List[Dict], recording: Dict, database) -> List[str]:
    """The categories whose rule the recording meets, in the rules' order."""
    chosen = []
    for rule in rules or []:
        check = _RULES.get(rule.get('when'))
        if check is None:
            logger.warning(f"Unknown category rule '{rule.get('when')}' for {rule.get('name')}")
            continue
        try:
            if check(rule, recording, database) and rule.get('name') not in chosen:
                chosen.append(rule['name'])
        except Exception as e:
            logger.warning(f"Category rule for {rule.get('name')} failed: {e}")
    return chosen


def _always(rule, recording, database):
    return True


def _moved(rule, recording, database):
    """The boat went somewhere: its fixes span more than `metres` (default 200)."""
    span = database.track_extent(recording['id'], POSITION_TOPIC)
    if not span:
        return False
    south, west, north, east = span
    mid = math.radians((north + south) / 2)
    height = (north - south) * 111320
    width = (east - west) * 111320 * math.cos(mid)
    return math.hypot(height, width) > float(rule.get('metres', 200))


def _weekday_evening(rule, recording, database):
    """Started on a weekday at or after `after` (HH:MM, boat time): a twilight sail."""
    start = recording.get('start_time')
    if not start:
        return False
    if not isinstance(start, datetime):
        start = datetime.fromisoformat(str(start))
    local = start + BOAT_OFFSET
    hours, minutes = (int(x) for x in str(rule.get('after', '16:00')).split(':'))
    return local.weekday() < 5 and (local.hour, local.minute) >= (hours, minutes)


def _race_started(rule, recording, database):
    """The racing app logged a start during the recording (race/event, FR-30)."""
    return database.has_payload(recording['id'], 'race/event', '"type":"start"')


def _track_enters(rule, recording, database):
    """A fix inside `bbox`: [south, west, north, east]."""
    south, west, north, east = (float(x) for x in rule['bbox'])
    return database.has_fix_within(recording['id'], POSITION_TOPIC, south, west, north, east)


_RULES = {
    'always': _always,
    'moved': _moved,
    'weekday_evening': _weekday_evening,
    'race_started': _race_started,
    'track_enters': _track_enters,
}


# === Wind (FR-26) ===

# The true wind the racing app reads, from the anemometer sketch
WIND_DIRECTION_TOPIC = 'anemometer/windDirection/2'
WIND_SPEED_TOPIC = 'anemometer/windSpeed/2'

# Less than this much wind data is not a day's wind
WIND_MIN_SPAN = timedelta(minutes=10)
WIND_MIN_SAMPLES = 60

# How settled the direction must be to name one: the length of the mean of the
# unit vectors, 1 for a wind that never moved and 0 for one from everywhere.
# 0.6 is roughly a spread of 55 degrees either side.
WIND_MIN_STEADINESS = 0.6

COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
           'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']


def wind_line(database, recording_id: int) -> str:
    """
    The wind as the hand-written posts give it, "NNE 12-14 kts", worked out
    from the recorded true wind, or '' when the data cannot say.

    Direction is the circular mean, named on sixteen points: an arithmetic
    mean of 350 and 10 would be 180. Speed is the 10th to 90th percentile, so
    a gust or a lull at the mooring does not set the range. Blank rather than
    guessed when there is too little wind data, or the direction wandered too
    far to name one quarter.
    """
    directions = database.numeric_series(recording_id, WIND_DIRECTION_TOPIC)
    speeds = [v for _, v in database.numeric_series(recording_id, WIND_SPEED_TOPIC)]
    if len(directions) < WIND_MIN_SAMPLES or not speeds:
        return ''
    if directions[-1][0] - directions[0][0] < WIND_MIN_SPAN:
        return ''

    east = sum(math.sin(math.radians(v)) for _, v in directions) / len(directions)
    north = sum(math.cos(math.radians(v)) for _, v in directions) / len(directions)
    if math.hypot(east, north) < WIND_MIN_STEADINESS:
        return ''
    bearing = math.degrees(math.atan2(east, north)) % 360
    name = COMPASS[int((bearing + 11.25) // 22.5) % 16]

    speeds.sort()
    low = round(speeds[int(0.1 * (len(speeds) - 1))])
    high = round(speeds[int(0.9 * (len(speeds) - 1))])
    return f"{name} {low} kts" if low == high else f"{name} {low}-{high} kts"


# === Crew ===

_SPLIT = re.compile(r'\s*(?:,|&|\band\b)\s*', re.IGNORECASE)
_NAME_WORD = re.compile(r"^[A-Z][a-zA-Z'\-]*$")


def crew_line(content_html: str) -> Optional[List[str]]:
    """
    The names in a post's crew line, or None if its first paragraph is not one.

    The hand-written posts open with the crew: "Henry, Steve", "Ian,Henry,
    Steve", "Fran and Roda". A paragraph is taken as a crew line only if every
    part is one to three capitalised words: anything with a time, a number or
    a sentence in it is not.
    """
    match = re.search(r'<p[^>]*>(.*?)</p>', content_html or '', re.DOTALL | re.IGNORECASE)
    if not match:
        return None
    text = html.unescape(re.sub(r'<[^>]+>', ' ', match.group(1))).strip()
    if not text or len(text) > 80:
        return None
    parts = [p.strip() for p in _SPLIT.split(text) if p.strip()]
    if not parts or len(parts) > 10:
        return None
    for part in parts:
        words = part.split()
        if not 1 <= len(words) <= 3 or not all(_NAME_WORD.match(w) for w in words):
            return None
    return parts


def count_names(lines: Iterable[List[str]]) -> Dict[str, int]:
    """
    How often each name sails. A part whose later words are all names that
    sail on their own is split: "Catherine Steve", in a line written without
    its comma, is Catherine and Steve, not a third person. Catherine need not
    sail alone for that; the missing comma is almost always before the name
    on every line. "Mary Ann" stays whole, as nobody called Ann sails alone.
    """
    lines = [list(line) for line in lines if line]
    singles = {}
    for line in lines:
        for part in line:
            if ' ' not in part:
                singles[part] = singles.get(part, 0) + 1

    counts = {}
    for line in lines:
        for part in line:
            words = part.split()
            names = words if len(words) > 1 and all(w in singles for w in words[1:]) else [part]
            for name in names:
                counts[name] = counts.get(name, 0) + 1
    return counts


def merge_counts(*counts: Dict[str, int]) -> List[str]:
    """Names from several sources, most sailed first, then alphabetical."""
    total = {}
    for source in counts:
        for name, n in (source or {}).items():
            total[name] = total.get(name, 0) + n
    return sorted(total, key=lambda name: (-total[name], name.lower()))


def load_json_setting(database, key: str, default):
    value = database.get_setting(key)
    if not value:
        return default
    try:
        return json.loads(value)
    except ValueError:
        return default
