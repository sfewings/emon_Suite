"""Flask routes, static and template serving. Port 5002, behind nginx at /race/.

Build order steps 3 and 6 (DESIGN 13): the ported HUD, and the race engine behind the API
that DESIGN 4 specifies.

Serving:

    GET  /              race screen, still a skeleton
    GET  /hud           instrument HUD, ported from docs/reference/flows.json
    GET  /hud/data      the {now, motor, fields} payload the HUD polls every 500 ms
    GET  /manifest.webmanifest  scope for both screens, so iOS keeps them in one web app
    GET  /api/state     HUD fields, position and race state in one payload
    GET  /api/courses   the course list for the selection screen
    GET  /api/config/<name>  one config document verbatim, for the map (DESIGN 12.1)
    POST /api/select    {course: "frostbite-3"}
    POST /api/timer     {hooter: 10 | 5 | 1 | null} or {nudge: seconds}
    POST /api/advance   {dir: +1 | -1}
    POST /api/shorten
    POST /api/reset

Still to come:

    PUT /api/config/{marks|courses|lines}

Every POST returns the race state it produced, so the device that pressed the button sees
the result without waiting for its next poll, and the events it caused, so nothing has to
be inferred from a state diff.

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
import mimetypes
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory

from engine import course, race
from mqtt_client import DEFAULT_BROKER, DEFAULT_PORT, DemoDriver, MqttClient
from store import Store

log = logging.getLogger(__name__)

# Python's mimetypes has no built-in entry for .m4a, and it looks for one in
# /etc/mime.types, which python:3.13-slim does not ship. So in the container the
# countdown clips were served as application/octet-stream, where on Windows and on the
# Pi's own Python they come out as audio/mp4. That is the whole of "the audio stopped
# working once it was hosted in a container": nothing about the files changed, and the
# bytes served are byte-identical to the bytes on disk.
#
# Registered here rather than by installing the media-types package into the image,
# because this way it holds whatever base image the Dockerfile uses, and it is visible in
# the place someone debugging a Content-Type would actually look.
#
# audio/mp4 rather than audio/x-m4a: it is the standard type for AAC in an MP4 container,
# and it is what the dev machine was serving while this worked.
mimetypes.add_type("audio/mp4", ".m4a")

HERE = Path(__file__).resolve().parent
CONFIG_DIR = HERE / "config"

SERVABLE_CONFIG = ("marks", "courses", "lines", "coast", "depth")
"""The config documents a browser may GET, by name and without an extension.

An allow-list rather than a directory listing, for the same reason the Dockerfile's COPY
list is one: it cannot start serving something that is dropped into config/ later. It is
also what makes the route traversal-proof without any path arithmetic, since the name is
compared against this tuple and never joined onto anything until it matches.

These five are the map's inputs and they are all safe to ship: DESIGN 12 says so of
coast.json and depth.json explicitly, and the marks, the courses and the lines are
already served in other shapes by /api/courses and /api/course/<id>.

