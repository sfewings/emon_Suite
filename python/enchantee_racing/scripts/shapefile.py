"""Minimal reader for a point shapefile and its dBase attribute table. Stdlib only.

Enough of the format to read the QGIS layer in docs/qgis/, and no more: points and null
shapes, and dBase III fields. Anything else raises rather than guessing.

No dependency on GDAL, fiona, geopandas or pyshp, deliberately. This reads the file that
every position in the app derives from, and it needs to keep working on a Raspberry Pi
with no compiler and no internet, years from now, when somebody wants to regenerate
marks.json from the same source.

read_points() self-checks: the .shp header declares the layer's bounding box, so if the
box computed from the decoded points does not match it, the record stride or byte order is
wrong and the reader raises instead of returning plausible rubbish. Getting this silently
wrong would move marks.
"""

from __future__ import annotations

import struct
from pathlib import Path

SHP_MAGIC = 9994
SHAPE_NULL = 0
SHAPE_POINT = 1

DBF_HEADER_END = 0x0D
DBF_DELETED = b"*"


def read_points(path) -> list:
    """[(lon, lat)] for a point shapefile, None for a null shape.

    Shapefiles store x then y, so for a geographic layer that is longitude then latitude,
    which is the opposite order from every other coordinate in this project. Callers get
    the file's order and are expected to know it.
    """
    data = Path(path).read_bytes()
    if len(data) < 100:
        raise ValueError("%s is too short to be a shapefile" % path)
    magic, = struct.unpack(">i", data[0:4])
    if magic != SHP_MAGIC:
        raise ValueError("%s is not a shapefile: magic %d, expected %d" % (path, magic, SHP_MAGIC))
    declared_type, = struct.unpack("<i", data[32:36])
    if declared_type != SHAPE_POINT:
        raise ValueError("%s holds shape type %d, and only points are supported"
                         % (path, declared_type))
    xmin, ymin, xmax, ymax = struct.unpack("<4d", data[36:68])

    points = []
    position = 100
    while position + 8 <= len(data):
        _record, words = struct.unpack(">2i", data[position:position + 8])
        body = position + 8
        record_type, = struct.unpack("<i", data[body:body + 4])
        if record_type == SHAPE_POINT:
            points.append(struct.unpack("<2d", data[body + 4:body + 20]))
        elif record_type == SHAPE_NULL:
            points.append(None)
        else:
            raise ValueError("%s record %d is shape type %d, not a point"
                             % (path, _record, record_type))
        position = body + words * 2

    real = [p for p in points if p is not None]
    if not real:
        raise ValueError("%s has no points" % path)
    computed = (min(p[0] for p in real), min(p[1] for p in real),
                max(p[0] for p in real), max(p[1] for p in real))
    declared = (xmin, ymin, xmax, ymax)
    if max(abs(c - d) for c, d in zip(computed, declared)) > 1e-9:
        raise ValueError("%s: decoded bounding box %r does not match the header's %r, so this "
                         "reader is misreading the file" % (path, computed, declared))
    return points


def read_attributes(path, encoding: str = "utf-8") -> list:
    """[{field: value}] from a dBase III table, in file order.

    Numeric fields come back as int or float, logical as bool, everything else as stripped
    text. An unparseable number becomes None rather than raising: a blank cell is normal in
    this data and is not the reader's business to adjudicate.
    """
    data = Path(path).read_bytes()
    if len(data) < 32:
        raise ValueError("%s is too short to be a dBase table" % path)
    count, header_length, record_length = struct.unpack("<I2H", data[4:12])

    fields = []
    position = 32
    while position < len(data) and data[position] != DBF_HEADER_END:
        descriptor = data[position:position + 32]
        fields.append((
            descriptor[0:11].split(b"\x00")[0].decode("ascii", "replace").strip(),
            chr(descriptor[11]),
            descriptor[16],
            descriptor[17],
        ))
        position += 32
    if not fields:
        raise ValueError("%s declares no fields" % path)

    rows = []
    for index in range(count):
        base = header_length + index * record_length
        if data[base:base + 1] == DBF_DELETED:
            continue
        offset = base + 1
        row = {}
        for name, kind, size, decimals in fields:
            text = data[offset:offset + size].decode(encoding, "replace").strip()
            offset += size
            if kind in ("N", "F"):
                try:
                    row[name] = float(text) if (decimals or "." in text) else int(text)
                except ValueError:
                    row[name] = None
            elif kind == "L":
                row[name] = text.upper() in ("Y", "T")
            else:
                row[name] = text
        rows.append(row)
    return rows


def read_layer(stem) -> list:
    """[(point, attributes)] for a shapefile given without its extension.

    Raises if the geometry and attribute counts disagree, which means the pair is not from
    the same export and nothing downstream can be trusted.
    """
    stem = Path(stem)
    points = read_points(stem.with_suffix(".shp"))
    rows = read_attributes(stem.with_suffix(".dbf"), _encoding_for(stem))
    if len(points) != len(rows):
        raise ValueError("%s: %d geometries against %d attribute rows"
                         % (stem.name, len(points), len(rows)))
    return list(zip(points, rows))


def _encoding_for(stem) -> str:
    """Whatever the .cpg says, or UTF-8. QGIS writes one; older tools do not."""
    cpg = Path(stem).with_suffix(".cpg")
    if cpg.exists():
        # QGIS has been seen to write the name twice with no separator, so take the first
        # recognisable token rather than the whole file.
        text = cpg.read_text(encoding="ascii", errors="replace").strip()
        for candidate in ("UTF-8", "utf8", "ISO-8859-1", "CP1252"):
            if text.upper().startswith(candidate.upper()):
                return candidate
    return "utf-8"
