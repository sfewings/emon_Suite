"""FR-24: the post as a draft of blocks, rendered once for preview and publish.

Run in the dev container (dev/README.md):
    python -m pytest event_recorder/tests/test_post_renderer.py

That the Track Log layout reproduces the post as built before FR-24 was checked once,
against the old builder from git, on a replayed recording: identical to a reader
(requirements doc, FR-24 notes). These tests pin the structure that check found.
"""

import os
import re
import time

import pytest

from event_recorder import post_renderer
from event_recorder.models import Artefacts, Database, ImageType, PostState, RecordingStatus
from event_recorder.post_renderer import LAYOUT_SHIP_LOG, LAYOUT_TRACK_LOG, PostContext, render
from event_recorder.recording_service import RecordingError, RecordingService
from event_recorder.web_interface import WebInterface
from event_recorder.wordpress_publisher import WordPressPublisher


@pytest.fixture
def perth(monkeypatch):
    """The boat's timezone, for the times written into a post."""
    monkeypatch.setenv("TZ", "Australia/Perth")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


RECORDING = {"id": 5, "name": "anchor_track_recording - 2026-09-01 17:30:00",
             "description": "Sailed to Pt Walter & back <quickly>",
             "start_time": "2026-09-01 09:30:00", "end_time": "2026-09-01 12:20:00"}


def _media():
    return [
        {"url": "https://x/route_map_0.png", "large_url": "https://x/route_map_0-1024.png",
         "id": 11, "caption": "Route Map", "image_type": "plot", "path": "/p/5/route_map_0.png"},
        {"url": "https://x/speed.png", "id": 12, "caption": "Speed",
         "image_type": "plot", "path": "/p/5/speed.png"},
        {"url": "https://x/kite.jpg", "id": 13, "caption": "Kite up",
         "image_type": "user_upload", "path": "/u/5/kite.jpg"},
        {"url": "https://x/sunset.jpg", "id": 14, "caption": "",
         "image_type": "user_upload", "path": "/u/5/sunset.jpg"},
    ]


def _ctx(**kwargs):
    return PostContext(dict(RECORDING), media=_media(),
                       statistics={"distance_km": 12.345, "max_speed": 6.1},
                       downloads=[{"url": "https://x/t.gpx", "label": "GPS Track",
                                   "export_type": "gpx"}], **kwargs)


def _headings(markup):
    return re.findall(r'<h2 class="wp-block-heading">([^<]*)</h2>', markup)


def _before_more(markup):
    return markup.split("<!--more-->")[0]


@pytest.mark.parametrize("layout", [LAYOUT_TRACK_LOG, LAYOUT_SHIP_LOG])
def test_every_block_is_opened_and_closed(layout):
    markup = render(layout, _ctx(draft={"crew": ["Henry", "Steve"]}))
    opened = re.findall(r"<!-- wp:([a-z-]+)", markup)
    closed = re.findall(r"<!-- /wp:([a-z-]+)", markup)
    assert sorted(opened) == sorted(closed)
    assert markup.count("<!--more-->") == 1


def test_the_track_log_layout_is_todays_post():
    markup = render(LAYOUT_TRACK_LOG, _ctx())

    assert _headings(markup) == ["Track Summary", "Statistics", "Data Visualizations", "Downloads"]
    above = _before_more(markup)
    # Crew photos straight after the summary, by-lines in italics, then the
    # statistics and the route map, all above the break
    assert above.index("kite.jpg") < above.index("Statistics") < above.index("route_map_0")
    assert "<em>Kite up</em>" in above
    # The route map is not repeated among the charts
    assert markup.count("route_map_0") == 1


def test_the_ship_log_layout_puts_the_story_first_and_the_data_below_the_break(perth):
    markup = render(LAYOUT_SHIP_LOG, _ctx(draft={
        "crew": ["Henry", "Steve"], "wind": "NNE 12-14 kts",
        "story": "Sailed course 3.\n\nA great start, faded late."}))

    above = _before_more(markup)
    paragraphs = re.findall(r"<p>(.*?)</p>", above)
    assert paragraphs[:5] == ["Henry, Steve", "5:30-8:20", "NNE 12-14 kts",
                              "Sailed course 3.", "A great start, faded late."]
    assert "Statistics" not in above and "Track Summary" not in markup
    # Photos as the hand-written posts have them: captioned only when typed
    assert "<figcaption" in above.split("kite.jpg")[1].split("</figure>")[0]
    assert "<em>" not in above
    assert "<figcaption" not in above.split("sunset.jpg")[1].split("</figure>")[0]
    assert _headings(markup) == ["Statistics", "Data Visualizations", "Downloads"]


