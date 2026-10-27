"""Record every message on 127.0.0.1:1884 as JSON lines until a stop file appears."""
import json
import os
import sys
import time

import paho.mqtt.client as mqtt

out, stop = sys.argv[1], sys.argv[2]
f = open(out, 'w')

def on_message(c, u, msg):
    f.write(json.dumps([msg.topic, msg.payload.decode('utf-8', 'replace'), int(msg.retain)]) + '\n')

c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
c.on_message = on_message
c.connect('127.0.0.1', 1884)
c.subscribe('#')
c.loop_start()
print('CAPTURING', flush=True)
while not os.path.exists(stop):
    time.sleep(0.5)
time.sleep(2)
c.loop_stop()
f.close()
