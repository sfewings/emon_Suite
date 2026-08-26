"""Generate config/depth.json: depth contours, depth bands, and the foreshore.

Run with QGIS's own Python. The BAG reader is a GDAL plugin that QGIS ships but does
not put on the driver path, so GDAL_DRIVER_PATH has to be set; this script sets it
itself before importing gdal.

    "C:\\Program Files\\QGIS 4.2.1\\bin\\python-qgis.bat" scripts/gen_depth.py

Finding the data was the whole job. What does NOT work, so nobody repeats it:

  - AHOENCSeries is a cached S-52 tile package. Its own service description says it
    is a picture, published from a static tile package. There is no vector in it.
  - The DoT layers in the QGIS project are pictures too. They are named
    `..._Image_...img` literally, and identifying a pixel returns RGB, not depth.
  - Perth_5m.tif is a real grid, but it is the COASTAL survey. 74% of the racing box
    is nodata: Freshwater Bay, Mosman Bay, Perth Water, Point Walter, Matilda Bay all
    empty. Only the main body of Melville Water is covered.
  - SC.zip PointData is singlebeam track lines hugging the foreshore. Interpolating
    it invents shallow water in the deep channel: it puts Blackwall Reach, which is
    really 22 m, at 1.9 m. Do not grid it on its own.

What works is the multibeam BAG, found through the survey index behind the DoT
bathymetry web app (services6.arcgis.com/.../Survey_index_linkedbagfiles). That index
also carries the vertical datum per survey, which is the only reason the numbers here
mean anything.

VERTICAL DATUM: the BAGs are reduced to Low Water Mark, which the index records as
0.756 m BELOW AHD. Contours here are depths below LWM, which is the chart convention
and the conservative one: at mean water level there is about 0.76 m more than the
contour says. Set DATUM_SHIFT to -0.756 to move the contours onto AHD instead.

THE GREEN CLASS IS NOT A DEPTH. The multibeam stops where the survey vessel could
float, and its shallowest sounding is -1.10 m, so the strip between that and the
bank is unmeasured. The gap is still interpolated, because contours drawn against a
cliff edge look wrong, but the interpolated area is then pulled back out and emitted
as `foreshore` rather than as shallow water. It is green for the same reason a paper
chart and every commercial plotter make an intertidal area green: "we do not know"
must not look like "deep".

Still true, and belongs anywhere this is used: surveyed 2010, and Swan sandbanks move.
Uncertainty in the BAG is 0.25 to 0.30 m. Orientation only, not for navigation.
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

BLOB = ("https://dotazprdauegisextpubst01.blob.core.windows.net/"
        "transport-wa-public/bathymetry/rasters/")
# SC20101001_Mean.bag ("Perth Water") is listed separately in the survey index but
# shares this footprint and contributed 0 additional cells, so it is not fetched.
BAGS = ["SC20100413_Mean.bag"]   # Swan River and Canning River

RES = 2.0                 # working grid, from 1 m source
NODATA = -9999.0
BAG_NODATA = 1e6
DATUM_SHIFT = 0.0         # -0.756 to express contours against AHD instead of LWM
CONTOURS = [-10.0, -5.0, -2.0]
OPEN_LOW, OPEN_HIGH = -1000.0, 1000.0
LAND_VALUE = 0.5          # so gap filling ramps up to the shore instead of off a cliff
FILL_DIST = 120           # cells, = 240 m
SIMPLIFY_M = 5.0
MIN_BAND_AREA = 400.0
MIN_LINE_LEN = 40.0

# The green one is not a depth class. It is water the multibeam never reached,
# which is the shore fringe and the drying flats, and it is rendered the way a
# paper chart and every commercial plotter render an intertidal area: green, not
# a shade of blue, because "we do not know" must not look like "deep".
FORESHORE = {"id": "foreshore", "depth": "unsurveyed / foreshore", "color": "#a8c66c"}

BANDS = [
    {"id": "shallow", "zmin": -2.0,     "zmax": OPEN_HIGH, "depth": "0-2 m",  "color": "#1f5c8b"},
    {"id": "mid",     "zmin": -5.0,     "zmax": -2.0,      "depth": "2-5 m",  "color": "#4e8fbd"},
    {"id": "deep",    "zmin": -10.0,    "zmax": -5.0,      "depth": "5-10 m", "color": "#92c0dc"},
    {"id": "deepest", "zmin": OPEN_LOW, "zmax": -10.0,     "depth": ">10 m",  "color": "#d8e9f5"},
]


def fetch(name):
    if not os.path.isdir(CACHE_DIR):
        os.makedirs(CACHE_DIR)
    path = os.path.join(CACHE_DIR, name)
    if os.path.exists(path):
        print("cached %s" % name)
        return path
    print("downloading %s (about 730 MB) ..." % name)
    with urllib.request.urlopen(BLOB + name, timeout=3600) as r, open(path, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 22)
    print("   %d bytes" % os.path.getsize(path))
    return path


def build_grid():
    paths = [fetch(n) for n in BAGS]
    ref = gdal.Open(paths[0])
    gt = ref.GetGeoTransform()
    x0 = gt[0]
    y1 = gt[3]
    x1 = x0 + gt[1] * ref.RasterXSize
    y0 = y1 + gt[5] * ref.RasterYSize
    # The BAG declares a compound CRS (MGA50 + a vertical CRS), so the authority code
    # only exists on the projected part. Everything downstream wants horizontal only.
    srs = osr.SpatialReference(); srs.ImportFromWkt(ref.GetProjection())
    code = srs.GetAuthorityCode(None) or srs.GetAuthorityCode("PROJCS")
    if code is None:
        raise SystemExit("cannot determine horizontal CRS of %s" % paths[0])
    horiz = osr.SpatialReference()
    horiz.ImportFromEPSG(int(code))
    wkt = horiz.ExportToWkt()
    authid = "EPSG:" + code
    ref = None
    x0 = np.floor(x0 / RES) * RES; y0 = np.floor(y0 / RES) * RES
    x1 = np.ceil(x1 / RES) * RES;  y1 = np.ceil(y1 / RES) * RES
    nx = int((x1 - x0) / RES); ny = int((y1 - y0) / RES)
    print("grid %d x %d at %.0f m, crs %s" % (nx, ny, RES, authid))

    merged = np.full((ny, nx), NODATA, dtype=np.float32)
    for p in paths:
        tmp = "/vsimem/" + os.path.basename(p) + ".tif"
        gdal.Warp(tmp, p, format="GTiff", xRes=RES, yRes=RES,
                  outputBounds=(x0, y0, x1, y1), srcNodata=BAG_NODATA,
                  dstNodata=NODATA, resampleAlg="average", srcBands=[1])
        ds = gdal.Open(tmp)
        a = ds.GetRasterBand(1).ReadAsArray()
        ds = None
        gdal.Unlink(tmp)
        take = (merged == NODATA) & (a != NODATA)
        merged[take] = a[take]
        print("   %-24s added %d cells" % (os.path.basename(p), int(take.sum())))

    if DATUM_SHIFT:
        m = merged != NODATA
        merged[m] = merged[m] + DATUM_SHIFT
        print("   datum shift %.3f m applied" % DATUM_SHIFT)

    have = int((merged != NODATA).sum())
    print("surveyed cells: %d (%.1f%% of grid)" % (have, 100.0 * have / merged.size))
    v = merged[merged != NODATA]
    print("elevation range %.2f .. %.2f  mean %.2f" % (v.min(), v.max(), v.mean()))
    return merged, (x0, y0, x1, y1), nx, ny, wkt, authid


def write_tif(path, arr, bounds, nx, ny, wkt):
    x0, y0, x1, y1 = bounds
    if os.path.exists(path):
        os.remove(path)
    ds = gdal.GetDriverByName("GTiff").Create(path, nx, ny, 1, gdal.GDT_Float32,
                                              options=["COMPRESS=LZW", "TILED=YES"])
    ds.SetGeoTransform((x0, RES, 0, y1, 0, -RES))
    ds.SetProjection(wkt)
    b = ds.GetRasterBand(1)
    b.WriteArray(arr)
    b.SetNoDataValue(NODATA)
    b.FlushCache()
    ds = None
    return path


def surveyed_polygons(grid, bounds, nx, ny, wkt, authid):
    """Polygons covering cells the survey actually measured, before gap filling.

    gdal.Polygonize with the same band as its own mask emits polygons only where
    the band is non-zero, which is exactly the footprint wanted.
    """
    x0, y0, x1, y1 = bounds
    mask = (grid != NODATA).astype(np.uint8)
    mds = gdal.GetDriverByName("MEM").Create("", nx, ny, 1, gdal.GDT_Byte)
    mds.SetGeoTransform((x0, RES, 0, y1, 0, -RES))
    mds.SetProjection(wkt)
    mb = mds.GetRasterBand(1)
    mb.WriteArray(mask)

    out = os.path.join(HERE, "_surveyed.gpkg")
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
    print("surveyed footprint: %d polygons" % n)

    q = QgsVectorLayer(out + "|layername=surveyed", "surveyed", "ogr")
    # dissolve so later clips see one geometry rather than thousands of cells
    return run("native:dissolve", {"INPUT": run("native:fixgeometries", {"INPUT": q})})


def run(alg, params):
    p = dict(params)
    p.setdefault("OUTPUT", "memory:")
    return processing.run(alg, p)["OUTPUT"]


def water_layer(authid, bounds):
    """Water inside the survey footprint: the footprint minus the coast's land."""
    land = QgsVectorLayer(COAST_GPKG + "|layername=coast_land", "land", "ogr")
    if not land.isValid():
        raise SystemExit("coast layer missing; run scripts/gen_coast.py first")
    land_p = run("native:reprojectlayer",
                 {"INPUT": land, "TARGET_CRS": QgsCoordinateReferenceSystem(authid)})
    x0, y0, x1, y1 = bounds
    fp = QgsVectorLayer("Polygon?crs=" + authid, "fp", "memory")
    f = QgsFeature()
    f.setGeometry(QgsGeometry.fromRect(QgsRectangle(x0, y0, x1, y1)))
    fp.dataProvider().addFeatures([f])
    fp.updateExtents()
    return run("native:difference", {"INPUT": fp, "OVERLAY": land_p}), land_p


