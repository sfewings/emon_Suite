"""
Unit tests for reading GPS tracks from gps/position/<n>.

The publisher now sends one JSON object per fix, {"lat":.., "lon":.., "ts":..},
instead of a bare number on each of gps/latitude/<n> and gps/longitude/<n>. The
point of the single message is that both halves of a fix are sampled together,
so there is nothing to join and nothing to get wrong.

Two things are tested hardest here. That the position topic is preferred and
needs no join; and that the old split topics still work, because every recording
already in the database has only those and must stay processable. The latter is
easy to break by deleting code that looks redundant.

No broker and no network. Run with pytest, or directly.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib
matplotlib.use('Agg')

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from event_recorder.data_processor import DataProcessor  # noqa: E402
from event_recorder.trigger_monitor import GPSTriggerMonitor  # noqa: E402

CLUB_LAT, CLUB_LON = -32.0075, 115.8100
T0 = datetime(2026, 8, 29, 9, 0, 0)


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def get_recording_topics(self, recording_id):
        return sorted({r['topic'] for r in self.rows})

    def get_recording_data(self, recording_id, topic_filter=None):
        return [r for r in self.rows if r['topic'] == topic_filter]

    def get_recording(self, recording_id):
        return {'name': 'Test', 'start_time': T0.isoformat()}


def _processor(tmp_path, rows):
    return DataProcessor(_FakeDB(rows), str(tmp_path / 'plots'),
                         {'enabled': False})


def _position_rows(n=30, subnode='0', with_speed=True, ts_in_payload=True):
    """Rows as the new publisher writes them: one JSON object per fix."""
    rows = []
    for i in range(n):
        arrived = T0 + timedelta(seconds=2 * i)
        fix = {'lat': CLUB_LAT + i * 1e-4, 'lon': CLUB_LON + i * 1e-4}
        if ts_in_payload:
            # Fix time, a little before arrival, as it really is.
            fix['ts'] = (arrived - timedelta(milliseconds=250)).timestamp()
        rows.append({'topic': f'gps/position/{subnode}',
                     'timestamp': arrived.isoformat(),
                     'payload': json.dumps(fix)})
        if with_speed:
            rows.append({'topic': f'gps/speed/{subnode}',
                         'timestamp': (arrived + timedelta(milliseconds=340)).isoformat(),
                         'payload': str(2.0 + (i % 5))})
    return rows


def _split_rows(n=30, subnode='0', with_speed=True):
    """Rows as recordings already in the database have them."""
    rows = []
    for i in range(n):
        arrived = T0 + timedelta(seconds=2 * i)
        rows.append({'topic': f'gps/latitude/{subnode}',
                     'timestamp': arrived.isoformat(),
                     'payload': str(CLUB_LAT + i * 1e-4)})
        rows.append({'topic': f'gps/longitude/{subnode}',
                     'timestamp': (arrived + timedelta(milliseconds=180)).isoformat(),
                     'payload': str(CLUB_LON + i * 1e-4)})
        if with_speed:
            rows.append({'topic': f'gps/speed/{subnode}',
                         'timestamp': (arrived + timedelta(milliseconds=340)).isoformat(),
                         'payload': str(2.0 + (i % 5))})
    return rows


# --- which source is used --------------------------------------------------------------

def test_the_position_topic_is_found_as_a_stream(tmp_path):
    processor = _processor(tmp_path, _position_rows())
    streams = processor._find_gps_streams(1)
    assert len(streams) == 1
    assert streams[0].position == 'gps/position/0'
    assert streams[0].speed == 'gps/speed/0'


def test_the_position_topic_wins_over_the_split_topics(tmp_path):
    """A recording spanning the publisher change has both. The single message is
    the one that cannot pair a latitude with the wrong longitude."""
    processor = _processor(tmp_path, _position_rows() + _split_rows())
    streams = processor._find_gps_streams(1)
    assert len(streams) == 1, "one GPS unit, not two"
    assert streams[0].position == 'gps/position/0'
    assert streams[0].latitude == 'gps/latitude/0'   # noted, but not used
    fixes = processor._get_track(1, streams[0])
    assert all(f.fix_ts is not None for f in fixes), \
        "fix_ts only comes from the position payload, so this proves it was read"


def test_the_split_topics_still_work_on_their_own(tmp_path):
    """Every recording made before the publisher changed has only these. This is
    the test that fails if the legacy path is deleted as redundant."""
    processor = _processor(tmp_path, _split_rows())
    streams = processor._find_gps_streams(1)
    assert len(streams) == 1
    assert streams[0].position is None
    fixes = processor._get_track(1, streams[0])
    assert len(fixes) == 30
    assert all(f.fix_ts is None for f in fixes)
    assert all(f.sog is not None for f in fixes)


def test_two_receivers_are_two_streams(tmp_path):
    processor = _processor(tmp_path,
                           _position_rows(subnode='0') + _position_rows(subnode='1'))
    streams = processor._find_gps_streams(1)
    assert [s.key for s in streams] == ['0', '1']


def test_a_latitude_with_no_longitude_and_no_position_is_not_a_track(tmp_path):
    rows = [r for r in _split_rows() if 'longitude' not in r['topic']]
    processor = _processor(tmp_path, rows)
    assert processor._find_gps_streams(1) == []


# --- reading the position payload ------------------------------------------------------

def test_a_position_fix_needs_no_join(tmp_path):
    processor = _processor(tmp_path, _position_rows())
    fixes = processor._get_track(1, processor._find_gps_streams(1)[0])
    assert len(fixes) == 30
    for i, fix in enumerate(fixes):
        assert abs(fix.lat - (CLUB_LAT + i * 1e-4)) < 1e-9
        assert abs(fix.lon - (CLUB_LON + i * 1e-4)) < 1e-9
        assert fix.sog == 2.0 + (i % 5)


def test_the_payload_timestamp_is_kept_apart_from_the_arrival_time(tmp_path):
    """They are different clocks. Speed readings are stamped on arrival, so
    matching uses that; an exported track should carry the fix time."""
    processor = _processor(tmp_path, _position_rows())
    fixes = processor._get_track(1, processor._find_gps_streams(1)[0])
    for fix in fixes:
        assert fix.fix_ts is not None
        assert fix.fix_ts < fix.ts
        assert (fix.ts - fix.fix_ts) < timedelta(seconds=1)


def test_a_position_payload_with_no_ts_still_reads(tmp_path):
    processor = _processor(tmp_path, _position_rows(ts_in_payload=False))
    fixes = processor._get_track(1, processor._find_gps_streams(1)[0])
    assert len(fixes) == 30
    assert all(f.fix_ts is None for f in fixes)


def test_unreadable_position_payloads_are_skipped_not_fatal(tmp_path):
    """A truncated or malformed payload must not lose the rest of the track.
    There is no sentinel for "no fix": the publisher omits the topic entirely."""
    rows = _position_rows(n=6)
    junk = ['not json', '{"lat": 1.0}', '{"lat": null, "lon": 115.8}',
            '{"lat": "x", "lon": 115.8}', '', '[]',
            '{"lat": NaN, "lon": 115.8}']
    for i, payload in enumerate(junk):
        rows.append({'topic': 'gps/position/0',
                     'timestamp': (T0 + timedelta(seconds=100 + i)).isoformat(),
                     'payload': payload})
    processor = _processor(tmp_path, rows)
    fixes = processor._get_track(1, processor._find_gps_streams(1)[0])
    assert len(fixes) == 6, "the six good fixes survive and the junk is dropped"


def test_fixes_come_back_in_time_order(tmp_path):
    rows = _position_rows(n=10)
    rows.reverse()
    processor = _processor(tmp_path, rows)
    fixes = processor._get_track(1, processor._find_gps_streams(1)[0])
    assert [f.ts for f in fixes] == sorted(f.ts for f in fixes)


# --- the consumers ---------------------------------------------------------------------

def test_the_auto_plot_config_asks_for_the_position_topic(tmp_path):
    processor = _processor(tmp_path, _position_rows())
    specs = processor._auto_generate_plot_config(1)
    maps = [s for s in specs if s['type'] == 'map']
    assert len(maps) == 1
    assert maps[0]['topics'] == ['gps/position/0']
    # The position topic must not also become a time-series chart: its payload is
    # a JSON object, and a JSON object plotted against time is not a chart.
    for spec in specs:
        if spec['type'] != 'map':
            assert 'gps/position/0' not in spec.get('topics', [])


def test_the_auto_plot_config_still_pairs_a_legacy_recording(tmp_path):
    processor = _processor(tmp_path, _split_rows())
    maps = [s for s in processor._auto_generate_plot_config(1) if s['type'] == 'map']
    assert len(maps) == 1
    assert maps[0]['topics'] == ['gps/latitude/0', 'gps/longitude/0']


def test_a_legacy_plot_spec_still_finds_a_position_recording(tmp_path):
    """An event config written by hand may still name the old pair. It should
    resolve to the same GPS unit rather than plotting nothing."""
    processor = _processor(tmp_path, _position_rows())
    coords, speeds = processor._get_gps_track(
        1, ['gps/latitude/0', 'gps/longitude/0'])
    assert len(coords) == 30 and len(speeds) == 30


def test_the_route_map_draws_from_a_position_recording(tmp_path):
    processor = _processor(tmp_path, _position_rows(n=60))
    outdir = tmp_path / 'out'
    outdir.mkdir(parents=True, exist_ok=True)
    png = processor._generate_route_map(
        1, {'title': 'Route Map', 'topics': ['gps/position/0']}, outdir)
    assert png.exists() and png.stat().st_size > 5000


def test_the_distance_statistic_reads_a_position_recording(tmp_path):
    """It used to ask for gps/latitude/0 by name, which finds nothing in a
    recording that has only gps/position/0, and reported no distance at all."""
    processor = _processor(tmp_path, _position_rows(n=60))
    stats = processor._calculate_gps_statistics(1)
    assert stats, "expected distance and speed statistics"
    assert any('distance' in k.lower() for k in stats), sorted(stats)


def test_kml_and_gpx_export_from_a_position_recording(tmp_path):
    processor = _processor(tmp_path, _position_rows(n=40))
    outdir = tmp_path / 'exports'
    outdir.mkdir(parents=True, exist_ok=True)

    kmls = processor.generate_kml_exports(1, outdir)
    assert len(kmls) == 1
    kml = kmls[0].read_text(encoding='utf-8')
    assert kml.count(',0\n') >= 39 or '115.81' in kml

    gpx_path = processor.generate_gpx_export(1, outdir)
    assert gpx_path is not None
    gpx = gpx_path.read_text(encoding='utf-8')
    assert gpx.count('<trkpt') == 40
    assert '<time>' in gpx
    # Speed rides along as an extension, forward-filled against arrival time.
    assert 'speed' in gpx.lower()


def test_gpx_export_still_works_for_a_legacy_recording(tmp_path):
    processor = _processor(tmp_path, _split_rows(n=40))
    outdir = tmp_path / 'exports'
    outdir.mkdir(parents=True, exist_ok=True)
    gpx_path = processor.generate_gpx_export(1, outdir)
    assert gpx_path is not None
    assert gpx_path.read_text(encoding='utf-8').count('<trkpt') == 40


# --- the live trigger monitor ----------------------------------------------------------

class _Msg:
    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = payload.encode('utf-8') if isinstance(payload, str) else payload


def _monitor():
    return GPSTriggerMonitor()


def test_a_position_message_sets_a_whole_fix():
    monitor = _monitor()
    monitor._on_message(None, None, _Msg(
        'gps/position/0', '{"lat":-32.0075,"lon":115.8100,"ts":1787932800}'))
    position = monitor.get_current_position()
    assert position is not None
    assert abs(position[0] - CLUB_LAT) < 1e-9
    assert abs(position[1] - CLUB_LON) < 1e-9


def test_a_position_message_never_leaves_a_half_updated_position():
    """The reason for preferring the single message. With the split topics the
    monitor holds a latitude from one fix and a longitude from another between
    the two messages, and movement is measured by distance, so that pairing is a
    jump the vessel never made and a false trigger."""
    monitor = _monitor()
    monitor._on_message(None, None, _Msg(
        'gps/position/0', '{"lat":-32.0000,"lon":115.8000}'))
    first = monitor.get_current_position()
    monitor._on_message(None, None, _Msg(
        'gps/position/0', '{"lat":-32.0100,"lon":115.8100}'))
    second = monitor.get_current_position()
    # Both readings are places the vessel actually was: no mixed pair exists at
    # any point, because each message replaces both halves at once.
    assert first[:2] == (-32.0000, 115.8000)
    assert second[:2] == (-32.0100, 115.8100)


def test_a_bad_position_message_leaves_the_last_good_fix_alone():
    monitor = _monitor()
    monitor._on_message(None, None, _Msg(
        'gps/position/0', '{"lat":-32.0075,"lon":115.8100}'))
    for payload in ('not json', '{"lat":1.0}', '{"lat":null,"lon":115.8}',
                    '{"lat":NaN,"lon":115.8}', ''):
        monitor._on_message(None, None, _Msg('gps/position/0', payload))
        position = monitor.get_current_position()
        assert position is not None, payload
        assert abs(position[0] - CLUB_LAT) < 1e-9, payload


def test_the_split_topics_still_drive_the_monitor():
    """For an installation whose publisher has not been updated."""
    monitor = _monitor()
    monitor._on_message(None, None, _Msg('gps/latitude/0', '-32.0075'))
    assert monitor.get_current_position() is None, "half a fix is not a position"
    monitor._on_message(None, None, _Msg('gps/longitude/0', '115.8100'))
    position = monitor.get_current_position()
    assert position is not None
    assert abs(position[0] - CLUB_LAT) < 1e-9
    assert abs(position[1] - CLUB_LON) < 1e-9


def test_the_example_configs_monitor_the_position_topic():
    """The configs are what a deployment copies, so they are what actually
    decides which topic is used."""
    for path in (ROOT / 'event_recorder' / 'config_examples' / 'events'
                 / '20260212-1000.yml',
                 ROOT / 'event_recorder' / 'test_event_recorder' / 'config'
                 / 'events' / '20260212-1000.yml'):
        text = path.read_text(encoding='utf-8')
        assert '- "gps/position/0"' in text, path
        # No monitor_topics entry naming the split topics any more. They may
        # still appear in comments explaining why.
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith('- "gps/latitude'):
                raise AssertionError(f"{path}: still monitors {stripped}")


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__, '-v']))
