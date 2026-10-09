"""TR-11: publishing runs in the background and updates its own post.

Run in the dev container (dev/README.md):
    python -m pytest event_recorder/tests/test_publish.py

Against a fake WordPress. The real one is in the dev rig's wordpress profile, and the
end-to-end check against it is in the requirements doc's TR-11 notes.
"""

import sqlite3
import threading
import time

import pytest

from event_recorder.models import Artefacts, Database, ImageType, PostState, RecordingStatus
from event_recorder.recording_service import RecordingError, RecordingService
from event_recorder.web_interface import WebInterface


class FakeWordPress:
    """Posts in a dict, each with a modified_gmt that changes on every write."""

    def __init__(self):
        self.posts = {}
        self.next_id = 100
        self.clock = 0
        self.check_fails = False
        self.gate = None          # a threading.Event to hold publish_recording on

    def _stamp(self):
        self.clock += 1
        return "2026-10-09T00:00:%02d" % self.clock

    def test_connection(self):
        return True, "ok"

    def get_post(self, post_id):
        if self.check_fails:
            raise ConnectionError("hotspot dropped")
        post = self.posts.get(post_id)
        return dict(post) if post else None

    def publish_recording(self, recording_data, images, exports=None, statistics=None,
                          map_htmls=None, template=None, category="Track Logs",
                          auto_publish=False, post_id=None, progress=None):
        if self.gate:
            self.gate.wait(5)
        for i in range(len(images)):
            if progress:
                progress("Uploading %d of %d" % (i + 1, len(images)), i, len(images))
        if post_id is None:
            post_id = self.next_id
            self.next_id += 1
        self.posts[post_id] = {
            "id": post_id,
            "title": recording_data["name"],
            "link": "http://localhost:8080/?p=%d" % post_id,
            "status": "publish" if auto_publish else "draft",
            "modified_gmt": self._stamp(),
        }
        return dict(self.posts[post_id])

    def find_post_by_link(self, link):
        if self.check_fails:
            raise ConnectionError("hotspot dropped")
        return next((dict(p) for p in self.posts.values() if p["link"] == link), None)

    def edit_in_wp_admin(self, post_id):
        self.posts[post_id]["modified_gmt"] = self._stamp()


@pytest.fixture
def wp():
    return FakeWordPress()


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "rec.db"))


@pytest.fixture
def service(db, wp, tmp_path):
    return RecordingService(db, plots_dir=str(tmp_path / "plots"),
                            uploads_dir=str(tmp_path / "uploads"),
                            wordpress_publisher=wp)


@pytest.fixture
def rid(db, tmp_path):
    """A processed recording with one plot on disk, which is all publish needs."""
    rid = db.create_recording("Sunday race")
    db.update_recording(rid, status=RecordingStatus.STOPPED, artefacts=Artefacts.FRESH)
    plot = tmp_path / "speed.png"
    plot.write_bytes(b"png")
    db.add_image(rid, str(plot), ImageType.PLOT, "Speed")
    return rid


def test_the_first_publish_creates_a_post_and_remembers_it(service, db, wp, rid):
    post = service.publish(rid)

    assert list(wp.posts) == [post["id"]]
    ref = db.get_post_draft(rid)
    assert ref["wp_post_id"] == post["id"]
    assert ref["wp_modified"] == wp.posts[post["id"]]["modified_gmt"]
    rec = db.get_recording(rid)
    # No publish_status configured here, so it goes out as a WordPress draft,
    # which WordPress owns as much as a live post (Q5)
    assert rec["post_state"] == PostState.WP_DRAFT and rec["stage"] == "published"
    # The recording's own state is untouched by publishing (TR-12)
    assert rec["status"] == RecordingStatus.STOPPED


def test_publishing_again_updates_the_same_post(service, db, wp, rid):
    first = service.publish(rid)

    second = service.publish(rid)

    assert second["id"] == first["id"]
    assert len(wp.posts) == 1, "a second post was created"
    assert db.get_post_draft(rid)["wp_modified"] == wp.posts[first["id"]]["modified_gmt"]


def test_a_post_edited_in_wp_admin_is_not_overwritten(service, db, wp, rid):
    post = service.publish(rid)
    wp.edit_in_wp_admin(post["id"])
    edited = dict(wp.posts[post["id"]])

    with pytest.raises(RecordingError) as refused:
        service.publish(rid)

    assert refused.value.status == 409
    assert "edited in WordPress" in str(refused.value)
    assert wp.posts[post["id"]] == edited
    # A refusal leaves the post's state as it was
    assert db.get_recording(rid)["post_state"] == PostState.WP_DRAFT


