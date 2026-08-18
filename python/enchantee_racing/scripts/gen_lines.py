import json, math

marks = {m["id"]: m for m in json.load(open('marks.json'))["marks"]}

def enu(a, b):
    lat0 = math.radians((a["lat"] + b["lat"]) / 2)
    dn = (b["lat"] - a["lat"]) * 111320.0
    de = (b["lon"] - a["lon"]) * 111320.0 * math.cos(lat0)
    return math.hypot(dn, de), math.degrees(math.atan2(de, dn)) % 360

INNER = {"lat": -32.001948, "lon": 115.812006}

doc = {
  "schema": "pfsyc-lines/1",
  "start_finish": {
    "id": "pfsyc-start-finish",
    "name": "PFSYC start / finish line",
    "inner": {
      "name": "Start box",
      "lat": INNER["lat"], "lon": INNER["lon"],
      "source": "user-supplied-2026",
      "note": "Not in the YWA register, which has no PFSYC inner start mark. Re-survey from the jetty to confirm."
    },
    "outer": {
      "mark": "club-32a",
      "lat": marks["club-32a"]["lat"], "lon": marks["club-32a"]["lon"],
      "source": marks["club-32a"]["source"]
    },
    "warning": ("club-32a is also a mid-course mark in most courses, so boats cross this line "
                "repeatedly while racing. Arm finish detection only after the final leg completes.")
  },
  "gates": [
    {"id": "bricklanding", "name": "Bricklanding", "marks": ["bricklanding-a-33a","bricklanding-b-33b"],
     "rounding": "starboard", "no_cross_while_racing": True,
     "note": "Sailing instructions forbid crossing the imaginary line between Bricklanding A and B."},
    {"id": "smith-lucky-bay", "name": "Smith / Lucky Bay", "marks": ["smith-35a","lucky-bay-35b"],
     "rounding": "port", "no_cross_while_racing": True,
     "note": "Sailing instructions forbid crossing the imaginary line between Smith and Lucky Bay."},
    {"id": "mosman", "name": "Mosman", "marks": ["mosman-a-14","mosman-b-13"],
     "rounding": "port", "no_cross_while_racing": False,
     "note": "Always sailed as a pair (14 then 13) in the course sheets."}
  ]
}

sf = doc["start_finish"]
L, B = enu(sf["inner"], sf["outer"])
sf["length_m"] = round(L, 1)
sf["length_nm"] = round(L / 1852, 3)
sf["bearing_inner_to_outer"] = round(B, 1)

for g in doc["gates"]:
    a, b = marks[g["marks"][0]], marks[g["marks"][1]]
    L, B = enu(a, b)
    g["width_m"] = round(L, 1)
    g["midpoint"] = {"lat": round((a["lat"] + b["lat"]) / 2, 6),
                     "lon": round((a["lon"] + b["lon"]) / 2, 6)}

json.dump(doc, open('lines.json','w'), indent=2)
print("start/finish %.1f m  bearing %.1f / %.1f" % (sf["length_m"], sf["bearing_inner_to_outer"],
      (sf["bearing_inner_to_outer"] + 180) % 360))
for g in doc["gates"]:
    print("gate %-16s %6.1f m  mid %.6f %.6f" % (g["id"], g["width_m"], g["midpoint"]["lat"], g["midpoint"]["lon"]))
