"""Unit tests for engine/course.py, and the CI check over the shipped course data.

Two halves. The first runs engine/course.py over the real config/ documents, which is
what DESIGN 7 means by the reconciliation check running in CI over every course: a
course sheet transcribed next season with a leg out of order fails here rather than
on the water. The second half is synthetic and checks that each rule actually fires,
because a validator that returns an empty list is indistinguishable from one that
works until the day it matters.

The file reading lives here on purpose. engine/ holds no I/O, so the tests do the
loading and hand parsed documents in, exactly as app.py will.

Bare asserts and no fixtures, so this runs under pytest and also standalone with
`python tests/test_courses.py` on a Pi that has no pytest.
"""

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # for standalone runs

from engine import course, nav  # noqa: E402

MARKS = json.loads((ROOT / "config" / "marks.json").read_text(encoding="utf-8"))
LINES = json.loads((ROOT / "config" / "lines.json").read_text(encoding="utf-8"))
COURSES = json.loads((ROOT / "config" / "courses.json").read_text(encoding="utf-8"))

PROBLEMS = course.validate(MARKS, COURSES, LINES)
INDEX = course.index_marks(MARKS)

# Courses whose legs do not sum to the printed distance. Pinned rather than silenced, so
# that a *new* mismatch fails the build while these do not. Every one has been read back
# off the sheet and the parse checked leg by leg; what is in doubt is which side is wrong,
# and DESIGN 7 keeps that open.
#
#   frostbite-1        +2.1%  no single substitution or deletion from its twenty course
#                             marks lands within 1 per cent of the printed figure
#   sunday-div-ii-2    +2.8%
#   sunday-div-iv-1    -9.9%  the largest, and the parse is not the suspect: legs 1-9 are
#                             identical to sunday-div-iii-1, which reconciles to +0.3%, and
#                             the divergent tail is four ordinary legs with nothing degenerate
#                             about them. Its printed shortened figure does not resolve either.
#   sunday-div-iv-2    +4.2%
#   twilight-1         +2.6%
#   twilight-3         -2.6%
#   parmelia-1        -28.3%   and parmelia-2 -23.3%, which are a different kind of
#                              mismatch from the six above and are explained rather than
#                              open. The club prints the distance sailed. Those six are
#                              open-water courses where the straight line between two marks
#                              is the route, so summing them reproduces the printed figure;
#                              the night race threads Blackwall Reach, rounds the Point
#                              Walter spit and crosses the Claremont shallows, and a boat
#                              cannot sail those straight lines.
#                              scripts/navigable_distance.py measures the route around land,
#                              water under 2 m and a standoff from every spit mark: 14.81
#                              and 13.80 nm, so -15.4% and -8.0%, while leaving these
#                              twenty-three at a mean 3.3% against 3.4% for straight lines.
#                              So the warning here is the expected result for a course of
#                              that shape and not a transcription fault. See DESIGN 7.1 and
#                              test_the_parmelia_gap_is_still_the_size_it_was below.
KNOWN_DISTANCE_MISMATCHES = {
    "frostbite-1", "sunday-div-ii-2", "sunday-div-iv-1", "sunday-div-iv-2",
    "twilight-1", "twilight-3",
    "parmelia-1", "parmelia-2",
}


# --- the shipped config ----------------------------------------------------


def test_shipped_config_has_no_errors():
    found = course.errors(PROBLEMS)
    assert found == [], "\n".join(str(p) for p in found)


def test_the_only_distance_mismatch_is_the_known_one():
    mismatched = {p.course for p in PROBLEMS if p.code == "distance-mismatch"}
    assert mismatched == KNOWN_DISTANCE_MISMATCHES, mismatched


def test_the_known_mismatch_is_still_the_size_it_was():
    """If someone re-reads the sheet and fixes it, this test is the reminder to unpin."""
    c = _course("frostbite-1")
    summed = course.course_distance_nm(c, INDEX, LINES)
    error_pct = (summed - c["distance_nm"]) / c["distance_nm"] * 100.0
    assert 2.0 < error_pct < 3.0, error_pct


def test_the_parmelia_gap_is_still_the_size_it_was():
    """The same reminder for the night race, whose gap is an order larger and is a
    property of the course rather than of the transcription: the club prints the distance
    sailed, and this course cannot be sailed in straight lines. See DESIGN 7.1 and
    scripts/navigable_distance.py, which measures the difference.

    Pinned in both directions. If it shrinks, someone has restated the printed distance or
    corrected a leg, and the note on both courses needs rewriting to match. If it grows, a
    mark has moved or a leg has been edited.
    """
    for course_id, low, high in (("parmelia-1", -30.0, -26.0),
                                 ("parmelia-2", -25.0, -21.0)):
        c = _course(course_id)
        summed = course.course_distance_nm(c, INDEX, LINES)
        error_pct = (summed - c["distance_nm"]) / c["distance_nm"] * 100.0
        assert low < error_pct < high, (course_id, summed, c["distance_nm"], error_pct)