def main():
    grid, bounds, nx, ny, wkt, authid = build_grid()
    water, land_p = water_layer(authid, bounds)

    # Burn land as slightly-above-datum so the fill ramps toward the shore. Without
    # this the shallow band stops where the survey vessel stopped, several metres out.
    work = write_tif(os.path.join(HERE, "_depth_work.tif"), grid, bounds, nx, ny, wkt)
    tmp_land = os.path.join(HERE, "_land_burn.gpkg")
    if os.path.exists(tmp_land):
        os.remove(tmp_land)
    o = QgsVectorFileWriter.SaveVectorOptions()
    o.driverName = "GPKG"
    o.layerName = "land"
    QgsVectorFileWriter.writeAsVectorFormatV3(land_p, tmp_land,
                                              QgsCoordinateTransformContext(), o)
    ds = gdal.Open(work, gdal.GA_Update)
    gdal.Rasterize(ds, tmp_land, burnValues=[LAND_VALUE])
    b = ds.GetRasterBand(1)
    b.SetNoDataValue(NODATA)
    gdal.FillNodata(targetBand=b, maskBand=None, maxSearchDist=FILL_DIST,
                    smoothingIterations=2)
    b.SetNoDataValue(NODATA)
    b.FlushCache()
    arr = b.ReadAsArray()
    ds = None
    got = int((arr != NODATA).sum())
    print("after land burn + fill: %d cells (%.1f%%)" % (got, 100.0 * got / arr.size))

    # The fill above makes the contours smooth, but it invents values between the
    # shallowest sounding and the bank. Keep the pre-fill footprint so those
    # invented areas can be pulled back out and shown as foreshore instead.
    surveyed = surveyed_polygons(grid, bounds, nx, ny, wkt, authid)

    # --- contour ------------------------------------------------------------
    cds = gdal.Open(work)
    cband = cds.GetRasterBand(1)
    srs = osr.SpatialReference(); srs.ImportFromWkt(wkt)
    vec = os.path.join(HERE, "_depth_vec.gpkg")
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
    print("raw bands=%d  raw lines=%d" % (pl.GetFeatureCount(), ll.GetFeatureCount()))
    vds = None
    cds = None

    bl = QgsVectorLayer(vec + "|layername=bands", "b", "ogr")
    cl = QgsVectorLayer(vec + "|layername=contours", "c", "ogr")

    # Simplify the survey edge ONCE and cut both sides with that same line. Doing
    # it per-layer after clipping leaves hairline white slivers between the blue
    # bands and the green foreshore, because each side rounds the shared boundary
    # its own way.
    surveyed = run("native:fixgeometries",
                   {"INPUT": run("native:simplifygeometries",
                                 {"INPUT": surveyed, "METHOD": 0,
                                  "TOLERANCE": SIMPLIFY_M})})

    # blue only where the survey actually reached
    b2 = run("native:simplifygeometries",
             {"INPUT": run("native:fixgeometries", {"INPUT": bl}),
              "METHOD": 0, "TOLERANCE": SIMPLIFY_M})
    b2 = run("native:clip", {"INPUT": run("native:fixgeometries", {"INPUT": b2}),
                             "OVERLAY": water})
    b2 = run("native:clip", {"INPUT": b2, "OVERLAY": surveyed})
    b2 = run("native:multiparttosingleparts", {"INPUT": run("native:fixgeometries", {"INPUT": b2})})
    b2 = run("native:extractbyexpression", {"INPUT": b2, "EXPRESSION": "$area > %f" % MIN_BAND_AREA})
    b2 = run("native:reprojectlayer", {"INPUT": b2, "TARGET_CRS": QgsCoordinateReferenceSystem("EPSG:4326")})

    c2 = run("native:simplifygeometries", {"INPUT": cl, "METHOD": 0, "TOLERANCE": SIMPLIFY_M})
    c2 = run("native:clip", {"INPUT": c2, "OVERLAY": water})
    c2 = run("native:clip", {"INPUT": c2, "OVERLAY": surveyed})
    c2 = run("native:multiparttosingleparts", {"INPUT": c2})
    c2 = run("native:extractbyexpression", {"INPUT": c2, "EXPRESSION": "$length > %f" % MIN_LINE_LEN})
    c2 = run("native:reprojectlayer", {"INPUT": c2, "TARGET_CRS": QgsCoordinateReferenceSystem("EPSG:4326")})
    # no further simplify: surveyed is already simplified, and re-rounding here is
    # exactly what would reopen the slivers
    fore = run("native:difference", {"INPUT": water, "OVERLAY": surveyed})
    fore = run("native:multiparttosingleparts", {"INPUT": run("native:fixgeometries", {"INPUT": fore})})
    fore = run("native:extractbyexpression",
               {"INPUT": fore, "EXPRESSION": "$area > %f" % MIN_BAND_AREA})
    fore = run("native:reprojectlayer",
               {"INPUT": fore, "TARGET_CRS": QgsCoordinateReferenceSystem("EPSG:4326")})
    print("kept bands=%d lines=%d foreshore=%d"
          % (b2.featureCount(), c2.featureCount(), fore.featureCount()))
    finish(b2, c2, fore, arr, bounds, nx, ny)


