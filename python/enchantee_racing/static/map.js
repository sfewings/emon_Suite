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
    marks: document.getElementById("layer-marks"),
    fit: document.getElementById("map-fit"),
    out: document.getElementById("map-out"),
    scope: document.getElementById("map-scope")
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

  // --- the view ----------------------------------------------------------------------
  //
  // Three levels, which DESIGN 12.1 settled: fit to the current course, then out to the
  // racing bbox, then out again to the whole coast extent. Two zoom-outs rather than one
  // because coast.json was deliberately generated far wider than the racing area for
  // ocean races and the island anchorages, and a single level would have to choose
  // between making that unreachable and making the ordinary case illegible.
  //
  // Free pan and pinch on top of that, and a Fit button to get back. The buttons are the
  // reliable path: they work with wet hands and one of them always returns the crew to
  // the course, which is what matters when the map has been dragged somewhere useless.
  var view = null;           // {x, y, w, h} in projected metres, mirrors the viewBox
  var levels = [];           // extents, index 0 the course, 2 the whole coast
  var level = 0;

  // Zoom limits. Out is the coast extent with a little slack, so the map cannot end up a
  // speck in a void; in is 100 m across, which is a mark approach and about as close as
  // data simplified at 10 m can honestly be read (DESIGN 12).
  var MIN_SPAN_M = 100;
  var MAX_SLACK = 1.25;

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

  function padded(extent, marginFraction) {
    // A margin, so nothing of interest sits against the glass. Taken from the larger side
    // so the margin is the same number of metres in both directions and the scale stays
    // square.
    var margin = Math.max(extent.w, extent.h) * (marginFraction || 0.04);
    return { x: extent.x - margin, y: extent.y - margin,
             w: extent.w + margin * 2, h: extent.h + margin * 2 };
  }

  function extentOfPoints(points) {
    var xs = [], ys = [];
    for (var i = 0; i < points.length; i++) { xs.push(points[i][0]); ys.push(points[i][1]); }
    var minX = Math.min.apply(null, xs), maxX = Math.max.apply(null, xs);
    var minY = Math.min.apply(null, ys), maxY = Math.max.apply(null, ys);
    return { x: minX, y: minY, w: maxX - minX, h: maxY - minY };
  }

  function clampView(v) {
    var outer = levels.length ? levels[levels.length - 1] : v;
    var maxW = outer.w * MAX_SLACK, maxH = outer.h * MAX_SLACK;

    // Zoom, on the larger axis so the aspect ratio is never touched: a map that stretches
    // is worse than no map, because a bearing read off it would be wrong.
    var scale = 1;
    if (v.w > maxW || v.h > maxH) scale = Math.min(maxW / v.w, maxH / v.h);
    if (v.w < MIN_SPAN_M || v.h < MIN_SPAN_M) {
      scale = Math.max(MIN_SPAN_M / v.w, MIN_SPAN_M / v.h);
    }
    if (scale !== 1) {
      var cx = v.x + v.w / 2, cy = v.y + v.h / 2;
      v = { x: cx - v.w * scale / 2, y: cy - v.h * scale / 2,
            w: v.w * scale, h: v.h * scale };
    }

    // Pan, by keeping the centre inside the outer extent. Looser than clamping the edges,
    // which would refuse to show a mark on the boundary, and enough that the crew can
    // never drag the chart off the screen entirely.
    var centreX = Math.min(Math.max(v.x + v.w / 2, outer.x), outer.x + outer.w);
    var centreY = Math.min(Math.max(v.y + v.h / 2, outer.y), outer.y + outer.h);
    return { x: centreX - v.w / 2, y: centreY - v.h / 2, w: v.w, h: v.h };
  }

  function setView(v) {
    view = clampView(v);
    el.chart.setAttribute("viewBox",
      view.x.toFixed(1) + " " + view.y.toFixed(1) + " " +
      view.w.toFixed(1) + " " + view.h.toFixed(1));
    applyScale();
  }

  function showLevel(i) {
    level = Math.min(Math.max(i, 0), levels.length - 1);
    setView(padded(levels[level]));
    if (el.out) el.out.disabled = (level >= levels.length - 1);
  }

  // --- gestures ----------------------------------------------------------------------
  //
  // Touch events, not Pointer Events: those need Safari 13 and the boat's iPad is on 12,
  // which is the same list clamp() and flexbox gap are on. It is also the trap every
  // pan-and-zoom recipe falls into, since they all reach for pointerdown.
  //
  // Screen to user coordinates goes through the svg's own CTM rather than arithmetic on
  // the element's rect. preserveAspectRatio is meet, so there are letterbox margins
  // whenever the viewBox aspect does not match the element's, and getScreenCTM already
  // accounts for them. Hand-computing that is a whole class of off-by-a-margin bug that
  // this simply does not have.

  function clientToUser(clientX, clientY) {
    var ctm = el.chart.getScreenCTM();
    if (!ctm) return null;
    var pt = el.chart.createSVGPoint();   // deprecated, and the one iOS 12 has
    pt.x = clientX;
    pt.y = clientY;
    pt = pt.matrixTransform(ctm.inverse());
    return { x: pt.x, y: pt.y };
  }

  var gesture = null;

  function midpoint(touches) {
    return { x: (touches[0].clientX + touches[1].clientX) / 2,
             y: (touches[0].clientY + touches[1].clientY) / 2 };
  }

  function spread(touches) {
    var dx = touches[0].clientX - touches[1].clientX;
    var dy = touches[0].clientY - touches[1].clientY;
    return Math.sqrt(dx * dx + dy * dy);
  }

  // Zoom about a fixed screen point. The size is set first and the view then shifted so
  // the user-space point that was under the finger is under it again, which is exact at
  // any aspect ratio and needs no knowledge of the letterboxing.
  function zoomAbout(clientX, clientY, factor) {
    var anchor = clientToUser(clientX, clientY);
    if (!anchor) return;
    setView({ x: view.x, y: view.y, w: view.w * factor, h: view.h * factor });
    var now = clientToUser(clientX, clientY);
    if (!now) return;
    setView({ x: view.x + (anchor.x - now.x), y: view.y + (anchor.y - now.y),
              w: view.w, h: view.h });
  }

  function panBy(dxPixels, dyPixels, from) {
    // Scale is constant while panning, so this is a plain multiplication rather than
    // another CTM round trip. Dragging right moves the chart right, which means the
    // window over it moves left.
    var mpp = metresPerPixel();
    setView({ x: from.x - dxPixels * mpp, y: from.y - dyPixels * mpp,
              w: from.w, h: from.h });
  }

  function onTouchStart(event) {
    if (!view) return;
    if (event.touches.length === 1) {
      gesture = { kind: "pan", x: event.touches[0].clientX, y: event.touches[0].clientY,
                  from: view };
    } else if (event.touches.length === 2) {
      gesture = { kind: "pinch", spread: spread(event.touches),
                  mid: midpoint(event.touches) };
    }
    if (gesture) event.preventDefault();
  }

  function onTouchMove(event) {
    if (!gesture || !view) return;
    event.preventDefault();
    if (gesture.kind === "pan" && event.touches.length === 1) {
      panBy(event.touches[0].clientX - gesture.x,
            event.touches[0].clientY - gesture.y, gesture.from);
    } else if (gesture.kind === "pinch" && event.touches.length === 2) {
      var now = spread(event.touches);
      if (!now || !gesture.spread) return;
      var mid = midpoint(event.touches);
      zoomAbout(mid.x, mid.y, gesture.spread / now);
      gesture.spread = now;
      gesture.mid = mid;
    }
  }

  function onTouchEnd(event) {
    // A finger lifted out of a pinch leaves one down, which should become a pan rather
    // than nothing: otherwise the map sticks until the crew lets go completely.
    if (event.touches.length === 1) {
      gesture = { kind: "pan", x: event.touches[0].clientX, y: event.touches[0].clientY,
                  from: view };
    } else if (event.touches.length === 0) {
      gesture = null;
    }
  }

  function bindGestures() {
    el.chart.addEventListener("touchstart", onTouchStart, false);
    el.chart.addEventListener("touchmove", onTouchMove, false);
    el.chart.addEventListener("touchend", onTouchEnd, false);
    el.chart.addEventListener("touchcancel", onTouchEnd, false);

    // Mouse, for a laptop on the jetty (CLAUDE.md wants the app editable and usable from
    // one). Not a substitute for the touch path and not tested by it.
    el.chart.addEventListener("mousedown", function (e) {
      if (!view) return;
      gesture = { kind: "pan", x: e.clientX, y: e.clientY, from: view };
      e.preventDefault();
    });
    window.addEventListener("mousemove", function (e) {
      if (!gesture || gesture.kind !== "pan" || !view) return;
      panBy(e.clientX - gesture.x, e.clientY - gesture.y, gesture.from);
    });
    window.addEventListener("mouseup", function () { gesture = null; });
    el.chart.addEventListener("wheel", function (e) {
      if (!view) return;
      e.preventDefault();
      zoomAbout(e.clientX, e.clientY, e.deltaY > 0 ? 1.2 : 1 / 1.2);
    });
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

  // The course the race is on, so the default view can be fit to it (DESIGN 12). One
  // fetch at load, not a poll: this page is its own document, so arriving at it is what
  // picks up a change of course. Following the race live is the next build step.
  //
  // A failure here is not a failure of the map: no course selected is the ordinary idle
  // case, and the racing bbox is the right view then. So this resolves to null rather
  // than rejecting, and never blocks the chart from drawing.
  function fetchCourse() {
    return fetch(base + "/api/state", { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (state) {
        var id = state && state.race && state.race.course;
        if (!id) return null;
        return fetch(base + "/api/course/" + encodeURIComponent(id),
                     { cache: "no-store" })
          .then(function (r) { return r.ok ? r.json() : null; });
      })
      .catch(function () { return null; });
  }

  // Every mark the course visits, plus both ends of the start line, since the race begins
  // and ends there and a view that cut the line off would be missing the part the crew
  // looks at first.
  function courseExtent(course, markIndex, lines) {
    if (!course || !course.legs) return null;
    var points = [
      project([lines.start_finish.inner.lon, lines.start_finish.inner.lat]),
      project([lines.start_finish.outer.lon, lines.start_finish.outer.lat])
    ];
    course.legs.forEach(function (leg) {
      var m = leg.mark && markIndex[leg.mark];
      if (m) points.push(project([m.lon, m.lat]));
    });
    return points.length > 2 ? extentOfPoints(points) : null;
  }

  Promise.all([fetchJson("lines"), fetchJson("marks"),
               fetchJson("coast"), fetchJson("depth"), fetchCourse()])
    .then(function (all) {
      var lines = all[0], marks = all[1], coast = all[2], depth = all[3];
      var course = all[4];

      // The origin has to be set before anything is projected, and everything below
      // depends on it, which is why it is the first thing this function does.
      origin = { lat: lines.start_finish.inner.lat, lon: lines.start_finish.inner.lon };

      var markIndex = {};
      marks.marks.forEach(function (m) { markIndex[m.id] = m; });

      drawDepth(depth);
      drawCoast(coast);
      drawLines(lines, markIndex);
      drawMarks(marks);

      // Three levels, outermost last (DESIGN 12.1). The course level falls back to the
      // racing bbox when no course is selected, which keeps the array three long and the
      // Out button's meaning the same either way.
      var racing = extentOf(marks.bbox);
      var fitted = courseExtent(course, markIndex, lines);
      levels = [fitted || racing, racing, extentOf(coast.bbox)];

      var names = [course && fitted ? (course.series_name || "course") + " " +
                                      course.course_no : "racing area",
                   "racing area", "Swan and the coast"];
      if (el.scope) {
        var label = function () { el.scope.textContent = names[level]; };
        el.chart.addEventListener("touchend", label);
        window.addEventListener("mouseup", label);
      }

      bindGestures();
      if (el.fit) {
        el.fit.addEventListener("click", function () { showLevel(0); if (el.scope) el.scope.textContent = names[0]; });
      }
      if (el.out) {
        el.out.addEventListener("click", function () { showLevel(level + 1); if (el.scope) el.scope.textContent = names[level]; });
      }
      showLevel(0);
      if (el.scope) el.scope.textContent = names[0];

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
