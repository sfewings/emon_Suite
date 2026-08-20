"""paho-mqtt subscriptions, writing into store.py, plus the demo driver.

Topics are confirmed from the Sailing HUD tab of docs/reference/flows.json and listed
in DESIGN 3. Payloads from existing devices are bare numbers, one value per topic:
speeds in knots, angles in degrees. Do not change that for existing topics.

gps/position/0 is the one exception, and the one topic that carries a JSON object:

    {"lat":-32.0039101,"lon":115.8137589,"ts":1787132108}

One topic with both values, because two separate topics can be sampled either side of a
fix boundary and give a position that is half of one fix and half of the next. Near a
mark that is a few metres; on a line-crossing test it can put the boat on the wrong side
of the finish (DESIGN 3). It is published by pyemonlib.emon_mqtt.gpsMessage, verified
arriving off a replay of the 16 August 2026 Frostbite recording at about 1 Hz.

The payload's ts is the receiving host's clock, not the time of the fix, as the comment
on the publishing side says. Staleness here counts from arrival like every other reading:
using ts would measure the clock skew between publisher and app rather than fix age, and
the 5 s position cutoff is about how old the fix is (DESIGN 9.5).

There is no sentinel to check for. The publisher skips the topic entirely when there is
no fix, so a lost fix simply ages out past the cutoff, which is exactly the wanted
behaviour.

The demo driver at the bottom is a port of the two disabled inject nodes on the same
tab. Driving the display without the boat is how the motor panel swap gets checked at
the dock, and how finish detection will be checked later (DESIGN 9.1).
"""

from __future__ import annotations

import json
import logging
import math
import threading
from typing import Any, Callable, Optional

from engine import nav
from store import POSITION_KEY, Store, parse_number

log = logging.getLogger(__name__)

TOPICS = {
    "gps/speed/0": "sog",
    "gps/course/0": "cog",
    "imu/0/heading": "hdg",
    "anemometer/windSpeed/2": "tws",
    "anemometer/windDirection/2": "twd",
    "anemometer/windSpeed/1": "aws",
    "anemometer/windDirection/0": "awa",  # measured relative to the bow
    "anemometer/windDirection/1": "awd",  # apparent wind as a compass bearing, fallback
    "sevCon/rpm0": "rpm",
    "sevCon/current0": "cur",
    "sevCon/temperature/controller/0": "ctrl",
    "sevCon/temperature/motor/0": "mot",
}

POSITION_TOPIC = "gps/position/0"
"""Handled apart from TOPICS because its payload is a JSON object, not a bare number."""

SUBSCRIPTIONS = tuple(sorted(TOPICS)) + (POSITION_TOPIC,)

DEFAULT_BROKER = "localhost"
DEFAULT_PORT = 1883
DEFAULT_KEEPALIVE = 60


