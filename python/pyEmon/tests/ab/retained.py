import time, paho.mqtt.client as mqtt
got = {}
c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
c.on_message = lambda c, u, m: got.__setitem__(m.topic, m.retain)
c.connect('127.0.0.1', 1884); c.subscribe('emon/#'); c.loop_start(); time.sleep(3); c.loop_stop()
print(f"retained emon/ topics {len(got)}, emon/config retained: {got.get('emon/config')}")
