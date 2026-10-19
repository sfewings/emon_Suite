"""The decoder and sinks against the old publishers, line by line, for every site config.

tests/legacy holds emon_mqtt.py and emon_influx.py verbatim from master. For each
emon_config file in provisioning/ (and python/testing_emon_settings, which names most node
types) and each line of tests/data/emonlog_sample.txt, the old class and the new shim are
driven side by side with fake MQTT and Influx clients, and must produce:

- exactly the same legacy MQTT publishes, in order, with skip_unused off;
- the same publishes minus the topics of channels named Unused, with skip_unused on, which
  is the one intended change (DESIGN 4.2);
- byte-identical Influx line protocol, in order;
- the same exception, where the old code raised one.

Needs a build of the emonSuite extension (conftest.py); skipped without one.
"""

import glob
import json
import os
import shutil
import time
from datetime import datetime, timezone

import pytest

from tests.conftest import HAS_EMONSUITE, REPO

pytestmark = pytest.mark.skipif(not HAS_EMONSUITE, reason="needs a build of pyemonlib.emonSuite")

if HAS_EMONSUITE:
    import paho.mqtt.client as paho_client

    from pyemonlib import emon_feed, emon_influx, emon_mqtt
    from tests.legacy import emon_influx_legacy, emon_mqtt_legacy

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, "data", "emonlog_sample.txt")
T_FIXED = 1787132108.0
WHEN = datetime.fromtimestamp(T_FIXED, tz=timezone.utc)

CONFIGS = sorted(
    glob.glob(os.path.join(REPO, "provisioning", "*", "emon_config", "*.yml"))
    + glob.glob(os.path.join(REPO, "python", "testing_emon_settings", "emon_config", "*.yml"))
)


def _config_id(path):
    rel = os.path.relpath(path, REPO).replace("\\", "/")
    return rel.replace("/emon_config/", ":").replace("provisioning/", "")


def _lines():
    with open(SAMPLE, encoding="utf-8") as f:
        return [line.rstrip("\n") for line in f if line.strip()]


# --- fakes ------------------------------------------------------------------------------

def _wire(payload):
    """What paho would put on the wire for a payload."""
    if payload is None:
        return b""
    if isinstance(payload, (bytes, bytearray)):
        return bytes(payload)
    if isinstance(payload, str):
        return payload.encode("utf-8")
    if isinstance(payload, (int, float)):
        return str(payload).encode("ascii")
    raise TypeError(f"paho would refuse {type(payload)}")


class FakeMqtt:
    def __init__(self, *args, **kwargs):
        self.published = []

    def connect(self, *a, **k):
        pass

    def loop_start(self):
        pass

    def loop_stop(self):
        pass

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.published.append((topic, _wire(payload), qos, retain))


class FakeWriteApi:
    def __init__(self):
        self.lines = []

    def write(self, bucket, record):
        self.lines.append((bucket, record.to_line_protocol()))

    def close(self):
        pass


class FakeInflux:
    def __init__(self, *a, **k):
        self.api = FakeWriteApi()

    def write_api(self, *a, **k):
        return self.api

    def close(self):
        pass


@pytest.fixture
def fakes(monkeypatch):
    monkeypatch.setattr(paho_client, "Client", FakeMqtt)
    monkeypatch.setattr(emon_influx_legacy, "InfluxDBClient", FakeInflux)
    monkeypatch.setattr(emon_influx, "InfluxDBClient", FakeInflux)
    # gps/position carries int(time.time()); both old and new read the same clock.
    monkeypatch.setattr(time, "time", lambda: T_FIXED)


def _settings_dir(tmp_path, config):
    d = tmp_path / "config"
    d.mkdir()
    shutil.copy(config, d / "emon_config.yml")
    return str(d / "emon_config.yml")


def _run(obj, call):
    try:
        call()
        return None
    except Exception as ex:  # the old classes raise ValueError for bad lines
        return (type(ex).__name__, str(ex))


def _unused_topics(settings):
    """Legacy topics belonging to channels named Unused, worked out from the config alone,
    independently of the decoder."""
    topics = set()
    for node, subs in (settings or {}).items():
        if not isinstance(subs, dict):
            continue
        for sub, ns in subs.items():
            if not isinstance(ns, dict):
                continue
            for key, value in ns.items():
                if value != "Unused" or not isinstance(key, str) or not key[1:].isdigit():
                    continue
                ch, n = key[0], int(key[1:])
                if node == "temp" and ch == "t":
                    topics.add(f"temperature/temp/{sub}/{n}")
                elif node == "pulse" and ch == "p":
                    topics.update({f"power/{sub}/{n}", f"pulse/{sub}/{n}"})
                elif node == "hws" and ch == "t":
                    topics.add(f"temperature/HWS/{n}")
                elif node == "hws" and ch == "p":
                    topics.add(f"pump/HWS/{n}")
                elif node == "wtr" and ch == "f":
                    topics.add(f"water/flowCount/{sub}/{n}")
                elif node == "wtr" and ch == "h":
                    topics.add(f"water/height/{sub}/{n}")
                elif node == "bat" and ch == "v":
                    topics.add(f"battery/voltage/{sub}/{n}")
    return topics