# Legs whose rounding differs from the register, as (course, leg index). Every one is on
# the Parmelia night race and every one has a reason:
#
#   blackwall-11, crawley-45   the instructions change both from the register's standard
#                              port rounding to starboard, in writing, for this race only.
#                              That sentence is also what confirms those two mark ids.
#   knot-spit-14, concrete-spit-15, foam-18, armstrong-spit-36
#                              fixed river navigation marks, not club racing buoys. The
#                              instructions require those to be passed on the deep-water
#                              side, which is the opposite hand depending on whether the
#                              leg runs up or down the river, and marks.json holds one
#                              standard rounding per mark and cannot express that.
#
# Pinned as an exact set rather than filtered by series, so a rounding that flips on any
# other course, or a new one appearing on these, still fails.
KNOWN_ROUNDING_MISMATCHES = {
    ("parmelia-1", 2), ("parmelia-1", 10), ("parmelia-1", 11),
    ("parmelia-1", 12), ("parmelia-1", 13),
    ("parmelia-2", 2), ("parmelia-2", 6), ("parmelia-2", 10),
    ("parmelia-2", 11), ("parmelia-2", 12), ("parmelia-2", 13),
}


def test_the_only_rounding_mismatches_are_the_documented_ones():
    """The register agreed with the fixtures sheets on all twenty marks, so the only
    mismatches are the Parmelia ones above, each for a stated reason."""
    found = {(p.course, p.leg) for p in PROBLEMS if p.code == "rounding-mismatch"}
    assert found == KNOWN_ROUNDING_MISMATCHES, (
        "unexpected: %s\nmissing: %s"
        % (sorted(found - KNOWN_ROUNDING_MISMATCHES),
           sorted(KNOWN_ROUNDING_MISMATCHES - found)))


def test_no_fixtures_course_has_a_rounding_mismatch():
    """The narrower claim the old test made, kept as its own assertion: everything read out
    of the fixtures book still agrees with the register, mark for mark."""
    found = [p for p in PROBLEMS
             if p.code == "rounding-mismatch" and not str(p.course).startswith("parmelia")]
    assert found == [], "\n".join(str(p) for p in found)


def test_the_other_three_courses_reconcile():
    """Within 1.5 per cent, where they were once within 0.1.

    The tolerance loosened when mark positions were redigitized in QGIS, and that is the
    expected direction. The club's printed distances were computed from the September 2019
    register, so agreement with them measured "same coordinates the club used", not
    accuracy. Now that the marks have moved by a median of 15 m the printed figures no
    longer match to a hundredth, and the recorded GPS track says the new positions are the
    better ones: closest approach to each rounding fell from a median of 21 m to 5 m.

    So this stays a transcription check, which is what DESIGN 7 asks of it. A leg in the
    wrong order or a missing leg still shows up here. It is no longer a precision check on
    the coordinates, because it is no longer measured against the better source.
    """
    for course_id in ("frostbite-2", "frostbite-3", "frostbite-4"):
        c = _course(course_id)
        summed = course.course_distance_nm(c, INDEX, LINES)
        error_pct = (summed - c["distance_nm"]) / c["distance_nm"] * 100.0
        assert abs(error_pct) < 1.5, (course_id, summed, c["distance_nm"], error_pct)


def test_frostbite_has_four_courses_with_the_four_pendants():
    frostbite = [c for c in COURSES["courses"] if c["series"] == "frostbite"]
    assert len(frostbite) == 4
    assert [c["course_no"] for c in frostbite] == [1, 2, 3, 4]
    assert [c["flags"]["numeral"] for c in frostbite] == [
        "pendant-1", "pendant-2", "pendant-3", "pendant-4"]


def test_every_leg_targets_exactly_one_mark_and_the_finish_is_last():
    for c in COURSES["courses"]:
        for i, leg in enumerate(c["legs"][:-1]):
            assert "mark" in leg and not course.is_finish(leg), (c["id"], i)
            assert leg["mark"] in INDEX, (c["id"], i, leg["mark"])
        last = c["legs"][-1]
        assert course.is_finish(last) and "mark" not in last, c["id"]
        assert last["line"] == LINES["start_finish"]["id"], c["id"]


