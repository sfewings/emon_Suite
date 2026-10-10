"""Publish when the recording stops, and Event Recorder from the racing app.

Run in the dev container (dev/README.md):
    python -m pytest event_recorder/tests/test_publish_on_stop.py
"""

import time

import pytest

from event_recorder.models import Artefacts, Database, ImageType, PostState, RecordingStatus
from event_recorder.recording_service import RecordingError, RecordingService
from event_recorder.web_interface import WebInterface


class WordPress:
    """Publishes, or is out of reach while `reachable` is False."""

    def __init__(self):
        self.reachable = True
        self.calls = []

    def test_connection(self):
        return self.reachable, "ok" if self.reachable else "Name or service not known"

    def get_post(self, post_id):
        return None

    def find_post_by_link(self, link):
        return None

    def publish_recording(self, **kwargs):
        self.calls.append(kwargs)
        return {"id": 9, "link": "http://wp/?p=9", "modified_gmt": "t",
                "status": "publish" if kwargs["auto_publish"] else "draft"}


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "rec.db"))


@pytest.fixture
def wp():
    return WordPress()


@pytest.fixture
def service(db, wp, tmp_path):
    # publish_status as on the boat: "Publish" puts the post live
    return RecordingService(db, plots_dir=str(tmp_path / "plots"),
                            uploads_dir=str(tmp_path / "uploads"), wordpress_publisher=wp,
                            wordpress_config=lambda: {"publish_status": "publish"})


@pytest.fixture
def rid(service, db, tmp_path):
    rid = service.start("Sunday race", topics=["gps/#"])
    db.update_recording(rid, artefacts=Artefacts.FRESH)     # charts drawn: publish does not
    photo = tmp_path / "kite.jpg"
    photo.write_bytes(b"jpg")
    db.add_image(rid, str(photo), ImageType.USER_UPLOAD, "")
    return rid


def _settled(service, rid):
    for _ in range(100):
        job = service.publish_job(rid)
        if job and job["state"] != "running":
            return job
        time.sleep(0.03)
    raise AssertionError("publish never finished")


def test_asking_while_recording_publishes_when_it_stops(service, db, wp, rid):
    assert service.set_publish_on_stop(rid, "publish") == "publish"
    assert wp.calls == []

    service.stop(rid)

    assert _settled(service, rid)["state"] == "done"
    assert wp.calls[0]["auto_publish"] is True
    assert db.publish_on_stop(rid) is None, "settled, so no longer asked"


def test_as_a_wordpress_draft(service, db, wp, rid):
    service.set_publish_on_stop(rid, "draft")
    service.stop(rid)
    _settled(service, rid)
    assert wp.calls[0]["auto_publish"] is False
    assert db.get_recording(rid)["post_state"] == PostState.WP_DRAFT


def test_asking_can_be_taken_back(service, wp, rid):
    service.set_publish_on_stop(rid, "publish")
    service.set_publish_on_stop(rid, None)
    service.stop(rid)
    time.sleep(0.1)
    assert wp.calls == [] and service.publish_job(rid) is None


def test_it_publishes_at_once_if_it_stopped_meanwhile(service, wp, rid):
    service.stop(rid)
    service.set_publish_on_stop(rid, "publish")
    assert _settled(service, rid)["state"] == "done"


def test_out_of_reach_when_it_stops_it_waits_and_tries_again(service, db, wp, rid):
    wp.reachable = False
    service.set_publish_on_stop(rid, "publish")
    service.stop(rid)

    job = _settled(service, rid)
    assert (job["state"], job["status"]) == ("failed", 503)
    assert db.publish_on_stop(rid) == "publish", "still asked"

    service.publish_pending()                 # too soon: not tried again yet
    assert service.publish_job(rid)["state"] == "failed"

    wp.reachable = True
    service._pending_tries[rid] -= service.PENDING_RETRY_SECONDS + 1
    service.publish_pending()

    assert _settled(service, rid)["state"] == "done"
    assert db.publish_on_stop(rid) is None


def test_stopping_with_publishing_asked_does_not_also_auto_process(service, db, rid, monkeypatch):
    db.set_setting("auto_process_on_stop", "true")
    drawn = []
    monkeypatch.setattr(service, "process_in_background", lambda r: drawn.append(r))
    service.set_publish_on_stop(rid, "publish")

    assert service.stop(rid) is False
    _settled(service, rid)
    assert drawn == []


@pytest.mark.parametrize("prepare, status", [
    (lambda service, db, rid: db.set_post_state(rid, PostState.PUBLISHED), 409),
    (lambda service, db, rid: setattr(service, "wordpress_publisher", None), 400),
])
def test_it_cannot_be_asked_when_it_could_not_happen(service, db, rid, prepare, status):
    prepare(service, db, rid)
    with pytest.raises(RecordingError) as refused:
        service.set_publish_on_stop(rid, "publish")
    assert refused.value.status == status


def test_the_page_can_ask_and_is_told(db, service, rid, tmp_path):
    client = WebInterface(database=db, plots_dir=str(tmp_path / "plots"),
                          uploads_dir=str(tmp_path / "uploads"),
                          recording_service=service).app.test_client()

    assert client.post(f"/log/api/publish_on_stop/{rid}", json={"mode": "draft"}).status_code == 200
    assert client.get(f"/log/api/state?id={rid}").get_json()["publish_on_stop"] == "draft"
    assert client.post(f"/log/api/publish_on_stop/{rid}", json={"mode": "whenever"}).status_code == 400

    page = client.get("/log/").get_data(as_text=True)
    assert 'id="publish-cancel"' in page
    # Event Recorder from the racing app opens outside the Home Screen app
    assert '<a id="recorder-link" target="_blank" rel="noopener">' in page
    # ...where the dashboard's tools include Stop
    assert 'id="admin-stop"' in page


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
