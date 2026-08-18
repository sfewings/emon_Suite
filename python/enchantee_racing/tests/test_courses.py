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

# Frostbite course 1 prints 7.11 nm and its legs sum to 7.30. Every row was read off
# the sheet and the row spacing is uniform, so no leg is missing, and no single
# substitution or deletion from the twenty course marks lands within 1 per cent of
# the printed figure. It is recorded as an open question in DESIGN 7 and in a note on
# the course itself. Pinned here rather than silenced so that a *new* mismatch fails
# the build while this one does not.
KNOWN_DISTANCE_MISMATCHES = {"frostbite-1"}


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


def test_rounding_lint_is_clean():
    """The register agreed with the sheets on all twenty marks, so this stays empty."""
    found = [p for p in PROBLEMS if p.code == "rounding-mismatch"]
    assert found == [], "\n".join(str(p) for p in found)


def test_the_other_three_courses_reconcile_tightly():
    """2 per cent is the documented tolerance; the real agreement is far better."""
    for course_id in ("frostbite-2", "frostbite-3", "frostbite-4"):
        c = _course(course_id)
        summed = course.course_distance_nm(c, INDEX, LINES)
        error_pct = (summed - c["distance_nm"]) / c["distance_nm"] * 100.0
        assert abs(error_pct) < 0.2, (course_id, summed, c["distance_nm"], error_pct)


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


def test_club_32a_is_both_a_course_mark_and_the_finish():
    """The hazard the whole finish-detection design exists for (DESIGN 11.5).

    Every Frostbite course rounds club-32a while racing and finishes on the line it
    forms the outer end of, so a naive finish test fires mid-race in all four.
    """
    outer = LINES["start_finish"]["outer"]["mark"]
    assert outer == "club-32a"
    for c in COURSES["courses"]:
        mid_course = sum(1 for leg in c["legs"] if leg.get("mark") == outer)
        assert mid_course >= 1, c["id"]
        assert course.is_finish(c["legs"][-1]), c["id"]


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
    marks_doc, courses_doc, lines_doc = _fixture()
    marks_doc["marks"][0]["lat"] = None
    assert "mark-no-position" in _codes(marks_doc, courses_doc, lines_doc)


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