def coverage_bbox(bounds):
    """The survey grid footprint in WGS84.

    Outside this rectangle there is no depth product at all, which is a different
    thing from `foreshore` (inside it, but unsurveyed). Perth Water above about
    115.858 E falls outside; the map should not imply coverage there.
    """
    x0, y0, x1, y1 = bounds
    src = osr.SpatialReference(); src.ImportFromEPSG(28350)
    dst = osr.SpatialReference(); dst.ImportFromEPSG(4326)
    src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    ct = osr.CoordinateTransformation(src, dst)
    pts = [ct.TransformPoint(x, y)[:2] for x, y in
           ((x0, y0), (x0, y1), (x1, y0), (x1, y1))]
    lons = [p[0] for p in pts]; lats = [p[1] for p in pts]
    return {"west": round(min(lons), 6), "east": round(max(lons), 6),
            "south": round(min(lats), 6), "north": round(max(lats), 6)}


def classify(zmin, zmax):
    for s in BANDS:
        if abs(s["zmin"] - zmin) < 0.01 and abs(s["zmax"] - zmax) < 0.01:
            return s
    return None


def write_gpkg(bands_layer, contours_layer):
    """Build the GeoPackage beside the target, then move it into place.

    QGIS holds an open handle on any GeoPackage it has layered, so writing straight
    to OUT_GPKG dies with WinError 32 whenever the project is open. Staging and
    replacing means a locked target costs you the desktop copy, not the run: the
    staged file is left next to it and config/depth.json, which is what the app
    actually loads, is already written by the time this is called.
    """
    # Must end in .gpkg: the driver appends its own extension otherwise, and you get
    # a stray "swan_depth.gpkg.new.gpkg" while the replace fails on a missing file.
    stage = OUT_GPKG[:-5] + ".new.gpkg"
    if os.path.exists(stage):
        os.remove(stage)
    for lyr, nm in ((bands_layer, "depth_bands"), (contours_layer, "depth_contours")):
        o = QgsVectorFileWriter.SaveVectorOptions()
        o.driverName = "GPKG"
        o.layerName = nm
        o.fileEncoding = "UTF-8"
        if os.path.exists(stage):
            o.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        QgsVectorFileWriter.writeAsVectorFormatV3(lyr, stage,
                                                  QgsCoordinateTransformContext(), o)
    try:
        os.replace(stage, OUT_GPKG)
        print("wrote %s (%d bytes)" % (OUT_GPKG, os.path.getsize(OUT_GPKG)))
    except OSError as e:
        print("COULD NOT REPLACE %s: %s" % (OUT_GPKG, e))
        print("   it is open in QGIS. The new one is %s" % stage)
        print("   close the project (or remove the depth layers) and rename it over.")


