"""Generate config/structures.json: jetties, breakwaters, marinas and bridges.

Run with QGIS's own Python:

    "C:\\Program Files\\QGIS 4.2.1\\bin\\python-qgis.bat" scripts/gen_structures.py

These are the things you actually steer by. A jetty is a better landmark than a
buoy: big, fixed, and lit at night. marks.json covers the racing marks and a few
navigation piles, and says nothing about the built edge of the river.

Source is OSM, same licence and same extent as coast.json, so the two line up
exactly and the loader can treat them as one basemap.

Kinds emitted:

    jetty       man_made=pier, as lines and as areas. Not clipped to the
                waterline: a jetty that stops at the water stops being
                recognisable from a boat.
    breakwater  man_made=breakwater
    groyne      man_made=groyne
    marina      leisure=marina, as areas
    slipway     leisure=slipway
    bridge      Only bridges genuinely over navigable water. The OSM bridge tag is
                useless on its own here, returning 1886 freeway overpasses, and
                intersecting the water from coast.json still leaves 152 because
                every culvert over a drain counts. So a bridge also has to span at
                least MIN_BRIDGE_SPAN metres of water.

Lights, beacons and buoys are NOT here. They used to be, as OSM
`man_made=lighthouse` plus a few seamarks, which yielded 24 for the whole extent.
The authoritative DoT register has 785. See scripts/gen_navaids.py; this file owns
the built edge of the river and navaids owns the aid network.

Deliberately NOT included: seamark:type=mooring (183 mooring buoys, clutter, not
fixed structure), wreck, berth.

Everything is done with plain QgsGeometry rather than the processing framework,
because a layer holding points, lines and polygons together cannot be fed to
native:reprojectlayer ("Could not create memory layer"). Splitting by geometry
type is needed for the GeoPackage anyway, since QGIS styles one geometry per
layer.

Simplify is 1 m, not the 10 m coast.json uses. A jetty is 3 m wide and 40 m long;
the coast tolerance would erase it.

Same caveat as the shoreline: crowd-sourced, orientation only, not for navigation,
and a private jetty may have been rebuilt or removed since it was mapped.
"""
import json
import os
import sys
import urllib.request

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qgis.core import (QgsApplication, QgsVectorLayer, QgsGeometry, QgsRectangle,
                       QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsFeature, QgsField, QgsProject, QgsWkbTypes,
                       QgsVectorFileWriter, QgsCoordinateTransformContext)
from qgis.PyQt.QtCore import QVariant

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
COAST_GPKG = os.path.join(REPO, "docs", "qgis", "swan_coast.gpkg")
OUT_GPKG = os.path.join(REPO, "docs", "qgis", "swan_structures.gpkg")
OUT_JSON = os.path.join(REPO, "config", "structures.json")
CACHE = os.path.join(HERE, "_structures_osm_cache.osm")

# Identical to gen_coast.py, on purpose.
WEST, EAST, SOUTH, NORTH = 115.40, 116.00, -32.32, -31.86
CRS4326 = QgsCoordinateReferenceSystem("EPSG:4326")
CRSPROJ = QgsCoordinateReferenceSystem("EPSG:7850")
SIMPLIFY_M = 1.0
MIN_BRIDGE_SPAN = 30.0

OVERPASS = "https://overpass-api.de/api/interpreter"
QUERY = """[out:xml][timeout:600];
(
  way["man_made"="pier"](%(s)f,%(w)f,%(n)f,%(e)f);
  relation["man_made"="pier"](%(s)f,%(w)f,%(n)f,%(e)f);
  way["man_made"="breakwater"](%(s)f,%(w)f,%(n)f,%(e)f);
  way["man_made"="groyne"](%(s)f,%(w)f,%(n)f,%(e)f);
  way["man_made"="quay"](%(s)f,%(w)f,%(n)f,%(e)f);
  way["waterway"="dock"](%(s)f,%(w)f,%(n)f,%(e)f);
  way["leisure"="marina"](%(s)f,%(w)f,%(n)f,%(e)f);
  relation["leisure"="marina"](%(s)f,%(w)f,%(n)f,%(e)f);
  way["leisure"="slipway"](%(s)f,%(w)f,%(n)f,%(e)f);
  way["bridge"]["layer"!~"^-"](%(s)f,%(w)f,%(n)f,%(e)f);
);
(._;>;);
out body;
"""

