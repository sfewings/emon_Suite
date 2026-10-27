"""Publish decoded emissions to MQTT: legacy topics, envelopes and emon/config (DESIGN 4.2).

Takes any client with paho's publish(topic, payload, qos, retain) signature and imports
nothing from paho itself, so it can be tested with a fake.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Iterable, Mapping, Optional

from pyemonlib.emon_decoder import Emission
from pyemonlib.emon_feed import CONFIG_TOPIC, envelope_json


def _env_flag(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() not in ("0", "false", "no", "off")


def envelopes_enabled_by_default() -> bool:
    """EMON_ENVELOPES=0 in a container's environment turns the emon/... topics off."""
    return _env_flag("EMON_ENVELOPES")


def skip_unused_by_default() -> bool:
    """EMON_SKIP_UNUSED=0 publishes legacy topics for channels named Unused, as before."""
    return _env_flag("EMON_SKIP_UNUSED")


class MqttSink:
    def __init__(self, client: Any, envelopes: Optional[bool] = None, legacy: bool = True,
                 skip_unused: Optional[bool] = None, log: Callable[[str], None] = print):
        self.client = client
        self.envelopes = envelopes_enabled_by_default() if envelopes is None else envelopes
        self.skip_unused = skip_unused_by_default() if skip_unused is None else skip_unused
        self.legacy = legacy
        self.log = log

    def publish(self, emissions: Iterable[Emission], context: str = "") -> None:
        """Legacy topics first, exactly as before; then the envelopes, retained.

        The legacy lane stops at the first exception, as the old per-type functions did
        (see emon_decoder). The envelope lane does not depend on it: canonical readings
        never raise, so a channel missing from emon_config no longer hides the rest.

        Channels named Unused get no envelope, and with skip_unused no legacy topic
        either. That is the one intended change to the legacy topics (DESIGN 4.2).
        """
        emissions = list(emissions)
        if self.legacy:
            for emission in emissions:
                if emission.mqtt is None or (self.skip_unused and emission.unused):
                    continue
                try:
                    out = emission.mqtt()
                    if out is not None:
                        self.client.publish(*out)
                except Exception as ex:  # the old code swallowed and printed, per message
                    self.log(f"MQTT:{context} - {ex}")
                    break
        if self.envelopes:
            for emission in emissions:
                if emission.reading is None:
                    continue
                try:
                    self.client.publish(emission.reading.topic, envelope_json(emission.reading),
                                        retain=True)
                except Exception as ex:
                    self.log(f"MQTT envelope:{context} - {ex}")

    def publish_config(self, settings: Mapping, filename: Optional[str]) -> None:
        """The active settings file, retained, so any consumer can see every name."""
        if not self.envelopes:
            return
        doc = {"file": os.path.basename(filename) if filename else None, "settings": settings}
        try:
            self.client.publish(CONFIG_TOPIC, json.dumps(doc, default=str, separators=(",", ":")),
                                retain=True)
        except Exception as ex:
            self.log(f"MQTT config - {ex}")
