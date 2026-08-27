# -*- coding: utf-8 -*-
"""Generate config/marks.json from the redigitized QGIS mark layer.

    cd config && python ../scripts/gen_marks.py

Positions come from the geometry of docs/qgis/Swan River Marks/
Swan_marks_YWA_SRRC_Sep2019.shp, which is the September 2019 YWA SRRC register
redigitized by hand in QGIS. That redigitization is now the truth for where a mark is.

An earlier version of this script read the register's own .xls directly, and those
positions were not all accurate: comparing the layer's geometry against the LAT and LON
columns it still carries from the spreadsheet, 61 of 142 marks moved, by a median of 15 m
and up to 135 m. The .xls stays in docs/reference as provenance, and is no longer read.

Everything except position still comes from the register, because the layer carries the
register's own columns:

    YWA_NAME   the "Yachting WA Number/Name" string, which packs number, name and
               rounding into one irregular field and is parsed here exactly as before
    NAV_NAME   the Department of Transport navigation-mark name, for marks that have one
    NAV_TYPE   structure and top mark, e.g. "Spar Buoy", "Beacon Port Lit"
    OWNER      the owning club, or DoT
    MARK_CLS   racing, or the lateral class of a navigation mark
    LAT, LON   the register's original coordinates, kept for comparison. NOT read for
               position: that is what the geometry is for.

The twenty marks used by the 2026-27 PFSYC course sheets are mapped explicitly by their
exact register string rather than by regex, and this fails loudly if any of them stops
resolving. Do not relax that: config/courses.json keys on these ids, and a mark that
silently changes id takes a course leg with it.
"""

import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shapefile  # noqa: E402

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
LAYER = PROJECT / "docs" / "qgis" / "Swan River Marks" / "Swan_marks_YWA_SRRC_Sep2019"

SOURCE_ID = "ywa-srrc-2019-qgis"
SOURCE_NOTE = ("Positions are from the September 2019 YWA SRRC register redigitized in "
               "QGIS (docs/qgis/Swan River Marks/), in GDA94 geographic coordinates. "
               "GDA94 differs from present-epoch WGS84 by about 1.8 m in this part of "
               "Australia, which is below GPS scatter and applies to every mark alike, so "
               "it is recorded rather than corrected. Names, numbers, rounding, owner and "
               "structure are the register's own, carried in the layer's attributes. "
               "Number is display only and is NOT unique: 37, 38, 39, 45 and 52 are each "
               "used by more than one mark. Always key on id.")

BBOX = dict(south=-32.030346, west=115.748, north=-31.959052, east=115.856573)

