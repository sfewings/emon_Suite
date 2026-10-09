"""FR-27: the event page at /log.

Run in the dev container (dev/README.md):
    python -m pytest event_recorder/tests/test_event_page.py

The page's own script is checked for iOS 12 by test_ios12_floor.py. These cover what it
talks to: the state it is shown, the per-field saves, publishing, and the preview and
files it links to, all under /log so the page works at /race/log/ unchanged.
"""

import threading
import time
from datetime import datetime, timedelta

import pytest

from event_recorder.models import Artefacts, Database, ImageType, PostState, RecordingStatus
from event_recorder.recording_service import RecordingService
from event_recorder.web_interface import WebInterface

EVENTS = {"anchor_track_recording": {"editor_default": True}, "track_recording": {}}


class QuietWordPress:
    """Enough of a publisher for the publish route, remembering what it was asked."""

    def __init__(self):
        self.calls = []

    def test_connection(self):
        return True, "ok"

    def publish_recording(self, **kwargs):
        self.calls.append(kwargs)
        return {"id": 9, "link": "http://localhost:8080/?p=9",
                "status": "publish" if kwargs["auto_publish"] else "draft",
                "modified_gmt": "t", "failed_uploads": []}


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "rec.db"))


@pytest.fixture
def wp():
    return QuietWordPress()


@pytest.fixture
def service(db, wp, tmp_path):
    return RecordingService(db, plots_dir=str(tmp_path / "plots"),
                            uploads_dir=str(tmp_path / "uploads"),
                            wordpress_publisher=wp, event_configs=lambda: EVENTS)


@pytest.fixture
def client(db, service, tmp_path):
    return WebInterface(database=db, plots_dir=str(tmp_path / "plots"),
                        uploads_dir=str(tmp_path / "uploads"),
                        recording_service=service).app.test_client()


def _recording(db, key, status=RecordingStatus.STOPPED, hours_ago=1, **fields):
    rid = db.create_recording(f"{key} - 2026-10-09 17:30:00", event_key=key)
    start = datetime.utcnow() - timedelta(hours=hours_ago)
    db.update_recording(rid, status=status, start_time=start,
                        end_time=None if status == RecordingStatus.ACTIVE else start + timedelta(hours=1),
                        **fields)
    return rid


def _state(client, rid=None):
    return client.get("/log/api/state" + (f"?id={rid}" if rid else "")).get_json()


def _save(client, rid, **changes):
    return client.put(f"/log/api/draft/{rid}", json={"changes": changes})


def test_the_page_and_its_assets_are_served_under_log(client):
    page = client.get("/log/")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    # All relative, so the page works at /race/log/ and /events/log/ alike
    assert 'href="assets/log.css"' in html and 'src="assets/log.js"' in html
    assert client.get("/log/assets/log.js").status_code == 200


def test_with_nothing_recorded_the_page_says_so(client):
    body = _state(client)
    assert body["success"] and body["recording"] is None


def test_the_page_opens_the_outings_anchor_recording(client, db):
    anchor = _recording(db, "anchor_track_recording", status=RecordingStatus.ACTIVE, hours_ago=2)
    track = _recording(db, "track_recording", status=RecordingStatus.ACTIVE)

    body = _state(client)

    assert body["recording"]["id"] == anchor
    assert [c["id"] for c in body["candidates"]] == [anchor, track]
    # Recording, so no publishing yet, and the time runs to now
    assert body["can_publish"] is False
    assert body["elapsed_seconds"] >= 2 * 3600 - 5
    assert "-" in body["time_line"]


def test_an_id_opens_that_recording_and_it_joins_the_switcher(client, db):
    old = _recording(db, "track_recording", hours_ago=24 * 30)
    _recording(db, "anchor_track_recording")

    body = _state(client, old)

    assert body["recording"]["id"] == old
    assert old in [c["id"] for c in body["candidates"]]


def test_two_devices_editing_different_fields_keep_both(client, db):
    rid = _recording(db, "anchor_track_recording")

    _save(client, rid, title="Twilight with Ed")          # the phone
    draft = _save(client, rid, story="Out to Pt Walter.").get_json()["draft"]   # the iPad

    assert (draft["title"], draft["story"]) == ("Twilight with Ed", "Out to Pt Walter.")
    assert draft["field_revisions"] == {"title": 1, "story": 2}