KINDS = {
    "jetty":      {"color": "#6b5b45", "label": "Jetty / pier"},
    "breakwater": {"color": "#5a5a5a", "label": "Breakwater"},
    "groyne":     {"color": "#7a7a6a", "label": "Groyne"},
    "marina":     {"color": "#9aa7b1", "label": "Marina"},
    "slipway":    {"color": "#8a7f6a", "label": "Slipway"},
    "bridge":     {"color": "#3f3f3f", "label": "Bridge"},
}


def fetch():
    if os.path.exists(CACHE):
        print("using cached OSM extract: %s" % CACHE)
        return CACHE
    q = QUERY % {"s": SOUTH, "w": WEST, "n": NORTH, "e": EAST}
    print("querying Overpass ...")
    req = urllib.request.Request(OVERPASS, data=q.encode("utf-8"))
    with urllib.request.urlopen(req, timeout=900) as r, open(CACHE, "wb") as f:
        f.write(r.read())
    print("cached %d bytes" % os.path.getsize(CACHE))
    return CACHE


def sub(osm, layer, expr):
    l = QgsVectorLayer(osm + "|layername=" + layer, layer, "ogr")
    if expr:
        l.setSubsetString(expr)
    return l


def water_geometry(to_proj):
    """One geometry: the extent minus the coast layer's land, in MGA50."""
    land = QgsVectorLayer(COAST_GPKG + "|layername=coast_land", "land", "ogr")
    if not land.isValid():
        raise SystemExit("coast layer missing; run scripts/gen_coast.py first")
    lg = None
    for f in land.getFeatures():
        lg = QgsGeometry(f.geometry())
        break
    if lg is None:
        raise SystemExit("coast layer is empty")
    box = QgsGeometry.fromRect(QgsRectangle(WEST, SOUTH, EAST, NORTH))
    water = box.difference(lg)
    water.transform(to_proj)
    return water


def collect(osm, water_p, to_proj):
    """[(kind, name, geometry in 4326)] for everything worth drawing."""
    out = []

    def take(layer, expr, kind, keep=None):
        src = sub(osm, layer, expr)
        has_name = "name" in src.fields().names()
        n = 0
        for f in src.getFeatures():
            g = QgsGeometry(f.geometry())
            if g.isEmpty():
                continue
            if keep is not None and not keep(g):
                continue
            nm = f["name"] if has_name else None
            out.append((kind, nm if nm else None, g))
            n += 1
        print("   %-11s %-14s %d" % (kind, layer, n))

    print("collecting:")
    take("lines", "\"man_made\" = 'pier'", "jetty")
    take("multipolygons", "\"man_made\" = 'pier'", "jetty")
    take("lines", "\"man_made\" = 'breakwater'", "breakwater")
    take("multipolygons", "\"man_made\" = 'breakwater'", "breakwater")
    take("lines", "\"man_made\" = 'groyne'", "groyne")
    take("multipolygons", "\"leisure\" = 'marina'", "marina")
    take("lines", "other_tags LIKE '%\"leisure\"=>\"slipway\"%'", "slipway")

    dropped = [0]

    def real_bridge(g):
        gp = QgsGeometry(g)
        if gp.transform(to_proj) != 0:
            return False
        if not gp.intersects(water_p):
            return False
        span = gp.intersection(water_p).length()
        if span < MIN_BRIDGE_SPAN:
            dropped[0] += 1
            return False
        return True

    take("lines", "other_tags LIKE '%\"bridge\"=>%'", "bridge", keep=real_bridge)
    print("   (dropped %d bridges spanning under %.0f m of water)"
          % (dropped[0], MIN_BRIDGE_SPAN))
    return out


def simplified(g, to_proj, to_geo):
    """Douglas-Peucker in metres, then back to WGS84."""
    gp = QgsGeometry(g)
    if gp.transform(to_proj) != 0:
        return None
    s = gp.simplify(SIMPLIFY_M)
    if s is None or s.isEmpty():
        s = gp
    if s.transform(to_geo) != 0:
        return None
    return s


