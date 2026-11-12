"""The boat's own daily log files, attached to a published post.

emon_log writes one /share/Input/<YYYYMMDD>.TXT per day, named in the boat's timezone.
A recording names the days it touches and the files are attached where they lie: never
copied, never written to, never deleted.

Run in the dev container (dev/README.md):
    python -m pytest event_recorder/tests/test_raw_logs.py
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib
matplotlib.use('Agg')

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from event_recorder.data_processor import DataProcessor  # noqa: E402
from event_recorder.models import Database, RecordingStatus  # noqa: E402

# A sail on the afternoon of 13 September, boat time: 13:04 to 15:53 in Perth, which
# is the morning of the same day in UTC.
START = datetime(2026, 9, 13, 5, 4)
END = datetime(2026, 9, 13, 7, 53)

BOAT_OFFSET = timedelta(hours=8)


class _FakeDB:
    """Only what find_raw_logs and the export config reach for."""

    def __init__(self, recording):
        self.recording = recording

    def get_recording(self, recording_id):
        return self.recording

    def get_recording_topics(self, recording_id):
        return []

    def get_recording_data(self, recording_id, topic_filter=None, limit=None):
        return []


def _boat_time(stamp):
    """_utc_to_local with the boat's offset, so a test does not depend on the
    timezone of the machine running it."""
    if stamp is None:
        return None
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone(timezone.utc).replace(tzinfo=None)
    return stamp + BOAT_OFFSET


def _processor(tmp_path, monkeypatch, start=START, end=END, log_dir='logs'):
    monkeypatch.setattr(DataProcessor, '_utc_to_local', staticmethod(_boat_time))
    logs = tmp_path / log_dir
    logs.mkdir(exist_ok=True)
    db = _FakeDB({'name': 'Test',
                  'start_time': start.isoformat() if start else None,
                  'end_time': end.isoformat() if end else None})
    processor = DataProcessor(db, str(tmp_path / 'plots'), {'enabled': False},
                              raw_log_dir=str(logs))
    return processor, logs


def _write(logs, *days):
    for day in days:
        (logs / f"{day}.TXT").write_text(f"log for {day}\n", encoding='utf-8')


def test_the_days_log_is_attached(tmp_path, monkeypatch):
    processor, logs = _processor(tmp_path, monkeypatch)
    _write(logs, '20260913')

    found = processor.find_raw_logs(processor.database.recording)
    assert [(p.name, label) for p, label in found] == \
        [('20260913.TXT', 'Raw log 2026-09-13')]


def test_the_file_is_named_for_the_boats_day_not_the_utc_one(tmp_path, monkeypatch):
    """A twilight sail finishing at 21:00 in Perth is 13:00 UTC on the same date, but
    an early-morning start is the previous date in UTC. The log file is named by
    emon_log in the boat's timezone, so that is the date to look for."""
    start = datetime(2026, 9, 13, 22, 30)      # 06:30 on the 14th, boat time
    end = datetime(2026, 9, 13, 23, 45)        # 07:45 on the 14th, boat time
    processor, logs = _processor(tmp_path, monkeypatch, start=start, end=end)
    _write(logs, '20260913', '20260914')

    found = processor.find_raw_logs(processor.database.recording)
    assert [p.name for p, _ in found] == ['20260914.TXT']


def test_a_sail_over_more_than_one_day_attaches_a_log_for_each(tmp_path, monkeypatch):
    """An overnight passage: every day it touches, not only the first."""
    start = datetime(2026, 9, 13, 5, 0)        # 13:00 on the 13th, boat time
    end = datetime(2026, 9, 15, 2, 0)          # 10:00 on the 15th, boat time
    processor, logs = _processor(tmp_path, monkeypatch, start=start, end=end)
    _write(logs, '20260913', '20260914', '20260915')

    found = processor.find_raw_logs(processor.database.recording)
    assert [p.name for p, _ in found] == \
        ['20260913.TXT', '20260914.TXT', '20260915.TXT']
    assert [label for _, label in found] == \
        ['Raw log 2026-09-13', 'Raw log 2026-09-14', 'Raw log 2026-09-15']


def test_a_day_with_no_log_is_skipped_rather_than_failing(tmp_path, monkeypatch):
    start = datetime(2026, 9, 13, 5, 0)
    end = datetime(2026, 9, 15, 2, 0)
    processor, logs = _processor(tmp_path, monkeypatch, start=start, end=end)
    _write(logs, '20260913', '20260915')       # the recorder was down on the 14th

    found = processor.find_raw_logs(processor.database.recording)
    assert [p.name for p, _ in found] == ['20260913.TXT', '20260915.TXT']


def test_the_whole_day_is_attached_not_the_recorded_part(tmp_path, monkeypatch):
    """Two sails on one day attach the same file to both posts, which is intended:
    the file is the boat's raw record of the day, not of the recording."""
    processor, logs = _processor(tmp_path, monkeypatch)
    _write(logs, '20260913')
    morning = processor.find_raw_logs(
        {'start_time': datetime(2026, 9, 13, 1, 0).isoformat(),
         'end_time': datetime(2026, 9, 13, 3, 0).isoformat()})
    afternoon = processor.find_raw_logs(
        {'start_time': START.isoformat(), 'end_time': END.isoformat()})
    assert morning == afternoon