def test_with_no_story_the_ship_log_falls_back_on_the_description(perth):
    markup = render(LAYOUT_SHIP_LOG, _ctx())
    assert "Sailed to Pt Walter &amp; back &lt;quickly&gt;" in markup


def test_an_uploaded_image_is_the_block_the_editor_writes(perth):
    markup = render(LAYOUT_TRACK_LOG, _ctx())
    assert ('<!-- wp:image {"id":11,"sizeSlug":"large","linkDestination":"none"} -->'
            in markup)
    assert ('<img src="https://x/route_map_0-1024.png" alt="Route Map" class="wp-image-11"/>'
            in markup)
    # Without a large size the original is used
    assert 'src="https://x/speed.png"' in markup


def test_what_the_crew_type_is_escaped():
    markup = render(LAYOUT_TRACK_LOG, _ctx())
    assert "&lt;quickly&gt;" in markup and "<quickly>" not in markup

    story = render([{"type": "story"}], _ctx(draft={"story": "<script>x</script>"}))
    assert "<script>" not in story


@pytest.mark.parametrize("start, end, line", [
    ("2026-09-01 09:30:00", "2026-09-01 12:20:00", "5:30-8:20"),
    ("2026-09-01 04:05:00", "2026-09-01 06:00:00", "12:05-2:00"),
    ("2026-09-01 04:05:00", None, "12:05"),
])
def test_the_time_line_reads_as_the_hand_written_posts_do(perth, start, end, line):
    assert post_renderer.log_time_line({"start_time": start, "end_time": end}) == line


# === Drafts ===

@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "rec.db"))


@pytest.fixture
def service(db, tmp_path):
    return RecordingService(db, plots_dir=str(tmp_path / "plots"),
                            uploads_dir=str(tmp_path / "uploads"))


@pytest.fixture
def client(db, service, tmp_path):
    return WebInterface(database=db, plots_dir=str(tmp_path / "plots"),
                        uploads_dir=str(tmp_path / "uploads"),
                        recording_service=service).app.test_client()


@pytest.fixture
def rid(db):
    rid = db.create_recording("Sunday race", "Course 3")
    db.update_recording(rid, status=RecordingStatus.STOPPED, artefacts=Artefacts.FRESH)
    return rid


def test_a_draft_is_offered_but_not_stored_until_the_first_edit(client, db, rid):
    draft = client.get(f"/api/recordings/{rid}/draft").get_json()["draft"]

    assert draft["stored"] is False and draft["revision"] == 0
    assert draft["title"] == "Sunday race" and draft["excerpt"] == "Course 3"
    # The ship's log, approved as the default (FR-25)
    assert draft["blocks"] == LAYOUT_SHIP_LOG
    assert db.get_draft(rid) is None


def test_saving_stores_the_draft_and_counts_the_revision(client, rid):
    saved = client.put(f"/api/recordings/{rid}/draft",
                       json={"revision": 0, "changes": {"title": "Twilight", "crew": ["Ed"]}})
    draft = saved.get_json()["draft"]

    assert saved.status_code == 200
    assert (draft["stored"], draft["revision"], draft["title"], draft["crew"]) == \
        (True, 1, "Twilight", ["Ed"])
    # Untouched fields keep what the new draft started with
    assert draft["blocks"] == LAYOUT_SHIP_LOG


def test_a_save_based_on_an_old_revision_is_refused_with_the_current_draft(client, rid):
    client.put(f"/api/recordings/{rid}/draft", json={"revision": 0, "changes": {"title": "A"}})

    stale = client.put(f"/api/recordings/{rid}/draft",
                       json={"revision": 0, "changes": {"title": "B"}})

    assert stale.status_code == 409
    assert stale.get_json()["draft"]["title"] == "A"


