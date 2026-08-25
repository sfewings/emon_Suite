// Projection for the map page. A transcription of engine/nav.py, not a reimplementation.
//
// The map draws marks, the start line, the course and the boat in one picture, and the
// engine decides which leg the boat is on and whether it has crossed the line. If the two
// disagree about where a point is, the boat sits off the marks and the start line stops
// lining up with the geometry the finish is detected against. That would look like a data
// fault and would not be one. So this file mirrors nav.py's enu() exactly, constant for
// constant, and static/geo-check.html compares the two against a fixture generated from
// nav.py itself.
//
// Why a local plane at all, rather than Mercator. The map covers about 10 km of river,
// and a plane whose scale is fixed at one origin latitude is linear: a straight line
// between two points on the ground is a straight line on the screen, and the line-crossing
// geometry the engine does in this same frame stays valid when it is drawn. nav.py's own
// comment records the cost, up to about a metre of position error 10 km out, which is well
// inside GPS scatter and invisible at any zoom this page offers.
//
// var and function rather than const and arrow functions, to match static/app.js and
// hud.html, which are written that way throughout. Not a compatibility requirement: iOS 12
// is Safari 12 and handles ES6 perfectly well. The things that genuinely are not there on
// that device are clamp(), flexbox gap and Pointer Events, and none of them is syntax.

window.Geo = (function () {
  "use strict";

  // WGS84, from engine/nav.py lines 57-59. Not rounded, not a spherical approximation:
  // the two radii of curvature differ by about half a per cent, and at 32 South the
  // parallel is 15 per cent shorter than the meridian, so a single constant is wrong in
  // both components at once.
  var WGS84_A = 6378137.0;
  var WGS84_F = 1.0 / 298.257223563;
  var WGS84_E2 = WGS84_F * (2.0 - WGS84_F);
  var DEG = Math.PI / 180.0;

  // nav.py metres_per_degree(). Meridian radius of curvature for latitude, prime vertical
  // scaled by cos(lat) for longitude.
  function metresPerDegree(lat) {
    var s = Math.sin(lat * DEG);
    var w = 1.0 - WGS84_E2 * s * s;
    var mLat = WGS84_A * (1.0 - WGS84_E2) / Math.pow(w, 1.5);
    var mLon = WGS84_A / Math.sqrt(w) * Math.cos(lat * DEG);
    return { lat: mLat * DEG, lon: mLon * DEG };
  }

  // nav.py norm180(). Here only to keep enu() a faithful copy: a course that straddles
  // the antimeridian is not a thing on the Swan, but transcribing the function with a
  // piece missing is how the two drift apart later.
  function norm180(deg) {
    var d = (deg + 180.0) % 360.0 - 180.0;
    // JavaScript's % keeps the sign of the dividend where Python's does not, so a
    // negative input lands a full turn away from where Python puts it. This is the one
    // place the transcription is not character for character, and the reason is here.
    if (d <= -180.0) d += 360.0;
    return d === -180.0 ? 180.0 : d;
  }

  // nav.py enu(). Metres east and north of origin, on the plane fixed by origin's
  // latitude. Accepts {lat, lon} for both, which is the shape marks.json uses and the
  // shape gps/position/0 delivers.
  function enu(origin, point) {
    var m = metresPerDegree(origin.lat);
    return {
      e: norm180(point.lon - origin.lon) * m.lon,
      n: (point.lat - origin.lat) * m.lat
    };
  }

  return {
    metresPerDegree: metresPerDegree,
    norm180: norm180,
    enu: enu,
    WGS84_A: WGS84_A,
    WGS84_E2: WGS84_E2
  };
}());
