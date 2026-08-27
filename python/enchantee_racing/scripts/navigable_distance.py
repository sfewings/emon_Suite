"""Shortest navigable distance between course marks, around land and shallows.

    cd python/enchantee_racing && PYTHONPATH=. python scripts/navigable_distance.py
    ... --courses all --spit-radius 150

Why this exists. `engine/course.py` sums straight lines mark to mark, and that
reproduces the club's printed distance to within a per cent or so for every course
in the fixtures book, which is what makes it a transcription check (DESIGN 7). The
Parmelia night race broke that badly: 17.5 nm printed against 12.54 summed, 28 per
cent under, and 15.0 against 11.51. The reason turned out to be the course itself
rather than the transcription. It threads Blackwall Reach, rounds the Point Walter
spit and crosses the Claremont shallows, so a boat cannot sail the straight lines
and the club's figure is the distance actually sailed.

This measures that. The coastline and the depth bands are rasterised onto a grid,
discs are cut around every mark the register calls a SPIT, and Dijkstra runs from
each course mark over what is left.

Measured with `--cell 40 --min-depth 2.0 --spit-radius 150`:

    twenty-three fixtures courses   mean absolute error 3.3 per cent
                                    (straight lines: 3.4 per cent)
    parmelia-1   12.54 -> 14.81 nm  -28.3 per cent -> -15.4
    parmelia-2   11.51 -> 13.80 nm  -23.3 per cent -> -8.0

So the open-water courses are unaffected, which is the control that makes the rest
believable, and about half of the Parmelia gap is explained for Division I/II and
two thirds for III/IV. parmelia-2 lands inside the range of mismatches the fixtures
book already contains.

What is left, and it is a narrow lead rather than a mystery: the printed distances
differ by 2.5 nm between the two courses, where the only difference in the legs is
Squadron Buoy against Armstrong Spit, and this model makes that worth about 1 nm.
The Squadron leg is where the remaining 2.7 nm of parmelia-1 hides.

Three things that had to be right before the numbers meant anything, each of which
was wrong first:

  * Eight-connected Dijkstra can only turn in 45 degree steps and measured every
    open-water course 3 to 12 per cent long. That is the artifact, not a finding.
    Sixteen neighbours bring it under 2 per cent, and the knight moves have to
    check the cells they pass over or they sail through a one-cell spit.
  * The depth bands give a range, so `shallow` is 0-2 m and can be a hand's depth
    anywhere inside it. Keying on the deepest value in each band left the Claremont
    shallows navigable and changed nothing.
  * A spit mark sits in the shoal it marks, so its own cell is not navigable and
    the route has to snap to the nearest cell that is.

Not part of the app. Nothing here is imported by the engine, which holds no I/O and
knows only marks and geometry; this reads config/ directly and is run by hand.
"""


import argparse
import heapq
import json
import math
import sys
from pathlib import Path

import numpy as np
from matplotlib.path import Path as MplPath

sys.path.insert(0, '.')
from engine import course as C, nav  # noqa: E402

# The SHALLOWEST water each band can contain, from depth.json's own band table:
# foreshore is unsurveyed or drying, shallow is 0-2 m, mid 2-5, deep 5-10, deepest >10.
#
# The shallowest and not the deepest, which is the whole point: the 0-2 m band can be a
# hand's depth anywhere inside it, so a boat drawing 2 m cannot use any of it. Reading it
# the other way round left the Claremont shallows navigable and changed nothing.
BAND_DEPTH = {'foreshore': 0.0, 'shallow': 0.0, 'mid': 2.0, 'deep': 5.0,
              'deepest': 10.0}


def load(name):
    return json.loads(Path('config/%s.json' % name).read_text(encoding='utf-8'))


def rings_of(geometry):
    """Every ring of a Polygon or MultiPolygon, outer rings first in each group."""
    kind = geometry.get('type')
    if kind == 'Polygon':
        return [geometry['coordinates']]
    if kind == 'MultiPolygon':
        return list(geometry['coordinates'])
    return []


def rasterise(groups, lons, lats):
    """Boolean mask, True where a grid point falls inside one of the polygons.

    Holes are honoured: a point inside an inner ring is outside the polygon, which
    matters because the depth bands have unsurveyed gaps and the coast has islands.
    """
    grid_lon, grid_lat = np.meshgrid(lons, lats)
    points = np.column_stack([grid_lon.ravel(), grid_lat.ravel()])
    mask = np.zeros(points.shape[0], dtype=bool)
    for rings in groups:
        if not rings:
            continue
        outer = MplPath(np.asarray(rings[0])[:, :2])
        inside = outer.contains_points(points)
        for hole in rings[1:]:
            if len(hole) >= 3:
                inside &= ~MplPath(np.asarray(hole)[:, :2]).contains_points(points)
        mask |= inside
    return mask.reshape(grid_lat.shape)


