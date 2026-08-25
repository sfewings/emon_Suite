"""The pre-start countdown audio: the files, and the page's scheduling of them.

What can go wrong here is not subtle but it is silent, which is worse. A missing clip, a
codec iOS will not decode, or a horn offset that no longer matches what the page schedules
against, and the first anyone knows is a start with no gun. None of it shows up on a
laptop, because a laptop plays anything.

So the files are checked structurally, without ffmpeg, the way wake.mp4 is: the Pi has
neither ffmpeg nor a sound card, and this has to be checkable there and in CI.

Bare asserts and no fixtures, so this runs under pytest and also standalone with
`python tests/test_audio.py`.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # for standalone runs

import app as app_module  # noqa: E402
from store import Store  # noqa: E402

AUDIO = ROOT / "static" / "audio"
MINUTES = list(range(1, 11))


def _manifest():
    return json.loads((AUDIO / "manifest.json").read_text(encoding="utf-8"))


def _script():
    return (ROOT / "static" / "app.js").read_text(encoding="utf-8")


def test_there_is_a_clip_for_every_minute_and_one_for_the_last_ten_seconds():
    """Ten hooter minutes plus the final recording. The timer offers T-10, T-5 and T-1,
    so every minute from ten down can be the one being counted."""
    for minute in MINUTES:
        path = AUDIO / ("min-%d.m4a" % minute)
        assert path.exists(), path.name
        assert path.stat().st_size > 500, "%s is too small to be audio" % path.name
    final = AUDIO / "final.m4a"
    assert final.exists()
    assert final.stat().st_size > 10_000, "the final countdown should be the long one"


def test_the_clips_are_aac_in_an_mp4_container():
    """The same reasoning as wake.mp4: it is what iOS will play without argument, and it
    fails silently rather than loudly when it is wrong."""
    for path in sorted(AUDIO.glob("*.m4a")):
        head = path.read_bytes()[:4096]
        assert b"ftyp" in head, "%s is not an MP4 container" % path.name
        assert b"mp4a" in head, "%s carries no AAC track" % path.name
        assert b"avc1" not in head, "%s has a video track it does not need" % path.name


def test_the_horn_offset_the_page_schedules_against_is_the_one_in_the_file():
    """The contract between scripts/gen_audio.py and static/app.js.

    The page starts final.m4a at T-0 minus this many seconds. If the file is regenerated
    with the horn somewhere else and this is not changed with it, every start is early or
    late by the difference, and nothing else in the app would notice.
    """
    horn_at = _manifest()["horn_at"]
    assert horn_at == 10.0, horn_at

    in_page = re.search(r'var HORN_AT = ([\d.]+);', _script())
    assert in_page, "HORN_AT not found in app.js"
    assert float(in_page.group(1)) == horn_at

    # and the generator's own constant, so all three move together
    generator = (ROOT / "scripts" / "gen_audio.py").read_text(encoding="utf-8")
    in_generator = re.search(r'^HORN_AT = ([\d.]+)$', generator, re.M)
    assert in_generator and float(in_generator.group(1)) == horn_at


def test_the_final_recording_is_long_enough_to_hold_the_countdown_and_the_horn():
    manifest = _manifest()
    # ten numbers on the second, then a horn that has to be audible for a moment
    assert manifest["final_seconds"] > manifest["horn_at"] + 0.5, manifest["final_seconds"]
    assert len(manifest["countdown"]) == 10, sorted(manifest["countdown"])
    for index, word in enumerate(["ten", "nine", "eight", "seven", "six", "five",
                                  "four", "three", "two", "one"]):
        piece = manifest["countdown"][word]
        assert piece["at"] == float(index), (word, piece)
        # each number has to finish inside its own second or it talks over the next
        assert piece["seconds"] < 1.0, (word, piece["seconds"])


def test_the_minute_clips_say_the_minute_and_say_it_singular_at_one():
    minutes = _manifest()["minutes"]
    for minute in MINUTES:
        said = minutes[str(minute)]["say"]
        assert said.lower().startswith(
            ["one", "two", "three", "four", "five",
             "six", "seven", "eight", "nine", "ten"][minute - 1]), said
    assert minutes["1"]["say"] == "One minute", "one minute is singular"
    assert minutes["2"]["say"] == "Two minutes"


def test_the_page_schedules_the_clips_rather_than_triggering_them():
    """The point of the whole arrangement: a 2 Hz poll cannot place a gun to the second.

    Triggering on the poll would put T-0 up to half a second out, which on a start line
    is a boat length. So the page hands each clip to the audio clock with a start time,
    and starts the final recording part-way in when it is already due.
    """
    script = _script()
    assert "source.start(when, offset)" in script, "clips must be scheduled with a time"
    assert "offset = now - when" in script, "a late start must seek into the clip"
    assert "deadline - cue.at" in script
    # and it must not reschedule on jitter, which would restart a playing clip
    assert re.search(r'Math\.abs\(deadline - planned\) > REPLAN_S', script)


def test_the_horn_is_not_cut_off_by_the_race_starting():
    """T-0 is both the horn and the moment the mode becomes racing.

    Stopping the scheduled audio whenever the countdown ends would silence the gun at the
    instant it is supposed to sound, which is the one cue nobody can miss.
    """
    script = _script()
    guard = re.search(r'if \(mode !== "racing"\) silence\(\);', script)
    assert guard, "racing must be excluded from the silence path"
    # a reset, though, has to stop it
    assert "function silence()" in script


def test_the_clips_are_served_and_addressed_relative_to_the_page():
    """An absolute path breaks behind the /race/ prefix (CLAUDE.md)."""
    script = _script()
    assert 'base + "/static/audio/" + cue.key + ".m4a"' in script
    assert '"/static/audio' not in script.replace('base + "/static/audio', "")

    store = Store()
    flask_app = app_module.create_app(store)
    flask_app.config["TESTING"] = True
    client = flask_app.test_client()
    for name in ["final.m4a"] + ["min-%d.m4a" % m for m in MINUTES]:
        response = client.get("/static/audio/" + name)
        assert response.status_code == 200, name
        assert len(response.get_data()) > 500, name
        # And with a Content-Type a browser will take. This is the assertion that was
        # missing, and its absence cost a silent countdown on the water.
        #
        # Python's mimetypes has no built-in entry for .m4a and looks for one in
        # /etc/mime.types, which python:3.13-slim does not ship. So the clips went out as
        # application/octet-stream from the container while the dev machine, whose
        # mimetypes reads the Windows registry, was serving audio/mp4. Chromium decodes
        # the same bytes either way, which is why only the boat's phones noticed.
        # app.py registers the type; this holds it there.
        assert response.mimetype == "audio/mp4", \
            "%s served as %s, which Safari may refuse" % (name, response.mimetype)

    # The assertion above is not enough on its own, and finding that out is the point of
    # this paragraph. It passes on any machine whose mimetypes already knows .m4a, which
    # is the Windows dev box and the Pi's own Python, both of which have a mime database.
    # It only fails where the bug lives, inside the slim container, and that is the one
    # place nobody runs the suite. Removing the registration from app.py and re-running
    # here still passed.
    #
    # So the registration is asserted in the source as well. Crude, and it is what makes
    # this test mean "does not depend on the host having a mime database" rather than
    # "happens to work on my machine".
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'mimetypes.add_type("audio/mp4", ".m4a")' in source, \
        "app.py must register .m4a itself: python:3.13-slim ships no /etc/mime.types, " \
        "so without this the clips go out as application/octet-stream"


def test_the_audio_context_is_taken_prefixed_as_well():
    """iOS Safari had no unprefixed AudioContext until 14.5.

    Every browser on iOS is WebKit underneath, so this is not a Safari-only concern: it
    is every browser on an older iPhone, and on the boat's iOS 12 iPad. Without the
    prefixed name the context is never created, and loadVoice, beep and updateAudio all
    guard on it, so the page goes completely silent rather than falling back to the tone.
    That is the whole of a "no audio on the phone, audio on the desktop" report.
    """
    script = _script()
    assert "window.webkitAudioContext" in script, \
        "no prefixed AudioContext fallback: every browser on an older iOS goes silent"
    # And the constructor actually used has to be the one that was resolved, not the
    # unprefixed global again.
    assert re.search(r"window\.AudioContext\s*\|\|\s*window\.webkitAudioContext", script), \
        "the two names must be resolved together"
    assert "new AudioContext(" not in script, \
        "constructing the unprefixed name directly defeats the fallback"


def test_a_missing_clip_falls_back_to_a_tone_rather_than_silence():
    """Whatever goes wrong with a file or a codec, the gun still has to make a noise."""
    script = _script()
    assert "if (!voiceReady) { maybeBeep(); return; }" in script
    assert "function beep(" in script


def test_the_whole_set_is_small_enough_to_serve_off_the_pi():
    total = sum(p.stat().st_size for p in AUDIO.glob("*.m4a"))
    assert total < 1_000_000, "%d bytes of audio is more than this needs" % total


if __name__ == "__main__":
    import traceback

    failures = 0
    for test_name, test in sorted(globals().items()):
        if not test_name.startswith("test_") or not callable(test):
            continue
        try:
            test()
        except Exception:
            failures += 1
            print("FAIL  " + test_name)
            traceback.print_exc()
        else:
            print("ok    " + test_name)
    print("%d failed" % failures if failures else "all passed")
    raise SystemExit(1 if failures else 0)
