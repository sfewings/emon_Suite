"""Generate config/navaids.json: every navigation aid in the mapped region.

Run with QGIS's own Python:

    "C:\\Program Files\\QGIS 4.2.1\\bin\\python-qgis.bat" scripts/gen_navaids.py

Source is Navigation Aids DoT (DOT-004), the authoritative WA register, CC BY 4.0,
IALA buoyage system A. 785 aids inside the coast.json extent.

Why not OSM, which already gave us the jetties: its seamark coverage here is
threadbare. The whole extent, Fremantle and Rottnest and Cockburn Sound included,
yields 9 lateral beacons, 11 minor lights, 3 major lights and 1 cardinal. DoT has
435 beacons, 329 buoys, 5 lighthouses and 52 leading marks. For the aid network
specifically, OSM is not a serious source.

The project already carried this layer as `Navigation Aids DoT (DOT-004)`, a WMS
picture. The same service exposes it as a real point feature layer at .../5, which
is where this comes from. Note the REST layer id is 5, not the 13 the WMS uses.

Leading marks are the reason this exists in its current shape. `Beacon Lead Front
Land Lit` and `Beacon Lead Rear Land Lit` are ON LAND and are transits you steer
by, so nothing here is clipped to water and the land ones are kept deliberately.

Overlap with marks.json is real and is flagged rather than dropped: 66 aids are
`Buoy Yacht` owned by the clubs, and many of those are the racing marks. Every
feature carries `dup_mark`, the id of a marks.json mark within DUP_RADIUS_M, or
null. The map page should draw an aid with `dup_mark` set only once.

Lights formerly came out of gen_structures.py as `kind=light` from OSM. That kind
has been removed there; navaids owns the aid network now, and structures owns the
built edge of the river.

ORIENTATION ONLY, NOT FOR NAVIGATION. This is a register extract, not a chart, and
carries no light characteristics, sectors or ranges. Notice to Mariners is a
separate DoT dataset (DOT-034) and is not consulted here.
"""
import json
import math
import os
import sys
import urllib.parse
import urllib.request

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qgis.core import (QgsApplication, QgsVectorLayer, QgsGeometry, QgsPointXY,
                       QgsFeature, QgsField, QgsVectorFileWriter,
                       QgsCoordinateTransformContext)
from qgis.PyQt.QtCore import QVariant

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT_GPKG = os.path.join(REPO, "docs", "qgis", "swan_navaids.gpkg")
OUT_JSON = os.path.join(REPO, "config", "navaids.json")
CACHE = os.path.join(HERE, "_navaids_cache.json")

# Identical to gen_coast.py and gen_structures.py, on purpose.
WEST, EAST, SOUTH, NORTH = 115.40, 116.00, -32.32, -31.86
DUP_RADIUS_M = 25.0

SERVICE = ("https://services.slip.wa.gov.au/public/rest/services/"
           "SLIP_Public_Services/Transport/MapServer/5/query")
PAGE = 1000