# Marks used by PFSYC 2026-27 course sheets.
# key = exact YWA_NAME value ; value = (id, number, display name, aliases)
COURSE_MARKS = {
 "32 Armstrong Port":            ("armstrong-32","32","Armstrong",["Armstrong Buoy"]),
 "74 Bishop Port":               ("bishop-74","74","Bishop",["Bishop Buoy"]),
 "38 BOND SPIT Port":            ("bond-38a","38A","Bond",["Bond Buoy","Bond Spit","Bond Buoy (38)"]),
 "33a Bricklanding A Starboard": ("bricklanding-a-33a","33A","Bricklanding A",["Bricklanding A Buoy"]),
 "33b Bricklanding B Starboard": ("bricklanding-b-33b","33B","Bricklanding B",["Bricklanding B Buoy"]),
 "32A PFSYC Start Outer Start":  ("club-32a","32A","Club Buoy",["PFSYC Start Outer","Club Buoy (32A)","Finish"]),
 "38 Dee Rd Port as of 1Sep19":  ("dee-rd-38","38","Dee Rd",["Dee Rd Buoy","Dee Road Buoy"]),
 "42B Dolphin East Starboard":   ("dolphin-east-42b","42B","Dolphin East",["Dolphin East Buoy"]),
 "42A Dolphin West Starboard":   ("dolphin-west-42a","42A","Dolphin West",["Dolphin West Buoy","DW Gate"]),
 "30 Dome Port":                 ("dome-30","30","Dome",["Dome Buoy"]),
 "55 Foam Starboard":            ("foam-55","55","Foam",["Foam Buoy"]),
 "41A Hallmark Port":            ("hallmark-41a","41A","Hallmark",["Hallmark Buoy","Hall Mark Buoy"]),
 "35b Lucky Bay  Port":          ("lucky-bay-35b","35B","Lucky Bay",["Lucky Bay Buoy"]),
 "28 Miller Port":               ("miller-28","28","Miller",["Miller Buoy"]),
 "14 Mosman Port":               ("mosman-a-14","14","Mosman A",["Mosman A Buoy","Mosman"]),
 "13 Suicide Port":              ("mosman-b-13","13","Mosman B",["Mosman B Buoy","Suicide","Suicide Buoy"]),
 "59 Robins Starboard":          ("robins-59","59","Robins",["Robins Buoy"]),
 "99 Sanders Starboard":         ("sanders-99","99","Sanders",["Sanders Buoy","Sanders (99)"]),
 "35a Smith Port":               ("smith-35a","35A","Smith",["Smith Buoy"]),
 "37 Squadron Port":             ("squadron-37","37","Squadron",["Squadron Buoy"]),
 # The Parmelia Night Race, from its own sailing instructions rather than the fixtures
 # sheet. Thirteen more marks, most of them fixed river navigation marks rather than club
 # racing buoys, which is why they were not in this table before.
 #
 # They are here for one visible reason: used_in_courses below is what makes a mark draw at
 # course size with a priority label instead of as a context speck, and a night race down
 # to Blackwall Reach is precisely when the crew needs to find them. The ids are the ones
 # the register already generated, so config/courses.json keeps working unchanged.
 "11 Blackwall Port":            ("blackwall-11","11","Blackwall",["Blackwall Buoy"]),
 "58 BURNSIDE SPIT Starboard":   ("burnside-spit-58","58","Burnside Spit",["Burnside"]),
 "21A CYC Start Outer Start":    ("cyc-start-outer-21a","21A","CYC Start Outer",
                                  ["CYC Outer Start Buoy","CYC Outer"]),
 "Point Resolution Port Beacon": ("point-resolution-port-beacon",None,"Point Resolution",
                                  ["Point Resolution Spit","Pt Resolution"]),
 "17 OUTER DOLPHIN Port":        ("outer-dolphin-17","17","Outer Dolphin",["Outer Dolphin"]),
 "16 INNER DOLPHIN":             ("inner-dolphin-16","16","Inner Dolphin",["Inner Dolphin"]),
 "45 Crawley Port":              ("crawley-45","45","Crawley",["Crawley Buoy"]),
 "14 KNOT SPIT Starboard":       ("knot-spit-14","14","Knot Spit",["Knot"]),
 "15 CONCRETE SPIT Starboard":   ("concrete-spit-15","15","Concrete Spit",["Concrete"]),
 "18 FOAM Starboard":            ("foam-18","18","Foam Spit",["Foam Spit (18)"]),
 "22 HEATHCOTE SPIT":            ("heathcote-spit-22","22","Heathcote Spit",["Heathcote"]),
 "# SoPYC Start Outer Start":    ("sopyc-start-outer",None,"SoPYC Start Outer",
                                  ["SOPYC Outer Start Buoy","SoPYC Outer"]),
 "36 ARMSTRONG SPIT Starboard":  ("armstrong-spit-36","36","Armstrong Spit",
                                  ["Armstrong Spit (36)"]),
}

# The PFSYC inner start mark, which the register itself has no row for. DESIGN 6 recorded
# it as hand-supplied and worth re-surveying; the QGIS layer now carries a digitized one,
# 47 m from that guess. gen_lines.py reads it from marks.json by this id.
START_INNER = ("PFSYC Start Inner Start",
               ("pfsyc-start-inner", None, "PFSYC start inner", ["Start box", "Inner start"]))

ROUNDING = {"port": "port", "starboard": "starboard", "start": None}


