"""Compatibility shim: the emon_mqtt class, now over emon_decoder and sink_mqtt (DESIGN D4).

Keeps the class name, constructor and process_line that emonSerialToMQTT.py,
emonCSVToMQTT.py, emonGPSDToMQTT.py and enchantee_racing/tests/replay/replay.py use, and
the mqttClient attribute replay.py reaches into. New code should use the decoder and sink
directly. This file is deleted in PLAN phase 4.

What it publishes, per line:

- every legacy topic, as before, except those of channels named Unused in emon_config
  (EMON_SKIP_UNUSED=0 restores them);
- a retained envelope on emon/<node>/<sub>/<field>[/<idx>] per reading (EMON_ENVELOPES=0
  turns these off);
- the line itself on EmonLog, as before.

And emon/config, retained, at start and whenever the settings file changes.
"""

import paho.mqtt.client as mqtt

import pyemonlib.emon_settings as emon_settings
from pyemonlib import emon_decoder
from pyemonlib.sink_mqtt import MqttSink


class emon_mqtt:
    def __init__(self, mqtt_server="localhost", mqtt_port=1883, settingsPath="./emon_config.yml",
                 envelopes=None, skip_unused=None):
        self.settings_manager = emon_settings.EmonSettings(settingsPath)
        self.dispatch = {key: None for key in emon_decoder.DECODERS}
        self.dispatch["other"] = None
        self.mqttClient = mqtt.Client()
        self.mqttClient.on_connect = self.on_connect
        self.mqttClient.connect(mqtt_server, mqtt_port, 120)
        self.mqttClient.loop_start()
        self.lineNumber = -1
        self.sink = MqttSink(self.mqttClient, envelopes=envelopes, skip_unused=skip_unused,
                             log=print)
        self.publish_config()

    def on_connect(self, client, userdata, flags, rc):
        print(f"emon_mqtt:Connected with result code {rc}")

    def on_disconnect(self, client, userdata, rc=0):
        print("DisConnected result code {rc}")
        self.mqttClient.loop_stop()

    @property
    def settings(self):
        """Property to access current settings from settings manager."""
        return self.settings_manager.get_settings()

    def publish_config(self):
        self.sink.publish_config(self.settings, self.settings_manager.get_current_settings_file())

    def printException(self, exceptionSource, reading, ex):
        if self.lineNumber == -1:
            print(f"MQTT:{exceptionSource} {reading} - {ex}")
        else:
            print(f"MQTT:{exceptionSource}:{self.lineNumber}, {reading} - {ex}")

    find_v_reference = staticmethod(emon_decoder.find_v_reference)

    def check_int(self, s):
        if s[0] in ('-', '+'):
            return s[1:].isdigit()
        return s.isdigit()

    def process_line(self, line):
        if self.settings_manager.check_and_reload_settings():
            self.publish_config()

        lineFields = line.split(',', 2)
        command = lineFields[0].rstrip('0123456789')
        if len(lineFields) < 3 or not self.check_int(lineFields[1]):
            raise ValueError(f"Invalid line format: {line}")
        if command not in self.settings_manager.get_current_nodes():
            raise ValueError(f"No current configuration for node: {command} in line: {line}")
        if command not in self.dispatch.keys():
            raise ValueError(f"Unknown device: {command} in line: {line}")

        if command == "other":
            print(line)
        else:
            emissions = emon_decoder.decode(line, self.settings[command])
            self.sink.publish(emissions, context=f"{command}Exception {line}")
        # Now publish the entire string
        self.mqttClient.publish("EmonLog", line)