def parse_position(payload: Any) -> Optional[dict]:
    """Parse a gps/position payload into {"lat": .., "lon": ..}, or None if unusable.

    Rejects anything that is not a JSON object with two coordinates in range. The
    publisher already skips the topic when there is no fix, so this is a guard against a
    garbled message rather than the normal no-fix path, and a garbled fix is the one
    reading that must never reach a line-crossing test.
    """
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", "replace")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            return None
    if not isinstance(payload, dict):
        return None
    try:
        lat = float(payload["lat"])
        lon = float(payload["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    # NaN first, and separately from the range check, because NaN does not fail a range
    # check: every comparison with it is False, so abs(nan) > 90.0 is False and a NaN
    # would be stored as a valid fix. json.loads accepts a bare NaN token, and float()
    # accepts the result without complaint, so it is reachable from a garbled payload.
    if not math.isfinite(lat) or not math.isfinite(lon):
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    return {"lat": lat, "lon": lon}


def handle_message(store: Store, topic: str, payload: Any, ts: Optional[float] = None) -> bool:
    """Route one message into the store. Returns whether it was kept.

    A topic that is not ours, or a payload that does not parse, is dropped silently: the
    broker carries far more than this app cares about, and a bad reading must not take
    the network loop down with it.
    """
    if topic == POSITION_TOPIC:
        position = parse_position(payload)
        if position is None:
            return False
        store.set(POSITION_KEY, position, ts)
        return True

    key = TOPICS.get(topic)
    if key is None:
        return False
    value = parse_number(payload)
    if value is None:
        return False
    store.set(key, value, ts)
    return True


class MqttClient:
    """Subscribes to the HUD topics and writes every reading into the store.

    paho 1.x callback signatures, matching the pin in requirements.txt and the version
    already deployed alongside event_recorder on this Pi.
    """

    def __init__(
        self,
        store: Store,
        broker: str = DEFAULT_BROKER,
        port: int = DEFAULT_PORT,
        keepalive: int = DEFAULT_KEEPALIVE,
        client_id: str = "enchantee-racing",
    ) -> None:
        import paho.mqtt.client as mqtt  # imported here so the demo runs without paho

        self.store = store
        self.broker = broker
        self.port = port
        self.keepalive = keepalive
        self.client = mqtt.Client(client_id=client_id)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc != 0:
            log.error("mqtt connect failed, rc=%s", rc)
            return
        # Subscribed on every connect, not once at startup, so a broker restart does
        # not leave the page quietly frozen on its last values.
        for topic in SUBSCRIPTIONS:
            client.subscribe(topic)
        log.info("mqtt connected to %s:%s, %d topics", self.broker, self.port, len(SUBSCRIPTIONS))

    def _on_disconnect(self, client, userdata, rc) -> None:
        log.warning("mqtt disconnected, rc=%s. paho will retry", rc)

    def _on_message(self, client, userdata, message) -> None:
        try:
            handle_message(self.store, message.topic, message.payload)
        except Exception:  # a malformed reading must never kill the network loop
            log.exception("dropped a message on %s", message.topic)

    def start(self) -> None:
        """Connect and run the network loop on its own thread.

        connect_async so a broker that is not up yet delays nothing: the pages must
        serve, showing dashes, whether or not the boat's broker is reachable.
        """
        self.client.connect_async(self.broker, self.port, self.keepalive)
        self.client.loop_start()

    def stop(self) -> None:
        self.client.loop_stop()
        try:
            self.client.disconnect()
        except Exception:
            pass


# --- demo mode -------------------------------------------------------------
#
# Ports the "Demo values" and "Demo motor values" function nodes. Both inject nodes
# ship disabled in the flow; here they are off unless asked for on the command line.


def demo_readings(tick: int) -> list:
    """A plausible upwind reach, one second per tick."""
    wobble = math.sin(tick / 9.0)
    hdg = 192.0 + wobble * 3.0
    twd = 84.0 + wobble * 6.0
    tws = 19.5 + wobble * 1.2
    sog = 15.9 + wobble * 0.6
    return [
        ("gps/speed/0", sog),
        ("gps/course/0", (hdg + 4.0) % 360.0),
        ("imu/0/heading", hdg),
        ("anemometer/windSpeed/2", tws),
        ("anemometer/windDirection/2", twd % 360.0),
        ("anemometer/windSpeed/1", tws + 6.0),
        ("anemometer/windDirection/0", (304.0 + wobble * 4.0) % 360.0),
    ]


def demo_motor_readings(tick: int) -> list:
    """The SevCon running, so the motor panels can be checked at the dock."""
    wobble = math.sin(tick / 11.0)
    return [
        ("sevCon/rpm0", 1450.0 + wobble * 120.0),
        ("sevCon/current0", 62.4 + wobble * 8.0),
        ("sevCon/temperature/controller/0", 41.0 + wobble * 2.0),
        ("sevCon/temperature/motor/0", 58.0 + wobble * 3.0),
    ]


DEMO_START = {"lat": -32.002349, "lon": 115.812409}
"""Where the demo boat starts: the middle of the PFSYC start line. Passed in from
lines.json by app.py when it can be; this is the fallback so the demo runs standalone."""


class DemoDriver:
    """Feeds demo readings into the store once a second, on a daemon thread.

    Goes in through handle_message, the same path a real message takes, so the demo
    exercises the topic map, the number parsing and the position parsing rather than
    side-stepping them.
    """

    def __init__(self, store: Store, motor: bool = False, interval_s: float = 1.0,
                 start: Any = None) -> None:
        self.store = store
        self.motor = motor
        self.interval_s = interval_s
        self.position = nav.as_latlon(start or DEMO_START)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.tick = 0

    def step(self) -> None:
        """One tick's worth of readings. Called by the thread, and by the tests."""
        self.tick += 1
        readings = demo_readings(self.tick)
        if self.motor:
            readings = readings + demo_motor_readings(self.tick)
        for topic, value in readings:
            handle_message(self.store, topic, value)

        # Dead reckon the position from the speed and course this same tick published,
        # rather than inventing a track alongside them. A demo boat whose position
        # disagrees with its own SOG and COG would make every bearing and
        # distance-to-mark look wrong for reasons that have nothing to do with the code
        # under test. The original inject nodes had no position to publish, so there is
        # nothing to port here (DESIGN 9.1).
        readings = dict(readings)
        sog_knots = readings["gps/speed/0"]
        cog = readings["gps/course/0"]
        metres = sog_knots * nav.METRES_PER_NM / 3600.0 * self.interval_s
        self.position = nav.destination(self.position, cog, metres)
        handle_message(self.store, POSITION_TOPIC, json.dumps(
            {"lat": round(self.position.lat, 7), "lon": round(self.position.lon, 7)},
            separators=(",", ":")))

    def _run(self) -> None:
        while not self._stop.is_set():
            self.step()
            self._stop.wait(self.interval_s)

    def start(self) -> None:
        log.warning("demo mode: feeding synthetic readings, the boat's data is not in use")
        self._thread = threading.Thread(target=self._run, name="demo", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
