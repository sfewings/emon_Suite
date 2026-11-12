"""
Plot legends, titles and units taken from the emon envelope (emon_live_ui DESIGN 4.2).

The envelope lane publishes one JSON object per reading carrying the feed's own name,
so a legend can say 'Main Battery / power' instead of 'bms/power/1'. These tests use
the names the boat's emon_config actually produces, checked against a decode of
20260913_Frostbite_1.TXT, rather than invented ones.

No broker and no decoder here: the envelopes are written out literally, which is also
how a reader can see what the recorder stores.
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

T0 = datetime(2026, 9, 13, 13, 4, 24)


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def get_recording_topics(self, recording_id):
        return sorted({r['topic'] for r in self.rows})

    def get_recording_data(self, recording_id, topic_filter=None, limit=None):
        rows = [r for r in self.rows if r['topic'] == topic_filter]
        return rows[:limit] if limit else rows

    def get_recording(self, recording_id):
        return {'name': 'Test', 'start_time': T0.isoformat(),
                'end_time': (T0 + timedelta(hours=1)).isoformat()}

    def get_recording_data_count(self, recording_id):
        return len(self.rows)


def _processor(tmp_path, rows):
    return DataProcessor(_FakeDB(rows), str(tmp_path / 'plots'), {'enabled': False})


def _envelope_rows(topic, node, sub, field, group, name, unit, kind,
                   n=10, first=0.0, idx=None):
    """n readings of one feed, each the envelope emon_feed.envelope() would build."""
    rows = []
    for i in range(n):
        body = {'s': 1, 'v': first + i, 'u': unit, 'kind': kind,
                'node': node, 'sub': sub, 'field': field,
                'group': group, 'name': name}
        if idx is not None:
            body['idx'] = idx
        body['t'] = (T0 + timedelta(seconds=i)).timestamp()
        rows.append({'topic': topic,
                     'timestamp': (T0 + timedelta(seconds=i)).isoformat(),
                     'payload': json.dumps(body)})
    return rows


def _battery_rows(n=10):
    return _envelope_rows('emon/bms/1/power', 'bms', 1, 'power',
                          'Main Battery', 'power', 'W', 'power', n=n)


def _wind_rows(n=10):
    """The three wind sources: same field, different subnode, different names."""
    rows = []
    for sub, group in ((0, 'Boat reference wind'), (1, 'Apparent wind'), (2, 'True wind')):
        rows += _envelope_rows(f'emon/mwv/{sub}/windSpeed', 'mwv', sub, 'windSpeed',
                               group, 'windSpeed', 'kn', 'speed', n=n, first=sub * 10.0)
    return rows


# --- reading an envelope ---------------------------------------------------------------

def test_an_envelope_payload_yields_its_value(tmp_path):
    """float(payload) on an envelope raises, which would leave every series empty."""
    processor = _processor(tmp_path, _battery_rows())
    data = processor._get_topic_data(1, 'emon/bms/1/power')
    assert data is not None, "the envelope payload must still produce a series"
    timestamps, values = data
    assert values == [float(i) for i in range(10)]


def test_a_bare_payload_still_yields_its_value(tmp_path):
    """Legacy topics are still recorded and must keep working."""
    rows = [{'topic': 'gps/speed/0',
             'timestamp': (T0 + timedelta(seconds=i)).isoformat(),
             'payload': str(float(i))} for i in range(10)]
    processor = _processor(tmp_path, rows)
    _, values = processor._get_topic_data(1, 'gps/speed/0')
    assert values == [float(i) for i in range(10)]


def test_a_position_envelope_is_not_a_number(tmp_path):
    """Its value is an object, so it must not land in a line plot as a number."""
    rows = [{'topic': 'emon/gps/0/position',
             'timestamp': T0.isoformat(),
             'payload': json.dumps({'s': 1, 'v': {'lat': -32.0, 'lon': 115.8},
                                    'node': 'gps', 'sub': 0, 'field': 'position',
                                    'group': 'Enchantee-GPS', 'name': 'position'})}]
    processor = _processor(tmp_path, rows)
    assert processor._get_topic_data(1, 'emon/gps/0/position') is None


# --- the names on the chart ------------------------------------------------------------

def test_a_feed_is_named_by_its_group_and_name(tmp_path):
    processor = _processor(tmp_path, _battery_rows())
    assert processor._feed_name(1, 'emon/bms/1/power') == 'Main Battery / power'


def test_a_legacy_topic_has_no_feed_name(tmp_path):
    rows = [{'topic': 'bms/power/1', 'timestamp': T0.isoformat(), 'payload': '42'}]
    processor = _processor(tmp_path, rows)
    assert processor._feed_name(1, 'bms/power/1') is None


def test_the_three_wind_sources_share_one_chart(tmp_path):
    """They differ only by subnode, so a key built by stripping a trailing index would
    give three separate charts where the legacy anemometer/windSpeed/0,1,2 gave one."""
    processor = _processor(tmp_path, _wind_rows())
    specs = [s for s in processor._auto_generate_plot_config(1)
             if s['type'] == 'multi_line']
    assert len(specs) == 1, "one wind speed chart, not three"
    assert sorted(specs[0]['labels']) == ['Apparent wind / windSpeed',
                                          'Boat reference wind / windSpeed',
                                          'True wind / windSpeed']


def test_the_unit_comes_from_the_envelope_not_a_keyword_table(tmp_path):
    processor = _processor(tmp_path, _wind_rows())
    spec = [s for s in processor._auto_generate_plot_config(1)
            if s['type'] == 'multi_line'][0]
    assert spec['ylabel'] == 'kn'


def test_one_sensors_channels_drop_the_repeated_group_name(tmp_path):
    """Sixteen cells of one battery: repeating 'Main Battery /' in every legend entry
    crowds out the part that differs."""
    rows = []
    for cell in range(4):
        rows += _envelope_rows(f'emon/bms/1/cellVoltage/{cell}', 'bms', 1,
                               'cellVoltage', 'Main Battery', f'cellVoltage {cell}',
                               'V', 'voltage', idx=cell, first=3.3)
    processor = _processor(tmp_path, rows)
    spec = [s for s in processor._auto_generate_plot_config(1)
            if s['type'] == 'multi_line'][0]
    # Group and field both, not the group alone: the title becomes the PNG filename,
    # and the pack's other charts are 'Main Battery' too.
    assert spec['title'] == 'Main Battery cellVoltage'
    assert spec['labels'] == [f'cellVoltage {i}' for i in range(4)]


def test_two_families_reporting_temperature_get_two_charts(tmp_path):
    """The title becomes the PNG filename, so two charts both called 'temperature'
    leave one file and one surviving chart. The wind sensors and the pressure/
    temperature/humidity sensors both report a temperature, which is how this was
    found in the replay."""
    rows = []
    for sub, group in ((0, 'Boat reference wind'), (1, 'Apparent wind')):
        rows += _envelope_rows(f'emon/mwv/{sub}/temperature', 'mwv', sub, 'temperature',
                               group, 'temperature', 'degC', 'temperature')
    for sub, group in ((0, 'Cabin GPS'), (1, 'Anemometer')):
        rows += _envelope_rows(f'emon/pth/{sub}/temperature', 'pth', sub, 'temperature',
                               group, 'temperature', 'degC', 'temperature')

    processor = _processor(tmp_path, rows)
    specs = [s for s in processor._auto_generate_plot_config(1)
             if s['type'] == 'multi_line']
    assert len(specs) == 2, "one chart per sensor family"
    titles = {s['title'] for s in specs}
    assert len(titles) == 2, f"titles must differ, got {titles}"


def test_the_config_document_is_not_charted(tmp_path):
    """emon/config is the retained configuration document, not a reading."""
    rows = _battery_rows() + [
        {'topic': 'emon/config', 'timestamp': T0.isoformat(),
         'payload': json.dumps({'file': '20260211-1447.yml', 'settings': {}})}]
    processor = _processor(tmp_path, rows)
    specs = processor._auto_generate_plot_config(1)
    assert all('emon/config' not in s['topics'] for s in specs)
    assert not any('config' in s['title'].lower() for s in specs)


def test_the_imu_axes_are_labelled_by_what_they_point_along(tmp_path):
    """'acc 0' says nothing about the boat. Which index is which is written down only
    in emon_decoder._imu, so the chart is the place to spell it out."""
    rows = []
    for idx in range(3):
        rows += _envelope_rows(f'emon/imu/0/acc/{idx}', 'imu', 0, 'acc',
                               'IMU Sensor', f'acc {idx}', 'g', 'acc', idx=idx)
    processor = _processor(tmp_path, rows)
    spec = [s for s in processor._auto_generate_plot_config(1)
            if s['type'] == 'multi_line'][0]
    assert spec['labels'] == ['X (bow-stern)', 'Y (port-starboard)', 'Z (vertical)']


def test_a_config_named_axis_beats_the_built_in_label(tmp_path):
    """emon_config can name the axes (imu axis0/1/2, enchantee from 20261103-1426) and
    then the envelope carries 'acc fore-aft'. That came from the boat; the table here
    is only for recordings made before it, which still read 'acc 0'."""
    rows = []
    for idx, axis in enumerate(('fore-aft', 'port-starboard', 'vertical')):
        rows += _envelope_rows(f'emon/imu/0/acc/{idx}', 'imu', 0, 'acc',
                               'IMU Sensor', f'acc {axis}', 'g', 'acc', idx=idx)
    processor = _processor(tmp_path, rows)
    spec = [s for s in processor._auto_generate_plot_config(1)
            if s['type'] == 'multi_line'][0]
    assert spec['labels'] == ['acc fore-aft', 'acc port-starboard', 'acc vertical']


def test_a_two_axis_group_is_not_given_axis_labels(tmp_path):
    """Only a whole three-axis sensor gets them; two of the three is something else."""
    rows = []
    for idx in range(2):
        rows += _envelope_rows(f'emon/imu/0/gyro/{idx}', 'imu', 0, 'gyro',
                               'IMU Sensor', f'gyro {idx}', 'deg/s', 'gyro', idx=idx)
    processor = _processor(tmp_path, rows)
    spec = [s for s in processor._auto_generate_plot_config(1)
            if s['type'] == 'multi_line'][0]
    assert spec['labels'] == ['gyro 0', 'gyro 1']


# --- derived feeds ---------------------------------------------------------------------

def _derived_rows(feed_id, n=10, first=0.0, unit='deg'):
    """A derived feed as emon_live publishes it: no group and no name, the id in
    'field', keyed 'derived/<id>' (emon_feed.feed_key)."""
    rows = []
    for i in range(n):
        stamp = T0 + timedelta(seconds=i)
        rows.append({
            'topic': f'emon/derived/{feed_id}',
            'timestamp': stamp.isoformat(),
            'payload': json.dumps({'s': 1, 'v': first + i, 'u': unit, 'kind': 'angle',
                                   'node': 'derived', 'field': feed_id,
                                   't': stamp.timestamp()})})
    return rows


def test_a_derived_feed_is_named_by_its_id(tmp_path):
    """It carries no group or name, so building a name from those gives None and a
    chart asking for 'derived/boat/heel' would match nothing and come out empty."""
    processor = _processor(tmp_path, _derived_rows('boat/heel'))
    assert processor._feed_name(1, 'emon/derived/boat/heel') == 'derived/boat/heel'


def test_a_chart_can_ask_for_derived_feeds_by_name(tmp_path):
    """Attitude is emon_live's to compute now (DESIGN D3); event_recorder only charts
    what the boat already publishes."""
    rows = _derived_rows('boat/heel') + _derived_rows('boat/pitch', first=-3.0)
    processor = _processor(tmp_path, rows)
    spec = processor._resolve_declared(1, [{
        'title': 'Pitch and heel',
        'feeds': ['derived/boat/heel', 'derived/boat/pitch'],
        'ylabel': 'Degrees',
    }])[0]
    assert spec['topics'] == ['emon/derived/boat/heel', 'emon/derived/boat/pitch']
    assert spec['labels'] == ['derived/boat/heel', 'derived/boat/pitch']
    assert processor._get_topic_data(1, 'emon/derived/boat/heel') is not None


# --- statistics ------------------------------------------------------------------------

def test_energy_comes_from_the_bms_when_there_is_no_shunt(tmp_path):
    """The boat has no bat shunt, so battery/power/0/0 is never published. Energy has
    to come from the pack's own power feed or the post reports none."""
    processor = _processor(tmp_path, _battery_rows(n=60))
    stats = processor._calculate_energy_statistics(1)
    assert 'energy_used_wh' in stats
    assert stats['energy_used_wh'] > 0


