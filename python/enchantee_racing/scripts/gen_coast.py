"""Generate config/coast.json, the land polygons the map page draws under the course.

Run with QGIS's own Python, which has the processing framework and GDAL:

    "C:\\Program Files\\QGIS 4.2.1\\bin\\python-qgis.bat" scripts/gen_coast.py

DESIGN.md section 12 describes dissolving OSM `natural=water` into a water layer.
That works inside the river and fails the moment you leave it, because OSM does not
tag the open sea: everything west of the Fremantle coastline would come out as a
hole in the map. So this emits LAND instead, and derives the sea rather than
assuming it.

The method, and the two things that are easy to get wrong:

  1. Coastline ways are individually short, and none of them crosses the extent on
     its own, so splitting the extent by them one at a time does nothing. They have
     to be dissolved and merged first. Merged, the mainland coast is a single 109 km
     string that enters north of the extent and leaves south of it, which does cut
     the extent in two.
  2. Islands arrive two ways. Open coastline ways land in the OSM driver's `lines`
     layer; closed ones (Rottnest, Garden Island, Carnac) are auto-polygonised into
     `multipolygons`. Both have to go into the cutting set or the sea swallows the
     islands.

Faces are then classified by seeding known open water. Whatever no seed reaches is
land, which picks up every island for free. River and lake polygons are subtracted
afterwards.

Caveats that belong with any use of the output, and in the loader comment:

  - OSM banks are crowd-sourced. This is orientation only, it is not navigation.
  - It says nothing about sandbanks, which is where the actual trouble is on
    Melville Water.
  - Point Walter spit is submerged at higher tides and its presence in OSM depends
    on which imagery the mapper traced. Do not read it as reliable.

Deliberately NOT sourced from the Geng course marks chart in docs/reference/, which
is marked not for navigational use and is a copyright work. See DESIGN.md 12.
"""
import json
import os
import sys
import urllib.request

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qgis.core import (QgsApplication, QgsVectorLayer, QgsProject,
                       QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsRectangle, QgsGeometry, QgsFeature, QgsPointXY,
                       QgsField, QgsVectorFileWriter, QgsCoordinateTransformContext)
from qgis.PyQt.QtCore import QVariant

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.path.join(REPO, "config", "coast.json")
GPKG = os.path.join(REPO, "docs", "qgis", "swan_coast.gpkg")
CACHE = os.path.join(HERE, "_coast_osm_cache.osm")

# Wider than the marks.json racing bbox on purpose. It reaches Guildford at the top
# of the navigable Swan, out past Rottnest, and south over Garden Island and
# Cockburn Sound, so ocean races and the island anchorages are already covered and
# nobody has to regenerate this to sail somewhere ordinary.
WEST, EAST, SOUTH, NORTH = 115.40, 116.00, -32.32, -31.86

MIN_WATER_AREA = 5000.0   # m2. Drops swimming pools and ornamental ponds.
MIN_LAND_AREA = 2000.0    # m2. Drops digitising slivers.
SIMPLIFY_M = 10.0         # Douglas-Peucker tolerance. Set for a zoomed-in single-bay
                          # view at roughly 8 m per pixel, not for the full extent.

CRS4326 = QgsCoordinateReferenceSystem("EPSG:4326")
CRSPROJ = QgsCoordinateReferenceSystem("EPSG:7850")   # GDA2020 / MGA zone 50

# Every one of these must fall in open water. They are what makes a face "sea".
SEEDS = [(115.42, -32.05),   # ocean west of Rottnest
         (115.68, -32.03),   # Gage Roads
         (115.73, -32.10),   # Owen Anchorage
         (115.72, -32.20),   # Cockburn Sound
         (115.72, -31.88),   # coast off Trigg
         (115.50, -31.95)]   # ocean north of Rottnest

OVERPASS = "https://overpass-api.de/api/interpreter"
QUERY = """[out:xml][timeout:600];
(
  way["natural"="water"](%(s)f,%(w)f,%(n)f,%(e)f);
  relation["natural"="water"](%(s)f,%(w)f,%(n)f,%(e)f);
  way["waterway"="riverbank"](%(s)f,%(w)f,%(n)f,%(e)f);
  relation["waterway"="riverbank"](%(s)f,%(w)f,%(n)f,%(e)f);
  way["natural"="coastline"](%(s)f,%(w)f,%(n)f,%(e)f);
);
(._;>;);
out body;
"""

COASTLINE_FILTER = 'other_tags LIKE \'%"natural"=>"coastline"%\''
ISLAND_FILTER = '"natural" = \'coastline\''
WATER_FILTER = '"natural" = \'water\' OR other_tags LIKE \'%"waterway"=>"riverbank"%\''


