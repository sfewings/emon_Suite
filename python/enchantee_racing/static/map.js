// Course map. Build step 3 of DESIGN 12.1: the static chart, no interaction and no live
// boat yet.
//
// Everything is drawn in one coordinate system: metres east and north of the start line's
// inner end, projected by geo.js, which is a transcription of the engine's own projection
// so the map and the engine cannot disagree about where a point is (DESIGN 12.1 step 2).
//
// The path data is built once and never rebuilt. Zooming and panning move the svg's
// viewBox, which costs the browser a transform and no re-layout, and means the 16,000
// coordinate pairs in coast.json and depth.json are parsed exactly once. That is the
// whole reason the viewBox is in metres rather than in degrees or pixels.
//
// One inversion to keep in mind throughout: north is +n in the projection and up on the
// screen, but SVG's y axis points down. So y = -n, applied in one place, project(), and
// nowhere else. Getting that wrong mirrors the map north to south, which on this river
// looks almost plausible.
//
// var and function to match app.js and hud.html. iOS 12 handles ES6 fine; what it does
// not have is clamp(), flexbox gap and Pointer Events (CLAUDE.md).

(function () {
  "use strict";

  // Built from location.pathname like every other fetch in this app, so the page works
  // behind /race/ and on the app's own port alike (CLAUDE.md).
  var base = location.pathname.replace(/\/[^\/]*$/, "");

  var el = {
    chart: document.getElementById("chart"),
    bands: document.getElementById("layer-bands"),
    contours: document.getElementById("layer-contours"),
    land: document.getElementById("layer-land"),
    lines: document.getElementById("layer-lines"),
    marks: document.getElementById("layer-marks")
  };

  var SVG_NS = "http://www.w3.org/2000/svg";

  // The frame's origin, and the whole map's. Set from lines.json once it arrives, because
  // the start line's inner end is the one point on the course that does not move between
  // races, and it is the origin the projection fixture is generated against.
  var origin = null;

  // The mark symbols, kept so their size can be recomputed when the view changes. A chart
  // draws a mark at a constant size on the paper, not a constant size on the ground: a
  // buoy is a few pixels whatever the scale, and the label stays readable. SVG has no way
  // to say that declaratively, since vector-effect only governs strokes, so the radius and
  // the font size are set in user units against the current metres-per-pixel.
  //
  // The alternative was to leave them in metres, which is what the first draft did: at the
  // racing extent a 25 m radius came out at 1.7 px and the marks were invisible specks.
  var symbols = [];          // {circle, label, usedInCourses}
  var SYMBOL_PX = { used: 4.5, context: 2.5, label: 11, labelGap: 6 };

  function project(lonLat) {
    // GeoJSON is [lon, lat]; geo.js takes {lat, lon}. Being the only place the two
    // conventions meet, this is the only place they can be crossed over.
    var p = Geo.enu(origin, { lat: lonLat[1], lon: lonLat[0] });
    return [p.e, -p.n];
  }

  // --- turning GeoJSON into path data -------------------------------------------------
  //
  // Coordinates are rounded to 0.1 m. Sub-decimetre precision in a path string is noise:
  // it cannot be seen at any zoom this page offers, and it doubles the length of the
  // attribute the browser has to parse.

  function ring(coords) {
    var parts = [];
    for (var i = 0; i < coords.length; i++) {
      var xy = project(coords[i]);
      parts.push((i === 0 ? "M" : "L") + xy[0].toFixed(1) + " " + xy[1].toFixed(1));
    }
    return parts.join("");
  }

  function polygonPath(rings) {
    // Rings after the first are holes. Kept, rather than dropped: the coast has islands
    // and the depth bands have unsurveyed gaps, and a filled hole is a lie about water.
    var out = "";
    for (var i = 0; i < rings.length; i++) out += ring(rings[i]) + "Z";
    return out;
  }

  function pathFor(geometry) {
    var type = geometry.type;
    var c = geometry.coordinates;
    if (type === "Polygon") return polygonPath(c);
    if (type === "MultiPolygon") {
      var out = "";
      for (var i = 0; i < c.length; i++) out += polygonPath(c[i]);
      return out;
    }
    if (type === "LineString") return ring(c);
    if (type === "MultiLineString") {
      var lines = "";
      for (var j = 0; j < c.length; j++) lines += ring(c[j]);
      return lines;
    }
    return "";
  }

  function add(parent, name, attrs) {
    var node = document.createElementNS(SVG_NS, name);
    for (var key in attrs) {
      if (attrs.hasOwnProperty(key) && attrs[key] !== null) {
        node.setAttribute(key, attrs[key]);
      }
    }
    parent.appendChild(node);
    return node;
  }

  // --- extent, in projected metres ----------------------------------------------------

  function extentOf(bbox) {
    // A bbox from marks.json or coast.json: {south, west, north, east}. Projected, the
    // south-west corner is the largest y because y is flipped, so both corners are taken
    // and then sorted rather than assumed.
    var a = project([bbox.west, bbox.south]);
    var b = project([bbox.east, bbox.north]);
    return {
      x: Math.min(a[0], b[0]),
      y: Math.min(a[1], b[1]),
      w: Math.abs(b[0] - a[0]),
      h: Math.abs(b[1] - a[1])
    };
  }

  function setView(extent, marginFraction) {
    // A margin, so nothing of interest sits against the glass. Taken from the larger side
    // so the margin is the same number of metres in both directions and the scale stays
    // square.
    var margin = Math.max(extent.w, extent.h) * (marginFraction || 0.04);
    el.chart.setAttribute("viewBox",
      (extent.x - margin).toFixed(1) + " " + (extent.y - margin).toFixed(1) + " " +
      (extent.w + margin * 2).toFixed(1) + " " + (extent.h + margin * 2).toFixed(1));
    applyScale();
  }

  function metresPerPixel() {
    var box = (el.chart.getAttribute("viewBox") || "0 0 1 1").split(/\s+/);
    var width = parseFloat(box[2]);
    var height = parseFloat(box[3]);
    var rect = el.chart.getBoundingClientRect();
    if (!rect.width || !rect.height) return width;   // not laid out yet
    // preserveAspectRatio is meet, so the scale is set by whichever axis has to fit, which
    // is the larger ratio of metres to pixels.
    return Math.max(width / rect.width, height / rect.height);
  }

  function applyScale() {
    var mpp = metresPerPixel();
    if (!isFinite(mpp) || mpp <= 0) return;
    el.marks.setAttribute("font-size", (SYMBOL_PX.label * mpp).toFixed(2));
    for (var i = 0; i < symbols.length; i++) {
      var sym = symbols[i];
      var px = sym.used ? SYMBOL_PX.used : SYMBOL_PX.context;
      sym.circle.setAttribute("r", (px * mpp).toFixed(2));
      if (sym.label) {
        var gap = (SYMBOL_PX.used + SYMBOL_PX.labelGap) * mpp;
        sym.label.setAttribute("x", (sym.x + gap).toFixed(1));
        sym.label.setAttribute("y", (sym.y - gap).toFixed(1));
      }
    }
  }

  // --- the layers, drawn bottom first (DESIGN 12) --------------------------------------

  function drawDepth(depth) {
    // Bands first, as filled areas, then the contours that divide them as strokes. The
    // colour is carried in the data rather than decided here, so the palette lives in one
    // place and gen_depth.py owns it. The night theme overrides by band id in CSS, which
    // is why the id goes on the class as well.
    var bands = [], contours = [];
    depth.features.forEach(function (f) {
      (f.properties.kind === "band" ? bands : contours).push(f);
    });

    // Deep first so shallow draws over it: the bands overlap at their shared edges and
    // shallowest-darkest only reads if the shallow one wins (DESIGN 12).
    var order = { deep: 0, mid: 1, shallow: 2 };
    bands.sort(function (a, b) {
      return (order[a.properties.band] || 0) - (order[b.properties.band] || 0);
    });

    bands.forEach(function (f) {
      add(el.bands, "path", {
        d: pathFor(f.geometry),
        class: "band band-" + f.properties.band,
        fill: f.properties.color
      });
    });

    contours.forEach(function (f) {
      add(el.contours, "path", {
        d: pathFor(f.geometry),
        class: "contour contour-" + String(f.properties.depth_m).replace(".", "-"),
        fill: "none"
      });
    });
  }

  function drawCoast(coast) {
    coast.features.forEach(function (f) {
      add(el.land, "path", { d: pathFor(f.geometry), class: "land" });
    });
  }

  function segment(parent, a, b, cls) {
    var p = project([a.lon, a.lat]), q = project([b.lon, b.lat]);
    add(parent, "line", {
      x1: p[0].toFixed(1), y1: p[1].toFixed(1),
      x2: q[0].toFixed(1), y2: q[1].toFixed(1),
      class: cls
    });
  }

  function drawLines(lines, markIndex) {
    var sf = lines.start_finish;
    segment(el.lines, sf.inner, sf.outer, "startline");

    // The two lines it is a breach to cross while racing (DESIGN 11.3). Drawn because a
    // rule you can see is a rule you can keep, and dashed so they read as prohibitions
    // rather than as legs. Mosman is deliberately absent from the data, since nothing
    // prohibits crossing between 14 and 13 (DESIGN 6), so nothing is drawn for it.
    //
    // These carry mark ids rather than coordinates, and are resolved through the index
    // rather than by number: fourteen numbers belong to two marks each, so id is the
    // only safe key (CLAUDE.md).
    (lines.no_cross_lines || []).forEach(function (l) {
      var a = markIndex[l.marks[0]], b = markIndex[l.marks[1]];
      if (!a || !b) return;      // a line naming a mark that is not shipped draws nothing
      segment(el.lines, a, b, "nocross");
    });
  }

  function drawMarks(marks) {
    marks.marks.forEach(function (m) {
      var xy = project([m.lon, m.lat]);
      var used = !!m.used_in_courses;
      var g = add(el.marks, "g", {
        class: "mark" + (used ? " mark-used" : " mark-context"),
        "data-id": m.id
      });
      // The radius is left to applyScale(), which sizes it in pixels against the current
      // view. Same for the label's offset, so it stays beside its mark rather than
      // drifting away from it as the scale changes.
      var circle = add(g, "circle", { cx: xy[0].toFixed(1), cy: xy[1].toFixed(1), r: 0 });
      var label = null;
      // Labels for the course marks only, for now. Which marks are labelled at which zoom
      // is build step 6; at the racing extent 131 labels is illegible and DESIGN 12 says
      // so.
      if (used) {
        label = add(g, "text", { x: xy[0], y: xy[1], class: "mark-label" });
        label.textContent = m.name;
      }
      symbols.push({ circle: circle, label: label, used: used, x: xy[0], y: xy[1] });
    });
  }

  // --- load ---------------------------------------------------------------------------

  function fetchJson(name) {
    return fetch(base + "/api/config/" + name, { cache: "no-store" })
      .then(function (r) {
        if (!r.ok) throw new Error(name + ": http " + r.status);
        return r.json();
      });
  }

  function fail(message) {
    var note = document.getElementById("map-caveat");
    if (note) {
      note.textContent = "Map data did not load: " + message;
      note.className = "failed";
    }
  }

  // Cross-page navigation by script, not by the anchor. Added to the Home Screen, iOS
  // treats a plain anchor to another document as leaving the web app and reopens it in an
  // overlay browser; the manifest's scope covers all three screens but iOS 12 predates
  // scope enforcement and needs this (DESIGN 9.8.1). app.js and hud.html carry the same
  // handler, and one test holds all three to it.
  Array.prototype.forEach.call(document.querySelectorAll("#nav a[href]"), function (a) {
    a.addEventListener("click", function (event) {
      event.preventDefault();
      location.assign(a.href);
    });
  });

  Promise.all([fetchJson("lines"), fetchJson("marks"),
               fetchJson("coast"), fetchJson("depth")])
    .then(function (all) {
      var lines = all[0], marks = all[1], coast = all[2], depth = all[3];

      // The origin has to be set before anything is projected, and everything below
      // depends on it, which is why it is the first thing this function does.
      origin = { lat: lines.start_finish.inner.lat, lon: lines.start_finish.inner.lon };

      var markIndex = {};
      marks.marks.forEach(function (m) { markIndex[m.id] = m; });

      drawDepth(depth);
      drawCoast(coast);
      drawLines(lines, markIndex);
      drawMarks(marks);

      // The racing bbox for now. Fit-to-current-course, and the second zoom-out to the
      // whole coast extent, are build step 4 (DESIGN 12.1).
      setView(extentOf(marks.bbox));

      // The symbols are sized against the element's pixel size, so a rotation or a split
      // view changes them. orientationchange as well as resize, because iOS fires the
      // first before the new size is settled and hud.html already learned that lesson.
      window.addEventListener("resize", applyScale);
      window.addEventListener("orientationchange", function () {
        setTimeout(applyScale, 250);
      });

      document.body.setAttribute("data-map", "ready");
    })
    .catch(function (e) { fail(String(e)); });
}());
