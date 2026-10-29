"""emon_live: one site's live state, served to its pages (DESIGN 4.4).

Subscribes to emon/#, keeps the latest reading of every feed, and serves:

    /                 the emon-ui engine, from emon_Suite/ui/        (phase 2c)
    /site/<path>      the site's emon-ui folder: site.json, pages/*.json
    /api/state        {"theme", "feeds": {name: {v, u, age}}} for the feeds the pages use;
                      ?all=1 for every feed known, which is how a page gets written
    /api/energy       the Sankey's flows over ?period=now|today|yesterday|week|month,
                      when the site's derived.yml has a `sankey:` block (energy.py)
    /api/feeds        every feed name known, and any name two topics share
    /api/config       the emon_config in force, as the bridge published it
    /api/settings     POST {"theme": "day" | "night"}

With the site's derived.yml it also computes derived feeds (derived.py), seeded from
Influx on start (influx.py) and published on emon/derived/... with --publish.

Every URL a page uses is relative, so the same pages work behind nginx at /, on a raw
port, by IP or by mDNS name.

    python app.py --site ../../provisioning/shannstainable/emon-ui --port 5003
"""

from __future__ import annotations

import argparse
import gzip
import logging
import os
import threading
from pathlib import Path
from typing import Optional

from flask import Flask, abort, jsonify, request, send_from_directory

from state import LiveState, Site, state_document

log = logging.getLogger("emon_live")

HERE = Path(__file__).resolve().parent
DEFAULT_UI_DIR = HERE.parents[1] / "ui"
GZIP_MIN_BYTES = 500
"""Below this, gzip costs more than it saves. /api/state for a whole site is several KB
and is polled every second by every open screen, which is why it is gzipped at all."""

TICK_S = 5.0
"""How often derived periods are checked for a boundary passed with no reading: totals
drop to 0 within this of midnight, and a 09:00 window closes within this of 09:00."""