def test_no_gates_anywhere():
    """The model that DESIGN 6 now records as wrong must not creep back in."""
    assert "gates" not in LINES
    assert {line["id"] for line in LINES["no_cross_lines"]} == {"bricklanding", "smith-lucky-bay"}
    for c in COURSES["courses"]:
        for leg in c["legs"]:
            assert "gate" not in leg and "marks" not in leg, (c["id"], leg)


def test_mosman_has_no_line():
    """Nothing prohibits crossing between 14 and 13, so there is nothing to detect."""
    for line in LINES["no_cross_lines"]:
        assert "mosman-a-14" not in line["marks"], line["id"]
        assert "mosman-b-13" not in line["marks"], line["id"]


# The one course in the whole document that never returns to the line before finishing,
# and so the one where a naive finish test would happen to be right. It is also the only
# Sunday course with no printed shortened distance, which is the same fact from the other
# side: there is no line crossing to shorten it at.
NO_MID_RACE_LINE = {"sunday-div-iii-2"}


def test_club_32a_is_both_a_course_mark_and_the_finish():
    """The hazard the whole finish-detection design exists for (DESIGN 11.5).

    Nearly every course rounds club-32a while racing and finishes on the line it forms
    the outer end of, so a naive finish test fires mid-race in 22 of the 23.
    """
    outer = LINES["start_finish"]["outer"]["mark"]
    assert outer == "club-32a"
    exposed = set()
    for c in COURSES["courses"]:
        assert course.is_finish(c["legs"][-1]), c["id"]
        if any(leg.get("mark") == outer for leg in c["legs"]):
            exposed.add(c["id"])

    everything = {c["id"] for c in COURSES["courses"]}
    assert everything - exposed == NO_MID_RACE_LINE, everything - exposed
    # and it is the overwhelming majority, which is why the arming rule exists at all
    assert len(exposed) >= len(everything) - 1


def test_a_shortened_course_ends_at_a_crossing_of_the_line():
    """Flag S means the next pass through the line ends the race (DESIGN 11.6).

    So a resolved `shortened_at` has to point at a leg that returns to the line, never
    at a mark out in the river. Solving it by nearest running total alone does exactly
    that when the arithmetic is a little off, which is how this was first got wrong.
    """
    outer = LINES["start_finish"]["outer"]["mark"]
    resolved = 0
    for c in COURSES["courses"]:
        at = c.get("shortened_at")
        if at is None:
            continue
        resolved += 1
        assert 0 <= at < len(c["legs"]), (c["id"], at)
        leg = c["legs"][at]
        assert leg.get("mark") == outer or leg.get("finish"), (c["id"], at, leg)
        # and it has to be a shortening, not the whole course
        assert at < len(c["legs"]) - 1, (c["id"], at)
    assert resolved >= 8, "the Sunday sheets print a shortened figure for most courses"


def test_every_printed_shortened_distance_is_recorded_even_when_unresolved():
    """A figure that could not be tied to a leg is still data, and saying so is the point."""
    for c in COURSES["courses"]:
        if "shortened_distance_nm" not in c:
            continue
        assert c["shortened_distance_nm"] < c["distance_nm"], c["id"]
        assert "shortened_note" in c, c["id"]
        if c.get("shortened_at") is None:
            assert "not resolved" in c["shortened_note"] or "no leg" in c["shortened_note"], \
                c["shortened_note"]


# --- the Parmelia night race ----------------------------------------------------------
#
# The mark sequence exactly as page 6 and page 7 of the sailing instructions print it, top
# to bottom. This is the transcription itself, written out a second time and independently
# of config/courses.json, so an edit to the data that does not match the sheet fails here.
# Bricklanding A and B are two rows on the sheet and two legs, never one gate (DESIGN 6).
PARMELIA_SHEET = [
    ("bricklanding-a-33a", "starboard"),
    ("bricklanding-b-33b", "starboard"),
    ("blackwall-11", "starboard"),
    ("burnside-spit-58", "starboard"),
    ("cyc-start-outer-21a", "starboard"),
    ("point-resolution-port-beacon", "port"),
    (None, None),                              # the one leg that differs by division
    ("club-32a", "starboard"),
    ("outer-dolphin-17", "port"),
    ("inner-dolphin-16", "port"),
    ("crawley-45", "starboard"),
    ("knot-spit-14", "port"),
    ("concrete-spit-15", "port"),
    ("foam-18", "port"),
    ("heathcote-spit-22", "starboard"),
    ("sopyc-start-outer", "starboard"),
]

PARMELIA_PIVOT = {"parmelia-1": ("squadron-37", "port"),
                  "parmelia-2": ("armstrong-spit-36", "port")}


