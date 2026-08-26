"""Generate config/depth.json: depth contours, depth bands, and the foreshore.

Run with QGIS's own Python. The BAG reader is a GDAL plugin that QGIS ships but does
not put on the driver path, so GDAL_DRIVER_PATH has to be set; this script sets it
itself before importing gdal.

    "C:\\Program Files\\QGIS 4.2.1\\bin\\python-qgis.bat" scripts/gen_depth.py

Two stages, because the river deserves more resolution than the ocean and the whole
mapped extent at 2 m would be 727 million cells:

    river    the SC2010 multibeam BAG, 1 m source, gridded at 2 m over its own
             footprint. Melville Water, Freshwater Bay, Blackwall Reach, the
             Canning: where the racing happens.
    region   the five DoT composite surfaces, 5 m source, gridded at 10 m over the
             rest of the mapped extent. Rottnest, Gage Roads, Owen Anchorage,
             Cockburn Sound, Warnbro, the northern beaches.

The river stage wins where they overlap, and the region stage is clipped out of the
river footprint so nothing is drawn twice.

Nothing extends further up the Swan or Canning than the BAG already reaches. The
Perth composite does poke further east but is almost entirely nodata up there, and
the region foreshore rule below will not invent green in the upper river because it
only paints near actual soundings.

VERTICAL DATUM: AHD, roughly mean sea level. This was got wrong once and the
correction matters, so here is the evidence rather than an assertion:

  - The DoT survey index records SC20100413 as VertDatTyp "Low Water Mark" with
    AHD_Diff 0.756 BELOW. Read naively that says the grid is on LWM.
  - It is not. SC.zip's README states its singlebeam text files are metres relative
    to AHD. BAG minus those points, over 16561 shared cells, is a median of
    -0.042 m. If the BAG were on LWM the difference would be near +0.756.
  - So VertDatTyp names the datum the survey was OBSERVED against; AHD_Diff is the
    correction already applied to the delivered grid.
  - BAG minus Perth_5m over 627364 cells is +0.002 m, and the four tile seams agree
    to within 0.011 m, so every source here shares that one datum.

CONSEQUENCE, and it is the unsafe direction: AHD is near mean sea level, so at low
water there is LESS water than these contours say, by up to about 0.76 m at LAT.
A charted 2 m contour is not the same line as this 2 m contour. Set DATUM_SHIFT to
+0.756 to move everything onto approximately LAT and get the chart-conservative
version instead.

What does NOT work as a source, so nobody repeats it:

  - AHOENCSeries is a cached S-52 tile package. Its own service description says it
    is a picture. There is no vector in it.
  - The DoT layers in the QGIS project are pictures too, named `..._Image_...img`
    literally, and identifying a pixel returns RGB, not depth.
  - SC.zip PointData is singlebeam track lines hugging the foreshore. Interpolating
    it alone invents shallow water in the deep channel: Blackwall Reach, really
    22 m, comes out at 1.9 m. Useful as a datum witness, useless as a surface.

THE GREEN CLASS IS NOT A DEPTH. A survey stops where the vessel could float, so the
strip between the shallowest sounding and the bank is unmeasured, as are the flats.
The gap is still interpolated internally, because contours drawn against a cliff
edge kink badly, but the interpolated area is pulled back out and emitted as
`foreshore`. Green, because a paper chart and every commercial plotter colour an
intertidal area green, and because "we do not know" must not look like "deep".
See docs/reference/NavigationMapExample.png.

Still true: surveyed 2010 or earlier, BAG uncertainty 0.25 to 0.30 m, and Swan
sandbanks move. Orientation only, not for navigation.
"""
import json
import os
import shutil
import sys
import urllib.request

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_PLUGINS = r"C:\Program Files\QGIS 4.2.1\apps\gdal\lib\gdalplugins"
if os.path.isdir(_PLUGINS):
    os.environ.setdefault("GDAL_DRIVER_PATH", _PLUGINS)

