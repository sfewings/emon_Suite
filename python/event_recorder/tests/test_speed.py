"""The Log page and notes were slow: ten seconds a load on the dev rig.

Run in the dev container (dev/README.md):
    python -m pytest event_recorder/tests/test_speed.py

Two causes. Every read of one topic of one recording walked all of the recording's rows,
the table being indexed on recording alone; and a finished recording's wind line and
categories were worked out again every minute the page was open.
"""

import sqlite3
import time
from datetime import datetime, timedelta

import pytest

from event_recorder import post_suggestions
from event_recorder.models import Database, RecordingStatus
from event_recorder.recording_service import RecordingService

INDEX = "idx_recording_data_recording_topic_time"

# The reads the Log page and a note make, as models.py makes them
HOT_QUERIES = [
    "SELECT timestamp, CAST(payload AS REAL) FROM recording_data "
    "WHERE recording_id = 1 AND topic = 'anemometer/windSpeed/2' ORDER BY timestamp",
    "SELECT timestamp, payload FROM recording_data WHERE recording_id = 1 "
    "AND topic = 'gps/position/0' AND timestamp > '' ORDER BY timestamp",
    "SELECT timestamp, payload FROM recording_data WHERE recording_id = 1 "
    "AND topic = 'gps/position/0' AND timestamp <= '2026-10-10' ORDER BY timestamp DESC LIMIT 1",
    "SELECT MAX(CAST(payload AS REAL)) FROM recording_data WHERE recording_id = 1 "
    "AND topic = 'gps/speed/0' AND timestamp > ''",
]


def _indexes(path):
    conn = sqlite3.connect(path)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    conn.close()
    return names


def test_a_new_database_is_indexed_by_recording_topic_and_time(tmp_path):
    path = tmp_path / "new.db"
    Database(str(path))
    names = _indexes(path)
    assert INDEX in names
    assert "idx_recording_data_recording_id" not in names


def test_an_existing_database_gains_the_index_and_loses_the_redundant_one(tmp_path):
    path = tmp_path / "old.db"
    Database(str(path))
    conn = sqlite3.connect(path)
    conn.execute(f"DROP INDEX {INDEX}")
    conn.execute("CREATE INDEX idx_recording_data_recording_id ON recording_data(recording_id)")
    conn.commit()
    conn.close()

    Database(str(path))

    names = _indexes(path)
    assert INDEX in names and "idx_recording_data_recording_id" not in names


@pytest.mark.parametrize("query", HOT_QUERIES)
def test_the_pages_reads_use_it_rather_than_walking_the_recording(tmp_path, query):
    path = tmp_path / "rec.db"
    Database(str(path))
    conn = sqlite3.connect(path)
    plan = " ".join(row[3] for row in conn.execute("EXPLAIN QUERY PLAN " + query))
    conn.close()
    assert INDEX in plan, plan
    assert "TEMP B-TREE" not in plan, f"sorts what it read: {plan}"


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "rec.db"))


def _counting(monkeypatch):
    calls = []
    real = post_suggestions.wind_line
    monkeypatch.setattr(post_suggestions, "wind_line",
                        lambda database, rid: calls.append(rid) or real(database, rid))
    return calls


def test_a_finished_recordings_lines_are_worked_out_once(db, monkeypatch):
    calls = _counting(monkeypatch)
    service = RecordingService(db)
    service.COMPUTED_SECONDS = 0          # would expire at once, if it expired
    rid = db.create_recording("x")
    db.update_recording(rid, status=RecordingStatus.STOPPED, end_time=datetime.utcnow())

    for _ in range(3):
        service.get_draft(rid)

    assert calls == [rid]


def test_they_are_worked_out_again_when_the_recording_changes(db, monkeypatch):
    calls = _counting(monkeypatch)
    service = RecordingService(db)
    rid = db.create_recording("x")
    db.update_recording(rid, status=RecordingStatus.STOPPED, end_time=datetime.utcnow())
    service.get_draft(rid)

    # Moved by the clock-step repair, or resumed and stopped again: its end moves
    db.update_recording(rid, end_time=datetime.utcnow() + timedelta(minutes=5))
    service.get_draft(rid)

    assert calls == [rid, rid]


def test_while_recording_they_still_refresh(db, monkeypatch):
    calls = _counting(monkeypatch)
    service = RecordingService(db)
    service.COMPUTED_SECONDS = 0
    rid = db.create_recording("x")         # active

    service.get_draft(rid)
    service.get_draft(rid)

    assert calls == [rid, rid]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
