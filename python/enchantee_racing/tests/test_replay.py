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


# --- the rig itself, and the instructions for it ---------------------------------------
#
# The commands in tests/replay/README.md are the ones anyone starting a replay copies, and
# a wrong one costs an afternoon rather than a test run: publishing into the provisioned
# broker writes a replayed race into InfluxDB under today's timestamps, and checking the
# wrong port compares a replay against live data. So the file and the instructions are
# held to each other here.


def _compose():
    return (ROOT / "tests" / "replay" / "docker-compose.yml").read_text(encoding="utf-8")


def _replay_readme():
    return (ROOT / "tests" / "replay" / "README.md").read_text(encoding="utf-8")


def test_the_rig_can_come_up_in_one_command_and_the_app_is_optional():
    """The broker alone by default, the app under --profile app.

    Default unchanged, because most of the time the app is wanted from a shell where
    Ctrl+C and up-arrow is the fastest edit-and-rerun loop there is. The profile is for
    when the app is not the thing being edited: driving a phone at it, or running beside
    the provisioned stack on the boat's Pi, where 1883 and 5002 are both taken.
    """
    import re

    compose = _compose()
    assert "container_name: racing_replay" in compose
    assert "container_name: enchantee_replay_mqtt" in compose

    # The app is behind the profile, and the broker is not.
    app = compose[compose.index("  racing:"):]
    assert re.search(r"profiles:\s*\n\s*- app", app), \
        "the app is not behind a profile, so the plain up -d now starts it too"
    broker = compose[compose.index("  mosquitto:"):compose.index("  racing:")]
    assert "profiles:" not in broker, "the broker must always come up"

    # Both ports come from variables with the plain-loop defaults, so the file works
    # unchanged on a laptop and moves out of the way on the Pi.
    assert "${REPLAY_MQTT_PORT:-1883}:1883" in compose
    assert "MQTT_PORT: ${REPLAY_MQTT_PORT:-1883}" in app, \
        "the app is not wired to the same broker port as the published one"
    assert "SERVICE_PORT: ${REPLAY_APP_PORT:-5002}" in app

    # 0.0.0.0, or the page loads on the Pi and not on the phone it is being tested on.
    assert "BIND_HOST: 0.0.0.0" in app, \
        "the replay app would bind loopback and be unreachable from a phone"
    # The image defaults to loopback because nginx fronts the deployed copy, which is what
    # makes this override necessary rather than decorative.
    provisioned = (ROOT.parent.parent / "provisioning" / "enchantee"
                   / "docker-compose.yml").read_text(encoding="utf-8")
    assert "BIND_HOST=127.0.0.1" in provisioned, \
        "the deployed copy no longer binds loopback, so check this override is still right"

    # The checkout over /app, two levels up from the compose file, or the replay runs the
    # image's copy of the code and proves nothing about the working tree.
    assert "- ../..:/app" in app, "the app container does not mount the checkout"

    # The boat's clock, because the recording's timestamps are local time.
    assert "TZ: ${TZ:-Australia/Perth}" in app


def test_the_readme_gives_the_commands_that_actually_work():
    """Every command in the Pi section was run verbatim before it was written down.

    Three of them carry an argument that is silently wrong if omitted, and each has its
    own reason: -p 1884 sends the replay to the isolated broker rather than the boat's,
    --url points the crosscheck at the replay rather than the deployed app, and
    --profile app on the way down stops the app being left holding the port.
    """
    readme = _replay_readme()
    compose = _compose()

    assert "--profile app up -d" in readme, "the README does not say how to start the app"
    assert "--profile app down" in readme, "the README does not say how to stop it"
    assert "REPLAY_MQTT_PORT=1884" in readme and "REPLAY_APP_PORT=5003" in readme

    # Both variables it names are the ones the compose file reads.
    for name in ("REPLAY_MQTT_PORT", "REPLAY_APP_PORT"):
        assert name in compose, "the README names %s and the compose file does not" % name

    # The three easily-forgotten arguments, each with its reason nearby. Checked on EVERY
    # invocation in the Pi section rather than once in the file: the first version of this
    # asserted the port appeared somewhere, and passed with it deleted from one of the two
    # commands, which is exactly the copy-and-paste that costs the afternoon.
    import re

    start = readme.index("## On the boat's Pi")
    end = readme.index("\n## ", start)
    section = readme[start:end]

    invocations = re.findall(r"[^\n]*replay\.py[^`]*?(?=\n\n|\n```)", section, re.S)
    assert invocations, "the Pi section gives no replay command at all"
    for call in invocations:
        assert "-p 1884" in call, \
            "a replay command with no -p would publish into the provisioned broker: %r" % (
                " ".join(call.split()),)

    checks = re.findall(r"[^\n]*crosscheck\.py[^`]*?(?=\n\n|\n```)", section, re.S)
    assert checks, "the Pi section gives no crosscheck command"
    for call in checks:
        assert "--url http://127.0.0.1:5003/api/state" in call, \
            "a crosscheck with no --url compares the replay against the deployed app: %r" % (
                " ".join(call.split()),)
    assert "docker restart racing_replay" in readme, \
        "template and config edits need a restart and the README does not say so"
    assert "../venv/bin/python" in readme, \
        "the Pi's system python3 has no paho, so the commands must name the venv"

    # And the long docker run it replaces is gone from both files that carried it.
    handover = (ROOT / "docs" / "HANDOVER.md").read_text(encoding="utf-8")
    for name, text in (("README.md", readme), ("HANDOVER.md", handover)):
        assert "docker run -d --name racing_replay" not in text, \
            "%s still gives the nine-line docker run" % name
        assert "--profile app" in text, "%s does not mention the profile" % name


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