race.json is deliberately absent. It is engine tuning, an arming radius and a stale
cutoff, and nothing in a browser draws it. The config editor of DESIGN 13 step 10 will
want PUT on some of these, which is why the URL has no extension: GET and PUT can then be
the same path, as DESIGN 4 writes it.
"""

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
    # The engine's tuning travels with the rest of the config, so app.py stays the only
    # place that reads a file and engine/ keeps taking documents (DESIGN 11.2).
    race_path = config_dir / "race.json"
    docs["race"] = json.loads(race_path.read_text(encoding="utf-8")) if race_path.exists() else {}
    return docs


def create_app(store: Store, config: dict | None = None) -> Flask:
    """Build the Flask app around an existing store.

    The store is passed in rather than created here so the tests can drive the pages
    with known readings, and so the MQTT loop and the app share one instance.
    """
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["STORE"] = store
    app.config["RACE_CONFIG"] = config or {}
    app.config.setdefault("EVENT_PUBLISHER", None)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/hud")
    def hud():
        return render_template("hud.html")

    @app.get("/hud/data")
    def hud_data():
        return jsonify(store.payload())

    @app.get("/manifest.webmanifest")
    def manifest():
        """The web app manifest, served from the app root rather than out of static/.

        The root matters. Its scope and start_url are relative, so they resolve against
        this URL: behind nginx that makes them /race/, and on the app's own port /. Served
        from static/ instead, "./" would resolve to /race/static/ and the scope would
        exclude both screens, which is the whole point of the file (DESIGN 5, CLAUDE.md).

        Read from disk on each request rather than cached, so it can be edited in place
        like the config documents. It is a handful of bytes and nothing polls it.
        """
        return send_from_directory(HERE, "manifest.webmanifest",
                                   mimetype="application/manifest+json")

    @app.get("/api/config/<name>")
    def api_config(name):
        """One config document, as JSON, for the map page to draw from (DESIGN 12.1).

        Sent as a file rather than re-serialised, so what the browser draws is byte for
        byte what is on disk and in git. That also means an edit to a course or a mark is
        picked up on the next request with no restart, unlike the copy load_config() holds
        for the engine, which is read once at startup.

        These are big by the standards of this app: coast and depth are 136 kB and 234 kB
        raw, 431 kB for the set with marks. They compress to about a fifth of that, which
        is why the nginx block sets gzip_types; without it nginx's default of text/html
        alone applies and all of that goes out uncompressed.
        """
        if name not in SERVABLE_CONFIG:
            return jsonify({"error": "no such config document", "name": name}), 404
        return send_from_directory(CONFIG_DIR, name + ".json",
                                   mimetype="application/json")

    @app.get("/api/state")
    def api_state():
        """HUD fields, position and race state. Everything a device needs, in one GET.

        One GET per 500 ms carries the lot, so every device converges within half a second
        and no page has to poll twice (DESIGN 4).

        A GET can cause a transition, because prestart becomes racing on the clock and the
        clock is evaluated here as well as on every fix. That is why it publishes: without
        it, a start that fell due while the boat sat still would never be logged.
        """
        payload = store.state()
        _drain_and_publish()
        return jsonify(payload)

    @app.get("/api/courses")
    def api_courses():
        """The course list for the selection screen: series, flags, distances (DESIGN 9.6)."""
        config = app.config["RACE_CONFIG"]
        courses = config.get("courses", {})
        unraceable = config.get("unraceable", set())
        return jsonify({
            "series": courses.get("series", {}),
            "courses": [
                {
                    "id": c["id"], "series": c["series"], "course_no": c["course_no"],
                    "distance_nm": c["distance_nm"], "wind_note": c.get("wind_note"),
                    "flags": c.get("flags", {}), "legs": len(c["legs"]),
                    "raceable": c["id"] not in unraceable,
                }
                for c in courses.get("courses", [])
            ],
        })

    @app.get("/api/course/<course_id>")
    def api_course(course_id):
        """Everything about one course, for the detail page (DESIGN 9.11).

        A briefing sheet: every leg with its mark, the side to round it, the leg's length
        and bearing, and the running total, plus what the sheet printed and what the
        arithmetic makes of it. Read-only, and it works whether or not this is the course
        being raced, because the crew looks at courses they have not chosen.

        The wind direction is taken from the store when there is one, so the leg types are
        this afternoon's rather than nothing at all. Without it the legs still list; they
        just do not say which are close hauled.
        """
        config = app.config["RACE_CONFIG"]
        chosen = [c for c in config.get("courses", {}).get("courses", [])
                  if c["id"] == course_id]
        if not chosen:
            return jsonify({"error": "unknown course %r" % course_id}), 404
        course_doc = chosen[0]

        marks = course.index_marks(config["marks"])
        twd = store.wind_direction()
        legs = course.leg_table(course_doc, marks, config["lines"], twd)
        series = config.get("courses", {}).get("series", {}).get(course_doc["series"], {})

        # The reconciliation findings for this course, so the page can say the printed
        # total is in doubt rather than leaving the crew to notice the numbers disagree
        # (DESIGN 7).
        notes = [str(p) for p in config.get("problems", []) if p.course == course_id]

        return jsonify({
            "id": course_doc["id"],
            "series": course_doc["series"],
            "series_name": series.get("name", course_doc["series"]),
            "division": course_doc.get("division"),
            "course_no": course_doc["course_no"],
            "distance_nm": course_doc["distance_nm"],
            "summed_nm": legs[-1]["cumulative_nm"] if legs else 0.0,
            "wind_note": course_doc.get("wind_note"),
            "flags": course_doc.get("flags", {}),
            "shortened_distance_nm": course_doc.get("shortened_distance_nm"),
            "shortened_at": course_doc.get("shortened_at"),
            "shortened_note": course_doc.get("shortened_note"),
            "time_limit": series.get("time_limit"),
            "starts": series.get("starts", []),
            "series_note": series.get("note"),
            "twd": twd,
            "raceable": course_id not in config.get("unraceable", set()),
            "notes": notes,
            "legs": legs,
        })

    def _drain_and_publish():
        """Publish whatever transitions have happened, from wherever they came.

        The store queues events rather than handing them back to one caller, because a
        transition can come from a command, from a fix on the paho thread, or from the
        clock reaching T-0 while a page happens to poll. Draining here covers all three,
        and each event is published exactly once because the drain empties the queue.
        """
        events = store.drain_events()
        publisher = app.config.get("EVENT_PUBLISHER")
        for event in events:
            log.info("race event: %s leg %s %s (%s)", event.get("type"), event.get("leg"),
                     event.get("leg_name"), event.get("source"))
            if publisher is not None:
                publisher(event)
        return events

    def _race_response(_events=None):
        # race_payload first: it evaluates the clock, so a start that fell due during this
        # request is in the payload and its event is in the drain below.
        payload = store.race_payload()
        drained = _drain_and_publish()
        # The body reports what this command caused, from apply_race's own return rather
        # than from the drain. The queue is shared with the paho thread, which drains
        # after every fix, so by the time we get here the drain can be empty even though
        # this POST did something. app.js feeds this array to announce(), so an empty one
        # silently loses the crew's notice. Publishing is unaffected: whichever thread
        # drains an event publishes it, and the drain empties the queue, so it still goes
        # to the broker exactly once.
        return jsonify({"race": payload,
                        "events": drained if _events is None else _events})

    @app.post("/api/select")
    def api_select():
        """{course: "frostbite-3"}. Builds the engine's context and selects the course."""
        course_id = (request.get_json(silent=True) or {}).get("course")
        config = app.config["RACE_CONFIG"]
        chosen = [c for c in config.get("courses", {}).get("courses", [])
                  if c["id"] == course_id]
        if not chosen:
            return jsonify({"error": "unknown course %r" % course_id}), 404
        if course_id in config.get("unraceable", set()):
            # engine/course.py found an error in this course, so it cannot be raced on
            # (DESIGN 7). Warnings do not block; errors do.
            return jsonify({"error": "course %r has config errors" % course_id}), 409

        # Choosing a course while one is live ends it first. The crew is on the course list
        # with a race running, tapping a card: they mean to sail that one instead, and the
        # old race is over whatever its leg said (DESIGN 9.6). It is logged as a reset
        # rather than a finish, because abandoning a race is not finishing one.
        store.apply_race(lambda state, context, now:
                         race.reset(state, context, now) if state.mode != race.IDLE
                         else (state, []))

        store.set_race_context(race.Context(
            course=chosen[0],
            marks=course.index_marks(config["marks"]),
            lines=config["lines"],
            config=race.Config.from_document(config.get("race")),
        ))
        return _race_response(store.apply_race(
            lambda state, context, now: race.select(state, context, course_id, now)))

    @app.post("/api/timer")
    def api_timer():
        """{hooter: 10 | 5 | 1 | null} to set T-0 from a hooter, or {nudge: seconds}.

        The nudge is not decoration: someone always taps late, and a start won on the line
        is won by a second (DESIGN 10).
        """
        body = request.get_json(silent=True) or {}
        if "nudge" in body:
            seconds = float(body["nudge"])
            return _race_response(store.apply_race(
                lambda state, context, now: race.nudge_timer(state, context, seconds, now)))
        hooter = body.get("hooter")
        minutes = None if hooter is None else float(hooter)
        return _race_response(store.apply_race(
            lambda state, context, now: race.set_timer(state, context, minutes, now)))

    @app.post("/api/advance")
    def api_advance():
        """{dir: +1 | -1}. Authoritative and immediate: manual is the contract (11.4)."""
        direction = int((request.get_json(silent=True) or {}).get("dir", 1))
        return _race_response(store.apply_race(
            lambda state, context, now: race.advance(state, context, direction, now)))

    @app.post("/api/shorten")
    def api_shorten():
        """Code flag S: arm the finish now, wherever the boat is (DESIGN 11.6).

        The confirm belongs in the browser, not here. An accidental tap ends the race, and
        a POST that has already arrived is too late to ask about.
        """
        return _race_response(store.apply_race(race.shorten))

    @app.post("/api/reset")
    def api_reset():
        """Back to idle. Only ever the crew: nothing here resets itself (DESIGN 11.5)."""
        return _race_response(store.apply_race(race.reset))

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
        # The demo boat starts on the line, which app.py can supply because it is the
        # side that reads config. engine/ works it out; mqtt_client only needs the answer.
        source = DemoDriver(store, motor=args.demo_motor,
                            start=course.start_point(config["lines"]))
    else:
        source = MqttClient(store, broker=args.broker, port=args.broker_port)
    source.start()

    app = create_app(store, config)
    # Wire the publisher that _drain_and_publish reads. Without this it stays at the
    # None create_app defaults it to, and every transition that does not come from a
    # position fix is logged and then dropped: select, timer, start, manual advance,
    # reset and shorten never reach race/event at all. DESIGN 11.9 wants all of them,
    # and the manual ones are the most diagnostic of the lot, since "a cluster of
    # manual overrides at one mark points straight at a bad coordinate". The tests set
    # this by hand, which is why they never caught its absence here.
    #
    # getattr because DemoDriver has no publish_event: in demo mode there is no broker
    # to publish to, and None is the right answer rather than an error.
    app.config["EVENT_PUBLISHER"] = getattr(source, "publish_event", None)
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