def test_a_recording_still_running_takes_its_logs_up_to_today(tmp_path, monkeypatch):
    """No end time yet. The day it started is still the day to attach."""
    processor, logs = _processor(tmp_path, monkeypatch, end=None)
    _write(logs, '20260913')
    found = processor.find_raw_logs(processor.database.recording)
    assert [p.name for p, _ in found] == ['20260913.TXT']


def test_no_log_directory_means_no_logs(tmp_path, monkeypatch):
    """A deployment without emon_log beside it, which is most of them."""
    monkeypatch.setattr(DataProcessor, '_utc_to_local', staticmethod(_boat_time))
    db = _FakeDB({'start_time': START.isoformat(), 'end_time': END.isoformat()})
    processor = DataProcessor(db, str(tmp_path / 'plots'), {'enabled': False})

    assert processor.find_raw_logs(db.recording) == []
    assert processor._auto_generate_export_config(1)['logs'] is False


def test_logs_are_on_by_default_where_the_directory_is(tmp_path, monkeypatch):
    processor, _ = _processor(tmp_path, monkeypatch)
    assert processor._auto_generate_export_config(1)['logs'] is True


def test_a_configured_directory_that_is_gone_is_not_fatal(tmp_path, monkeypatch):
    processor, logs = _processor(tmp_path, monkeypatch)
    _write(logs, '20260913')
    processor.raw_log_dir = tmp_path / 'not-mounted'
    assert processor.find_raw_logs(processor.database.recording) == []


def test_processing_registers_the_log_as_an_export(tmp_path, monkeypatch):
    """End to end against a real database: a 'log' export row is what carries the
    file into _gather, and from there into the post's Downloads."""
    monkeypatch.setattr(DataProcessor, '_utc_to_local', staticmethod(_boat_time))
    logs = tmp_path / 'logs'
    logs.mkdir()
    _write(logs, '20260913')

    db = Database(str(tmp_path / 'rec.db'))
    rid = db.create_recording('x')
    db.update_recording(rid, status=RecordingStatus.STOPPED,
                        start_time=START.isoformat(), end_time=END.isoformat())

    processor = DataProcessor(db, str(tmp_path / 'plots'), {'enabled': False},
                              raw_log_dir=str(logs))
    results = processor.process_recording(rid, plot_config=[],
                                          export_config={'logs': True})

    assert results['status'] == 'success'
    assert [(e['type'], Path(e['path']).name) for e in results['exports']] == \
        [('log', '20260913.TXT')]
    rows = [r for r in db.get_recording_exports(rid) if r['export_type'] == 'log']
    assert len(rows) == 1
    assert Path(rows[0]['file_path']) == logs / '20260913.TXT'
    assert rows[0]['label'] == 'Raw log 2026-09-13'
    # And reprocessing does not accumulate a second row for the same file
    processor.process_recording(rid, plot_config=[], export_config={'logs': True})
    assert len([r for r in db.get_recording_exports(rid)
                if r['export_type'] == 'log']) == 1


def test_a_database_from_before_the_log_type_is_migrated(tmp_path):
    """The boat's database has a recording_exports whose CHECK allows only csv, kml
    and gpx. add_export uses INSERT OR IGNORE, so without a migration a raw log is
    rejected and silently dropped: the export never appears and nothing is logged.
    The existing rows must survive the recreation."""
    import sqlite3

    path = tmp_path / 'old.db'
    db = Database(str(path))                      # current schema
    rid = db.create_recording('x')
    db.add_export(rid, 'gpx', str(tmp_path / 'track.gpx'), 'GPS Track')

    # Put the old constraint back, as a database written before today has it
    with sqlite3.connect(str(path)) as conn:
        conn.execute("PRAGMA legacy_alter_table=ON")
        conn.execute("ALTER TABLE recording_exports RENAME TO old")
        conn.execute("""
            CREATE TABLE recording_exports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recording_id INTEGER NOT NULL,
                export_type TEXT NOT NULL CHECK(export_type IN ('csv', 'kml', 'gpx')),
                file_path TEXT NOT NULL UNIQUE,
                label TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE
            )
        """)
        conn.execute("INSERT INTO recording_exports SELECT * FROM old")
        conn.execute("DROP TABLE old")

    reopened = Database(str(path))                # migrates on open
    assert reopened.add_export(rid, 'log', str(tmp_path / '20260913.TXT'),
                               'Raw log 2026-09-13')
    rows = reopened.get_recording_exports(rid)
    assert sorted(r['export_type'] for r in rows) == ['gpx', 'log']
    assert [r['label'] for r in rows if r['export_type'] == 'gpx'] == ['GPS Track']


def test_the_log_is_referenced_where_it_lies_and_left_alone(tmp_path, monkeypatch):
    """Nothing here may copy, move or write to the boat's logs: the mount is
    read-only and the file is the only record of the day."""
    processor, logs = _processor(tmp_path, monkeypatch)
    _write(logs, '20260913')
    before = (logs / '20260913.TXT').read_text(encoding='utf-8')

    found = processor.find_raw_logs(processor.database.recording)
    assert found[0][0] == logs / '20260913.TXT'
    assert (logs / '20260913.TXT').read_text(encoding='utf-8') == before
    assert sorted(p.name for p in logs.iterdir()) == ['20260913.TXT']
