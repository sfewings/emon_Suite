"""Extract every course sheet from the fixtures PDF into config/courses.json.

    python scripts/extract_courses.py [--dry-run]

A development-time script, like gen_marks.py: it needs PyMuPDF and the reference PDF,
neither of which the Pi has, and it commits its output.

The four Frostbite courses were transcribed by hand first. They are now the **control**:
this script parses their page too and refuses to write anything unless what it reads
matches what was transcribed, leg for leg, rounding for rounding. That check has already
earned its place three times over, catching a rounding lost to the printed dotted leaders
("_stbd" has no word boundary in front of it), a finish leg no regex would match because
"Finish (Club Buoy) (32A)" has no name before its number, and the flare and torch counts
in the Twilight prose being read as marks 2 and 7.

The Frostbite entries are then copied through untouched, notes and all, rather than
regenerated: they carry judgements no parser is going to reproduce, such as which of two
marks a printed "(38)" meant.

Marks resolve on printed name **and** number, never number alone. Seventeen numbers in
marks.json belong to two marks each, and one of them matters here: bare 38 is Dee Rd,
900 m from Bond, and both appear on these sheets. Failing loudly on an unresolved name is
the whole point, so it does.

What the sheets carry that Frostbite did not:

- A **shortened course** distance, on all three Sunday sheets. Where the printed figure
  agrees with the running total at a leg that comes back through the line, that leg index
  goes in `shortened_at`, which engine/course.py has validated since it was written and
  has never had data for (DESIGN 11.6). Where it does not agree, the printed figure is
  recorded and `shortened_at` left null, with the residual in a note: a guess about where
  a race ends is worse than an admission that it is not known.
- Start times and division flags that differ per series, and in Friday's case per season
  and division.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from engine import course as course_module  # noqa: E402

PDF = ROOT / "docs" / "reference" / "Sailing Fixtures & Courses 2026 - 2027.pdf"
COURSES = ROOT / "config" / "courses.json"
MARKS = ROOT / "config" / "marks.json"
LINES = ROOT / "config" / "lines.json"

# The finish is the club line, not a mark, on every sheet in this document.
FINISH_LINE = "pfsyc-start-finish"

# How close the running total has to come to a printed shortened figure before that leg
# is accepted as where a shortened race ends. The full-course distances reconcile to
# about a per cent (DESIGN 7), so this is the same order and no tighter.
SHORTENED_TOLERANCE_PCT = 3.0

SHEETS = [
    {"page": 14, "series": "frostbite", "control": True},
    {"page": 15, "series": "friday"},
    {"page": 16, "series": "sunday-div-ii"},
    {"page": 17, "series": "sunday-div-iii"},
    {"page": 18, "series": "sunday-div-iv"},
    {"page": 19, "series": "twilight"},
]

# Prose off the sheets and the sailing instructions, which wants reading rather than
# parsing. Frostbite's entry is left where it is, in the committed file.
SERIES = {
    "friday": {
        "name": "Friday Afternoon",
        "note": "Open Invitation Series.",
        "starts": [
            {"divisions": ["IV"], "time": "15:05", "flag": None, "season": "summer"},
            {"divisions": ["III"], "time": "15:15", "flag": None, "season": "summer"},
            {"divisions": ["II"], "time": "15:25", "flag": None, "season": "summer"},
            {"divisions": ["I"], "time": "15:35", "flag": None, "season": "summer"},
            {"divisions": ["III", "IV"], "time": "15:05", "flag": None, "season": "winter"},
            {"divisions": ["I", "II"], "time": "15:25", "flag": None, "season": "winter"},
        ],
        "time_limit": "17:30",
        "time_limit_note": ("The sheet prints \"Time Limit: 1730 hrs [no extensions]\". A "
                            "wall-clock limit, not a duration, and explicitly not subject "
                            "to the half-hour extension the general rule allows."),
        "shortened_signal": ("International Code Flag S from the start box. Flown at the "
                             "start under the numeral pendant it means the finish is the "
                             "first crossing of the line after the start; flown during the "
                             "race it means the next pass through the line ends it."),
        "flag_note": ("The sheet names no naval numeral flag and the start order is by "
                      "division and season, so no division flag is recorded against a "
                      "course. Each course carries only its numeral pendant."),
    },
    "sunday-div-ii": {
        "name": "Sunday Afternoon Div II",
        "note": None,
        "starts": [{"divisions": ["II"], "time": "14:20", "flag": "naval-2"}],
        "time_limit": "3h",
        "time_limit_note": ("Not printed on the sheet. The sailing instructions give three "
                            "hours unless specified elsewhere, extended by thirty minutes "
                            "if the first boat finishes inside the three."),
        "shortened_signal": ("International Code Flag S from the start box. The sheet also "
                             "prints a shortened distance for each course."),
        "flag_note": "One start, one flag: Naval Numeral Flag 2, so it sits on each course.",
    },
    "sunday-div-iii": {
        "name": "Sunday Afternoon Div III",
        "note": None,
        "starts": [{"divisions": ["III"], "time": "14:00", "flag": "naval-3"}],
        "time_limit": "3h",
        "time_limit_note": ("Not printed on the sheet. The sailing instructions give three "
                            "hours unless specified elsewhere, extended by thirty minutes "
                            "if the first boat finishes inside the three."),
        "shortened_signal": ("International Code Flag S from the start box. The sheet also "
                             "prints a shortened distance for each course."),
        "flag_note": "One start, one flag: Naval Numeral Flag 3, so it sits on each course.",
    },
    "sunday-div-iv": {
        "name": "Sunday Afternoon Div IV",
        "note": None,
        "starts": [{"divisions": ["IV"], "time": "14:00", "flag": "naval-4"}],
        "time_limit": "3h",
        "time_limit_note": ("Not printed on the sheet. The sailing instructions give three "
                            "hours unless specified elsewhere, extended by thirty minutes "
                            "if the first boat finishes inside the three."),
        "shortened_signal": ("International Code Flag S from the start box. The sheet also "
                             "prints a shortened distance for each course."),
        "flag_note": "One start, one flag: Naval Numeral Flag 4, so it sits on each course.",
    },
    "twilight": {
        "name": "Twilight Cruises",
        "note": ("All divisions, combined. A flying start. The sheet says it is not a "
                 "competitive event and that spinnakers shall not be used."),
        "starts": [{"divisions": ["I", "II", "III", "IV"], "time": "18:20", "flag": None}],
        "time_limit": None,
        "time_limit_note": "None printed, and a cruise is not a race with a limit.",
        "shortened_signal": None,
        "flag_note": ("Combined division and a flying start, so no naval numeral flag is "
                      "printed. Each course carries only its numeral pendant."),
    },
}

# Which division sails the sheet, matching the "division" the hand-transcribed Frostbite
# courses already carry. Friday is an open invitation with the divisions starting
# separately off one sheet, so it names no single one.
DIVISION = {
    "friday": "open",
    "sunday-div-ii": "II",
    "sunday-div-iii": "III",
    "sunday-div-iv": "IV",
    "twilight": "combined",
}

DIVISION_FLAG = {
    "sunday-div-ii": "naval-2",
    "sunday-div-iii": "naval-3",
    "sunday-div-iv": "naval-4",
}


def norm(text: str) -> str:
    """A mark name reduced to what is comparable between the sheet and the register."""
    text = text.lower().replace("’", "'")
    text = re.sub(r"\b(buoy|beacon|mark|spit)\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


class Resolver:
    """Printed name and number to a mark id, or a loud failure."""

    def __init__(self, marks_doc):
        self.by_name_number = {}
        self.by_alias = {}
        for mark in marks_doc["marks"]:
            number = (mark.get("number") or "").upper()
            if number:
                self.by_name_number.setdefault((norm(mark["name"]), number), []).append(mark["id"])
            for alias in mark.get("aliases", []):
                self.by_alias.setdefault(norm(alias), []).append(mark["id"])
                found = re.search(r"\((\d+[A-Za-z]?)\)", alias)
                if found:
                    plain = norm(re.sub(r"\(.*?\)", "", alias))
                    self.by_alias.setdefault(
                        plain + " #" + found.group(1).upper(), []).append(mark["id"])

    def resolve(self, name: str, number: str) -> str:
        key = (norm(name), number.upper())
        ids = self.by_name_number.get(key, [])
        if len(ids) == 1:
            return ids[0]
        # The sheets print a number the register gives to a different mark. bond-38a
        # carries "Bond Buoy (38)" as an alias for exactly this, because bare 38 is Dee Rd.
        ids = self.by_alias.get(norm(name) + " #" + number.upper(), [])
        if len(ids) == 1:
            return ids[0]
        ids = self.by_alias.get(norm(name), [])
        if len(ids) == 1:
            return ids[0]
        raise SystemExit(
            'cannot resolve "%s (%s)" to one mark in config/marks.json: got %s.\n'
            "Add an alias to the mark it means, rather than guessing here."
            % (name, number, ids or "nothing"))


MARK_OR_ROUNDING = re.compile(
    r"(?P<finish>Finish)\s*\(([^)]*)\)(?:\s*\((?P<fnum>\d+[A-Za-z]?)\))?"
    r"|(?P<name>[A-Za-z][A-Za-z'\-. ]*?)\s*(?:Buoy|Beacon)?\s*\((?P<num>\d+[A-Za-z]?)\)"
    r"|(?P<round>stbd|starboard|port)",
    re.IGNORECASE)


def parse_sheet(text: str) -> list:
    """Every course on one sheet, as printed: names, numbers and roundings in order."""
    # The dotted leaders on the printed sheet come through as runs of underscores, and an
    # underscore is a word character, so "_stbd" hides the rounding from a \b match.
    text = re.sub(r"_+", " ", text.replace("‘", "'").replace("’", "'"))

    blocks = re.split(r"Course\s*No\.?\s*(\d+)", text)
    courses = []
    for i in range(1, len(blocks), 2):
        number, body = int(blocks[i]), blocks[i + 1]
        head = body[:260]

        # "8.30nnm" is a typo on the Div III sheet, so tolerate the doubled n.
        distances = [float(m.group(1)) for m in re.finditer(r"([\d.]+)\s*n+m", head, re.I)]
        pendant = re.search(r"Numeral Pendant\s*(\d+)", head, re.I)
        wind = re.search(r"((?:North|South|East|West)[a-z]*(?:\s+[A-Za-z]*erly)?\s*Breeze)",
                         head, re.I)
        shortened_printed = None
        if re.search(r"Shortened\s*Course", head, re.I):
            shortened_printed = distances[1] if len(distances) > 1 else None

        legs, pending = [], None
        for match in MARK_OR_ROUNDING.finditer(body):
            if match.group("round"):
                if pending is None:
                    continue
                rounding = "starboard" if match.group("round").lower().startswith("st") else "port"
                legs.append(dict(pending, rounding=rounding))
                if pending["finish"]:
                    break          # the course ends here; anything after is prose
                pending = None
            elif match.group("finish"):
                pending = {"name": match.group(2), "number": match.group("fnum"), "finish": True}
            else:
                pending = {"name": match.group("name").strip(),
                           "number": match.group("num"), "finish": False}

        courses.append({
            "course_no": number,
            "distance_nm": distances[0] if distances else None,
            "shortened_printed": shortened_printed,
            "pendant": int(pendant.group(1)) if pendant else number,
            "wind_note": " ".join(wind.group(1).split()).title() if wind else None,
            "printed_legs": legs,
        })
    return courses


def build_course(series: str, parsed: dict, resolver: Resolver) -> dict:
    legs = []
    for leg in parsed["printed_legs"]:
        if leg["finish"]:
            legs.append({"finish": True, "line": FINISH_LINE, "rounding": leg["rounding"]})
        else:
            legs.append({"mark": resolver.resolve(leg["name"], leg["number"]),
                         "rounding": leg["rounding"]})
    if not legs or not legs[-1].get("finish"):
        raise SystemExit("%s course %s did not end at a finish leg; parse is wrong"
                         % (series, parsed["course_no"]))

    course = {
        "id": "%s-%d" % (series, parsed["course_no"]),
        "series": series,
        "division": DIVISION.get(series),
        "course_no": parsed["course_no"],
        "distance_nm": parsed["distance_nm"],
        "wind_note": parsed["wind_note"],
        "flags": {"division": DIVISION_FLAG.get(series),
                  "numeral": "pendant-%d" % parsed["pendant"]},
        "legs": legs,
    }
    if parsed["shortened_printed"] is not None:
        course["shortened_distance_nm"] = parsed["shortened_printed"]
    return course


def solve_shortened(course: dict, marks: dict, lines_doc: dict) -> None:
    """Which leg a shortened race ends at, if the printed figure says so clearly.

    Flag S means the next pass through the start/finish line ends the race, so the
    printed shortened distance should equal the running total at one of the legs. Take
    the closest, and only believe it if it is close.
    """
    printed = course.get("shortened_distance_nm")
    if printed is None:
        return
    running = course_module.cumulative_distances_nm(course, marks, lines_doc)
    if not running:
        return

    # Only legs that bring the boat back to the line can end a shortened race, so those
    # are the only candidates. Taking the nearest total over all legs instead picks a
    # mark out in the middle of the river whenever the arithmetic is a little off, which
    # is how this first read Div II course 2 as finishing at Sanders.
    outer = (lines_doc.get("start_finish") or {}).get("outer", {}).get("mark")
    candidates = [i for i, leg in enumerate(course["legs"])
                  if leg.get("mark") == outer or leg.get("finish")]
    if not candidates:
        course["shortened_note"] = (
            "Printed shortened distance %.2f nm, but no leg of this course returns to the "
            "line before the finish, so there is nowhere for a shortened race to end."
            % printed)
        return

    best = min(candidates, key=lambda i: abs(running[i] - printed))
    error_pct = (running[best] - printed) / printed * 100.0
    if abs(error_pct) <= SHORTENED_TOLERANCE_PCT:
        course["shortened_at"] = best
        course["shortened_note"] = (
            "Printed shortened distance %.2f nm matches the running total after leg %d "
            "(%.2f nm, %+.1f per cent)." % (printed, best + 1, running[best], error_pct))
    else:
        course["shortened_note"] = (
            "Printed shortened distance %.2f nm matches no leg boundary: the closest is "
            "after leg %d at %.2f nm, %+.1f per cent out. Recorded but not resolved to a "
            "leg, because a guess about where a race ends is worse than saying it is not "
            "known (DESIGN 11.6)." % (printed, best + 1, running[best], error_pct))


def shortened_summary(course: dict) -> str:
    if "shortened_distance_nm" not in course:
        return ""
    at = course.get("shortened_at")
    return "  shortened %.2f -> %s" % (
        course["shortened_distance_nm"],
        ("leg %d" % (at + 1)) if at is not None else "UNRESOLVED")


def control(parsed: list, committed: list) -> None:
    """The hand transcription is the truth the parser has to reproduce."""
    by_no = {c["course_no"]: c for c in committed}
    for course in parsed:
        want = by_no.get(course["course_no"])
        if want is None:
            raise SystemExit("control: no committed Frostbite course %d" % course["course_no"])
        if course["distance_nm"] != want["distance_nm"]:
            raise SystemExit("control: course %d printed %s, committed %s"
                             % (course["course_no"], course["distance_nm"], want["distance_nm"]))
        if len(course["printed_legs"]) != len(want["legs"]):
            raise SystemExit("control: course %d parsed %d legs, committed %d"
                             % (course["course_no"], len(course["printed_legs"]), len(want["legs"])))
        for i, (got, expected) in enumerate(zip(course["printed_legs"], want["legs"]), 1):
            if got["rounding"] != expected["rounding"]:
                raise SystemExit("control: course %d leg %d rounding %s, committed %s"
                                 % (course["course_no"], i, got["rounding"], expected["rounding"]))
            if got["finish"] != bool(expected.get("finish")):
                raise SystemExit("control: course %d leg %d finish mismatch"
                                 % (course["course_no"], i))
    print("control: the parser reproduces all %d committed Frostbite courses" % len(parsed))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    args = parser.parse_args(argv)

    try:
        import pymupdf
    except ImportError:
        raise SystemExit("PyMuPDF is needed to read the PDF: pip install pymupdf")

    doc = pymupdf.open(str(PDF))
    marks_doc = json.loads(MARKS.read_text(encoding="utf-8"))
    lines_doc = json.loads(LINES.read_text(encoding="utf-8"))
    existing = json.loads(COURSES.read_text(encoding="utf-8"))
    resolver = Resolver(marks_doc)
    marks = course_module.index_marks(marks_doc)

    keep = [c for c in existing["courses"] if c["series"] == "frostbite"]
    built = list(keep)

    for sheet in SHEETS:
        parsed = parse_sheet(doc[sheet["page"]].get_text())
        if sheet.get("control"):
            control(parsed, keep)
            continue
        print("\n%s (page %d): %d courses" % (sheet["series"], sheet["page"], len(parsed)))
        for entry in parsed:
            course = build_course(sheet["series"], entry, resolver)
            solve_shortened(course, marks, lines_doc)
            summed = course_module.course_distance_nm(course, marks, lines_doc)
            printed = course["distance_nm"]
            print("  %-18s %2d legs  printed %5.2f  summed %5.2f  %+5.1f%%%s"
                  % (course["id"], len(course["legs"]), printed, summed,
                     (summed - printed) / printed * 100.0,
                     shortened_summary(course)))
            built.append(course)

    doc_out = dict(existing)
    doc_out["series"] = dict(existing.get("series", {}))
    doc_out["series"].update(SERIES)
    doc_out["courses"] = built
    doc_out["source"] = ("docs/reference/Sailing Fixtures & Courses 2026 - 2027.pdf, "
                         "pages 15-20 (course sheets)")
    doc_out["note"] = existing["note"]

    problems = course_module.validate(marks_doc, doc_out, lines_doc)
    errors = course_module.errors(problems)
    print("\n%d courses, %d series" % (len(built), len(doc_out["series"])))
    for problem in course_module.warnings(problems):
        print("  warning: %s" % (problem,))
    for problem in errors:
        print("  ERROR:   %s" % (problem,))
    if errors:
        raise SystemExit("refusing to write: the result does not validate")

    if args.dry_run:
        print("\ndry run, nothing written")
        return 0
    COURSES.write_text(json.dumps(doc_out, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    print("\nwrote %s" % COURSES.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
