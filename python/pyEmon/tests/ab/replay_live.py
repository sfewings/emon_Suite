"""Replay a recorded log in real time, round and round, as emonSerialToMQTT would.

    replay_live.py <broker> <settings.yml> <log> [speed] [passes]

speed 1 is real time; passes 0 (the default) is for ever. Runs inside an
emon_serial_to_mqtt image so the bridge code is the image's.

For the emon_live test bench: a throwaway broker (DESIGN 9.2). Pointed at a production
broker it is a live sail as far as every consumer knows, EmonLog included, so emon_influx
and emon_log store it: HANDOVER says how that was done and cleaned up on 27 Oct 2026.
"""
import re
import sys
import time
from datetime import datetime

from pyemonlib import emon_mqtt

broker, settings_path, path = sys.argv[1:4]
speed = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
passes = int(sys.argv[5]) if len(sys.argv) > 5 else 0
m = emon_mqtt.emon_mqtt(mqtt_server=broker, mqtt_port=1883, settingsPath=settings_path)
time.sleep(1)
stamp = re.compile(r'^(\d\d/\d\d/\d{4} \d\d:\d\d:\d\d),')
lines = []
for raw in open(path, encoding='utf-8', errors='replace'):
    s = stamp.match(raw)
    if s:
        lines.append((datetime.strptime(s.group(1), '%d/%m/%Y %H:%M:%S').timestamp(), raw[s.end():].rstrip('\r\n')))
print(f"{len(lines)} lines, {lines[-1][0] - lines[0][0]:.0f} s", flush=True)
done = 0
while passes == 0 or done < passes:
    start, t0 = time.time(), lines[0][0]
    for t, line in lines:
        wait = (t - t0) / speed - (time.time() - start)
        if wait > 0:
            time.sleep(wait)
        try:
            m.process_line(line)
        except Exception as e:
            print(f"Error processing line: {e}", flush=True)
    done += 1
    print(f"pass {done} done", flush=True)
time.sleep(3)   # let paho send what is queued
m.mqttClient.loop_stop()
m.mqttClient.disconnect()
