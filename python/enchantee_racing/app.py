"""Flask routes, static and template serving. Port 5002, behind nginx at /race/.

Build order step 3 (DESIGN 13): the HUD, ported off the Node-RED flow and served here
so it can be compared side by side against /nodered/hud with the boat running.

Serving now:

    GET /            race screen, still a skeleton
    GET /hud         instrument HUD, ported from docs/reference/flows.json
    GET /hud/data    the {now, motor, fields} payload the HUD polls every 500 ms

Still to come (DESIGN 4), once there is a race engine to serve:

    GET /api/state   HUD fields plus race state in one payload
    POST /api/select /api/timer /api/advance /api/reset
    PUT /api/config/{marks|courses|lines}

Constraints that are properties of the deployment, not preferences (CLAUDE.md):

- The app is reached as http://enchantee.local/race/, http://10.42.0.1/race/ and
  http://<current-ip>/race/, and must also work on its own port. No host is hardcoded
  anywhere, and pages address their data relative to location.pathname.
- Plain HTTP, no TLS. No secure-context APIs.
- No internet. Every page is self-contained; nothing is fetched off-box.

This module owns all file access. It reads config/ from disk and hands plain data to
engine/, which never touches the filesystem. On startup, and after any PUT to
/api/config, run engine.course.validate() over the three documents: refuse to offer a
course that has errors, and log warnings without blocking, because a printed distance
that does not reconcile is a data smell and sometimes the printed figure is the thing
that is wrong (DESIGN 7).
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from flask import Flask, jsonify, render_template

from engine import course
from mqtt_client import DEFAULT_BROKER, DEFAULT_PORT, DemoDriver, MqttClient
from store import Store

log = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
CONFIG_DIR = HERE / "config"

SERVICE_PORT = 5002


def load_config(config_dir: Path = CONFIG_DIR) -> dict:
    """Read the three config documents and validate them against each other.

    The only place these files are read. engine/ is handed the parsed documents, which
    is what lets the whole of the course validation run in CI without a filesystem.
    """
    docs = {
        name: json.loads((config_dir / ("%s.json" % name)).read_text(encoding="utf-8"))
        for name in ("marks", "courses", "lines")
    }
    problems = course.validate(docs["marks"], docs["courses"], docs["lines"])
    for problem in course.warnings(problems):
        log.warning("config: %s", problem)
    errors = course.errors(problems)
    for problem in errors:
        log.error("config: %s", problem)
    docs["problems"] = problems
    docs["unraceable"] = {p.course for p in errors if p.course}
    return docs


def create_app(store: Store, config: dict | None = None) -> Flask:
    """Build the Flask app around an existing store.

    The store is passed in rather than created here so the tests can drive the pages
    with known readings, and so the MQTT loop and the app share one instance.
    """
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["STORE"] = store
    app.config["RACE_CONFIG"] = config or {}

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/hud")
    def hud():
        return render_template("hud.html")

    @app.get("/hud/data")
    def hud_data():
        return jsonify(store.payload())

    return app


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enchantee race support app")
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind address. nginx proxies to 127.0.0.1, so that is the default")
    parser.add_argument("--port", type=int, default=SERVICE_PORT)
    parser.add_argument("--broker", default=DEFAULT_BROKER, help="MQTT broker host")
    parser.add_argument("--broker-port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--demo", action="store_true",
                        help="feed synthetic readings instead of subscribing to the broker")
    parser.add_argument("--demo-motor", action="store_true",
                        help="with --demo, also drive the SevCon panels")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    store = Store()
    config = load_config()

    source = None
    if args.demo:
        source = DemoDriver(store, motor=args.demo_motor)
    else:
        source = MqttClient(store, broker=args.broker, port=args.broker_port)
    source.start()

    app = create_app(store, config)
    try:
        # threaded so a slow poll from one phone cannot stall another: several devices
        # are expected, each polling twice a second (DESIGN 2).
        app.run(host=args.host, port=args.port, debug=args.debug, threaded=True,
                use_reloader=False)
    finally:
        source.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
