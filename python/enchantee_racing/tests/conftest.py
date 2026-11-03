"""Put the project root on sys.path so tests import the way the app does.

There is no packaging step. The app is deployed by copying the directory onto the
Pi and running app.py, so `from engine import nav` has to work from the root
without an install.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# --- feeding readings in -----------------------------------------------------------
#
# The app reads the boat's envelopes now, not the fourteen legacy topics it used to
# subscribe to (3 Nov 2026). Tests say what reading arrives, not how it is wrapped, so
# they go through this rather than building an envelope each time.
#
# Either naming works. LEGACY is the old topic for each feed, kept because it is the
# only written record of which topic became which name, and because it lets a test that
# predates the change keep reading as it did.

LEGACY = {
    "gps/speed/0": "Enchantee-GPS / speed",
    "gps/course/0": "Enchantee-GPS / course",
    "gps/position/0": "Enchantee-GPS / position",
    "imu/0/heading": "IMU Sensor / heading",
    "imu/0/acc/1": "IMU Sensor / acc port-starboard",
    "imu/0/acc/2": "IMU Sensor / acc vertical",
    "anemometer/windSpeed/2": "True wind / windSpeed",
    "anemometer/windDirection/2": "True wind / windDirection",
    "anemometer/windSpeed/1": "Apparent wind / windSpeed",
    "anemometer/windDirection/0": "Boat reference wind / windDirection",
    "anemometer/windDirection/1": "Apparent wind / windDirection",
    "sevCon/rpm0": "SevCon / rpm",
    "sevCon/current0": "SevCon / batteryCurrent",
    "sevCon/temperature/controller/0": "SevCon / controllerTemperature",
    "sevCon/temperature/motor/0": "SevCon / motorTemperature",
}


def feed(store, name, payload, ts=None, on_events=None):
    """Deliver one reading to the store as the boat would, and return whether it stuck.

    `name` is a feed name or one of the legacy topics in LEGACY. `payload` is the value:
    bytes and str are parsed as the old bare-number payloads were, so a test written
    against b"70" needs no change beyond calling this instead of handle_message.

    Topics that are not readings at all - event_recorder's recording status - are passed
    through untouched, since those are still plain topics.
    """
    import json

    import mqtt_client

    if isinstance(name, str) and name.startswith("event_recorder/"):
        return mqtt_client.handle_message(store, name, payload, ts, on_events)

    value = payload
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", "replace")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return mqtt_client.handle_message(
                store, *mqtt_client.demo_envelope(LEGACY.get(name, name), value),
                ts=ts, on_events=on_events)

    topic, body = mqtt_client.demo_envelope(LEGACY.get(name, name), value)
    return mqtt_client.handle_message(store, topic, body, ts, on_events)
