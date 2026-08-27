"""
Data processor for generating plots and statistics from recorded data.

Uses matplotlib for time-series plots and for GPS route maps, which are drawn
over the offline vector chart fetched from enchantee_racing (see chart_map.py)
and coloured by speed over ground. folium still writes an interactive
OpenStreetMap view alongside, for the WordPress post.
Calculates statistics including distance, speed, energy consumption.
"""

import bisect
import csv
import logging
import math
import os
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta
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
from .models import Database, RecordingStatus, ImageType

logger = logging.getLogger(__name__)


class GpsStream(NamedTuple):
    """One GPS unit's topics in a recording.

    `position` is gps/position/<key> and is preferred: it carries lat, lon and
    the fix time in one payload. `latitude`/`longitude` are the older pair, kept
    because recordings already in the database have only those.
    """

    key: str                      # the subnode, '0' or '1', which names outputs
    position: Optional[str]
    latitude: Optional[str]
    longitude: Optional[str]
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

    # Axis labels used for 3-axis sensors (acc / gyro / mag).
    _AXIS_LABELS: Dict[int, str] = {0: 'X', 1: 'Y', 2: 'Z'}
    _AXIS_TOPICS: frozenset = frozenset({'acc', 'gyro', 'mag'})

    # Colour cycle for auto-generated series.
    _AUTO_COLORS: List[str] = [
        '#667eea', '#e05c5c', '#48cae4', '#f72585',
        '#2ec4b6', '#ff9f1c', '#a8dadc', '#6d6875',
    ]

    # ─────────────────────────────────────────────────────────────────────────

    def __init__(self, database: Database, plots_dir: str = "/data/plots",
                 charts_config: Dict = None):
        """
        Initialize data processor.

        Args:
            database: Database instance
            plots_dir: Directory for plot output
            charts_config: The `charts` service config section, for the offline
                basemap fetched from enchantee_racing. None uses defaults.
        """
        self.database = database
        self.plots_dir = Path(plots_dir)
        self.plots_dir.mkdir(parents=True, exist_ok=True)

        # How far apart two readings may be and still belong to the same fix.
        # Only used for the topics that genuinely arrive separately: speed, and
        # latitude/longitude in recordings made before gps/position existed.
        self.GPS_MATCH_TOLERANCE = timedelta(seconds=5)

        # Plot defaults
        self.default_dpi = 150
        self.default_width = 12
        self.default_height = 6
        self.default_style = 'seaborn-v0_8'

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

    def _auto_generate_plot_config(self, recording_id: int) -> List[Dict]:
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
        topics = self.database.get_recording_topics(recording_id)
        if not topics:
            return []

        plot_config = []
        skip_topics: set = set()

        # ── 1. GPS position streams → route maps ──────────────────────────
        # One map per GPS unit. gps/position/<n> is preferred and needs no
        # pairing; the latitude/longitude topics are used for recordings made
        # before it existed. Whichever a stream uses, its topics are taken off
        # the list below: a latitude plotted against time is not a chart anyone
        # asked for.
        streams = self._find_gps_streams(recording_id)
        for i, stream in enumerate(streams):
            title = 'Route Map' if len(streams) == 1 else f'Route Map {i}'
            if stream.position:
                map_topics = [stream.position]
            else:
                map_topics = [stream.latitude, stream.longitude]
            plot_config.append({
                'type': 'map',
                'title': title,
                'topics': map_topics,
            })
            skip_topics.update(t for t in (stream.position, stream.latitude,
                                           stream.longitude) if t)

        # ── 2. Group remaining topics by structural prefix ─────────────────
        remaining = [t for t in topics if t not in skip_topics]
        groups: Dict[str, List[str]] = defaultdict(list)
        for topic in remaining:
            groups[self._topic_group_key(topic)].append(topic)

        # ── 3. Apply semantic merges (e.g. heading + course) ───────────────
        groups = self._apply_semantic_merges(dict(groups))

        # ── 4. Build one multi_line spec per group ─────────────────────────
        for group_topics in sorted(groups.values(), key=lambda g: g[0]):
            group_topics = sorted(group_topics)
            title   = self._group_plot_title(group_topics)
            ylabel  = self._group_ylabel(group_topics)
            labels  = self._group_series_labels(group_topics)
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

        logger.info(f"Auto-generated {len(plot_config)} plot configs from {len(topics)} topics")
        return plot_config

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

    def _topic_group_key(self, topic: str) -> str:
        """
        Return the grouping key for a topic.

        The key is the topic path with the trailing numeric channel/axis index
        stripped, so that anemometer/temperature/0,1,2 all map to the same
        key 'anemometer/temperature'.
        """
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

    def _group_plot_title(self, topics: List[str]) -> str:
        """
        Derive a chart title from the group of topics.

        Finds the longest common MQTT path prefix (ignoring numeric components)
        and converts it to a readable title.  When topics come from entirely
        different topic families (semantic merge), the distinct roots are
        joined with ' / '.
        """
        split_topics = [t.split('/') for t in topics]
        common: List[str] = []
        for components in zip(*split_topics):
            unique = set(components)
            if len(unique) == 1 and not list(unique)[0].isdigit():
                common.append(list(unique)[0])
            else:
                break

        if common:
            return ' '.join(self._readable_component(p) for p in common)

        # No common non-numeric prefix — combine root-level family names
        roots = sorted({t.split('/')[0] for t in topics})
        return ' / '.join(self._readable_component(r) for r in roots)

    def _group_ylabel(self, topics: List[str]) -> str:
        """
        Return the Y-axis label (with units) for a group of topics.

        Searches the combined topic strings for the first matching keyword
        in _TOPIC_UNITS.  Longer/more-specific keywords are tried first.
        """
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

    def _group_series_labels(self, topics: List[str]) -> List[str]:
        """
        Generate per-series legend labels for the topics in a group.

        Strategy:
        - Find the longest common MQTT path prefix shared by all topics.
        - When topics share a prefix (same family, different channel index):
            * Single trailing digit on a 3-axis sensor (acc/gyro/mag) → X/Y/Z
            * Single trailing digit on anything else → the digit as a string
            * Multi-part suffix → readable form of the suffix
        - When there is no common prefix (topics from different families,
          e.g. after a semantic merge) → full readable name for each topic.
        """
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
                          export_config: Dict = None) -> Dict:
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

        # Update status
        self.database.update_recording(recording_id, status=RecordingStatus.PROCESSING)

        try:
            # Create output directory for this recording
            output_dir = self.plots_dir / str(recording_id)
            output_dir.mkdir(parents=True, exist_ok=True)

            results = {
                'plots': [],
                'exports': [],
                'statistics': {},
                'status': 'success'
            }

            # Auto-generate plot config if none provided
            if not plot_config:
                plot_config = self._auto_generate_plot_config(recording_id)

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

            self.database.update_recording(recording_id, status=RecordingStatus.PROCESSED)
            return results

        except Exception as e:
            logger.error(f"Processing failed: {e}")
            self.database.update_recording(recording_id, status=RecordingStatus.FAILED)
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

        # Create plot
        fig, ax = plt.subplots(figsize=(self.default_width, self.default_height))

        ax.plot(timestamps, values, linewidth=2, color=color)
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
        filename = f"{title.replace(' ', '_').lower()}.png"
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

        for i, topic in enumerate(topics):
            data = self._get_topic_data(recording_id, topic)
            if data:
                timestamps, values = data
                label = labels[i] if i < len(labels) else topic
                color = colors[i % len(colors)]
                ax.plot(timestamps, values, linewidth=2, label=label, color=color)

        ax.set_title(title, fontsize=16, fontweight='bold')
        ax.set_xlabel('Time', fontsize=12)
        ax.set_ylabel(ylabel, fontsize=12)
        ax.grid(True, alpha=0.3)

        if show_legend:
            ax.legend(fontsize=10, loc='best')

        # Format x-axis
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        plt.xticks(rotation=45, ha='right')

        plt.tight_layout()

        # Save
        filename = f"{title.replace(' ', '_').lower()}.png"
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
        water and OpenStreetMap tiles are unreachable there. An interactive
        folium map is written alongside it, on a different filename stem, so the
        WordPress post still carries the OpenStreetMap view for anyone reading it
        ashore.

        Args:
            recording_id: Recording ID
            plot_spec: Plot specification
            output_dir: Output directory

        Returns:
            Path to generated map image
        """
        title = plot_spec.get('title', 'Route Map')
        topics = plot_spec.get('topics', ['gps/latitude/0', 'gps/longitude/0'])

        coords, speeds = self._get_gps_track(recording_id, topics)
        if not coords or len(coords) < 2:
            raise ValueError("Insufficient GPS data for route map")

        output_path = self._generate_chart_route_map(title, coords, speeds, output_dir)
        self._generate_osm_map_html(title, coords, output_dir)
        return output_path

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

        filename = f"{title.replace(' ', '_').lower()}.png"
        output_path = output_dir / filename
        plt.savefig(output_path, dpi=self.default_dpi, bbox_inches='tight')
        plt.close()

        logger.info(
            f"Generated route map: {filename} "
            f"(chart={'yes' if on_chart else 'no'}, "
            f"speed={'yes' if mappable is not None else 'no'})"
        )
        return output_path

    def _generate_osm_map_html(self, title: str,
                               coords: List[Tuple[float, float]],
                               output_dir: Path) -> Optional[Path]:
        """
        Write the interactive OpenStreetMap view for the WordPress post.

        Generating this needs no internet; only viewing it does, which is the
        WordPress reader's situation and not the boat's. Written with an `_osm`
        suffix so it does not share a filename stem with the chart PNG: the
        publisher drops any image whose stem matches a map HTML, and the chart
        map is the one that must reach the post.

        Args:
            title: Plot title
            coords: List of (latitude, longitude)
            output_dir: Output directory

        Returns:
            Path to the HTML file, or None if folium is unavailable
        """
        try:
            import folium
        except ImportError:
            logger.info("folium not installed; no interactive map for WordPress")
            return None

        try:
            center_lat = sum(lat for lat, lon in coords) / len(coords)
            center_lon = sum(lon for lat, lon in coords) / len(coords)

            m = folium.Map(location=[center_lat, center_lon], zoom_start=14)
            folium.PolyLine(coords, color='#667eea', weight=4, opacity=0.8).add_to(m)
            folium.Marker(coords[0], popup='Start',
                          icon=folium.Icon(color='green', icon='play')).add_to(m)
            folium.Marker(coords[-1], popup='End',
                          icon=folium.Icon(color='red', icon='stop')).add_to(m)
            m.fit_bounds(coords)

            stem = f"{title.replace(' ', '_').lower()}_osm"
            html_path = output_dir / f"{stem}.html"
            m.save(str(html_path))
            logger.info(f"Generated interactive OSM map: {html_path.name}")
            return html_path
        except Exception as e:
            logger.warning(f"Could not generate interactive OSM map: {e}")
            return None

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
            table_data.append(['Max Speed', f"{statistics['max_speed']:.1f} km/h"])
        if 'avg_speed' in statistics:
            table_data.append(['Avg Speed', f"{statistics['avg_speed']:.1f} km/h"])

        # Add energy stats
        if 'energy_used_wh' in statistics:
            table_data.append(['Energy Used', f"{statistics['energy_used_wh']:.1f} Wh"])
        if 'efficiency_wh_per_km' in statistics:
            table_data.append(['Efficiency', f"{statistics['efficiency_wh_per_km']:.1f} Wh/km"])

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

                value = float(record['payload'])

                timestamps.append(timestamp)
                values.append(value)
            except (ValueError, KeyError):
                continue

        if not timestamps:
            return None

        return (timestamps, values)

    # === GPS Track Reading ===
    #
    # One place builds a track, and everything that needs one uses it: route
    # maps, KML, GPX and the distance statistic. There used to be four separate
    # joins of the latitude and longitude topics, two of them duplicated
    # forward-fill loops, and they did not agree with each other.
    #
    # gps/position/<n> is the preferred source and needs no join at all: it
    # carries lat, lon and the fix time in one JSON payload precisely so the two
    # halves of a fix cannot be sampled either side of it. The separate
    # gps/latitude/<n> and gps/longitude/<n> topics are still read, because every
    # recording made before the publisher was changed has only those, and a
    # recording already in the database must stay processable.

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
        Find each GPS unit's topics in a recording.

        A unit is identified by the subnode on the end of its topics, so a
        recording from two receivers yields two streams. gps/position/<n> wins
        over the latitude/longitude pair for the same subnode.

        Args:
            recording_id: Recording ID

        Returns:
            List of GpsStream, ordered by subnode
        """
        topics = self.database.get_recording_topics(recording_id)

        positions, latitudes, longitudes, speeds = {}, {}, {}, {}
        for topic in topics:
            lowered = topic.lower()
            key = topic.rsplit('/', 1)[-1]
            if 'position' in lowered:
                positions[key] = topic
            elif 'latitude' in lowered:
                latitudes[key] = topic
            elif 'longitude' in lowered:
                longitudes[key] = topic
            elif 'speed' in lowered:
                speeds[key] = topic

        streams = []
        for key in sorted(set(positions) | set(latitudes)):
            position = positions.get(key)
            latitude = latitudes.get(key)
            longitude = longitudes.get(key)
            if not position and not (latitude and longitude):
                # A latitude with no longitude and no position is not a track.
                continue
            streams.append(GpsStream(key=key, position=position,
                                     latitude=latitude, longitude=longitude,
                                     speed=speeds.get(key)))
        return streams

    def _stream_for_topics(self, recording_id: int,
                           topics: List[str]) -> Optional['GpsStream']:
        """
        Resolve a plot spec's topic list to a GPS stream.

        A spec may name a position topic, or a latitude/longitude pair, because
        an event config written by hand can say either and older configs say the
        pair. Matched on the subnode so a spec naming the legacy pair still gets
        the position topic when the recording has one.

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
        if stream.position:
            fixes = self._read_position_topic(recording_id, stream.position)
        else:
            fixes = self._read_latlon_topics(recording_id, stream)

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
                fix = json.loads(payload) if isinstance(payload, str) else payload
                lat = float(fix['lat'])
                lon = float(fix['lon'])
                if not (math.isfinite(lat) and math.isfinite(lon)):
                    raise ValueError('non-finite position')

                arrived = record['timestamp']
                if isinstance(arrived, str):
                    arrived = datetime.fromisoformat(arrived)

                fix_time = None
                raw_ts = fix.get('ts')
                if isinstance(raw_ts, (int, float)) and math.isfinite(raw_ts):
                    try:
                        fix_time = datetime.fromtimestamp(float(raw_ts))
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

    def _read_latlon_topics(self, recording_id: int,
                            stream: 'GpsStream') -> List['TrackFix']:
        """
        Read fixes by joining the separate latitude and longitude topics.

        For recordings made before gps/position/<n> existed. Latitude and
        longitude arrive as two messages whose timestamps differ by
        milliseconds, so they are matched nearest-neighbour within a tolerance;
        exact equality almost never matches. A latitude with no longitude inside
        the window is dropped, which is why this returns whole fixes rather than
        two lists a caller might zip together and misalign.

        Args:
            recording_id: Recording ID
            stream: The stream to read

        Returns:
            List of TrackFix without speeds
        """
        lat_data = self._get_topic_data(recording_id, stream.latitude)
        lon_data = self._get_topic_data(recording_id, stream.longitude)
        if not lat_data or not lon_data:
            return []

        lat_pairs = sorted(zip(*lat_data), key=lambda p: p[0])
        lon_pairs = sorted(zip(*lon_data), key=lambda p: p[0])
        lon_times = [p[0] for p in lon_pairs]

        fixes = []
        for lat_ts, lat_value in lat_pairs:
            idx = self._nearest_index(lon_times, lat_ts, self.GPS_MATCH_TOLERANCE)
            if idx is None:
                continue
            fixes.append(TrackFix(ts=lat_ts, fix_ts=None, lat=lat_value,
                                  lon=lon_pairs[idx][1], sog=None))
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
        """Auto-generate export config: CSV always; KML/GPX when a track exists."""
        has_gps = bool(self._find_gps_streams(recording_id))
        return {'csv': True, 'kml': has_gps, 'gpx': has_gps}

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

        all_topics = self.database.get_recording_topics(recording_id)
        ext_topics = [
            t for t in all_topics
            if t.lower().startswith('gps/')
            and 'latitude' not in t.lower()
            and 'longitude' not in t.lower()
            and 'position' not in t.lower()
        ]
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

        stats['start_time'] = start_time.strftime('%Y-%m-%d %H:%M:%S') if start_time else ''
        stats['end_time'] = end_time.strftime('%Y-%m-%d %H:%M:%S') if end_time else ''

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

        # Get speed data
        speed_data = self._get_topic_data(recording_id, 'gps/speed/0')
        if speed_data:
            timestamps, speeds = speed_data
            stats['max_speed'] = max(speeds)
            stats['avg_speed'] = sum(speeds) / len(speeds)

        return stats

    def _calculate_energy_statistics(self, recording_id: int) -> Dict:
        """Calculate energy consumption statistics."""
        stats = {}

        # Get battery power data
        power_data = self._get_topic_data(recording_id, 'battery/power/0/0')
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

        # Calculate efficiency (Wh/km)
        if 'distance_km' in stats and stats['distance_km'] > 0:
            stats['efficiency_wh_per_km'] = stats['energy_used_wh'] / stats['distance_km']

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
