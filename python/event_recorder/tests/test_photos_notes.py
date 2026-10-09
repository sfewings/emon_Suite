"""FR-29: photo and note capture from the event page.

Run in the dev container (dev/README.md):
    python -m pytest event_recorder/tests/test_photos_notes.py
"""

import io
import json
import re
import threading
from datetime import datetime, timedelta

import pytest
from PIL import Image

from event_recorder import photos
from event_recorder.models import Artefacts, Database, ImageType, PostState, RecordingStatus
from event_recorder.post_renderer import LAYOUT_SHIP_LOG, PostContext, render
from event_recorder.recording_service import RecordingService
from event_recorder.web_interface import WebInterface


def _jpeg(width=3000, height=2000, taken="2026:10:09 17:42:10", orientation=None, offset=None):
    """A camera JPEG: landscape pixels, with the EXIF a phone writes."""
    image = Image.new("RGB", (width, height), (40, 90, 160))
    exif = Image.Exif()
    detail = {}
    if taken:
        detail[36867] = taken
    if offset:
        detail[36881] = offset
    if orientation:
        exif[274] = orientation
    if detail:
        exif[0x8769] = detail
    out = io.BytesIO()
    image.save(out, "JPEG", exif=exif.tobytes())
    return out.getvalue()


# === photos.prepare ===

def test_a_phone_photo_gets_a_web_copy_and_a_thumbnail_the_right_way_up(tmp_path):
    original = tmp_path / "IMG_0164.jpg"
    original.write_bytes(_jpeg(orientation=6))      # held upright: stored on its side

    prepared = photos.prepare(original)

    assert original.exists(), "the original is kept"
    with Image.open(prepared["web"]) as web:
        assert web.size == (1365, 2048), "portrait, at most 2048 px"
    with Image.open(prepared["thumb"]) as thumb:
        assert max(thumb.size) == 400 and thumb.size[1] > thumb.size[0]


def test_the_time_a_photo_was_taken_is_read_as_perth_time(tmp_path):
    original = tmp_path / "a.jpg"
    original.write_bytes(_jpeg(taken="2026:10:09 17:42:10"))
    assert photos.prepare(original)["taken_at"] == datetime(2026, 10, 9, 9, 42, 10)


def test_a_photo_that_says_its_own_offset_is_read_with_it(tmp_path):
    original = tmp_path / "a.jpg"
    original.write_bytes(_jpeg(taken="2026:10:09 17:42:10", offset="+10:00"))
    assert photos.prepare(original)["taken_at"] == datetime(2026, 10, 9, 7, 42, 10)


def test_a_photo_that_cannot_be_read_is_kept_as_it_came(tmp_path):
    original = tmp_path / "IMG_0001.heic"
    original.write_bytes(b"not a picture Pillow knows")
    assert photos.prepare(original) == {"web": original, "thumb": None, "taken_at": None}


def test_a_screenshot_png_with_transparency_becomes_a_jpeg(tmp_path):
    original = tmp_path / "screen.png"
    Image.new("RGBA", (473, 1024), (0, 0, 0, 0)).save(original)
    prepared = photos.prepare(original)
    with Image.open(prepared["web"]) as web:
        assert web.format == "JPEG" and web.size == (473, 1024)


# === The event page's routes ===

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
    rid = db.create_recording("Sunday race", event_key="anchor_track_recording")
    db.update_recording(rid, status=RecordingStatus.STOPPED, artefacts=Artefacts.FRESH)
    return rid


def _upload(client, rid, data, name="IMG_0164.jpg"):
    return client.post(f"/log/api/photos/{rid}", data={"file": (io.BytesIO(data), name)},
                       content_type="multipart/form-data")


def test_uploading_a_photo_keeps_it_with_its_time_and_a_thumbnail(client, db, rid):
    response = _upload(client, rid, _jpeg())
    assert response.status_code == 200, response.get_json()

    image = db.get_image(response.get_json()["image_id"])
    assert image["image_type"] == ImageType.USER_UPLOAD
    assert image["image_path"].endswith("_web.jpg")
    assert str(image["taken_at"]).startswith("2026-10-09 09:42:10")

    photo = client.get(f"/log/api/state?id={rid}").get_json()["photos"][0]
    assert re.match(rf"uploads/{rid}/thumbs/.+\.jpg$", photo["thumb_url"])
    assert client.get(f"/log/{photo['thumb_url']}").status_code == 200


def test_what_is_not_a_photo_is_refused(client, rid):
    assert _upload(client, rid, b"#!/bin/sh", name="script.sh").status_code == 400


def test_a_photo_without_exif_is_placed_when_it_arrived(client, db, rid):
    before = datetime.utcnow() - timedelta(seconds=1)
    image_id = _upload(client, rid, _jpeg(taken=None)).get_json()["image_id"]
    assert datetime.fromisoformat(str(db.get_image(image_id)["taken_at"])) >= before