import numpy as np
from osgeo import gdal, ogr, osr
from qgis.core import (QgsApplication, QgsVectorLayer, QgsGeometry, QgsRectangle,
                       QgsCoordinateReferenceSystem, QgsFeature, QgsField,
                       QgsVectorFileWriter, QgsCoordinateTransformContext, QgsPointXY)
from qgis.PyQt.QtCore import QVariant

gdal.UseExceptions()

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
COAST_GPKG = os.path.join(REPO, "docs", "qgis", "swan_coast.gpkg")
OUT_GPKG = os.path.join(REPO, "docs", "qgis", "swan_depth.gpkg")
OUT_JSON = os.path.join(REPO, "config", "depth.json")
CACHE_DIR = os.path.join(HERE, "_bathy_cache")

BAG_BLOB = ("https://dotazprdauegisextpubst01.blob.core.windows.net/"
            "transport-wa-public/bathymetry/rasters/")
TIF_BLOB = "https://s3-ap-southeast-2.amazonaws.com/transport.wa/Bathymetry/Rasters/"

# SC20101001_Mean.bag ("Perth Water") shares this footprint and contributed 0
# additional cells, so it is not fetched.
RIVER_SOURCES = [("SC20100413_Mean.bag", BAG_BLOB, 1e6)]
# The five composite surfaces whose footprints touch the mapped extent, from the
# DoT survey index. They abut rather than overlap and tile the metro coast.
REGION_SOURCES = [(n + ".tif", TIF_BLOB, -9999.0) for n in
                  ("Rottnest_5m", "Perth_5m", "CockburnSound_5m",
                   "Warnbro_5m", "OceanReef_5m")]

# Same extent as gen_coast.py and gen_structures.py.
WEST, EAST, SOUTH, NORTH = 115.40, 116.00, -32.32, -31.86

NODATA = -9999.0
DATUM_SHIFT = 0.0        # +0.756 to express contours against approximately LAT
CONTOURS = [-10.0, -5.0, -2.0]
OPEN_LOW, OPEN_HIGH = -1000.0, 1000.0
LAND_VALUE = 0.5         # so gap filling ramps up to the shore instead of off a cliff
FILL_M = 240.0           # how far interpolation reaches into a gap, metres
# Per stage. The river is looked at zoomed in on a phone, so it keeps small
# detail. The region is looked at zoomed out and at 10 m the contour generator
# emits thousands of short offshore fragments that are pure noise at that scale;
# without these the file is 3.7 MB instead of well under 1.
MIN_BAND_AREA = {"river": 400.0, "region": 8000.0}
MIN_LINE_LEN = {"river": 40.0, "region": 250.0}
# Region foreshore only within this distance of the SHORE. Anchoring it to the
# coastline rather than to the survey edge matters: a survey edge is partly just
# where a 25 km raster tile stops, and buffering that drew green rectangles and
# straight lines across open ocean. The coastline is real, so a band along it is
# real. It also stops green spreading up the Swan past the surveyed reach, since
# the unsurveyed upper river is nowhere near a surveyed shore... it is near a
# shore, so the reach is deliberately short.
FORESHORE_REACH = 400.0
# ...and within this of real soundings, which is what excludes inland lakes.
# Herdsman and Monger are unsurveyed water within 400 m of their own shores,
# so the shore rule alone painted them green. They are kilometres from any
# sounding; the Rottnest salt lakes are a few hundred metres from one and
# stay, which is right, they are at least water you can see from a boat.
FORESHORE_SOUNDING_REACH = 1500.0

CRS4326 = QgsCoordinateReferenceSystem("EPSG:4326")
MGA = QgsCoordinateReferenceSystem("EPSG:28350")

