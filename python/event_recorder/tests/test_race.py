"""
Race recordings (FR-32): the leg table, the boat at the gun, the marks on the
charts, and the triggers that start a recording on the countdown and stop it
five minutes after the finish.

No broker and no network. Run with pytest, or directly.
"""

import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib
matplotlib.use('Agg')

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from event_recorder import race_analysis as ra  # noqa: E402
from event_recorder import post_renderer  # noqa: E402
from event_recorder.data_processor import DataProcessor  # noqa: E402
from event_recorder.trigger_monitor import GPSTriggerMonitor, TriggerState  # noqa: E402

T0 = 1_800_000_000.0          # the gun
LAT0, LON0 = -32.0, 115.8
M_PER_DEG_LAT = 111_195.0


# === A small course: a line, one mark due north, back to finish ===

def _docs():
    inner = {'lat': LAT0, 'lon': LON0 - 0.001}
    outer = {'lat': LAT0, 'lon': LON0 + 0.001}
    return (
        {'schema': 'pfsyc-courses/1',
         'series': {'test': {'name': 'Test Regatta'}},
         'courses': [{
            'id': 'test-1', 'series': 'test', 'course_no': 1, 'wind_note': 'Northerly breeze',
            'flags': {'division': None, 'numeral': 'pendant-1'},
            'legs': [{'mark': 'north', 'rounding': 'port'},
                     {'finish': True, 'line': 'pfsyc-start-finish'}]}]},
        {'schema': 'pfsyc-marks/2', 'marks': [
            {'id': 'north', 'name': 'North', 'lat': LAT0 + 0.01, 'lon': LON0}]},
        {'schema': 'pfsyc-lines/2', 'start_finish': {
            'id': 'pfsyc-start-finish', 'inner': inner, 'outer': outer}},
    )


def _geometry_for(course_id):
    courses, marks, lines = _docs()
    return ra.course_geometry(course_id, courses, marks, lines)


def _event(kind, ts, leg=0, name=None, **extra):
    e = {'type': kind, 'course': 'test-1', 'leg': leg, 'leg_name': name, 'ts': ts,
         'lat': None, 'lon': None, 'source': 'auto'}
    e.update(extra)
    return e


def _race_events(finish=True):
    events = [_event('select', T0 - 400, 0, 'North'),
              _event('timer', T0 - 300, 0, 'North', start_at=T0),
              _event('start', T0, 0, 'North'),
              _event('rounded', T0 + 600, 1, 'Finish')]
    if finish:
        events.append(_event('finish', T0 + 1200, 1, None))
    return events


def _track(start=T0 - 60, end=T0 + 1300, sog=5.0):
    """Starts 0.0005 deg south of the line, sails north to the mark by T0+600, back by
    T0+1200. One fix a second."""
    fixes = []
    t = start
    while t <= end:
        if t < T0:
            lat = LAT0 - 0.0005
        elif t <= T0 + 600:
            lat = LAT0 + 0.01 * (t - T0) / 600
        elif t <= T0 + 1200:
            lat = LAT0 + 0.01 * (1 - (t - T0 - 600) / 600)
        else:
            lat = LAT0
        fixes.append((t, lat, LON0, sog))
        t += 1.0
    return fixes


def _wind(value, start=T0 - 60, end=T0 + 1300, step=5.0):
    out, t = [], start
    while t <= end:
        out.append((t, value(t) if callable(value) else value))
        t += step
    return out


def _analyse(events=None, end=T0 + 1500, **kw):
    kw.setdefault('twd', _wind(0.0))           # from the north: the mark is upwind
    kw.setdefault('tws', _wind(lambda t: 10.0 + (t % 3)))
    kw.setdefault('awa', _wind(lambda t: -35.0 if t < T0 + 300 else 35.0))
    return ra.analyse(events if events is not None else _race_events(), end,
                      kw.pop('track', _track()), geometry_for=_geometry_for, **kw)