def test_the_parmelia_courses_match_the_sailing_instructions():
    for course_id, pivot in PARMELIA_PIVOT.items():
        legs = _course(course_id)["legs"]
        expected = [pivot if m is None else (m, r) for m, r in PARMELIA_SHEET]
        got = [(leg.get("mark"), leg.get("rounding")) for leg in legs[:-1]]
        assert got == expected, (course_id, got)
        # and one finish leg on the end, targeting the line rather than a mark
        assert legs[-1].get("finish") is True and legs[-1].get("mark") is None, course_id


def test_the_two_parmelia_courses_differ_by_exactly_one_mark():
    """Division III and IV turn at Armstrong Spit where I and II carry on to Squadron. That
    single substitution is the whole difference between the two sheets."""
    one = [(l.get("mark"), l.get("rounding")) for l in _course("parmelia-1")["legs"]]
    two = [(l.get("mark"), l.get("rounding")) for l in _course("parmelia-2")["legs"]]
    assert len(one) == len(two)
    differ = [i for i, (a, b) in enumerate(zip(one, two)) if a != b]
    assert differ == [6], differ
    assert one[6] == ("squadron-37", "port")
    assert two[6] == ("armstrong-spit-36", "port")


def test_bricklanding_is_two_legs_on_the_night_race_too():
    """The sheet prints "BRICKLANDING A & B (33A, 33B)" on one row with one rounding, which
    is exactly the wording that produced the gate model DESIGN 6 threw out."""
    for course_id in PARMELIA_PIVOT:
        legs = _course(course_id)["legs"]
        assert legs[0]["mark"] == "bricklanding-a-33a"
        assert legs[1]["mark"] == "bricklanding-b-33b"
        for leg in legs:
            assert "gate" not in leg and "marks" not in leg, course_id


def test_the_parmelia_shortening_point_is_a_pass_of_the_line():
    """The instructions shorten at the first passing of the PFSYC outer start mark, not at a
    distance. Only a leg that returns to the line is a candidate (DESIGN 11.6), and that
    mark is the outer end of the line itself."""
    for course_id in PARMELIA_PIVOT:
        c = _course(course_id)
        at = c["shortened_at"]
        assert c["legs"][at]["mark"] == "club-32a", (course_id, at)
        # No printed shortened distance exists, so the key must be absent rather than null:
        # a null would claim the sheet printed a figure that could not be resolved.
        assert "shortened_distance_nm" not in c, course_id
        assert "shortened_note" in c, course_id


def test_the_parmelia_finish_is_westerly():
    """The instructions require the line to be crossed in a westerly direction. Independent
    of the leg list: it falls out of where the last mark is, so it checks the geometry."""
    for course_id in PARMELIA_PIVOT:
        legs = course.leg_table(_course(course_id), INDEX, LINES)
        bearing = legs[-1]["bearing"]
        assert 225.0 < bearing < 315.0, (course_id, bearing)


def test_the_parmelia_open_question_is_recorded_in_the_data():
    """POINT RESOLUTION SPIT has no entry in the SRRC register and is read as the DoT lit
    port beacon off Point Resolution. That is an inference, and the note is where it is
    admitted; this test is what stops the admission being quietly dropped."""
    for course_id in PARMELIA_PIVOT:
        note = _course(course_id)["note"]
        assert "POINT RESOLUTION SPIT" in note, course_id
        assert "point-resolution-port-beacon" in note, course_id
        assert "inference" in note.lower(), course_id


def test_the_parmelia_series_carries_both_starts_and_their_flags():
    series = COURSES["series"]["parmelia"]
    starts = {tuple(s["divisions"]): (s["time"], s["flag"]) for s in series["starts"]}
    assert starts[("III",)] == ("18:50", "naval-3")
    assert starts[("IV",)] == ("18:50", "naval-4")
    assert starts[("I",)] == ("19:00", "naval-1")
    assert starts[("II",)] == ("19:00", "naval-2")
    assert series["time_limit"] == "6h"
    assert "seven" in series["time_limit_note"]


