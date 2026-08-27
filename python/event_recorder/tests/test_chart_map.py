"""
Unit tests for the offline route-map basemap and speed colouring.

No broker, no network and no WordPress, unlike the integration scripts beside
this file: everything here is about the contract with enchantee_racing and the
ways it is allowed to fail. Run with pytest, or directly.

The failure paths are most of the point. The boat has no internet, the other app
may be stopped, a chart may be regenerated with a new shape, and a recording may
have been made somewhere the chart does not cover. None of those may lose a
track or raise out of processing.
"""

import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from event_recorder import chart_map  # noqa: E402
from event_recorder.data_processor import DataProcessor  # noqa: E402

# Somewhere in the Swan, and a box around it.
CLUB_LAT, CLUB_LON = -32.0075, 115.8100
DEAD_URL = 'http://127.0.0.1:1'   # nothing listens on port 1


def _tiny_charts():
    """The smallest set of documents draw_basemap will accept and draw."""
    box = [[[115.79, -32.02], [115.83, -32.02],
            [115.83, -31.99], [115.79, -31.99], [115.79, -32.02]]]
    return {
        'coast': {
            'schema': 'pfsyc-coast/1',
            'bbox': {'south': -32.05, 'west': 115.75, 'north': -31.95, 'east': 115.87},
            'type': 'FeatureCollection',
            'features': [{'type': 'Feature', 'properties': {'kind': 'land'},
                          'geometry': {'type': 'Polygon', 'coordinates': box}}],
        },
        'depth': {
            'schema': 'pfsyc-depth/2',
            'type': 'FeatureCollection',
            'features': [
                {'type': 'Feature',
                 'properties': {'kind': 'band', 'band': 'deep', 'color': '#92c0dc'},
                 'geometry': {'type': 'Polygon', 'coordinates': box}},
                {'type': 'Feature',
                 'properties': {'kind': 'contour', 'depth_m': 2.0},
                 'geometry': {'type': 'LineString',
                              'coordinates': [[115.79, -32.00], [115.83, -32.00]]}},
            ],
        },
        'structures': {
            'schema': 'pfsyc-structures/1',
            'type': 'FeatureCollection',
            'features': [{'type': 'Feature', 'properties': {'kind': 'jetty'},
                          'geometry': {'type': 'LineString',
                                       'coordinates': [[115.80, -32.01], [115.81, -32.01]]}}],
        },
        'navaids': {
            'schema': 'pfsyc-navaids/1',
            'type': 'FeatureCollection',
            'features': [
                {'type': 'Feature',
                 'properties': {'kind': 'buoy_port', 'lit': True, 'dup_mark': False,
                                'name': 'Test - Mark 1'},
                 'geometry': {'type': 'Point', 'coordinates': [115.805, -32.005]}},
                {'type': 'Feature',
                 'properties': {'kind': 'buoy_yacht', 'dup_mark': True, 'name': 'Dup'},
                 'geometry': {'type': 'Point', 'coordinates': [115.806, -32.006]}},
            ],
        },
        'marks': {
            'schema': 'pfsyc-marks/2',
            'bbox': {'south': -32.02, 'west': 115.79, 'north': -31.99, 'east': 115.83},
            'marks': [{'id': 'club-32a', 'name': '32A', 'lat': -32.007, 'lon': 115.809}],
        },
    }


def _write_cache(cache_dir, charts):
    cache_dir.mkdir(parents=True, exist_ok=True)
    for name, document in charts.items():
        (cache_dir / f"{name}.json").write_text(json.dumps(document), encoding='utf-8')


# --- the contract with enchantee_racing ------------------------------------------------

def test_schema_mismatch_is_rejected():
    """These are generated documents and depth has already changed shape once.
    A renamed property draws a blank layer rather than raising, so the version is
    checked instead of trusted."""
    assert chart_map._schema_ok('pfsyc-depth/2', 'pfsyc-depth/2')
    assert not chart_map._schema_ok('pfsyc-depth/3', 'pfsyc-depth/2')
    assert not chart_map._schema_ok('pfsyc-coast/1', 'pfsyc-depth/2')
    assert not chart_map._schema_ok('', 'pfsyc-depth/2')
    assert not chart_map._schema_ok('pfsyc-depth', 'pfsyc-depth/2')


def test_a_cached_document_with_a_new_schema_is_ignored(tmp_path):
    charts = _tiny_charts()
    charts['depth']['schema'] = 'pfsyc-depth/99'
    _write_cache(tmp_path / 'charts', charts)
    loaded = chart_map.ChartCache(cache_dir=str(tmp_path / 'charts')).load()
    assert loaded is not None, "the rest of the chart should still be usable"
    assert 'depth' not in loaded
    assert 'coast' in loaded


