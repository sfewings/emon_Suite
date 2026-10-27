// dial: a round gauge, as on the boat's Node-RED Dials page (DESIGN 6.2, PLAN 3).
//
//   "dial": {"feed": "SevCon / motorTemperature", "min": 0, "max": 100,
//            "warn": 50, "bad": 75, "decimals": 0, "label": "Motor", "tint": "mot"}
//
// "tint" colours the number as the reading is coloured elsewhere (emon-ui.css).
// A list of dials sits side by side in one tile. The arc fills from 0, or from min when 0
// is off the scale, to the value, so a reversing rpm or a regenerating current fills the
// other way. "warn" and "bad" colour the arc once the value is past them: upwards when
// warn is below bad (a temperature), downwards when warn is above bad (a battery
// voltage). With only one of them given, upwards. The bands are marked on the scale.
//
// The SVG has width and height attributes as well as a viewBox, and sits in a box that
// keeps its shape by padding: iOS 12 sizes an SVG with only a viewBox at 300 px wide, and
// does not keep its aspect ratio from height: auto (enchantee_racing/CLAUDE.md).

(function () {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";
  var W = 120, H = 96, CX = 60, CY = 58, R = 46, SWEEP = 120;   // degrees each side of up

  function svgEl(tag, attrs, parent) {
    var e = document.createElementNS(NS, tag);
    Object.keys(attrs).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (parent) parent.appendChild(e);
    return e;
  }

  function point(a, r) {
    var rad = a * Math.PI / 180;
    return [CX + r * Math.sin(rad), CY - r * Math.cos(rad)];
  }

  // An arc from angle a0 to a1, clockwise from straight up, in degrees.
  function arc(a0, a1, r) {
    if (a1 < a0) { var t = a0; a0 = a1; a1 = t; }
    if (a1 - a0 < 0.01) return "";
    var p0 = point(a0, r), p1 = point(a1, r);
    return "M" + p0[0].toFixed(2) + " " + p0[1].toFixed(2) +
      " A" + r + " " + r + " 0 " + (a1 - a0 > 180 ? 1 : 0) + " 1 " +
      p1[0].toFixed(2) + " " + p1[1].toFixed(2);
  }

  function makeDial(spec, row, ui) {
    var min = typeof spec.min === "number" ? spec.min : 0;
    var max = typeof spec.max === "number" && spec.max > min ? spec.max : min + 100;
    var warn = typeof spec.warn === "number" ? spec.warn : null;
    var bad = typeof spec.bad === "number" ? spec.bad : null;
    var low = warn !== null && bad !== null && warn > bad;   // the bad end is the bottom

    function angle(v) {
      var f = (Math.max(min, Math.min(max, v)) - min) / (max - min);
      return -SWEEP + f * 2 * SWEEP;
    }
    function state(v) {
      if (low) return v <= bad ? "bad" : v <= warn ? "warn" : "";
      if (bad !== null && v >= bad) return "bad";
      return warn !== null && v >= warn ? "warn" : "";
    }

    var cell = ui.el("div", "dial");
    var box = ui.el("div", "dial-box");
    var svg = svgEl("svg", { viewBox: "0 0 " + W + " " + H, width: String(W), height: String(H) });
    svgEl("path", { "class": "track", d: arc(-SWEEP, SWEEP, R) }, svg);
    // The bands, just outside the track.
    var top = low ? min : max;
    if (warn !== null) {
      svgEl("path", { "class": "band warn", d: arc(angle(warn), angle(bad !== null ? bad : top), R + 7) }, svg);
    }
    if (bad !== null) svgEl("path", { "class": "band bad", d: arc(angle(bad), angle(top), R + 7) }, svg);
    var fill = svgEl("path", { "class": "fill", d: "" }, svg);
    var lo = point(-SWEEP, R), hi = point(SWEEP, R);
    svgEl("text", { "class": "end", x: lo[0].toFixed(1), y: (lo[1] + 13).toFixed(1) }, svg).textContent = ui.fmt(min);
    svgEl("text", { "class": "end", x: hi[0].toFixed(1), y: (hi[1] + 13).toFixed(1) }, svg).textContent = ui.fmt(max);
    var value = svgEl("text", { "class": "val" + (spec.tint ? " r-" + spec.tint : ""), x: String(CX), y: String(CY + 6) }, svg);
    var units = svgEl("text", { "class": "unit", x: String(CX), y: String(CY + 20) }, svg);
    box.appendChild(svg);
    cell.appendChild(box);
    if (spec.label) cell.appendChild(ui.el("div", "k", spec.label));
    row.appendChild(cell);

    var origin = angle(Math.max(min, Math.min(max, 0)));
    return function (view) {
      var v = view.value(spec.feed);
      if (typeof v !== "number") {
        fill.setAttribute("d", "");
        value.textContent = ui.fmt(null);
        units.textContent = "";
        return;
      }
      fill.setAttribute("d", arc(origin, angle(v), R));
      fill.setAttribute("class", "fill " + state(v));
      value.textContent = ui.fmt(v, spec.decimals);
      units.textContent = spec.unit !== undefined ? spec.unit : view.unit(spec.feed);
    };
  }

  EmonUI.part("dial", function (spec, body, tile, ui) {
    var list = Array.isArray(spec) ? spec : [spec];
    var row = ui.el("div", "dials");
    body.appendChild(row);
    var updates = list.map(function (d) { return makeDial(d, row, ui); });
    return {
      feeds: list.map(function (d) { return d.feed; }).filter(Boolean),
      update: function (view) { updates.forEach(function (u) { u(view); }); }
    };
  });
}());