def test_the_parmelia_courses_are_not_produced_by_the_extractor():
    """They come from their own instructions document, so extract_courses.py must carry them
    through rather than rebuild them. It keys that on the series, so the series must not be
    one the extractor owns."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "extract_courses", ROOT / "scripts" / "extract_courses.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert "parmelia" not in module.SERIES
    for course_id in PARMELIA_PIVOT:
        assert _course(course_id)["series"] == "parmelia"


def test_rounding_is_taken_from_the_leg_not_the_mark():
    """Course 2 rounds club-32a to starboard on one pass and to port on another."""
    legs = _course("frostbite-2")["legs"]
    sides = {leg["rounding"] for leg in legs if leg.get("mark") == "club-32a"}
    assert sides == {"port", "starboard"}, sides
    assert INDEX["club-32a"]["rounding"] is None  # a start mark, so nothing to inherit


def test_leg_names_are_the_display_names():
    """The crew calls it Squadron, not 37 and not squadron-37 (DESIGN 9.2)."""
    legs = _course("frostbite-3")["legs"]
    names = [course.leg_name(leg, INDEX) for leg in legs]
    assert names[4] == "Squadron", names
    assert names[5] == "Hallmark", names
    assert names[-1] == "Finish", names


def test_leg_target_of_the_finish_is_the_middle_of_the_line():
    inner, outer = course.start_line(LINES)
    target = course.leg_target(_course("frostbite-1")["legs"][-1], INDEX, LINES)
    assert nav.distance_m(target, nav.midpoint(inner, outer)) < 0.001
    half = nav.distance_m(inner, outer) / 2.0
    assert abs(nav.distance_m(inner, target) - half) < 0.001


def test_leg_distances_line_up_with_the_total():
    for c in COURSES["courses"]:
        legs = course.leg_distances_nm(c, INDEX, LINES)
        cumulative = course.cumulative_distances_nm(c, INDEX, LINES)
        assert len(legs) == len(c["legs"]) == len(cumulative)
        assert all(d > 0 for d in legs), c["id"]
        assert all(cumulative[i] < cumulative[i + 1] for i in range(len(cumulative) - 1))
        assert abs(cumulative[-1] - course.course_distance_nm(c, INDEX, LINES)) < 1e-9


def test_first_leg_is_measured_from_the_start_line():
    """Not from the inner mark and not from club-32a (DESIGN 7)."""
    c = _course("frostbite-4")
    first = course.leg_distances_nm(c, INDEX, LINES)[0]
    expected = nav.distance_nm(course.start_point(LINES), nav.as_latlon(INDEX["miller-28"]))
    assert abs(first - expected) < 1e-9


# --- the rules actually fire ----------------------------------------------


def _course(course_id):
    for c in COURSES["courses"]:
        if c["id"] == course_id:
            return c
    raise AssertionError("no course %r in config/courses.json" % course_id)


def _fixture():
    """A minimal, self-consistent set of three documents.

    Its printed distance is computed rather than hardcoded, so the fixture validates
    clean and each test below can introduce exactly one fault.
    """
    marks_doc = {
        "marks": [
            {"id": "alpha", "number": "1", "name": "Alpha", "lat": -32.0000, "lon": 115.8000,
             "rounding": "port"},
            {"id": "bravo", "number": "2", "name": "Bravo", "lat": -32.0100, "lon": 115.8100,
             "rounding": "starboard"},
            {"id": "outer", "number": "3", "name": "Outer", "lat": -32.0028, "lon": 115.8128,
             "rounding": None},
        ]
    }
    lines_doc = {
        "start_finish": {
            "id": "test-line",
            "inner": {"lat": -32.0019, "lon": 115.8120},
            "outer": {"mark": "outer", "lat": -32.0028, "lon": 115.8128},
        },
        "no_cross_lines": [{"id": "pair", "marks": ["alpha", "bravo"]}],
    }
    legs = [
        {"mark": "alpha", "rounding": "port"},
        {"mark": "bravo", "rounding": "starboard"},
        {"finish": True, "line": "test-line", "rounding": "port"},
    ]
    courses_doc = {
        "series": {"test": {"name": "Test series"}},
        "courses": [{
            "id": "test-1", "series": "test", "course_no": 1,
            "distance_nm": 0.0, "wind_note": "", "flags": {"numeral": "pendant-1"},
            "shortened_at": None, "legs": legs,
        }],
    }
    c = courses_doc["courses"][0]
    c["distance_nm"] = round(course.course_distance_nm(c, course.index_marks(marks_doc), lines_doc), 3)
    return marks_doc, courses_doc, lines_doc


def _codes(marks_doc, courses_doc, lines_doc, **kw):
    return [p.code for p in course.validate(marks_doc, courses_doc, lines_doc, **kw)]


def test_the_fixture_itself_is_clean():
    assert _codes(*_fixture()) == []


def test_a_gate_leg_is_rejected():
    """Both spellings of the old model, on a leg and in lines.json."""
    marks_doc, courses_doc, lines_doc = _fixture()
    courses_doc["courses"][0]["legs"][0] = {
        "marks": ["alpha", "bravo"], "rounding": "port", "gate": "pair"}
    codes = _codes(marks_doc, courses_doc, lines_doc)
    assert codes.count("gates-removed") == 2, codes
    assert "leg-shape" in codes  # and it no longer names a single mark

    marks_doc, courses_doc, lines_doc = _fixture()
    lines_doc["gates"] = lines_doc.pop("no_cross_lines")
    assert "gates-removed" in _codes(marks_doc, courses_doc, lines_doc)


def test_an_unknown_mark_id_is_an_error():
    marks_doc, courses_doc, lines_doc = _fixture()
    courses_doc["courses"][0]["legs"][0]["mark"] = "charlie"
    assert "unknown-mark" in _codes(marks_doc, courses_doc, lines_doc)

    marks_doc, courses_doc, lines_doc = _fixture()
    lines_doc["no_cross_lines"][0]["marks"] = ["alpha", "charlie"]
    assert "unknown-mark" in _codes(marks_doc, courses_doc, lines_doc)


def test_a_missing_or_misplaced_finish_is_an_error():
    marks_doc, courses_doc, lines_doc = _fixture()
    courses_doc["courses"][0]["legs"].pop()
    assert "no-finish" in _codes(marks_doc, courses_doc, lines_doc)

    marks_doc, courses_doc, lines_doc = _fixture()
    legs = courses_doc["courses"][0]["legs"]
    legs.insert(0, legs.pop())
    assert "finish-not-last" in _codes(marks_doc, courses_doc, lines_doc)

    marks_doc, courses_doc, lines_doc = _fixture()
    legs = courses_doc["courses"][0]["legs"]
    legs.append(copy.deepcopy(legs[-1]))
    assert "many-finishes" in _codes(marks_doc, courses_doc, lines_doc)


def test_a_finish_leg_pointing_at_the_wrong_line_is_an_error():
    marks_doc, courses_doc, lines_doc = _fixture()
    courses_doc["courses"][0]["legs"][-1]["line"] = "some-other-line"
    assert "unknown-line" in _codes(marks_doc, courses_doc, lines_doc)


def test_a_leg_with_no_target_is_an_error():
    marks_doc, courses_doc, lines_doc = _fixture()
    del courses_doc["courses"][0]["legs"][0]["mark"]
    assert "leg-shape" in _codes(marks_doc, courses_doc, lines_doc)


def test_bad_rounding_is_an_error():
    marks_doc, courses_doc, lines_doc = _fixture()
    courses_doc["courses"][0]["legs"][0]["rounding"] = "left"
    assert "bad-rounding" in _codes(marks_doc, courses_doc, lines_doc)

    marks_doc, courses_doc, lines_doc = _fixture()
    del courses_doc["courses"][0]["legs"][1]["rounding"]
    assert "bad-rounding" in _codes(marks_doc, courses_doc, lines_doc)


def test_a_rounding_that_contradicts_the_register_is_a_warning_not_an_error():
    """The sheet is authoritative; disagreeing with the register is a smell, not a stop."""
    marks_doc, courses_doc, lines_doc = _fixture()
    courses_doc["courses"][0]["legs"][0]["rounding"] = "starboard"  # alpha is registered port
    problems = course.validate(marks_doc, courses_doc, lines_doc)
    assert [p.code for p in problems if p.severity == course.WARNING] == ["rounding-mismatch"]
    assert course.errors(problems) == []


def test_a_distance_that_does_not_reconcile_is_a_warning_not_an_error():
    marks_doc, courses_doc, lines_doc = _fixture()
    courses_doc["courses"][0]["distance_nm"] *= 1.5
    problems = course.validate(marks_doc, courses_doc, lines_doc)
    assert [p.code for p in problems] == ["distance-mismatch"]
    assert course.warnings(problems) == problems


def test_the_distance_tolerance_is_adjustable():
    marks_doc, courses_doc, lines_doc = _fixture()
    courses_doc["courses"][0]["distance_nm"] *= 1.01  # 1 per cent out
    assert _codes(marks_doc, courses_doc, lines_doc) == []  # inside the 2 per cent default
    assert _codes(marks_doc, courses_doc, lines_doc, tolerance_pct=0.5) == ["distance-mismatch"]


def test_an_unresolvable_leg_suppresses_the_distance_check():
    """One fault should not produce two findings; the id error is the real one."""
    marks_doc, courses_doc, lines_doc = _fixture()
    courses_doc["courses"][0]["legs"][0]["mark"] = "charlie"
    codes = _codes(marks_doc, courses_doc, lines_doc)
    assert "unknown-mark" in codes
    assert "distance-mismatch" not in codes


def test_duplicate_ids_are_errors():
    marks_doc, courses_doc, lines_doc = _fixture()
    marks_doc["marks"].append(copy.deepcopy(marks_doc["marks"][0]))
    assert "duplicate-mark-id" in _codes(marks_doc, courses_doc, lines_doc)

    marks_doc, courses_doc, lines_doc = _fixture()
    courses_doc["courses"].append(copy.deepcopy(courses_doc["courses"][0]))
    assert "duplicate-course-id" in _codes(marks_doc, courses_doc, lines_doc)


def test_an_unknown_series_is_an_error():
    marks_doc, courses_doc, lines_doc = _fixture()
    courses_doc["courses"][0]["series"] = "twilight"
    assert "unknown-series" in _codes(marks_doc, courses_doc, lines_doc)


def test_a_bad_shortened_at_is_an_error():
    marks_doc, courses_doc, lines_doc = _fixture()
    courses_doc["courses"][0]["shortened_at"] = 99
    assert "bad-shortened-at" in _codes(marks_doc, courses_doc, lines_doc)

    marks_doc, courses_doc, lines_doc = _fixture()
    courses_doc["courses"][0]["shortened_at"] = 1
    assert _codes(marks_doc, courses_doc, lines_doc) == []


def test_a_mark_with_no_position_is_an_error():
    for bad in [None, "", "south", [], {}]:
        marks_doc, courses_doc, lines_doc = _fixture()
        marks_doc["marks"][0]["lat"] = bad
        assert "mark-no-position" in _codes(marks_doc, courses_doc, lines_doc), bad

    marks_doc, courses_doc, lines_doc = _fixture()
    del marks_doc["marks"][0]["lon"]
    assert "mark-no-position" in _codes(marks_doc, courses_doc, lines_doc)


def test_a_mark_with_a_position_that_is_not_finite_is_an_error():
    """`nan is None` is False, so an is-not-None check would pass this straight through.

    json.loads accepts a bare NaN token, so a hand-edited marks.json can carry one. Left
    unvalidated it reaches engine/nav, where it fails no range check and no comparison,
    and turns every distance into nan (DESIGN 6).
    """
    for bad in [float("nan"), float("inf"), float("-inf")]:
        marks_doc, courses_doc, lines_doc = _fixture()
        marks_doc["marks"][1]["lon"] = bad
        codes = _codes(marks_doc, courses_doc, lines_doc)
        assert "mark-no-position" in codes, bad
        # and the distance check stands down rather than reporting a nan mismatch too
        assert "distance-mismatch" not in codes, bad


def test_the_shipped_marks_all_have_finite_positions():
    """102 marks from the register, none of them NaN, null or a string."""
    for mark in MARKS["marks"]:
        assert course._has_position(mark), mark["id"]


def test_a_degenerate_start_line_is_an_error():
    marks_doc, courses_doc, lines_doc = _fixture()
    lines_doc["start_finish"]["inner"] = dict(lines_doc["start_finish"]["outer"])
    assert "start-finish-degenerate" in _codes(marks_doc, courses_doc, lines_doc)


def test_validate_reports_everything_in_one_pass():
    """It never raises and never stops at the first fault."""
    marks_doc, courses_doc, lines_doc = _fixture()
    legs = courses_doc["courses"][0]["legs"]
    legs[0]["mark"] = "charlie"
    legs[1]["rounding"] = "sideways"
    legs.pop()
    codes = _codes(marks_doc, courses_doc, lines_doc)
    assert {"unknown-mark", "bad-rounding", "no-finish"} <= set(codes), codes


def test_validate_survives_empty_documents():
    """A missing or truncated config file must produce findings, not a traceback."""
    problems = course.validate({}, {}, {})
    assert [p.code for p in problems] == ["no-start-finish"]
    assert course.index_marks({}) == {}


def test_problem_str_names_the_course_and_leg():
    p = course.Problem(course.ERROR, "unknown-mark", "unknown mark 'charlie'", "test-1", 3)
    assert str(p) == "error: unknown mark 'charlie' [test-1 leg 3]"
    assert str(course.Problem(course.WARNING, "x", "hmm")) == "warning: hmm"


# --- the leg table, which is what the detail page renders ------------------


def test_the_leg_table_lists_every_leg_with_its_own_numbers():
    """One row per leg, in order, with the distances the reconciliation already uses.

    The same arithmetic as leg_distances_nm, so a course that does not add up looks wrong
    on the page as well as in the log (DESIGN 9.11).
    """
    frostbite3 = [c for c in COURSES["courses"] if c["id"] == "frostbite-3"][0]
    rows = course.leg_table(frostbite3, INDEX, LINES)

    assert len(rows) == len(frostbite3["legs"])
    assert [r["leg"] for r in rows] == list(range(1, len(rows) + 1))

    # the per-leg distances are the ones the reconciliation sums
    plain = course.leg_distances_nm(frostbite3, INDEX, LINES)
    assert [round(r["distance_nm"], 9) for r in rows] == [round(d, 9) for d in plain]
    running = course.cumulative_distances_nm(frostbite3, INDEX, LINES)
    assert [round(r["cumulative_nm"], 9) for r in rows] == [round(d, 9) for d in running]
    assert abs(rows[-1]["cumulative_nm"]
               - course.course_distance_nm(frostbite3, INDEX, LINES)) < 1e-9

    # names, not ids, because the crew calls it Squadron (DESIGN 9.2)
    assert rows[0]["name"] == "Dolphin East"
    assert rows[0]["number"] == "42B"
    assert rows[0]["rounding"] == "starboard"

    # the last row is the finish and has no mark of its own
    assert rows[-1]["finish"] is True
    assert rows[-1]["mark"] is None
    assert all(r["finish"] is False for r in rows[:-1])


def test_the_leg_table_bearings_run_mark_to_mark_from_the_line():
    """The first leg is measured from the middle of the start line, each one after it from
    the mark before, which is the same walk the distances take."""
    frostbite3 = [c for c in COURSES["courses"] if c["id"] == "frostbite-3"][0]
    rows = course.leg_table(frostbite3, INDEX, LINES)

    start = course.start_point(LINES)
    first = course.leg_target(frostbite3["legs"][0], INDEX, LINES)
    assert abs(nav.norm180(rows[0]["bearing"] - nav.bearing(start, first))) < 1e-6

    second = course.leg_target(frostbite3["legs"][1], INDEX, LINES)
    assert abs(nav.norm180(rows[1]["bearing"] - nav.bearing(first, second))) < 1e-6
    for row in rows:
        assert 0.0 <= row["bearing"] < 360.0, row


def test_the_leg_table_says_which_legs_are_beats_when_the_wind_is_known():
    """And says nothing rather than guessing when it is not (DESIGN 3)."""
    frostbite3 = [c for c in COURSES["courses"] if c["id"] == "frostbite-3"][0]

    without = course.leg_table(frostbite3, INDEX, LINES)
    assert all(r["leg_type"] is None for r in without)

    rows = course.leg_table(frostbite3, INDEX, LINES, twd=0.0)
    assert all(r["leg_type"] in ("beat", "reach", "run") for r in rows)
    # a leg straight into a northerly is a beat, one straight away from it is a run
    for row in rows:
        off = abs(nav.norm180(0.0 - row["bearing"]))
        expected = "beat" if off < 40.0 else "run" if off > 140.0 else "reach"
        assert row["leg_type"] == expected, (row["leg"], row["bearing"])


def test_the_leg_type_thresholds_have_one_definition():
    """race.py called it first and now delegates, so a briefing sheet and the race screen
    cannot disagree about what a leg is."""
    from engine import race as race_module

    assert race_module.leg_type(0.0, 10.0) == course.leg_type(0.0, 10.0) == "beat"
    assert race_module.leg_type(0.0, 90.0) == course.leg_type(0.0, 90.0) == "reach"
    assert race_module.leg_type(0.0, 179.0) == course.leg_type(0.0, 179.0) == "run"
    assert race_module.leg_type(None, 90.0) is course.leg_type(None, 90.0) is None
    assert race_module.BEAT_MAX == course.BEAT_MAX
    assert race_module.RUN_MIN == course.RUN_MIN


def test_the_leg_table_carries_the_note_on_a_leg_that_has_one():
    """Frostbite course 4 leg 3 records which of two marks a printed "(38)" meant, and the
    detail page is exactly where someone would want to read that."""
    frostbite4 = [c for c in COURSES["courses"] if c["id"] == "frostbite-4"][0]
    rows = course.leg_table(frostbite4, INDEX, LINES)
    assert rows[2]["mark"] == "bond-38a"
    assert rows[2]["note"] and "38" in rows[2]["note"]
    assert rows[0]["note"] is None


def test_the_leg_table_works_for_every_shipped_course():
    """It is rendered for any course the crew taps, including ones nobody is sailing."""
    for c in COURSES["courses"]:
        rows = course.leg_table(c, INDEX, LINES, twd=210.0)
        assert len(rows) == len(c["legs"]), c["id"]
        assert rows[-1]["finish"] is True, c["id"]
        assert all(r["distance_nm"] >= 0.0 for r in rows), c["id"]
        assert all(r["rounding"] in ("port", "starboard") for r in rows), c["id"]


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
