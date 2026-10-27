import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))   # emon_live: state, app, mqtt_client

import pytest  # noqa: E402

from state import LiveState  # noqa: E402  (also puts pyEmon on the path)

RETAINED = os.path.join(HERE, "data", "retained_shannstainable.jsonl")
"""Every retained emon/# message on shannstainable's broker on 21 Oct 2026, a few hours
after phase 1 was deployed: what emon_live receives the moment it subscribes there."""

CAPTURED_AT = 1792580200.0
"""About 5 s after the newest `t` in that capture (the power board, 1792580194.631). The
oldest is nearly three hours older: retained values of slow or silent feeds."""


class FakeClock:
    def __init__(self, now: float = CAPTURED_AT) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def state(clock):
    return LiveState(clock=clock)


def retained_messages():
    with open(RETAINED, encoding="utf-8") as f:
        return [tuple(json.loads(line)) for line in f]
