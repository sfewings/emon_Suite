"""
Offline basemap for GPS route maps, sourced from the enchantee_racing app.

The host has no internet on the water, so folium's OpenStreetMap tiles are
unreachable when a recording is processed on the boat. enchantee_racing already
carries a vector chart of the sailing area as GeoJSON and serves it at
/api/config/<name>, so this module fetches those documents, caches them on disk,
and draws them under a matplotlib route map.

The dependency is deliberately one-way and loose: read-only HTTP to one
endpoint, cached, and every failure degrades rather than raising. A recording
still plots on plain lat/lon axes if enchantee_racing has never been reachable,
which is also what happens when a track leaves the charted area.
"""

import json
import logging
import math
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Documents fetched from enchantee_racing, and the schema each must declare.
# The schema is a contract check, not decoration: these are generated files that
# have already changed shape once (depth is on its second version), and drawing
# a document whose properties have been renamed produces a blank layer rather
# than an error. A version bump here should be a deliberate edit to this table
# after checking what moved.
CHART_DOCUMENTS = {
    'coast': 'pfsyc-coast/1',
    'depth': 'pfsyc-depth/2',
    'structures': 'pfsyc-structures/1',
    'navaids': 'pfsyc-navaids/1',
    'marks': 'pfsyc-marks/2',
}

DEFAULT_BASE_URL = 'http://localhost:5002'
DEFAULT_TIMEOUT = 5

# Day-theme colours, transcribed from enchantee_racing/static/app.css so a
# printed route map and the chart on the boat's iPad look like the same chart.
# The depth band fills are NOT here: depth.json carries its own colours and
# gen_depth.py owns that palette.
LAND = '#e8e2d5'
LAND_EDGE = '#b8ac96'
CONTOUR = '#1c4f73'
MARK = '#4a5560'
STRUCTURE_COLOURS = {
    'jetty': '#6b5b45', 'bridge': '#3f3f3f', 'groyne': '#7a7a6a',
    'slipway': '#8a7f6a', 'marina': '#9aa7b1', 'breakwater': '#5a5a5a',
}
NAVAID_COLOURS = {
    'buoy_port': '#c62828', 'beacon_port': '#c62828',
    'buoy_starboard': '#1b7f3a', 'beacon_starboard': '#1b7f3a',
    'buoy_cardinal': '#1a1a1a', 'beacon_cardinal': '#1a1a1a',
    'buoy_danger': '#111111', 'beacon_danger': '#111111',
    'buoy_special': '#d4a017', 'beacon_special': '#d4a017',
    'leading': '#e07b00', 'light': '#7b1fa2',
}
NAVAID_DEFAULT = '#4a5560'

# Contour line weights by depth, matching the stylesheet's three cases.
CONTOUR_STYLES = {
    2.0: {'linewidth': 0.9, 'linestyle': '-', 'alpha': 1.0},
    5.0: {'linewidth': 0.6, 'linestyle': (0, (5, 4)), 'alpha': 0.85},
    10.0: {'linewidth': 0.6, 'linestyle': (0, (1, 3)), 'alpha': 0.7},
}

# Speed colouring. Fixed domain so a colour means a speed rather than a rank and
# two recordings can be compared; matches enchantee_racing/static/palette.js,
# which is generated from this same colormap.
SPEED_CMAP = 'viridis'
SPEED_MIN_KT = 0.0
SPEED_MAX_KT = 8.0


