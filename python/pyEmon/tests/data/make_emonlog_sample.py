"""Regenerate emonlog_sample.txt, the regression fixture for test_decoder_regression.py.

    python tests/data/make_emonlog_sample.py

Serial lines as emonSerialToMQTT hands them to process_line: no timestamp, an optional
'|relaybits' path and an optional ':rssi'. Three sources:

- synthetic house lines for every node type and every subnode 0 to 5, built from the
  samples in tests/test_pybind.py, each also with an RSSI, a single relay hop with an
  RSSI, and two relay hops (whose RSSI is never published);
- real boat lines, the first of each node type and subnode from the two recorded
  Frostbite races in python/enchantee_racing/tests/data, plus a GPS line carrying an RSSI
  (GPS_RSSI below);
- lines that must be rejected: unknown node, malformed subnode, too few fields.

The committed fixture also holds real house lines, six per node type and subnode, from a
shannstainable day. That log is not in the repository, so regenerate on the shannstainable
Pi, or the house lines are lost:

    python tests/data/make_emonlog_sample.py --house /share/Input/20261018.TXT
"""

import argparse
import os
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
PYTHON = os.path.normpath(os.path.join(HERE, "..", "..", ".."))   # emon_Suite/python

HOUSE = {
    "rain": ["rain,100,3,2512,3456", "rain,0,0,-150,2900"],
    "hws": ["hws,19,49,50,52,52,52,39,0,0,0", "hws,61,66,58,55,54,53,41,1,0,1"],
    "temp": ["temp1,{s},4149,4,3554,2513,2651,3606", "temp1,{s},4100,2,-512,2100"],
    "disp": ["disp1,{s},2425"],
    "pulse": ["pulse3,{s},2867,1281,0,310,2425,0,748650,7417037,10674727,4105306,3236,17"],
    "wtr": ["wtr3,{s},4096,2,962290,552769", "wtr3,{s},4096,1,123,1,1820"],
    "scl": ["scl,{s},1522,3352"],
    "bat": ["bat2,{s},-173,-148,-13,1207598,2822473,42932,875943,11412025,15694,"
            "4983,2487,2497,2488,2467,2513,2484,2477,2480"],
    "inv": ["inv3,{s},58,360,527,0,8,648,95,948", "inv2,{s},124,191,487,3,0,2,77"],
    "bee": ["bee,{s},19,20,1123456,1234567,3215,2327,20456,4512"],
    "air": ["air,{s},1779,502,114,15,4,0"],
    "leaf": ["leaf,{s},57876,77,36,64,11440,8"],
    "bms": ["bms,{s},52.80,77.5,-25.80,20672,26.00,20,3.306,3.294,3.307,3.293,3.308,3.294,"
            "3.307,3.292,3.307,3.294,3.307,3.295,3.308,3.294,3.308,3.294"],
    "imu": ["imu,{s},0.1,0.2,0.3,0.4,0.5,0.6,700,800,900,180.0"],
}

BOAT_FILES = [
    os.path.join(PYTHON, "enchantee_racing", "tests", "data", "20260913_Frostbite_1.TXT"),
    os.path.join(PYTHON, "enchantee_racing", "tests", "data", "20260816_Frostbite_3.TXT"),
]
# Real, from an event_recorder recording of 4 Sep 2025 that was never committed
GPS_RSSI = ["gps,0,-35.0328670,117.8880100,128.88,2.22:13"]

REJECTED = [
    "nosuchnode,0,1,2,3",
    "temp1,x,4149,4,3554",
    "pulse3,0",
    "other,0,hello",
]


def _variants(line):
    yield line
    yield line + ":-61"
    yield line + "|00000010:-70"
    yield line + "|00000110:-75"


def house_lines():
    for node, templates in HOUSE.items():
        for template in templates:
            subs = range(6) if "{s}" in template else [None]
            for s in subs:
                yield from _variants(template.format(s=s) if s is not None else template)


def boat_lines(per_key=6):
    seen = OrderedDict()
    for path in BOAT_FILES:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            for raw in f:
                parts = raw.rstrip("\r\n").split(",", 3)
                if len(parts) < 4:
                    continue
                line = ",".join(parts[1:])
                key = (parts[1].rstrip("0123456789"), parts[2])
                if len(seen.setdefault(key, [])) < per_key:
                    seen[key].append(line)
    for lines in seen.values():
        yield from lines
    yield from GPS_RSSI


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--house", help="a real dated log (dd/mm/yyyy hh:mm:ss,line) to sample too")
    ap.add_argument("--out", default=os.path.join(HERE, "emonlog_sample.txt"))
    args = ap.parse_args()

    lines = list(house_lines()) + list(boat_lines()) + REJECTED
    if args.house:
        seen = {}
        with open(args.house, encoding="utf-8", errors="replace") as f:
            for raw in f:
                parts = raw.rstrip("\r\n").split(",", 3)
                if len(parts) >= 4:
                    node = parts[1].rstrip("0123456789")
                    # rain and hws have no subnode: field 2 is a reading, not a key
                    key = (node, None if node in ("rain", "hws") else parts[2])
                    if seen.get(key, 0) < 6:
                        seen[key] = seen.get(key, 0) + 1
                        lines.append(",".join(parts[1:]))
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print(f"{len(lines)} lines to {args.out}")


if __name__ == "__main__":
    main()
