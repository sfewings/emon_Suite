// compass: bearings on a rose, or angles off the bow (DESIGN 6.2, PLAN 3).
//
//   "compass": {"needles": [{"feed": "True wind / windDirection", "label": "TWD"},
//                           {"feed": "Enchantee-GPS / course", "label": "COG"}]}
//   "compass": {"relative": true,
//               "needles": [{"feed": "Boat reference wind / windDirection", "label": "AWA"}]}
//
// The first needle is the one read: solid, in the tile's hue, its value in the middle.
// Others are outlines. A needle's "tint" (emon-ui.css, reading colours) colours it solid,
// with its legend value, and the middle number when it is the first: TWD orange, COG
// light yellow, as on the race app's dial. A bearing reads as three digits with its sixteen-point name
// beneath ("245", "WSW"). "relative": the rose is the boat, bow up, and an angle reads
// signed, port negative, with the race app's red and green sectors from 30 to 60 degrees
// either side (enchantee_racing/engine/nav.py; static/gar.js). A needle whose feed is
// past the tile's "gone" is hidden rather than left pointing at an old value.
//
// The SVG has width and height attributes as well as a viewBox, in a box that keeps its
// shape by padding, for iOS 12 (see dial.js).

(function () {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";
  var S = 120, C = 60, R = 52;
  var POINTS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];

  function svgEl(tag, attrs, parent) {
    var e = document.createElementNS(NS, tag);
    Object.keys(attrs).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (parent) parent.appendChild(e);
    return e;
  }

  function point(a, r) {
    var rad = a * Math.PI / 180;
    return [C + r * Math.sin(rad), C - r * Math.cos(rad)];
  }

  function xy(p) { return p[0].toFixed(2) + " " + p[1].toFixed(2); }

  function sector(a0, a1, r0, r1) {
    return "M" + xy(point(a0, r0)) + " L" + xy(point(a0, r1)) +
      " A" + r1 + " " + r1 + " 0 0 1 " + xy(point(a1, r1)) +
      " L" + xy(point(a1, r0)) + " A" + r0 + " " + r0 + " 0 0 0 " + xy(point(a0, r0)) + "Z";
  }

  function norm360(a) { return ((a % 360) + 360) % 360; }
  function norm180(a) { return norm360(a + 180) - 180; }
  function three(a) { return ("00" + Math.round(norm360(a)) % 360).slice(-3); }
  function pointName(a) { return POINTS[Math.floor((norm360(a) + 11.25) / 22.5) % 16]; }

  EmonUI.part("compass", function (spec, body, tile, ui) {
    var relative = !!spec.relative;
    var needles = spec.needles || (spec.feed ? [{ feed: spec.feed, label: spec.label }] : []);

    var wrap = ui.el("div", "compass");
    // The width limit is on a box of its own: the padding that sets the rose's height is
    // a share of its parent's width, not of the rose's own.
    var size = ui.el("div", "compass-size");
    var box = ui.el("div", "compass-box");
    var svg = svgEl("svg", { viewBox: "0 0 " + S + " " + S, width: String(S), height: String(S) });
    if (relative) {
      svgEl("path", { "class": "port", d: sector(-60, -30, R - 9, R) }, svg);
      svgEl("path", { "class": "stbd", d: sector(30, 60, R - 9, R) }, svg);
    }
    svgEl("circle", { "class": "ring", cx: String(C), cy: String(C), r: String(R) }, svg);
    for (var a = 0; a < 360; a += 10) {
      var major = a % 30 === 0;
      var outer = point(a, R), inner = point(a, R - (major ? 7 : 4));
      svgEl("line", {
        "class": major ? "tick major" : "tick",
        x1: outer[0].toFixed(2), y1: outer[1].toFixed(2),
        x2: inner[0].toFixed(2), y2: inner[1].toFixed(2)
      }, svg);
    }
    var marks = relative ? [[0, "0"], [90, "90"], [180, "180"], [270, "90"]]
                         : [[0, "N"], [90, "E"], [180, "S"], [270, "W"]];
    marks.forEach(function (m) {
      var p = point(m[0], R - 14);
      svgEl("text", { "class": "mark", x: p[0].toFixed(1), y: (p[1] + 3.5).toFixed(1) }, svg).textContent = m[1];
    });

    var drawn = needles.map(function (n, i) {
      var g = svgEl("g", { "class": (i === 0 ? "needle main" : "needle") + (n.tint ? " r-" + n.tint : "") }, svg);
      svgEl("polygon", { points: i === 0 ? "60,9 65,22 55,22" : "60,24 64,33 56,33" }, g);
      if (i === 0) svgEl("line", { x1: "60", y1: "22", x2: "60", y2: "34" }, g);
      return g;
    });
    var first0 = needles[0] || {};
    var value = svgEl("text", { "class": "val" + (first0.tint ? " r-" + first0.tint : ""), x: String(C), y: String(C + 6) }, svg);
    var sub = svgEl("text", { "class": "unit", x: String(C), y: String(C + 19) }, svg);
    box.appendChild(svg);
    size.appendChild(box);
    wrap.appendChild(size);

    // The legend: every needle's label and value, the first in the tile's hue.
    var legend = ui.el("div", "kv c" + Math.max(1, Math.min(4, needles.length)));
    var cells = needles.map(function (n, i) {
      var cell = ui.el("div");
      cell.appendChild(ui.el("div", "k", n.label || ""));
      var v = ui.el("div", "v" + (n.tint ? " r-" + n.tint : i === 0 ? " t-main" : ""));
      cell.appendChild(v);
      legend.appendChild(cell);
      return v;
    });
    if (needles.length > 1 || (needles[0] && needles[0].label)) wrap.appendChild(legend);
    body.appendChild(wrap);

    function reading(v) {
      if (typeof v !== "number") return ui.fmt(null);
      if (!relative) return three(v) + "°";
      var r = Math.round(norm180(v));
      return (r < 0 ? "−" + -r : String(r)) + "°";
    }

    return {
      feeds: needles.map(function (n) { return n.feed; }).filter(Boolean),
      update: function (view) {
        needles.forEach(function (n, i) {
          var v = view.value(n.feed);
          var on = typeof v === "number";
          drawn[i].style.display = on ? "" : "none";
          if (on) drawn[i].setAttribute("transform", "rotate(" + norm360(v).toFixed(1) + " " + C + " " + C + ")");
          cells[i].textContent = reading(v);
        });
        var first = needles.length ? view.value(needles[0].feed) : null;
        value.textContent = reading(first);
        sub.textContent = typeof first !== "number" ? "" :
          relative ? (Math.round(norm180(first)) < 0 ? "port" : Math.round(norm180(first)) > 0 ? "stbd" : "")
                   : pointName(first);
      }
    };
  });
}());
