"""Validate and interpret course data: marks, courses and the two lines. No I/O.

CLAUDE.md's layout calls this module "load and validate", and also says engine/ must
contain no I/O. Both hold if app.py does the reading and this module takes the
already-parsed JSON, which is why every function here takes documents or an index
rather than a path. It is also what lets the whole of build order step 2 be checked
in CI without a filesystem or a boat.

What the rules are, and where they come from:

- Marks are keyed by string id. `number` is a display string and is not unique:
  fourteen numbers are shared by two marks each, and 37 (Deepwater Spit and
  Squadron) and 38 (Bond and Dee Rd) collide inside PFSYC's own courses (DESIGN 6).
- Legs are an ordered list that allows repeats. club-32a appears three times in one
  Frostbite course counting the finish. Course position is a leg index, never a mark
  identity (DESIGN 7, 11.2).
- Every leg targets exactly one mark, except the last, which targets the
  start/finish line. There are no gates, no leg has two marks, and nothing targets a
  midpoint of a mark pair. A leg carrying `marks` or `gate` is rejected outright,
  because that was the earlier and wrong model (DESIGN 6).
- Rounding is per leg, never inherited from the mark: Frostbite course 2 rounds
  club-32a to starboard on one pass and to port on another. The register's rounding
  column agrees with the sheets on all twenty marks, so a leg that disagrees with it
  is almost certainly a transcription error and is reported as a warning (DESIGN 6).
- The printed distance validates the transcription. Summing leg distances mark to
  mark, measured from and back to the midpoint of the start line, reproduces the
  sheet's printed total to within a few hundredths of a mile. This single check is
  what disproved the gate model, and it should run in CI over every course
  (DESIGN 7).

Severity matters to callers. An `error` means the data cannot be raced on: an id
that does not resolve, a course with no finish. A `warning` means the data is
suspect but usable, which is the right level for a printed distance that does not
reconcile, because the printed figure is sometimes the thing that is wrong. app.py
should refuse to serve a course with errors and surface warnings to the log only.

`shortened_at` is now solved from the printed shortened distance, by
scripts/extract_courses.py, using the same cumulative arithmetic as the reconciliation
below. Only legs that return to the start/finish line are candidates: flag S means the
next pass through the line ends the race, and solving by nearest running total across
every leg instead lands on a mark in the middle of the river whenever a course's own
distance is a little out (DESIGN 11.6).
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, NamedTuple, Optional, Sequence

from . import nav

ERROR = "error"
WARNING = "warning"

ROUNDINGS = ("port", "starboard")

DEFAULT_TOLERANCE_PCT = 2.0
"""Per DESIGN 7. The observed agreement is far tighter: of the six courses checked
so far, five land within 0.1 per cent, so anything past a few tenths is a signal."""


class Problem(NamedTuple):
    """One validation finding. Never raised, always collected and returned."""

    severity: str
    code: str
    message: str
    course: Optional[str] = None
    leg: Optional[int] = None

    def __str__(self) -> str:
        where = ""
        if self.course:
            where = " [%s" % self.course + ("" if self.leg is None else " leg %d" % self.leg) + "]"
        return "%s: %s%s" % (self.severity, self.message, where)


def _has_position(thing: Optional[Mapping[str, Any]]) -> bool:
    """Can this mark or line end be projected without blowing up?

    Finiteness rather than an is-not-None check. json.loads accepts a bare NaN token, and
    `nan is None` is False, so a hand-edited marks.json could carry one and pass
    validation, then reach engine/nav where it fails no range check and no comparison.
    """
    if not thing:
        return False
    try:
        return math.isfinite(float(thing["lat"])) and math.isfinite(float(thing["lon"]))
    except (KeyError, TypeError, ValueError):
        return False


def index_marks(marks_doc: Mapping[str, Any]) -> dict:
    """id -> mark, for the other functions here. Duplicates keep the first entry.

    A duplicate id is reported by validate(); this does not raise, so that a broken
    config still produces a full problem list rather than one exception.
    """
    index: dict = {}
    for mark in marks_doc.get("marks", []):
        index.setdefault(mark.get("id"), mark)
    return index


def errors(problems: Iterable[Problem]) -> list:
    """Just the problems that make the data unraceable."""
    return [p for p in problems if p.severity == ERROR]


def warnings(problems: Iterable[Problem]) -> list:
    """Just the problems that make the data suspect but usable."""
    return [p for p in problems if p.severity == WARNING]


# --- interpreting a course -------------------------------------------------


def start_line(lines_doc: Mapping[str, Any]) -> tuple:
    """The two ends of the start/finish line, inner first."""
    sf = lines_doc["start_finish"]
    return nav.as_latlon(sf["inner"]), nav.as_latlon(sf["outer"])


def start_point(lines_doc: Mapping[str, Any]) -> nav.LatLon:
    """The midpoint of the start line: where a course is measured from and back to.

    The start is a line, not a point, so any single point is a convention. The
    midpoint is the one that reproduces the printed distances (DESIGN 7), and it is
    also what a pre-start distance-to-line readout aims at (DESIGN 10).
    """
    inner, outer = start_line(lines_doc)
    return nav.midpoint(inner, outer)


def is_finish(leg: Mapping[str, Any]) -> bool:
    """Is this the leg that targets the finish line rather than a mark?"""
    return bool(leg.get("finish"))


def leg_target(leg: Mapping[str, Any], marks: Mapping[str, Any], lines_doc: Mapping[str, Any]) -> nav.LatLon:
    """Where the boat is steering for on this leg.

    `marks` is an index from index_marks(). Raises KeyError on an unresolved id,
    so call validate() first if the data is not already trusted.
    """
    if is_finish(leg):
        return start_point(lines_doc)
    return nav.as_latlon(marks[leg["mark"]])


def leg_name(leg: Mapping[str, Any], marks: Mapping[str, Any]) -> str:
    """What to call this leg on screen.

    The display `name` from marks.json, never the id and never the number, because
    the crew calls it "Squadron", not "37" (DESIGN 9.2).
    """
    if is_finish(leg):
        return "Finish"
    mark = marks.get(leg.get("mark"))
    return mark.get("name", leg.get("mark", "?")) if mark else str(leg.get("mark", "?"))


def leg_distances_nm(
    course: Mapping[str, Any], marks: Mapping[str, Any], lines_doc: Mapping[str, Any]
) -> list:
    """Distance of each leg in nautical miles, starting from the start line."""
    here = start_point(lines_doc)
    out = []
    for leg in course.get("legs", []):
        target = leg_target(leg, marks, lines_doc)
        out.append(nav.distance_nm(here, target))
        here = target
    return out


def course_distance_nm(
    course: Mapping[str, Any], marks: Mapping[str, Any], lines_doc: Mapping[str, Any]
) -> float:
    """Total sailed distance, mark to mark, in nautical miles.

    Compare against the sheet's printed `distance_nm`. This is a straight-line sum
    and takes no account of sailing close hauled, so it is a transcription check, not
    a prediction of how far the boat sails.
    """
    return sum(leg_distances_nm(course, marks, lines_doc))


def cumulative_distances_nm(
    course: Mapping[str, Any], marks: Mapping[str, Any], lines_doc: Mapping[str, Any]
) -> list:
    """Running total after each leg. The basis for solving `shortened_at` (DESIGN 11.6)."""
    total = 0.0
    out = []
    for d in leg_distances_nm(course, marks, lines_doc):
        total += d
        out.append(total)
    return out


def leg_table(
    course: Mapping[str, Any], marks: Mapping[str, Any], lines_doc: Mapping[str, Any],
    twd: Optional[float] = None,
) -> list:
    """Every leg of a course, as a briefing sheet rather than as state.

    One row per leg with the mark's display name and number, which side to round it, the
    leg's length and bearing, and the running total. This is what the course detail page
    shows, and the numbers are the same ones the distance reconciliation uses, so a course
    that does not add up looks wrong on the page as well as in the log (DESIGN 9.11).

    The bearing is the straight line from the previous mark, or from the middle of the
    start line for the first leg. It is what to steer in the absence of wind, not a
    prediction: a close haul sails nothing like its bearing, which is why `leg_type` is
    here to say which legs those are, when the wind direction is known.
    """
    here = start_point(lines_doc)
    total = 0.0
    rows = []
    for index, leg in enumerate(course.get("legs", [])):
        target = leg_target(leg, marks, lines_doc)
        distance = nav.distance_nm(here, target)
        total += distance
        bearing = nav.bearing(here, target)
        mark_id = leg.get("mark")
        mark = marks.get(mark_id) or {}
        rows.append({
            "leg": index + 1,
            "mark": mark_id,
            "name": leg_name(leg, marks),
            "number": mark.get("number"),
            "rounding": leg.get("rounding"),
            "finish": is_finish(leg),
            "distance_nm": distance,
            "cumulative_nm": total,
            "bearing": bearing,
            "leg_type": leg_type(twd, bearing),
            "note": leg.get("note"),
        })
        here = target
    return rows


# Under this off the wind it is a close haul, over the other it is a run (DESIGN 3).
CLOSE_HAUL_MAX = 40.0
RUN_MIN = 140.0


def leg_type(twd: Optional[float], bearing_to_mark: Optional[float]) -> Optional[str]:
    """close haul, reach or run for a leg, from norm180(twd - bearing) (DESIGN 3).

    Lives here rather than in race.py, which called it first, because the detail page
    wants it for a course nobody is sailing and race.py already imports this module. One
    definition, so the briefing sheet and the race screen cannot disagree about what a
    leg is.
    """
    if twd is None or bearing_to_mark is None:
        return None
    off_the_wind = abs(nav.norm180(twd - bearing_to_mark))
    if off_the_wind < CLOSE_HAUL_MAX:
        return "close haul"
    if off_the_wind > RUN_MIN:
        return "run"
    return "reach"


# --- validation ------------------------------------------------------------


def validate(
    marks_doc: Mapping[str, Any],
    courses_doc: Mapping[str, Any],
    lines_doc: Mapping[str, Any],
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
) -> list:
    """Check the three config documents against each other. Returns a problem list.

    Never raises on bad data and never stops at the first fault: the point is to
    hand back everything that is wrong in one pass, so a season's course sheets can
    be transcribed and checked in one sitting.
    """
    problems: list = []
    marks = index_marks(marks_doc)
    problems += _validate_marks(marks_doc, marks)
    problems += _validate_lines(lines_doc, marks)
    problems += _validate_courses(courses_doc, marks, lines_doc, tolerance_pct)
    return problems


def _validate_marks(marks_doc: Mapping[str, Any], marks: Mapping[str, Any]) -> list:
    problems = []
    seen = set()
    for i, mark in enumerate(marks_doc.get("marks", [])):
        mark_id = mark.get("id")
        if not mark_id:
            problems.append(Problem(ERROR, "mark-no-id", "mark %d has no id" % i))
            continue
        if mark_id in seen:
            problems.append(Problem(ERROR, "duplicate-mark-id", "duplicate mark id %r" % mark_id))
        seen.add(mark_id)
        if not _has_position(mark):
            problems.append(
                Problem(ERROR, "mark-no-position",
                        "mark %r has no usable position: lat=%r lon=%r"
                        % (mark_id, mark.get("lat"), mark.get("lon")))
            )
        rounding = mark.get("rounding")
        if rounding is not None and rounding not in ROUNDINGS:
            problems.append(
                Problem(ERROR, "bad-mark-rounding", "mark %r has rounding %r" % (mark_id, rounding))
            )
    return problems


def _validate_lines(lines_doc: Mapping[str, Any], marks: Mapping[str, Any]) -> list:
    problems = []
    sf = lines_doc.get("start_finish")
    if not sf:
        problems.append(Problem(ERROR, "no-start-finish", "lines.json has no start_finish"))
    else:
        for end in ("inner", "outer"):
            point = sf.get(end)
            if not point or point.get("lat") is None or point.get("lon") is None:
                problems.append(
                    Problem(ERROR, "start-finish-end", "start_finish %s end has no position" % end)
                )
        if sf.get("inner") and sf.get("outer"):
            inner, outer = start_line(lines_doc)
            if nav.distance_m(inner, outer) < 1.0:
                problems.append(
                    Problem(ERROR, "start-finish-degenerate", "start_finish ends are less than 1 m apart")
                )

    if "gates" in lines_doc:
        problems.append(
            Problem(
                ERROR,
                "gates-removed",
                'lines.json has a "gates" key. There are no gates: Bricklanding, '
                "Smith / Lucky Bay and Mosman are pairs of ordinary marks, each rounded "
                'on its own. The two forbidden lines belong in "no_cross_lines" '
                "(DESIGN 6)",
            )
        )

    for line in lines_doc.get("no_cross_lines", []):
        line_id = line.get("id", "?")
        line_marks = line.get("marks", [])
        if len(line_marks) != 2:
            problems.append(
                Problem(ERROR, "no-cross-marks", "no_cross_line %r needs exactly two marks" % line_id)
            )
        for mark_id in line_marks:
            if mark_id not in marks:
                problems.append(
                    Problem(ERROR, "unknown-mark", "no_cross_line %r references unknown mark %r"
                            % (line_id, mark_id))
                )
    return problems


def _validate_courses(
    courses_doc: Mapping[str, Any],
    marks: Mapping[str, Any],
    lines_doc: Mapping[str, Any],
    tolerance_pct: float,
) -> list:
    problems = []
    series = courses_doc.get("series", {})
    start_finish_id = (lines_doc.get("start_finish") or {}).get("id")
    seen_ids = set()

    for course in courses_doc.get("courses", []):
        course_id = course.get("id")
        if not course_id:
            problems.append(Problem(ERROR, "course-no-id", "a course has no id"))
            continue
        if course_id in seen_ids:
            problems.append(Problem(ERROR, "duplicate-course-id", "duplicate course id", course_id))
        seen_ids.add(course_id)

        if course.get("series") not in series:
            problems.append(
                Problem(ERROR, "unknown-series", "unknown series %r" % course.get("series"), course_id)
            )

        printed = course.get("distance_nm")
        if not isinstance(printed, (int, float)) or printed <= 0:
            problems.append(
                Problem(ERROR, "bad-distance", "distance_nm is %r" % printed, course_id)
            )
            printed = None

        legs = course.get("legs", [])
        if not legs:
            problems.append(Problem(ERROR, "no-legs", "course has no legs", course_id))
            continue

        problems += _validate_legs(course_id, legs, marks, start_finish_id)

        shortened = course.get("shortened_at")
        if shortened is not None and not (isinstance(shortened, int) and 0 <= shortened < len(legs)):
            problems.append(
                Problem(ERROR, "bad-shortened-at", "shortened_at is %r" % shortened, course_id)
            )

        # Distance reconciliation, only once every position it needs is usable.
        # One fault should produce one finding, and an unresolved id or a mark with
        # no coordinates has already been reported by the checks above.
        resolvable = _has_position(lines_doc.get("start_finish", {}).get("inner")) and _has_position(
            lines_doc.get("start_finish", {}).get("outer")
        ) and all(is_finish(leg) or _has_position(marks.get(leg.get("mark"))) for leg in legs)
        if printed and resolvable:
            summed = course_distance_nm(course, marks, lines_doc)
            error_pct = (summed - printed) / printed * 100.0
            if abs(error_pct) > tolerance_pct:
                problems.append(
                    Problem(
                        WARNING,
                        "distance-mismatch",
                        "legs sum to %.2f nm against a printed %.2f, %+.1f per cent. A leg is in "
                        "the wrong order, missing, or the wrong mark, or else the printed figure "
                        "is wrong (DESIGN 7)" % (summed, printed, error_pct),
                        course_id,
                    )
                )
    return problems


def _validate_legs(
    course_id: str, legs: Sequence[Mapping[str, Any]], marks: Mapping[str, Any], start_finish_id
) -> list:
    problems = []
    finishes = 0

    for i, leg in enumerate(legs):
        for removed in ("gate", "marks"):
            if removed in leg:
                problems.append(
                    Problem(
                        ERROR,
                        "gates-removed",
                        'leg has a "%s" key. Every leg targets exactly one mark: the three mark '
                        "pairs are consecutive legs, each mark rounded on its own (DESIGN 6)" % removed,
                        course_id,
                        i,
                    )
                )

        if is_finish(leg):
            finishes += 1
            if leg.get("line") != start_finish_id:
                problems.append(
                    Problem(ERROR, "unknown-line", "finish line is %r, not %r"
                            % (leg.get("line"), start_finish_id), course_id, i)
                )
            if "mark" in leg:
                problems.append(
                    Problem(ERROR, "leg-shape", "the finish leg targets the line, not a mark",
                            course_id, i)
                )
        elif "mark" not in leg:
            problems.append(
                Problem(ERROR, "leg-shape", "leg has neither a mark nor finish", course_id, i)
            )
        elif leg["mark"] not in marks:
            problems.append(
                Problem(ERROR, "unknown-mark", "unknown mark %r" % leg["mark"], course_id, i)
            )

        rounding = leg.get("rounding")
        if rounding not in ROUNDINGS:
            problems.append(
                Problem(ERROR, "bad-rounding", "rounding is %r, expected one of %s"
                        % (rounding, " or ".join(ROUNDINGS)), course_id, i)
            )
        elif not is_finish(leg):
            registered = (marks.get(leg.get("mark")) or {}).get("rounding")
            if registered is not None and registered != rounding:
                problems.append(
                    Problem(
                        WARNING,
                        "rounding-mismatch",
                        "sheet rounds %s to %s, the register says %s. The register agreed with "
                        "the sheets on all twenty marks, so this is probably a transcription "
                        "error (DESIGN 6)" % (leg["mark"], rounding, registered),
                        course_id,
                        i,
                    )
                )

    if finishes == 0:
        problems.append(
            Problem(ERROR, "no-finish", "course has no finish leg", course_id)
        )
    elif finishes > 1:
        problems.append(
            Problem(ERROR, "many-finishes", "course has %d finish legs" % finishes, course_id)
        )
    elif not is_finish(legs[-1]):
        problems.append(
            Problem(ERROR, "finish-not-last", "the finish leg is not the last leg", course_id)
        )
    return problems