def test_a_post_deleted_in_wordpress_is_published_afresh(service, db, wp, rid):
    old = service.publish(rid)
    del wp.posts[old["id"]]

    new = service.publish(rid)

    assert new["id"] != old["id"]
    assert db.get_post_draft(rid)["wp_post_id"] == new["id"]


def test_not_being_able_to_check_the_post_never_makes_a_second_one(service, wp, rid):
    service.publish(rid)
    wp.check_fails = True

    with pytest.raises(RecordingError) as refused:
        service.publish(rid)

    assert refused.value.status == 503
    assert len(wp.posts) == 1


def _published_before_tr11(db, wp, rid):
    """A recording published by the old code: a link, but no post_drafts row."""
    wp.posts[7] = {"id": 7, "title": "Track Log", "link": "http://localhost:8080/?p=7",
                   "status": "publish", "modified_gmt": "2026-03-01T00:00:00"}
    db.update_recording(rid, wordpress_url="http://localhost:8080/?p=7")


def test_a_recording_published_before_tr11_is_not_published_twice(service, db, wp, rid):
    _published_before_tr11(db, wp, rid)

    with pytest.raises(RecordingError) as refused:
        service.publish(rid)

    assert refused.value.status == 409
    assert "before the recorder kept track" in str(refused.value)
    assert list(wp.posts) == [7]


def test_once_that_old_post_is_deleted_the_recording_publishes_afresh(service, db, wp, rid):
    _published_before_tr11(db, wp, rid)
    del wp.posts[7]

    post = service.publish(rid)

    assert db.get_post_draft(rid)["wp_post_id"] == post["id"]


def _wait_for(service, rid, state, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = service.publish_job(rid)
        if job and job["state"] == state:
            return job
        time.sleep(0.02)
    raise AssertionError("job never reached %s: %s" % (state, service.publish_job(rid)))


def test_publishing_runs_in_the_background_and_reports_progress(service, wp, rid):
    wp.gate = threading.Event()
    steps = []
    original = wp.publish_recording

    def watched(*args, **kwargs):
        progress = kwargs["progress"]
        kwargs["progress"] = lambda s, d, t: (steps.append(s), progress(s, d, t))
        return original(*args, **kwargs)
    wp.publish_recording = watched

    job = service.start_publish(rid)
    assert job["state"] == "running"

    with pytest.raises(RecordingError) as refused:
        service.start_publish(rid)
    assert refused.value.status == 409

    wp.gate.set()
    done = _wait_for(service, rid, "done")
    assert done["post"]["id"] in wp.posts
    assert done["finished_at"]
    assert steps == ["Uploading 1 of 1"]


def test_a_failed_publish_is_reported_on_the_job(service, wp, rid):
    service.publish(rid)
    wp.edit_in_wp_admin(next(iter(wp.posts)))

    service.start_publish(rid)
    job = _wait_for(service, rid, "failed")

    assert job["status"] == 409
    assert "edited in WordPress" in job["error"]


def test_the_routes_start_and_report_the_job(db, service, wp, rid, tmp_path):
    client = WebInterface(database=db, plots_dir=str(tmp_path / "plots"),
                          uploads_dir=str(tmp_path / "uploads"),
                          recording_service=service).app.test_client()

    assert client.get(f"/api/recordings/{rid}/publish").status_code == 404

    started = client.post(f"/api/recordings/{rid}/publish", json={})
    assert started.status_code == 202
    assert started.get_json()["job"]["state"] in ("running", "done")

    _wait_for(service, rid, "done")
    report = client.get(f"/api/recordings/{rid}/publish").get_json()
    assert report["job"]["post"]["link"].startswith("http://localhost:8080/")


def test_without_wordpress_publishing_is_refused_at_once(db, tmp_path, rid):
    service = RecordingService(db, plots_dir=str(tmp_path / "plots"))
    with pytest.raises(RecordingError) as refused:
        service.start_publish(rid)
    assert refused.value.status == 400
    assert service.publish_job(rid) is None


def test_deleting_a_recording_removes_its_post_reference(service, db, rid, tmp_path):
    service.publish(rid)

    service.delete(rid)

    conn = sqlite3.connect(tmp_path / "rec.db")
    assert conn.execute("SELECT COUNT(*) FROM post_drafts").fetchone()[0] == 0
    conn.close()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