def fetch_osm():
    """Download once and cache. The cache is what makes reruns offline-safe."""
    if os.path.exists(CACHE):
        print("using cached OSM extract: %s" % CACHE)
        return CACHE
    q = QUERY % {"s": SOUTH, "w": WEST, "n": NORTH, "e": EAST}
    print("querying Overpass ...")
    req = urllib.request.Request(OVERPASS, data=q.encode("utf-8"))
    with urllib.request.urlopen(req, timeout=900) as r, open(CACHE, "wb") as f:
        f.write(r.read())
    print("cached %d bytes to %s" % (os.path.getsize(CACHE), CACHE))
    return CACHE


def run(alg, params):
    p = dict(params)
    p.setdefault("OUTPUT", "memory:")
    return processing.run(alg, p)["OUTPUT"]


def mem(name, wkb, crs, geoms):
    lyr = QgsVectorLayer(wkb + "?crs=" + crs.authid(), name, "memory")
    feats = []
    for g in geoms:
        f = QgsFeature()
        f.setGeometry(g)
        feats.append(f)
    lyr.dataProvider().addFeatures(feats)
    lyr.updateExtents()
    return lyr


def build(osm_path):
    coast_lines = QgsVectorLayer(osm_path + "|layername=lines", "coast_lines", "ogr")
    coast_lines.setSubsetString(COASTLINE_FILTER)
    islands = QgsVectorLayer(osm_path + "|layername=multipolygons", "islands", "ogr")
    islands.setSubsetString(ISLAND_FILTER)
    water = QgsVectorLayer(osm_path + "|layername=multipolygons", "water", "ogr")
    water.setSubsetString(WATER_FILTER)

    # See docstring note 1: without the merge, nothing traverses the extent.
    merged = run("native:mergelines", {"INPUT": run("native:dissolve", {"INPUT": coast_lines})})
    island_lines = run("native:polygonstolines", {"INPUT": islands})

    coast_p = run("native:reprojectlayer", {"INPUT": merged, "TARGET_CRS": CRSPROJ})
    island_p = run("native:reprojectlayer", {"INPUT": island_lines, "TARGET_CRS": CRSPROJ})
    water_p = run("native:reprojectlayer", {"INPUT": water, "TARGET_CRS": CRSPROJ})

    xf = QgsCoordinateTransform(CRS4326, CRSPROJ, QgsProject.instance())
    box = QgsGeometry.fromRect(QgsRectangle(WEST, SOUTH, EAST, NORTH))
    box.transform(xf)

    cutters = run("native:mergevectorlayers", {"LAYERS": [coast_p, island_p], "CRS": CRSPROJ})
    faces = run("native:multiparttosingleparts",
                {"INPUT": run("native:splitwithlines",
                              {"INPUT": mem("bbox", "Polygon", CRSPROJ, [box]),
                               "LINES": cutters})})

    seeds = []
    for x, y in SEEDS:
        g = QgsGeometry.fromPointXY(QgsPointXY(x, y))
        g.transform(xf)
        seeds.append(g)

    sea, land = [], []
    for f in faces.getFeatures():
        g = QgsGeometry(f.geometry())
        if any(g.contains(p) for p in seeds):
            sea.append(g)
        else:
            land.append(g)
    if not sea:
        raise SystemExit("no face matched an open-water seed; check SEEDS against the extent")
    print("faces=%d  sea=%d (%.0f km2)  land=%d (%.0f km2)"
          % (faces.featureCount(), len(sea), sum(g.area() for g in sea) / 1e6,
             len(land), sum(g.area() for g in land) / 1e6))

    big_water = run("native:extractbyexpression",
                    {"INPUT": water_p, "EXPRESSION": "$area > %f" % MIN_WATER_AREA})
    water_dis = run("native:dissolve",
                    {"INPUT": run("native:fixgeometries", {"INPUT": big_water})})

    cut = run("native:difference",
              {"INPUT": run("native:fixgeometries",
                            {"INPUT": mem("land", "Polygon", CRSPROJ, land)}),
               "OVERLAY": water_dis})
    cut = run("native:multiparttosingleparts", {"INPUT": cut})
    cut = run("native:extractbyexpression",
              {"INPUT": cut, "EXPRESSION": "$area > %f" % MIN_LAND_AREA})

    simp = run("native:fixgeometries",
               {"INPUT": run("native:simplifygeometries",
                             {"INPUT": cut, "METHOD": 0, "TOLERANCE": SIMPLIFY_M})})
    final = run("native:dissolve",
                {"INPUT": run("native:reprojectlayer", {"INPUT": simp, "TARGET_CRS": CRS4326})})
    return QgsGeometry(next(final.getFeatures()).geometry())


