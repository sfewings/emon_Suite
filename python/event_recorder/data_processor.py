"""
Data processor for generating plots and statistics from recorded data.

Uses matplotlib for time-series plots and for GPS route maps, which are drawn
over the offline vector chart fetched from enchantee_racing (see chart_map.py)
and coloured by speed over ground. That is the only map now: the interactive
OpenStreetMap copy folium wrote alongside it was dropped on 3 Nov 2026.
Calculates statistics including distance, speed, energy consumption.
"""

import bisect
import csv
import fnmatch
import logging
import math
import os
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple
from xml.dom import minidom
import json

# Matplotlib configuration (must be before pyplot import)
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for Docker
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import MaxNLocator
import numpy as np

from . import chart_map
from .models import Artefacts, Database, ImageType

logger = logging.getLogger(__name__)


# === The emon envelope (emon_live_ui DESIGN 4.2) ===
#
# Readings now arrive on emon/<node>/<sub>/<field>[/<idx>] as one JSON object each:
# the value under "v", the unit under "u", and the feed's own name under "group" and
# "name", which is what a plot legend wants. A recording still holds bare numeric
# payloads on legacy topics, so everything here accepts both.
#
# Parsed here rather than by importing pyemonlib.emon_feed: that package reaches a
# compiled extension this service has no other use for, and the envelope is a versioned
# format ("s") of five keys. If it gains a version, this is the one place to look.

def _envelope(payload) -> Optional[Dict]:
    """The envelope dict for a payload, or None when it is not one."""
    if not isinstance(payload, str) or not payload.lstrip().startswith('{'):
        return None
    try:
        obj = json.loads(payload)
    except ValueError:
        return None
    # The same three keys emon_feed.parse requires before trusting an object.
    if isinstance(obj, dict) and 's' in obj and 'v' in obj and 'node' in obj:
        return obj
    return None


def _payload_number(payload) -> Optional[float]:
    """The numeric value of a payload, envelope or bare, or None if it has none.

    An envelope whose value is an object (gps position) has no number and gives None,
    which is what keeps a position out of a line plot.
    """
    envelope = _envelope(payload)
    if envelope is not None:
        value = envelope.get('v')
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)
    try:
        return float(payload)
    except (TypeError, ValueError):
        return None


def _payload_object(payload) -> Optional[Dict]:
    """The object a payload carries: an envelope's "v", or a bare JSON object.

    gps/position/<n> publishes {"lat":..,"lon":..,"ts":..} bare on the legacy topic and
    wrapped in an envelope on emon/..., and the track reader wants the same dict either
    way.
    """
    envelope = _envelope(payload)
    if envelope is not None:
        value = envelope.get('v')
        return value if isinstance(value, dict) else None
    if not isinstance(payload, str) or not payload.lstrip().startswith('{'):
        return None
    try:
        obj = json.loads(payload)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


class GpsStream(NamedTuple):
    """One GPS unit's topics in a recording.

    `position` carries lat, lon and the fix time in one payload, so a fix needs no
    join. It is the only source: the separate latitude and longitude topics they
    replaced were sampled either side of a fix and had to be matched by timestamp.
    """

    key: str                      # the subnode, '0' or '1', which names outputs
    position: str
    speed: Optional[str]


class TrackFix(NamedTuple):
    """One position, and the speed that belongs to it.

    `ts` is when the reading arrived here and is what other topics are matched
    against, since they are stamped on arrival too. `fix_ts` is the time the
    receiver put on the fix, which only gps/position carries, and is the better
    one to write into an exported track.
    """

    ts: datetime
    fix_ts: Optional[datetime]
    lat: float
    lon: float
    sog: Optional[float]