def build_grid(cell_m, min_depth, spit_radius_m=0.0, pad_m=600.0):
    marks_doc, lines_doc = load('marks'), load('lines')
    coast, depth = load('coast'), load('depth')

    # Extent: every mark any course uses, plus the start line, padded.
    pts = [(m['lat'], m['lon']) for m in marks_doc['marks']]
    lat0 = sum(p[0] for p in pts) / len(pts)
    m_per_deg_lat, m_per_deg_lon = nav.metres_per_degree(lat0)
    south = min(p[0] for p in pts) - pad_m / m_per_deg_lat
    north = max(p[0] for p in pts) + pad_m / m_per_deg_lat
    west = min(p[1] for p in pts) - pad_m / m_per_deg_lon
    east = max(p[1] for p in pts) + pad_m / m_per_deg_lon

    nlat = int((north - south) * m_per_deg_lat / cell_m) + 1
    nlon = int((east - west) * m_per_deg_lon / cell_m) + 1
    lats = np.linspace(south, north, nlat)
    lons = np.linspace(west, east, nlon)

    land = rasterise([rings for f in coast['features']
                      for rings in rings_of(f['geometry'])], lons, lats)

    # Shallow: any band whose water depth is below the draft we will accept. Bands
    # overlap at their edges, so the shallowest wins, which is the safe direction.
    too_shallow = np.zeros_like(land)
    for feature in depth['features']:
        props = feature['properties']
        if props.get('kind') != 'band':
            continue
        if BAND_DEPTH.get(props.get('band'), 99.0) >= min_depth:
            continue
        too_shallow |= rasterise(rings_of(feature['geometry']), lons, lats)

    # Keep-off discs around every mark the register calls a SPIT.
    #
    # These are the authoritative statement of where a shoal is, and they are better
    # evidence than the bathymetry raster: the survey has unsurveyed gaps that the
    # raster leaves navigable, and the sailing instructions require fixed river
    # navigation marks to be passed on the deep-water side, which is a tighter
    # corridor than the 2 m contour. A boat rounding one stands off it, so the disc
    # both blocks the shoal and stops the route clipping the mark itself.
    spits = np.zeros_like(land)
    spit_count = 0
    if spit_radius_m > 0:
        grid_lon, grid_lat = np.meshgrid(lons, lats)
        for mark in marks_doc['marks']:
            if 'spit' not in str(mark.get('name', '')).lower():
                continue
            spit_count += 1
            dy = (grid_lat - mark['lat']) * m_per_deg_lat
            dx = (grid_lon - mark['lon']) * m_per_deg_lon
            spits |= (dx * dx + dy * dy) <= spit_radius_m ** 2

    navigable = ~land & ~too_shallow & ~spits
    return dict(lats=lats, lons=lons, navigable=navigable,
                m_lat=m_per_deg_lat, m_lon=m_per_deg_lon,
                marks=C.index_marks(marks_doc), lines=lines_doc,
                land=land, shallow=too_shallow, spits=spits,
                spit_count=spit_count)


def nearest_navigable(grid, lat, lon):
    """Grid index closest to a position that a boat can actually occupy.

    A spit mark sits in the shallow water it marks, so its own cell is often not
    navigable. Snapping is what lets the route reach it.
    """
    i = int(round((lat - grid['lats'][0]) / (grid['lats'][1] - grid['lats'][0])))
    j = int(round((lon - grid['lons'][0]) / (grid['lons'][1] - grid['lons'][0])))
    nav_mask = grid['navigable']
    i = max(0, min(i, nav_mask.shape[0] - 1))
    j = max(0, min(j, nav_mask.shape[1] - 1))
    if nav_mask[i, j]:
        return i, j
    for radius in range(1, 60):
        best = None
        for di in range(-radius, radius + 1):
            for dj in range(-radius, radius + 1):
                if max(abs(di), abs(dj)) != radius:
                    continue
                a, b = i + di, j + dj
                if 0 <= a < nav_mask.shape[0] and 0 <= b < nav_mask.shape[1] \
                        and nav_mask[a, b]:
                    d = di * di + dj * dj
                    if best is None or d < best[0]:
                        best = (d, a, b)
        if best:
            return best[1], best[2]
    raise SystemExit('no navigable cell near %.5f %.5f' % (lat, lon))


def moves(dlat_m, dlon_m, neighbours):
    """Offsets and their true lengths, with the cells each one passes over.

    Eight neighbours can only turn in 45 degree steps, so a route at 22.5 degrees to
    the grid is measured up to 8 per cent long. That bias is not academic here: it
    put every open-water fixtures course 3 to 12 per cent over its printed distance,
    which would have been read as the club measuring something else. Sixteen
    neighbours add the knight moves and cut the worst case to about 2 per cent.

    The intermediate cells matter. A (1, 2) step that jumps a one-cell spit would
    sail the boat through it, so each move carries the cells it crosses and they must
    all be navigable.
    """
    offsets = [(di, dj) for di in (-1, 0, 1) for dj in (-1, 0, 1) if di or dj]
    if neighbours == 16:
        offsets += [(di, dj) for di, dj in
                    [(1, 2), (2, 1), (-1, 2), (-2, 1),
                     (1, -2), (2, -1), (-1, -2), (-2, -1)]]
    out = []
    for di, dj in offsets:
        sdi = (di > 0) - (di < 0)
        sdj = (dj > 0) - (dj < 0)
        if abs(dj) == 2:                       # a (±1, ±2) step
            via = [(0, sdj), (di, sdj)]
        elif abs(di) == 2:                     # a (±2, ±1) step
            via = [(sdi, 0), (sdi, dj)]
        else:
            via = []
        out.append((di, dj, math.hypot(di * dlat_m, dj * dlon_m), via))
    return out