FORESHORE = {"id": "foreshore", "depth": "unsurveyed / foreshore", "color": "#a8c66c"}
BANDS = [
    {"id": "shallow", "zmin": -2.0,     "zmax": OPEN_HIGH, "depth": "0-2 m",  "color": "#1f5c8b"},
    {"id": "mid",     "zmin": -5.0,     "zmax": -2.0,      "depth": "2-5 m",  "color": "#4e8fbd"},
    {"id": "deep",    "zmin": -10.0,    "zmax": -5.0,      "depth": "5-10 m", "color": "#92c0dc"},
    {"id": "deepest", "zmin": OPEN_LOW, "zmax": -10.0,     "depth": ">10 m",  "color": "#d8e9f5"},
]


# --------------------------------------------------------------------------- io

def fetch(name, blob):
    if not os.path.isdir(CACHE_DIR):
        os.makedirs(CACHE_DIR)
    path = os.path.join(CACHE_DIR, name)
    if os.path.exists(path):
        return path
    print("   downloading %s ..." % name)
    with urllib.request.urlopen(blob + name, timeout=3600) as r, open(path, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 22)
    print("      %d bytes" % os.path.getsize(path))
    return path


def run(alg, params):
    p = dict(params)
    p.setdefault("OUTPUT", "memory:")
    return processing.run(alg, p)["OUTPUT"]


def mem_poly(name, geoms, crs=MGA):
    lyr = QgsVectorLayer("Polygon?crs=" + crs.authid(), name, "memory")
    fs = []
    for g in geoms:
        f = QgsFeature()
        f.setGeometry(g)
        fs.append(f)
    lyr.dataProvider().addFeatures(fs)
    lyr.updateExtents()
    return lyr


def snap(v, res, up=False):
    return (np.ceil(v / res) if up else np.floor(v / res)) * res


# ------------------------------------------------------------------- grid build

def source_footprint(path, srcnd):
    ds = gdal.Open(path)
    g = ds.GetGeoTransform()
    x0, y1 = g[0], g[3]
    x1 = x0 + g[1] * ds.RasterXSize
    y0 = y1 + g[5] * ds.RasterYSize
    srs = osr.SpatialReference()
    srs.ImportFromWkt(ds.GetProjection())
    code = srs.GetAuthorityCode(None) or srs.GetAuthorityCode("PROJCS")
    ds = None
    return (x0, y0, x1, y1), int(code)


def build_grid(sources, bounds, res, wkt):
    """Mosaic sources onto one grid. Earlier sources win where they overlap."""
    x0, y0, x1, y1 = bounds
    nx = int(round((x1 - x0) / res))
    ny = int(round((y1 - y0) / res))
    print("   grid %d x %d at %.0f m" % (nx, ny, res))
    merged = np.full((ny, nx), NODATA, dtype=np.float32)
    for name, blob, srcnd in sources:
        path = fetch(name, blob)
        tmp = "/vsimem/stage_%s.tif" % os.path.basename(name)
        gdal.Warp(tmp, path, format="GTiff", xRes=res, yRes=res,
                  outputBounds=(x0, y0, x1, y1), srcNodata=srcnd, dstNodata=NODATA,
                  dstSRS="EPSG:28350", resampleAlg="average", srcBands=[1])
        ds = gdal.Open(tmp)
        a = ds.GetRasterBand(1).ReadAsArray()
        ds = None
        gdal.Unlink(tmp)
        take = (merged == NODATA) & (a != NODATA)
        merged[take] = a[take]
        print("   %-24s +%d cells" % (name, int(take.sum())))
        del a
    if DATUM_SHIFT:
        m = merged != NODATA
        merged[m] += DATUM_SHIFT
        print("   datum shift %+.3f m applied" % DATUM_SHIFT)
    have = int((merged != NODATA).sum())
    print("   surveyed cells %d (%.1f%%)" % (have, 100.0 * have / merged.size))
    if have:
        v = merged[merged != NODATA]
        print("   elevation %.2f .. %.2f  mean %.2f" % (v.min(), v.max(), v.mean()))
    return merged, (x0, y0, x1, y1), nx, ny


