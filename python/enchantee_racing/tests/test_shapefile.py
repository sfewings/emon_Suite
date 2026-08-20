"""Unit tests for scripts/shapefile.py, the reader every mark position comes from.

A shapefile reader that is subtly wrong does not raise, it moves marks. So these tests
check the decoded layer against things that are true independently of the reader: the
bounding box the file declares in its own header, the record count in its index file, and
the register's own LAT and LON columns, which sit alongside the geometry and agree with it
exactly wherever a mark was not moved during redigitizing.

Reads the real layer rather than a synthetic one. It is in the repository, it is the
authority for the whole app, and a test against a fixture I made up would not have caught
a misread of the file that matters.
"""

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import shapefile  # noqa: E402
from engine import nav  # noqa: E402

LAYER = ROOT / "docs" / "qgis" / "Swan River Marks" / "Swan_marks_YWA_SRRC_Sep2019"

BBOX = dict(south=-32.030346, west=115.748, north=-31.959052, east=115.856573)


def test_the_layer_reads_and_self_checks():
    """read_points raises if the decoded box disagrees with the declared one."""
    points = shapefile.read_points(LAYER.with_suffix(".shp"))
    assert len(points) == 142
    assert all(p is not None for p in points)


def test_the_record_count_matches_the_index_file():
    """The .shx is a separate file with one 8-byte entry per record, so it is an
    independent statement of how many records there should be."""
    index_bytes = LAYER.with_suffix(".shx").stat().st_size
    assert (index_bytes - 100) % 8 == 0
    assert (index_bytes - 100) // 8 == len(shapefile.read_points(LAYER.with_suffix(".shp")))


def test_geometry_is_longitude_then_latitude():
    """Shapefiles store x then y, the opposite order from everything else here.

    Getting this backwards would put every mark in Somalia rather than subtly wrong, but
    it is the single easiest mistake to make with this format, so it is pinned.
    """
    for lon, lat in shapefile.read_points(LAYER.with_suffix(".shp")):
        assert -33.0 < lat < -31.0, (lat, lon)
        assert 115.0 < lon < 116.5, (lat, lon)


def test_the_attribute_table_has_the_register_columns():
    rows = shapefile.read_attributes(LAYER.with_suffix(".dbf"))
    assert len(rows) == 142
    for needed in ("NAME", "NAV_TYPE", "NAV_NAME", "YWA_NAME", "OWNER", "MARK_CLS", "LAT", "LON"):
        assert needed in rows[0], needed
    assert isinstance(rows[0]["LAT"], float)   # numeric fields parsed, not left as text
    assert isinstance(rows[0]["NAME"], str)


def test_read_layer_pairs_geometry_with_attributes():
    layer = shapefile.read_layer(LAYER)
    assert len(layer) == 142
    labelled = {row["YWA_NAME"]: point for point, row in layer if row["YWA_NAME"]}
    assert "32A PFSYC Start Outer Start" in labelled
    assert "PFSYC Start Inner Start" in labelled


def test_the_geometry_agrees_with_the_register_columns_where_nothing_moved():
    """The layer carries the register's own LAT and LON next to the digitized geometry.

    Wherever a mark was not moved the two are the same point, so this is the reader
    checking itself against numbers decoded by a completely different code path: text out
    of a dBase field against doubles out of the .shp. If the geometry decode were wrong,
    these would not agree anywhere.
    """
    same = moved = 0
    for point, row in shapefile.read_layer(LAYER):
        if point is None or row["LAT"] is None or row["LON"] is None:
            continue
        lon, lat = point
        metres = nav.distance_m(nav.LatLon(lat, lon), nav.LatLon(row["LAT"], row["LON"]))
        if metres < 0.05:
            same += 1
        else:
            moved += 1
    assert same >= 70, same    # 81 at the time of writing
    assert moved >= 50, moved  # 61, the redigitized ones


def test_the_marks_used_by_courses_are_all_in_the_layer():
    """gen_marks.py refuses to write without these, so a rename is caught at generation
    time. This catches it at test time instead, which is cheaper."""
    import gen_marks  # noqa: E402

    labels = {row["YWA_NAME"] for _point, row in shapefile.read_layer(LAYER) if row["YWA_NAME"]}
    for label in gen_marks.COURSE_MARKS:
        assert label in labels, label
    assert gen_marks.START_INNER[0] in labels


def test_a_file_that_is_not_a_shapefile_raises():
    """Wrong file, wrong extension, truncated download: all must fail loudly."""
    for path in (LAYER.with_suffix(".dbf"), LAYER.with_suffix(".prj")):
        try:
            shapefile.read_points(path)
        except ValueError:
            pass
        else:
            raise AssertionError("read %s as a shapefile" % path.name)


def test_a_truncated_shapefile_raises_rather_than_returning_half_a_layer(tmp_path=None):
    """Half a layer is the dangerous outcome: marks silently missing, not an error."""
    import tempfile

    data = LAYER.with_suffix(".shp").read_bytes()
    cut = Path(tempfile.mkdtemp()) / "cut.shp"
    cut.write_bytes(data[: 100 + (len(data) - 100) // 2])
    try:
        shapefile.read_points(cut)
    except ValueError as exc:
        assert "bounding box" in str(exc)
    else:
        raise AssertionError("a truncated layer read cleanly")


def test_every_mark_the_generator_keeps_is_inside_the_documented_bbox():
    """The bbox drives the map extent and the coast.json query, so it is not decorative."""
    import json

    marks = json.loads((ROOT / "config" / "marks.json").read_text(encoding="utf-8"))
    assert marks["bbox"] == BBOX
    for mark in marks["marks"]:
        assert BBOX["south"] <= mark["lat"] <= BBOX["north"], mark["id"]
        assert BBOX["west"] <= mark["lon"] <= BBOX["east"], mark["id"]


if __name__ == "__main__":
    import traceback

    failures = 0
    for test_name, test in sorted(globals().items()):
        if not test_name.startswith("test_") or not callable(test):
            continue
        try:
            test()
        except Exception:
            failures += 1
            print("FAIL  " + test_name)
            traceback.print_exc()
        else:
            print("ok    " + test_name)
    print("%d failed" % failures if failures else "all passed")
    raise SystemExit(1 if failures else 0)
