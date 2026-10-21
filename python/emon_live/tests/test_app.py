"""The Flask routes, through Flask's test client. No broker."""

import gzip
import json

import pytest

from conftest import retained_messages
from app import create_app
from state import Site, handle_message


@pytest.fixture
def site_dir(tmp_path):
    (tmp_path / "pages").mkdir()
    (tmp_path / "site.json").write_text(json.dumps({"title": "Home", "theme": "night"}))
    (tmp_path / "pages" / "house.json").write_text(json.dumps(
        {"tiles": [{"feed": "Power board / Consumed"}, {"line": "{Power board / Imported} W in"}]}))
    return tmp_path


@pytest.fixture
def client(state, site_dir, tmp_path_factory):
    ui = tmp_path_factory.mktemp("ui")
    (ui / "index.html").write_text("<!doctype html><title>emon</title>")
    for topic, payload in retained_messages():
        handle_message(state, topic, payload)
    return create_app(state, Site(site_dir), ui).test_client()


def test_state_has_only_the_feeds_the_pages_use(client):
    doc = client.get("/api/state").get_json()
    assert set(doc["feeds"]) == {"Power board / Consumed", "Power board / Imported"}
    assert doc["theme"] == "day"   # the LiveState's; app.main takes it from site.json


def test_state_all_has_every_feed(client):
    doc = client.get("/api/state?all=1").get_json()
    assert len(doc["feeds"]) > 100


def test_state_is_gzipped_when_asked_and_large_enough(client):
    r = client.get("/api/state?all=1", headers={"Accept-Encoding": "gzip, deflate"})
    assert r.headers["Content-Encoding"] == "gzip"
    assert len(json.loads(gzip.decompress(r.data))["feeds"]) > 100
    assert r.headers["Cache-Control"] == "no-store"
    small = client.get("/api/state", headers={"Accept-Encoding": "gzip"})
    assert "Content-Encoding" not in small.headers, "two feeds are not worth compressing"


def test_theme_post_changes_what_every_poll_sees(client):
    assert client.post("/api/settings", json={"theme": "night"}).get_json() == {"theme": "night"}
    assert client.get("/api/state").get_json()["theme"] == "night"
    assert client.post("/api/settings", json={"theme": "x"}).get_json() == {"theme": "night"}
    assert client.post("/api/settings", data="not json").get_json() == {"theme": "night"}


def test_feeds_and_config(client):
    feeds = client.get("/api/feeds").get_json()
    assert "Power board / Consumed" in feeds["feeds"] and feeds["duplicates"] == {}
    assert "pulse" in client.get("/api/config").get_json()["settings"]


def test_site_and_ui_files_are_served_and_contained(client):
    assert client.get("/site/site.json").get_json()["title"] == "Home"
    assert client.get("/site/pages/house.json").status_code == 200
    assert client.get("/site/../site.json").status_code == 404
    assert client.get("/site/%2e%2e/%2e%2e/etc/passwd").status_code == 404
    assert b"<title>emon</title>" in client.get("/").data
    assert client.get("/nothing.js").status_code == 404


def test_without_a_site_folder_state_returns_everything(state):
    for topic, payload in retained_messages():
        handle_message(state, topic, payload)
    client = create_app(state, Site(None), None).test_client()
    assert len(client.get("/api/state").get_json()["feeds"]) > 100
    assert client.get("/site/site.json").status_code == 404
    assert client.get("/").status_code == 404