def check(land_geom):
    """Every mark in the register must fall in water. This is the real test."""
    marks = json.load(open(os.path.join(REPO, "config", "marks.json"), encoding="utf-8"))["marks"]
    bad = [m for m in marks
           if land_geom.contains(QgsGeometry.fromPointXY(QgsPointXY(m["lon"], m["lat"])))]
    print("marks checked=%d  falling on land=%d" % (len(marks), len(bad)))
    for m in bad:
        print("   ON LAND: %s %s %.6f %.6f" % (m["id"], m["name"], m["lat"], m["lon"]))
    return bad


def write_outputs(land_geom):
    lyr = QgsVectorLayer("MultiPolygon?crs=EPSG:4326", "coast_land", "memory")
    lyr.dataProvider().addAttributes([QgsField("kind", QVariant.String)])
    lyr.updateFields()
    f = QgsFeature(lyr.fields())
    f.setGeometry(land_geom)
    f.setAttributes(["land"])
    lyr.dataProvider().addFeatures([f])
    lyr.updateExtents()

    # A GeoPackage for QGIS to point at, so the desktop project and the app agree.
    if os.path.exists(GPKG):
        os.remove(GPKG)
    gopts = QgsVectorFileWriter.SaveVectorOptions()
    gopts.driverName = "GPKG"
    gopts.layerName = "coast_land"
    gopts.fileEncoding = "UTF-8"
    QgsVectorFileWriter.writeAsVectorFormatV3(lyr, GPKG, QgsCoordinateTransformContext(), gopts)

    # The GeoJSON driver forces a .geojson extension, so write there and rename.
    stage = os.path.join(REPO, "config", "_coast_stage.geojson")
    for p in (stage, stage + ".geojson"):
        if os.path.exists(p):
            os.remove(p)
    jopts = QgsVectorFileWriter.SaveVectorOptions()
    jopts.driverName = "GeoJSON"
    jopts.fileEncoding = "UTF-8"
    jopts.layerOptions = ["COORDINATE_PRECISION=5", "RFC7946=NO"]
    res = QgsVectorFileWriter.writeAsVectorFormatV3(lyr, stage, QgsCoordinateTransformContext(), jopts)
    written = res[2] if len(res) > 2 and res[2] else stage
    if res[0] != QgsVectorFileWriter.NoError:
        raise SystemExit("GeoJSON write failed: %s" % (res,))

    doc = json.load(open(written, encoding="utf-8"))
    os.remove(written)

    out = {
        "schema": "pfsyc-coast/1",
        "generated_from": "OpenStreetMap via Overpass, %s" % OVERPASS,
        "license": "ODbL 1.0, (c) OpenStreetMap contributors",
        "source_note": (
            "Land polygons. Sea is derived by splitting the extent with the OSM coastline "
            "and classifying faces from open-water seeds, because OSM does not tag the open "
            "ocean and a dissolve of natural=water alone would render everything west of "
            "Fremantle as land. River and lake polygons above %d m2 are subtracted. "
            "Simplified with Douglas-Peucker at %d m in EPSG:7850. "
            "ORIENTATION ONLY, NOT FOR NAVIGATION: banks are crowd-sourced, nothing here "
            "describes sandbanks, and Point Walter spit is submerged at higher tides and "
            "mapped inconsistently."
            % (int(MIN_WATER_AREA), int(SIMPLIFY_M))),
        "bbox": {"south": SOUTH, "west": WEST, "north": NORTH, "east": EAST},
        "simplify_m": SIMPLIFY_M,
        "type": "FeatureCollection",
        "features": doc["features"],
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print("wrote %s  (%d bytes)" % (OUT, os.path.getsize(OUT)))
    print("wrote %s  (%d bytes)" % (GPKG, os.path.getsize(GPKG)))


if __name__ == "__main__":
    QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH",
                                                r"C:\Program Files\QGIS 4.2.1\apps\qgis"), True)
    app = QgsApplication([], False)
    app.initQgis()
    sys.path.append(os.path.join(QgsApplication.prefixPath(), "python", "plugins"))
    import processing
    from processing.core.Processing import Processing
    from qgis.analysis import QgsNativeAlgorithms

    QgsApplication.processingRegistry().addProvider(QgsNativeAlgorithms())
    Processing.initialize()

    geom = build(fetch_osm())
    parts = geom.asGeometryCollection()      # real copies; .parts() hands out
                                             # pointers QGIS can invalidate mid-loop
    print("land parts=%d  vertices=%d"
          % (len(parts), sum(len(list(p.vertices())) for p in parts)))
    failures = check(geom)
    write_outputs(geom)
    app.exitQgis()
    sys.exit(1 if failures else 0)