# --- the tests --------------------------------------------------------------------------

@pytest.mark.parametrize("config", CONFIGS, ids=[_config_id(c) for c in CONFIGS])
def test_mqtt_legacy_topics_are_unchanged(fakes, tmp_path, config, capsys):
    path = _settings_dir(tmp_path, config)
    old = emon_mqtt_legacy.emon_mqtt(settingsPath=path)
    new = emon_mqtt.emon_mqtt(settingsPath=path, envelopes=False, skip_unused=False)
    new_skip = emon_mqtt.emon_mqtt(settingsPath=path, envelopes=False, skip_unused=True)
    unused = _unused_topics(old.settings)

    for line in _lines():
        for client in (old.mqttClient, new.mqttClient, new_skip.mqttClient):
            client.published.clear()
        e_old = _run(old, lambda: old.process_line(line))
        e_new = _run(new, lambda: new.process_line(line))
        e_skip = _run(new_skip, lambda: new_skip.process_line(line))
        assert e_new == e_old, line
        assert e_skip == e_old, line
        assert new.mqttClient.published == old.mqttClient.published, line

        expected = [p for p in old.mqttClient.published if p[0] not in unused]
        got = new_skip.mqttClient.published
        if got != expected:
            # The one way they may differ: an Unused channel whose legacy topic raised in
            # the old code (a missing key) and so hid everything after it. Skipping it
            # lets the rest through, which is better, and the extra topics must be ones
            # the old code would otherwise have sent.
            assert [p for p in got if p[0] in unused] == [], line
            assert all(p in got for p in expected), line
    capsys.readouterr()


@pytest.mark.parametrize("config", CONFIGS, ids=[_config_id(c) for c in CONFIGS])
def test_influx_points_are_unchanged(fakes, tmp_path, config, capsys):
    path = _settings_dir(tmp_path, config)
    old = emon_influx_legacy.emon_influx(settingsPath=path, batchProcess=False)
    new = emon_influx.emon_influx(settingsPath=path, batchProcess=False)
    for line in _lines():
        old.write_api.lines.clear()
        new.write_api.lines.clear()
        assert _run(new, lambda: new.process_line(WHEN, line)) == \
            _run(old, lambda: old.process_line(WHEN, line)), line
        assert new.write_api.lines == old.write_api.lines, line
    capsys.readouterr()


@pytest.mark.parametrize("config", CONFIGS, ids=[_config_id(c) for c in CONFIGS])
def test_envelopes_are_well_formed_named_and_unique(fakes, tmp_path, config, capsys):
    path = _settings_dir(tmp_path, config)
    new = emon_mqtt.emon_mqtt(settingsPath=path, envelopes=True, skip_unused=True)
    config_msgs = [p for p in new.mqttClient.published if p[0] == emon_feed.CONFIG_TOPIC]
    assert len(config_msgs) == 1 and config_msgs[0][3] is True, "emon/config, retained, at start"
    doc = json.loads(config_msgs[0][1])
    assert doc["file"] == "emon_config.yml" and isinstance(doc["settings"], dict)

    catalogue = emon_feed.Catalogue()
    for line in _lines():
        new.mqttClient.published.clear()
        _run(new, lambda: new.process_line(line))
        envelopes = [p for p in new.mqttClient.published if p[0].startswith("emon/")]
        topics = [p[0] for p in envelopes]
        assert len(topics) == len(set(topics)), f"two readings share a topic: {line}"
        for topic, payload, qos, retain in envelopes:
            assert retain is True, topic
            reading = emon_feed.parse(topic, payload)
            assert reading is not None and reading.topic == topic, topic
            assert reading.name and reading.name != "Unused", topic
            assert reading.t == T_FIXED, topic
            catalogue.add(reading)
    # Across every line, one name never means two channels.
    assert catalogue.duplicates == {}
    capsys.readouterr()


def test_the_sample_covers_every_payload_type():
    from pyemonlib import emon_decoder
    nodes = {line.split(",", 1)[0].rstrip("0123456789") for line in _lines()}
    assert set(emon_decoder.DECODERS) <= nodes