def write_tif(path, arr, bounds, nx, ny, res, wkt):
    x0, y0, x1, y1 = bounds
    if os.path.exists(path):
        os.remove(path)
    ds = gdal.GetDriverByName("GTiff").Create(path, nx, ny, 1, gdal.GDT_Float32,
                                              options=["COMPRESS=LZW", "TILED=YES"])
    ds.SetGeoTransform((x0, res, 0, y1, 0, -res))
    ds.SetProjection(wkt)
    b = ds.GetRasterBand(1)
    b.WriteArray(arr)
    b.SetNoDataValue(NODATA)
    b.FlushCache()
    ds = None
    return path


def surveyed_polygons(mask, bounds, nx, ny, res, wkt, tag):
    """Polygons over cells a survey actually measured, before any gap filling.

    gdal.Polygonize with the band as its own mask emits polygons only where the
    band is non-zero, which is exactly the footprint wanted.
    """
    x0, y0, x1, y1 = bounds
    mds = gdal.GetDriverByName("MEM").Create("", nx, ny, 1, gdal.GDT_Byte)
    mds.SetGeoTransform((x0, res, 0, y1, 0, -res))
    mds.SetProjection(wkt)
    mb = mds.GetRasterBand(1)
    mb.WriteArray(mask.astype(np.uint8))
    out = os.path.join(HERE, "_surveyed_%s.gpkg" % tag)
    if os.path.exists(out):
        os.remove(out)
    srs = osr.SpatialReference()
    srs.ImportFromWkt(wkt)
    vds = ogr.GetDriverByName("GPKG").CreateDataSource(out)
    lyr = vds.CreateLayer("surveyed", srs, ogr.wkbPolygon)
    lyr.CreateField(ogr.FieldDefn("v", ogr.OFTInteger))
    gdal.Polygonize(mb, mb, lyr, 0)
    n = lyr.GetFeatureCount()
    vds = None
    mds = None
    print("   surveyed footprint: %d polygons" % n)
    q = QgsVectorLayer(out + "|layername=surveyed", "surveyed_" + tag, "ogr")
    return run("native:dissolve", {"INPUT": run("native:fixgeometries", {"INPUT": q})})


# ------------------------------------------------------------------ one stage