# === The analysis ===

def test_a_race_is_two_legs_with_their_lengths_and_times():
    race = _analyse()
    assert [r['name'] for r in race['legs']] == ['North', 'Finish']
    assert race['finished'] and race['gun'] == T0 and race['finish'] == T0 + 1200
    first, second = race['legs']
    assert math.isclose(first['length_m'], 0.01 * M_PER_DEG_LAT, rel_tol=0.01)
    assert math.isclose(first['duration_s'], 600, abs_tol=1e-6)
    assert math.isclose(first['distance_m'], first['length_m'], rel_tol=0.01)
    assert math.isclose(first['avg_speed_kn'],
                        first['distance_m'] / 1852 / (600 / 3600), rel_tol=1e-9)
    assert not first['unfinished'] and not second['unfinished']


def test_the_point_of_sail_is_the_leg_bearing_against_the_true_wind():
    race = _analyse()
    assert [r['point_of_sail'] for r in race['legs']] == ['Close-hauled', 'Run']
    assert ra.point_of_sail(0, 60) == 'Close reach'
    assert ra.point_of_sail(0, 90) == 'Beam reach'
    assert ra.point_of_sail(0, 270) == 'Beam reach'
    assert ra.point_of_sail(0, 120) == 'Broad reach'
    assert ra.point_of_sail(0, 49) == 'Close-hauled'
    assert ra.point_of_sail(None, 90) is None


def test_no_leg_is_ever_called_a_beat():
    assert 'Beat' not in {name for _, name in ra.POINTS_OF_SAIL}


def test_the_wind_direction_is_averaged_as_an_angle():
    assert math.isclose(ra.circular_mean([350, 10]), 0.0, abs_tol=1e-9) or \
        math.isclose(ra.circular_mean([350, 10]), 360.0, abs_tol=1e-9)
    race = _analyse(twd=_wind(lambda t: 350.0 if int(t) % 2 else 10.0, step=1.0))
    twd = race['legs'][0]['twd']
    assert min(twd, 360 - twd) < 1.0


def test_wind_speed_and_the_tacks_are_split_by_leg():
    race = _analyse()
    first, second = race['legs']
    assert first['tws_min'] == 10.0 and first['tws_max'] == 12.0
    assert 10.0 < first['tws_mean'] < 12.0
    # Port for the first half of leg 1, starboard after it
    assert first['awa_port'] == 35.0 and first['awa_starboard'] == 35.0
    assert second['awa_port'] is None and second['awa_starboard'] == 35.0


def test_the_tacks_ignore_a_boat_drifting():
    race = _analyse(track=_track(sog=0.5))
    assert race['legs'][0]['awa_port'] is None
    assert race['legs'][0]['awa_starboard'] is None


def test_an_awa_recorded_as_a_bearing_off_the_bow_reads_as_signed():
    race = _analyse(awa=_wind(325.0))
    assert race['legs'][0]['awa_port'] == 35.0


def test_the_totals_sum_the_legs_and_average_the_race():
    race = _analyse()
    total, legs = race['total'], race['legs']
    assert math.isclose(total['distance_m'], sum(r['distance_m'] for r in legs))
    assert math.isclose(total['length_m'], sum(r['length_m'] for r in legs))
    assert math.isclose(total['duration_s'], 1200, abs_tol=1e-6)
    assert math.isclose(total['avg_speed_kn'],
                        total['distance_m'] / 1852 / (1200 / 3600), rel_tol=1e-9)
    assert total['tws_min'] == 10.0 and total['tws_max'] == 12.0
    assert total['awa_port'] == 35.0 and total['awa_starboard'] == 35.0


def test_the_boat_at_the_gun_is_found_from_the_track():
    race = _analyse()
    start = race['start']
    assert math.isclose(start['lat'], LAT0, abs_tol=2e-5)
    assert start['distance_to_line_m'] < 3.0