def test_refresh_offline_keeps_the_cache(tmp_path):
    """The boat has no internet and enchantee_racing may be stopped. Neither may
    lose the cached chart or raise."""
    cache = tmp_path / 'charts'
    _write_cache(cache, _tiny_charts())
    cache_obj = chart_map.ChartCache(base_url=DEAD_URL, cache_dir=str(cache), timeout=1)
    results = cache_obj.refresh()
    assert set(results.values()) == {'failed'}
    loaded = cache_obj.load()
    assert loaded is not None and 'coast' in loaded


def test_no_cache_at_all_means_no_chart(tmp_path):
    """First run, before enchantee_racing has ever been reachable. Route maps
    fall back to plain axes rather than failing."""
    cache_obj = chart_map.ChartCache(base_url=DEAD_URL,
                                     cache_dir=str(tmp_path / 'nothing'), timeout=1)
    cache_obj.refresh()
    assert cache_obj.load() is None


def test_a_chart_without_a_coastline_is_no_chart(tmp_path):
    """Coast carries the extent, and without it there is no way to tell whether a
    track is on the chart."""
    charts = _tiny_charts()
    del charts['coast']
    _write_cache(tmp_path / 'charts', charts)
    assert chart_map.ChartCache(cache_dir=str(tmp_path / 'charts')).load() is None


def test_disabled_fetches_nothing_and_draws_nothing(tmp_path):
    _write_cache(tmp_path / 'charts', _tiny_charts())
    cache_obj = chart_map.ChartCache(cache_dir=str(tmp_path / 'charts'), enabled=False)
    assert set(cache_obj.refresh().values()) == {'skipped'}
    assert cache_obj.load() is None


def test_the_real_documents_still_match_the_expected_schemas():
    """Guards against enchantee_racing regenerating a chart in a new shape without
    this side being updated. Skipped when the other project is not checked out."""
    config_dir = ROOT / 'enchantee_racing' / 'config'
    if not config_dir.is_dir():
        return
    for name, expected in chart_map.CHART_DOCUMENTS.items():
        path = config_dir / f"{name}.json"
        if not path.exists():
            continue
        declared = json.loads(path.read_text(encoding='utf-8')).get('schema')
        assert chart_map._schema_ok(str(declared), expected), \
            f"{name}.json declares {declared}, chart_map expects {expected}"


# --- is the track on the chart ---------------------------------------------------------

def test_a_local_track_is_on_the_chart():
    charts = _tiny_charts()
    coords = [(CLUB_LAT + i * 1e-4, CLUB_LON + i * 1e-4) for i in range(50)]
    assert chart_map.track_on_chart(coords, charts)


def test_a_track_sailed_elsewhere_falls_back_to_plain_axes():
    """The requirement is explicit: do not lose a track because it was sailed
    somewhere else."""
    charts = _tiny_charts()
    coords = [(-26.0 + i * 1e-4, 123.8 + i * 1e-4) for i in range(50)]
    assert not chart_map.track_on_chart(coords, charts)


def test_one_wild_fix_does_not_send_a_local_track_off_the_chart():
    """A single bad fix is common and must not change how the plot is drawn, which
    is why the test is on percentiles and not on the full extent."""
    charts = _tiny_charts()
    coords = [(CLUB_LAT + i * 1e-5, CLUB_LON + i * 1e-5) for i in range(500)]
    coords[250] = (0.0, 0.0)
    assert chart_map.track_on_chart(coords, charts)


def test_an_empty_track_is_not_on_the_chart():
    assert not chart_map.track_on_chart([], _tiny_charts())


# --- drawing ---------------------------------------------------------------------------

def test_the_basemap_draws_every_layer_and_skips_duplicate_aids():
    fig, ax = plt.subplots()
    chart_map.draw_basemap(ax, _tiny_charts())
    # One land polygon plus one depth band, as patches.
    assert len(ax.patches) == 2
    # The duplicate aid is drawn once, by marks.json, so only one aid colour and
    # one mark series are plotted alongside the contour and the jetty.
    assert len(ax.lines) >= 3
    plt.close(fig)


