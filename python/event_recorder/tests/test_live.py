"""FR-31: live while recording.

Run in the dev container (dev/README.md):
    python -m pytest event_recorder/tests/test_live.py
"""

import json
from datetime import datetime, timedelta

import pytest

from event_recorder import live_summary
from event_recorder.data_recorder import DataRecorder
from event_recorder.live_summary import LiveSummaries
from event_recorder.main import EventRecorderService
from event_recorder.models import Database, RecordingStatus
from event_recorder.recording_service import RecordingService

START = datetime(2026, 9, 13, 5, 30)
# A nautical mile is a minute of latitude
MILE_NORTH = 1 / 60


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "rec.db"))


@pytest.fixture(autouse=True)
def always_refresh(monkeypatch):
    """No waiting out the ten-second refresh in a test."""
    monkeypatch.setattr(live_summary, "REFRESH_SECONDS", 0)


def _fixes(db, rid, points, start=START, every=timedelta(seconds=10)):
    db.add_messages_batch([(rid, start + i * every, "gps/position/0",
                            json.dumps({"lat": lat, "lon": lon, "ts": 0}))
                           for i, (lat, lon) in enumerate(points)])


def _north(steps, lat=-32.0, lon=115.8, per_step=MILE_NORTH / 30):
    return [(lat + i * per_step, lon) for i in range(steps + 1)]


def test_a_mile_sailed_is_a_mile(db):
    rid = db.create_recording("x")
    _fixes(db, rid, _north(30))          # a mile in 300 s: 12 knots
    assert LiveSummaries(db).summary(rid)["distance_nm"] == pytest.approx(1.0, abs=0.01)


def test_a_gps_jump_is_not_distance_sailed(db):
    rid = db.create_recording("x")
    points = _north(30)
    points.insert(15, (points[15][0] + 0.5, points[15][1]))     # 30 miles away and back
    _fixes(db, rid, points)
    assert LiveSummaries(db).summary(rid)["distance_nm"] == pytest.approx(1.0, abs=0.05)


def test_each_refresh_reads_only_what_arrived_since(db, monkeypatch):
    rid = db.create_recording("x")
    _fixes(db, rid, _north(30))
    live = LiveSummaries(db)
    assert live.summary(rid)["distance_nm"] == pytest.approx(1.0, abs=0.01)

    asked = []
    real = db.positions_since
    monkeypatch.setattr(db, "positions_since",
                        lambda *a: asked.append(a[2]) or real(*a))
    _fixes(db, rid, _north(30, lat=-32.0 + MILE_NORTH)[1:], start=START + timedelta(seconds=310))

    assert live.summary(rid)["distance_nm"] == pytest.approx(2.0, abs=0.02)
    assert asked == [START + timedelta(seconds=300)], "only after the last fix it had"


def test_the_track_is_thinned_but_keeps_its_ends(db):
    rid = db.create_recording("x")
    points = _north(300, per_step=MILE_NORTH / 300)          # a fix every 6 m
    _fixes(db, rid, points, every=timedelta(seconds=1))
    track = LiveSummaries(db).summary(rid)["track"]

    # Fixes 6.2 m apart, kept once 20 m on: every fourth, about 76 of 301
    assert 70 < len(track) < 85
    assert track[0] == [round(points[0][0], 6), round(points[0][1], 6)]
    # ...and always the boat's last position, where the page puts its "now" dot
    assert track[-1] == [round(points[-1][0], 6), round(points[-1][1], 6)]


def test_the_top_speed_is_the_highest_reported(db):
    rid = db.create_recording("x")
    db.add_messages_batch([(rid, START + timedelta(seconds=i), "gps/speed/0", str(v))
                           for i, v in enumerate([3.2, 6.94, 5.1])])
    _fixes(db, rid, _north(2))
    assert LiveSummaries(db).summary(rid)["max_sog"] == 6.9


# === The recorder counts as it goes ===

class Message:
    def __init__(self, topic, payload):
        self.topic, self.payload = topic, payload.encode()


def test_messages_are_counted_as_they_arrive_from_where_a_resume_left_off(db):
    recorder = DataRecorder(db)
    rid = db.create_recording("x")
    recorder.start_recording(rid, ["gps/#"], initial_count=1000)

    for topic in ("gps/speed/0", "gps/speed/0", "anemometer/windSpeed/2"):
        recorder._on_message(None, None, Message(topic, "4.2"))

    assert recorder.message_count(rid) == 1002
    assert recorder.message_count(999) is None


def test_the_status_no_longer_counts_the_recordings_rows(db, monkeypatch):
    sent = []
    service = RecordingService(db, data_recorder=DataRecorder(db))
    rid = service.start("x", topics=["gps/#"])
    main = EventRecorderService.__new__(EventRecorderService)
    main.database, main.recordings, main.data_recorder = db, service, service.data_recorder
    main._status_mqtt_client = type("C", (), {"publish": lambda self, t, p, **k: sent.append(json.loads(p))})()

    def no(recording_id):
        raise AssertionError("COUNT(*) over recording_data, once a second")
    monkeypatch.setattr(db, "get_recording_data_count", no)

    main._publish_recording_status(rid)

    assert sent and sent[0]["message_count"] == 0
    assert "distance_nm" in sent[0] and "max_sog" in sent[0]


# === On the page and in the preview ===

def test_the_page_shows_the_live_summary(db, tmp_path):
    service = RecordingService(db, plots_dir=str(tmp_path / "plots"))
    rid = service.start("x", topics=["gps/#"])
    _fixes(db, rid, _north(30))

    live = service.page_state(rid, lambda p: p)["live"]

    assert live["distance_nm"] == pytest.approx(1.0, abs=0.01) and len(live["track"]) > 2


def test_before_processing_the_preview_has_the_live_numbers(db, tmp_path):
    service = RecordingService(db, plots_dir=str(tmp_path / "plots"))
    rid = service.start("x", topics=["gps/#"])
    _fixes(db, rid, _north(30))
    db.add_messages_batch([(rid, START, "gps/speed/0", "6.2")])

    preview = service.preview(rid, lambda p: p, layout="ship_log")

    assert "1.00 nm" in preview and "6.20 knots" in preview


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
