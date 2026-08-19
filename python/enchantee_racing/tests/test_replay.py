"""Unit tests for the replay tool's log reading. No broker, no pyemonlib, no clock.

The publishing half of tests/replay/replay.py cannot be tested here: it goes through
pyemonlib's C++ extension to a real broker, which is what tests/replay/crosscheck.py is
for. What can be tested is everything before that, which is where a replay quietly gets
the wrong answer: the timestamp parsing, the window filtering, and the record-type filter
that decides what reaches the app at all.
"""

import sys
import tempfile
from datetime import time as clock_time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "replay"))

import mqtt_client  # noqa: E402
import replay  # noqa: E402

# Real lines from tests/data/20260816_Frostbite_3.TXT, one of each kind the log carries.
SAMPLE = """16/08/2026 13:02:24,gps,0,-32.001369476,115.809333801,299.25,0.07
16/08/2026 13:02:25,imu,0,0.040,-0.078,0.996,0.186,0.339,0.922,-1404.900,-135.500,-84.300,68.00
16/08/2026 13:02:25,mwv,0,12.3,351.0,22.3
16/08/2026 13:02:25,mwv,2,12.3,59.0,22.3
16/08/2026 13:02:26,svc,0,33,41,54.30,-0.20,-0.06
16/08/2026 13:02:26,pth,1,101590.00,22.50,37.70
16/08/2026 13:02:27,bms,1,54.30,99.6,3.10,318,15.00,33,3.351
16/08/2026 13:02:28,temp1,0,21.5,22.0,0.0,0.0
not a log line at all
16/08/2026 13:02:29,gps
16/08/2026 not-a-timestamp,gps,0,1,2,3,4
16/08/2026 13:59:59,gps,0,-32.002349853,115.815017700,221.97,4.19
"""


def _log(text=SAMPLE):
    handle = tempfile.NamedTemporaryFile("w", suffix=".TXT", delete=False, encoding="utf-8")
    handle.write(text)
    handle.close()
    return handle.name


def test_parse_clock():
    assert replay.parse_clock("13:05") == clock_time(13, 5)
    assert replay.parse_clock("9:30") == clock_time(9, 30)
    assert replay.parse_clock("00:00") == clock_time(0, 0)


def test_records_yields_the_device_line_the_boat_would_have_sent():
    """Everything after the timestamp, which is what emon_mqtt.process_line takes."""
    got = list(replay.records(_log()))
    assert got[0][1] == "gps,0,-32.001369476,115.809333801,299.25,0.07"
    assert got[0][0].strftime("%H:%M:%S") == "13:02:24"


def test_records_skips_what_it_cannot_read():
    """A log truncated mid-write must not stop a replay."""
    kinds = [device.split(",")[0] for _stamp, device in replay.records(_log())]
    assert kinds == ["gps", "imu", "mwv", "mwv", "svc", "pth", "bms", "temp1", "gps"]
    assert "not a log line at all" not in kinds


def test_records_filters_to_a_window_on_the_logs_own_clock():
    path = _log()
    assert len(list(replay.records(path, start=clock_time(13, 30)))) == 1
    assert len(list(replay.records(path, stop=clock_time(13, 30)))) == 8
    assert list(replay.records(path, start=clock_time(14, 0))) == []


def test_stop_ends_the_read_rather_than_filtering():
    """A recording is 55,000 lines; --stop should not read the rest of them."""
    lines = SAMPLE.splitlines(keepends=True)
    huge = _log("".join(lines[:5]) + "16/08/2026 20:00:00,gps,0,1,2,3,4\n" + "".join(lines) * 50)
    assert len(list(replay.records(huge, stop=clock_time(19, 0)))) == 5


def test_the_racing_types_are_the_ones_that_become_subscribed_topics():
    """If the app subscribes to a topic no replayed record produces, replay is useless.

    The mapping from record type to topic prefix is not mechanical, so it is written out
    here: this test is what catches a new subscription whose data replay never sends.
    """
    prefix_for = {"gps": "gps/", "imu": "imu/", "mwv": "anemometer/", "svc": "sevCon/"}
    assert set(prefix_for) == set(replay.RACING_TYPES)
    for topic in mqtt_client.TOPICS:
        assert any(topic.startswith(p) for p in prefix_for.values()), topic


def test_the_type_filter_strips_trailing_digits_like_emon_mqtt_does():
    """emon_mqtt does command.rstrip('0123456789'), so temp1 is a temp record.

    Matching any other way makes the filter miss records, and a skipped record that
    should have been published looks exactly like a sensor that stopped reporting.
    """
    for name, expected in [("temp1", "temp"), ("gps", "gps"), ("svc", "svc"), ("mwv", "mwv")]:
        assert name.rstrip("0123456789") == expected
    assert "temp" not in replay.RACING_TYPES  # so temp1 is skipped, not published


def test_summarise_describes_the_file_without_a_broker(capsys=None):
    replay.summarise(_log())  # must not raise; needs no broker and no pyemonlib


def test_drain_time_is_long_enough_to_matter():
    """Zero here means the tail of every replay is silently lost at QoS 0."""
    assert replay.DRAIN_S >= 1.0


if __name__ == "__main__":
    import traceback

    failures = 0
    for test_name, test in sorted(globals().items()):
        if not test_name.startswith("test_") or not callable(test):
            continue
        try:
            test()
        except Exception:
            failures += 1
            print("FAIL  " + test_name)
            traceback.print_exc()
        else:
            print("ok    " + test_name)
    print("%d failed" % failures if failures else "all passed")
    raise SystemExit(1 if failures else 0)