def test_the_speed_scale_is_fixed_so_two_recordings_compare():
    """A colour must mean a speed and not a rank, and it must be the same scale
    enchantee_racing's trail uses."""
    assert chart_map.SPEED_MIN_KT == 0.0
    assert chart_map.SPEED_MAX_KT == 8.0
    assert chart_map.SPEED_CMAP == 'viridis'

    fig, ax = plt.subplots()
    coords = [(CLUB_LAT, CLUB_LON), (CLUB_LAT + 1e-3, CLUB_LON + 1e-3)]
    mappable = chart_map.draw_speed_track(ax, coords, [3.0, 4.0])
    assert mappable.norm.vmin == 0.0 and mappable.norm.vmax == 8.0
    plt.close(fig)


def test_a_speed_above_the_scale_clamps_and_does_not_rescale():
    fig, ax = plt.subplots()
    coords = [(CLUB_LAT, CLUB_LON), (CLUB_LAT + 1e-3, CLUB_LON + 1e-3)]
    mappable = chart_map.draw_speed_track(ax, coords, [40.0, 40.0])
    assert mappable.norm.vmax == 8.0
    plt.close(fig)


def test_a_gap_in_the_speed_data_is_drawn_and_not_dropped():
    """Dropping it would join the fixes either side with a straight line and claim
    a course the boat did not sail."""
    from matplotlib.collections import LineCollection

    fig, ax = plt.subplots()
    coords = [(CLUB_LAT + i * 1e-4, CLUB_LON) for i in range(4)]
    chart_map.draw_speed_track(ax, coords, [4.0, None, None, 4.0], casing=False)
    drawn = sum(len(c.get_segments()) for c in ax.collections
                if isinstance(c, LineCollection))
    assert drawn == 3, "every segment should be drawn, coloured or grey"
    plt.close(fig)


def test_a_track_with_no_speed_at_all_still_draws_without_a_colourbar():
    fig, ax = plt.subplots()
    coords = [(CLUB_LAT + i * 1e-4, CLUB_LON) for i in range(4)]
    mappable = chart_map.draw_speed_track(ax, coords, [None] * 4)
    assert mappable is None, "nothing to put on a colourbar"
    assert len(ax.collections) >= 1, "but the track is still on the plot"
    plt.close(fig)


def test_the_aspect_corrects_for_latitude():
    """Equal units squash the track east to west by about 15 per cent at 32 South,
    which is enough to read a wrong bearing off the picture."""
    aspect = chart_map.latitude_aspect([(-32.0, 115.8), (-32.01, 115.81)])
    assert 1.15 < aspect < 1.20, aspect
    assert abs(chart_map.latitude_aspect([(0.0, 0.0)]) - 1.0) < 1e-9


# --- the track and its speeds come out aligned ----------------------------------------

class _FakeDB:
    """Only the two methods the route map reads."""

    def __init__(self, rows):
        self.rows = rows

    def get_recording_topics(self, recording_id):
        return sorted({r['topic'] for r in self.rows})

    def get_recording_data(self, recording_id, topic_filter=None):
        return [r for r in self.rows if r['topic'] == topic_filter]


def _rows(n=60, drop_lon_at=None, speed_topic='gps/speed/0'):
    t0 = datetime(2026, 8, 29, 9, 0, 0)
    rows = []
    for i in range(n):
        ts = t0 + timedelta(seconds=2 * i)
        rows.append({'topic': 'gps/latitude/0', 'timestamp': ts.isoformat(),
                     'payload': str(CLUB_LAT + i * 1e-4)})
        if i != drop_lon_at:
            # Offset, as separate MQTT topics really are.
            rows.append({'topic': 'gps/longitude/0',
                         'timestamp': (ts + timedelta(milliseconds=180)).isoformat(),
                         'payload': str(CLUB_LON + i * 1e-4)})
        if speed_topic:
            rows.append({'topic': speed_topic,
                         'timestamp': (ts + timedelta(milliseconds=340)).isoformat(),
                         'payload': str(2.0 + (i % 5))})
    return rows


def _processor(tmp_path, rows, charts=None):
    if charts is not None:
        _write_cache(tmp_path / 'charts', charts)
    return DataProcessor(_FakeDB(rows), str(tmp_path / 'plots'),
                         {'enabled': charts is not None, 'base_url': DEAD_URL,
                          'cache_dir': str(tmp_path / 'charts'), 'timeout': 1})


def test_speeds_line_up_with_coordinates(tmp_path):
    processor = _processor(tmp_path, _rows())
    coords, speeds = processor._get_gps_track(1, ['gps/latitude/0', 'gps/longitude/0'])
    assert len(coords) == 60
    assert len(speeds) == len(coords)
    assert all(s is not None for s in speeds)
    # Speed i belongs to fix i: both derive from the same second.
    for i, speed in enumerate(speeds):
        assert speed == 2.0 + (i % 5), i


