"""Play a recorded log straight into the app, on one machine, with one command.

    python tests/replay/play_local.py tests/data/20260913_Frostbite_1.TXT --speed 4

Then open http://localhost:5002/map (or /, /gar, /hud) in a browser.

This is the light-weight sibling of replay.py, for a laptop with nothing on it but Python
and Flask: no Docker, no MQTT broker, no compiled pyemonlib. It runs the app in this
process and feeds the store directly, through mqtt_client.handle_message, so every reading
takes exactly the path it takes off the boat's broker. What it does not exercise is the
part replay.py exists to cover: the C++ log parse, emon_mqtt's topic mapping and the broker
itself (README.md, "Checking the replay actually landed"). Use replay.py for that; use this
to look at the screens.

The log lines are parsed here in Python, in the field order EmonShared.cpp prints them:

    gps,subnode,latitude,longitude,course,speed
    imu,subnode,accX,accY,accZ,magX,magY,magZ,gyroX,gyroY,gyroZ,heading
    mwv,subnode,windSpeed,windDirection,temperature
    svc,subnode,motorTemperature,controllerTemperature,capVoltage,batteryCurrent,rpm

and published to the topics pyemonlib/emon_mqtt.py would publish them on, in the same
order (course and speed before the combined position, so the engine sees them together).

Timing is scheduled against the first record replayed, as replay.py does, so it does not
drift. Readings are stamped with this machine's clock as they are fed, as they would be by
the broker. Keep --speed at 4 or below if the race engine matters: its 10 s hold after an
advance runs on the wall clock and is not compressed (README.md).
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import sys
import threading
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP_DIR))

import app as app_module  # noqa: E402
import mqtt_client  # noqa: E402
from store import Store  # noqa: E402

LOG_TIME_FORMAT = "%d/%m/%Y %H:%M:%S"


def _numbers(fields, count):
    """The first `count` fields as floats. A relay or RSSI suffix ("|0101", ":-45") is
    dropped from the field it is glued to; anything after `count` fields is ignored."""
    out = []
    for raw in fields[:count]:
        out.append(float(raw.split("|")[0].split(":")[0]))
    if len(out) < count:
        raise ValueError("short record")
    return out


def messages(kind, fields):
    """(topic, payload) pairs for one record, as emon_mqtt would publish them."""
    sub = int(fields[0])
    if kind == "gps":
        lat, lon, course, speed = _numbers(fields[1:], 4)
        out = [("gps/course/%d" % sub, course), ("gps/speed/%d" % sub, speed)]
        if abs(lat) <= 90.0 and abs(lon) <= 180.0:     # no fix is sent as 1000.0
            out.append(("gps/position/%d" % sub, json.dumps(
                {"lat": round(lat, 7), "lon": round(lon, 7), "ts": int(time.time())})))
        return out
    if kind == "imu":
        v = _numbers(fields[1:], 10)
        out = [("imu/%d/acc/%d" % (sub, i), v[i]) for i in range(3)]
        out.append(("imu/%d/heading" % sub, v[9]))
        return out
    if kind == "mwv":
        speed, direction, _temp = _numbers(fields[1:], 3)
        return [("anemometer/windSpeed/%d" % sub, speed),
                ("anemometer/windDirection/%d" % sub, direction)]
    if kind == "svc":
        motor, controller, _cap, current, rpm = _numbers(fields[1:], 5)
        return [("sevCon/temperature/motor/%d" % sub, motor),
                ("sevCon/temperature/controller/%d" % sub, controller),
                ("sevCon/current%d" % sub, current),
                ("sevCon/rpm%d" % sub, rpm)]
    return []


def records(path, start=None, stop=None):
    """(datetime, kind, fields) for every usable line, within the window if one is given."""
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            parts = line.strip().strip("\x00").split(",")
            if len(parts) < 3:
                continue
            try:
                stamp = datetime.datetime.strptime(parts[0], LOG_TIME_FORMAT)
            except ValueError:
                continue
            if start is not None and stamp.time() < start:
                continue
            if stop is not None and stamp.time() > stop:
                return
            yield stamp, parts[1], parts[2:]


def play(store, path, speed, start, stop, progress_s, done):
    first_log = first_wall = None
    next_progress = 0.0
    fed = 0
    for stamp, kind, fields in records(path, start, stop):
        try:
            pairs = messages(kind, fields)
        except (ValueError, IndexError):
            continue
        if not pairs:
            continue
        if first_log is None:
            first_log, first_wall = stamp, time.time()
            print("playing from %s at %gx" % (stamp.strftime("%H:%M:%S"), speed))
        due = first_wall + (stamp - first_log).total_seconds() / speed
        wait = due - time.time()
        if wait > 0:
            time.sleep(wait)
        for topic, payload in pairs:
            mqtt_client.handle_message(store, topic, payload)
        fed += 1
        if time.time() >= next_progress:
            next_progress = time.time() + progress_s
            fix = store.state().get("position") or {}
            where = fix.get("v") or {}
            print("  log %s   %6d records   %s" % (
                stamp.strftime("%H:%M:%S"), fed,
                "%.5f, %.5f" % (where["lat"], where["lon"]) if where else "no fix"))
    print("replay finished after %d records; the app keeps running, Ctrl+C to stop" % fed)
    done.set()


def parse_clock(text):
    return datetime.datetime.strptime(text, "%H:%M").time()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("file", help="a recorded log, e.g. tests/data/20260913_Frostbite_1.TXT")
    ap.add_argument("--speed", "-x", type=float, default=4.0,
                    help="playback speed, 4 = four times real time (default 4)")
    ap.add_argument("--start", type=parse_clock, metavar="HH:MM",
                    help="skip to this time on the log's own clock")
    ap.add_argument("--stop", type=parse_clock, metavar="HH:MM")
    ap.add_argument("--port", type=int, default=app_module.SERVICE_PORT)
    ap.add_argument("--host", default="127.0.0.1",
                    help="0.0.0.0 to open it from a phone or tablet on the same wifi")
    ap.add_argument("--progress-seconds", type=float, default=10.0)
    args = ap.parse_args(argv)

    path = Path(args.file)
    if not path.is_absolute() and not path.exists():
        path = APP_DIR / args.file          # also accept paths relative to the app
    if not path.exists():
        ap.error("no such log: %s" % args.file)

    logging.basicConfig(level=logging.WARNING)
    # The course-config warnings are known and not about this; keep them off the console.
    logging.getLogger("app").setLevel(logging.ERROR)

    store = Store()
    flask_app = app_module.create_app(store, app_module.load_config())
    done = threading.Event()
    threading.Thread(target=play, daemon=True,
                     args=(store, path, args.speed, args.start, args.stop,
                           args.progress_seconds, done)).start()

    shown = "localhost" if args.host in ("127.0.0.1", "0.0.0.0") else args.host
    print("open http://%s:%d/map   (also /  /gar  /hud)" % (shown, args.port))
    logging.getLogger("werkzeug").setLevel(logging.ERROR)   # no line per poll
    flask_app.run(host=args.host, port=args.port, threaded=True, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
