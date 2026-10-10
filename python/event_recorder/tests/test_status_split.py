"""TR-12: recording, artefact and post state kept apart.

Run in the dev container (dev/README.md):
    python -m pytest event_recorder/tests/test_status_split.py
"""

import sqlite3
from datetime import datetime

import pytest

from event_recorder.data_processor import DataProcessor
from event_recorder.models import (Artefacts, Database, ImageType, PostState,
                                   RecordingStatus, stage_of)
from event_recorder.recording_service import RecordingError, RecordingService
from event_recorder.recovery_manager import RecoveryManager
from event_recorder.web_interface import WebInterface

# The schema as TR-11 left it: one status for everything, post_drafts with no state
BEFORE_TR12 = """
CREATE TABLE recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, description TEXT,
    status TEXT NOT NULL CHECK(status IN ('active', 'stopped', 'processing', 'processed', 'published', 'failed')),
    start_time TIMESTAMP NOT NULL, end_time TIMESTAMP, trigger_type TEXT,
    wordpress_url TEXT, error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE recording_data (id INTEGER PRIMARY KEY AUTOINCREMENT, recording_id INTEGER NOT NULL,
    timestamp TIMESTAMP NOT NULL, topic TEXT NOT NULL, payload TEXT NOT NULL,
    FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE);
CREATE TABLE recording_images (id INTEGER PRIMARY KEY AUTOINCREMENT, recording_id INTEGER NOT NULL,
    image_path TEXT NOT NULL, image_type TEXT NOT NULL, caption TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE);
CREATE TABLE service_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO service_settings VALUES ('orphans_removed', 'done');
CREATE TABLE post_drafts (recording_id INTEGER PRIMARY KEY, wp_post_id INTEGER,
    wp_modified TEXT, wp_status TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE);
"""

# (name, old status, error_message) -> (status, artefacts, post_state, stage)
LEGACY = [
    ("recording now",  "active",     None,
     ("active", "none", "none", "active")),
    ("not processed",  "stopped",    None,
     ("stopped", "none", "none", "stopped")),
    ("interrupted",    "processing", None,
     ("stopped", "none", "none", "stopped")),
    ("processed",      "processed",  None,
     ("stopped", "fresh", "none", "processed")),
    ("published",      "published",  None,
     ("stopped", "fresh", "published", "published")),
    ("publish failed", "failed",     "WordPress publishing failed",
     ("stopped", "fresh", "publish_failed", "failed")),
    ("empty",          "failed",     "No data recorded before interruption",
     ("failed", "none", "none", "failed")),
    ("plots failed",   "failed",     None,
     ("stopped", "failed", "none", "failed")),
    ("recovery plots", "failed",     "Recovery processing failed: boom",
     ("stopped", "failed", "none", "failed")),
]


def _legacy_database(path):
    conn = sqlite3.connect(path)
    conn.executescript(BEFORE_TR12)
    for name, status, error, _ in LEGACY:
        conn.execute("INSERT INTO recordings (name, status, start_time, error_message) "
                     "VALUES (?, ?, '2026-09-01 02:00:00', ?)", (name, status, error))
    conn.commit()
    conn.close()


def _states(db):
    return {r["name"]: (r["status"], r["artefacts"], r["post_state"], r["stage"])
            for r in db.get_all_recordings()}


def test_every_old_status_lands_in_the_right_three_states(tmp_path):
    path = tmp_path / "legacy.db"
    _legacy_database(path)

    states = _states(Database(str(path)))

    for name, _, _, expected in LEGACY:
        assert states[name] == expected, name


def test_the_publish_error_moves_to_the_post(tmp_path):
    path = tmp_path / "legacy.db"
    _legacy_database(path)
    db = Database(str(path))
    rec = next(r for r in db.get_all_recordings() if r["name"] == "publish failed")
    assert rec["post_error"] == "WordPress publishing failed"