# Ordered: first match wins, so the specific cases sit above the general ones.
# Colours follow IALA A, port red and starboard green, with the land transits in
# orange because they are the ones you line up rather than pass.
RULES = [
    ("lighthouse",      lambda f, s: s == "LIGHTHOUSE",                 "#d92b1f", "Lighthouse"),
    ("ais",             lambda f, s: f.startswith("AIS"),               "#8a5fd0", "AIS / virtual"),
    ("leading",         lambda f, s: "Lead" in f,                       "#e07b00", "Leading mark"),
    ("light_major",     lambda f, s: f == "Major Light",                "#d92b1f", "Major light"),
    ("light_minor",     lambda f, s: f == "Minor Light",                "#e2574c", "Minor light"),
    ("racon",           lambda f, s: "Racon" in f,                      "#8a5fd0", "Racon"),
    ("beacon_cardinal", lambda f, s: s == "BEACON" and "Cardinal" in f, "#f0c020", "Cardinal beacon"),
    ("beacon_danger",   lambda f, s: s == "BEACON" and "Isolated" in f, "#222222", "Isolated danger beacon"),
    ("beacon_port",     lambda f, s: s == "BEACON" and "Port" in f,     "#cc2222", "Port beacon"),
    ("beacon_starboard", lambda f, s: s == "BEACON" and "Starboard" in f, "#1f8f3a", "Starboard beacon"),
    ("beacon_special",  lambda f, s: s == "BEACON" and "Special" in f,  "#f0c020", "Special mark beacon"),
    ("beacon_other",    lambda f, s: s == "BEACON",                     "#6d6d6d", "Beacon"),
    ("buoy_cardinal",   lambda f, s: "Cardinal" in f,                   "#f0c020", "Cardinal buoy"),
    ("buoy_danger",     lambda f, s: "Isolated" in f,                   "#222222", "Isolated danger buoy"),
    ("buoy_port",       lambda f, s: "Port" in f,                       "#cc2222", "Port buoy"),
    ("buoy_starboard",  lambda f, s: "Starboard" in f,                  "#1f8f3a", "Starboard buoy"),
    ("buoy_special",    lambda f, s: "Special" in f,                    "#f0c020", "Special mark buoy"),
    ("buoy_yacht",      lambda f, s: "Yacht" in f,                      "#3a7ca8", "Yacht racing buoy"),
    ("buoy_other",      lambda f, s: "Buoy" in f,                       "#6d6d6d", "Buoy"),
    ("other",           lambda f, s: True,                              "#999999", "Other"),
]
KIND_STYLE = {k: {"color": c, "label": lb} for k, _, c, lb in RULES}


def classify(func, structure):
    f = func or ""
    s = (structure or "").upper()
    for kind, test, _c, _l in RULES:
        if test(f, s):
            return kind
    return "other"


def is_lit(func):
    f = func or ""
    if "Unlit" in f:
        return False
    if "Lit" in f or f in ("Major Light", "Minor Light", "Lighthouse"):
        return True
    return False


