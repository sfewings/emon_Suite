"""FR-28: which recording the event page opens.

Run in the dev container (dev/README.md):
    python -m pytest event_recorder/tests/test_editor_choice.py
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

from event_recorder.models import Database, PostState, RecordingStatus
from event_recorder.recording_service import RecordingService

EVENTS = {
    "track_recording": {"enabled": True},
    "anchor_track_recording": {"enabled": True, "editor_default": True},
}


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "rec.db"))


@pytest.fixture
def service(db):
    return RecordingService(db, event_configs=lambda: EVENTS)


def _recording(db, key, hours_ago=0, status=RecordingStatus.ACTIVE):
    rid = db.create_recording(f"{key} - 2026-10-09 10:00:00", event_key=key)
    db.update_recording(rid, status=status,
                        start_time=datetime.utcnow() - timedelta(hours=hours_ago))
    return rid


def _chosen(service):
    choice = service.editor_choice()
    return (choice["recording"] or {}).get("id"), [r["id"] for r in choice["candidates"]]


def test_of_two_recordings_running_the_anchor_one_is_opened(db, service):
    anchor = _recording(db, "anchor_track_recording", hours_ago=1)
    track = _recording(db, "track_recording", hours_ago=0.5)    # started later

    chosen, candidates = _chosen(service)

    assert chosen == anchor
    assert candidates == [anchor, track]


def test_without_an_anchor_recording_the_most_recent_active_one_is_opened(db, service):
    _recording(db, "manual", hours_ago=2)
    newest = _recording(db, "track_recording", hours_ago=1)
    assert _chosen(service)[0] == newest


def test_an_active_recording_wins_over_any_stopped_one(db, service):
    _recording(db, "anchor_track_recording", status=RecordingStatus.STOPPED)
    track = _recording(db, "track_recording", hours_ago=3)
    assert _chosen(service) == (track, [track])


def test_after_the_sail_the_outings_anchor_recording_is_opened(db, service):
    anchor = _recording(db, "anchor_track_recording", hours_ago=3, status=RecordingStatus.STOPPED)
    track = _recording(db, "track_recording", hours_ago=2, status=RecordingStatus.STOPPED)

    assert _chosen(service) == (anchor, [anchor, track])


def test_a_week_old_anchor_recording_does_not_displace_todays_sail(db, service):
    _recording(db, "anchor_track_recording", hours_ago=24 * 7, status=RecordingStatus.STOPPED)
    today = _recording(db, "track_recording", hours_ago=2, status=RecordingStatus.STOPPED)

    assert _chosen(service) == (today, [today])


def test_published_and_failed_recordings_are_not_opened(db, service):
    published = _recording(db, "anchor_track_recording", hours_ago=1, status=RecordingStatus.STOPPED)
    db.set_post_state(published, PostState.PUBLISHED)
    _recording(db, "anchor_track_recording", hours_ago=0.5, status=RecordingStatus.FAILED)
    waiting = _recording(db, "track_recording", hours_ago=2, status=RecordingStatus.STOPPED)

    assert _chosen(service)[0] == waiting


def test_with_nothing_to_open_there_is_nothing(service):
    assert _chosen(service) == (None, [])


def test_with_no_event_config_the_most_recent_is_opened(db):
    service = RecordingService(db)
    _recording(db, "anchor_track_recording", hours_ago=2)
    newest = _recording(db, "track_recording", hours_ago=1)
    assert _chosen(service)[0] == newest


def test_a_manual_recording_is_keyed_manual(service, db):
    rid = service.start("Twilight")
    assert db.get_recording(rid)["event_key"] == "manual"


def test_older_recordings_get_their_event_key_from_their_name(tmp_path):
    """Before FR-28 the key was only in the name, and only until it is edited."""
    path = tmp_path / "old.db"
    Database(str(path))
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE recordings DROP COLUMN event_key")
    rows = [("anchor_track_recording - 2026-10-07 18:03:28", "anchor_departure"),
            ("Manual test", "manual"),
            ("Terra15 software team Crew", "anchor_departure")]
    for name, trigger in rows:
        conn.execute("INSERT INTO recordings (name, status, start_time, trigger_type) "
                     "VALUES (?, 'stopped', '2026-10-07', ?)", (name, trigger))
    conn.commit()
    conn.close()

    db = Database(str(path))

    keys = {r["name"]: r["event_key"] for r in db.get_all_recordings()}
    assert keys == {
        "anchor_track_recording - 2026-10-07 18:03:28": "anchor_track_recording",
        "Manual test": "manual",
        # Already retitled: no way to tell, so left unknown rather than guessed
        "Terra15 software team Crew": None,
    }


def test_the_boats_event_config_marks_the_anchor_event_and_only_that():
    # In the checkout, or where the dev rig mounts it in the container
    places = [Path(__file__).resolve().parents[3] / "provisioning" / "enchantee" / "config" / "events",
              Path("/config/events")]
    events_dir = next((p for p in places if p.exists()), None)
    if events_dir is None:
        pytest.skip("the boat's event config is not reachable from here")
    latest = sorted(events_dir.glob("*.yml"))[-1]
    events = yaml.safe_load(latest.read_text(encoding="utf-8"))["events"]

    marked = [key for key, config in events.items() if config.get("editor_default")]
    assert marked == ["anchor_track_recording"]
    assert "race/#" in events["anchor_track_recording"]["record_topics"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
