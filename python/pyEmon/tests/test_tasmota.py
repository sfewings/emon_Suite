"""Tasmota plugs as pulse subnodes: the bridge's lines, and how the decoder treats them."""

import json
import os
import sys

import pytest

from tests.conftest import HAS_EMONSUITE

PYTHON = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PYTHON not in sys.path:
    sys.path.insert(0, PYTHON)

import emonTasmotaToMQTT as bridge  # noqa: E402

PULSE = {
    0: {"name": "Power board", "p0": "HWS", "p1": "Solar", "p2": "Consumed", "p3": "Imported",
        "p4": "Car", "p5": "Unused"},
    1: {"name": "Fridge plug", "tasmota": "plug_fridge", "p0": "Fridge", "p0_wPerPulse": 1,
        "p1": "Unused", "p2": "Unused", "p3": "Unused", "p4": "Unused", "p5": "Unused"},
    2: {"name": "Washer plug", "tasmota": "plug_washer", "p0": "Washing machine",
        "p1": "Unused", "p2": "Unused", "p3": "Unused", "p4": "Unused", "p5": "Unused"},
}

SENSOR = {"Time": "2026-11-20T21:00:00",
          "ENERGY": {"TotalStartTime": "2026-11-01T10:00:00", "Total": 12.3456, "Yesterday": 1.2,
                     "Today": 0.4, "Period": 1, "Power": 87.6, "ApparentPower": 120,
                     "ReactivePower": 82, "Factor": 0.73, "Voltage": 241, "Current": 0.5}}


def test_plug_subnodes_only_tasmota():
    assert bridge.plug_subnodes({"pulse": PULSE}) == {"plug_fridge": 1, "plug_washer": 2}
    assert bridge.plug_subnodes({"temp": {}}) == {}
    assert bridge.plug_subnodes({}) == {}


def test_plug_line():
    assert bridge.plug_line(1, SENSOR) == "pulse3,1,88,0,0,0,0,0,12346,0,0,0,0,0,0"
    assert bridge.plug_line(1, SENSOR, -62) == "pulse3,1,88,0,0,0,0,0,12346,0,0,0,0,0,0:-62"


def test_plug_line_odd_payloads():
    multi = {"ENERGY": {"Total": 1.0, "Power": [5, 7]}}
    assert bridge.plug_line(2, multi) == "pulse3,2,5,0,0,0,0,0,1000,0,0,0,0,0,0"
    negative = {"ENERGY": {"Total": 0.001, "Power": -0.4}}
    assert bridge.plug_line(2, negative).startswith("pulse3,2,0,")
    assert bridge.plug_line(1, {"AM2301": {}}) is None
    assert bridge.plug_line(1, {"ENERGY": {"Power": 5}}) is None
    assert bridge.plug_line(1, {"ENERGY": {"Total": "x", "Power": 5}}) is None


def test_state_rssi():
    assert bridge.state_rssi({"Wifi": {"RSSI": 76, "Signal": -62}}) == -62
    assert bridge.state_rssi({"Uptime": "1T00:00:00"}) is None


class FakeEmon:
    """Stands in for emon_mqtt: the settings, and the lines it was given."""

    class _Manager:
        def check_and_reload_settings(self):
            return False

    def __init__(self):
        self.settings = {"pulse": PULSE}
        self.settings_manager = self._Manager()
        self.lines = []

    def publish_config(self):
        pass

    def process_line(self, line):
        self.lines.append(line)


def test_bridge_handles_messages():
    emon = FakeEmon()
    b = bridge.TasmotaBridge(emon)
    b.handle("plug_fridge", "SENSOR", json.dumps(SENSOR))
    b.handle("plug_washer", "STATE", json.dumps({"Wifi": {"Signal": -70}}))
    b.handle("plug_washer", "SENSOR", json.dumps(SENSOR))
    b.handle("someone_else", "SENSOR", json.dumps(SENSOR))     # not configured: ignored
    b.handle("plug_fridge", "SENSOR", json.dumps({"no": "energy"}))
    b.handle("plug_fridge", "LWT", "Offline")
    assert emon.lines == ["pulse3,1,88,0,0,0,0,0,12346,0,0,0,0,0,0",
                          "pulse3,2,88,0,0,0,0,0,12346,0,0,0,0,0,0:-70"]


def test_bridge_drops_stale_rssi(monkeypatch):
    emon = FakeEmon()
    b = bridge.TasmotaBridge(emon)
    b.rssi["plug_fridge"] = (-50, 0.0)                         # long ago
    b.handle("plug_fridge", "SENSOR", json.dumps(SENSOR))
    assert emon.lines == ["pulse3,1,88,0,0,0,0,0,12346,0,0,0,0,0,0"]


@pytest.mark.skipif(not HAS_EMONSUITE, reason="needs the emonSuite extension")
def test_decoder_plug_readings_and_influx():
    from pyemonlib import emon_decoder

    line = bridge.plug_line(1, SENSOR, -62)
    emissions = emon_decoder.decode(line, PULSE, t=1000.0)
    names = [(e.reading.name, e.reading.value) for e in emissions if e.reading is not None]
    assert ("Fridge", 88) in names
    assert ("Fridge (pulse)", 12346) in names
    assert any(n.startswith("rssi") and v == -62 for n, v in names)
    assert len(names) == 3                                      # nothing for Unused channels

    influx = [e.influx() for e in emissions if e.influx is not None]
    sensors = [dict(tags)["sensor"] for _, tags, _ in influx]
    assert sensors == ["power/1/0", "pulse/1/0", "rssi/Fridge plug"]
    # Unused channels are still flagged, so the MQTT sink leaves their legacy topics out.
    assert sum(e.unused for e in emissions) == 10


@pytest.mark.skipif(not HAS_EMONSUITE, reason="needs the emonSuite extension")
def test_decoder_other_pulse_subnodes_unchanged():
    """Without 'tasmota', an Unused channel still goes to Influx, as it always has."""
    from pyemonlib import emon_decoder

    line = "pulse3,0,0,0,420,3,2,0,2782718,23913030,59333068,15654039,13720734,17,3246:-30"
    emissions = emon_decoder.decode(line, PULSE, t=1000.0)
    sensors = [dict(e.influx()[1])["sensor"] for e in emissions if e.influx is not None]
    assert "power/0/5" in sensors and "pulse/0/5" in sensors
    assert len(sensors) == 13