class DataProcessor:
    """
    Processes recorded data to generate plots and statistics.

    Handles:
    - Time-series line plots
    - Multi-metric comparison plots
    - GPS route maps over the offline chart, coloured by speed over ground
    - Statistics calculation
    - Statistics summary tables
    """

    # ── Automatic plot grouping / labelling tables ────────────────────────────

    # Keyword → Y-axis unit string.  The first matching keyword wins.
    _TOPIC_UNITS: Dict[str, str] = {
        'windspeed':     'knots',
        'winddirection': '°Degrees',
        'temperature':   '°C',
        'speed':         'knots',
        'course':        '°Degrees',
        'heading':       '°Degrees',
        'acc':           'm/s²',
        'gyro':          '°/s',
        'mag':           'µT',
        'pressure':      'hPa',
        'humidity':      '%',
        'voltage':       'V',
        'power':         'W',
        'current':       'A',
        'energy':        'Wh',
        'altitude':      'm',
        'elevation':     'm',
        'distance':      'km',
        'rssi':          'dBm',
        'rpm':           'RPM',
        'throttle':      '%',
    }

    # Sets of keywords: topic groups whose keys contain ANY keyword in a set
    # are merged into a single chart (e.g. "course" and "heading" together).
    _SEMANTIC_MERGE_GROUPS: List[frozenset] = [
        frozenset({'heading', 'course'}),
    ]

    # Human-readable overrides for individual MQTT path components.
    _TOPIC_COMPONENT_NAMES: Dict[str, str] = {
        'imu':           'IMU',
        'gps':           'GPS',
        'rssi':          'RSSI',
        'bms':           'BMS',
        'acc':           'Acceleration',
        'gyro':          'Gyroscope',
        'mag':           'Magnetometer',
        'windSpeed':     'Wind Speed',
        'windDirection': 'Wind Direction',
        'windspeed':     'Wind Speed',
        'winddirection': 'Wind Direction',
    }

    # Recorded under emon/# but not readings: emon/config is the retained configuration
    # document the bridge publishes for tools and lint (emon_live_ui DESIGN 5). It has no
    # value to plot, and charting it produced an 'EMON Config' chart of nothing.
    _NOT_A_FEED: frozenset = frozenset({'emon/config'})

    # Axis labels used for 3-axis sensors (acc / gyro / mag). The boat's axes, spelled
    # out: the IMU reports x, y, z by index (emon_decoder._imu) and nothing downstream
    # says which way each one points, so a legend reading 'X' tells a reader nothing.
    _AXIS_LABELS: Dict[int, str] = {
        0: 'X (bow-stern)',
        1: 'Y (port-starboard)',
        2: 'Z (vertical)',
    }

    _AXIS_TOPICS: frozenset = frozenset({'acc', 'gyro', 'mag'})

    # Colour cycle for auto-generated series.
    _AUTO_COLORS: List[str] = [
        '#667eea', '#e05c5c', '#48cae4', '#f72585',
        '#2ec4b6', '#ff9f1c', '#a8dadc', '#6d6875',
    ]

    # ─────────────────────────────────────────────────────────────────────────

    def __init__(self, database: Database, plots_dir: str = "/data/plots",
                 charts_config: Dict = None, plot_defaults: Dict = None):
        """
        Initialize data processor.

        Args:
            database: Database instance
            plots_dir: Directory for plot output
            charts_config: The `charts` service config section, for the offline
                basemap fetched from enchantee_racing. None uses defaults.
            plot_defaults: The `plots` service config section, giving dpi,
                figure size, style and line width. None uses defaults.
        """
        self.database = database
        self.plots_dir = Path(plots_dir)
        self.plots_dir.mkdir(parents=True, exist_ok=True)

        # How far apart two readings may be and still belong to the same fix.
        # Only speed arrives separately now: position carries lat and lon together.
        self.GPS_MATCH_TOLERANCE = timedelta(seconds=5)

        # {recording_id: {topic: envelope}}, built on demand by _feed_index.
        self._feed_index_cache: Dict[int, Dict[str, Dict]] = {}

        # Plot defaults
        plot_defaults = plot_defaults or {}
        self.default_dpi = plot_defaults.get('dpi', 150)
        self.default_width = plot_defaults.get('default_width', 12)
        self.default_height = plot_defaults.get('default_height', 6)
        self.default_style = plot_defaults.get('style', 'seaborn-v0_8')

        # Line width in points, so 1 is 1/72 inch however high the dpi is: a
        # bigger image does not draw a finer line, it draws the same line on a
        # bigger canvas. At the old width of 2 the trace was over four pixels
        # across while a busy topic puts nine readings in every pixel column,
        # and the detail underneath was lost to the thickness of the line.
        self.default_linewidth = plot_defaults.get('linewidth', 0.9)

        # Offline basemap for route maps. Refreshed and loaded at most once per
        # processor, on first use, so a run that plots no track does no HTTP.
        self.chart_cache = chart_map.ChartCache.from_config(charts_config, self.plots_dir)
        self._charts = None
        self._charts_loaded = False

        logger.info(f"DataProcessor initialized (plots_dir={plots_dir})")

    def _load_charts(self) -> Optional[Dict]:
        """
        Load the offline chart, refreshing it from enchantee_racing first.

        Refreshed here rather than only at startup so a regenerated chart is
        picked up without restarting this service, and processing that happens
        days after a recording still gets the current one. Every failure path
        ends in a cached copy or in None, never an exception: a recording must
        process whether or not enchantee_racing is running.

        Returns:
            Chart documents, or None when there is no usable chart
        """
        if not self._charts_loaded:
            self._charts_loaded = True
            try:
                self.chart_cache.refresh()
                self._charts = self.chart_cache.load()
            except Exception as e:
                logger.warning(f"Offline chart unavailable: {e}")
                self._charts = None
        return self._charts

    def _resolve_declared(self, recording_id: int,
                          plot_config: Optional[List[Dict]]) -> List[Dict]:
        """Turn the event config's `plots:` entries into drawable specs.

        A declared chart selects its series by feed name:

            - title: "Temperatures"
              feeds: ["*/temperature"]
            - title: "Battery"
              feeds: ["SevCon / capVoltage", "Main Battery / batteryVoltage"]
              right_feeds: ["Main Battery / cellVoltage *"]
              right_ylabel: "Cell V"

        `feeds` goes on the left axis and `right_feeds` on a second axis on the right,
        for quantities that belong on one chart but share no scale. Specs that name
        `topics` instead are passed through untouched, which is what the map specs and
        any hand-written legacy config do.

        A chart whose feeds match nothing in this recording is dropped rather than drawn
        empty: the boat does not carry every sensor on every sail.
        """
        resolved = []
        for spec in plot_config or []:
            spec = dict(spec)
            if spec.get('type') == 'statistics_table':
                continue        # built from the computed statistics, not from topics
            if not spec.get('feeds') and not spec.get('right_feeds'):
                if spec.get('topics'):
                    resolved.append(spec)
                continue

            left = self._resolve_feeds(recording_id, spec.get('feeds') or [])
            right = self._resolve_feeds(recording_id, spec.get('right_feeds') or [])
            right = [t for t in right if t not in left]
            if not left and not right:
                logger.info(f"Declared chart {spec.get('title')!r} matches no feed here")
                continue

            spec['type'] = spec.get('type', 'multi_line')
            spec['topics'] = left + right
            spec['right_topics'] = right
            spec.setdefault('legend', True)
            spec.setdefault('labels', self._declared_labels(recording_id, left + right))
            if not spec.get('ylabel'):
                spec['ylabel'] = self._group_ylabel(left or right, recording_id)
            if right and not spec.get('right_ylabel'):
                spec['right_ylabel'] = self._group_ylabel(right, recording_id)
            spec.setdefault('colors', [self._AUTO_COLORS[i % len(self._AUTO_COLORS)]
                                       for i in range(len(spec['topics']))])
            resolved.append(spec)
        return resolved

    def _declared_labels(self, recording_id: int, topics: List[str]) -> List[str]:
        """Legend labels for a declared chart: the feed's own name."""
        return [self._feed_name(recording_id, topic)
                or self._topic_readable_name(topic) for topic in topics]

    def _auto_generate_plot_config(self, recording_id: int,
                                   skip_feeds: Optional[List[str]] = None,
                                   declared_topics: Optional[set] = None) -> List[Dict]:
        """
        Auto-generate plot configurations from recorded topics.

        Related topics are grouped into a single multi-line chart rather
        than producing one chart per topic feed.  Grouping rules:

        1.  GPS latitude/longitude pairs → interactive route map.
        2.  Topics that share the same path prefix (after stripping the
            trailing numeric channel index) are placed on one chart.
            e.g. anemometer/temperature/0,1,2 → one "Temperature" chart.
        3.  Semantic merge rules combine cross-family topics that are
            logically the same quantity (e.g. gps/course/* + imu/0/heading).

        Y-axis labels (with units) and series legend labels are assigned
        automatically from lookup tables, but can be overridden by passing
        an explicit plot_config.

        Args:
            recording_id: Recording ID

        Returns:
            List of plot configuration dicts (all type 'multi_line' or 'map')
        """
        topics = [t for t in self.database.get_recording_topics(recording_id)
                  if t not in self._NOT_A_FEED]
        if not topics:
            return []

        plot_config = []
        skip_topics: set = set()

        # Feeds the event config asks not to be charted, and the ones already drawn by
        # a chart it declared: both are off the auto-generated list below, so a declared
        # chart does not also appear as a second, automatic one.
        skip_topics.update(self._resolve_feeds(recording_id, skip_feeds or []))
        skip_topics.update(declared_topics or ())

        # ── 1. GPS position streams → route maps ──────────────────────────
        # One map per GPS unit, from its position topic. That topic is taken off the
        # list below: a position plotted against time is not a chart anyone asked for.
        streams = self._find_gps_streams(recording_id)
        for i, stream in enumerate(streams):
            title = 'Route Map' if len(streams) == 1 else f'Route Map {i}'
            plot_config.append({
                'type': 'map',
                'title': title,
                'topics': [stream.position],
            })
            skip_topics.add(stream.position)
            # The unit's own latitude and longitude feeds go too. The map is what a
            # position is for; a latitude against time is a sawtooth nobody reads. They
            # used to disappear by being part of the GPS stream, but the envelope makes
            # each of them a named feed in its own right, so they have to be named here.
            skip_topics.update(self._stream_coordinate_topics(recording_id, stream))

        # ── 2. Group remaining topics by structural prefix ─────────────────
        remaining = [t for t in topics if t not in skip_topics]
        feeds = self._feed_index(recording_id)
        groups: Dict[str, List[str]] = defaultdict(list)
        for topic in remaining:
            groups[self._topic_group_key(topic, feeds.get(topic))].append(topic)

        # ── 3. Apply semantic merges (e.g. heading + course) ───────────────
        groups = self._apply_semantic_merges(dict(groups))

        # ── 4. Build one multi_line spec per group ─────────────────────────
        for group_topics in sorted(groups.values(), key=lambda g: g[0]):
            group_topics = sorted(group_topics)
            title   = self._group_plot_title(group_topics, recording_id)
            ylabel  = self._group_ylabel(group_topics, recording_id)
            labels  = self._group_series_labels(group_topics, recording_id)
            colors  = [self._AUTO_COLORS[i % len(self._AUTO_COLORS)]
                       for i in range(len(group_topics))]
            plot_config.append({
                'type':   'multi_line',
                'title':  title,
                'topics': group_topics,
                'labels': labels,
                'ylabel': ylabel,
                'colors': colors,
                'legend': True,
            })

        # ── 5. No two charts may share a title ─────────────────────────────
        # The title becomes the PNG's filename, so a repeat silently overwrites: two
        # sensor families both reporting 'temperature' (the wind sensors and the
        # pressure/temperature/humidity ones) left one chart where there were two. The
        # node tells them apart and is what the group key already grouped them by.
        self._disambiguate_titles(plot_config, recording_id)

        logger.info(f"Auto-generated {len(plot_config)} plot configs from {len(topics)} topics")
        return plot_config

    def _disambiguate_titles(self, plot_config: List[Dict], recording_id: int) -> None:
        """Make every title unique, in place, leaving already-unique ones alone."""
        counts: Dict[str, int] = defaultdict(int)
        for spec in plot_config:
            counts[spec['title']] += 1

        feeds = self._feed_index(recording_id)
        used = {t for t, n in counts.items() if n == 1}
        for spec in plot_config:
            if counts[spec['title']] == 1:
                continue
            nodes = {e.get('node', '') for t in spec['topics']
                     for e in [feeds.get(t)] if e is not None}
            stem = f"{nodes.pop()} {spec['title']}" if len(nodes) == 1 else spec['title']
            candidate, n = stem, 1
            while candidate in used:
                n += 1
                candidate = f"{stem} {n}"
            spec['title'] = candidate
            used.add(candidate)

    def _topic_to_title(self, topic: str) -> str:
        """Convert MQTT topic path to readable plot title."""
        # e.g. "gps/speed/0" → "GPS Speed 0"
        # e.g. "rssi/Breaksea location" → "RSSI Breaksea Location"
        # e.g. "scale/1" → "Scale 1"
        parts = topic.replace('/', ' ').split()
        titled = []
        for part in parts:
            if part.isnumeric():
                titled.append(part)
            elif len(part) <= 4 and part.isalpha():
                titled.append(part.upper())
            else:
                titled.append(part.capitalize())
        return ' '.join(titled)

    # ── Grouping helpers ──────────────────────────────────────────────────────

    def _readable_component(self, part: str) -> str:
        """Return a human-readable label for one MQTT path component."""
        override = (self._TOPIC_COMPONENT_NAMES.get(part)
                    or self._TOPIC_COMPONENT_NAMES.get(part.lower()))
        if override:
            return override
        if len(part) <= 4 and part.isalpha():
            return part.upper()
        return part.capitalize()

    def _topic_group_key(self, topic: str, envelope: Optional[Dict] = None) -> str:
        """
        Return the grouping key for a topic.

        With an envelope the key is '<node>/<field>', which is what makes one chart of
        readings that differ only by subnode: the boat's three wind sources publish
        windSpeed on emon/mwv/0, /1 and /2, and stripping a trailing index would leave
        three separate keys where the legacy anemometer/windSpeed/0,1,2 gave one.

        Without one, the key is the topic path with the trailing numeric channel or axis
        index stripped, so anemometer/temperature/0,1,2 all map to 'anemometer/
        temperature' as before.
        """
        if envelope is not None:
            return f"{envelope.get('node', '')}/{envelope.get('field', '')}"
        parts = topic.split('/')
        if parts and parts[-1].isdigit():
            return '/'.join(parts[:-1])
        return topic

    def _apply_semantic_merges(self, groups: Dict[str, List[str]]) -> Dict[str, List[str]]:
        """
        Merge groups whose keys share semantic meaning.

        Uses _SEMANTIC_MERGE_GROUPS: each entry is a frozenset of keywords;
        any group key containing at least one keyword from the set is merged
        with the others in the same set.
        """
        for keywords in self._SEMANTIC_MERGE_GROUPS:
            matching = [k for k in list(groups.keys())
                        if any(kw in k.lower() for kw in keywords)]
            if len(matching) > 1:
                primary = min(matching)   # deterministic: alphabetically first
                for key in matching:
                    if key != primary:
                        groups[primary].extend(groups.pop(key))
        return groups

    def _group_plot_title(self, topics: List[str],
                          recording_id: Optional[int] = None) -> str:
        """
        Derive a chart title from the group of topics.

        Envelopes give the title outright: the sensor's group name when every series
        shares one ('Main Battery'), otherwise the reading they have in common
        ('windSpeed'). A path prefix is only readable by accident; a name is deliberate.

        Otherwise, finds the longest common MQTT path prefix and converts it to a
        readable title. When topics come from entirely different topic families
        (semantic merge), the distinct roots are joined with ' / '.

        A numeric component is kept only when named components follow it. An
        interior number identifies the instance — imu/0 and imu/2 are different
        sensors — and dropping it titled every unit's acceleration, gyroscope
        and magnetometer chart 'IMU', so all nine wrote one file and only the
        last survived. A trailing number is the channel or axis index, which is
        already drawn as a separate series, so it stays out of the title.
        """
        if recording_id is not None:
            feeds = self._feed_index(recording_id)
            named = [feeds.get(t) for t in topics]
            if all(e is not None for e in named):
                groups = {e.get('group', '') for e in named}
                fields = {e.get('field', '') for e in named}
                one_group = groups.pop() if len(groups) == 1 else ''
                # The field verbatim, not title-cased: it is already the name the
                # decoder chose, and _readable_component would flatten cellVoltage to
                # 'Cellvoltage'. The legends use their names verbatim for the same
                # reason, so a chart and its legend agree.
                one_field = fields.pop() if len(fields) == 1 else ''
                # Both when both are known. The title becomes the PNG's filename
                # (_title_to_stem), so 'Main Battery' alone would have the pack's seven
                # charts write one file and only the last survive — the same collision
                # the prefix rule below guards against for the IMU.
                title = ' '.join(p for p in (one_group, one_field) if p)
                if title:
                    return title
                # Neither is shared: a semantically merged group, where the feeds come
                # from different sensors and measure differently-named things that mean
                # the same (course and heading). Name it for what it holds. Without this
                # it fell through to the common topic prefix, which for envelopes is the
                # literal 'emon'.
                named_fields = sorted(f for f in fields if f)
                if named_fields:
                    return ' / '.join(named_fields)

        split_topics = [t.split('/') for t in topics]
        common: List[str] = []
        for components in zip(*split_topics):
            if len(set(components)) != 1:
                break
            common.append(components[0])
        while common and common[-1].isdigit():
            common.pop()

        if common:
            return ' '.join(self._readable_component(p) for p in common)

        # No common non-numeric prefix — combine root-level family names
        roots = sorted({t.split('/')[0] for t in topics})
        return ' / '.join(self._readable_component(r) for r in roots)

    def _group_ylabel(self, topics: List[str],
                      recording_id: Optional[int] = None) -> str:
        """
        Return the Y-axis label (with units) for a group of topics.

        An envelope states its unit, so when every series in the group agrees on one it
        is used verbatim and nothing is guessed. _TOPIC_UNITS below is the fallback for
        legacy topics: it searches the combined topic strings for the first matching
        keyword, longest first.
        """
        if recording_id is not None:
            feeds = self._feed_index(recording_id)
            units = {e.get('u') for t in topics
                     for e in [feeds.get(t)] if e is not None and e.get('u')}
            if len(units) == 1:
                return units.pop()

        combined = ' '.join(topics).lower()
        # Sort by keyword length descending so more-specific terms win
        for keyword, unit in sorted(self._TOPIC_UNITS.items(),
                                    key=lambda kv: -len(kv[0])):
            if keyword in combined:
                return unit
        return 'Value'

    def _topic_readable_name(self, topic: str) -> str:
        """
        Full readable name for a topic, skipping non-terminal numeric parts.

        e.g. 'imu/0/heading' → 'IMU Heading'
             'gps/course/0'  → 'GPS Course 0'
        """
        parts = topic.split('/')
        readable = []
        for i, part in enumerate(parts):
            is_last = (i == len(parts) - 1)
            if part.isdigit() and not is_last:
                continue   # skip node-ID digits in the middle
            readable.append(self._readable_component(part))
        return ' '.join(readable)

    def _axis_labels(self, envelopes: List[Dict]) -> Optional[List[str]]:
        """Axis labels for a three-axis sensor's channels, or None if it is not one.

        Every envelope must be the same field of the same sensor and carry an index in
        range: a chart mixing acc with gyro, or holding only two of the three axes, is
        not what these labels describe.
        """
        fields = {e.get('field', '') for e in envelopes}
        groups = {e.get('group', '') for e in envelopes}
        if len(fields) != 1 or len(groups) != 1:
            return None
        if fields.pop() not in self._AXIS_TOPICS:
            return None
        indexes = [e.get('idx') for e in envelopes]
        # All three, exactly once each. Two of the three is a partial chart that these
        # labels would misdescribe, and a repeated index is not a set of axes at all.
        if sorted(i for i in indexes if i is not None) != sorted(self._AXIS_LABELS):
            return None
        return [self._AXIS_LABELS[i] for i in indexes]

    def _group_series_labels(self, topics: List[str],
                             recording_id: Optional[int] = None) -> List[str]:
        """
        Generate per-series legend labels for the topics in a group.

        A feed that carries an envelope is labelled by the name emon_config gave it:
        'Main Battery / power', 'True wind / windSpeed'. That is the whole point of the
        envelope lane, and it beats anything reconstructed from a topic path.

        Where every series in a group shares a group name, the shared half is dropped and
        only what distinguishes them is kept, so a chart of one battery's sixteen cells
        reads 'cellVoltage 0..15' rather than repeating 'Main Battery /' sixteen times.

        Without envelopes the old reconstruction applies:
        - Find the longest common MQTT path prefix shared by all topics.
        - When topics share a prefix (same family, different channel index):
            * Single trailing digit on a 3-axis sensor (acc/gyro/mag) → X/Y/Z
            * Single trailing digit on anything else → the digit as a string
            * Multi-part suffix → readable form of the suffix
        - When there is no common prefix (topics from different families,
          e.g. after a semantic merge) → full readable name for each topic.
        """
        if recording_id is not None:
            feeds = self._feed_index(recording_id)
            named = [feeds.get(t) for t in topics]
            if all(e is not None and e.get('name') for e in named):
                # A three-axis sensor is labelled by what each axis points along, not
                # by its index. 'acc 0' says nothing about the boat; 'X (bow-stern)'
                # does, and the index-to-axis mapping is only written down in
                # emon_decoder._imu. This has to come before the group check below,
                # which would otherwise return the envelope names and never reach it.
                axis_labels = self._axis_labels(named)
                if axis_labels:
                    return axis_labels

                groups = {e.get('group', '') for e in named}
                if len(groups) == 1 and len(topics) > 1:
                    # One sensor's channels: its name is in the title already.
                    return [e['name'] for e in named]
                return [f"{e['group']} / {e['name']}" if e.get('group') else e['name']
                        for e in named]

        if len(topics) == 1:
            return [self._topic_readable_name(topics[0])]

        # Find how many leading path components are identical across all topics
        split_topics = [t.split('/') for t in topics]
        common_len = 0
        for components in zip(*split_topics):
            if len(set(components)) == 1:
                common_len += 1
            else:
                break

        labels = []
        for topic in topics:
            parts = topic.split('/')
            suffix = parts[common_len:]

            if not suffix or common_len == 0:
                # No (or empty) common prefix → use the full readable name
                labels.append(self._topic_readable_name(topic))
                continue

            if len(suffix) == 1 and suffix[0].isdigit():
                idx = int(suffix[0])
                # 3-axis sensors get X / Y / Z labels
                if any(kw in topic.lower() for kw in self._AXIS_TOPICS):
                    labels.append(self._AXIS_LABELS.get(idx, str(idx)))
                else:
                    labels.append(str(idx))
            else:
                # Multi-component suffix → readable, skipping numeric node IDs
                meaningful = [self._readable_component(p)
                              for p in suffix if not p.isdigit()]
                labels.append(' '.join(meaningful) if meaningful else topic)

        return labels

    def process_recording(self, recording_id: int, plot_config: List[Dict] = None,
                          export_config: Dict = None,
                          skip_feeds: List[str] = None) -> Dict:
        """
        Process recording: generate plots, statistics, and export files.

        If plot_config is empty or None, auto-generates plots for all
        recorded topics. If export_config is None, auto-generates export
        files based on available data (CSV always; KML/GPX when GPS data present).

        Args:
            recording_id: Recording ID
            plot_config: List of plot configuration dicts (optional)
            export_config: Dict with keys 'csv', 'kml', 'gpx' (True/False).
                           Pass None for auto-detection.

        Returns:
            Dict with processing results:
            {
                'plots': [list of image paths],
                'exports': [list of export file dicts],
                'statistics': {stats dict},
                'status': 'success' or 'failed',
                'error': error message if failed
            }
        """
        logger.info(f"Processing recording {recording_id}")

        # The artefacts' state, not the recording's (TR-12): processing a
        # recording says nothing about whether recording it went well
        self.database.update_recording(recording_id, artefacts=Artefacts.PROCESSING)

        try:
            # Create output directory for this recording
            output_dir = self.plots_dir / str(recording_id)
            output_dir.mkdir(parents=True, exist_ok=True)

            # Clear the previous run's generated artefacts so re-processing
            # replaces them rather than adding to them. Plot rows would
            # otherwise accumulate a duplicate set per run, and the publisher
            # globs *.html, so a map left behind under an old filename would be
            # embedded in the post alongside the new one. Export rows go too:
            # a type switched off since the last run kept its row, and the
            # publisher went on offering the file. User uploads live outside
            # this directory and are not touched.
            cleared = self.database.delete_plot_images(recording_id)
            for stale_map in output_dir.glob('*.html'):
                stale_map.unlink()
            # The PNGs too. Only the database rows and the maps were cleared before,
            # which was invisible while every run drew the same chart set under the same
            # filenames. Once the charts are composed from config, a regrouped run draws
            # fewer or differently-named files and the previous run's were left in the
            # directory: not in the post, since that follows the database rows, but
            # misleading to anyone reading the directory. User uploads live elsewhere.
            for stale_plot in output_dir.glob('*.png'):
                stale_plot.unlink()
            if cleared:
                logger.info(f"Cleared {cleared} plot image record(s) from previous run")
            cleared = self.database.delete_recording_exports(recording_id)
            if cleared:
                logger.info(f"Cleared {cleared} export record(s) from previous run")

            results = {
                'plots': [],
                'exports': [],
                'statistics': {},
                'status': 'success'
            }

            # Charts the event config declares are drawn first, in the order it lists
            # them, and the feeds they use are then left out of the automatic ones, so
            # a hand-composed chart does not reappear as an automatic duplicate.
            # Anything the config says nothing about is still grouped automatically:
            # a sensor added to the boat shows up without the config being edited.
            declared = self._resolve_declared(recording_id, plot_config)
            auto = self._auto_generate_plot_config(
                recording_id, skip_feeds=skip_feeds,
                declared_topics={t for spec in declared for t in spec['topics']})
            plot_config = declared + auto

            # Generate plots
            if plot_config:
                logger.info(f"Generating {len(plot_config)} plots")
                for plot_spec in plot_config:
                    try:
                        plot_path = self._generate_plot(recording_id, plot_spec, output_dir)
                        if plot_path:
                            results['plots'].append(str(plot_path))
                            # Add to database
                            self.database.add_image(
                                recording_id,
                                str(plot_path),
                                ImageType.PLOT,
                                caption=plot_spec.get('title', 'Plot')
                            )
                    except Exception as e:
                        logger.error(f"Failed to generate plot '{plot_spec.get('title')}': {e}")

            # Calculate statistics
            logger.info("Calculating statistics")
            results['statistics'] = self.calculate_statistics(recording_id)

            # Generate statistics table as image
            stats_table_path = self._generate_statistics_table(
                recording_id,
                results['statistics'],
                output_dir
            )
            if stats_table_path:
                results['plots'].append(str(stats_table_path))
                self.database.add_image(
                    recording_id,
                    str(stats_table_path),
                    ImageType.PLOT,
                    caption="Statistics Summary"
                )

            # Save statistics as JSON sidecar so the publisher can render
            # them as an HTML table instead of uploading the PNG image
            if results['statistics']:
                json_path = output_dir / 'statistics_summary.json'
                try:
                    with open(json_path, 'w') as f:
                        json.dump(results['statistics'], f, indent=2, default=str)
                    logger.info(f"Saved statistics JSON: {json_path}")
                except Exception as e:
                    logger.warning(f"Could not save statistics JSON: {e}")

            # Generate export files
            if export_config is None:
                export_config = self._auto_generate_export_config(recording_id)
            logger.info(f"Export config: {export_config}")

            if export_config.get('csv', False):
                csv_path = self.generate_csv_export(recording_id, output_dir)
                if csv_path:
                    self.database.add_export(recording_id, 'csv', str(csv_path), 'All Data')
                    results['exports'].append({'type': 'csv', 'path': str(csv_path), 'label': 'All Data'})

            if export_config.get('kml', False):
                kml_paths = self.generate_kml_exports(recording_id, output_dir)
                for j, kml_path in enumerate(kml_paths):
                    label = 'Route Map' if len(kml_paths) == 1 else f'Route Map {j}'
                    self.database.add_export(recording_id, 'kml', str(kml_path), label)
                    results['exports'].append({'type': 'kml', 'path': str(kml_path), 'label': label})

            if export_config.get('gpx', False):
                gpx_path = self.generate_gpx_export(recording_id, output_dir)
                if gpx_path:
                    self.database.add_export(recording_id, 'gpx', str(gpx_path), 'GPS Track')
                    results['exports'].append({'type': 'gpx', 'path': str(gpx_path), 'label': 'GPS Track'})

            logger.info(f"Processing complete: {len(results['plots'])} plots, "
                        f"{len(results['exports'])} exports")

            self.database.update_recording(recording_id, artefacts=Artefacts.FRESH,
                                           processed_at=datetime.utcnow())
            return results

        except Exception as e:
            logger.error(f"Processing failed: {e}")
            self.database.update_recording(recording_id, artefacts=Artefacts.FAILED,
                                           error_message=f"Processing failed: {e}")
            return {
                'plots': [],
                'statistics': {},
                'status': 'failed',
                'error': str(e)
            }

    def _generate_plot(self, recording_id: int, plot_spec: Dict, output_dir: Path) -> Optional[Path]:
        """
        Generate plot based on specification.

        Args:
            recording_id: Recording ID
            plot_spec: Plot specification dict
            output_dir: Output directory

        Returns:
            Path to generated plot or None
        """
        plot_type = plot_spec.get('type', 'line')

        if plot_type == 'line':
            return self._generate_line_plot(recording_id, plot_spec, output_dir)
        elif plot_type == 'multi_line':
            return self._generate_multi_line_plot(recording_id, plot_spec, output_dir)
        elif plot_type == 'map':
            return self._generate_route_map(recording_id, plot_spec, output_dir)
        elif plot_type == 'statistics_table':
            # Handled separately
            return None
        else:
            logger.warning(f"Unknown plot type: {plot_type}")
            return None

    def _generate_line_plot(self, recording_id: int, plot_spec: Dict, output_dir: Path) -> Path:
        """
        Generate single-line time-series plot.

        Args:
            recording_id: Recording ID
            plot_spec: Plot specification with 'topics', 'title', 'ylabel', etc.
            output_dir: Output directory

        Returns:
            Path to generated plot
        """
        title = plot_spec.get('title', 'Plot')
        topics = plot_spec.get('topics', [])
        ylabel = plot_spec.get('ylabel', 'Value')
        color = plot_spec.get('color', '#667eea')

        if not topics:
            raise ValueError("No topics specified for line plot")

        # Get data
        data = self._get_topic_data(recording_id, topics[0])
        if not data:
            raise ValueError(f"No data found for topic {topics[0]}")

        timestamps, values = data
        timestamps = [self._utc_to_local(t) for t in timestamps]

        # Create plot
        fig, ax = plt.subplots(figsize=(self.default_width, self.default_height))

        ax.plot(timestamps, values, linewidth=self.default_linewidth, color=color)
        ax.set_title(title, fontsize=16, fontweight='bold')
        ax.set_xlabel('Time', fontsize=12)
        ax.set_ylabel(ylabel, fontsize=12)
        ax.grid(True, alpha=0.3)

        # Format x-axis
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        plt.xticks(rotation=45, ha='right')

        # Format y-axis
        ax.yaxis.set_major_locator(MaxNLocator(nbins=10))

        plt.tight_layout()

        # Save
        filename = f"{self._title_to_stem(title)}.png"
        output_path = output_dir / filename
        plt.savefig(output_path, dpi=self.default_dpi, bbox_inches='tight')
        plt.close()

        logger.info(f"Generated line plot: {filename}")
        return output_path

    def _generate_multi_line_plot(self, recording_id: int, plot_spec: Dict, output_dir: Path) -> Path:
        """
        Generate multi-line comparison plot.

        Args:
            recording_id: Recording ID
            plot_spec: Plot specification with multiple topics
            output_dir: Output directory

        Returns:
            Path to generated plot
        """
        title = plot_spec.get('title', 'Comparison Plot')
        topics = plot_spec.get('topics', [])
        labels = plot_spec.get('labels', topics)
        ylabel = plot_spec.get('ylabel', 'Value')
        colors = plot_spec.get('colors', ['#667eea', '#764ba2', '#48cae4', '#f72585'])
        show_legend = plot_spec.get('legend', True)

        if not topics:
            raise ValueError("No topics specified for multi-line plot")

        # Create plot
        fig, ax = plt.subplots(figsize=(self.default_width, self.default_height))

        # Series the spec puts on a second axis, for quantities that belong on one
        # chart but share no scale: a pack's 3.3 V cells against its 55 V total, or a
        # motor's amps against the battery's watts. Dashed, so which axis a line is
        # read against is visible without tracing it back to the legend.
        right_topics = set(plot_spec.get('right_topics') or ())
        right_ax = ax.twinx() if right_topics else None
        handles = []

        for i, topic in enumerate(topics):
            data = self._get_topic_data(recording_id, topic)
            if data:
                timestamps, values = data
                timestamps = [self._utc_to_local(t) for t in timestamps]
                # The spec's own label wins; otherwise the feed's name, and only then
                # the topic, which is what a reader can make least of.
                label = (labels[i] if i < len(labels)
                         else self._feed_name(recording_id, topic) or topic)
                color = colors[i % len(colors)]
                target = right_ax if topic in right_topics else ax
                line, = target.plot(timestamps, values,
                                    linewidth=self.default_linewidth,
                                    label=label, color=color,
                                    linestyle='--' if topic in right_topics else '-')
                handles.append(line)

        ax.set_title(title, fontsize=16, fontweight='bold')
        ax.set_xlabel('Time', fontsize=12)
        ax.set_ylabel(ylabel, fontsize=12)
        ax.grid(True, alpha=0.3)
        if right_ax is not None:
            right_ax.set_ylabel(plot_spec.get('right_ylabel', ''), fontsize=12)

        # `invert` / `right_invert` flip an axis. The pack reports power negative while
        # it is being drawn from, so inverting that axis puts "motor working harder"
        # upwards on both scales and the two lines rise and fall together instead of
        # mirroring each other.
        if plot_spec.get('invert'):
            ax.invert_yaxis()
        if right_ax is not None and plot_spec.get('right_invert'):
            right_ax.invert_yaxis()

        if show_legend:
            # One legend for both axes; twinx draws its own otherwise and they overlap.
            # Outside the axes on the right: these charts carry up to twenty series and
            # 'best' puts the box over the data.
            ncol = 2 if len(handles) > 10 else 1
            ax.legend(handles, [h.get_label() for h in handles], fontsize=8, ncol=ncol,
                      loc='upper left', bbox_to_anchor=(1.08 if right_ax is not None
                                                        else 1.01, 1.0),
                      borderaxespad=0, frameon=False)

        # Format x-axis
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        plt.xticks(rotation=45, ha='right')

        plt.tight_layout()

        # Save
        filename = f"{self._title_to_stem(title)}.png"
        output_path = output_dir / filename
        plt.savefig(output_path, dpi=self.default_dpi, bbox_inches='tight')
        plt.close()

        logger.info(f"Generated multi-line plot: {filename}")
        return output_path

    def _generate_route_map(self, recording_id: int, plot_spec: Dict, output_dir: Path) -> Path:
        """
        Generate GPS route map, coloured by speed over ground.

        The returned PNG is drawn with matplotlib over the offline vector chart
        fetched from enchantee_racing, because the host has no internet on the
        water and OpenStreetMap tiles are unreachable there. It is the only map
        the post carries.

        Args:
            recording_id: Recording ID
            plot_spec: Plot specification
            output_dir: Output directory

        Returns:
            Path to generated map image
        """
        title = plot_spec.get('title', 'Route Map')
        topics = plot_spec.get('topics', ['gps/position/0'])

        coords, speeds = self._get_gps_track(recording_id, topics)
        if not coords or len(coords) < 2:
            raise ValueError("Insufficient GPS data for route map")

        # The interactive OpenStreetMap view that used to be written alongside this is
        # gone (owner's decision, 3 Nov 2026). The chart map is drawn over the vector
        # chart of the sailing area, which is the better map of the two and the only one
        # that works on the boat; the OSM copy was a second rendering of the same track
        # for a reader ashore, and the post is clearer with one map in it.
        return self._generate_chart_route_map(title, coords, speeds, output_dir)

    def _generate_chart_route_map(self, title: str,
                                  coords: List[Tuple[float, float]],
                                  speeds: List[Optional[float]],
                                  output_dir: Path) -> Path:
        """
        Draw the route over the offline chart, coloured by speed over ground.

        Falls back to plain latitude/longitude axes when there is no cached
        chart or when the track leaves the charted area, so a track sailed
        somewhere else is still plotted rather than lost.

        Args:
            title: Plot title
            coords: List of (latitude, longitude)
            speeds: Speed in knots per coordinate, None where unknown
            output_dir: Output directory

        Returns:
            Path to generated plot
        """
        lats = [lat for lat, lon in coords]
        lons = [lon for lat, lon in coords]

        fig, ax = plt.subplots(figsize=(self.default_width, self.default_height))

        charts = self._load_charts()
        on_chart = bool(charts) and chart_map.track_on_chart(coords, charts)
        if on_chart:
            chart_map.draw_basemap(ax, charts)
        elif charts:
            logger.info("Track is outside the charted area; using plain axes")

        mappable = chart_map.draw_speed_track(ax, coords, speeds)

        ax.plot(lons[0], lats[0], 'o', markersize=10, markerfacecolor='#2e9e4f',
                markeredgecolor='#ffffff', markeredgewidth=1.2, label='Start',
                zorder=10)
        ax.plot(lons[-1], lats[-1], 'o', markersize=10, markerfacecolor='#d64545',
                markeredgecolor='#ffffff', markeredgewidth=1.2, label='End',
                zorder=10)

        # Limits come from the track, not from the chart: the coastline is
        # generated far wider than the sailing area for the ocean races, and
        # letting it autoscale would draw the track as a speck.
        margin_lat = max((max(lats) - min(lats)) * 0.08, 0.0005)
        margin_lon = max((max(lons) - min(lons)) * 0.08, 0.0005)
        ax.set_xlim(min(lons) - margin_lon, max(lons) + margin_lon)
        ax.set_ylim(min(lats) - margin_lat, max(lats) + margin_lat)

        if mappable is not None:
            bar = fig.colorbar(mappable, ax=ax, pad=0.02)
            bar.set_label('Speed over ground (kt)', fontsize=11)

        ax.set_title(title, fontsize=16, fontweight='bold', pad=26)
        ax.set_xlabel('Longitude', fontsize=12)
        ax.set_ylabel('Latitude', fontsize=12)
        if not on_chart:
            ax.grid(True, alpha=0.3)
        # Above the axes rather than inside them. The aspect is fixed to correct
        # for latitude, so a tall narrow track leaves a narrow axes box, and an
        # in-axes legend either covers the track or is clipped by the spine.
        ax.legend(loc='lower left', bbox_to_anchor=(0.0, 1.0), ncol=2,
                  frameon=False, fontsize=10, handletextpad=0.4,
                  columnspacing=1.4)

        # A degree of longitude is shorter than a degree of latitude. Equal
        # units squash the track east to west by about 15 per cent at 32 South,
        # which is enough to read a wrong bearing off the picture.
        ax.set_aspect(chart_map.latitude_aspect(coords), adjustable='box')

        plt.tight_layout()

        filename = f"{self._title_to_stem(title)}.png"
        output_path = output_dir / filename
        plt.savefig(output_path, dpi=self.default_dpi, bbox_inches='tight')
        plt.close()

        logger.info(
            f"Generated route map: {filename} "
            f"(chart={'yes' if on_chart else 'no'}, "
            f"speed={'yes' if mappable is not None else 'no'})"
        )
        return output_path

    @staticmethod
    def _utc_to_local(stamp: Optional[datetime]) -> Optional[datetime]:
        """
        Reinterpret a stored timestamp in the container's timezone.

        Everything is recorded with datetime.utcnow(), which is the right thing
        to store but the wrong thing to show: a chart of an afternoon sail was
        labelled with the morning's UTC hours. Anything a reader sees goes
        through here first. Exports do not: GPX and KML timestamps are UTC by
        specification.

        Returns a naive datetime, matching what the rest of the module passes
        around, so a converted value can be compared with an unconverted one
        without TypeError.

        Args:
            stamp: Naive UTC datetime, or None

        Returns:
            Naive local datetime, or None
        """
        if stamp is None:
            return None
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone().replace(tzinfo=None)

    @staticmethod
    def _title_to_stem(title: str) -> str:
        """
        Convert a plot title to a filename stem.

        A semantically merged group is titled 'GPS / IMU', and the separator is
        a path separator: writing that straight into a filename sent the plot to
        a directory that does not exist, and it was silently lost. Titles can
        also arrive in a plot_config from the API, so anything outside
        [a-z0-9-] collapses to an underscore rather than being trusted.

        Args:
            title: Plot title

        Returns:
            Filename stem, without extension
        """
        return re.sub(r'[^a-z0-9-]+', '_', title.lower()).strip('_') or 'plot'

    def _generate_statistics_table(self, recording_id: int, statistics: Dict, output_dir: Path) -> Optional[Path]:
        """
        Generate statistics summary table as image.

        Args:
            recording_id: Recording ID
            statistics: Statistics dict
            output_dir: Output directory

        Returns:
            Path to generated table image
        """
        if not statistics:
            return None

        # Prepare table data
        table_data = [['Metric', 'Value']]

        # Add timing stats
        if 'start_time' in statistics:
            table_data.append(['Start Time', statistics['start_time']])
        if 'end_time' in statistics:
            table_data.append(['End Time', statistics['end_time']])
        if 'duration' in statistics:
            table_data.append(['Duration', statistics['duration']])
        if 'message_count' in statistics:
            table_data.append(['Messages Recorded', f"{statistics['message_count']:,}"])

        # Add GPS-derived stats
        if 'distance_km' in statistics:
            table_data.append(['Distance', f"{statistics['distance_km']:.2f} km"])
        if 'max_speed' in statistics:
            table_data.append(['Max Speed', f"{statistics['max_speed']:.1f} knots"])
        if 'avg_speed' in statistics:
            table_data.append(['Avg Speed', f"{statistics['avg_speed']:.1f} knots"])

        # Add energy stats
        if 'energy_used_wh' in statistics:
            table_data.append(['Energy Used', f"{statistics['energy_used_wh']:.1f} Wh"])
        if 'efficiency_wh_per_km' in statistics:
            table_data.append(['Efficiency', f"{statistics['efficiency_wh_per_km']:.1f} Wh/km"])

        if 'battery_cycles' in statistics:
            table_data.append(['Battery Cycles', f"{statistics['battery_cycles']:.0f}"])

        # Create figure
        fig, ax = plt.subplots(figsize=(8, len(table_data) * 0.4 + 1))
        ax.axis('tight')
        ax.axis('off')

        # Create table
        table = ax.table(
            cellText=table_data,
            cellLoc='left',
            loc='center',
            colWidths=[0.5, 0.5]
        )

        table.auto_set_font_size(False)
        table.set_fontsize(11)
        table.scale(1, 2)

        # Style header row
        for i in range(2):
            cell = table[(0, i)]
            cell.set_facecolor('#667eea')
            cell.set_text_props(weight='bold', color='white')

        # Alternate row colors
        for i in range(1, len(table_data)):
            for j in range(2):
                cell = table[(i, j)]
                if i % 2 == 0:
                    cell.set_facecolor('#f0f0f0')

        plt.title('Track Statistics', fontsize=14, fontweight='bold', pad=20)

        # Save
        filename = "statistics_summary.png"
        output_path = output_dir / filename
        plt.savefig(output_path, dpi=self.default_dpi, bbox_inches='tight')
        plt.close()

        logger.info(f"Generated statistics table: {filename}")
        return output_path

    def _get_topic_data(self, recording_id: int, topic: str) -> Optional[Tuple[List[datetime], List[float]]]:
        """
        Get time-series data for a topic.

        Args:
            recording_id: Recording ID
            topic: MQTT topic

        Returns:
            Tuple of (timestamps, values) or None
        """
        # Get data from database
        data = self.database.get_recording_data(recording_id, topic_filter=topic)

        if not data:
            return None

        timestamps = []
        values = []

        for record in data:
            try:
                timestamp = record['timestamp']
                if isinstance(timestamp, str):
                    timestamp = datetime.fromisoformat(timestamp)

                value = _payload_number(record['payload'])
                if value is None:
                    continue

                timestamps.append(timestamp)
                values.append(value)
            except (ValueError, KeyError):
                continue

        if not timestamps:
            return None

        return (timestamps, values)

    def _feed_index(self, recording_id: int) -> Dict[str, Dict]:
        """{topic: envelope} for every topic in the recording that carries one.

        One row per topic is enough: a feed's name, unit and kind are the same in every
        envelope it publishes, only "v" and "t" differ. Legacy topics are absent from the
        result, which is how callers tell the two apart.

        Cached per recording: the labels, the y-axis units and the GPS stream search all
        want it while one recording is being processed.
        """
        cached = self._feed_index_cache.get(recording_id)
        if cached is not None:
            return cached

        index = {}
        for topic in self.database.get_recording_topics(recording_id):
            rows = self.database.get_recording_data(recording_id, topic_filter=topic,
                                                    limit=1)
            if not rows:
                continue
            envelope = _envelope(rows[0]['payload'])
            if envelope is not None:
                index[topic] = envelope

        self._feed_index_cache[recording_id] = index
        logger.info(f"Feed index: {len(index)} named feeds in recording {recording_id}")
        return index

    def _resolve_feeds(self, recording_id: int,
                       patterns: List[str]) -> List[str]:
        """Topics whose feed name matches any of the glob patterns, in pattern order.

        Patterns are matched against the feed name ('Main Battery / power'), not the
        topic, which is the whole point of naming feeds: an event config says what it
        wants in the words emon_config uses, and never has to know that the pack reports
        over the BMS on emon/bms/1/power.

        fnmatch, so 'Main Battery / cellVoltage *' takes all sixteen cells and
        '*/temperature' takes every sensor's temperature. A pattern matching nothing is
        not an error: a recording may simply not contain that sensor.
        """
        feeds = self._feed_index(recording_id)
        names = {topic: self._feed_name(recording_id, topic) for topic in feeds}

        found: List[str] = []
        for pattern in patterns:
            # Sorted by the digits in the name where there are any, so cellVoltage 2
            # comes before cellVoltage 10 rather than after it, as a plain sort gives.
            matched = sorted((topic for topic, name in names.items()
                              if name and fnmatch.fnmatch(name, pattern)),
                             key=lambda t: self._name_sort_key(names[t]))
            if not matched:
                # Also allow a raw topic, so a legacy recording and a hand-written
                # config that names one still work.
                matched = [t for t in self.database.get_recording_topics(recording_id)
                           if t == pattern]
            if not matched:
                logger.info(f"No feed matches {pattern!r} in recording {recording_id}")
            found.extend(t for t in matched if t not in found)
        return found

    def _last_feed_value(self, recording_id: int, pattern: str) -> Optional[float]:
        """The final reading of the first feed matching `pattern`, or None."""
        topics = self._resolve_feeds(recording_id, [pattern])
        if not topics:
            return None
        data = self._get_topic_data(recording_id, topics[0])
        return data[1][-1] if data and data[1] else None

    @staticmethod
    def _name_sort_key(name: str) -> tuple:
        """Natural sort: 'cellVoltage 2' before 'cellVoltage 10'."""
        return tuple((int(part), '') if part.isdigit() else (0, part)
                     for part in re.split(r'(\d+)', name or ''))

    def _feed_name(self, recording_id: int, topic: str) -> Optional[str]:
        """'Main Battery / power' for a topic, or None if it carries no envelope.

        Mirrors emon_feed.feed_key. A derived feed (emon_live's derived.yml) carries no
        group or name at all: it is keyed 'derived/<id>' off the id in its field, which
        is how 'derived/boat/heel' is written in a chart's `feeds`.
        """
        envelope = self._feed_index(recording_id).get(topic)
        if not envelope:
            return None
        if envelope.get('node') == 'derived':
            field = envelope.get('field', '')
            return f"derived/{field}" if field else None
        group, name = envelope.get('group', ''), envelope.get('name', '')
        if group and name:
            return f"{group} / {name}"
        return name or None

    # === GPS Track Reading ===
    #
    # One place builds a track, and everything that needs one uses it: route
    # maps, KML, GPX and the distance statistic. There used to be four separate
    # joins of the latitude and longitude topics, two of them duplicated
    # forward-fill loops, and they did not agree with each other.
    #
    # The position topic is now the only source. It carries lat, lon and the fix time in
    # one payload precisely so the two halves of a fix cannot be sampled either side of
    # it, and the separate latitude and longitude topics it replaced are no longer read
    # (owner's decision, 2 Nov 2026). A recording made before the publisher changed, and
    # so holding only the pair, no longer yields a track.

    @staticmethod
    def _nearest_index(sorted_times: List[datetime], target: datetime,
                       tolerance: timedelta) -> Optional[int]:
        """Index of the closest timestamp within tolerance, or None."""
        idx = bisect.bisect_left(sorted_times, target)
        best = None
        for candidate_idx in [idx - 1, idx]:
            if 0 <= candidate_idx < len(sorted_times):
                diff = abs(sorted_times[candidate_idx] - target)
                if diff <= tolerance:
                    if best is None or diff < abs(sorted_times[best] - target):
                        best = candidate_idx
        return best

    def _find_gps_streams(self, recording_id: int) -> List['GpsStream']:
        """
        Find each GPS unit's position and speed topics in a recording.

        A unit is identified by its subnode, so a recording from two receivers yields two
        streams. Envelopes are matched on "field", which says what a reading is without
        the topic having to spell it: emon/gps/0/position and the legacy gps/position/0
        both resolve to the same stream. Legacy topics, which carry no envelope, fall
        back to the topic text.

        Args:
            recording_id: Recording ID

        Returns:
            List of GpsStream, ordered by subnode
        """
        feeds = self._feed_index(recording_id)

        positions, speeds = {}, {}
        for topic in self.database.get_recording_topics(recording_id):
            envelope = feeds.get(topic)
            if envelope is not None:
                if envelope.get('node') != 'gps':
                    continue
                field = envelope.get('field', '')
                key = str(envelope.get('sub', ''))
            else:
                lowered = topic.lower()
                if not lowered.startswith('gps/'):
                    continue
                field = ('position' if 'position' in lowered
                         else 'speed' if 'speed' in lowered else '')
                key = topic.rsplit('/', 1)[-1]
            if field == 'position':
                positions[key] = topic
            elif field == 'speed':
                speeds[key] = topic

        return [GpsStream(key=key, position=positions[key], speed=speeds.get(key))
                for key in sorted(positions)]

    def _stream_coordinate_topics(self, recording_id: int,
                                  stream: 'GpsStream') -> List[str]:
        """The stream's latitude and longitude topics, which the map supersedes."""
        found = []
        for topic, envelope in self._feed_index(recording_id).items():
            if (envelope.get('node') == 'gps'
                    and str(envelope.get('sub', '')) == stream.key
                    and envelope.get('field') in ('latitude', 'longitude')):
                found.append(topic)
        # Legacy recordings name them directly.
        for topic in self.database.get_recording_topics(recording_id):
            lowered = topic.lower()
            if (lowered.startswith('gps/')
                    and ('latitude' in lowered or 'longitude' in lowered)
                    and topic.rsplit('/', 1)[-1] == stream.key):
                found.append(topic)
        return found

    def _stream_for_topics(self, recording_id: int,
                           topics: List[str]) -> Optional['GpsStream']:
        """
        Resolve a plot spec's topic list to a GPS stream.

        Matched on the subnode, the last path component, so a spec naming the legacy
        gps/position/0 still resolves to the recording's emon/gps/0/position. A spec
        that matches nothing gets the first stream, as before.

        Args:
            recording_id: Recording ID
            topics: Topics from the plot spec

        Returns:
            The matching GpsStream, or None
        """
        streams = self._find_gps_streams(recording_id)
        if not streams:
            return None
        wanted = {t.rsplit('/', 1)[-1] for t in topics if t}
        for stream in streams:
            if stream.key in wanted:
                return stream
        return streams[0]

    def _get_track(self, recording_id: int, stream: 'GpsStream') -> List['TrackFix']:
        """
        Read one GPS stream as a list of fixes, oldest first.

        Args:
            recording_id: Recording ID
            stream: The stream to read

        Returns:
            List of TrackFix. Speed is None where no reading matched.
        """
        fixes = self._read_position_topic(recording_id, stream.position)

        if not fixes:
            return []
        return self._attach_speeds(recording_id, stream, fixes)

    def _read_position_topic(self, recording_id: int,
                             topic: str) -> List['TrackFix']:
        """
        Read fixes from a gps/position/<n> topic.

        The payload is one JSON object per fix, {"lat":.., "lon":.., "ts":..},
        so there is nothing to join: both halves of the fix were sampled
        together by the publisher. `ts` is the fix time in epoch seconds; the
        row's own timestamp is when it arrived here, and is what speed readings
        are matched against, since those are stamped on arrival too.

        A payload that is not an object with two finite numbers is skipped
        rather than raising. There is no sentinel for "no fix": the publisher
        omits the topic entirely.

        Args:
            recording_id: Recording ID
            topic: The position topic

        Returns:
            List of TrackFix without speeds
        """
        rows = self.database.get_recording_data(recording_id, topic_filter=topic)
        fixes = []
        skipped = 0
        for record in rows or []:
            try:
                payload = record['payload']
                if isinstance(payload, (bytes, bytearray)):
                    payload = payload.decode('utf-8', 'replace')
                fix = _payload_object(payload)
                if fix is None:
                    raise ValueError('not a position payload')
                lat = float(fix['lat'])
                lon = float(fix['lon'])
                if not (math.isfinite(lat) and math.isfinite(lon)):
                    raise ValueError('non-finite position')

                arrived = record['timestamp']
                if isinstance(arrived, str):
                    arrived = datetime.fromisoformat(arrived)

                # The legacy payload puts the fix time in "ts" beside lat and lon; an
                # envelope carries the reading's own "t" instead, and its "v" holds only
                # the position. Both are epoch seconds.
                fix_time = None
                envelope = _envelope(payload)
                raw_ts = fix.get('ts') if envelope is None else envelope.get('t')
                if isinstance(raw_ts, (int, float)) and math.isfinite(raw_ts):
                    try:
                        # utcfromtimestamp, not fromtimestamp: the exports label
                        # this time 'Z', so it has to actually be UTC and not
                        # whatever the container's timezone renders it as.
                        fix_time = datetime.utcfromtimestamp(float(raw_ts))
                    except (OverflowError, OSError, ValueError):
                        fix_time = None

                fixes.append(TrackFix(ts=arrived, fix_ts=fix_time,
                                      lat=lat, lon=lon, sog=None))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                skipped += 1
                continue

        if skipped:
            logger.warning(f"{topic}: skipped {skipped} unreadable position payload(s)")
        fixes.sort(key=lambda f: f.ts)
        return fixes

    def _attach_speeds(self, recording_id: int, stream: 'GpsStream',
                       fixes: List['TrackFix']) -> List['TrackFix']:
        """
        Match speed over ground onto each fix.

        Speed is its own topic whichever way position arrives, so this is the
        one join that remains. Matched against the arrival timestamp, because
        that is what the speed rows carry.

        Args:
            recording_id: Recording ID
            stream: The stream being read
            fixes: Fixes without speeds

        Returns:
            The same fixes, with speeds where one matched
        """
        if not stream.speed:
            logger.info(f"No speed topic for GPS {stream.key}; "
                        "track will not be coloured")
            return fixes

        speed_data = self._get_topic_data(recording_id, stream.speed)
        if not speed_data:
            return fixes

        speed_pairs = sorted(zip(*speed_data), key=lambda p: p[0])
        speed_times = [p[0] for p in speed_pairs]

        out = []
        for fix in fixes:
            idx = self._nearest_index(speed_times, fix.ts, self.GPS_MATCH_TOLERANCE)
            out.append(fix._replace(
                sog=speed_pairs[idx][1] if idx is not None else None))
        return out

    def _get_gps_track(self, recording_id: int, topics: List[str]
                       ) -> Tuple[List[Tuple[float, float]], List[Optional[float]]]:
        """
        Get coordinates and the speed at each of them, for a plot spec.

        Args:
            recording_id: Recording ID
            topics: Topics from the plot spec, position or latitude/longitude

        Returns:
            Tuple of (coordinates, speeds in knots with None where unknown),
            the two the same length
        """
        stream = self._stream_for_topics(recording_id, topics)
        if stream is None:
            return [], []
        fixes = self._get_track(recording_id, stream)
        return ([(f.lat, f.lon) for f in fixes], [f.sog for f in fixes])

    def _get_gps_coordinates(self, recording_id: int,
                             topics: List[str]) -> List[Tuple[float, float]]:
        """
        Get GPS coordinates from a recording.

        Args:
            recording_id: Recording ID
            topics: Topics from the plot spec, position or latitude/longitude

        Returns:
            List of (latitude, longitude) tuples
        """
        return self._get_gps_track(recording_id, topics)[0]

    # === Export File Generation ===

    def _auto_generate_export_config(self, recording_id: int) -> Dict:
        """
        Auto-generate export config: KML/GPX when a track exists, no CSV.

        This is what automatic processing gets, because a recording does not
        record which event started it and so cannot reach that event's
        exports: section. Every event config turns CSV off (a full day is a
        quarter-gigabyte, more than the uplink can publish), and the default
        of CSV on went on writing one anyway. Ask for it explicitly through
        the process endpoint's export_config when it is wanted.
        """
        has_gps = bool(self._find_gps_streams(recording_id))
        return {'csv': False, 'kml': has_gps, 'gpx': has_gps}

    def generate_csv_export(self, recording_id: int, output_dir: Path) -> Optional[Path]:
        """
        Generate a merged time-series CSV for all topics in the recording.

        Each row is one unique timestamp; topic values are forward-filled.
        """
        topics = self.database.get_recording_topics(recording_id)
        if not topics:
            return None

        all_data = self.database.get_recording_data(recording_id)
        if not all_data:
            return None

        output_path = output_dir / 'data_export.csv'
        try:
            ts_map = defaultdict(dict)
            for row in all_data:
                ts_map[row['timestamp']][row['topic']] = row['payload']

            sorted_timestamps = sorted(ts_map.keys())
            fieldnames = ['timestamp'] + sorted(topics)

            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                current_values = {t: '' for t in topics}
                for ts in sorted_timestamps:
                    current_values.update(ts_map[ts])
                    row = {'timestamp': ts}
                    row.update(current_values)
                    writer.writerow(row)

            logger.info(f"CSV export: {output_path} ({len(sorted_timestamps)} rows)")
            return output_path
        except Exception as e:
            logger.error(f"CSV export failed: {e}")
            return None

    def generate_kml_exports(self, recording_id: int, output_dir: Path) -> List[Path]:
        """Generate one KML file per GPS stream."""
        streams = self._find_gps_streams(recording_id)
        output_paths = []

        for i, stream in enumerate(streams):
            try:
                fixes = self._get_track(recording_id, stream)
                coords = [(f.lon, f.lat) for f in fixes]   # (lon, lat) for KML

                if len(coords) < 2:
                    continue

                kml = ET.Element('kml', xmlns='http://www.opengis.net/kml/2.2')
                doc = ET.SubElement(kml, 'Document')
                name_el = ET.SubElement(doc, 'name')
                name_el.text = 'Route Map' if len(streams) == 1 else f'Route Map {i}'
                pm = ET.SubElement(doc, 'Placemark')
                ET.SubElement(pm, 'name').text = f'Track {i}' if len(streams) > 1 else 'Track'
                ls = ET.SubElement(pm, 'LineString')
                ET.SubElement(ls, 'tessellate').text = '1'
                ET.SubElement(ls, 'coordinates').text = '\n'.join(
                    f'{lon},{lat},0' for lon, lat in coords
                )

                pretty = minidom.parseString(ET.tostring(kml, encoding='unicode')).toprettyxml(indent='  ')
                filename = 'route_map.kml' if len(streams) == 1 else f'route_map_{i}.kml'
                output_path = output_dir / filename
                output_path.write_text(pretty, encoding='utf-8')
                output_paths.append(output_path)
                logger.info(f"KML export: {output_path} ({len(coords)} points)")

            except Exception as e:
                logger.error(f"KML export failed for stream {stream.key}: {e}")

        return output_paths

    def generate_gpx_export(self, recording_id: int, output_dir: Path) -> Optional[Path]:
        """
        Generate a single GPX file with all GPS streams as named tracks.

        Speed and other gps/* extension topics are included in <extensions>.
        """
        streams = self._find_gps_streams(recording_id)
        if not streams:
            return None

        # The GPS unit's other readings: course, speed and anything else it sends, but
        # not the position itself, which is the track. An envelope names its node, so
        # emon/gps/<n>/<field> is recognised by that rather than by the topic prefix.
        feeds = self._feed_index(recording_id)
        ext_topics = []
        for topic in self.database.get_recording_topics(recording_id):
            envelope = feeds.get(topic)
            if envelope is not None:
                if envelope.get('node') == 'gps' and envelope.get('field') != 'position':
                    ext_topics.append(topic)
                continue
            lowered = topic.lower()
            if (lowered.startswith('gps/')
                    and 'latitude' not in lowered
                    and 'longitude' not in lowered
                    and 'position' not in lowered):
                ext_topics.append(topic)
        # Timestamps parsed to datetimes, not left as the strings the database
        # returns. They are forward-filled against a fix's arrival time below,
        # and that is a datetime; comparing it with a string would either raise
        # or, if both were stringified, compare "09:00:00" against
        # "09:00:00.123" lexicographically and pick the wrong reading.
        ext_data = {}
        for topic in ext_topics:
            rows = self.database.get_recording_data(recording_id, topic_filter=topic)
            series = []
            for record in rows or []:
                stamp = record['timestamp']
                if isinstance(stamp, str):
                    try:
                        stamp = datetime.fromisoformat(stamp)
                    except ValueError:
                        continue
                series.append((stamp, record['payload']))
            if series:
                ext_data[topic] = sorted(series, key=lambda p: p[0])

        gpx = ET.Element('gpx', {
            'version': '1.1',
            'creator': 'emon_Suite event_recorder',
            'xmlns': 'http://www.topografix.com/GPX/1/1',
        })

        recording = self.database.get_recording(recording_id)
        meta = ET.SubElement(gpx, 'metadata')
        ET.SubElement(meta, 'name').text = recording.get('name', f'Recording {recording_id}')
        ET.SubElement(meta, 'time').text = str(recording.get('start_time', ''))

        for i, stream in enumerate(streams):
            fixes = self._get_track(recording_id, stream)
            if not fixes:
                continue

            ext_series = {topic: list(series) for topic, series in ext_data.items()}
            ext_indices = {topic: 0 for topic in ext_series}

            trk = ET.SubElement(gpx, 'trk')
            ET.SubElement(trk, 'name').text = f'Track {i}' if len(streams) > 1 else 'Track'
            trkseg = ET.SubElement(trk, 'trkseg')

            for fix in fixes:
                # The extension topics are stamped on arrival, so they are
                # forward-filled against that and not against the fix time.
                ts = fix.ts
                trkpt = ET.SubElement(trkseg, 'trkpt',
                                      lat=f'{fix.lat:.8f}', lon=f'{fix.lon:.8f}')
                # The receiver's own fix time when there is one, which is more
                # accurate than when the message reached this service.
                stamped = fix.fix_ts or fix.ts
                ET.SubElement(trkpt, 'time').text = \
                    stamped.isoformat(sep='T', timespec='seconds') + 'Z'

                # Elevation if available
                for topic, series in ext_series.items():
                    if 'altitude' in topic.lower() or 'elevation' in topic.lower():
                        idx = ext_indices[topic]
                        while idx + 1 < len(series) and series[idx + 1][0] <= ts:
                            idx += 1
                        ext_indices[topic] = idx
                        if series:
                            ET.SubElement(trkpt, 'ele').text = str(series[idx][1])
                        break

                # Other extensions
                ext_values = {}
                for topic, series in ext_series.items():
                    if 'altitude' in topic.lower() or 'elevation' in topic.lower():
                        continue
                    idx = ext_indices[topic]
                    while idx + 1 < len(series) and series[idx + 1][0] <= ts:
                        idx += 1
                    ext_indices[topic] = idx
                    if series:
                        tag = '_'.join(topic.split('/')[1:]).replace('/', '_') or topic.replace('/', '_')
                        ext_values[tag] = str(series[idx][1])

                if ext_values:
                    extensions = ET.SubElement(trkpt, 'extensions')
                    for tag, value in ext_values.items():
                        ET.SubElement(extensions, tag).text = value

        if not gpx.findall('trk'):
            return None

        xml_str = '<?xml version="1.0" encoding="UTF-8"?>' + ET.tostring(gpx, encoding='unicode')
        pretty = minidom.parseString(xml_str).toprettyxml(indent='  ')
        # Remove the extra declaration minidom adds
        lines = pretty.splitlines()
        if lines and lines[0].startswith('<?xml'):
            lines = lines[1:]
        pretty = '<?xml version="1.0" encoding="UTF-8"?>\n' + '\n'.join(lines)

        output_path = output_dir / 'track.gpx'
        output_path.write_text(pretty, encoding='utf-8')
        logger.info(f"GPX export: {output_path}")
        return output_path

    def calculate_statistics(self, recording_id: int) -> Dict:
        """
        Calculate statistics for recording.

        Args:
            recording_id: Recording ID

        Returns:
            Dict with statistics
        """
        stats = {}

        # Get recording info
        recording = self.database.get_recording(recording_id)
        if not recording:
            return stats

        # Duration
        start_time = recording['start_time']
        end_time = recording['end_time']

        if isinstance(start_time, str):
            start_time = datetime.fromisoformat(start_time)
        if end_time and isinstance(end_time, str):
            end_time = datetime.fromisoformat(end_time)

        local_start = self._utc_to_local(start_time)
        local_end = self._utc_to_local(end_time)
        stats['start_time'] = local_start.strftime('%Y-%m-%d %H:%M:%S') if local_start else ''
        stats['end_time'] = local_end.strftime('%Y-%m-%d %H:%M:%S') if local_end else ''

        if end_time:
            duration = end_time - start_time
            stats['duration'] = str(duration).split('.')[0]  # Remove microseconds
            stats['duration_seconds'] = duration.total_seconds()

        # Message count
        stats['message_count'] = self.database.get_recording_data_count(recording_id)

        # GPS-based statistics
        gps_stats = self._calculate_gps_statistics(recording_id)
        stats.update(gps_stats)

        # Energy statistics
        energy_stats = self._calculate_energy_statistics(recording_id)
        stats.update(energy_stats)

        # The pack's lifetime cycle count. A slowly-rising counter, so the last value is
        # the fact worth keeping; it was a chart of a near-flat line, which said less
        # than one number in the table.
        cycles = self._last_feed_value(recording_id, 'Main Battery / lifetimeCycles')
        if cycles is not None:
            stats['battery_cycles'] = cycles

        # Efficiency needs both, so it is computed here rather than inside either.
        # It used to be computed inside _calculate_energy_statistics against that
        # function's own local dict, which never holds distance_km: that arrives from
        # _calculate_gps_statistics and is merged above. The test was therefore never
        # true and the post template's {efficiency} has never had a value.
        if stats.get('distance_km', 0) > 0 and 'energy_used_wh' in stats:
            stats['efficiency_wh_per_km'] = stats['energy_used_wh'] / stats['distance_km']

        return stats

    def _calculate_gps_statistics(self, recording_id: int) -> Dict:
        """Calculate GPS-based statistics (distance, speed)."""
        stats = {}

        # The first GPS stream in the recording, whichever topics it uses. Not a
        # hardcoded gps/latitude/0, which found nothing in a recording that has
        # only gps/position/0 and so silently reported no distance travelled.
        streams = self._find_gps_streams(recording_id)
        if not streams:
            return stats
        coords = [(f.lat, f.lon) for f in self._get_track(recording_id, streams[0])]

        if len(coords) < 2:
            return stats

        # Calculate total distance using Haversine
        total_distance = 0
        for i in range(1, len(coords)):
            lat1, lon1 = coords[i-1]
            lat2, lon2 = coords[i]
            distance = self._haversine_distance(lat1, lon1, lat2, lon2)
            total_distance += distance

        stats['distance_km'] = total_distance / 1000  # Convert to km

        # Speed from the same stream the track came from, rather than a hardcoded
        # gps/speed/0, which names neither the envelope topic nor a second receiver's.
        speed_data = (self._get_topic_data(recording_id, streams[0].speed)
                      if streams[0].speed else None)
        if speed_data:
            timestamps, speeds = speed_data
            stats['max_speed'] = max(speeds)
            stats['avg_speed'] = sum(speeds) / len(speeds)

        return stats

    def _power_topic(self, recording_id: int) -> Optional[str]:
        """The topic carrying battery power, or None if the recording has none."""
        topics = self.database.get_recording_topics(recording_id)
        if 'battery/power/0/0' in topics:
            return 'battery/power/0/0'

        for topic, envelope in sorted(self._feed_index(recording_id).items()):
            if envelope.get('kind') == 'power' and envelope.get('node') == 'bms':
                logger.info(f"Energy statistics from {self._feed_name(recording_id, topic)}")
                return topic
        return None

    def _calculate_energy_statistics(self, recording_id: int) -> Dict:
        """Calculate energy consumption statistics."""
        stats = {}

        # The battery power feed. battery/power/0/0 is the shunt topic and is kept for
        # recordings that have it, but the boat has no shunt: its pack reports over the
        # BMS, so an envelope whose kind is 'power' on the bms node is used instead.
        topic = self._power_topic(recording_id)
        if not topic:
            return stats
        power_data = self._get_topic_data(recording_id, topic)
        if not power_data:
            return stats

        timestamps, powers = power_data

        # Calculate energy using trapezoidal integration
        total_energy = 0
        for i in range(1, len(timestamps)):
            dt = (timestamps[i] - timestamps[i-1]).total_seconds() / 3600  # hours
            avg_power = (powers[i] + powers[i-1]) / 2
            total_energy += avg_power * dt

        stats['energy_used_wh'] = abs(total_energy)

        # Efficiency is not computed here: it needs distance_km, which this function has
        # no access to. See _calculate_statistics, where the two are merged.
        return stats

    def _haversine_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two GPS points (meters)."""
        R = 6371000  # Earth radius in meters

        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)

        a = (math.sin(delta_lat / 2) ** 2 +
             math.cos(lat1_rad) * math.cos(lat2_rad) *
             math.sin(delta_lon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c


def main():
    """CLI for testing data processor."""
    import argparse

    parser = argparse.ArgumentParser(description="Data Processor Test")
    parser.add_argument('--db', default='/data/recordings.db', help="Database path")
    parser.add_argument('--recording-id', type=int, required=True, help="Recording ID to process")
    parser.add_argument('--plots-dir', default='/tmp/plots', help="Plots output directory")

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(level=logging.INFO,
                       format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    from .models import Database
    db = Database(args.db)
    processor = DataProcessor(db, args.plots_dir)

    # Example plot config
    plot_config = [
        {'type': 'line', 'title': 'Speed', 'topics': ['gps/speed/0'], 'ylabel': 'Speed (km/h)'},
        {'type': 'multi_line', 'title': 'Battery Power', 'topics': ['battery/power/0/0', 'battery/power/0/1'],
         'labels': ['Bank 1', 'Bank 2'], 'ylabel': 'Power (W)'},
        {'type': 'map', 'title': 'Route Map', 'topics': ['gps/latitude/0', 'gps/longitude/0']}
    ]

    results = processor.process_recording(args.recording_id, plot_config)

    print("\nProcessing Results:")
    print(f"  Status: {results['status']}")
    print(f"  Plots generated: {len(results['plots'])}")
    for plot in results['plots']:
        print(f"    - {plot}")
    print(f"\nStatistics:")
    for key, value in results['statistics'].items():
        print(f"    {key}: {value}")


if __name__ == '__main__':
    main()
