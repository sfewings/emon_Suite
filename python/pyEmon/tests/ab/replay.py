"""Feed recorded lines through emon_mqtt.process_line, as emonSerialToMQTT does.

Runs inside an emon_serial_to_mqtt image (old or new), so it exercises that image's
installed pyemonlib. Lines may carry the 'dd/mm/yyyy hh:mm:ss,' prefix of the logs.
"""
import re
import sys
import time

import yaml
from pyemonlib import emon_mqtt

broker, settings_path, *files = sys.argv[1:]

def check_int(s):
    if s[0] in ('-', '+'):
        return s[1:].isdigit()
    return s.isdigit()

nodes = list(yaml.full_load(open(settings_path))) + ['base']
m = emon_mqtt.emon_mqtt(mqtt_server=broker, mqtt_port=1883, settingsPath=settings_path)
time.sleep(1)

stamp = re.compile(r'^\d\d/\d\d/\d{4} \d\d:\d\d:\d\d,')
fed = errors = 0
for path in files:
    for raw in open(path, encoding='utf-8', errors='replace'):
        line = stamp.sub('', raw.rstrip('\r\n'))
        f = line.split(',', 2)
        if len(f) > 2 and f[0].rstrip('0123456789') in nodes and f[1] and check_int(f[1]):
            try:
                m.process_line(line)
            except Exception as e:
                errors += 1
                print(f"Error processing line: {e}")
            fed += 1
            time.sleep(0.003)   # paho's queue is unbounded, but keep the broker comfortable
time.sleep(3)
m.mqttClient.loop_stop()
m.mqttClient.disconnect()
print(f"REPLAY fed={fed} errors={errors}")
