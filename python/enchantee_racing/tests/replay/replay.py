"""Replay a recorded emon log into MQTT, so the app can be driven without the boat.

Replay is the primary test strategy for this project (CLAUDE.md): line-crossing code is
exactly the kind that looks obviously correct and is not, and a recorded race is the
only honest way to find out. This is the tool that gets a recording onto the broker.

    docker compose -f tests/replay/docker-compose.yml up -d
    python tests/replay/replay.py tests/data/20260816_Frostbite_3.TXT --speed 60
    python app.py --broker localhost            # in another terminal

Publishing goes through pyemonlib's own emon_mqtt.process_line, not a reimplementation
of it, so every topic and payload is byte-for-byte what the boat puts on the broker,
gps/position/0 included. The parsing is the same C++ EmonSerial the boat firmware uses.
If the topic mapping ever changes, replay changes with it and nothing here needs
touching.

Two differences from python/emonCSVToMQTT.py, which does the same job for the whole
emon suite:

- Timing is scheduled against the first record rather than slept per line. Sleeping
  each gap in turn accumulates the scheduler's error, and over a two and a half hour
  race at 60x that drift is larger than the intervals being reproduced.
- It prints a progress line every few seconds instead of one line per record. A race is
  55,000 records, and the log noise was drowning the thing being tested.

Use emonCSVToMQTT.py when replaying anything else; use this when replaying a race.
"""

from __future__ import annotations

import argparse
import datetime
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent.parent          # python/enchantee_racing
PYTHON_DIR = PROJECT.parent           # python/

LOG_TIME_FORMAT = "%d/%m/%Y %H:%M:%S"
DEFAULT_SETTINGS = HERE / "emon_config.yml"

DRAIN_S = 2.0
"""How long to let paho write before exiting. Everything here is published at QoS 0, so
a message sits in the client's socket buffer until the network thread gets to it, and a
process that returns from main() straight after its last publish takes the tail of them
with it. Replaying the last ten seconds of a race and finding the app never saw them is
a fine way to waste an afternoon looking for a fault in the app."""

RACING_TYPES = ("gps", "imu", "mwv", "svc")
"""The record types that become topics mqtt_client.TOPICS subscribes to: gps for SOG,
COG and position, imu for heading, mwv for the anemometers, svc for the SevCon. A race
log also carries bms, pth and temp records, which are battery, pressure and cabin
temperature and reach no part of this app. Publishing them needs node configuration
this replay has no business inventing, so they are skipped by default and counted.
Pass --types all to put the whole log on the broker."""


def import_emon_mqtt():
    """Import pyemonlib: Python from the source tree, C++ extension from the build tree.

    pyemonlib.emonSuite is a pybind11 extension that is not in the source directory and
    not installed into this venv; it is left in pyEmon/build by whoever last built it.
    Rather than put the whole build tree on the path, which would quietly use a stale
    copy of the Python modules the day someone edits one without rebuilding, this takes
    the package from source and extends its __path__ to find the compiled bit.
    """
    sys.path.insert(0, str(PYTHON_DIR / "pyEmon"))
    try:
        import pyemonlib
    except ImportError as exc:
        raise SystemExit("cannot import pyemonlib from %s: %s" % (PYTHON_DIR / "pyEmon", exc))

    tag = "cpython-%d%d" % (sys.version_info[0], sys.version_info[1])
    for build in sorted((PYTHON_DIR / "pyEmon" / "build").glob("lib.*%s*" % tag)):
        package = build / "pyemonlib"
        if list(package.glob("emonSuite*")):
            pyemonlib.__path__.append(str(package))
            break
    else:
        raise SystemExit(
            "no built pyemonlib.emonSuite for %s under %s.\n"
            "Build it first:  cd %s && pip install -e ."
            % (tag, PYTHON_DIR / "pyEmon" / "build", PYTHON_DIR / "pyEmon")
        )

    from pyemonlib import emon_mqtt
    return emon_mqtt


def parse_clock(text):
    """A HH:MM or H:MM wall-clock time, as it reads in the log."""
    hours, minutes = text.split(":")
    return datetime.time(int(hours), int(minutes))


def records(path, start=None, stop=None):
    """Yield (timestamp, device_line) per usable line.

    device_line is what the boat's serial receiver would have handed to emon_mqtt:
    everything after the timestamp, e.g. "gps,0,-32.0013,115.8093,299.25,0.07".
    """
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.rstrip("\r\n")
            if not line.strip():
                continue
            parts = line.split(",", 2)
            if len(parts) < 3:
                continue
            try:
                stamp = datetime.datetime.strptime(parts[0], LOG_TIME_FORMAT)
            except ValueError:
                continue
            if start and stamp.time() < start:
                continue
            if stop and stamp.time() > stop:
                return
            yield stamp, parts[1] + "," + parts[2]