class ChartCache:
    """Fetches and caches the enchantee_racing chart documents."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL,
                 cache_dir: str = '/data/charts',
                 timeout: int = DEFAULT_TIMEOUT,
                 enabled: bool = True):
        """
        Initialize chart cache.

        Args:
            base_url: Base URL of the enchantee_racing app
            cache_dir: Directory holding the cached documents
            timeout: Per-request timeout in seconds
            enabled: When false, nothing is fetched and no chart is drawn
        """
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip('/')
        self.cache_dir = Path(cache_dir)
        self.timeout = timeout
        self.enabled = enabled

    @classmethod
    def from_config(cls, config: Optional[Dict], plots_dir: Path) -> 'ChartCache':
        """
        Build from the `charts` section of the service config.

        Args:
            config: The `charts` config section, or None for defaults
            plots_dir: Plot output directory; the cache sits beside it

        Returns:
            ChartCache instance
        """
        config = config or {}
        return cls(
            base_url=config.get('base_url') or os.environ.get('ENCHANTEE_URL')
            or DEFAULT_BASE_URL,
            cache_dir=config.get('cache_dir') or str(Path(plots_dir).parent / 'charts'),
            timeout=int(config.get('timeout') or DEFAULT_TIMEOUT),
            enabled=config.get('enabled', True),
        )

    def _path(self, name: str) -> Path:
        return self.cache_dir / f"{name}.json"

    def refresh(self) -> Dict[str, str]:
        """
        Fetch any chart document that has changed, keeping the cache otherwise.

        Called before processing rather than only at startup, so a chart
        regenerated on the boat is picked up without restarting this service.
        Conditional on mtime, so an unchanged chart costs one 304.

        Returns:
            Dict of document name to 'updated', 'unchanged', 'failed' or 'skipped'
        """
        if not self.enabled:
            return {name: 'skipped' for name in CHART_DOCUMENTS}

        try:
            import requests
        except ImportError:
            logger.warning("requests not installed, cannot refresh charts")
            return {name: 'failed' for name in CHART_DOCUMENTS}

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        results = {}

        for name, schema in CHART_DOCUMENTS.items():
            path = self._path(name)
            headers = {}
            if path.exists():
                stamp = _http_date(path.stat().st_mtime)
                if stamp:
                    headers['If-Modified-Since'] = stamp
            try:
                response = requests.get(
                    f"{self.base_url}/api/config/{name}",
                    headers=headers, timeout=self.timeout
                )
                if response.status_code == 304:
                    results[name] = 'unchanged'
                    continue
                response.raise_for_status()
                document = response.json()
                declared = str(document.get('schema', ''))
                if not _schema_ok(declared, schema):
                    logger.warning(
                        f"Chart '{name}' declares schema '{declared}', "
                        f"expected '{schema}'; keeping any cached copy"
                    )
                    results[name] = 'failed'
                    continue
                path.write_text(json.dumps(document), encoding='utf-8')
                results[name] = 'updated'
            except Exception as e:
                # Offline, enchantee_racing stopped, or a bad response. The
                # cached copy stands; a recording must still process.
                logger.info(f"Chart '{name}' not refreshed ({e}); using cache if present")
                results[name] = 'failed'

        return results

    def load(self) -> Optional[Dict]:
        """
        Load the cached chart documents.

        Returns:
            Dict of document name to parsed GeoJSON, or None if there is no
            usable chart. Coast is required: it carries the extent, and without
            it there is nothing to decide whether a track is on the chart at all.
        """
        if not self.enabled:
            return None

        charts = {}
        for name, schema in CHART_DOCUMENTS.items():
            path = self._path(name)
            if not path.exists():
                continue
            try:
                document = json.loads(path.read_text(encoding='utf-8'))
            except Exception as e:
                logger.warning(f"Cached chart '{name}' unreadable: {e}")
                continue
            if not _schema_ok(str(document.get('schema', '')), schema):
                logger.warning(f"Cached chart '{name}' has an unexpected schema; ignored")
                continue
            charts[name] = document

        if 'coast' not in charts:
            logger.info("No cached coastline; route maps will use plain axes")
            return None
        return charts


def _schema_ok(declared: str, expected: str) -> bool:
    """True when the declared schema matches the expected name and version."""
    parts = declared.split('/')
    return len(parts) == 2 and parts == expected.split('/')


def _http_date(mtime: float) -> Optional[str]:
    """Format an mtime as an HTTP date for If-Modified-Since."""
    try:
        from email.utils import formatdate
        return formatdate(mtime, usegmt=True)
    except Exception:
        return None


def chart_bbox(charts: Dict) -> Optional[Tuple[float, float, float, float]]:
    """
    The charted extent as (south, west, north, east).

    Args:
        charts: Loaded chart documents

    Returns:
        Bounding box tuple, or None when the coastline does not declare one
    """
    bbox = (charts.get('coast') or {}).get('bbox')
    if not isinstance(bbox, dict):
        return None
    try:
        return (float(bbox['south']), float(bbox['west']),
                float(bbox['north']), float(bbox['east']))
    except (KeyError, TypeError, ValueError):
        return None


def track_on_chart(coords: List[Tuple[float, float]], charts: Dict) -> bool:
    """
    Whether a track sits inside the charted area.

    Uses the 1st and 99th percentile of the track rather than its full extent,
    so a single wild fix cannot send an otherwise local track to plain axes.

    Args:
        coords: List of (latitude, longitude)
        charts: Loaded chart documents

    Returns:
        True when the chart should be drawn under this track
    """
    bbox = chart_bbox(charts)
    if not bbox or not coords:
        return False
    south, west, north, east = bbox
    lats = sorted(lat for lat, _ in coords)
    lons = sorted(lon for _, lon in coords)
    lo_lat, hi_lat = _percentile(lats, 0.01), _percentile(lats, 0.99)
    lo_lon, hi_lon = _percentile(lons, 0.01), _percentile(lons, 0.99)
    return (south <= lo_lat and hi_lat <= north
            and west <= lo_lon and hi_lon <= east)


def _percentile(sorted_values: List[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    idx = int(round(fraction * (len(sorted_values) - 1)))
    return sorted_values[max(0, min(idx, len(sorted_values) - 1))]


def draw_basemap(ax, charts: Dict, show_marks: bool = True) -> None:
    """
    Draw the chart under a route map, in the order the map page uses.

    Depth bands, then the contours dividing them, then land over both, then
    structures, aids and racing marks. Mark and aid names are deliberately not
    drawn: at track scale they cover the track, which is the subject.

    Args:
        ax: Matplotlib axes, in degrees (x=longitude, y=latitude)
        charts: Loaded chart documents
        show_marks: Draw racing mark symbols
    """
    depth = charts.get('depth')
    if depth:
        bands, contours = [], []
        for feature in depth.get('features', []):
            props = feature.get('properties', {})
            (bands if props.get('kind') == 'band' else contours).append(feature)

        # Deepest first so shallower bands draw over: they overlap at shared
        # edges and shallowest-darkest only reads if the shallow one wins.
        order = {'deepest': 0, 'deep': 1, 'mid': 2, 'shallow': 3, 'foreshore': 4}
        bands.sort(key=lambda f: order.get(f['properties'].get('band'), 0))
        for feature in bands:
            colour = feature['properties'].get('color') or '#d8e9f5'
            _fill(ax, feature['geometry'], colour, edge=None, zorder=1)
        for feature in contours:
            level = feature['properties'].get('depth_m')
            style = CONTOUR_STYLES.get(
                float(level) if isinstance(level, (int, float)) else -1,
                {'linewidth': 0.6, 'linestyle': '-', 'alpha': 0.8})
            _stroke(ax, feature['geometry'], CONTOUR, zorder=2, **style)

    coast = charts.get('coast')
    if coast:
        for feature in coast.get('features', []):
            _fill(ax, feature['geometry'], LAND, edge=LAND_EDGE, zorder=3,
                  linewidth=0.5)

    structures = charts.get('structures')
    if structures:
        for feature in structures.get('features', []):
            kind = feature['properties'].get('kind')
            colour = STRUCTURE_COLOURS.get(kind, '#7a7a6a')
            geometry = feature['geometry']
            if geometry.get('type') in ('Polygon', 'MultiPolygon'):
                _fill(ax, geometry, colour, edge=colour, zorder=4, linewidth=0.4)
            else:
                _stroke(ax, geometry, colour, zorder=4, linewidth=0.7, alpha=0.9)

    navaids = charts.get('navaids')
    if navaids:
        by_colour = {}
        for feature in navaids.get('features', []):
            props = feature.get('properties', {})
            # An aid that is also a racing mark is drawn once, and marks.json
            # wins because it carries the course data.
            if props.get('dup_mark'):
                continue
            coordinates = feature.get('geometry', {}).get('coordinates')
            if not coordinates or len(coordinates) < 2:
                continue
            colour = NAVAID_COLOURS.get(props.get('kind'), NAVAID_DEFAULT)
            by_colour.setdefault(colour, [[], []])
            by_colour[colour][0].append(coordinates[0])
            by_colour[colour][1].append(coordinates[1])
        for colour, (lons, lats) in by_colour.items():
            ax.plot(lons, lats, marker='.', linestyle='none', markersize=1.6,
                    color=colour, zorder=5, alpha=0.9)

    if show_marks and charts.get('marks'):
        lons, lats = [], []
        for mark in charts['marks'].get('marks', []):
            try:
                lons.append(float(mark['lon']))
                lats.append(float(mark['lat']))
            except (KeyError, TypeError, ValueError):
                continue
        if lons:
            # Bigger than the aid dots: these are the buoys the club races to,
            # and on a track-scale plot they are the landmarks worth reading.
            ax.plot(lons, lats, marker='o', linestyle='none', markersize=3.6,
                    markerfacecolor=MARK, markeredgecolor='#ffffff',
                    markeredgewidth=0.6, zorder=6)


def _rings_to_path(rings):
    """Build a matplotlib Path from GeoJSON rings, holes included."""
    from matplotlib.path import Path as MplPath

    vertices, codes = [], []
    for ring in rings:
        if len(ring) < 3:
            continue
        for i, point in enumerate(ring):
            vertices.append((point[0], point[1]))
            codes.append(MplPath.MOVETO if i == 0 else MplPath.LINETO)
        vertices.append((ring[0][0], ring[0][1]))
        codes.append(MplPath.CLOSEPOLY)
    if not vertices:
        return None
    return MplPath(vertices, codes)


def _fill(ax, geometry, colour, edge=None, zorder=1, linewidth=0.0):
    """Fill a GeoJSON Polygon or MultiPolygon, keeping holes as holes."""
    from matplotlib.patches import PathPatch

    kind = geometry.get('type')
    if kind == 'Polygon':
        groups = [geometry.get('coordinates') or []]
    elif kind == 'MultiPolygon':
        groups = geometry.get('coordinates') or []
    else:
        return

    for rings in groups:
        path = _rings_to_path(rings)
        if path is None:
            continue
        ax.add_patch(PathPatch(
            path, facecolor=colour, edgecolor=edge or 'none',
            linewidth=linewidth if edge else 0.0, zorder=zorder,
            antialiased=True))


def _stroke(ax, geometry, colour, zorder=2, linewidth=0.6, linestyle='-',
            alpha=1.0):
    """Stroke a GeoJSON LineString or MultiLineString."""
    kind = geometry.get('type')
    if kind == 'LineString':
        parts = [geometry.get('coordinates') or []]
    elif kind == 'MultiLineString':
        parts = geometry.get('coordinates') or []
    elif kind in ('Polygon', 'MultiPolygon'):
        # A jetty mapped as an area, stroked rather than filled.
        groups = ([geometry.get('coordinates') or []] if kind == 'Polygon'
                  else geometry.get('coordinates') or [])
        parts = [ring for rings in groups for ring in rings]
    else:
        return

    for coordinates in parts:
        if len(coordinates) < 2:
            continue
        ax.plot([p[0] for p in coordinates], [p[1] for p in coordinates],
                color=colour, linewidth=linewidth, linestyle=linestyle,
                alpha=alpha, zorder=zorder, solid_capstyle='round')


def draw_speed_track(ax, coords: List[Tuple[float, float]],
                     speeds: List[Optional[float]], zorder: int = 8,
                     linewidth: float = 1.8, casing: bool = True):
    """
    Draw the track as segments coloured by speed over ground.

    Segments take the mean of their two endpoint speeds, which halves the
    visible stepping at a colour boundary. A segment with no speed at either end
    is drawn in grey rather than dropped: dropping it would put a straight line
    across the gap and claim a course the boat did not sail.

    Args:
        ax: Matplotlib axes in degrees
        coords: List of (latitude, longitude)
        speeds: Speed in knots per coordinate, None where unknown
        zorder: Draw order, above the basemap
        linewidth: Track line width in points
        casing: Draw a white casing under the track, for legibility over the chart

    Returns:
        The ScalarMappable for the colourbar, or None when nothing was drawn
    """
    import numpy as np
    from matplotlib.cm import ScalarMappable
    from matplotlib.collections import LineCollection
    from matplotlib.colors import Normalize

    if len(coords) < 2:
        return None

    segments, values, unknown = [], [], []
    for i in range(len(coords) - 1):
        (lat_a, lon_a), (lat_b, lon_b) = coords[i], coords[i + 1]
        segment = [(lon_a, lat_a), (lon_b, lat_b)]
        pair = [s for s in (speeds[i], speeds[i + 1])
                if isinstance(s, (int, float)) and math.isfinite(s)]
        if pair:
            segments.append(segment)
            values.append(sum(pair) / len(pair))
        else:
            unknown.append(segment)

    norm = Normalize(vmin=SPEED_MIN_KT, vmax=SPEED_MAX_KT)

    # A white casing under the whole track. The chart is a busy background of
    # four blues, a green and a beige, and the bottom of viridis is a dark
    # purple that disappears into the mid-depth band without it. Chart
    # convention for a route line, and it costs nothing in a static image.
    if casing:
        ax.add_collection(LineCollection(
            segments + unknown, colors='#ffffff',
            linewidths=linewidth + 1.6, zorder=zorder - 1, capstyle='round'))

    if unknown:
        ax.add_collection(LineCollection(
            unknown, colors='#8a8a8a', linewidths=linewidth, zorder=zorder,
            capstyle='round'))

    if not segments:
        return None

    collection = LineCollection(
        segments, cmap=SPEED_CMAP, norm=norm, linewidths=linewidth,
        zorder=zorder + 1, capstyle='round')
    collection.set_array(np.asarray(values))
    ax.add_collection(collection)

    mappable = ScalarMappable(norm=norm, cmap=SPEED_CMAP)
    mappable.set_array(np.asarray(values))
    return mappable


def latitude_aspect(coords: List[Tuple[float, float]]) -> float:
    """
    Axes aspect that makes a degree of longitude the right width.

    A plot with equal units on both axes squashes the track east to west by
    about 15 per cent at 32 South, which is enough to read a wrong bearing off
    the picture.

    Args:
        coords: List of (latitude, longitude)

    Returns:
        Aspect ratio for ax.set_aspect
    """
    if not coords:
        return 1.0
    mean_lat = sum(lat for lat, _ in coords) / len(coords)
    return 1.0 / max(math.cos(math.radians(mean_lat)), 1e-6)
