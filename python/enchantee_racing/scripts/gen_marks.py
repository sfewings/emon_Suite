# -*- coding: utf-8 -*-
"""Generate config/marks.json and config/lines.json from the YWA SRRC register."""
import pandas as pd, json, math, re, unicodedata
from collections import Counter

SRC = '/mnt/user-data/uploads/6kavqmsveqfnyw2m.xls'
SOURCE_ID = "ywa-srrc-2019"

BBOX = dict(south=-32.030346, west=115.748, north=-31.959052, east=115.856573)

# Marks used by PFSYC 2026-27 course sheets.
# key = exact spreadsheet column C value ; value = (id, number, display name, aliases)
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
}

ROUNDING = {"port":"port","starboard":"starboard","start":None}

def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii","ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+","-", s).strip("-").lower()
    return re.sub(r"-+","-",s)

def parse_label(raw):
    """Split '38 Dee Rd Port as of 1Sep19' into number, name, rounding, note."""
    t = re.sub(r"\s+"," ", str(raw)).strip()
    note = None
    for pat in [r"\s+as of \S+$", r"\s+Check location$", r"\s+removed$"]:
        m = re.search(pat, t)
        if m:
            note = m.group(0).strip(); t = t[:m.start()].strip()
    num = None
    m = re.match(r"^(#|\d+[A-Za-z]?)\s+(.*)$", t)
    if m:
        num = None if m.group(1) == "#" else m.group(1).upper()
        t = m.group(2)
    rounding = None
    m = re.search(r"\b(Port|Starboard|Start)\s*$", t, re.I)
    if m:
        rounding = ROUNDING[m.group(1).lower()]
        t = t[:m.start()].strip()
    return num, t, rounding, note

def in_bbox(lat, lon):
    return BBOX["south"] <= lat <= BBOX["north"] and BBOX["west"] <= lon <= BBOX["east"]

df = pd.read_excel(SRC, header=0)
marks, skipped, no_pos = [], [], []
seen_ids = set()

for _, r in df.iterrows():
    label = r.iloc[2]
    if pd.isna(label):
        continue
    label = str(label).strip()
    lat, lon = r.iloc[4], r.iloc[5]
    if pd.isna(lat) or pd.isna(lon):
        no_pos.append(label); continue
    lat, lon = float(lat), float(lon)
    if not in_bbox(lat, lon):
        skipped.append(label); continue

    num, name, rounding, note = parse_label(label)
    if label in COURSE_MARKS:
        mid, num_c, name_c, aliases = COURSE_MARKS[label]
        num, name = num_c, name_c
        used = True
    else:
        mid = slug(f"{name}-{num}" if num else name)
        aliases, used = [], False
    if mid in seen_ids:
        mid = mid + "-2"
    seen_ids.add(mid)

    m = {
        "id": mid, "number": num, "name": name,
        "aliases": aliases,
        "lat": round(lat, 6), "lon": round(lon, 6),
        "rounding": rounding,
        "owner": None if pd.isna(r.iloc[3]) else str(r.iloc[3]).strip(),
        "type": None if pd.isna(r.iloc[0]) else str(r.iloc[0]).strip(),
        "used_in_courses": used,
        "source": SOURCE_ID,
        "source_label": label,
    }
    if note: m["note"] = note
    marks.append(m)

marks.sort(key=lambda m: m["id"])

# ---- validation -------------------------------------------------------
errs = []
found = {m["source_label"] for m in marks}
for lbl,(mid,*_ ) in COURSE_MARKS.items():
    if lbl not in found: errs.append(f"course mark not found in register: {lbl}")
dup = [k for k,v in Counter(m["id"] for m in marks).items() if v > 1]
if dup: errs.append(f"duplicate ids: {dup}")
numdup = [k for k,v in Counter(m["number"] for m in marks if m["number"]).items() if v > 1]

print("marks in bbox        :", len(marks))
print("course marks resolved:", sum(1 for m in marks if m["used_in_courses"]), "/", len(COURSE_MARKS))
print("outside bbox skipped :", len(skipped))
print("named but no position:", len(no_pos))
print("shared numbers       :", sorted(numdup))
print("errors               :", errs or "none")

with open('/home/claude/build/marks.json','w') as f:
    json.dump({
        "schema": "pfsyc-marks/1",
        "generated_from": "YWA SRRC VERSION Sept19 (Yachting WA / DoT navaid register)",
        "source_note": ("Positions are WGS84 decimal degrees from the September 2019 register. "
                        "Marks may have moved since; verify against recorded GPS tracks. "
                        "Number is display only and is NOT unique: 37, 38, 39, 45 and 52 are each "
                        "used by more than one mark. Always key on id."),
        "bbox": BBOX,
        "marks": marks,
    }, f, indent=2)
print("wrote marks.json")
