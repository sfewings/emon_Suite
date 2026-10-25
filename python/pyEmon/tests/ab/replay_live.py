"""Replay a recorded log in real time, round and round, as emonSerialToMQTT would.

For the emon_live test bench only: a throwaway broker, never the production one
(DESIGN 9.2). Runs inside an emon_serial_to_mqtt image so the bridge code is the image's.
"""
import re
import sys
import time
from datetime import datetime

from pyemonlib import emon_mqtt

broker, settings_path, path = sys.argv[1:4]
speed = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
m = emon_mqtt.emon_mqtt(mqtt_server=broker, mqtt_port=1883, settingsPath=settings_path)
time.sleep(1)
stamp = re.compile(r'^(\d\d/\d\d/\d{4} \d\d:\d\d:\d\d),')
lines = []
for raw in open(path, encoding='utf-8', errors='replace'):
    s = stamp.match(raw)
    if s:
        lines.append((datetime.strptime(s.group(1), '%d/%m/%Y %H:%M:%S').timestamp(), raw[s.end():].rstrip('\r\n')))
print(f"{len(lines)} lines, {lines[-1][0] - lines[0][0]:.0f} s", flush=True)
while True:
    start, t0 = time.time(), lines[0][0]
    for t, line in lines:
        wait = (t - t0) / speed - (time.time() - start)
        if wait > 0:
            time.sleep(wait)
        try:
            m.process_line(line)
        except Exception as e:
            print(f"Error processing line: {e}", flush=True)
    print("loop", flush=True)