def test_the_boat_behind_the_line_at_the_gun_is_behind():
    events = _race_events()
    events[2]['lat'], events[2]['lon'] = LAT0 - 0.0005, LON0
    start = _analyse(events=events)['start']
    assert start['side'] == 'behind'
    assert math.isclose(start['distance_to_line_m'], 0.0005 * M_PER_DEG_LAT, rel_tol=0.01)
    events[2]['lat'] = LAT0 + 0.0002
    assert _analyse(events=events)['start']['side'] == 'over'


def test_a_race_with_no_finish_ends_with_the_recording_unfinished():
    race = _analyse(events=_race_events(finish=False), end=T0 + 900)
    assert not race['finished'] and race['finish'] is None
    assert race['legs'][-1]['unfinished']
    assert math.isclose(race['legs'][-1]['duration_s'], 300, abs_tol=1e-6)
    assert race['marks'][-1]['label'] == 'End'


def test_a_race_joined_late_starts_at_the_step_forward():
    events = [_event('select', T0 - 400, 0, 'North'),
              _event('rounded', T0 + 600, 1, 'Finish', source='manual'),
              _event('finish', T0 + 1200, 1, None, source='manual')]
    race = _analyse(events=events)
    assert race['gun'] is None and race['start'] is None
    assert [r['leg'] for r in race['legs']] == [2]
    assert race['marks'][0]['label'] == 'Joined'


def test_a_restart_after_a_recall_begins_the_race_again():
    events = _race_events()
    events.insert(3, _event('start', T0 + 120, 0, 'North'))
    race = _analyse(events=events)
    assert race['gun'] == T0 + 120
    assert math.isclose(race['legs'][0]['duration_s'], 480, abs_tol=1e-6)


def test_a_step_back_returns_time_to_the_leg():
    events = _race_events()
    events[3:3] = [_event('rounded', T0 + 100, 1, 'Finish', source='manual'),
                   _event('back', T0 + 110, 0, 'North', source='manual')]
    race = _analyse(events=events)
    first, second = race['legs']
    assert math.isclose(first['duration_s'], 590, abs_tol=1e-6)
    assert math.isclose(second['duration_s'], 610, abs_tol=1e-6)


def test_the_triggering_event_recorded_twice_counts_once():
    events = _race_events()
    events.append(dict(events[3]))
    assert len(ra.dedupe_events(events)) == len(_race_events())
    assert len(_analyse(events=events)['legs']) == 2


def test_a_reset_ends_the_race_unfinished():
    events = _race_events(finish=False) + [_event('reset', T0 + 900, 1, 'Finish')]
    race = _analyse(events=events, end=T0 + 5000)
    assert not race['finished']
    assert math.isclose(race['total']['duration_s'], 900, abs_tol=1e-6)


def test_no_race_in_the_recording_is_none():
    assert _analyse(events=[_event('select', T0, 0, 'North'),
                            _event('timer', T0 + 1, 0, 'North', start_at=T0 + 301)]) is None


def test_an_unknown_course_still_tables_the_legs_without_lengths():
    events = [dict(e, course='nowhere') for e in _race_events()]
    race = _analyse(events=events)
    assert [r['name'] for r in race['legs']] == ['North', 'Finish']
    assert race['legs'][0]['length_m'] is None and race['legs'][0]['point_of_sail'] is None
    assert race['total']['length_m'] is None


def test_the_charts_are_marked_at_the_start_each_rounding_and_the_finish():
    race = _analyse()
    assert [(m['label'], m['t']) for m in race['marks']] == [
        ('Start', T0), ('North', T0 + 600), ('Finish', T0 + 1200)]


def test_the_analysis_is_json_ready():
    json.dumps(_analyse())


