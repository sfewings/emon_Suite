"""Bridge Tasmota power plugs (e.g. Athom Plug V2) into emon as pulse3 lines.

Each plug publishes to the site's broker under its Tasmota Topic, with the default
FullTopic (%prefix%/%topic%/):

    tele/<topic>/SENSOR  {"ENERGY": {"Total": kWh, "Power": W, ...}, ...}  every TelePeriod
    tele/<topic>/STATE   {"Wifi": {"Signal": dBm, ...}, ...}                every TelePeriod
    tele/<topic>/LWT     Online | Offline                                   retained

A plug is a pulse subnode in emon_config that names its Topic in a 'tasmota' key:

    pulse:
      1:
        name: Fridge plug
        tasmota: plug_fridge
        p0: Fridge
        p0_wPerPulse: 1
        p1: Unused          # ... to p5

Each SENSOR message becomes one line, the plug in channel 0, energy as a Wh count:

    pulse3,<sub>,<W>,0,0,0,0,0,<Wh>,0,0,0,0,0,0[:<dBm>]

and goes through emon_mqtt.process_line, as the serial and GPS bridges do, so the plug
reaches the raw daily log (via EmonLog and emon_log), Influx, the legacy topics and the
emon/... envelopes like any other node. Monitoring only: nothing is sent to the plugs.
Topics with no 'tasmota' subnode are ignored with one warning each. emon_config is
re-read as the other bridges re-read it, so a plug is added by editing the config.
"""

import argparse
import json
import time
from typing import Any, Dict, Mapping, Optional

import paho.mqtt.client as mqtt

from pyemonlib import emon_mqtt

CHANNELS = 6          # PULSE_MAX_SENSORS
RSSI_MAX_AGE_S = 300  # a STATE older than this is not the plug's current signal


def plug_subnodes(settings: Mapping) -> Dict[str, int]:
    """{tasmota topic: pulse subnode} from the settings, for subnodes with a 'tasmota' key."""
    pulse = settings.get("pulse") if isinstance(settings, Mapping) else None
    if not isinstance(pulse, Mapping):
        return {}
    plugs = {}
    for sub, node in pulse.items():
        if isinstance(node, Mapping) and node.get("tasmota"):
            plugs[str(node["tasmota"])] = int(sub)
    return plugs


def _number(value: Any) -> Optional[float]:
    """A JSON number, or the first of a list of them (Tasmota's multi-channel form)."""
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def plug_line(sub: int, sensor: Mapping, rssi: Optional[int] = None) -> Optional[str]:
    """The pulse3 line for one SENSOR message, or None if it carries no usable ENERGY."""
    energy = sensor.get("ENERGY") if isinstance(sensor, Mapping) else None
    if not isinstance(energy, Mapping):
        return None
    power = _number(energy.get("Power"))
    total = _number(energy.get("Total"))
    if power is None or total is None:
        return None
    watts = max(0, int(round(power)))           # the parser takes digits only
    wh = max(0, int(round(total * 1000)))       # kWh to a Wh count, as pulse counters are
    powers = [watts] + [0] * (CHANNELS - 1)
    pulses = [wh] + [0] * (CHANNELS - 1)
    line = "pulse3," + ",".join(str(v) for v in [sub] + powers + pulses + [0])
    if rssi is not None:
        line += f":{int(rssi)}"
    return line


def state_rssi(state: Mapping) -> Optional[int]:
    """The WiFi signal in dBm from a STATE message."""
    wifi = state.get("Wifi") if isinstance(state, Mapping) else None
    if not isinstance(wifi, Mapping):
        return None
    signal = _number(wifi.get("Signal"))
    return None if signal is None else int(signal)


class TasmotaBridge:
    def __init__(self, emon: emon_mqtt.emon_mqtt):
        self.emon = emon
        self.rssi: Dict[str, tuple] = {}     # topic -> (dBm, time received)
        self.warned: set = set()

    def plugs(self) -> Dict[str, int]:
        # process_line checks again, but only after the topic is looked up here.
        if self.emon.settings_manager.check_and_reload_settings():
            self.emon.publish_config()
        return plug_subnodes(self.emon.settings)

    def warn_once(self, key: str, message: str) -> None:
        if key not in self.warned:
            self.warned.add(key)
            print(message, flush=True)

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        print(f"tasmota: connected ({reason_code}), plugs {self.plugs()}", flush=True)
        client.subscribe([("tele/+/SENSOR", 0), ("tele/+/STATE", 0), ("tele/+/LWT", 0)])

    def on_message(self, client, userdata, msg):
        try:
            _, topic, kind = msg.topic.split("/", 2)
        except ValueError:
            return
        try:
            self.handle(topic, kind, msg.payload.decode("utf-8", "replace"))
        except Exception as ex:   # one bad message must not stop the bridge
            print(f"tasmota: {msg.topic}: {ex}", flush=True)

    def handle(self, topic: str, kind: str, payload: str) -> None:
        if kind == "LWT":
            print(f"tasmota: {topic} {payload}", flush=True)
            return
        if kind == "STATE":
            rssi = state_rssi(json.loads(payload))
            if rssi is not None:
                self.rssi[topic] = (rssi, time.time())
            return
        if kind != "SENSOR":
            return
        sub = self.plugs().get(topic)
        if sub is None:
            self.warn_once(topic, f"tasmota: {topic} is not a 'tasmota' pulse subnode in emon_config; ignored")
            return
        rssi, seen = self.rssi.get(topic, (None, 0.0))
        if time.time() - seen > RSSI_MAX_AGE_S:
            rssi = None
        line = plug_line(sub, json.loads(payload), rssi)
        if line is None:
            self.warn_once(f"{topic}/ENERGY", f"tasmota: {topic} SENSOR has no ENERGY Power and Total; ignored")
            return
        self.emon.process_line(line)
        print(line, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bridge Tasmota power plugs into emon as pulse3 lines")
    parser.add_argument("-m", "--MQTT", help="MQTT broker the plugs and emon share", default="localhost")
    parser.add_argument("-s", "--settingsPath", help="emon_config.yml, or the folder of dated settings files",
                        default="/share/config/emon_config.yml")
    args = parser.parse_args()

    emon = emon_mqtt.emon_mqtt(mqtt_server=args.MQTT, mqtt_port=1883, settingsPath=args.settingsPath)
    bridge = TasmotaBridge(emon)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = bridge.on_connect
    client.on_message = bridge.on_message
    client.connect(args.MQTT, 1883, 60)
    client.loop_forever()


if __name__ == "__main__":
    main()