def summarise(path, start=None, stop=None):
    """What is in the file, without publishing anything. Needs no broker."""
    kinds = Counter()
    first = last = None
    for stamp, device in records(path, start, stop):
        first = first or stamp
        last = stamp
        fields = device.split(",")
        kinds["%s/%s" % (fields[0], fields[1] if len(fields) > 1 else "?")] += 1
    if first is None:
        print("no usable records")
        return
    span = (last - first).total_seconds()
    print("%s" % Path(path).name)
    print("  %s to %s  (%dh %02dm, %d records)"
          % (first.strftime("%H:%M:%S"), last.strftime("%H:%M:%S"),
             span // 3600, (span % 3600) // 60, sum(kinds.values())))
    for kind, count in sorted(kinds.items(), key=lambda kv: -kv[1]):
        print("  %-10s %6d  %5.2f Hz" % (kind, count, count / span if span else 0))


def _display_fields(device, seen):
    """Track a few values for the progress line. Display only, nothing depends on it."""
    fields = device.split(",")
    kind, subnode = fields[0], fields[1] if len(fields) > 1 else ""
    try:
        if kind == "gps" and subnode == "0" and len(fields) >= 6:
            seen["pos"] = (float(fields[2]), float(fields[3]))
            seen["sog"] = float(fields[5])
        elif kind == "imu" and subnode == "0" and len(fields) >= 12:
            seen["hdg"] = float(fields[11])
        elif kind == "mwv" and subnode == "2" and len(fields) >= 4:
            seen["tws"] = float(fields[2])
    except ValueError:
        pass


def replay(emon, path, speed, start, stop, progress_s, types=RACING_TYPES):
    sent = 0
    seen = {}
    skipped = Counter()
    failures = Counter()
    first_log = None
    started_at = time.monotonic()
    next_report = progress_s

    for stamp, device in records(path, start, stop):
        # emon_mqtt strips trailing digits off the record name, so temp1 is a temp
        # record. Match the same way or the filter misses them.
        kind = device.split(",", 1)[0].rstrip("0123456789")
        if types is not None and kind not in types:
            skipped[kind] += 1
            continue

        if first_log is None:
            first_log = stamp
            print("replaying from %s at %gx" % (stamp.strftime("%H:%M:%S"), speed))

        # Scheduled against the first record, so the error does not accumulate.
        due = (stamp - first_log).total_seconds() / speed
        behind = due - (time.monotonic() - started_at)
        if behind > 0:
            time.sleep(behind)

        try:
            emon.process_line(device)
            sent += 1
        except Exception as exc:  # a bad record must not end the replay
            reason = "%s: %s" % (kind, str(exc).split(" in line:")[0])
            failures[reason] += 1
            if sum(failures.values()) <= 3:
                print("  dropped %r: %s" % (device[:60], exc))

        _display_fields(device, seen)
        elapsed = time.monotonic() - started_at
        if elapsed >= next_report:
            next_report = elapsed + progress_s
            position = seen.get("pos")
            print("  %s  sent %6d  %s  sog %4.1f kt  hdg %3.0f  tws %4.1f kt"
                  % (stamp.strftime("%H:%M:%S"), sent,
                     "%.5f,%.5f" % position if position else "no fix",
                     seen.get("sog", 0.0), seen.get("hdg", 0.0), seen.get("tws", 0.0)))

    dropped = sum(failures.values())
    print("done: %d published, %d dropped, %d skipped, %.0f s wall clock"
          % (sent, dropped, sum(skipped.values()), time.monotonic() - started_at))
    for kind, count in sorted(skipped.items(), key=lambda kv: -kv[1]):
        print("  skipped %-6s %6d  (no topic this app subscribes to)" % (kind, count))
    for reason, count in sorted(failures.items(), key=lambda kv: -kv[1]):
        print("  DROPPED %6d  %s" % (count, reason))
    return dropped


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file", help="recorded emon log, e.g. tests/data/20260816_Frostbite_3.TXT")
    parser.add_argument("-m", "--broker", default="localhost")
    parser.add_argument("-p", "--port", type=int, default=1883)
    parser.add_argument("-x", "--speed", type=float, default=1.0,
                        help="playback multiplier: 60 replays a minute per second")
    parser.add_argument("--start", type=parse_clock, metavar="HH:MM",
                        help="skip to this time on the log's own clock")
    parser.add_argument("--stop", type=parse_clock, metavar="HH:MM")
    parser.add_argument("-s", "--settings", default=str(DEFAULT_SETTINGS),
                        help="emon_config.yml, needed only to name nodes in rssi topics")
    parser.add_argument("--summary", action="store_true",
                        help="describe the file and exit, publishing nothing")
    parser.add_argument("--types", default=",".join(RACING_TYPES),
                        help="record types to publish, or 'all' (default: %(default)s)")
    parser.add_argument("--progress-seconds", type=float, default=5.0)
    args = parser.parse_args(argv)

    types = None if args.types == "all" else tuple(t.strip() for t in args.types.split(","))

    if args.speed <= 0:
        parser.error("speed must be greater than 0")

    if args.summary:
        summarise(args.file, args.start, args.stop)
        return 0

    emon_mqtt = import_emon_mqtt()
    try:
        emon = emon_mqtt.emon_mqtt(mqtt_server=args.broker, mqtt_port=args.port,
                                   settingsPath=args.settings)
    except Exception as exc:
        raise SystemExit(
            "cannot reach the broker at %s:%d (%s).\n"
            "Start one:  docker compose -f tests/replay/docker-compose.yml up -d"
            % (args.broker, args.port, exc))
    print("publishing to %s:%d" % (args.broker, args.port))

    try:
        replay(emon, args.file, args.speed, args.start, args.stop, args.progress_seconds, types)
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        drain(emon)
    return 0


def drain(emon):
    """Give paho time to put the last publishes on the wire, then close tidily."""
    time.sleep(DRAIN_S)
    try:
        emon.mqttClient.loop_stop()
        emon.mqttClient.disconnect()
    except Exception:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