def stage(name, sources, bounds, res, simplify, water, land_gpkg,
          foreshore_mode, wkt, land_layer=None):
    min_area = MIN_BAND_AREA[name]
    min_len = MIN_LINE_LEN[name]
    print("[%s]" % name)
    grid, bounds, nx, ny = build_grid(sources, bounds, res, wkt)
    if int((grid != NODATA).sum()) == 0:
        raise SystemExit("%s: no source data on the grid" % name)

    surveyed = surveyed_polygons(grid != NODATA, bounds, nx, ny, res, wkt, name)

    # Burn land slightly above datum so the fill ramps toward the shore rather
    # than off a cliff, then interpolate the gaps.
    work = write_tif(os.path.join(HERE, "_work_%s.tif" % name),
                     grid, bounds, nx, ny, res, wkt)
    del grid
    ds = gdal.Open(work, gdal.GA_Update)
    gdal.Rasterize(ds, land_gpkg, burnValues=[LAND_VALUE])
    b = ds.GetRasterBand(1)
    b.SetNoDataValue(NODATA)
    gdal.FillNodata(targetBand=b, maskBand=None,
                    maxSearchDist=int(round(FILL_M / res)), smoothingIterations=2)
    b.SetNoDataValue(NODATA)
    b.FlushCache()
    ds = None

    cds = gdal.Open(work)
    cband = cds.GetRasterBand(1)
    srs = osr.SpatialReference()
    srs.ImportFromWkt(wkt)
    vec = os.path.join(HERE, "_vec_%s.gpkg" % name)
    if os.path.exists(vec):
        os.remove(vec)
    vds = ogr.GetDriverByName("GPKG").CreateDataSource(vec)
    pl = vds.CreateLayer("bands", srs, ogr.wkbMultiPolygon)
    pl.CreateField(ogr.FieldDefn("zmin", ogr.OFTReal))
    pl.CreateField(ogr.FieldDefn("zmax", ogr.OFTReal))
    gdal.ContourGenerateEx(cband, pl, options=[
        "FIXED_LEVELS=" + ",".join(str(v) for v in ([OPEN_LOW] + CONTOURS + [OPEN_HIGH])),
        "ID_FIELD=-1", "POLYGONIZE=YES",
        "ELEV_FIELD_MIN=0", "ELEV_FIELD_MAX=1", "NODATA=%f" % NODATA])
    ll = vds.CreateLayer("contours", srs, ogr.wkbLineString)
    ll.CreateField(ogr.FieldDefn("elev", ogr.OFTReal))
    gdal.ContourGenerateEx(cband, ll, options=[
        "FIXED_LEVELS=" + ",".join(str(v) for v in CONTOURS),
        "ID_FIELD=-1", "ELEV_FIELD=0", "NODATA=%f" % NODATA])
    print("   raw bands %d  raw lines %d" % (pl.GetFeatureCount(), ll.GetFeatureCount()))
    vds = None
    cds = None

    # Simplify the survey edge ONCE and cut both sides with that same line.
    # Doing it per-layer after clipping leaves hairline white slivers along the
    # shared boundary, because each side rounds it its own way.
    surveyed = run("native:fixgeometries",
                   {"INPUT": run("native:simplifygeometries",
                                 {"INPUT": surveyed, "METHOD": 0,
                                  "TOLERANCE": simplify})})

    bl = QgsVectorLayer(vec + "|layername=bands", "b", "ogr")
    cl = QgsVectorLayer(vec + "|layername=contours", "c", "ogr")

    b2 = run("native:simplifygeometries",
             {"INPUT": run("native:fixgeometries", {"INPUT": bl}),
              "METHOD": 0, "TOLERANCE": simplify})
    b2 = run("native:clip", {"INPUT": run("native:fixgeometries", {"INPUT": b2}),
                             "OVERLAY": water})
    b2 = run("native:clip", {"INPUT": b2, "OVERLAY": surveyed})
    b2 = run("native:multiparttosingleparts", {"INPUT": run("native:fixgeometries", {"INPUT": b2})})
    b2 = run("native:extractbyexpression",
             {"INPUT": b2, "EXPRESSION": "$area > %f" % min_area})

    c2 = run("native:simplifygeometries", {"INPUT": cl, "METHOD": 0, "TOLERANCE": simplify})
    c2 = run("native:clip", {"INPUT": c2, "OVERLAY": water})
    c2 = run("native:clip", {"INPUT": c2, "OVERLAY": surveyed})
    c2 = run("native:multiparttosingleparts", {"INPUT": c2})
    c2 = run("native:extractbyexpression",
             {"INPUT": c2, "EXPRESSION": "$length > %f" % min_len})

    # Foreshore. "footprint" trusts the stage bounds, which is right for the river
    # because the BAG box hugs the river, so unsurveyed-inside-the-box is exactly
    # the fringe and the flats. "near_shore" keeps green within FORESHORE_REACH of
    # the coastline, which is the only safe rule over a 2900 km2 box where most of
    # the water was never going to be surveyed at all.
    gap = run("native:difference", {"INPUT": water, "OVERLAY": surveyed})
    if foreshore_mode == "near_shore":
        reach = run("native:buffer", {"INPUT": land_layer, "DISTANCE": FORESHORE_REACH,
                                      "SEGMENTS": 8, "DISSOLVE": True})
        gap = run("native:clip", {"INPUT": gap, "OVERLAY": reach})
        near_data = run("native:buffer", {"INPUT": surveyed,
                                          "DISTANCE": FORESHORE_SOUNDING_REACH,
                                          "SEGMENTS": 8, "DISSOLVE": True})
        gap = run("native:clip", {"INPUT": gap, "OVERLAY": near_data})
    fore = run("native:multiparttosingleparts", {"INPUT": run("native:fixgeometries", {"INPUT": gap})})
    fore = run("native:extractbyexpression",
               {"INPUT": fore, "EXPRESSION": "$area > %f" % min_area})
    print("   kept bands %d  lines %d  foreshore %d"
          % (b2.featureCount(), c2.featureCount(), fore.featureCount()))
    return b2, c2, fore, surveyed