def test_a_published_recording_reset_to_processed_is_still_published(tmp_path):
    """The old way to republish, or add a photo, was to reset to processed first,
    so 'processed' with a link is a post that is out."""
    path = tmp_path / "legacy.db"
    _legacy_database(path)
    conn = sqlite3.connect(path)
    conn.execute("UPDATE recordings SET wordpress_url = 'https://enchantee.org/?p=8473' "
                 "WHERE name = 'processed'")
    conn.commit()
    conn.close()

    states = _states(Database(str(path)))

    assert states["processed"] == ("stopped", "fresh", "published", "published")


def test_a_post_id_stored_before_tr12_counts_as_published(tmp_path):
    path = tmp_path / "legacy.db"
    _legacy_database(path)
    conn = sqlite3.connect(path)
    for name, wp_status in (("processed", "publish"), ("not processed", "draft")):
        rid = conn.execute("SELECT id FROM recordings WHERE name = ?", (name,)).fetchone()[0]
        conn.execute("INSERT INTO post_drafts (recording_id, wp_post_id, wp_status) "
                     "VALUES (?, 21, ?)", (rid, wp_status))
    conn.commit()
    conn.close()

    states = _states(Database(str(path)))

    assert states["processed"][2] == "published"
    assert states["not processed"][2] == "wp_draft"


def test_the_migration_runs_once_and_then_leaves_things_alone(tmp_path):
    path = tmp_path / "legacy.db"
    _legacy_database(path)
    first = _states(Database(str(path)))
    assert _states(Database(str(path))) == first


@pytest.mark.parametrize("status, artefacts, post, stage", [
    ("active", "fresh", "published", "active"),
    ("failed", "none", "none", "failed"),
    ("stopped", "none", "publishing", "publishing"),
    ("stopped", "fresh", "wp_draft", "published"),
    ("stopped", "stale", "none", "processed"),
    ("stopped", "processing", "none", "processing"),
    ("stopped", "none", "none", "stopped"),
])
def test_stage_is_derived_from_the_three(status, artefacts, post, stage):
    assert stage_of({"status": status, "artefacts": artefacts, "post_state": post}) == stage


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "rec.db"))


@pytest.fixture
def service(db, tmp_path):
    return RecordingService(db, plots_dir=str(tmp_path / "plots"),
                            uploads_dir=str(tmp_path / "uploads"))


def _stopped(db, **fields):
    rid = db.create_recording("Sunday race")
    db.update_recording(rid, status=RecordingStatus.STOPPED, **fields)
    return rid


def test_processing_sets_the_artefacts_and_leaves_the_recording_alone(db, tmp_path):
    rid = _stopped(db)
    DataProcessor(db, str(tmp_path / "plots")).process_recording(rid)

    rec = db.get_recording(rid)
    assert (rec["status"], rec["artefacts"]) == ("stopped", "fresh")
    assert rec["processed_at"]


def test_a_processing_failure_is_the_artefacts_not_the_recording(db, tmp_path, monkeypatch):
    rid = _stopped(db)
    processor = DataProcessor(db, str(tmp_path / "plots"))
    monkeypatch.setattr(processor, "_auto_generate_plot_config",
                        lambda rid: (_ for _ in ()).throw(RuntimeError("no fonts")))

    processor.process_recording(rid)

    rec = db.get_recording(rid)
    assert (rec["status"], rec["artefacts"], rec["stage"]) == ("stopped", "failed", "failed")
    assert "no fonts" in rec["error_message"]


def test_stopping_a_recording_processed_while_running_marks_its_plots_stale(db, service):
    rid = service.start("x")
    db.update_recording(rid, artefacts=Artefacts.FRESH)

    service.stop(rid)

    assert db.get_recording(rid)["artefacts"] == Artefacts.STALE


def test_moving_a_recording_onto_a_corrected_clock_marks_its_plots_stale(db):
    rid = _stopped(db, artefacts=Artefacts.FRESH, end_time=datetime.utcnow())
    db.shift_recording_times(rid, 3600)
    assert db.get_recording(rid)["artefacts"] == Artefacts.STALE