def dijkstra(grid, source, neighbours=16):
    """Distance in metres from one cell to every navigable cell."""
    nav_mask = grid['navigable']
    rows, cols = nav_mask.shape
    dlat_m = (grid['lats'][1] - grid['lats'][0]) * grid['m_lat']
    dlon_m = (grid['lons'][1] - grid['lons'][0]) * grid['m_lon']
    steps = moves(dlat_m, dlon_m, neighbours)

    dist = np.full((rows, cols), np.inf)
    dist[source] = 0.0
    heap = [(0.0, source[0], source[1])]
    while heap:
        d, i, j = heapq.heappop(heap)
        if d > dist[i, j]:
            continue
        for di, dj, step, via in steps:
            a, b = i + di, j + dj
            if not (0 <= a < rows and 0 <= b < cols) or not nav_mask[a, b]:
                continue
            blocked = False
            for vi, vj in via:
                p, q = i + vi, j + vj
                if not (0 <= p < rows and 0 <= q < cols) or not nav_mask[p, q]:
                    blocked = True
                    break
            if blocked:
                continue
            nd = d + step
            if nd < dist[a, b]:
                dist[a, b] = nd
                heapq.heappush(heap, (nd, a, b))
    return dist


def course_points(crs, grid):
    """The positions a course visits, start line mid at both ends."""
    # The same point course_distance_nm measures from and back to (DESIGN 7).
    start = C.start_point(grid['lines'])
    mid = {'lat': start.lat, 'lon': start.lon}
    pts = [mid]
    for leg in crs['legs']:
        if C.is_finish(leg):
            pts.append(mid)
        else:
            m = grid['marks'][leg['mark']]
            pts.append({'lat': m['lat'], 'lon': m['lon']})
    return pts


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--cell', type=float, default=25.0, help='grid cell, metres')
    ap.add_argument('--min-depth', type=float, default=2.0,
                    help='shallowest water treated as navigable, metres')
    ap.add_argument('--courses', default='parmelia-1,parmelia-2')
    ap.add_argument('--neighbours', type=int, default=16, choices=(8, 16))
    ap.add_argument('--spit-radius', type=float, default=0.0,
                    help='keep-off radius around SPIT marks, metres')
    args = ap.parse_args(argv)

    grid = build_grid(args.cell, args.min_depth, args.spit_radius)
    nav_pct = 100.0 * grid['navigable'].sum() / grid['navigable'].size
    print('grid %d x %d at %.0f m, min depth %.1f m, %d-connected, spit keep-off %.0f m '
          '(%d marks), %.0f%% navigable'
          % (grid['navigable'].shape[0], grid['navigable'].shape[1],
             args.cell, args.min_depth, args.neighbours, args.spit_radius,
             grid['spit_count'], nav_pct))

    courses_doc = load('courses')
    by_id = {c['id']: c for c in courses_doc['courses']}
    wanted = ([c.strip() for c in args.courses.split(',')] if args.courses != 'all'
              else [c['id'] for c in courses_doc['courses']])

    cache = {}
    print()
    print('%-18s %8s %8s %8s %8s %8s' % ('course', 'printed', 'straight', 'sailed',
                                         'str err', 'sail err'))
    rows = []
    for cid in wanted:
        crs = by_id[cid]
        pts = course_points(crs, grid)
        cells = [nearest_navigable(grid, p['lat'], p['lon']) for p in pts]
        total = 0.0
        for a, b in zip(cells, cells[1:]):
            if a not in cache:
                cache[a] = dijkstra(grid, a, args.neighbours)
            d = cache[a][b]
            if not np.isfinite(d):
                print('  %s: no route between %s and %s' % (cid, a, b))
                total = float('nan')
                break
            total += d
        sailed = total / 1852.0
        straight = C.course_distance_nm(crs, grid['marks'], grid['lines'])
        printed = crs['distance_nm']
        rows.append((cid, printed, straight, sailed))
        print('%-18s %8.2f %8.2f %8.2f %+7.1f%% %+7.1f%%'
              % (cid, printed, straight, sailed,
                 (straight - printed) / printed * 100.0,
                 (sailed - printed) / printed * 100.0))

    finite = [r for r in rows if r[3] == r[3]]
    if finite:
        print()
        print('mean |straight err| %.1f%%   mean |sailed err| %.1f%%'
              % (sum(abs((r[2] - r[1]) / r[1]) for r in finite) / len(finite) * 100.0,
                 sum(abs((r[3] - r[1]) / r[1]) for r in finite) / len(finite) * 100.0))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