# ----------------------------------------------------------------------- main

def water_layer(bounds, exclude=None):
    land = QgsVectorLayer(COAST_GPKG + "|layername=coast_land", "land", "ogr")
    if not land.isValid():
        raise SystemExit("coast layer missing; run scripts/gen_coast.py first")
    land_m = run("native:reprojectlayer", {"INPUT": land, "TARGET_CRS": MGA})
    x0, y0, x1, y1 = bounds
    box = mem_poly("box", [QgsGeometry.fromRect(QgsRectangle(x0, y0, x1, y1))])
    w = run("native:difference", {"INPUT": box, "OVERLAY": land_m})
    if exclude is not None:
        w = run("native:difference", {"INPUT": w, "OVERLAY": exclude})
    return w, land_m


def main():
    horiz = osr.SpatialReference()
    horiz.ImportFromEPSG(28350)
    wkt = horiz.ExportToWkt()

    # region bounds: the mapped extent in MGA50
    to_m = osr.CoordinateTransformation(
        _srs(4326), _srs(28350))
    xs, ys = [], []
    for lon, lat in ((WEST, SOUTH), (WEST, NORTH), (EAST, SOUTH), (EAST, NORTH)):
        x, y, _ = to_m.TransformPoint(lon, lat)
        xs.append(x)
        ys.append(y)
    region_bounds = (snap(min(xs), 10.0), snap(min(ys), 10.0),
                     snap(max(xs), 10.0, True), snap(max(ys), 10.0, True))

    river_bounds, code = source_footprint(fetch(*RIVER_SOURCES[0][:2]),
                                          RIVER_SOURCES[0][2])
    river_bounds = (snap(river_bounds[0], 2.0), snap(river_bounds[1], 2.0),
                    snap(river_bounds[2], 2.0, True), snap(river_bounds[3], 2.0, True))
    print("river bounds  %.0f %.0f %.0f %.0f" % river_bounds)
    print("region bounds %.0f %.0f %.0f %.0f" % region_bounds)

    river_box = mem_poly("riverbox",
                         [QgsGeometry.fromRect(QgsRectangle(*river_bounds))])

    # land written once, for gdal.Rasterize in both stages
    _, land_m = water_layer(region_bounds)
    land_gpkg = os.path.join(HERE, "_land_burn.gpkg")
    if os.path.exists(land_gpkg):
        os.remove(land_gpkg)
    o = QgsVectorFileWriter.SaveVectorOptions()
    o.driverName = "GPKG"
    o.layerName = "land"
    QgsVectorFileWriter.writeAsVectorFormatV3(land_m, land_gpkg,
                                              QgsCoordinateTransformContext(), o)

    water_river, _ = water_layer(river_bounds)
    water_region, _ = water_layer(region_bounds, exclude=river_box)

    rb, rl, rf, _ = stage("river", RIVER_SOURCES, river_bounds, 2.0, 5.0,
                          water_river, land_gpkg, "footprint", wkt)
    gb, gl, gf, _ = stage("region", REGION_SOURCES, region_bounds, 10.0, 20.0,
                          water_region, land_gpkg, "near_shore", wkt,
                          land_layer=land_m)

    bands = to4326(run("native:mergevectorlayers", {"LAYERS": [rb, gb], "CRS": MGA}))
    lines = to4326(run("native:mergevectorlayers", {"LAYERS": [rl, gl], "CRS": MGA}))
    fore = to4326(run("native:mergevectorlayers", {"LAYERS": [rf, gf], "CRS": MGA}))
    print("merged: bands %d  lines %d  foreshore %d"
          % (bands.featureCount(), lines.featureCount(), fore.featureCount()))
    finish(bands, lines, fore, river_bounds, region_bounds)


