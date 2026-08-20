"""Generate config/lines.json from config/marks.json. Run from the config directory.

There are no gates. An earlier version of this script emitted a "gates" array
holding Bricklanding, Smith / Lucky Bay and Mosman as single legs with two mark
refs, targeted at their midpoints. That was wrong: each of those six marks is
rounded on its own and is its own leg. The sailing instructions forbid sailing
between the first two pairs, and the printed course distances only reconcile when
every mark is rounded in turn. See DESIGN.md section 6.

What is left is two kinds of line, neither of which is ever a leg target:

  start_finish     the one line the race actually crosses, and the finish test
  no_cross_lines   lines it is a rule breach to cross while racing

Mosman is deliberately absent. Nothing prohibits crossing between 14 and 13, so
there is no line to detect and nothing for the app to say about it.
"""
import json, math

marks = {m["id"]: m for m in json.load(open('marks.json'))["marks"]}

def enu(a, b):
    lat0 = math.radians((a["lat"] + b["lat"]) / 2)
    dn = (b["lat"] - a["lat"]) * 111320.0
    de = (b["lon"] - a["lon"]) * 111320.0 * math.cos(lat0)
    return math.hypot(dn, de), math.degrees(math.atan2(de, dn)) % 360

INNER_ID = "pfsyc-start-inner"
"""The inner end of the start line now comes from the mark data like everything else.

It used to be a hardcoded pair of coordinates supplied by hand, because the register has
inner start marks for RPYC and SoPYC but no row for PFSYC, and DESIGN 6 flagged it
user-supplied-2026 and worth re-surveying. The QGIS redigitization carries a digitized
PFSYC Start Inner Start, 47 m from that guess, so the guess is gone.
"""

doc = {
  "schema": "pfsyc-lines/2",
  "note": ("No gates: every course leg targets exactly one mark, except the last, which "
           "targets start_finish. no_cross_lines are for breach detection only and are "
           "never leg targets. Mosman (14, 13) is absent on purpose, see DESIGN.md section 6."),
  "start_finish": {
    "id": "pfsyc-start-finish",
    "name": "PFSYC start / finish line",
    "inner": {
      "mark": INNER_ID,
      "name": marks[INNER_ID]["name"],
      "lat": marks[INNER_ID]["lat"], "lon": marks[INNER_ID]["lon"],
      "source": marks[INNER_ID]["source"],
      "note": "The register has no row for a PFSYC inner start mark; this one is digitized in the QGIS layer."
    },
    "outer": {
      "mark": "club-32a",
      "lat": marks["club-32a"]["lat"], "lon": marks["club-32a"]["lon"],
      "source": marks["club-32a"]["source"]
    },
    "warning": ("club-32a is also a mid-course mark in most courses, so boats cross this line "
                "repeatedly while racing. Arm finish detection only after the final leg completes.")
  },
  "no_cross_lines": [
    {"id": "bricklanding", "name": "Bricklanding", "marks": ["bricklanding-a-33a","bricklanding-b-33b"],
     "note": ("Sailing instructions, Navigation Marks: boats that are racing are not permitted to "
              "cross an imaginary line between Bricklanding A and Bricklanding B. Both marks are "
              "rounded to starboard, one leg each.")},
    {"id": "smith-lucky-bay", "name": "Smith / Lucky Bay", "marks": ["smith-35a","lucky-bay-35b"],
     "note": ("Sailing instructions, Navigation Marks: boats that are racing are not permitted to "
              "cross an imaginary line between Smith Buoy and Lucky Bay Buoy. Both marks are "
              "rounded to port, one leg each.")}
  ]
}

sf = doc["start_finish"]
L, B = enu(sf["inner"], sf["outer"])
sf["length_m"] = round(L, 1)
sf["length_nm"] = round(L / 1852, 3)
sf["bearing_inner_to_outer"] = round(B, 1)

for line in doc["no_cross_lines"]:
    a, b = marks[line["marks"][0]], marks[line["marks"][1]]
    L, B = enu(a, b)
    line["length_m"] = round(L, 1)

json.dump(doc, open('lines.json','w'), indent=2)
print("start/finish %.1f m  bearing %.1f / %.1f" % (sf["length_m"], sf["bearing_inner_to_outer"],
      (sf["bearing_inner_to_outer"] + 180) % 360))
for line in doc["no_cross_lines"]:
    print("no-cross %-16s %6.1f m" % (line["id"], line["length_m"]))