def test_a_dropped_longitude_does_not_shift_every_later_speed(tmp_path):
    """The bug this guards against: building coordinates and speeds in separate
    passes leaves index i of one belonging to index i+1 of the other from the
    first unmatched latitude onwards, so the whole back half of the track is
    coloured with the wrong speeds."""
    # 20 s apart, so a dropped longitude has no neighbour inside the 5 s window.
    t0 = datetime(2026, 8, 29, 9, 0, 0)
    rows = []
    for i in range(20):
        ts = t0 + timedelta(seconds=20 * i)
        rows.append({'topic': 'gps/latitude/0', 'timestamp': ts.isoformat(),
                     'payload': str(CLUB_LAT + i * 1e-4)})
        if i != 5:
            rows.append({'topic': 'gps/longitude/0',
                         'timestamp': (ts + timedelta(milliseconds=180)).isoformat(),
                         'payload': str(CLUB_LON + i * 1e-4)})
        rows.append({'topic': 'gps/speed/0',
                     'timestamp': (ts + timedelta(milliseconds=340)).isoformat(),
                     'payload': str(float(i))})

    processor = _processor(tmp_path, rows)
    coords, speeds = processor._get_gps_track(1, ['gps/latitude/0', 'gps/longitude/0'])
    assert len(coords) == 19, "the unmatched latitude is dropped from the track"
    assert len(speeds) == len(coords)
    # Fix 5 is gone, so from there on the speed must skip 5 too.
    assert speeds == [float(i) for i in range(20) if i != 5]


def test_a_recording_with_no_speed_topic_still_plots(tmp_path):
    processor = _processor(tmp_path, _rows(speed_topic=None))
    coords, speeds = processor._get_gps_track(1, ['gps/latitude/0', 'gps/longitude/0'])
    assert len(coords) == 60
    assert speeds == [None] * 60


def test_a_differently_numbered_gps_unit_finds_its_own_speed(tmp_path):
    rows = []
    for row in _rows(speed_topic='gps/speed/1'):
        rows.append({**row, 'topic': row['topic'].replace('/0', '/1')
                     if row['topic'].endswith('/0') else row['topic']})
    processor = _processor(tmp_path, rows)
    streams = processor._find_gps_streams(1)
    assert [s.key for s in streams] == ['1']
    assert streams[0].speed == 'gps/speed/1'
    coords, speeds = processor._get_gps_track(1, ['gps/latitude/1', 'gps/longitude/1'])
    assert len(coords) == 60 and all(s is not None for s in speeds)


# --- what reaches WordPress -----------------------------------------------------------

def test_the_chart_map_and_the_osm_map_have_different_stems(tmp_path):
    """The publisher drops any image whose filename stem matches a map HTML, so
    that the interactive map replaces its own screenshot. If the chart PNG shared
    a stem with the folium HTML it would be dropped from the post, and it is the
    map that must reach it."""
    processor = _processor(tmp_path, _rows(), _tiny_charts())
    outdir = tmp_path / 'plots' / '1'
    outdir.mkdir(parents=True, exist_ok=True)
    png = processor._generate_route_map(
        1, {'title': 'Route Map', 'topics': ['gps/latitude/0', 'gps/longitude/0']},
        outdir)
    assert png.exists() and png.suffix == '.png'
    for html in outdir.glob('*.html'):
        assert html.stem != png.stem, \
            "the chart map would be excluded from the WordPress post"


def test_the_route_map_is_produced_on_the_chart_and_off_it(tmp_path):
    for label, charts, rows in (
        ('on chart', _tiny_charts(), _rows()),
        ('no chart', None, _rows()),
    ):
        processor = _processor(tmp_path / label.replace(' ', '_'), rows, charts)
        outdir = tmp_path / label.replace(' ', '_') / 'out'
        outdir.mkdir(parents=True, exist_ok=True)
        png = processor._generate_route_map(
            1, {'title': 'Route Map', 'topics': ['gps/latitude/0', 'gps/longitude/0']},
            outdir)
        assert png.exists() and png.stat().st_size > 5000, label


def test_too_few_fixes_is_still_an_error(tmp_path):
    """Unchanged behaviour: the caller logs it and carries on with the other plots."""
    processor = _processor(tmp_path, _rows(n=1))
    outdir = tmp_path / 'out'
    outdir.mkdir(parents=True, exist_ok=True)
    try:
        processor._generate_route_map(
            1, {'title': 'Route Map', 'topics': ['gps/latitude/0', 'gps/longitude/0']},
            outdir)
    except ValueError:
        return
    raise AssertionError("expected ValueError for insufficient GPS data")


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__, '-v']))
