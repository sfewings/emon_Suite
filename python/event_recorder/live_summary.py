"""
A recording's summary while it is still going (FR-31): how long, how far, how
fast, and the track so far, for the event page and the recorder's status.

Built incrementally. Each refresh reads only the fixes that arrived since the
last, so a three-hour recording costs the same to keep up to date at the end
as at the start, and nothing here runs the plotting code, which is for when
the recording has stopped. A refresh is at most every REFRESH_SECONDS: the
page asks every 5 s, and the boat moves a few metres in that.
"""

import math
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional

POSITION_TOPIC = 'gps/position/0'
SPEED_TOPIC = 'gps/speed/0'

REFRESH_SECONDS = 10

# A fix this far from the last kept one goes on the track, or this long after it
TRACK_STEP_METRES = 20
TRACK_STEP_SECONDS = 60
TRACK_MAX_POINTS = 3000

# Faster than this between fixes is a GPS jump, not the boat: left out of the distance
JUMP_KNOTS = 30


def _metres(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class LiveSummaries:
    """One running summary per recording, kept up to date on demand."""

    def __init__(self, database):
        self.database = database
        self._state: Dict[int, Dict] = {}
        self._lock = threading.Lock()

    def summary(self, recording_id: int) -> Dict:
        """
        {'distance_nm', 'max_sog', 'track': [[lat, lon], ...]}, current to
        within REFRESH_SECONDS.
        """
        with self._lock:
            state = self._state.get(recording_id)
            if state is None:
                state = self._state[recording_id] = {
                    'after': None, 'refreshed': 0.0, 'metres': 0.0, 'max_sog': None,
                    'last_fix': None, 'track': [], 'last_kept': None,
                }
            if time.monotonic() - state['refreshed'] >= REFRESH_SECONDS:
                self._catch_up(recording_id, state)
                state['refreshed'] = time.monotonic()
            track = [list(p) for p in state['track']]
            # Always ending where the boat is now, which thinning may have
            # skipped: the page draws its "now" dot at the last point
            last = state['last_fix']
            if last is not None:
                now = [round(last[1], 6), round(last[2], 6)]
                if not track or track[-1] != now:
                    track.append(now)
            return {
                'distance_nm': round(state['metres'] / 1852.0, 2),
                'max_sog': state['max_sog'],
                'track': track,
            }

    def forget(self, recording_id: int):
        with self._lock:
            self._state.pop(recording_id, None)

    def _catch_up(self, recording_id: int, state: Dict):
        fixes = self.database.positions_since(recording_id, POSITION_TOPIC, state['after'])
        top = self.database.max_value_since(recording_id, SPEED_TOPIC, state['after'])
        if top is not None and (state['max_sog'] is None or top > state['max_sog']):
            state['max_sog'] = round(top, 1)

        for when, lat, lon in fixes:
            last = state['last_fix']
            if last is not None:
                step = _metres(last[1], last[2], lat, lon)
                seconds = (when - last[0]).total_seconds()
                if seconds > 0 and step / seconds * 1.943844 <= JUMP_KNOTS:
                    state['metres'] += step
            state['last_fix'] = (when, lat, lon)

            kept = state['last_kept']
            if (kept is None
                    or _metres(kept[1], kept[2], lat, lon) >= TRACK_STEP_METRES
                    or (when - kept[0]).total_seconds() >= TRACK_STEP_SECONDS):
                state['track'].append((round(lat, 6), round(lon, 6)))
                state['last_kept'] = (when, lat, lon)
                if len(state['track']) > TRACK_MAX_POINTS:
                    # Every other point, rather than dropping the start of the day
                    state['track'] = state['track'][::2]

        if fixes:
            state['after'] = fixes[-1][0]
