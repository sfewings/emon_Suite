"""FR-30: categories and crew offered, not typed.

Run in the dev container (dev/README.md):
    python -m pytest event_recorder/tests/test_suggestions.py
"""

import json
from datetime import datetime

import pytest

from event_recorder import post_suggestions
from event_recorder.models import Artefacts, Database, ImageType, RecordingStatus
from event_recorder.post_suggestions import count_names, crew_line, suggest_categories
from event_recorder.recording_service import RecordingService
from event_recorder.wordpress_publisher import WordPressPublisher

RULES = [
    {"name": "Track Logs", "when": "always"},
    {"name": "Ship's Log", "when": "moved", "metres": 200},
    {"name": "Twilight", "when": "weekday_evening", "after": "16:00"},
    {"name": "Club event", "when": "race_started"},
    {"name": "Rottnest", "when": "track_enters", "bbox": [-32.03, 115.44, -31.98, 115.56]},
]


# === Crew lines, as the hand-written posts on enchantee.org open ===

@pytest.mark.parametrize("first_paragraph, crew", [
    ("Henry, Steve", ["Henry", "Steve"]),
    ("Ian,Henry, Steve", ["Ian", "Henry", "Steve"]),
    ("Nagako, Catherine Steve", ["Nagako", "Catherine Steve"]),
    ("Fran and Roda", ["Fran", "Roda"]),
    ("Oscar, Amy, Billel, Richelle, Brian, Mike, Henry, Steve",
     ["Oscar", "Amy", "Billel", "Richelle", "Brian", "Mike", "Henry", "Steve"]),
    ("2:20-4:20", None),
    ("NNE 12-14kts", None),
    ("Depart 5:30 Arrive~10pm", None),
    ("Sailed a Sunday afternoon course 1 to test the new Race app.", None),
])
def test_a_crew_line_is_recognised_and_nothing_else_is(first_paragraph, crew):
    content = f'<p class="wp-block-paragraph">{first_paragraph}</p>\n<p>more</p>'
    assert crew_line(content) == crew


def test_a_photo_before_the_crew_line_does_not_hide_it():
    content = ('<figure class="wp-block-image"><img src="x.jpg"/></figure>'
               '<p class="wp-block-paragraph">Nagako, Catherine Steve</p>')
    assert crew_line(content) == ["Nagako", "Catherine Steve"]


def test_a_name_run_together_without_its_comma_is_split():
    # As on enchantee.org: Catherine never sails alone, Steve nearly always does
    counts = count_names([["Henry", "Steve"], ["Nagako", "Catherine Steve"]])
    assert counts == {"Henry": 1, "Steve": 2, "Nagako": 1, "Catherine": 1}


def test_a_two_word_name_nobody_sails_alone_with_is_kept_whole():
    assert count_names([["Mary Ann", "Steve"]]) == {"Mary Ann": 1, "Steve": 1}


# === Category rules ===

@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "rec.db"))


def _recording(db, start="2026-10-07 09:30:00"):      # Wednesday 17:30 in Perth
    rid = db.create_recording("x", event_key="anchor_track_recording")
    db.update_recording(rid, status=RecordingStatus.STOPPED, start_time=start)
    return db.get_recording(rid)


def _fixes(db, rid, *points):
    db.add_messages_batch([(rid, datetime(2026, 10, 7, 9, 30, i), "gps/position/0",
                            json.dumps({"lat": lat, "lon": lon, "ts": 0}))
                           for i, (lat, lon) in enumerate(points)])


def test_a_twilight_sail_on_the_river(db):
    rec = _recording(db)
    _fixes(db, rec["id"], (-32.0014, 115.8094), (-32.0100, 115.7800))
    assert suggest_categories(RULES, rec, db) == ["Track Logs", "Ship's Log", "Twilight"]


def test_a_saturday_race_to_rottnest(db):
    rec = _recording(db, start="2026-10-10 01:00:00")     # Saturday 9:00 in Perth
    _fixes(db, rec["id"], (-32.0014, 115.8094), (-31.9960, 115.5400))
    db.add_messages_batch([(rec["id"], datetime(2026, 10, 10, 1, 5), "race/event",
                            '{"type":"start","course":"rottnest","leg":0}')])
    assert suggest_categories(RULES, rec, db) == \
        ["Track Logs", "Ship's Log", "Club event", "Rottnest"]


def test_a_day_at_the_mooring_is_not_a_ships_log(db):
    rec = _recording(db, start="2026-10-10 01:00:00")
    _fixes(db, rec["id"], (-32.00140, 115.80940), (-32.00150, 115.80950))
    assert suggest_categories(RULES, rec, db) == ["Track Logs"]