def test_a_race_is_called_what_the_race_app_calls_it():
    courses = _docs()[0]
    identity = ra.course_identity('test-1', courses)
    assert identity['title'] == 'Test Regatta · Course 1 · Northerly breeze'
    assert identity['flags'] == ['pendant-1']
    courses['courses'][0]['flags'] = {'division': 'naval-2', 'numeral': 'pendant-1'}
    assert ra.course_identity('test-1', courses)['flags'] == ['naval-2', 'pendant-1']
    courses['courses'][0]['wind_note'] = None
    assert ra.course_identity('test-1', courses)['title'] == 'Test Regatta · Course 1'
    assert ra.course_identity('nowhere', courses) is None


def test_the_real_opening_day_course_is_titled_as_the_race_app_heads_it():
    path = ROOT / 'enchantee_racing' / 'config' / 'courses.json'
    if not path.exists():
        return
    identity = ra.course_identity('opening-day-1', json.loads(path.read_text()))
    assert identity['title'].startswith('Opening Day Regatta · Course 1')


# === A real race: Opening Day, 1 November 2026 ===
#
# The boat's own log of the day, committed with the race app's replay tests, run through
# the race app's engine for the race events exactly as it ran live, then through this
# module. The figures are the ones recording 113 gave from the same race as the boat
# recorded it, so a change to the analysis that would have told the day differently
# fails here.

RACING = ROOT / 'enchantee_racing'
OPENING_DAY_LOG = RACING / 'tests' / 'data' / '20261101_OpeningDay_1.TXT'


def _opening_day():
    sys.path.insert(0, str(RACING))
    from engine import course as course_module, nav, race

    def seconds(clock):
        h, m, sec = (int(p) for p in clock.split(':'))
        return float(h * 3600 + m * 60 + sec)

    track, twd, tws, awa = [], [], [], []
    for line in open(OPENING_DAY_LOG, encoding='utf-8', errors='replace'):
        f = line.rstrip().split(',')
        if len(f) < 6:
            continue
        try:
            t = seconds(f[0][11:])
            if f[1] == 'gps' and f[2] == '0' and len(f) >= 7:
                track.append((t, float(f[3]), float(f[4]), float(f[6]), float(f[5])))
            elif f[1] == 'mwv' and f[2] == '2':
                tws.append((t, float(f[3])))
                twd.append((t, float(f[4])))
            elif f[1] == 'mwv' and f[2] == '0':
                awa.append((t, float(f[4])))
        except ValueError:
            continue

    config = RACING / 'config'
    docs = {name: json.loads((config / f'{name}.json').read_text())
            for name in ('courses', 'marks', 'lines', 'race')}
    chosen = [c for c in docs['courses']['courses'] if c['id'] == 'opening-day-1'][0]
    context = race.Context(course=chosen, marks=course_module.index_marks(docs['marks']),
                           lines=docs['lines'],
                           config=race.Config.from_document(docs['race']))
    gun = seconds('14:35:04')
    state, events = race.select(race.initial(), context, 'opening-day-1', gun - 600)
    state, more = race.set_timer(state, context, minutes=0, now=gun)
    events += more
    state, more = race.on_clock(state, context, gun)
    events += more
    for t, lat, lon, sog, cog in track:
        if t < gun:
            continue
        state, more = race.on_fix(state, context, race.Fix(nav.LatLon(lat, lon), t, cog, sog), t)
        events += more
        if state.mode == race.FINISHED:
            break

    def geometry_for(course_id):
        return ra.course_geometry(course_id, docs['courses'], docs['marks'], docs['lines'])

    return ra.analyse(events, seconds('17:16:29'),
                      [(t, lat, lon, sog) for t, lat, lon, sog, _cog in track],
                      twd=twd, tws=tws, awa=awa, geometry_for=geometry_for)