def test_two_devices_editing_one_field_keep_the_later(client, db):
    rid = _recording(db, "anchor_track_recording")
    _save(client, rid, title="Phone")
    draft = _save(client, rid, title="iPad").get_json()["draft"]

    assert draft["title"] == "iPad"
    # The phone saved at revision 1 and now sees 2: it was overtaken, and shows its text
    assert draft["field_revisions"]["title"] == 2


def test_the_first_save_keeps_the_rest_of_the_new_draft(client, db):
    rid = _recording(db, "anchor_track_recording", description="Course 3")
    draft = _save(client, rid, crew=["Henry", "Steve"]).get_json()["draft"]

    assert draft["stored"] is True
    assert draft["excerpt"] == "Course 3" and draft["crew"] == ["Henry", "Steve"]
    assert draft["blocks"][0] == {"type": "log_lines"}


def test_saves_at_the_same_moment_all_land(client, db):
    rid = _recording(db, "anchor_track_recording")
    fields = ["title", "wind", "excerpt", "story"]
    threads = [threading.Thread(target=_save, args=(client, rid), kwargs={f: f.upper()})
               for f in fields]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    draft = _state(client, rid)["draft"]
    assert [draft[f] for f in fields] == ["TITLE", "WIND", "EXCERPT", "STORY"]
    assert sorted(draft["field_revisions"].values()) == [1, 2, 3, 4]


def test_once_wordpress_has_the_post_the_page_cannot_change_it(client, db):
    rid = _recording(db, "anchor_track_recording")
    db.set_post_state(rid, PostState.WP_DRAFT)
    assert _save(client, rid, title="x").status_code == 409
    assert _state(client, rid)["can_publish"] is False


def test_crew_are_suggested_from_earlier_drafts_most_sailed_first(client, db):
    for crew in (["Henry", "Steve"], ["Steve", "Ed"], ["Steve"]):
        _save(client, _recording(db, "anchor_track_recording"), crew=crew)
    assert _state(client)["crew_suggestions"] == ["Steve", "Ed", "Henry"]


def _wait_for_job(client, rid):
    for _ in range(100):
        job = _state(client, rid)["publish_job"]
        if job and job["state"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("publish never finished")


def test_publishing_from_the_page_draws_the_charts_first_when_needed(
        client, db, service, wp, tmp_path, monkeypatch):
    rid = _recording(db, "anchor_track_recording")
    photo = tmp_path / "kite.jpg"
    photo.write_bytes(b"jpg")
    db.add_image(rid, str(photo), ImageType.USER_UPLOAD, "")
    drawn = []

    def process(recording_id, *args):
        drawn.append(recording_id)
        db.update_recording(recording_id, artefacts=Artefacts.FRESH)
        return {"status": "success"}
    monkeypatch.setattr(service, "process", process)

    assert client.post(f"/log/api/publish/{rid}", json={}).status_code == 202
    job = _wait_for_job(client, rid)

    assert job["state"] == "done", job
    assert drawn == [rid]
    assert wp.calls[0]["blocks"][0] == {"type": "log_lines"}


def test_send_as_a_wordpress_draft(client, db, wp, tmp_path):
    rid = _recording(db, "anchor_track_recording", artefacts=Artefacts.FRESH)
    photo = tmp_path / "kite.jpg"
    photo.write_bytes(b"jpg")
    db.add_image(rid, str(photo), ImageType.USER_UPLOAD, "")

    client.post(f"/log/api/publish/{rid}", json={"draft": True})
    _wait_for_job(client, rid)

    assert wp.calls[0]["auto_publish"] is False
    assert db.get_recording(rid)["post_state"] == PostState.WP_DRAFT


def test_the_preview_and_its_images_work_under_log(client, db, tmp_path):
    rid = _recording(db, "anchor_track_recording", artefacts=Artefacts.FRESH)
    plot = tmp_path / "plots" / str(rid) / "route_map_0.png"
    plot.parent.mkdir(parents=True)
    plot.write_bytes(b"png")
    db.add_image(rid, str(plot), ImageType.PLOT, "Route Map")

    page = client.get(f"/log/preview?id={rid}").get_data(as_text=True)
    assert f'src="plots/{rid}/route_map_0.png"' in page
    # ...which, from /log/preview, is /log/plots/...
    assert client.get(f"/log/plots/{rid}/route_map_0.png").data == b"png"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