@pytest.mark.parametrize("start, twilight", [
    ("2026-10-07 07:59:00", False),    # Wednesday 15:59
    ("2026-10-07 08:00:00", True),     # Wednesday 16:00
    ("2026-10-09 23:30:00", False),    # Saturday 07:30
])
def test_twilight_is_a_weekday_evening_in_boat_time(db, start, twilight):
    rec = _recording(db, start=start)
    assert ("Twilight" in suggest_categories(RULES, rec, db)) is twilight


def test_a_race_event_that_is_not_a_start_is_not_a_club_event(db):
    rec = _recording(db)
    db.add_messages_batch([(rec["id"], datetime(2026, 10, 7, 9, 31), "race/event",
                            '{"type":"select","course":"frostbite_1"}')])
    assert "Club event" not in suggest_categories(RULES, rec, db)


def test_a_rule_of_an_unknown_kind_is_skipped_not_fatal(db):
    rules = [{"name": "Whales", "when": "whales_seen"}, {"name": "Track Logs", "when": "always"}]
    assert suggest_categories(rules, _recording(db), db) == ["Track Logs"]


# === In the service ===

class Site:
    """The parts of WordPressPublisher refresh_from_site uses."""

    def __init__(self, reachable=True):
        self.reachable = reachable

    def test_connection(self):
        return self.reachable, "ok" if self.reachable else "no route"

    def list_categories(self):
        return ["Ship's Log", "Twilight", "Track Logs", "Whales"]

    def post_contents(self, category):
        assert category == "Ship's Log"
        return ['<p>Henry, Steve</p>', '<p>2:20-4:20</p>', '<p>Steve, Ed</p>',
                '<figure></figure><p>Nagako, Catherine Steve</p>']


def test_a_new_draft_starts_with_the_suggested_categories(db):
    service = RecordingService(db, post_config=lambda: {"categories": RULES})
    rec = _recording(db)
    _fixes(db, rec["id"], (-32.0014, 115.8094), (-32.0100, 115.7800))
    assert service.get_draft(rec["id"])["categories"] == ["Track Logs", "Ship's Log", "Twilight"]


def test_without_rules_a_new_draft_is_a_track_log(db):
    assert RecordingService(db).get_draft(_recording(db)["id"])["categories"] == ["Track Logs"]


def test_the_site_is_learnt_when_it_can_be_reached(db):
    service = RecordingService(db, wordpress_publisher=Site())
    service.save_draft_fields(_recording(db)["id"], {"crew": ["Ed", "Steve"]})

    assert service.refresh_from_site() is True

    assert service.categories_available() == ["Ship's Log", "Twilight", "Track Logs", "Whales"]
    # Steve: three posts and a draft; Ed: a post and a draft
    assert service.crew_suggestions()[:2] == ["Steve", "Ed"]
    assert set(service.crew_suggestions()) == {"Steve", "Ed", "Henry", "Nagako", "Catherine"}


def test_at_sea_what_was_learnt_is_kept(db):
    RecordingService(db, wordpress_publisher=Site()).refresh_from_site()
    offline = RecordingService(db, wordpress_publisher=Site(reachable=False))

    assert offline.refresh_from_site() is False
    assert "Whales" in offline.categories_available()


def test_a_recording_nobody_wrote_up_publishes_with_its_suggested_categories(db, tmp_path):
    sent = {}

    class WP(Site):
        def publish_recording(self, **kwargs):
            sent.update(kwargs)
            return {"id": 1, "link": "l", "status": "publish", "modified_gmt": "t"}
        def get_post(self, post_id):
            return None
        def find_post_by_link(self, link):
            return None

    service = RecordingService(db, plots_dir=str(tmp_path), wordpress_publisher=WP(),
                               post_config=lambda: {"categories": RULES})
    rec = _recording(db)
    db.update_recording(rec["id"], artefacts=Artefacts.FRESH)
    db.add_image(rec["id"], __file__, ImageType.USER_UPLOAD, "")
    _fixes(db, rec["id"], (-32.0014, 115.8094), (-32.0100, 115.7800))

    service.publish(rec["id"])

    assert sent["draft"]["categories"] == ["Track Logs", "Ship's Log", "Twilight"]


# === The publisher no longer creates categories ===

class Response:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body

    def raise_for_status(self):
        pass


def test_a_category_is_found_by_name_and_never_created(monkeypatch):
    wp = WordPressPublisher("http://wp.invalid", "u", "p")
    requests = []

    def fake(method, url, **kwargs):
        requests.append(method)
        return Response(200, [{"id": 2, "name": "Ship&#039;s Log"}])
    monkeypatch.setattr(wp, "_retry_request", fake)

    assert wp.get_category_id("Ship's Log", create=False) == 2
    assert wp.get_category_id("Garden Island", create=False) is None
    assert "POST" not in requests


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