def finish(bands, lines, foreshore, arr, bounds, nx, ny):
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

    # sanity: which band does each mark sit in, and does anything read as dry?
    geoms = {}
    for f in ob.getFeatures():
        geoms.setdefault(f["band"], []).append(QgsGeometry(f.geometry()))
    marks = json.load(open(os.path.join(REPO, "config", "marks.json"),
                           encoding="utf-8"))["marks"]
    tally = {}
    unplaced = []
    for m in marks:
        pt = QgsGeometry.fromPointXY(QgsPointXY(m["lon"], m["lat"]))
        hit = None
        for k, gs in geoms.items():
            if any(g.contains(pt) for g in gs):
                hit = k
                break
        tally[hit or "none"] = tally.get(hit or "none", 0) + 1
        if hit is None:
            unplaced.append(m["id"])
    print("marks by depth band:", tally)
    if unplaced:
        print("   marks in no band (%d): %s" % (len(unplaced), unplaced[:12]))

    doc = {
        "schema": "pfsyc-depth/1",
        "generated_from": [BLOB + n for n in BAGS],
        "license": "CC BY 4.0, Department of Transport, Western Australia",
        "survey": "SC2010 multibeam, 1 m grid, uncertainty 0.25-0.30 m",
        "vertical_datum": ("Low Water Mark, which the DoT survey index records as "
                           "0.756 m below AHD. Depths are below LWM, the chart "
                           "convention; at mean water level expect about 0.76 m more."),
        "source_note": ("2 m, 5 m and 10 m depth contours and the four depth bands for "
                        "the Swan and Canning, plus a fifth class, foreshore. Land is "
                        "masked using config/coast.json. The blue bands cover only water "
                        "the multibeam actually measured; water inside the bank that it "
                        "never reached is the foreshore class, green, because the "
                        "shallowest sounding in the BAG is -1.10 m and everything "
                        "shallower is the drying fringe. Do not read foreshore as a "
                        "depth: it means unsurveyed. Surveyed 2010 and Swan sandbanks "
                        "move. ORIENTATION ONLY, NOT FOR NAVIGATION."),
        "bands": ([{"id": FORESHORE["id"], "depth": FORESHORE["depth"],
                    "color": FORESHORE["color"]}]
                  + [{"id": b["id"], "depth": b["depth"], "color": b["color"]}
                     for b in BANDS]),
        "contour_levels_m": [abs(v) for v in CONTOURS],
        "coverage_bbox": coverage_bbox(bounds),
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
