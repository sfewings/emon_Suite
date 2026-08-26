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
    structures: document.getElementById("layer-structures"),
    navaids: document.getElementById("layer-navaids"),
    lines: document.getElementById("layer-lines"),
    marks: document.getElementById("layer-marks"),
    course: document.getElementById("layer-course"),
    boat: document.getElementById("layer-boat"),
    zoom: document.getElementById("map-zoom"),
    readout: document.getElementById("map-readout")
  };

  // The four cells of the strip, left to right. Their contents change with what the boat
  // is doing; the cells themselves never move.
  var cells = el.readout
    ? Array.prototype.map.call(el.readout.querySelectorAll(".cell"), function (cell) {
        return { cell: cell,
                 lbl: cell.querySelector(".lbl"),
                 val: cell.querySelector(".val"),
                 unit: cell.querySelector(".unit") };
      })
    : [];

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
  // Three named extents, which DESIGN 12.2 settled: the race course, the river, and
  // everything. Two zoom-outs rather than one because coast.json was deliberately
  // generated far wider than the racing area for ocean races and the island anchorages,
  // and a single level would have to choose between making that unreachable and making
  // the ordinary case illegible.
  //
  // One button cycles them and free pan and pinch sit on top of it. Once the chart has
  // been moved the button offers to fit the extent it names before it will advance, so the
  // tap that recovers a map dragged somewhere useless is always the next tap. That was the
  // one property of the old two-button Fit/Out pair worth carrying over.
  var view = null;           // {x, y, w, h} in projected metres, mirrors the viewBox
  var levels = [];           // extents, index 0 the course, 2 everything
  var level = 0;
  var moved = false;         // the view has been panned or pinched off levels[level]

  var LEVEL_NAMES = ["Race course", "River", "Everything"];

  // The span of the innermost extent when there is no course to fit: a region the size of
  // a race, with the boat in the middle of it. The twenty-three courses in config run from
  // 1856 m to 5349 m across with a median of 3082, so 3000 m is a race-sized view by
  // measurement rather than by feel (DESIGN 12.2).
  var COURSE_SPAN_M = 3000;

  // Zoom limits. Out is the coast extent with a little slack, so the map cannot end up a
  // speck in a void; in is 100 m across, which is a mark approach and about as close as
  // data simplified at 10 m can honestly be read (DESIGN 12).
  var MIN_SPAN_M = 100;
  var MAX_SLACK = 1.25;

  // The zoom past which the aid register is more clutter than information. Their size is
  // in the stylesheet, where non-scaling-stroke already holds it constant on screen.
  var NAVAID_MAX_MPP = 25;

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
    var previous = view;
    view = clampView(v);
    el.chart.setAttribute("viewBox",
      view.x.toFixed(1) + " " + view.y.toFixed(1) + " " +
      view.w.toFixed(1) + " " + view.h.toFixed(1));
    // Only when the scale actually changed. applyScale writes an attribute to all 131
    // circles and 20 labels, and a pan does not change the scale at all, so doing it on
    // every touchmove was 151 pointless attribute writes per event. Reported from the
    // boat as pan and pinch being slower on the iPad than the iPhone, which is the
    // machine that would notice.
    if (!previous || previous.w !== view.w) applyScale();
  }

  // Gesture updates are coalesced to one per frame. iOS delivers touchmove faster than it
  // paints, so without this a pinch could run clampView and a viewBox write several times
  // for one frame on screen, and on the iPad that is the difference between workable and
  // smooth. The buttons call setView directly: they happen once and should feel instant.
  var pendingView = null;
  var frame = null;

  function scheduleView(v) {
    pendingView = v;
    if (frame !== null) return;
    frame = requestAnimationFrame(function () {
      frame = null;
      var next = pendingView;
      pendingView = null;
      if (next) setView(next);
    });
  }

  // The innermost extent when no course is selected: a race-sized region centred on the
  // boat. Not the racing bbox, which is three times the span of any course and shows the
  // crew a view they never sail in; and not a follow, which was considered and dropped
  // because a view that recentres itself fights the hand that just panned it. The boat is
  // put in the middle when this extent is asked for, and stays where it goes after that.
  //
  // With no fix, the start line's inner end, which is the origin and the club.
  function boatRegion() {
    var half = COURSE_SPAN_M / 2;
    var at = [0, 0];
    var fix = lastState && lastState.position && !lastState.position.stale
            ? lastState.position.v : null;
    if (fix && origin) at = project([fix.lon, fix.lat]);
    return { x: at[0] - half, y: at[1] - half, w: COURSE_SPAN_M, h: COURSE_SPAN_M };
  }

  // levels[0] is whichever of the two the boat is in a position to want: the course being
  // sailed if there is one, else a race-sized region around the boat, recomputed each time
  // it is asked for so it is centred on where the boat is now rather than where it was at
  // load.
  function innerExtent() {
    return courseExtentNow || boatRegion();
  }

  function showLevel(i) {
    level = Math.min(Math.max(i, 0), levels.length - 1);
    if (level === 0) levels[0] = innerExtent();
    setView(padded(levels[level]));
    moved = false;
    labelZoom();
  }

  // The button says where you are and, once the chart has been moved, what one tap will
  // get you back to. Two states rather than one because a name alone is a label and the
  // crew needs a control: after a pinch, "FIT RIVER" is the only text on the page that
  // says the view is no longer any of the three.
  function labelZoom() {
    if (!el.zoom) return;
    var name = LEVEL_NAMES[level] || "";
    el.zoom.textContent = moved ? "Fit " + name : name;
    el.zoom.setAttribute("data-fit", moved ? "yes" : "no");
  }

  // A tap fits the named extent first if the chart has been moved off it, and otherwise
  // steps to the next one and wraps. Wrapping rather than stopping at Everything: with one
  // button there is no other way back in, and a control that does nothing when tapped is
  // worse on a wet screen than one that goes somewhere.
  function cycleZoom() {
    if (moved) showLevel(level);
    else showLevel((level + 1) % levels.length);
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
    moved = true;
    labelZoom();
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
    if (!moved) { moved = true; labelZoom(); }
    scheduleView({ x: from.x - dxPixels * mpp, y: from.y - dyPixels * mpp,
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

  // --- which labels are shown, and where (DESIGN 12.1 step 6) --------------------------
  //
  // Two things decide it. A threshold says which marks are eligible at this zoom, and
  // collision avoidance thins whatever is eligible down to what actually fits.
  //
  // A threshold alone is not enough, which is the thing worth knowing here. At the racing
  // extent the twenty course marks overlap into an unreadable mat, so a rule that showed
  // course labels above some zoom and nothing below it would leave the view the crew uses
  // to see the whole race area with no names on it at all. Thinning by collision keeps as
  // many as fit at every zoom, which is what a chart does.
  //
  // Priority decides who survives a collision: the mark being sailed to first, then the
  // rest of the course, then the context marks. So the label that matters most is the one
  // that is never dropped.
  var LABEL_MAX_MPP = 50;       // beyond this nothing is labelled: the coast extent
  var LABEL_CONTEXT_MPP = 1.0;  // below this the 111 context marks are eligible too
  // Estimated label width: characters, plus the halo, plus a little air.
  //
  // Measured rather than guessed, and the first guess was wrong. 0.58 of the font size per
  // character let seven pairs overlap at the racing extent, because the real ratio runs
  // from 0.66 for a long name to 0.72 for a short one. The spread is the halo: mark-label
  // paints a 3 px stroke behind the text, which adds a constant that is proportionally
  // much larger for "Bond" than for "Bricklanding A". So the halo is modelled separately
  // rather than averaged into the per-character figure, which is what made one number fit
  // both ends.
  var LABEL_CHAR_W = 0.66;      // width of a character as a fraction of the font size
  var LABEL_HALO_PX = 3;        // the halo's stroke width, in screen pixels
  var LABEL_AIR_PX = 2;         // so two labels that just miss still look separate

  function overlaps(a, b) {
    return !(a.right < b.left || b.right < a.left ||
             a.bottom < b.top || b.bottom < a.top);
  }

  function layoutLabels(targetId) {
    var mpp = metresPerPixel();
    if (!isFinite(mpp) || mpp <= 0 || !view) return;

    var showContext = mpp <= LABEL_CONTEXT_MPP;
    var showAny = mpp <= LABEL_MAX_MPP;

    // Priority order, and a stable one: the target, then the course, then the rest. Array
    // order is the tie-break, which is marks.json order, so the same marks win the same
    // collisions every time and labels do not flicker between two poll ticks.
    var order = symbols.slice();
    order.sort(function (a, b) {
      return rank(a, targetId) - rank(b, targetId);
    });

    var gap = (SYMBOL_PX.used + SYMBOL_PX.labelGap) * mpp;
    var fontH = SYMBOL_PX.label * mpp;
    var placed = [];
    var bounds = { left: view.x, right: view.x + view.w,
                   top: view.y, bottom: view.y + view.h };

    for (var i = 0; i < order.length; i++) {
      var sym = order[i];
      var eligible = showAny && (sym.used || showContext);
      if (!eligible) { hide(sym.label); continue; }

      // The label's width is estimated from its character count rather than measured with
      // getBBox. Measuring 131 text nodes would force a layout on every view change, and
      // this page already had to be made faster for the iPad once; an estimate that is a
      // few pixels out only ever costs a label that could have fitted.
      // A stroke of width W paints W/2 either side, so it adds W to the box, not 2W.
      var w = sym.chars * fontH * LABEL_CHAR_W + (LABEL_HALO_PX + LABEL_AIR_PX * 2) * mpp;
      var air = LABEL_AIR_PX * mpp;

      // Four placements, tried in order, so a label blocked on one side can go to the
      // other rather than being dropped. This is also what keeps names off the edge of
      // the screen: an off-screen placement is rejected like any other collision.
      var options = [
        { x: sym.x + gap, y: sym.y - gap, anchor: "start" },
        { x: sym.x - gap, y: sym.y - gap, anchor: "end" },
        { x: sym.x + gap, y: sym.y + gap + fontH * 0.8, anchor: "start" },
        { x: sym.x - gap, y: sym.y + gap + fontH * 0.8, anchor: "end" }
      ];

      var chosen = null;
      for (var o = 0; o < options.length && !chosen; o++) {
        var opt = options[o];
        var box = {
          left: opt.anchor === "start" ? opt.x : opt.x - w,
          right: opt.anchor === "start" ? opt.x + w : opt.x,
          top: opt.y - fontH * 0.8 - air,
          bottom: opt.y + fontH * 0.2 + air
        };
        if (box.left < bounds.left || box.right > bounds.right ||
            box.top < bounds.top || box.bottom > bounds.bottom) continue;
        var clash = false;
        for (var j = 0; j < placed.length && !clash; j++) {
          clash = overlaps(box, placed[j]);
        }
        if (!clash) { chosen = { opt: opt, box: box }; }
      }

      if (!chosen) { hide(sym.label); continue; }
      sym.label.setAttribute("x", chosen.opt.x.toFixed(1));
      sym.label.setAttribute("y", chosen.opt.y.toFixed(1));
      sym.label.setAttribute("text-anchor", chosen.opt.anchor);
      sym.label.removeAttribute("hidden");
      placed.push(chosen.box);
    }
  }

  function rank(sym, targetId) {
    if (targetId && sym.id === targetId) return 0;
    return sym.used ? 1 : 2;
  }

  function hide(label) {
    if (label) label.setAttribute("hidden", "hidden");
  }

  // The mark the race is steering to, so its label is the one that never loses a
  // collision. Null before the gun and after the finish, which is correct: there is no
  // mark being sailed to then.
  function targetMarkId() {
    if (!lastState || !lastState.race || !courseNow || !courseNow.legs) return null;
    var leg = courseNow.legs[lastState.race.leg];
    return leg ? leg.mark : null;
  }

  function applyScale() {
    var mpp = metresPerPixel();
    if (!isFinite(mpp) || mpp <= 0) return;
    el.marks.setAttribute("font-size", (SYMBOL_PX.label * mpp).toFixed(2));
    // The halo, in user units, for the same reason as the font size: a stroke-width given
    // in CSS px inside an svg is user units, so a fixed one is a halo of fixed size on the
    // ground that grows on screen as you zoom in until it swallows the glyphs. Inherited
    // by the labels rather than set on each of them, which is one write instead of 131.
    el.marks.setAttribute("stroke-width", (LABEL_HALO_PX * mpp).toFixed(2));

    // The aid dots need no sizing at all, and working out why was the useful part.
    //
    // They are lines, and #chart line already carries vector-effect: non-scaling-stroke,
    // which makes stroke-width mean screen pixels rather than user units. So a constant
    // stroke-width in the stylesheet is already a constant size on the screen at every
    // zoom, and the elaborate per-view write this used to do was multiplying by the
    // scale a second time: 3.5 by 14.43 metres per pixel came out as fifty screen pixels
    // and the chart disappeared under 680 blobs.
    //
    // What is left here is the gate. Beyond NAVAID_MAX_MPP the whole register is a swarm
    // of dots over the ocean and tells the crew nothing, and one attribute hides the lot.
    if (mpp > NAVAID_MAX_MPP) el.navaids.setAttribute("display", "none");
    else el.navaids.removeAttribute("display");
    for (var i = 0; i < symbols.length; i++) {
      var sym = symbols[i];
      var px = sym.used ? SYMBOL_PX.used : SYMBOL_PX.context;
      sym.circle.setAttribute("r", (px * mpp).toFixed(2));
    }
    // Placement and visibility are layoutLabels()' business, not this loop's: where a
    // label goes depends on where every other label went.
    layoutLabels(targetMarkId());
    // The overlay is sized in pixels too, so a change of scale has to redraw it. Cheap:
    // a dozen nodes against the chart's sixteen thousand coordinate pairs, which is the
    // whole reason the chart is built once and this is not.
    if (lastState) { drawCourse(lastState); drawBoat(lastState); }
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

    // Deepest first so the shallower ones draw over: the bands overlap at their shared
    // edges and shallowest-darkest only reads if the shallow one wins (DESIGN 12).
    //
    // Five classes now, not three, on a 2/5/10 split. foreshore draws last because it is
    // the shallowest thing on the chart: it is not a depth at all but the strip the survey
    // vessel could not float over, which on the Swan is the drying fringe. Its colour is
    // green and comes from the data like the rest.
    var order = { deepest: 0, deep: 1, mid: 2, shallow: 3, foreshore: 4 };
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

  // --- the built edge of the river, and the aid network -------------------------------

  function drawStructures(structures) {
    // Polygons and lines in one document: jetties arrive as both, since OSM maps some
    // piers as areas and some as ways. pathFor handles either, and fill versus stroke is
    // left to the class so a jetty line and a jetty polygon look like the same thing.
    structures.features.forEach(function (f) {
      add(el.structures, "path", {
        d: pathFor(f.geometry),
        class: "structure structure-" + f.properties.kind
      });
    });
  }

  // 785 aids, and they cannot be circles.
  //
  // Every symbol on this page has to hold its size on the screen while the frame is in
  // metres, which for the marks means writing an r to each of them whenever the scale
  // changes. That is 131 writes and it was already worth optimising for the iPad. Adding
  // 785 more would put 916 attribute writes on the zoom path.
  //
  // So an aid is a zero-length line with a round cap, and its size is the layer's
  // stroke-width. stroke-width inherits, so the whole set resizes with one attribute
  // write instead of 785, and a round cap on a zero-length line paints a dot.
  function drawNavaids(navaids) {
    navaids.features.forEach(function (f) {
      // An aid that is also a racing mark is drawn once, and marks.json wins because it
      // carries the rounding and the course data. DESIGN 12 says so explicitly: 105 of
      // these sit within 25 m of a mark, mostly the club-owned yacht buoys, since DoT
      // records the racing buoys too.
      if (f.properties.dup_mark) return;
      var xy = project(f.geometry.coordinates);
      add(el.navaids, "line", {
        x1: xy[0].toFixed(1), y1: xy[1].toFixed(1),
        x2: xy[0].toFixed(1), y2: xy[1].toFixed(1),
        class: "navaid navaid-" + f.properties.kind + (f.properties.lit ? " navaid-lit" : "")
      });
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
      // Every mark gets a label node, including the 111 that no current course visits.
      // Which of them are shown is layoutLabels()' business and changes with the zoom;
      // creating them once is cheaper than making and destroying text nodes on every view
      // change, and they cost nothing while hidden.
      var label = add(g, "text", { x: xy[0], y: xy[1], class: "mark-label" });
      label.textContent = m.name;
      symbols.push({
        circle: circle, label: label, used: used, id: m.id,
        x: xy[0], y: xy[1],
        // The name's length, kept so the label's width can be estimated without asking
        // the browser to measure it. See layoutLabels().
        chars: (m.name || "").length
      });
    });
  }

  // --- the live overlay: the course being sailed, and the boat -------------------------
  //
  // The only two things on this page that move, and the only ones the crew is looking for
  // once the gun has gone. Both come off /api/state, which the race screen already polls
  // at 2 Hz and which carries the position and the race state in one payload (DESIGN 4).
  //
  // Everything here is redrawn from scratch on each poll, unlike the chart, which is built
  // once. That is affordable because it is a handful of nodes rather than sixteen thousand
  // coordinate pairs, and it means there is no state to get out of step with the race.

  var POLL_MS = 500;
  var BOAT_PX = { hull: 9, vector: 34, ring: 9 };
  var courseNow = null;        // the course document, refetched when the id changes
  var courseExtentNow = null;  // its extent, or null when no course is selected
  var markIndexNow = {};
  var linesNow = null;
  var boatShape = null;        // {hull, vector}
  var lastState = null;        // the last /api/state, so a zoom can redraw the overlay

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  // The legs, mark to mark in the order the sheet prints them, starting and finishing at
  // the line. Drawn as separate segments rather than one polyline so the leg being sailed
  // can be picked out: DESIGN 9.2 puts the next mark first in the crew's attention, and
  // this is that on a chart.
  function drawCourse(state) {
    clear(el.course);
    if (!courseNow || !courseNow.legs || !linesNow) return;

    var startMid = midOfLine(linesNow);
    var previous = startMid;
    var legIndex = state && state.race ? state.race.leg : null;

    courseNow.legs.forEach(function (leg, i) {
      var to = leg.mark && markIndexNow[leg.mark];
      var point = to ? project([to.lon, to.lat]) : startMid;   // the finish is the line
      var current = (legIndex !== null && legIndex === i);
      // The leg after this one. Not decoration: it is what decides sail selection and
      // which way to round before the crew gets there, which is why DESIGN 9.2 already
      // gives it a place in the secondary row with its transit angle and leg type. On the
      // last leg there is no next, and nothing is marked.
      var next = (legIndex !== null && legIndex + 1 === i);
      add(el.course, "line", {
        x1: previous[0].toFixed(1), y1: previous[1].toFixed(1),
        x2: point[0].toFixed(1), y2: point[1].toFixed(1),
        class: "leg-line" + (current ? " leg-now" : (next ? " leg-next" : ""))
      });
      if (current && to) {
        // A ring round the mark being sailed to. Sized in pixels like every other symbol
        // on this page, so it stays an annotation rather than becoming a circle on the
        // ground.
        add(el.course, "circle", {
          cx: point[0].toFixed(1), cy: point[1].toFixed(1),
          r: (BOAT_PX.ring * metresPerPixel()).toFixed(1),
          class: "target-ring"
        });
      }
      previous = point;
    });
  }

  function midOfLine(lines) {
    var a = project([lines.start_finish.inner.lon, lines.start_finish.inner.lat]);
    var b = project([lines.start_finish.outer.lon, lines.start_finish.outer.lat]);
    return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  }

  function drawBoat(state) {
    var fix = state && state.position;
    // Hidden outright past the 5 s cutoff, not dimmed. A dimmed boat still reads as a
    // boat, and it would be a boat somewhere it is not (DESIGN 9.5). The server has
    // already applied the cutoff, so this is one flag rather than a second opinion.
    if (!fix || !fix.v || fix.stale) {
      el.boat.setAttribute("hidden", "hidden");
      return;
    }
    el.boat.removeAttribute("hidden");

    var at = project([fix.v.lon, fix.v.lat]);
    var mpp = metresPerPixel();
    // Course over ground, because that is where the boat is going, and it is what the HUD
    // shows beside a bearing for the same reason (DESIGN 9.10). Heading is the fallback
    // for a boat that is stopped, where COG is noise.
    var fields = state.fields || {};
    var course = fields.cog && typeof fields.cog.v === "number" ? fields.cog.v
               : (fields.hdg && typeof fields.hdg.v === "number" ? fields.hdg.v : null);

    if (!boatShape) {
      boatShape = {
        vector: add(el.boat, "line", { class: "boat-vector" }),
        hull: add(el.boat, "path", { class: "boat" })
      };
    }

    // A triangle pointing along the course, sized in pixels. Drawn from the heading rather
    // than rotated by a transform, so there is no second coordinate system to reason about
    // and no dependence on transform-box or vector-effect behaviour on an old Safari.
    var heading = course === null ? 0 : course;
    var rad = heading * Math.PI / 180.0;
    var size = BOAT_PX.hull * mpp;
    // Screen space: x is east, y is south, and a bearing is clockwise from north.
    var ahead = [Math.sin(rad), -Math.cos(rad)];
    var side = [-ahead[1], ahead[0]];
    var nose = [at[0] + ahead[0] * size, at[1] + ahead[1] * size];
    var portQ = [at[0] - ahead[0] * size * 0.7 + side[0] * size * 0.6,
                 at[1] - ahead[1] * size * 0.7 + side[1] * size * 0.6];
    var stbdQ = [at[0] - ahead[0] * size * 0.7 - side[0] * size * 0.6,
                 at[1] - ahead[1] * size * 0.7 - side[1] * size * 0.6];
    boatShape.hull.setAttribute("d",
      "M" + nose[0].toFixed(1) + " " + nose[1].toFixed(1) +
      "L" + portQ[0].toFixed(1) + " " + portQ[1].toFixed(1) +
      "L" + stbdQ[0].toFixed(1) + " " + stbdQ[1].toFixed(1) + "Z");

    if (course === null) {
      boatShape.vector.setAttribute("x1", at[0]);
      boatShape.vector.setAttribute("y1", at[1]);
      boatShape.vector.setAttribute("x2", at[0]);
      boatShape.vector.setAttribute("y2", at[1]);
    } else {
      var reach = BOAT_PX.vector * mpp;
      boatShape.vector.setAttribute("x1", at[0].toFixed(1));
      boatShape.vector.setAttribute("y1", at[1].toFixed(1));
      boatShape.vector.setAttribute("x2", (at[0] + ahead[0] * reach).toFixed(1));
      boatShape.vector.setAttribute("y2", (at[1] + ahead[1] * reach).toFixed(1));
    }
  }

  // --- the four readings under the chart -----------------------------------------------
  //
  // The strip DESIGN 12.2 settled, in the space the caveat used to take. Which four
  // readings depends on what the boat is doing, because a map is the screen the crew is
  // looking at when they are not looking at the other two, and the reason to leave it was
  // always one number.
  //
  // The three sets, and the order they are tested in: racing first, so motoring inside a
  // race still shows the race. That order is the crew's, not a guess.
  var STALE_S = 15;            // instruments dim past this, as app.js and hud.html
  var NM_ABOVE_M = 500;        // metres below, nautical miles above (DESIGN 9.4)
  var METRES_TO_NM = 1 / 1852;
  var BLANK = "---";

  var READOUTS = {
    // Racing: where the mark is and how the wind sits, which is the whole of steering a
    // leg. Distance and off-the-bow come from the race engine and are blank without a
    // fix, exactly as they are on the other two screens (DESIGN 9.5).
    racing: [
      { key: "dist", label: "distance" },
      { key: "rel",  label: "off the bow", unit: "deg" },
      { key: "twa",  label: "TWA", unit: "deg" },
      { key: "tws",  label: "TWS", unit: "kt" }
    ],
    // Motoring: the four SevCon readings, in the HUD's order and its colours.
    motor: [
      { key: "rpm",  label: "RPM" },
      { key: "cur",  label: "current", unit: "A" },
      { key: "mot",  label: "motor", unit: "\u00b0C" },
      { key: "ctrl", label: "controller", unit: "\u00b0C" }
    ],
    // Anything else: sailing, but not racing. COG rather than a bearing, because outside a
    // race there is no mark to take one to and the boat's own course is the only bearing
    // there is; it is labelled COG for that reason and not BRG.
    idle: [
      { key: "sog", label: "SOG", unit: "kt" },
      { key: "cog", label: "COG", unit: "deg" },
      { key: "twa", label: "TWA", unit: "deg" },
      { key: "tws", label: "TWS", unit: "kt" }
    ]
  };

  function whichSet(state) {
    if (!state) return "idle";
    if (state.race && state.race.mode === "racing") return "racing";
    if (state.motor) return "motor";
    return "idle";
  }

  function fixed1(v) { return v.toFixed(1); }
  function whole(v)  { return String(Math.round(v)); }

  // Signed, port negative, as every other relative angle in this app (DESIGN 9.3).
  function signed(v) {
    var n = Math.round(v);
    return (n > 0 ? "+" : "") + n;
  }

  function degrees(v) {
    return ("00" + (((Math.round(v) % 360) + 360) % 360)).slice(-3);
  }

  var FORMAT = { sog: fixed1, tws: fixed1, cur: fixed1,
                 twa: signed, rel: signed, cog: degrees,
                 rpm: whole, mot: whole, ctrl: whole };

  // One reading: its text, its unit if that can change, and whether it is old enough to
  // dim. Blank rather than dim when the number cannot be known at all, since a dimmed
  // number still reads as a number in spray (DESIGN 9.5).
  function reading(state, key) {
    var nav = state && state.race ? state.race.nav : null;
    if (key === "dist") {
      if (!nav || nav.distance_m === null || nav.distance_m === undefined) {
        return { text: BLANK, unit: "m" };
      }
      return nav.distance_m < NM_ABOVE_M
        ? { text: whole(nav.distance_m), unit: "m" }
        : { text: (nav.distance_m * METRES_TO_NM).toFixed(2), unit: "nm" };
    }
    if (key === "rel") {
      if (!nav || nav.relative === null || nav.relative === undefined) {
        return { text: BLANK };
      }
      return { text: signed(nav.relative) };
    }
    var f = state && state.fields ? state.fields[key] : null;
    if (!f || typeof f.v !== "number") return { text: BLANK };
    return { text: (FORMAT[key] || whole)(f.v), stale: f.age > STALE_S };
  }

  var readoutSet = null;

  function renderReadout(state) {
    if (!cells.length) return;
    var name = whichSet(state);
    var spec = READOUTS[name];

    // The labels and units are only rewritten when the set itself changes. They are
    // constant within a set, and this runs twice a second.
    var changed = name !== readoutSet;
    readoutSet = name;

    for (var i = 0; i < cells.length; i++) {
      var c = cells[i];
      var s = spec[i];
      if (!s) { c.cell.style.display = "none"; continue; }
      if (changed) {
        c.cell.setAttribute("data-key", s.key);
        c.lbl.textContent = s.label;
        c.unit.textContent = s.unit || "";
      }
      var r = reading(state, s.key);
      c.val.textContent = r.text;
      // Only the distance switches its own unit, and only that cell is told to.
      if (r.unit !== undefined) c.unit.textContent = r.unit;
      c.val.classList.toggle("stale", !!r.stale);
    }
  }

  function onState(state) {
    var id = state && state.race ? state.race.course : null;
    var have = courseNow ? courseNow.id : null;
    if (id !== have) {
      // The crew has chosen a different course, or abandoned one. Refetch it and refit the
      // view: a course change is a deliberate act that just happened, so following it is
      // what the crew expects, the same principle DESIGN 9.6 applies to a mode change on
      // the race screen. Only when the view is on the inner level and has not been dragged
      // somewhere by hand, because refitting under a hand that just panned is the one
      // thing this page must never do.
      if (!id) {
        courseNow = null;
        courseExtentNow = null;
        if (level === 0 && !moved) showLevel(0);
        drawCourse(state);
        return;
      }
      fetch(base + "/api/course/" + encodeURIComponent(id), { cache: "no-store" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (course) {
          courseNow = course;
          courseExtentNow = courseExtent(course, markIndexNow, linesNow);
          if (level === 0 && !moved) showLevel(0);
          drawCourse(state);
        })
        .catch(function () { /* the chart is still a chart without a course on it */ });
      return;
    }
    drawCourse(state);
  }

  function poll() {
    fetch(base + "/api/state", { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (state) {
        if (!state) return;
        lastState = state;
        onState(state);
        drawBoat(state);
        renderReadout(state);
      })
      .catch(function () { /* a dropout self-heals on the next poll (DESIGN 2) */ });
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
    // The readings are worth nothing if the chart is not there, so the message takes the
    // whole strip. It used to be written over the caveat line, which is where the strip is.
    if (el.readout) {
      el.readout.textContent = "Map data did not load: " + message;
      el.readout.className = "failed";
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
               fetchJson("coast"), fetchJson("depth"),
               fetchJson("structures"), fetchJson("navaids"), fetchCourse()])
    .then(function (all) {
      var lines = all[0], marks = all[1], coast = all[2], depth = all[3];
      var structures = all[4], navaids = all[5];
      var course = all[6];

      // The origin has to be set before anything is projected, and everything below
      // depends on it, which is why it is the first thing this function does.
      origin = { lat: lines.start_finish.inner.lat, lon: lines.start_finish.inner.lon };

      var markIndex = {};
      marks.marks.forEach(function (m) { markIndex[m.id] = m; });

      drawDepth(depth);
      drawCoast(coast);
      drawStructures(structures);
      drawNavaids(navaids);
      drawLines(lines, markIndex);
      drawMarks(marks);

      // The three named extents, outermost last (DESIGN 12.2). Index 0 is a placeholder:
      // showLevel recomputes it every time it is selected, because with no course it is a
      // region around the boat and the boat moves.
      //
      // "River" is marks.json's bbox, 10.3 by 7.9 km, which is every mark the club races
      // to and so is the working stretch of the Swan whatever the chart calls it.
      // "Everything" is coast.json's, 57 by 51 km, deliberately generated far wider for
      // the ocean races and the island anchorages.
      var river = extentOf(marks.bbox);

      // What the poll needs, kept where it can reach it. The chart is built once and the
      // overlay redrawn on every poll, so these are the only pieces of the load that
      // outlive it.
      courseNow = course;
      markIndexNow = markIndex;
      linesNow = lines;
      courseExtentNow = courseExtent(course, markIndex, lines);

      levels = [courseExtentNow || river, river, extentOf(coast.bbox)];

      bindGestures();
      if (el.zoom) el.zoom.addEventListener("click", cycleZoom);
      showLevel(0);
      renderReadout(null);

      // The overlay, and then the poll that keeps it current. Drawn once immediately so
      // the course is on the chart before the first poll returns.
      drawCourse(null);
      poll();
      setInterval(poll, POLL_MS);

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