def test_opening_day_is_tabled_leg_by_leg_as_the_day_went():
    if not OPENING_DAY_LOG.exists():
        raise AssertionError(f"{OPENING_DAY_LOG} is committed; its absence is a broken checkout")
    race = _opening_day()
    legs = race['legs']
    assert [r['name'] for r in legs] == [
        'Miller', 'Dolphin East', 'Smith', 'Lucky Bay', 'Squadron', 'Dolphin West',
        'Sanders', 'Hallmark', 'Finish']
    assert [r['point_of_sail'] for r in legs] == [
        'Close-hauled', 'Run', 'Close-hauled', 'Broad reach', 'Broad reach', 'Broad reach',
        'Close-hauled', 'Broad reach', 'Close-hauled']
    assert race['finished'] and not any(r['unfinished'] for r in legs)
    assert abs(race['total']['length_m'] / 1852 - 9.40) < 0.01
    assert abs(race['total']['duration_s'] - 9385) < 2
    # As the boat recorded it: 11.74 nm sailed, 4.5 kn, a westerly of about 250
    assert abs(race['total']['distance_m'] / 1852 - 11.74) < 0.15
    assert abs(race['total']['avg_speed_kn'] - 4.5) < 0.1
    assert abs(race['total']['twd'] - 250) < 3
    # Upwind at the low thirties off the bow, on both tacks
    for leg in (legs[0], legs[2], legs[8]):
        assert 28 < leg['awa_port'] < 40 and 28 < leg['awa_starboard'] < 40, leg
    # 73 m behind the line at the gun, from the track: the start event carries no fix
    assert race['start']['side'] == 'behind'
    assert abs(race['start']['distance_to_line_m'] - 73) < 10


# === The post ===

def test_the_post_table_has_a_row_per_leg_and_a_total_in_both_units():
    race = _analyse()
    race['gun_local'], race['finish_local'] = '13:35:00', '13:55:00'
    table = post_renderer.race_table_html(race)
    assert table.count('<tr>') == 1 + 2 + 1
    assert 'Close-hauled' in table and 'Run' in table and 'Total' in table
    assert ' nm<br>' in table and ' km' in table
    assert 'Start: 13:35:00' in table and 'Finish: 13:55:00' in table
    assert 'At the gun:' in table


def test_the_statistics_table_leaves_the_race_to_its_own_table():
    stats = {'duration': '0:20:00', 'race': _analyse()}
    table = post_renderer.statistics_table_html(stats)
    assert 'Race' not in table and 'legs' not in table


def test_the_statistics_block_draws_the_race_above_the_statistics():
    ctx = post_renderer.PostContext({'name': 'r'},
                                    statistics={'duration': '0:20:00', 'race': _analyse()})
    out = post_renderer.render([{'type': 'statistics', 'heading': True}], ctx)
    assert out.index('Race') < out.index('Statistics')


def test_the_flags_are_small_inline_images_at_the_top_of_the_post():
    race = _analyse()
    race['title'] = 'Test Regatta · Course 1'
    race['flags'] = [{'name': 'naval-2', 'svg': '<svg id="p"></svg>'},
                     {'name': 'pendant-1', 'svg': '<svg id="p"></svg>'}]
    flags = post_renderer.race_flags_html(race)
    assert flags.count('<img src="data:image/svg+xml;base64,') == 2
    assert 'height="28"' in flags and 'Test Regatta' in flags
    for layout in post_renderer.LAYOUTS.values():
        assert layout[0] == {'type': 'race_flags'}
    ctx = post_renderer.PostContext({'name': 'r'}, statistics={'race': race})
    out = post_renderer.render(post_renderer.LAYOUTS['ship_log'], ctx)
    assert out.index('data:image/svg+xml') < out.index('Race')


def test_a_recording_with_no_race_has_no_flags():
    assert post_renderer.race_flags_html(None) == ''
    assert post_renderer.race_flags_html({'flags': []}) == ''
    ctx = post_renderer.PostContext({'name': 'r'}, statistics={'duration': '1:00:00'})
    assert post_renderer.render([{'type': 'race_flags'}], ctx) == ''


def test_a_recording_with_no_race_draws_no_race_table():
    assert post_renderer.race_table_html(None) == ''
    assert post_renderer.race_table_html({'legs': []}) == ''


