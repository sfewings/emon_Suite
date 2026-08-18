"""paho-mqtt subscriptions, writing into store.py.

Skeleton only.

Topics are confirmed from docs/reference/flows.json and listed in DESIGN 3.
Payloads from existing devices are bare numbers, one value per topic: speeds in
knots, angles in degrees. Do not change that for existing topics.

    gps/speed/0                          SOG
    gps/course/0                         COG
    gps/position/0                       {"lat":.., "lon":.., "ts":..}
    imu/0/heading                        HDG
    anemometer/windSpeed/2               TWS
    anemometer/windDirection/2           TWD
    anemometer/windSpeed/1               AWS
    anemometer/windDirection/0           AWA, already bow relative
    anemometer/windDirection/1           AWD, fallback for AWA
    sevCon/rpm0                          motor RPM
    sevCon/current0                      motor current
    sevCon/temperature/controller/0      controller temperature
    sevCon/temperature/motor/0           motor temperature

Derived here or in the engine, not measured: TWA is norm180(twd - hdg), and AWA
falls back to norm180(awd - hdg) when anemometer/windDirection/0 is absent. Port
the existing implementations rather than rewriting them.

gps/position/0 does not exist yet. No latitude or longitude appears anywhere in
the 438 nodes of flows.json, and every race feature depends on position, so
publishing it is action item zero (DESIGN 3, build order step 5).

Race transitions are published outbound for event_recorder to log (DESIGN 11.9):

    race/event  {type, course, leg, leg_name, ts, lat, lon, source}
"""
