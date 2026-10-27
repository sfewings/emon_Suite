"""paho subscription to emon/#, writing into state.py.

Modelled on enchantee_racing's mqtt_client.py. The routing itself is state.handle_message,
so everything here is the network loop and nothing a test needs.
"""

from __future__ import annotations

import logging

from state import LiveState, emon_feed, handle_message

log = logging.getLogger(__name__)

SUBSCRIPTIONS = ("emon/#",)
"""Envelopes, derived feeds and emon/config. Retained, so one subscribe fills the store.
Feeds outside emon (ecowitt, pantech) are accepted by raw topic (DESIGN 5) but not yet
subscribed to; they join this list when a page first needs one."""

DEFAULT_BROKER = "localhost"
DEFAULT_PORT = 1883
DEFAULT_KEEPALIVE = 60


class MqttClient:
    """paho 2, version 2 callbacks. emon_live is a new container with its own
    requirements, so it does not inherit the race app's pin on paho 1."""

    def __init__(self, state: LiveState, broker: str = DEFAULT_BROKER, port: int = DEFAULT_PORT,
                 keepalive: int = DEFAULT_KEEPALIVE, client_id: str = "emon-live") -> None:
        import paho.mqtt.client as mqtt  # here, so the tests and state.py need no paho

        self.state = state
        self.broker = broker
        self.port = port
        self.keepalive = keepalive
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            log.error("mqtt connect failed: %s", reason_code)
            return
        # On every connect, not once, so a broker restart does not leave pages frozen on
        # their last values. The bridge republishes emon/config on its own reconnect.
        for topic in SUBSCRIPTIONS:
            client.subscribe(topic)
        log.info("mqtt connected to %s:%s", self.broker, self.port)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        log.warning("mqtt disconnected: %s. paho will retry", reason_code)

    def _on_message(self, client, userdata, message) -> None:
        try:
            handle_message(self.state, message.topic, message.payload)
        except Exception:  # handle_message does not raise; this is the belt to its braces
            log.exception("dropped a message on %s", message.topic)

    def publish_reading(self, reading) -> None:
        """A derived reading on emon/derived/<id>, retained, as the bridge publishes its
        envelopes, so a consumer has every derived value the moment it subscribes."""
        self.client.publish(reading.topic, emon_feed.envelope_json(reading), retain=True)

    def start(self) -> None:
        """connect_async, so pages serve, showing dashes, before the broker is up."""
        self.client.connect_async(self.broker, self.port, self.keepalive)
        self.client.loop_start()

    def stop(self) -> None:
        self.client.loop_stop()
        try:
            self.client.disconnect()
        except Exception:
            pass