# === Processing ===

class _FakeDB:
    def __init__(self, rows, recording):
        self.rows, self.recording = rows, recording
        self.images = []

    def get_recording(self, recording_id):
        return self.recording

    def get_recording_topics(self, recording_id):
        return sorted({r['topic'] for r in self.rows})

    def get_recording_data(self, recording_id, topic_filter=None, limit=None):
        rows = [r for r in self.rows if r['topic'] == topic_filter]
        return rows[:limit] if limit else rows

    def last_data_time(self, recording_id):
        return None


def _iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).replace(tzinfo=None).isoformat()


def _recording_rows():
    rows = []
    for t, lat, lon, sog in _track():
        rows.append({'topic': 'gps/position/0', 'timestamp': _iso(t),
                     'payload': json.dumps({'lat': lat, 'lon': lon})})
        rows.append({'topic': 'gps/speed/0', 'timestamp': _iso(t), 'payload': str(sog)})
    for t, v in _wind(0.0):
        rows.append({'topic': 'anemometer/windDirection/2', 'timestamp': _iso(t),
                     'payload': str(v)})
        rows.append({'topic': 'anemometer/windSpeed/2', 'timestamp': _iso(t),
                     'payload': '10'})
        rows.append({'topic': 'anemometer/windDirection/0', 'timestamp': _iso(t),
                     'payload': '325'})
    for e in _race_events():
        rows.append({'topic': 'race/event', 'timestamp': _iso(e['ts']),
                     'payload': json.dumps(e)})
    rows.sort(key=lambda r: r['timestamp'])
    return rows


def _processor(tmp_path):
    cache = tmp_path / 'charts'
    cache.mkdir()
    courses, marks, lines = _docs()
    box = [[[115.7, -32.1], [115.9, -32.1], [115.9, -31.9], [115.7, -31.9], [115.7, -32.1]]]
    coast = {'schema': 'pfsyc-coast/1', 'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {'kind': 'extent'},
         'geometry': {'type': 'Polygon', 'coordinates': box}}]}
    for name, doc in (('coast', coast), ('courses', courses), ('marks', marks),
                      ('lines', lines)):
        (cache / f'{name}.json').write_text(json.dumps(doc))
    (cache / 'flags').mkdir()
    (cache / 'flags' / 'pendant-1.svg').write_text('<svg>1</svg>')
    recording = {'id': 1, 'start_time': _iso(T0 - 60), 'end_time': _iso(T0 + 1300)}
    return DataProcessor(_FakeDB(_recording_rows(), recording), str(tmp_path / 'plots'),
                         {'enabled': True, 'base_url': 'http://127.0.0.1:1',
                          'cache_dir': str(cache), 'timeout': 1})


def test_a_recording_is_analysed_from_its_feeds_and_the_cached_course(tmp_path):
    race = _processor(tmp_path).analyse_race(1)
    assert [r['point_of_sail'] for r in race['legs']] == ['Close-hauled', 'Run']
    assert race['legs'][0]['tws_mean'] == 10.0
    assert race['legs'][0]['awa_port'] == 35.0
    assert race['gun_local'] and race['finish_local']
    assert race['title'] == 'Test Regatta · Course 1 · Northerly breeze'
    assert race['flags'] == [{'name': 'pendant-1', 'svg': '<svg>1</svg>'}]


def test_a_flag_with_an_odd_name_is_never_fetched(tmp_path):
    processor = _processor(tmp_path)
    assert processor.chart_cache.flag_svg('../../etc/passwd') is None
    assert processor.chart_cache.flag_svg('pendant-1') == '<svg>1</svg>'


