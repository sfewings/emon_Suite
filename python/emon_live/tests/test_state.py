"""state.py with injected messages and a fake clock. No broker, no Flask."""

import json

from conftest import CAPTURED_AT, retained_messages
from state import LiveState, Site, handle_message, page_feeds, state_document

from pyemonlib import emon_feed


def envelope(group, name, v, t, u="W", node="pulse", sub=0, field="power", idx=0):
    return emon_feed.envelope_json(emon_feed.Reading(
        node=node, sub=sub, field=field, value=v, unit=u, kind="power", idx=idx,
        group=group, name=name, t=t))


def test_the_retained_capture_fills_the_store_by_name(state):
    for topic, payload in retained_messages():
        assert handle_message(state, topic, payload), topic
    doc = state_document(state)
    feeds = doc["feeds"]
    assert feeds["Power board / Consumed"] == {"v": 618.0, "u": "W", "age": 5.4}
    assert feeds["Hot water system / Inlet (T6)"]["u"] == "degC"
    assert not any(name.startswith("emon/") for name in feeds), "every envelope carries names"
    assert state.catalogue.duplicates == {}, "no two topics share a name (DESIGN 5)"
    assert state.config["file"] and "pulse" in state.config["settings"]


def test_age_counts_from_the_bridge_time_not_arrival(state, clock):
    handle_message(state, "emon/pulse/0/power/2", envelope("Power board", "Consumed", 500, t=CAPTURED_AT - 30))
    assert state_document(state)["feeds"]["Power board / Consumed"]["age"] == 30.0
    clock.now += 60
    assert state_document(state)["feeds"]["Power board / Consumed"]["age"] == 90.0


def test_a_bridge_clock_slightly_ahead_gives_age_zero_not_negative(state):
    handle_message(state, "emon/pulse/0/power/2", envelope("Power board", "Consumed", 1, t=CAPTURED_AT + 2))
    assert state_document(state)["feeds"]["Power board / Consumed"]["age"] == 0.0


def test_a_newer_reading_replaces_the_older(state):
    handle_message(state, "emon/pulse/0/power/2", envelope("Power board", "Consumed", 1, t=CAPTURED_AT - 9))
    handle_message(state, "emon/pulse/0/power/2", envelope("Power board", "Consumed", 2, t=CAPTURED_AT - 1))
    assert state_document(state)["feeds"]["Power board / Consumed"]["v"] == 2


def test_the_document_is_limited_to_the_feeds_asked_for(state):
    for topic, payload in retained_messages():
        handle_message(state, topic, payload)
    doc = state_document(state, {"Power board / Consumed", "Nonexistent / feed"})
    assert list(doc["feeds"]) == ["Power board / Consumed"], "a feed never seen is left out"


def test_junk_is_dropped_without_raising(state):
    assert not handle_message(state, "emon/pulse/0/power/2", b"\xff\xfe")
    assert not handle_message(state, "emon/pulse/0/power/2", "{not json")
    assert not handle_message(state, "emon/config", "[1, 2]")
    assert not handle_message(state, "emon/config", b"\xff")
    assert len(state.store) == 0 and state.config is None


def test_legacy_number_is_kept_by_topic(state):
    """Feeds outside emon are named by their raw topic (DESIGN 5)."""
    assert handle_message(state, "ecowitt/tempf", "71.2")
    assert state_document(state)["feeds"]["ecowitt/tempf"]["v"] == 71.2


def test_theme_is_server_state_and_ignores_nonsense():
    state = LiveState(theme="night")
    assert state.theme == "night"
    assert state.set_theme("day") == "day"
    assert state.set_theme("purple") == "day"
    assert state_document(state)["theme"] == "day"
    assert LiveState(theme="purple").theme == "day"


def test_page_feeds_finds_feed_keys_and_placeholders():
    page = {"tiles": [
        {"hero": [{"feed": "Hot water system / Water (T3)", "label": "Tank"},
                  {"feed": "derived/hws/showersRemaining"}],
         "gauge": {"feed": "derived/hws/showersRemaining", "max": 27},
         "line": "Today {derived/hws/showers} showers · {derived/hws/showerMinutes} min"},
        {"title": "No feeds here {}"},
    ]}
    assert page_feeds([page]) == {
        "Hot water system / Water (T3)", "derived/hws/showersRemaining",
        "derived/hws/showers", "derived/hws/showerMinutes"}


def test_site_rereads_pages_when_a_file_changes(tmp_path):
    (tmp_path / "pages").mkdir()
    (tmp_path / "site.json").write_text(json.dumps({"title": "Home", "theme": "night"}))
    page = tmp_path / "pages" / "house.json"
    page.write_text(json.dumps({"tiles": [{"feed": "A / a"}]}))
    site = Site(tmp_path)
    assert site.site["title"] == "Home" and site.feeds == {"A / a"}

    page.write_text(json.dumps({"tiles": [{"feed": "B / b"}]}))
    _touch_forward(page)
    site.refresh()
    assert site.feeds == {"B / b"}

    page.write_text("{half saved")
    _touch_forward(page)
    site.refresh()
    assert site.feeds == {"B / b"}, "a file that does not parse keeps the last good version"

    page.unlink()
    site.refresh()
    assert site.pages == {} and site.feeds == set()


def test_no_site_folder_is_not_an_error():
    site = Site(None)
    assert site.site == {} and site.pages == {} and site.feeds == set()


def _touch_forward(path):
    """Coarse filesystem timestamps can leave a rewrite with the same mtime."""
    import os
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
