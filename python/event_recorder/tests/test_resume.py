"""Recordings survive a restart or a power cut, and carry on.

Run in the dev container (dev/README.md):
    python -m pytest event_recorder/tests/test_resume.py

Before this, a clean shutdown ended every recording in progress and recovery ended any a
power cut left active. The anchor trigger will not start another away from the mooring,
so a restart mid-sail, an edit on the jetty or a container update, lost the rest of the
sail.
"""

import json
import time
from datetime import datetime, timedelta

import pytest

from event_recorder.main import EventRecorderService
from event_recorder.models import Database, RecordingStatus
from event_recorder.recording_service import RecordingService
from event_recorder.recovery_manager import RecoveryManager
from event_recorder.trigger_monitor import GPSTriggerMonitor, TriggerState

MOORING = (-32.001378, 115.809363)
ANCHOR_EVENT = {
    "monitor_topics": ["gps/position/0"],
    "start_condition": {"type": "anchor_departure", "anchor_lat": MOORING[0],
                        "anchor_lon": MOORING[1], "radius": 50, "duration": 5},
    "stop_condition": {"type": "anchor_return", "anchor_lat": MOORING[0],
                       "anchor_lon": MOORING[1], "radius": 50, "duration": 15},
    "record_topics": ["gps/#", "anemometer/#", "race/#"],
}


class FakeRecorder:
    def __init__(self):
        self.recording, self.stopped = {}, []

    def start_recording(self, recording_id, topics, initial_count=0):
        self.recording[recording_id] = topics

    def stop_recording(self, recording_id):
        self.stopped.append(recording_id)
        self.recording.pop(recording_id, None)

    def get_active_recordings(self):
        return list(self.recording)


class FakeTriggers:
    def __init__(self, monitors):
        self.monitors, self.resumed = set(monitors), {}

    def resume_monitor(self, monitor_id, recording_id):
        if monitor_id not in self.monitors:
            return False
        self.resumed[monitor_id] = recording_id
        return True


class FakeConfig:
    def __init__(self, events):
        self.events = events

    def get_enabled_event_configs(self):
        return self.events


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "rec.db"))


@pytest.fixture
def recorder():
    return FakeRecorder()


@pytest.fixture
def service(db, recorder):
    return RecordingService(db, data_recorder=recorder)


def _active(db, key, hours_ago, data_hours_ago=None, topics=None):
    rid = db.create_recording(f"{key} - x", event_key=key, record_topics=topics)
    db.update_recording(rid, start_time=datetime.utcnow() - timedelta(hours=hours_ago))
    if data_hours_ago is not None:
        db.add_messages_batch([(rid, datetime.utcnow() - timedelta(hours=data_hours_ago),
                                "gps/speed/0", "4.2")])
    return rid


def _main(db, service, events, monitors):
    main = EventRecorderService.__new__(EventRecorderService)
    main.database, main.recordings = db, service
    main.config = FakeConfig(events)
    main.trigger_monitor = FakeTriggers(monitors)
    main.active_recordings = {}
    return main


# === Shutdown ===

def test_a_shutdown_saves_the_buffer_and_leaves_recordings_active(db, service, recorder):
    rid = service.start("anchor_track_recording - x", topics=["gps/#"],
                        event_key="anchor_track_recording")

    service.suspend_all()

    assert recorder.stopped == [rid], "the buffer is flushed"
    rec = db.get_recording(rid)
    assert rec["status"] == RecordingStatus.ACTIVE and rec["end_time"] is None


def test_the_service_suspends_rather_than_stops_on_shutdown(db, service, recorder):
    main = _main(db, service, {}, [])
    main.running = True
    main._status_mqtt_client = None
    main.data_recorder = type("R", (), {"shutdown": lambda self: None})()
    main.trigger_monitor = type("T", (), {"shutdown": lambda self: None})()
    rid = service.start("x", topics=["gps/#"])

    main.stop()

    assert db.get_recording(rid)["status"] == RecordingStatus.ACTIVE


def test_recordings_store_what_they_record(db, service):
    rid = service.start("x", topics=["gps/#", "race/#"])
    assert json.loads(db.get_recording(rid)["record_topics"]) == ["gps/#", "race/#"]


# === Recovery's decision ===

def test_a_recording_interrupted_mid_sail_is_to_be_resumed(db):
    rid = _active(db, "anchor_track_recording", hours_ago=2, data_hours_ago=0.01)
    actions = RecoveryManager(db).check_interrupted_recordings()
    assert actions["resume"] == [rid]
    assert db.get_recording(rid)["status"] == RecordingStatus.ACTIVE