def test_the_race_recording_is_named_from_its_course_when_it_starts(tmp_path):
    from event_recorder import main as main_module
    (tmp_path / 'charts').mkdir()
    (tmp_path / 'charts' / 'courses.json').write_text(json.dumps(_docs()[0]))
    added, updated = [], []

    class _Config:
        def get(self, key, default=None):
            return {'enabled': True, 'base_url': 'http://127.0.0.1:1',
                    'cache_dir': str(tmp_path / 'charts'), 'timeout': 1}

        def get_plots_dir(self):
            return str(tmp_path / 'plots')

    class _Fake:
        config = _Config()
        data_recorder = type('R', (), {'buffer': type('B', (), {
            'add_message': staticmethod(lambda *a: added.append(a))})()})()
        database = type('D', (), {
            'update_recording': staticmethod(lambda rid, **kw: updated.append((rid, kw)))})()

    payload = json.dumps(_event('timer', T0, 0, 'North', start_at=T0 + 300))
    main_module.EventRecorderService._on_trigger_message(
        _Fake(), 7, 'race/event', payload, datetime.utcnow())
    assert len(added) == 1
    assert updated == [(7, {'name': 'Test Regatta · Course 1 · Northerly breeze'})]


def test_every_time_chart_and_the_route_map_carry_the_race(tmp_path):
    processor = _processor(tmp_path)
    processor._race = processor.analyse_race(1)
    out = tmp_path / 'out'
    out.mkdir()
    marked = []
    original = processor._mark_race

    def spy(ax):
        pad = original(ax)
        marked.append(len(ax.lines))
        return pad
    processor._mark_race = spy
    processor._generate_line_plot(1, {'title': 'Wind', 'topics': ['anemometer/windSpeed/2']}, out)
    processor._generate_multi_line_plot(
        1, {'title': 'Wind 2', 'topics': ['anemometer/windSpeed/2']}, out)
    assert marked == [1 + 3, 1 + 3]      # the series and three race lines, each chart
    path = processor._generate_route_map(1, {'title': 'Route Map',
                                             'topics': ['gps/position/0']}, out)
    assert path.exists()


def test_marks_too_close_to_label_apart_share_a_label(tmp_path):
    processor = _processor(tmp_path)
    processor._race = {'marks': [
        {'t': T0, 'label': 'Start', 'kind': 'start'},
        {'t': T0 + 3000, 'label': 'Smith', 'kind': 'leg'},
        {'t': T0 + 3040, 'label': 'Lucky Bay', 'kind': 'leg'},
        {'t': T0 + 9000, 'label': 'Finish', 'kind': 'finish'}]}
    labels = [label.split(' ', 1)[1].rsplit(' ', 1)[0] for _, label, _ in
              processor._race_labels()]
    assert labels == ['Start', 'Smith, Lucky Bay', 'Finish']


def test_the_race_events_are_not_charted_as_a_series(tmp_path):
    # Live on 18 Nov 2026 they drew a "RACE Event" chart of nothing into the post
    specs = _processor(tmp_path)._auto_generate_plot_config(1)
    assert not [t for spec in specs for t in spec['topics'] if t.startswith('race/')]
    assert any('anemometer/windSpeed/2' in spec['topics'] for spec in specs)


def test_the_charts_of_an_ordinary_recording_are_unmarked(tmp_path):
    processor = _processor(tmp_path)
    out = tmp_path / 'out'
    out.mkdir()
    processor._generate_line_plot(1, {'title': 'Wind', 'topics': ['anemometer/windSpeed/2']}, out)
    assert processor._race is None


# === The triggers ===

class _Msg:
    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = payload.encode('utf-8') if isinstance(payload, str) else payload


RACE_CONFIG = {
    'monitor_topics': ['gps/position/0', 'race/event'],
    'start_condition': {'type': 'race_event', 'events': ['timer', 'start', 'rounded']},
    'stop_condition': [
        {'type': 'race_finish', 'events': ['finish'], 'grace': 300},
        {'type': 'anchor_return', 'anchor_lat': -32.1, 'anchor_lon': 115.7,
         'radius': 50, 'duration': 15},
    ],
    'record_topics': ['emon/#', 'race/#'],
}


