"""FR-26: the time and wind lines worked out from the recording, and nautical miles.

Run in the dev container (dev/README.md):
    python -m pytest event_recorder/tests/test_log_lines.py
"""

import time
from datetime import datetime, timedelta

import pytest

from event_recorder import post_renderer
from event_recorder.models import Database, RecordingStatus
from event_recorder.post_renderer import LAYOUT_SHIP_LOG, PostContext, render
from event_recorder.post_suggestions import (WIND_DIRECTION_TOPIC, WIND_SPEED_TOPIC,
                                             wind_line)
from event_recorder.recording_service import RecordingService


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "rec.db"))


def _recording(db):
    rid = db.create_recording("x", event_key="anchor_track_recording")
    db.update_recording(rid, status=RecordingStatus.STOPPED,
                        start_time="2026-09-13 05:04:00", end_time="2026-09-13 07:53:00")
    return rid


def _wind(db, rid, directions, speeds, every=timedelta(seconds=15)):
    start = datetime(2026, 9, 13, 5, 30)
    db.add_messages_batch(
        [(rid, start + i * every, WIND_DIRECTION_TOPIC, str(d)) for i, d in enumerate(directions)] +
        [(rid, start + i * every, WIND_SPEED_TOPIC, str(s)) for i, s in enumerate(speeds)])


# === The wind line ===

def test_a_steady_sea_breeze(db):
    rid = _recording(db)
    _wind(db, rid, [245 + (i % 9) for i in range(200)], [8 + (i % 6) for i in range(200)])
    assert wind_line(db, rid) == "WSW 8-13 kts"


def test_a_northerly_either_side_of_north_is_north_not_south(db):
    """An arithmetic mean of 350 and 10 is 180. The circular mean is 0."""
    rid = _recording(db)
    _wind(db, rid, [350, 10] * 100, [12] * 200)
    assert wind_line(db, rid) == "N 12 kts"


def test_a_gust_and_a_lull_do_not_set_the_range(db):
    rid = _recording(db)
    _wind(db, rid, [270] * 200, [2] + [12, 13, 14] * 66 + [30])
    assert wind_line(db, rid) == "W 12-14 kts"


def test_a_wind_from_everywhere_is_left_blank_not_guessed(db):
    rid = _recording(db)
    _wind(db, rid, [i * 37 % 360 for i in range(200)], [6] * 200)
    assert wind_line(db, rid) == ""


def test_too_little_wind_data_is_left_blank(db):
    rid = _recording(db)
    _wind(db, rid, [270] * 30, [10] * 30)                       # too few
    assert wind_line(db, rid) == ""

    rid = _recording(db)
    _wind(db, rid, [270] * 200, [10] * 200, every=timedelta(seconds=2))   # under 10 minutes
    assert wind_line(db, rid) == ""


@pytest.mark.parametrize("bearing, name", [(0, "N"), (11, "N"), (12, "NNE"), (247, "WSW"),
                                           (277, "W"), (349, "N"), (348, "NNW")])
def test_the_sixteen_points(db, bearing, name):
    rid = _recording(db)
    _wind(db, rid, [bearing] * 100, [10] * 100)
    assert wind_line(db, rid).split()[0] == name


# === In the draft and the post ===

def test_the_draft_carries_the_recordings_lines(db):
    rid = _recording(db)
    _wind(db, rid, [270] * 100, [10] * 100)
    computed = RecordingService(db).get_draft(rid)["computed"]
    assert computed["wind"] == "W 10 kts"
    assert computed["time_line"]           # the local start and end, as "H:MM-H:MM"


def test_the_post_takes_the_crews_line_over_the_recordings():
    computed = {"time_line": "1:04-3:53", "wind": "W 8-13 kts"}
    rec = {"start_time": "2026-09-13 05:04:00", "end_time": "2026-09-13 07:53:00"}

    def lines(draft):
        markup = render([{"type": "log_lines"}], PostContext(rec, draft=draft))
        return [p for p in markup.split("<p>")[1:]]

    from_data = lines({"computed": computed})
    assert "1:04-3:53" in from_data[0] and "W 8-13 kts" in from_data[1]

    typed = lines({"computed": computed, "time_line": "1:30-3:45", "wind": "NNE 12-14 kts"})
    assert "1:30-3:45" in typed[0] and "NNE 12-14 kts" in typed[1]


def test_clearing_the_crews_wind_goes_back_to_the_recordings(db):
    rid = _recording(db)
    _wind(db, rid, [270] * 100, [10] * 100)
    service = RecordingService(db)
    service.save_draft_fields(rid, {"wind": "Gusty"})
    assert "Gusty" in service.preview(rid, lambda p: p)

    service.save_draft_fields(rid, {"wind": ""})
    assert "W 10 kts" in service.preview(rid, lambda p: p)


def test_while_recording_the_time_runs_to_now(db):
    rid = db.create_recording("x", event_key="anchor_track_recording")
    db.update_recording(rid, start_time=datetime.utcnow() - timedelta(hours=2))
    line = RecordingService(db).get_draft(rid)["computed"]["time_line"]
    assert "-" in line


# === Nautical miles ===

def test_the_distance_is_in_nautical_miles():
    table = post_renderer.statistics_table_html({"distance_km": 12.345, "max_speed": 6.1})
    assert "6.67 nm" in table and "km" not in table
    assert "6.10 knots" in table


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