def _srs(epsg):
    s = osr.SpatialReference()
    s.ImportFromEPSG(epsg)
    s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return s


def to4326(lyr):
    return run("native:reprojectlayer", {"INPUT": lyr, "TARGET_CRS": CRS4326})


def bbox4326(bounds):
    x0, y0, x1, y1 = bounds
    ct = osr.CoordinateTransformation(_srs(28350), _srs(4326))
    pts = [ct.TransformPoint(x, y)[:2] for x, y in
           ((x0, y0), (x0, y1), (x1, y0), (x1, y1))]
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    return {"west": round(min(lons), 6), "east": round(max(lons), 6),
            "south": round(min(lats), 6), "north": round(max(lats), 6)}


def classify(zmin, zmax):
    for s in BANDS:
        if abs(s["zmin"] - zmin) < 0.01 and abs(s["zmax"] - zmax) < 0.01:
            return s
    return None


def finish(bands, lines, foreshore, river_bounds, region_bounds):
    ob = QgsVectorLayer("MultiPolygon?crs=EPSG:4326", "depth_bands", "memory")
    ob.dataProvider().addAttributes([QgsField("band", QVariant.String),
                                     QgsField("depth", QVariant.String),
                                     QgsField("color", QVariant.String)])
    ob.updateFields()
    feats, skipped = [], 0
    for f in foreshore.getFeatures():
        nf = QgsFeature(ob.fields())
        nf.setGeometry(f.geometry())
        nf.setAttributes([FORESHORE["id"], FORESHORE["depth"], FORESHORE["color"]])
        feats.append(nf)
    for f in bands.getFeatures():
        s = classify(f["zmin"], f["zmax"])
        if s is None:
            skipped += 1
            continue
        nf = QgsFeature(ob.fields())
        nf.setGeometry(f.geometry())
        nf.setAttributes([s["id"], s["depth"], s["color"]])
        feats.append(nf)
    ob.dataProvider().addFeatures(feats)
    ob.updateExtents()
    if skipped:
        print("WARNING: dropped %d band parts with an unrecognised z range" % skipped)

    ol = QgsVectorLayer("LineString?crs=EPSG:4326", "depth_contours", "memory")
    ol.dataProvider().addAttributes([QgsField("depth_m", QVariant.Double)])
    ol.updateFields()
    lf = []
    for f in lines.getFeatures():
        nf = QgsFeature(ol.fields())
        nf.setGeometry(f.geometry())
        nf.setAttributes([abs(float(f["elev"]))])
        lf.append(nf)
    ol.dataProvider().addFeatures(lf)
    ol.updateExtents()

    counts = {}
    for f in ob.getFeatures():
        counts[f["band"]] = counts.get(f["band"], 0) + 1
    print("bands by class:", counts)

    geoms = {}
    for f in ob.getFeatures():
        geoms.setdefault(f["band"], []).append(QgsGeometry(f.geometry()))
    marks = json.load(open(os.path.join(REPO, "config", "marks.json"),
                           encoding="utf-8"))["marks"]
    tally = {}
    for m in marks:
        pt = QgsGeometry.fromPointXY(QgsPointXY(m["lon"], m["lat"]))
        hit = None
        for k in ("foreshore", "shallow", "mid", "deep", "deepest"):
            if any(g.contains(pt) for g in geoms.get(k, [])):
                hit = k
                break
        tally[hit or "none"] = tally.get(hit or "none", 0) + 1
    print("marks by depth band:", tally)

    doc = {
        "schema": "pfsyc-depth/2",
        "generated_from": ([BAG_BLOB + n for n, _b, _d in RIVER_SOURCES]
                           + [TIF_BLOB + n for n, _b, _d in REGION_SOURCES]),
        "license": "CC BY 4.0, Department of Transport, Western Australia",
        "survey": ("SC2010 multibeam at 1 m for the river, gridded at 2 m; the five "
                   "DoT composite surfaces at 5 m for the rest of the region, "
                   "gridded at 10 m"),
        "vertical_datum": (
            "AHD, roughly mean sea level. NOT chart datum. Verified rather than "
            "assumed: the DoT survey index calls SC20100413 'Low Water Mark' with "
            "AHD_Diff 0.756 below, but that names the datum the survey was observed "
            "against, and the correction is already applied to the delivered grid. "
            "BAG minus the AHD-documented singlebeam points is -0.042 m over 16561 "
            "cells; BAG minus Perth_5m is +0.002 m over 627364; the four tile seams "
            "agree within 0.011 m. UNSAFE DIRECTION: at low water there is LESS "
            "water than these contours say, by up to about 0.76 m at LAT."),
        "source_note": (
            "2 m, 5 m and 10 m depth contours, the four bands between them, and a "
            "fifth class, foreshore. Land is masked using config/coast.json. Blue "
            "covers only water a survey actually measured; water inside the bank "
            "that was never reached is foreshore, green, because 'we do not know' "
            "must not look like 'deep'. Do not read foreshore as a depth. Foreshore "
            "in the river covers the whole unsurveyed part of the BAG footprint; in "
            "the wider region it is limited to within %d m of the coastline AND "
            "within %d m of real soundings, so green never spreads across open "
            "ocean, never follows a raster tile edge, and does not appear on "
            "inland lakes. Surveyed 2010 or earlier and Swan sandbanks move. "
            "ORIENTATION ONLY, NOT FOR NAVIGATION."
            % (int(FORESHORE_REACH), int(FORESHORE_SOUNDING_REACH))),
        "bands": ([{"id": FORESHORE["id"], "depth": FORESHORE["depth"],
                    "color": FORESHORE["color"]}]
                  + [{"id": b["id"], "depth": b["depth"], "color": b["color"]}
                     for b in BANDS]),
        "contour_levels_m": [abs(v) for v in CONTOURS],
        "coverage": {"river_2m": bbox4326(river_bounds),
                     "region_10m": bbox4326(region_bounds)},
        "counts": counts,
        "type": "FeatureCollection",
        "features": [],
    }
    for lyr, kind in ((ob, "band"), (ol, "contour")):
        for f in lyr.getFeatures():
            props = {"kind": kind}
            for fld in lyr.fields().names():
                props[fld] = f[fld]
            doc["features"].append({"type": "Feature", "properties": props,
                                    "geometry": json.loads(f.geometry().asJson(5))})
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    print("wrote %s (%d bytes, %d features)"
          % (OUT_JSON, os.path.getsize(OUT_JSON), len(doc["features"])))
    write_gpkg(ob, ol)