def test_efficiency_is_computed_from_distance_and_energy(tmp_path):
    """It used to be computed inside _calculate_energy_statistics against that
    function's own dict, which never holds distance_km, so {efficiency} in the post
    template was never filled."""
    rows = _battery_rows(n=60)
    for i in range(60):
        rows.append({'topic': 'emon/gps/0/position',
                     'timestamp': (T0 + timedelta(seconds=i)).isoformat(),
                     'payload': json.dumps(
                         {'s': 1, 'v': {'lat': -32.0 + i * 1e-3, 'lon': 115.8},
                          't': (T0 + timedelta(seconds=i)).timestamp(),
                          'node': 'gps', 'sub': 0, 'field': 'position',
                          'group': 'Enchantee-GPS', 'name': 'position'})})

    processor = _processor(tmp_path, rows)
    stats = processor.calculate_statistics(1)
    assert stats.get('distance_km', 0) > 0
    assert stats.get('energy_used_wh', 0) > 0
    assert 'efficiency_wh_per_km' in stats, "distance and energy are both present"
    assert stats['efficiency_wh_per_km'] == (stats['energy_used_wh']
                                             / stats['distance_km'])


# --- the GPS stream, found by envelope rather than by topic text ------------------------

def test_the_position_feed_is_found_under_its_envelope_topic(tmp_path):
    """emon/gps/0/position does not start with 'gps/', so a prefix test misses it."""
    rows = []
    for i in range(5):
        rows.append({'topic': 'emon/gps/0/position',
                     'timestamp': (T0 + timedelta(seconds=i)).isoformat(),
                     'payload': json.dumps(
                         {'s': 1, 'v': {'lat': -32.0 + i * 1e-4, 'lon': 115.8 + i * 1e-4},
                          't': (T0 + timedelta(seconds=i)).timestamp(),
                          'node': 'gps', 'sub': 0, 'field': 'position',
                          'group': 'Enchantee-GPS', 'name': 'position'})})
    rows += _envelope_rows('emon/gps/0/speed', 'gps', 0, 'speed',
                           'Enchantee-GPS', 'speed', 'kn', 'speed', n=5)

    processor = _processor(tmp_path, rows)
    streams = processor._find_gps_streams(1)
    assert len(streams) == 1
    assert streams[0].position == 'emon/gps/0/position'
    assert streams[0].speed == 'emon/gps/0/speed'

    fixes = processor._get_track(1, streams[0])
    assert len(fixes) == 5
    assert all(f.fix_ts is not None for f in fixes), \
        "the envelope carries the fix time in 't', not in the value"
    assert all(f.sog is not None for f in fixes)