def slug(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return re.sub(r"-+", "-", text)


def parse_label(raw):
    """Split '38 Dee Rd Port as of 1Sep19' into number, name, rounding, note.

    The register packs four things into one column and is inconsistent about all of them:
    mixed case in numbers (33a against 42B), doubled spaces, '#' for an unnumbered start
    mark, and free-text status appended after the rounding word.
    """
    text = re.sub(r"\s+", " ", str(raw)).strip()
    note = None
    for pattern in (r"\s+as of \S+$", r"\s+Check location$", r"\s+removed$"):
        found = re.search(pattern, text)
        if found:
            note = found.group(0).strip()
            text = text[:found.start()].strip()
    number = None
    found = re.match(r"^(#|\d+[A-Za-z]?)\s+(.*)$", text)
    if found:
        number = None if found.group(1) == "#" else found.group(1).upper()
        text = found.group(2)
    rounding = None
    found = re.search(r"\b(Port|Starboard|Start)\s*$", text, re.I)
    if found:
        rounding = ROUNDING[found.group(1).lower()]
        text = text[:found.start()].strip()
    return number, text, rounding, note


def in_bbox(lat, lon):
    return (BBOX["south"] <= lat <= BBOX["north"]
            and BBOX["west"] <= lon <= BBOX["east"])


def main():
    layer = shapefile.read_layer(LAYER)
    print("read %d records from %s" % (len(layer), LAYER.name))

    marks = {}
    outside = duplicates = no_geometry = 0
    for point, row in layer:
        if point is None:
            no_geometry += 1
            continue
        lon, lat = point           # shapefiles store x then y
        if not in_bbox(lat, lon):
            outside += 1
            continue

        label = (row.get("YWA_NAME") or "").strip()
        nav_name = (row.get("NAV_NAME") or "").strip()
        number, name, rounding, note = parse_label(label) if label else (None, nav_name, None, None)
        if not name:
            name = nav_name or label
        if not name:
            continue

        known = COURSE_MARKS.get(label)
        course_mark = known is not None
        if known is None and nav_name:
            # Fall back to the Department of Transport name. The register's YWA_NAME column
            # is the club's own numbering and is empty for a DoT navigation mark, so a
            # course that rounds one cannot be keyed the usual way: the Parmelia night race
            # rounds the Point Resolution port beacon, which has no YWA_NAME at all.
            # Narrow by construction, since it only matches when a COURSE_MARKS key is
            # spelled exactly like a NAV_NAME, and no club buoy is.
            known = COURSE_MARKS.get(nav_name)
            course_mark = known is not None
        if label == START_INNER[0]:
            # Supplied, not a course mark: it is the inner end of the start line.
            known = START_INNER[1]
            course_mark = False
        if known:
            mark_id, number, name, aliases = known
        else:
            mark_id = slug("%s %s" % (name, number or ""))
            aliases = []

        if mark_id in marks:
            # An exact duplicate is a digitizing artifact and harmless; two different
            # positions under one id is a data fault and must not be silently resolved.
            existing = marks[mark_id]
            if abs(existing["lat"] - round(lat, 7)) > 1e-7 or abs(existing["lon"] - round(lon, 7)) > 1e-7:
                raise SystemExit("id %r appears twice at different positions: %r and %r"
                                 % (mark_id, (existing["lat"], existing["lon"]), (lat, lon)))
            duplicates += 1
            continue

        marks[mark_id] = {
            "id": mark_id,
            "number": number,
            "name": name,
            "aliases": aliases,
            "lat": round(lat, 7),
            "lon": round(lon, 7),
            "rounding": rounding,
            "owner": (row.get("OWNER") or "").strip() or None,
            "type": (row.get("NAV_TYPE") or "").strip() or None,
            "mark_class": (row.get("MARK_CLS") or "").strip() or None,
            "nav_name": nav_name or None,
            # Whether COURSE_MARKS claimed this mark, by either key. This used to test
            # `label in COURSE_MARKS`, which silently excluded anything matched on its DoT
            # name instead: the Point Resolution beacon took its curated name and aliases
            # and still drew as a context speck.
            "used_in_courses": course_mark,
            "source": SOURCE_ID,
            "source_label": label or nav_name,
        }
        if note:
            marks[mark_id]["source_note"] = note

    missing = [label for label in COURSE_MARKS
               if label not in {m["source_label"] for m in marks.values()}]
    if missing:
        raise SystemExit("course marks missing from the layer, refusing to write:\n  "
                         + "\n  ".join(repr(m) for m in missing))
    if START_INNER[1][0] not in marks:
        raise SystemExit("%r is not in the layer, so there is no PFSYC inner start mark"
                         % START_INNER[0])

    document = {
        "schema": "pfsyc-marks/2",
        "generated_from": "Swan_marks_YWA_SRRC_Sep2019.shp (QGIS redigitization of the "
                          "YWA SRRC September 2019 register)",
        "source_note": SOURCE_NOTE,
        "bbox": BBOX,
        "marks": [marks[k] for k in sorted(marks)],
    }
    Path("marks.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    used = sum(1 for m in marks.values() if m["used_in_courses"])
    print("wrote marks.json: %d marks, %d used in current courses" % (len(marks), used))
    print("  skipped %d outside the bbox, %d exact duplicates, %d without geometry"
          % (outside, duplicates, no_geometry))
    owners = Counter(m["owner"] for m in marks.values())
    print("  owners: " + ", ".join("%s %d" % (o or "unknown", n) for o, n in owners.most_common()))


if __name__ == "__main__":
    main()