class FailingWordPress:
    def test_connection(self):
        return True, "ok"

    def publish_recording(self, **kwargs):
        return None


def test_a_failed_publish_is_the_posts_state_and_can_be_cleared(db, tmp_path):
    rid = _stopped(db, artefacts=Artefacts.FRESH)
    plot = tmp_path / "speed.png"
    plot.write_bytes(b"png")
    db.add_image(rid, str(plot), ImageType.PLOT, "Speed")
    service = RecordingService(db, plots_dir=str(tmp_path / "plots"),
                               wordpress_publisher=FailingWordPress())

    with pytest.raises(RecordingError):
        service.publish(rid)

    rec = db.get_recording(rid)
    assert (rec["status"], rec["artefacts"], rec["post_state"]) == \
        ("stopped", "fresh", "publish_failed")
    assert rec["post_error"] == "WordPress publishing failed"

    assert service.reset_to_processed(rid) == "failed"
    assert db.get_recording(rid)["stage"] == "processed"


def test_reset_refuses_when_nothing_has_failed(db, service):
    rid = _stopped(db, artefacts=Artefacts.FRESH)
    db.set_post_state(rid, PostState.PUBLISHED)
    with pytest.raises(RecordingError) as refused:
        service.reset_to_processed(rid)
    assert refused.value.status == 400


def test_recovery_queues_only_recordings_never_processed(db):
    waiting = _stopped(db)
    _stopped(db, artefacts=Artefacts.FRESH)
    published = _stopped(db, artefacts=Artefacts.FRESH)
    db.set_post_state(published, PostState.PUBLISHED)
    interrupted = _stopped(db, artefacts=Artefacts.PROCESSING)

    actions = RecoveryManager(db).check_interrupted_recordings()

    assert sorted(actions["process"]) == sorted([waiting, interrupted])
    assert db.get_recording(interrupted)["artefacts"] == Artefacts.NONE


def test_recovery_turns_an_interrupted_publish_into_a_failed_one(db):
    rid = _stopped(db, artefacts=Artefacts.FRESH)
    db.set_post_state(rid, PostState.PUBLISHING)

    RecoveryManager(db).check_interrupted_recordings()

    rec = db.get_recording(rid)
    assert rec["post_state"] == PostState.PUBLISH_FAILED
    assert "interrupted" in rec["post_error"]


def test_recovery_summary_counts_by_stage(db):
    _stopped(db)
    _stopped(db, artefacts=Artefacts.FRESH)
    assert RecoveryManager(db).get_recovery_summary() == {"stopped": 1, "processed": 1}


def test_photos_are_refused_once_wordpress_has_the_post_and_not_before(db, service, tmp_path):
    client = WebInterface(database=db, plots_dir=str(tmp_path / "plots"),
                          uploads_dir=str(tmp_path / "uploads"),
                          recording_service=service).app.test_client()
    rid = _stopped(db, artefacts=Artefacts.FRESH)
    rename = lambda: client.put(f"/api/recordings/{rid}", json={"name": "Twilight"})

    db.set_post_state(rid, PostState.PUBLISH_FAILED, "hotspot")
    assert rename().status_code == 200

    db.set_post_state(rid, PostState.WP_DRAFT)
    assert rename().status_code == 409


def test_the_list_filters_by_stage(db, service, tmp_path):
    client = WebInterface(database=db, plots_dir=str(tmp_path / "plots"),
                          uploads_dir=str(tmp_path / "uploads"),
                          recording_service=service).app.test_client()
    processed = _stopped(db, artefacts=Artefacts.FRESH)
    _stopped(db)
    active = service.start("now")

    def ids(stage):
        body = client.get(f"/api/recordings?status={stage}").get_json()
        return [r["id"] for r in body["recordings"]]

    assert ids("processed") == [processed]
    assert ids("active") == [active]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