def test_one_interrupted_before_any_data_arrived_is_resumed_too(db):
    rid = _active(db, "anchor_track_recording", hours_ago=0.01)
    assert RecoveryManager(db).check_interrupted_recordings()["resume"] == [rid]


def test_one_silent_for_hours_is_ended_where_its_data_ends(db):
    rid = _active(db, "anchor_track_recording", hours_ago=30, data_hours_ago=20)
    last = db.last_data_time(rid)

    actions = RecoveryManager(db).check_interrupted_recordings()

    assert rid in actions["process"] and rid not in actions["resume"]
    rec = db.get_recording(rid)
    assert rec["status"] == RecordingStatus.STOPPED
    # Not now: the hours the Pi was off are not part of the sail
    assert datetime.fromisoformat(str(rec["end_time"])) == last


def test_one_that_never_recorded_anything_long_ago_has_failed(db):
    rid = _active(db, "anchor_track_recording", hours_ago=30)
    assert RecoveryManager(db).check_interrupted_recordings()["failed"] == [rid]


# === Resuming on start ===

def test_a_triggered_recording_resumes_with_its_topics_and_its_trigger(db, service, recorder):
    rid = _active(db, "anchor_track_recording", 1, 0.01, topics=["gps/#", "race/#"])
    main = _main(db, service, {"anchor_track_recording": ANCHOR_EVENT}, ["anchor_track_recording"])
    main._to_resume = [rid]

    main._resume_recordings()

    assert recorder.recording[rid] == ["gps/#", "race/#"]
    assert main.trigger_monitor.resumed == {"anchor_track_recording": rid}
    assert main.active_recordings == {"anchor_track_recording": rid}


def test_one_from_before_topics_were_stored_takes_them_from_its_event(db, service, recorder):
    rid = _active(db, "anchor_track_recording", 1, 0.01)
    main = _main(db, service, {"anchor_track_recording": ANCHOR_EVENT}, ["anchor_track_recording"])
    main._to_resume = [rid]

    main._resume_recordings()

    assert recorder.recording[rid] == ANCHOR_EVENT["record_topics"]


def test_a_manual_recording_resumes_without_a_trigger(db, service, recorder):
    rid = _active(db, "manual", 1, 0.01, topics=["gps/#"])
    main = _main(db, service, {}, [])
    main._to_resume = [rid]

    main._resume_recordings()

    assert recorder.recording[rid] == ["gps/#"]
    assert main.active_recordings == {}


def test_one_whose_event_has_gone_from_the_config_is_ended_not_left_running(db, service, recorder):
    rid = _active(db, "old_event", 1, 0.01, topics=["gps/#"])
    main = _main(db, service, {}, [])
    main._to_resume = [rid]

    main._resume_recordings()

    assert rid not in recorder.recording
    assert db.get_recording(rid)["status"] == RecordingStatus.STOPPED


def test_two_of_one_event_cannot_both_carry_on(db, service, recorder):
    earlier = _active(db, "anchor_track_recording", 3, 0.02, topics=["gps/#"])
    later = _active(db, "anchor_track_recording", 1, 0.01, topics=["gps/#"])
    main = _main(db, service, {"anchor_track_recording": ANCHOR_EVENT}, ["anchor_track_recording"])
    main._to_resume = [earlier, later]

    main._resume_recordings()

    assert db.get_recording(earlier)["status"] == RecordingStatus.STOPPED
    assert main.active_recordings == {"anchor_track_recording": later}


# === And the real trigger then ends it as it would have ===

def test_a_resumed_anchor_recording_stops_when_the_boat_is_back_on_the_mooring():
    stopped = []
    monitor = GPSTriggerMonitor()
    monitor.add_monitor("anchor_track_recording", ANCHOR_EVENT,
                        on_start=lambda *a: pytest.fail("must not start another"),
                        on_stop=lambda key, rid: stopped.append(rid))

    assert monitor.resume_monitor("anchor_track_recording", 42)
    assert monitor.monitor_states["anchor_track_recording"]["state"] == TriggerState.TRIGGERED

    # Out on the river: nothing happens
    t = datetime(2026, 10, 9, 9, 0, 0)
    for i in range(3):
        monitor.current_position = (-32.0100, 115.7800, t + timedelta(seconds=i * 10))
        monitor._check_triggers()
    assert stopped == []

    # Back on the mooring for longer than the stop condition's 15 s
    for i in range(4):
        monitor.current_position = (MOORING[0], MOORING[1], t + timedelta(minutes=30, seconds=i * 10))
        monitor._check_triggers()
    assert stopped == [42]


def test_resuming_a_monitor_that_does_not_exist_says_so():
    assert GPSTriggerMonitor().resume_monitor("renamed_event", 42) is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
