"""TR-9: foreign keys enforced, and deleting a recording removes all of it.

Run in the dev container (dev/README.md):
    python -m pytest event_recorder/tests/test_foreign_keys.py
"""

import sqlite3
from datetime import datetime

import pytest

from event_recorder.models import Database, ImageType
from event_recorder.web_interface import WebInterface


# The recordings table as it was before 'processed' was added, which is what
# sends an existing database through the table-recreating migration.
OLD_SCHEMA = """
CREATE TABLE recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, description TEXT,
    status TEXT NOT NULL CHECK(status IN ('active','stopped','processing','published','failed')),
    start_time TIMESTAMP NOT NULL, end_time TIMESTAMP, trigger_type TEXT,
    wordpress_url TEXT, error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE recording_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT, recording_id INTEGER NOT NULL,
    timestamp TIMESTAMP NOT NULL, topic TEXT NOT NULL, payload TEXT NOT NULL,
    FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE);
CREATE TABLE recording_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT, recording_id INTEGER NOT NULL,
    image_path TEXT NOT NULL, image_type TEXT NOT NULL, caption TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE);
INSERT INTO recordings (name, status, start_time) VALUES ('kept', 'stopped', '2026-01-01');
INSERT INTO recording_data (recording_id, timestamp, topic, payload)
    VALUES (1, '2026-01-01', 'gps/speed/0', '4.2');
"""


def _old_database(path):
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.commit()
    conn.close()


def _damaged_database(path):
    """An old database put through the migration as it was written before
    TR-9: the rename rewrites the children to recordings_old, then the drop
    leaves them pointing at nothing."""
    _old_database(path)
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE recordings RENAME TO recordings_old")
    conn.execute("""
        CREATE TABLE recordings (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, description TEXT,
            status TEXT NOT NULL CHECK(status IN ('active','stopped','processing','processed','published','failed')),
            start_time TIMESTAMP NOT NULL, end_time TIMESTAMP, trigger_type TEXT,
            wordpress_url TEXT, error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
    """)
    conn.execute("INSERT INTO recordings SELECT * FROM recordings_old")
    conn.execute("DROP TABLE recordings_old")
    conn.commit()
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='recording_data'").fetchone()[0]
    conn.close()
    assert 'recordings_old' in sql, "fixture should reproduce the damage"


def _references(path):
    conn = sqlite3.connect(path)
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' AND sql LIKE '%REFERENCES%'"
    ).fetchall()
    conn.close()
    return {name: sql for name, sql in rows}


def _count(path, table, recording_id=None):
    conn = sqlite3.connect(path)
    if recording_id is None:
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    else:
        n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE recording_id = ?",
                         (recording_id,)).fetchone()[0]
    conn.close()
    return n


def _recording_with_children(db, tmp_path):
    rec = db.create_recording("Sunday race")
    db.add_messages_batch([(rec, datetime.utcnow(), "gps/speed/0", "5.1")] * 3)
    db.add_image(rec, str(tmp_path / "photo.jpg"), ImageType.USER_UPLOAD, "kite up")
    db.add_export(rec, "gpx", str(tmp_path / f"track_{rec}.gpx"), "Track")
    return rec


def test_deleting_a_recording_removes_its_data_images_and_exports(tmp_path):
    path = tmp_path / "rec.db"
    db = Database(str(path))
    gone = _recording_with_children(db, tmp_path)
    kept = _recording_with_children(db, tmp_path)

    db.delete_recording(gone)

    for table in ("recording_data", "recording_images", "recording_exports"):
        assert _count(path, table, gone) == 0, table
        assert _count(path, table, kept) > 0, table


def test_old_database_migrates_without_losing_data_or_pointing_children_at_nothing(tmp_path):
    path = tmp_path / "old.db"
    _old_database(path)

    db = Database(str(path))

    assert _count(path, "recording_data") == 1
    for name, sql in _references(path).items():
        assert "recordings_old" not in sql, name
    db.add_messages_batch([(1, datetime.utcnow(), "gps/speed/0", "4.3")])
    assert _count(path, "recording_data") == 2


def test_database_already_damaged_by_the_old_migration_is_repaired(tmp_path):
    path = tmp_path / "damaged.db"
    _damaged_database(path)

    db = Database(str(path))

    for name, sql in _references(path).items():
        assert "recordings_old" not in sql, name
    assert _count(path, "recording_data") == 1
    db.add_messages_batch([(1, datetime.utcnow(), "gps/speed/0", "4.3")])
    assert _count(path, "recording_data") == 2
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_orphans_from_earlier_deletes_are_removed_once(tmp_path):
    path = tmp_path / "orphans.db"
    _old_database(path)
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO recording_data (recording_id, timestamp, topic, payload) "
                 "VALUES (99, '2026-01-01', 'gps/speed/0', '1')")
    conn.commit()
    conn.close()

    Database(str(path))
    assert _count(path, "recording_data", 99) == 0
    assert _count(path, "recording_data", 1) == 1

    # Only once: a later start does not scan recording_data again
    conn = sqlite3.connect(path)
    assert conn.execute(
        "SELECT COUNT(*) FROM service_settings WHERE key='orphans_removed'").fetchone()[0] == 1
    conn.close()


def test_buffered_rows_for_a_deleted_recording_do_not_block_the_rest(tmp_path):
    path = tmp_path / "buffer.db"
    db = Database(str(path))
    live = db.create_recording("live")
    gone = db.create_recording("gone")
    db.delete_recording(gone)

    now = datetime.utcnow()
    db.add_messages_batch([(live, now, "a", "1"), (gone, now, "a", "2"), (live, now, "b", "3")])

    assert _count(path, "recording_data", live) == 2
    assert _count(path, "recording_data", gone) == 0


def test_delete_route_removes_the_crews_photos_as_well_as_the_plots(tmp_path):
    db = Database(str(tmp_path / "web.db"))
    rec = _recording_with_children(db, tmp_path)
    db.update_recording(rec, status="stopped")
    plots = tmp_path / "plots" / str(rec)
    uploads = tmp_path / "uploads" / str(rec)
    for d in (plots, uploads):
        d.mkdir(parents=True)
        (d / "file.png").write_bytes(b"x")

    web = WebInterface(database=db, plots_dir=str(tmp_path / "plots"),
                       uploads_dir=str(tmp_path / "uploads"))
    response = web.app.test_client().delete(f"/api/recordings/{rec}")

    assert response.status_code == 200, response.get_json()
    assert not plots.exists()
    assert not uploads.exists()
    assert db.get_recording(rec) is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
