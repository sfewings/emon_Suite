// cell-bar: one bar per cell of a battery, lowest and highest marked (DESIGN 6.2, PLAN 3).
//
//   "cell-bar": {"min": 3.0, "max": 3.65, "spread": 0.05, "decimals": 3,
//                "cells": [{"feed": "Main Battery / cellVoltage 0", "label": "1"}, ...]}
//
// Each bar fills from min to max. Beneath, the lowest and highest cells and the spread
// between them; past "spread" the two ends and the line turn the warning colour, which is
// what a cell drifting out of balance looks like. A cell's label defaults to its place in
// the list, counting from 1. "tint_low" and "tint_high" colour the lowest and highest
// readings in the line beneath (Node-RED's battery page had them cyan and red). Cells
// are listed one by one so that every feed is named in the page, where the server and
// the linter look for them (DESIGN 4.4, 9.4).

(function () {
  "use strict";

  EmonUI.part("cell-bar", function (spec, body, tile, ui) {
    var cells = spec.cells || [];
    var min = typeof spec.min === "number" ? spec.min : 0;
    var max = typeof spec.max === "number" && spec.max > min ? spec.max : min + 1;
    var limit = typeof spec.spread === "number" ? spec.spread : null;

    var row = ui.el("div", "cells");
    var bars = cells.map(function (c, i) {
      var cell = ui.el("div", "cell");
      var bar = ui.el("div", "cbar");
      var fill = ui.el("i");
      bar.appendChild(fill);
      cell.appendChild(bar);
      cell.appendChild(ui.el("div", "cl", c.label !== undefined ? String(c.label) : String(i + 1)));
      row.appendChild(cell);
      return { spec: c, el: cell, fill: fill, label: c.label !== undefined ? String(c.label) : String(i + 1) };
    });
    body.appendChild(row);
    var line = ui.el("div", "sub line");
    body.appendChild(line);

    // A spread in V reads better in mV: "Δ 91 mV".
    function spreadText(d, u) {
      if (u === "V") return ui.fmt(d * 1000, 0) + " mV";
      return ui.fmt(d, spec.decimals) + (u ? " " + u : "");
    }

    return {
      feeds: cells.map(function (c) { return c.feed; }).filter(Boolean),
      update: function (view) {
        var lo = null, hi = null, u = "";
        bars.forEach(function (b) {
          var v = view.value(b.spec.feed);
          b.v = typeof v === "number" ? v : null;
          var pct = b.v === null ? 0 : (b.v - min) / (max - min) * 100;
          b.fill.style.height = Math.max(0, Math.min(100, pct)).toFixed(1) + "%";
          if (b.v === null) return;
          u = u || view.unit(b.spec.feed);
          if (lo === null || b.v < lo.v) lo = b;
          if (hi === null || b.v > hi.v) hi = b;
        });
        var wide = lo !== null && limit !== null && hi.v - lo.v > limit;
        bars.forEach(function (b) {
          b.el.className = "cell" + (b.v === null ? " none" : "") +
            (b === lo ? " lo" : b === hi ? " hi" : "") + (wide && (b === lo || b === hi) ? " warn" : "");
        });
        line.className = "sub line" + (wide ? " warn" : "");
        line.innerHTML = "";
        if (lo === null) {
          line.textContent = ui.fmt(null);
          return;
        }
        line.appendChild(document.createTextNode("low "));
        line.appendChild(ui.el("span", spec.tint_low ? "r-" + spec.tint_low : "", ui.fmt(lo.v, spec.decimals)));
        line.appendChild(document.createTextNode(" (" + lo.label + ") · high "));
        line.appendChild(ui.el("span", spec.tint_high ? "r-" + spec.tint_high : "", ui.fmt(hi.v, spec.decimals)));
        line.appendChild(document.createTextNode(" (" + hi.label + ") · Δ " + spreadText(hi.v - lo.v, u)));
      }
    };
  });
}());