def fetch():
    if os.path.exists(CACHE):
        print("using cached register: %s" % CACHE)
        return json.load(open(CACHE, encoding="utf-8"))
    env = {"xmin": WEST, "ymin": SOUTH, "xmax": EAST, "ymax": NORTH,
           "spatialReference": {"wkid": 4326}}
    feats, offset = [], 0
    while True:
        q = {
            "geometry": json.dumps(env),
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326", "outSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "*", "returnGeometry": "true",
            "resultOffset": str(offset), "resultRecordCount": str(PAGE),
            "f": "json",
        }
        url = SERVICE + "?" + urllib.parse.urlencode(q)
        print("fetching offset %d ..." % offset)
        with urllib.request.urlopen(url, timeout=180) as r:
            page = json.loads(r.read().decode("utf-8"))
        got = page.get("features", [])
        feats.extend(got)
        if len(got) < PAGE or not page.get("exceededTransferLimit"):
            break
        offset += PAGE
    doc = {"features": feats}
    with open(CACHE, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    print("cached %d aids" % len(feats))
    return doc


def load_marks():
    p = os.path.join(REPO, "config", "marks.json")
    return json.load(open(p, encoding="utf-8"))["marks"]


def metres(lon1, lat1, lon2, lat2):
    lat0 = math.radians((lat1 + lat2) / 2.0)
    dx = (lon2 - lon1) * 111320.0 * math.cos(lat0)
    dy = (lat2 - lat1) * 110540.0
    return math.hypot(dx, dy)


def main():
    raw = fetch()
    marks = load_marks()
    print("aids: %d   marks to check against: %d" % (len(raw["features"]), len(marks)))

    lyr = QgsVectorLayer("Point?crs=EPSG:4326", "navaids", "memory")
    lyr.dataProvider().addAttributes([
        QgsField("kind", QVariant.String),
        QgsField("name", QVariant.String),
        QgsField("func", QVariant.String),
        QgsField("structure", QVariant.String),
        QgsField("owner", QVariant.String),
        QgsField("lit", QVariant.Int),
        QgsField("navaidid", QVariant.String),
        QgsField("dup_mark", QVariant.String),
    ])
    lyr.updateFields()

    counts, lit_n, dup_n, skipped = {}, 0, 0, 0
    feats = []
    for f in raw["features"]:
        a = f.get("attributes", {})
        g = f.get("geometry") or {}
        lon, lat = g.get("x"), g.get("y")
        if lon is None or lat is None:
            skipped += 1
            continue
        kind = classify(a.get("functiondesc"), a.get("markstructure"))
        lit = is_lit(a.get("functiondesc"))
        dup = None
        for m in marks:
            if metres(lon, lat, m["lon"], m["lat"]) <= DUP_RADIUS_M:
                dup = m["id"]
                break
        counts[kind] = counts.get(kind, 0) + 1
        lit_n += 1 if lit else 0
        dup_n += 1 if dup else 0
        nf = QgsFeature(lyr.fields())
        nf.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
        nf.setAttributes([kind, a.get("navaiddesc"), a.get("functiondesc"),
                          a.get("markstructure"), a.get("owner"),
                          1 if lit else 0, a.get("navaidid"), dup])
        feats.append(nf)
    lyr.dataProvider().addFeatures(feats)
    lyr.updateExtents()

    print("by kind:")
    for k in sorted(counts, key=lambda k: -counts[k]):
        print("   %-18s %4d   %s" % (k, counts[k], KIND_STYLE[k]["label"]))
    print("lit: %d of %d   duplicating a marks.json mark: %d   no geometry: %d"
          % (lit_n, lyr.featureCount(), dup_n, skipped))
    write(lyr, counts, lit_n, dup_n)


def write(lyr, counts, lit_n, dup_n):
    doc = {
        "schema": "pfsyc-navaids/1",
        "generated_from": SERVICE,
        "license": "CC BY 4.0, Department of Transport, Western Australia",
        "dataset": "Navigation Aids DoT (DOT-004), IALA buoyage system A",
        "source_note": (
            "Every navigation aid in the mapped extent, from the authoritative DoT "
            "register rather than OSM, whose seamark coverage here is threadbare. "
            "Leading marks are included and are often ON LAND, because a transit is "
            "steered by whether or not it floats; nothing is clipped to water. "
            "%d aids sit within %d m of a mark in marks.json and carry dup_mark, so "
            "the map can avoid drawing them twice. "
            "ORIENTATION ONLY, NOT FOR NAVIGATION: a register extract, not a chart. "
            "No light characteristics, sectors or ranges, and Notice to Mariners "
            "(DOT-034) is not consulted."
            % (dup_n, int(DUP_RADIUS_M))),
        "bbox": {"south": SOUTH, "west": WEST, "north": NORTH, "east": EAST},
        "kinds": KIND_STYLE,
        "counts": counts,
        "lit_count": lit_n,
        "type": "FeatureCollection",
        "features": [],
    }
    for f in lyr.getFeatures():
        doc["features"].append({
            "type": "Feature",
            "properties": {
                "kind": f["kind"], "name": f["name"], "func": f["func"],
                "structure": f["structure"], "owner": f["owner"],
                "lit": bool(f["lit"]), "navaidid": f["navaidid"],
                "dup_mark": f["dup_mark"] or None,
            },
            "geometry": json.loads(f.geometry().asJson(5)),
        })
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    print("wrote %s (%d bytes, %d features)"
          % (OUT_JSON, os.path.getsize(OUT_JSON), len(doc["features"])))

    stage = OUT_GPKG[:-5] + ".new.gpkg"      # driver forces .gpkg
    if os.path.exists(stage):
        os.remove(stage)
    o = QgsVectorFileWriter.SaveVectorOptions()
    o.driverName = "GPKG"
    o.layerName = "navaids"
    o.fileEncoding = "UTF-8"
    QgsVectorFileWriter.writeAsVectorFormatV3(lyr, stage,
                                              QgsCoordinateTransformContext(), o)
    try:
        os.replace(stage, OUT_GPKG)
        print("wrote %s (%d bytes)" % (OUT_GPKG, os.path.getsize(OUT_GPKG)))
    except OSError as e:
        print("COULD NOT REPLACE %s: %s" % (OUT_GPKG, e))
        print("   it is open in QGIS. The new one is %s" % stage)


if __name__ == "__main__":
    QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH",
                                                r"C:\Program Files\QGIS 4.2.1\apps\qgis"), True)
    app = QgsApplication([], False)
    app.initQgis()
    main()
    app.exitQgis()