def create_app(state: LiveState, site: Site, ui_dir: Optional[Path] = DEFAULT_UI_DIR,
               sankey=None, window=None, banks=None) -> Flask:
    """`sankey` is an energy.Sankey when the site's derived.yml has a `sankey:` block,
    and `window` the influx.Window its past periods are answered from; without the
    latter only ?period=now has values."""
    app = Flask(__name__, static_folder=None)

    @app.after_request
    def _compress(response):
        if (response.mimetype == "application/json"
                and "gzip" in request.headers.get("Accept-Encoding", "")
                and not response.direct_passthrough
                and response.content_length is not None
                and response.content_length >= GZIP_MIN_BYTES):
            response.set_data(gzip.compress(response.get_data(), compresslevel=5))
            response.headers["Content-Encoding"] = "gzip"
            response.headers["Vary"] = "Accept-Encoding"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/state")
    def api_state():
        site.refresh()
        everything = request.args.get("all") in ("1", "true", "yes") or not site.pages
        return jsonify(state_document(state, None if everything else site.feeds))

    @app.get("/api/energy")
    def api_energy():
        """The Sankey's flows over one period (energy.py). "now" is live and costs
        nothing; the rest are Influx queries behind a cache, so a roomful of screens
        polling is still one set of queries a minute."""
        if sankey is None or not sankey:
            abort(404, "this site's derived.yml has no sankey: block")
        period = request.args.get("period", "now")
        try:
            return jsonify(sankey.document(period, state, window))
        except ValueError as ex:
            abort(400, str(ex))

    @app.get("/api/banks")
    def api_banks():
        """Every battery bank's cells and readings over one period (banks.py). "now" is
        live; the rest are bounded Influx queries behind a cache, answered once however
        many screens ask."""
        if banks is None or not banks:
            abort(404, "this site's derived.yml has no banks: block")
        period = request.args.get("period", "now")
        try:
            return jsonify(banks.document(period, state, window))
        except ValueError as ex:
            abort(400, str(ex))

    @app.get("/api/feeds")
    def api_feeds():
        return jsonify({
            "feeds": state.catalogue.keys(),
            "duplicates": {k: sorted(v) for k, v in state.catalogue.duplicates.items()},
        })

    @app.get("/api/config")
    def api_config():
        if state.config is None:
            abort(404, "no emon/config received yet")
        return jsonify(state.config)

    @app.post("/api/settings")
    def api_settings():
        body = request.get_json(silent=True) or {}
        return jsonify({"theme": state.set_theme(body.get("theme"))})

    @app.get("/site/<path:path>")
    def site_file(path):
        if site.root is None:
            abort(404)
        return send_from_directory(site.root, path)  # refuses paths outside the folder

    @app.get("/")
    def index():
        return ui_file("index.html")

    @app.get("/<path:path>")
    def ui_file(path):
        if ui_dir is None or not Path(ui_dir).is_dir():
            abort(404, "no ui folder; the engine arrives in phase 2c")
        return send_from_directory(ui_dir, path)

    return app


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--broker", default=os.environ.get("MQTT_IP", "localhost"))
    parser.add_argument("--broker-port", type=int, default=int(os.environ.get("MQTT_PORT", 1883)))
    parser.add_argument("--host", default=os.environ.get("BIND_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("SERVICE_PORT", 5003)))
    parser.add_argument("--site", default=os.environ.get("SITE_DIR"),
                        help="the site's emon-ui folder, e.g. provisioning/<site>/emon-ui")
    parser.add_argument("--ui", default=os.environ.get("UI_DIR", str(DEFAULT_UI_DIR)))
    parser.add_argument("--derived", default=os.environ.get("DERIVED_FILE"),
                        help="derived.yml; default <site>/derived.yml when there is one")
    parser.add_argument("--influx", default=os.environ.get("INFLUX_URL", "http://localhost:8086"),
                        help="where to seed derived values from on start; 'none' to skip")
    parser.add_argument("--publish", action="store_true",
                        default=os.environ.get("PUBLISH_DERIVED", "0") not in ("0", "", "false", "no"),
                        help="publish derived values on emon/derived/... (off for test runs)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    site = Site(args.site)
    state = LiveState(theme=site.site.get("theme", "day"))

    sankey = None
    banks_block = None
    window = None
    derived_file = args.derived or (Path(args.site) / "derived.yml" if args.site else None)
    if derived_file is not None and Path(derived_file).is_file():
        import banks
        import derived
        import energy
        import yaml
        state.derived = derived.load(derived_file)
        log.info("%s: %d derived feeds", derived_file, len(state.derived.entries))
        with open(derived_file, encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}
        sankey = energy.Sankey(doc)
        if sankey:
            log.info("%s: a sankey of %d flows", derived_file, len(sankey.flows))
        banks_block = banks.load(doc)
        if banks_block:
            log.info("%s: %d battery banks", derived_file, len(banks_block.list))
        if args.influx != "none":
            # Before subscribing, so the replay's readings come first and the retained
            # messages that follow are recognised as older (derived.Derived.on_value).
            import influx
            store = influx.Influx(args.influx)
            state.accept_derived(influx.seed(state.derived, store))
            if sankey or banks_block:
                series = dict(state.derived.influx)
                series.update(banks_block.series() if banks_block else {})
                window = influx.Window(store, series)

    from mqtt_client import MqttClient  # here, so create_app is importable without paho
    source = MqttClient(state, args.broker, args.broker_port)
    if args.publish:
        state.publish = source.publish_reading
    source.start()
    stop = threading.Event()
    if state.derived is not None:
        def tick() -> None:
            while not stop.wait(TICK_S):
                state.accept_derived(state.derived.tick(state.clock()))
        threading.Thread(target=tick, name="derived-tick", daemon=True).start()
    try:
        create_app(state, site, Path(args.ui), sankey, window, banks_block).run(
            host=args.host, port=args.port, threaded=True)
    finally:
        stop.set()
        source.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