@pytest.mark.parametrize("changes", [
    {"titel": "typo"},
    {"crew": "Ed"},
    {"blocks": [{"type": "marquee"}]},
])
def test_a_save_that_is_not_a_draft_is_refused(client, rid, changes):
    response = client.put(f"/api/recordings/{rid}/draft", json={"revision": 0, "changes": changes})
    assert response.status_code == 400


def test_a_published_recordings_draft_cannot_change(client, db, rid):
    db.set_post_state(rid, PostState.PUBLISHED)
    response = client.put(f"/api/recordings/{rid}/draft",
                          json={"revision": 0, "changes": {"title": "x"}})
    assert response.status_code == 409


def test_the_layout_setting_chooses_what_a_new_draft_starts_as(db, service, rid):
    db.set_setting("post_layout", "track_log")
    assert service.get_draft(rid)["blocks"] == LAYOUT_TRACK_LOG
    db.set_setting("post_layout", "something else")
    assert service.get_draft(rid)["blocks"] == LAYOUT_SHIP_LOG


def test_a_recording_with_no_draft_publishes_as_a_ships_log(db, service, rid, monkeypatch):
    db.add_image(rid, __file__, ImageType.USER_UPLOAD, "a photo")
    db.update_recording(rid, description="Out to Pt Walter")
    wp = WordPressPublisher("http://wp.invalid", "u", "p")
    sent = {}
    monkeypatch.setattr(wp, "test_connection", lambda: (True, "ok"))
    monkeypatch.setattr(wp, "upload_media", lambda path, caption=None, upload_name=None:
                        {"id": 7, "url": "https://wp/a.jpg"})
    monkeypatch.setattr(wp, "create_post", lambda **kw: sent.update(kw) or
                        {"id": 1, "link": "https://wp/?p=1", "status": "publish",
                         "modified_gmt": "t"})
    service.wordpress_publisher = wp

    service.publish(rid, auto_publish=True)

    assert "Track Summary" not in sent["content"]
    assert "<p>Out to Pt Walter</p>" in sent["content"]


def test_the_preview_is_a_page_drawn_from_files_on_the_pi(client, db, rid, tmp_path):
    plot = tmp_path / "plots" / str(rid) / "route_map_0.png"
    plot.parent.mkdir(parents=True)
    plot.write_bytes(b"png")
    db.add_image(rid, str(plot), ImageType.PLOT, "Route Map")

    page = client.get(f"/preview?id={rid}&layout=ship_log")

    assert page.status_code == 200
    text = page.get_data(as_text=True)
    assert f'src="plots/{rid}/route_map_0.png"' in text
    assert "home page shows only what is above this line" in text
    assert client.get(f"/preview?id={rid}&layout=nope").status_code == 400


def test_publishing_sends_the_drafts_title_excerpt_categories_and_blocks(
        db, service, rid, monkeypatch, perth):
    db.add_image(rid, __file__, ImageType.USER_UPLOAD, "a photo")
    service.save_draft(rid, {"title": "Twilight with Ed", "excerpt": "Short and sweet",
                             "categories": ["Ship's Log", "Twilight"], "crew": ["Ed", "Steve"],
                             "blocks": LAYOUT_SHIP_LOG}, 0)

    wp = WordPressPublisher("http://wp.invalid", "u", "p")
    sent = {}
    monkeypatch.setattr(wp, "test_connection", lambda: (True, "ok"))
    monkeypatch.setattr(wp, "upload_media", lambda path, caption=None, upload_name=None:
                        {"id": 7, "url": "https://wp/a.jpg", "large_url": "https://wp/a-1024.jpg"})
    monkeypatch.setattr(wp, "create_post", lambda **kw: sent.update(kw) or
                        {"id": 1, "link": "https://wp/?p=1", "status": "publish",
                         "modified_gmt": "t"})
    service.wordpress_publisher = wp

    service.publish(rid, auto_publish=True)

    assert sent["title"] == "Twilight with Ed"
    assert sent["excerpt"] == "Short and sweet"
    assert sent["categories"] == ["Ship's Log", "Twilight"]
    assert re.findall(r"<p>(.*?)</p>", sent["content"])[0] == "Ed, Steve"
    # The large size, not the full-size file: the publisher once dropped
    # large_url between uploading and rendering, and only the class was checked
    assert '<img src="https://wp/a-1024.jpg" alt="a photo" class="wp-image-7"/>' in sent["content"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