def make_layer(name, wkb, rows):
    lyr = QgsVectorLayer("%s?crs=EPSG:4326" % wkb, name, "memory")
    lyr.dataProvider().addAttributes([QgsField("kind", QVariant.String),
                                      QgsField("name", QVariant.String)])
    lyr.updateFields()
    feats = []
    for kind, nm, g in rows:
        f = QgsFeature(lyr.fields())
        f.setGeometry(g)
        f.setAttributes([kind, nm])
        feats.append(f)
    lyr.dataProvider().addFeatures(feats)
    lyr.updateExtents()
    return lyr


def main():
    osm = fetch()
    to_proj = QgsCoordinateTransform(CRS4326, CRSPROJ, QgsProject.instance())
    to_geo = QgsCoordinateTransform(CRSPROJ, CRS4326, QgsProject.instance())
    water_p = water_geometry(to_proj)

    items = collect(osm, water_p, to_proj)
    print("collected: %d" % len(items))

    buckets = {"points": [], "lines": [], "areas": []}
    for kind, nm, g in items:
        s = simplified(g, to_proj, to_geo)
        if s is None:
            continue
        t = QgsWkbTypes.geometryType(s.wkbType())
        if t == QgsWkbTypes.PointGeometry:
            buckets["points"].append((kind, nm, s))
        elif t == QgsWkbTypes.LineGeometry:
            buckets["lines"].append((kind, nm, s))
        elif t == QgsWkbTypes.PolygonGeometry:
            buckets["areas"].append((kind, nm, s))

    layers = {
        "points": make_layer("structure_points", "MultiPoint", buckets["points"]),
        "lines": make_layer("structure_lines", "MultiLineString", buckets["lines"]),
        "areas": make_layer("structure_areas", "MultiPolygon", buckets["areas"]),
    }
    counts = {}
    named = 0
    for key, lyr in layers.items():
        print("   %-7s %d features" % (key, lyr.featureCount()))
        for f in lyr.getFeatures():
            counts[f["kind"]] = counts.get(f["kind"], 0) + 1
            if f["name"]:
                named += 1
    print("by kind:", counts)
    print("named: %d of %d" % (named, sum(counts.values())))
    write(layers, counts)


def write(layers, counts):
    doc = {
        "schema": "pfsyc-structures/1",
        "generated_from": "OpenStreetMap via Overpass, %s" % OVERPASS,
        "license": "ODbL 1.0, (c) OpenStreetMap contributors",
        "source_note": (
            "Jetties, breakwaters, groynes, marinas, slipways, water-crossing bridges "
            "and marinas. Lights and beacons live in navaids.json, from the DoT "
            "register. Bridges must both intersect the water from coast.json and "
            "span at least %d m of it, because the OSM bridge tag alone returns every "
            "freeway overpass in the extent. Jetties are not clipped to the "
            "waterline. Simplified at %d m, unlike coast.json at 10 m, because these "
            "objects are small enough that the coast tolerance would erase them. "
            "ORIENTATION ONLY, NOT FOR NAVIGATION: crowd-sourced, and a jetty may "
            "have been rebuilt or removed since it was mapped."
            % (int(MIN_BRIDGE_SPAN), int(SIMPLIFY_M))),
        "bbox": {"south": SOUTH, "west": WEST, "north": NORTH, "east": EAST},
        "kinds": KINDS,
        "counts": counts,
        "type": "FeatureCollection",
        "features": [],
    }
    for key in ("areas", "lines", "points"):
        for f in layers[key].getFeatures():
            doc["features"].append({
                "type": "Feature",
                "properties": {"kind": f["kind"], "name": f["name"] or None},
                "geometry": json.loads(f.geometry().asJson(5)),
            })
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    print("wrote %s (%d bytes, %d features)"
          % (OUT_JSON, os.path.getsize(OUT_JSON), len(doc["features"])))

    stage = OUT_GPKG[:-5] + ".new.gpkg"   # driver forces .gpkg, so stage as .gpkg
    if os.path.exists(stage):
        os.remove(stage)
    first = True
    for key, nm in (("lines", "structure_lines"), ("areas", "structure_areas"),
                    ("points", "structure_points")):
        if layers[key].featureCount() == 0:
            print("   (skipping empty %s)" % nm)
            continue
        o = QgsVectorFileWriter.SaveVectorOptions()
        o.driverName = "GPKG"
        o.layerName = nm
        o.fileEncoding = "UTF-8"
        if not first:
            o.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        QgsVectorFileWriter.writeAsVectorFormatV3(layers[key], stage,
                                                  QgsCoordinateTransformContext(), o)
        first = False
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