def write_gpkg(bands_layer, contours_layer):
    """Stage beside the target, then move it in.

    QGIS holds an open handle on any GeoPackage it has layered, so writing straight
    to OUT_GPKG dies with WinError 32 whenever the project is open. The name must
    end in .gpkg or the driver appends its own extension and the replace then fails
    on a file that was never created.
    """
    stage_path = OUT_GPKG[:-5] + ".new.gpkg"
    if os.path.exists(stage_path):
        os.remove(stage_path)
    for lyr, nm in ((bands_layer, "depth_bands"), (contours_layer, "depth_contours")):
        o = QgsVectorFileWriter.SaveVectorOptions()
        o.driverName = "GPKG"
        o.layerName = nm
        o.fileEncoding = "UTF-8"
        if os.path.exists(stage_path):
            o.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        QgsVectorFileWriter.writeAsVectorFormatV3(lyr, stage_path,
                                                  QgsCoordinateTransformContext(), o)
    try:
        os.replace(stage_path, OUT_GPKG)
        print("wrote %s (%d bytes)" % (OUT_GPKG, os.path.getsize(OUT_GPKG)))
    except OSError as e:
        print("COULD NOT REPLACE %s: %s" % (OUT_GPKG, e))
        print("   it is open in QGIS. The new one is %s" % stage_path)


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
    main()
    app.exitQgis()