def test_a_caption_can_be_given_and_a_photo_removed_with_its_files(client, db, rid, tmp_path):
    image_id = _upload(client, rid, _jpeg()).get_json()["image_id"]
    assert client.put(f"/log/api/photos/{rid}/{image_id}", json={"caption": "Kite up"}).status_code == 200
    assert db.get_image(image_id)["caption"] == "Kite up"

    assert client.delete(f"/log/api/photos/{rid}/{image_id}").status_code == 200
    assert db.get_image(image_id) is None
    leftovers = [p for p in (tmp_path / "uploads" / str(rid)).rglob("*") if p.is_file()]
    assert leftovers == []


def test_once_published_photos_cannot_be_added_or_changed(client, db, rid):
    image_id = _upload(client, rid, _jpeg()).get_json()["image_id"]
    db.set_post_state(rid, PostState.PUBLISHED)
    assert _upload(client, rid, _jpeg()).status_code == 409
    assert client.delete(f"/log/api/photos/{rid}/{image_id}").status_code == 409


def _fix(db, rid, when, lat, lon):
    db.add_messages_batch([(rid, when, "gps/position/0",
                            json.dumps({"lat": lat, "lon": lon, "ts": 0}))])


def test_a_note_is_placed_where_the_boat_was_when_it_was_opened(client, db, rid):
    opened = datetime(2026, 10, 9, 9, 30, 0)
    _fix(db, rid, opened - timedelta(seconds=40), -32.0001, 115.8001)
    _fix(db, rid, opened + timedelta(seconds=5), -32.0050, 115.8050)    # the nearest

    response = client.post(f"/log/api/notes/{rid}",
                           json={"text": "Dolphins at the bridge", "ts": "2026-10-09T09:30:00.000Z"})

    note = response.get_json()["note"]
    assert (note["ts"], note["lat"], note["lon"]) == ("2026-10-09T09:30:00Z", -32.005, 115.805)
    assert client.get(f"/log/api/state?id={rid}").get_json()["draft"]["notes"] == [note]


def test_a_note_far_from_any_fix_has_no_position(client, db, rid):
    _fix(db, rid, datetime(2026, 10, 9, 8, 0, 0), -32.0, 115.8)
    note = client.post(f"/log/api/notes/{rid}", json={
        "text": "Kite up", "ts": "2026-10-09T09:30:00Z"}).get_json()["note"]
    assert note["lat"] is None and note["lon"] is None


@pytest.mark.parametrize("text", ["", "   ", "x" * 501])
def test_a_note_is_some_words_on_one_line(client, rid, text):
    assert client.post(f"/log/api/notes/{rid}", json={"text": text}).status_code == 400


def test_notes_are_kept_in_the_order_they_happened(client, rid):
    for ts, text in (("2026-10-09T09:40:00Z", "second"), ("2026-10-09T09:10:00Z", "first")):
        client.post(f"/log/api/notes/{rid}", json={"text": text, "ts": ts})
    notes = client.get(f"/log/api/state?id={rid}").get_json()["draft"]["notes"]
    assert [n["text"] for n in notes] == ["first", "second"]


def test_notes_added_from_two_devices_at_once_are_both_kept(client, rid):
    threads = [threading.Thread(target=client.post, args=(f"/log/api/notes/{rid}",),
                                kwargs={"json": {"text": f"note {i}"}}) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    notes = client.get(f"/log/api/state?id={rid}").get_json()["draft"]["notes"]
    assert sorted(n["text"] for n in notes) == [f"note {i}" for i in range(6)]


def test_the_post_tells_photos_and_notes_in_the_order_they_happened():
    media = [{"url": "kite.jpg", "image_type": "user_upload", "path": "/u/kite.jpg",
              "caption": "", "taken_at": "2026-10-09 09:20:00"},
             {"url": "sunset.jpg", "image_type": "user_upload", "path": "/u/sunset.jpg",
              "caption": "", "taken_at": "2026-10-09 10:45:00"}]
    notes = [{"ts": "2026-10-09T09:05:00Z", "text": "Left the mooring"},
             {"ts": "2026-10-09T09:50:00Z", "text": "Dolphins at the bridge"}]
    ctx = PostContext({"start_time": "2026-10-09 09:00:00", "end_time": "2026-10-09 11:00:00"},
                      media=media, draft={"notes": notes})

    above = render(LAYOUT_SHIP_LOG, ctx).split("<!--more-->")[0]
    order = [above.index(s) for s in ("Left the mooring", "kite.jpg",
                                      "Dolphins at the bridge", "sunset.jpg")]
    assert order == sorted(order)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
