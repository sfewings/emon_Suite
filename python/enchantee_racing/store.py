"""Thread-safe {v, ts} cache holding the latest reading for each topic.

Skeleton only.

Two long-lived threads share this state: the paho network loop writing readings
and Flask request handlers reading them. Every mutation goes behind the single
lock defined here. Engine code never touches the store; it is handed values
(CLAUDE.md).

Readings leave here wrapped as {v, age} so the page can dim or blank a stale
sensor:

- Wind and motor readings go stale at 15 s and are dimmed.
- Position goes stale at 5 s, and the treatment is blanking, not dimming.
  Distance and bearing show `---`, and the leg engine stops evaluating advance.
  A dimmed number still reads as a number at a glance (DESIGN 9.5).

Position is the one topic whose payload is not a bare number: gps/position/0
carries {"lat":.., "lon":.., "ts":..} atomically so lat and lon always come from
the same fix (DESIGN 3).
"""
