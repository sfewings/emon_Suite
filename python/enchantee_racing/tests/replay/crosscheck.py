"""Compare what the app is serving against the log records that produced it.

Run this after a replay has finished. It reads the recording, finds the last record of
each kind at or before a given moment, and asserts that /hud/data is carrying exactly
those values. That covers the whole chain in one go: log file, the C++ EmonSerial parse,
emon_mqtt's topic mapping, mosquitto, the app's subscription, store.derive, and the JSON
the page polls.

    python tests/replay/replay.py tests/data/20260816_Frostbite_3.TXT -x 120 --stop 13:22
    python tests/replay/crosscheck.py tests/data/20260816_Frostbite_3.TXT --at 13:22

Exits non-zero on any disagreement. It earned its place the first time it ran, by
catching the replay exiting before paho had flushed its last publishes: every field was
close but wrong, which is the signature of data from the wrong moment rather than a
broken calculation.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.request

# gps,subnode,latitude,longitude,course,speed and the rest, per EmonShared.cpp. Indices
# are into the whole comma-split line, so field 0 is the timestamp.
GPS_COURSE, GPS_SPEED = 5, 6
IMU_HEADING = 12
MWV_SPEED, MWV_DIRECTION = 3, 4


def norm180(angle):
    return ((angle + 180.0) % 360.0) - 180.0


def last_records(path, at):
    """The last record of each kind at or before `at`, keyed "kind/subnode"."""
    latest = {}
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            parts = line.rstrip().split(",")
            if len(parts) < 3:
                continue
            if parts[0][11:] > at:
                break
            latest["%s/%s" % (parts[1], parts[2])] = parts
    return latest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file")
    parser.add_argument("--at", default="13:22:00", metavar="HH:MM:SS",
                        help="the moment the replay stopped, on the log's clock")
    parser.add_argument("--url", default="http://127.0.0.1:5002/hud/data")
    args = parser.parse_args(argv)

    at = args.at if args.at.count(":") == 2 else args.at + ":00"
    records = last_records(args.file, at)
    for needed in ("gps/0", "imu/0", "mwv/0", "mwv/1", "mwv/2"):
        if needed not in records:
            raise SystemExit("no %s record at or before %s in %s" % (needed, at, args.file))

    payload = json.loads(urllib.request.urlopen(args.url, timeout=5).read())
    fields = payload["fields"]

    gps, imu = records["gps/0"], records["imu/0"]
    mwv0, mwv1, mwv2 = records["mwv/0"], records["mwv/1"], records["mwv/2"]
    heading = float(imu[IMU_HEADING])
    true_direction = float(mwv2[MWV_DIRECTION])

    expected = [
        ("sog", float(gps[GPS_SPEED])),
        ("cog", float(gps[GPS_COURSE])),
        ("hdg", heading),
        ("tws", float(mwv2[MWV_SPEED])),
        ("twd", true_direction),
        ("aws", float(mwv1[MWV_SPEED])),
        # Neither of these is published by anything: the app derives them (DESIGN 3).
        ("twa", norm180(true_direction - heading)),
        ("awa", norm180(float(mwv0[MWV_DIRECTION]))),
    ]

    print("last records at or before %s" % at)
    for kind in ("gps/0", "imu/0", "mwv/0", "mwv/1", "mwv/2"):
        print("  %-6s %s" % (kind, records[kind][0][11:]))
    print()
    print("%-6s %12s %14s %8s" % ("field", "from log", "from the app", "age"))

    wrong = 0
    for name, want in expected:
        served = fields.get(name)
        if served is None:
            print("%-6s %12.2f %14s %8s  MISSING" % (name, want, "null", "-"))
            wrong += 1
            continue
        got = served["v"]
        ok = math.isclose(got, want, rel_tol=1e-6, abs_tol=1e-4)
        wrong += 0 if ok else 1
        print("%-6s %12.2f %14.2f %7.1fs  %s" % (name, want, got, served["age"],
                                                 "ok" if ok else "MISMATCH"))

    print()
    print("motor panels: %s" % payload["motor"])
    print("%d of %d fields disagree" % (wrong, len(expected)))
    return 1 if wrong else 0


if __name__ == "__main__":
    raise SystemExit(main())