def _monitor():
    monitor = GPSTriggerMonitor()
    calls = {'start': [], 'stop': [], 'message': []}

    def on_start(monitor_id, config):
        calls['start'].append(monitor_id)
        return 42

    def on_stop(monitor_id, recording_id):
        calls['stop'].append(recording_id)

    monitor.add_monitor('race_recording', RACE_CONFIG, on_start, on_stop)
    monitor.on_trigger_message = lambda *args: calls['message'].append(args)
    return monitor, calls


def _race(monitor, kind, **extra):
    monitor._on_message(None, None, _Msg('race/event', json.dumps(
        dict({'type': kind, 'course': 'test-1', 'leg': 0, 'ts': T0}, **extra))))


def _fix(monitor, lat=LAT0, lon=LON0):
    monitor._on_message(None, None, _Msg('gps/position/0',
                                         json.dumps({'lat': lat, 'lon': lon})))


def test_the_countdown_starts_a_race_recording_and_is_written_into_it():
    monitor, calls = _monitor()
    _race(monitor, 'timer', start_at=T0 + 300)
    assert calls['start'] == ['race_recording']
    assert monitor.monitor_states['race_recording']['state'] == TriggerState.TRIGGERED
    recording_id, topic, payload, _ = calls['message'][0]
    assert recording_id == 42 and topic == 'race/event'
    assert json.loads(payload)['type'] == 'timer'


def test_a_cleared_timer_starts_nothing():
    monitor, calls = _monitor()
    _race(monitor, 'timer', start_at=None)
    _race(monitor, 'select')
    assert calls['start'] == []


def test_a_leg_stepped_forward_late_starts_it():
    monitor, calls = _monitor()
    _race(monitor, 'rounded', leg=3, source='manual')
    assert calls['start'] == ['race_recording']


def test_it_stops_five_minutes_after_the_finish_not_at_it():
    monitor, calls = _monitor()
    _race(monitor, 'timer', start_at=T0)
    _fix(monitor)
    _race(monitor, 'finish', leg=1)
    _fix(monitor)
    assert calls['stop'] == []
    state = monitor.monitor_states['race_recording']
    state['race_finished_at'] -= timedelta(seconds=301)
    _fix(monitor)
    assert calls['stop'] == [42]
    assert state['state'] == TriggerState.MONITORING and state['race_finished_at'] is None


def test_it_stops_back_at_the_mooring_without_a_finish():
    monitor, calls = _monitor()
    _race(monitor, 'timer', start_at=T0)
    _fix(monitor, -32.1, 115.7)
    monitor.monitor_states['race_recording']['stationary_start_time'] -= timedelta(seconds=16)
    _fix(monitor, -32.1, 115.7)
    assert calls['stop'] == [42]


def test_the_next_race_starts_a_new_recording():
    monitor, calls = _monitor()
    _race(monitor, 'timer', start_at=T0)
    _race(monitor, 'finish', leg=1)
    monitor.monitor_states['race_recording']['race_finished_at'] -= timedelta(seconds=301)
    _fix(monitor)
    _race(monitor, 'timer', start_at=T0 + 3600)
    assert calls['start'] == ['race_recording', 'race_recording']


def test_race_events_leave_a_gps_monitor_alone():
    monitor, calls = _monitor()
    monitor.add_monitor('anchor', {
        'monitor_topics': ['gps/position/0'],
        'start_condition': {'type': 'anchor_departure', 'anchor_lat': LAT0,
                            'anchor_lon': LON0, 'radius': 50},
        'stop_condition': {'type': 'anchor_return', 'anchor_lat': LAT0,
                           'anchor_lon': LON0, 'radius': 50},
        'record_topics': ['emon/#']})
    _race(monitor, 'timer', start_at=T0)
    assert calls['start'] == ['race_recording']
    assert monitor.monitor_states['anchor']['state'] == TriggerState.MONITORING


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__, '-v']))
