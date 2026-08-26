"""Store default QGIS styles inside the GeoPackages, so a fresh add looks right.

    "C:\\Program Files\\QGIS 4.2.1\\bin\\python-qgis.bat" scripts/apply_qgis_styles.py

QGIS reads a default style out of a GeoPackage's `layer_styles` table when a layer
is added, so embedding them here means nobody has to restyle by hand after
regenerating. It also keeps the desktop colours and the colours the app draws with
in one place: both come from the same dicts in the gen_*.py generators.

A layer already in an open project keeps the renderer the project saved, so after
running this, an existing layer needs Properties, Style, Load Style, From database,
or simply removing and re-adding it.

Writes are skipped with a message if QGIS has the GeoPackage open, same as the
generators.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qgis.core import (QgsApplication, QgsVectorLayer, QgsFillSymbol, QgsLineSymbol,
                       QgsMarkerSymbol, QgsCategorizedSymbolRenderer,
                       QgsRendererCategory)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
QGIS_DIR = os.path.join(REPO, "docs", "qgis")

DEPTH = os.path.join(QGIS_DIR, "swan_depth.gpkg")
STRUCT = os.path.join(QGIS_DIR, "swan_structures.gpkg")
NAVAIDS = os.path.join(QGIS_DIR, "swan_navaids.gpkg")
COAST = os.path.join(QGIS_DIR, "swan_coast.gpkg")

# Kept identical to BANDS in gen_depth.py. Shallowest darkest, chart convention.
DEPTH_BANDS = [("foreshore", "unsurveyed / foreshore", "#a8c66c"),
               ("shallow", "0 - 2 m", "#1f5c8b"),
               ("mid", "2 - 5 m", "#4e8fbd"),
               ("deep", "5 - 10 m", "#92c0dc"),
               ("deepest", "> 10 m", "#d8e9f5")]

# 2 m is the one that matters, so it is the loudest.
DEPTH_LINES = [(2.0, "2 m", "#0f3d5f", "0.5", "solid"),
               (5.0, "5 m", "#2f6f96", "0.35", "dash"),
               (10.0, "10 m", "#6098b8", "0.25", "dot")]

STRUCT_LINES = [("jetty", "Jetty / pier", "#6b5b45", "0.55"),
                ("breakwater", "Breakwater", "#5a5a5a", "0.7"),
                ("groyne", "Groyne", "#7a7a6a", "0.45"),
                ("slipway", "Slipway", "#8a7f6a", "0.45"),
                ("bridge", "Bridge", "#3f3f3f", "0.8")]

STRUCT_AREAS = [("jetty", "Jetty / pier", "#6b5b45"),
                ("breakwater", "Breakwater", "#5a5a5a"),
                ("marina", "Marina", "#9aa7b1")]

# Kept identical to RULES in gen_navaids.py. IALA A: port red, starboard green.
# Leading marks are orange because they are the ones you line up, not pass.
NAVAIDS_KINDS = [
    ("lighthouse",       "Lighthouse",              "#d92b1f", "star",     "4.5"),
    ("light_major",      "Major light",             "#d92b1f", "star",     "3.2"),
    ("light_minor",      "Minor light",             "#e2574c", "star",     "2.4"),
    ("leading",          "Leading mark",            "#e07b00", "triangle", "3.0"),
    ("beacon_port",      "Port beacon",             "#cc2222", "square",   "2.2"),
    ("beacon_starboard", "Starboard beacon",        "#1f8f3a", "square",   "2.2"),
    ("beacon_cardinal",  "Cardinal beacon",         "#f0c020", "diamond",  "2.4"),
    ("beacon_danger",    "Isolated danger beacon",  "#222222", "square",   "2.4"),
    ("beacon_special",   "Special mark beacon",     "#f0c020", "square",   "2.2"),
    ("beacon_other",     "Beacon",                  "#6d6d6d", "square",   "2.0"),
    ("buoy_port",        "Port buoy",               "#cc2222", "circle",   "2.2"),
    ("buoy_starboard",   "Starboard buoy",          "#1f8f3a", "circle",   "2.2"),
    ("buoy_cardinal",    "Cardinal buoy",           "#f0c020", "diamond",  "2.2"),
    ("buoy_danger",      "Isolated danger buoy",    "#222222", "circle",   "2.4"),
    ("buoy_special",     "Special mark buoy",       "#f0c020", "circle",   "2.2"),
    ("buoy_yacht",       "Yacht racing buoy",       "#3a7ca8", "circle",   "1.8"),
    ("buoy_other",       "Buoy",                    "#6d6d6d", "circle",   "2.0"),
    ("ais",              "AIS / virtual",           "#8a5fd0", "pentagon", "2.4"),
    ("racon",            "Racon",                   "#8a5fd0", "pentagon", "2.4"),
    ("other",            "Other",                   "#999999", "circle",   "1.8"),
]


def categorized(field, cats):
    return QgsCategorizedSymbolRenderer(field, cats)


def save(path, layername, renderer, label):
    if not os.path.exists(path):
        print("   MISSING %s" % path)
        return False
    lyr = QgsVectorLayer("%s|layername=%s" % (path, layername), layername, "ogr")
    if not lyr.isValid():
        print("   INVALID %s|%s" % (os.path.basename(path), layername))
        return False
    lyr.setRenderer(renderer)
    try:
        # V2 since QGIS 4.0; the old one is deprecated but is what 3.x has.
        if hasattr(lyr, "saveStyleToDatabaseV2"):
            lyr.saveStyleToDatabaseV2(layername, label, True, "")
        else:
            lyr.saveStyleToDatabase(layername, label, True, "")
    except Exception as e:                      # locked, or no write permission
        print("   COULD NOT WRITE STYLE for %s: %s" % (layername, e))
        return False
    print("   styled %-18s in %s" % (layername, os.path.basename(path)))
    return True


def main():
    print("depth:")
    save(DEPTH, "depth_bands",
         categorized("band", [
             QgsRendererCategory(v, QgsFillSymbol.createSimple(
                 {"color": c, "outline_style": "no"}), lb)
             for v, lb, c in DEPTH_BANDS]),
         "Foreshore plus depth bands 0-2 / 2-5 / 5-10 / >10 m below LWM")

    save(DEPTH, "depth_contours",
         categorized("depth_m", [
             QgsRendererCategory(v, QgsLineSymbol.createSimple(
                 {"color": c, "width": w, "width_unit": "Point", "line_style": s}), lb)
             for v, lb, c, w, s in DEPTH_LINES]),
         "Depth contours 2 / 5 / 10 m below LWM")

    print("structures:")
    save(STRUCT, "structure_lines",
         categorized("kind", [
             QgsRendererCategory(v, QgsLineSymbol.createSimple(
                 {"color": c, "width": w, "width_unit": "Point"}), lb)
             for v, lb, c, w in STRUCT_LINES]),
         "Jetties, breakwaters, groynes, slipways, bridges")

    save(STRUCT, "structure_areas",
         categorized("kind", [
             QgsRendererCategory(v, QgsFillSymbol.createSimple(
                 {"color": c, "outline_color": "60,55,45,255",
                  "outline_width": "0.2"}), lb)
             for v, lb, c in STRUCT_AREAS]),
         "Jetty, breakwater and marina areas")

    print("navaids:")
    save(NAVAIDS, "navaids",
         categorized("kind", [
             QgsRendererCategory(v, QgsMarkerSymbol.createSimple(
                 {"name": shape, "color": c, "size": sz,
                  "outline_color": "30,30,30,255", "outline_width": "0.2"}), lb)
             for v, lb, c, shape, sz in NAVAIDS_KINDS]),
         "Navigation aids, DoT DOT-004, IALA system A")

    print("coast:")
    save(COAST, "coast_land",
         categorized("kind", [
             QgsRendererCategory("land", QgsFillSymbol.createSimple(
                 {"color": "214,201,168,90", "outline_color": "60,45,25,255",
                  "outline_width": "0.5", "outline_width_unit": "Point"}), "Land")]),
         "Land, translucent so charts underneath stay readable")


if __name__ == "__main__":
    QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH",
                                                r"C:\Program Files\QGIS 4.2.1\apps\qgis"), True)
    app = QgsApplication([], False)
    app.initQgis()
    main()
    app.exitQgis()
