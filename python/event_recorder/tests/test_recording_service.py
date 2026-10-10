"""TR-10: one recording service behind the triggers and the routes.

Run in the dev container (dev/README.md):
    python -m pytest event_recorder/tests/test_recording_service.py
"""

import time

import pytest

from event_recorder.main import EventRecorderService
from event_recorder.models import Database, RecordingStatus
from event_recorder.recording_service import RecordingError, RecordingService
from event_recorder.web_interface import WebInterface


class FakeRecorder:
    """DataRecorder without MQTT: remembers what it was told to record."""

    def __init__(self):
        self.recording = {}

    def start_recording(self, recording_id, topics):
        self.recording[recording_id] = topics

    def stop_recording(self, recording_id):
        self.recording.pop(recording_id, None)

    def get_active_recordings(self):
        return list(self.recording)

    def get_buffer_status(self):
        return {'connected': True, 'buffer_size': 0}


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "rec.db"))


@pytest.fixture
def recorder():
    return FakeRecorder()


@pytest.fixture
def service(db, recorder, tmp_path):
    return RecordingService(db, data_recorder=recorder,
                            plots_dir=str(tmp_path / "plots"),
                            uploads_dir=str(tmp_path / "uploads"))


@pytest.fixture
def client(db, service, tmp_path):
    web = WebInterface(database=db, plots_dir=str(tmp_path / "plots"),
                       uploads_dir=str(tmp_path / "uploads"),
                       recording_service=service)
    return web.app.test_client()


def _service_with_triggers(service, db):
    """The parts of EventRecorderService the trigger and clock code use,
    without its config file, MQTT connections or web thread."""
    main = EventRecorderService.__new__(EventRecorderService)
    main.recordings = service
    main.database = db
    main.active_recordings = {}
    main._clock_reference = (time.time(), time.monotonic())
    return main


def test_a_recording_started_from_the_web_ui_is_recorded_and_counted_as_this_runs(
        client, service, recorder):
    response = client.post("/api/recordings", json={"name": "Twilight", "topics": ["gps/#"]})
    rid = response.get_json()["recording_id"]

    assert recorder.recording[rid] == ["gps/#"]
    # Before TR-10 only triggered recordings reached this set, so the
    # clock-step repair never moved a manual one
    assert rid in service.recordings_this_run


def test_a_manual_recording_is_labelled_manual_not_gps_movement(client, db):
    rid = client.post("/api/recordings", json={"name": "x"}).get_json()["recording_id"]
    assert db.get_recording(rid)["trigger_type"] == "manual"


def test_stopping_from_the_web_ui_ends_the_recording(client, db, recorder, service):
    rid = service.start("Sunday race", topics=["gps/#"])

    response = client.post(f"/api/recordings/{rid}/stop")

    assert response.status_code == 200
    assert response.get_json()["auto_processing"] is False
    assert rid not in recorder.recording
    rec = db.get_recording(rid)
    assert rec["status"] == RecordingStatus.STOPPED and rec["end_time"]


def test_stop_starts_auto_processing_when_the_setting_is_on(db, service, monkeypatch):
    processed = []
    monkeypatch.setattr(service, "process", lambda rid, *a, **k: processed.append(rid))
    db.set_setting("auto_process_on_stop", "true")
    rid = service.start("x")

    assert service.stop(rid) is True
    for _ in range(50):
        if processed:
            break
        time.sleep(0.02)
    assert processed == [rid]


def test_stopping_a_recording_that_is_not_active_is_refused(client, service):
    rid = service.start("x")
    service.stop(rid)

    response = client.post(f"/api/recordings/{rid}/stop")

    assert response.status_code == 400
    assert "not active" in response.get_json()["error"]


def test_the_trigger_leaves_alone_a_recording_the_crew_already_stopped(db, service):
    main = _service_with_triggers(service, db)
    rid = service.start("anchor_track_recording - today")
    main.active_recordings["anchor_track_recording"] = rid
    service.stop(rid)
    stopped_at = db.get_recording(rid)["end_time"]

    main._on_trigger_stop("anchor_track_recording", rid)

    assert db.get_recording(rid)["end_time"] == stopped_at
    assert main.active_recordings == {}


def test_a_trigger_start_goes_through_the_service(db, service, recorder):
    main = _service_with_triggers(service, db)

    rid = main._on_trigger_start(
        "anchor_track_recording",
        {"description": "Left the mooring", "record_topics": ["gps/#", "race/#"],
         "start_condition": {"type": "anchor_departure"}},
        "anchor_track_recording")

    assert recorder.recording[rid] == ["gps/#", "race/#"]
    assert rid in service.recordings_this_run
    assert main.active_recordings == {"anchor_track_recording": rid}
    assert db.get_recording(rid)["trigger_type"] == "anchor_departure"


def test_the_clock_step_repair_moves_manual_recordings_too(db, service, monkeypatch):
    main = _service_with_triggers(service, db)
    manual = service.start("manual")
    moved = []
    monkeypatch.setattr(db, "shift_recording_times",
                        lambda rid, step: moved.append(rid) or 0)
    # The wall clock seen to jump a day ahead of the monotonic one
    main._clock_reference = (time.time() - 86400, time.monotonic())

    main._check_for_clock_step()

    assert moved == [manual]


def test_shutdown_ends_manual_recordings_as_well_as_triggered_ones(db, service, recorder):
    main = _service_with_triggers(service, db)
    manual = service.start("manual")
    triggered = main._on_trigger_start(
        "track_recording", {"record_topics": ["gps/#"]}, "track_recording")

    service.stop_all()

    for rid in (manual, triggered):
        assert db.get_recording(rid)["status"] == RecordingStatus.STOPPED, rid
    assert recorder.recording == {}


def test_status_counts_manual_recordings(client, service):
    service.start("manual")
    status = client.get("/api/status").get_json()["status"]
    assert status["active_recordings"] == 1


@pytest.mark.parametrize("call, status", [
    (lambda s, rid: s.publish(rid), 400),        # no WordPress configured
    (lambda s, rid: s.publish(9999), 400),       # refused for that before lookup
    (lambda s, rid: s.delete(9999), 404),
    (lambda s, rid: s.delete(rid), 400),         # still active
    (lambda s, rid: s.reset_to_processed(rid), 400),
])
def test_refusals_carry_the_status_a_route_should_return(service, call, status):
    rid = service.start("x")
    with pytest.raises(RecordingError) as refused:
        call(service, rid)
    assert refused.value.status == status


def test_routes_return_the_services_status_for_a_refusal(client, service):
    rid = service.start("x")
    assert client.delete(f"/api/recordings/{rid}").status_code == 400
    assert client.delete("/api/recordings/9999").status_code == 404
    assert client.post(f"/api/recordings/{rid}/publish").status_code == 400


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
