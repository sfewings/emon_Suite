// table: rows of a name, its pills and its figures, under column headings (DESIGN 6.2).
//
//   "table": {
//     "columns": ["Now", "Today", "Cost"],
//     "rows": [
//       {"label": "Car",
//        "leds": [{"feed": "derived/car/charging", "on": "charging", "off": "idle"}],
//        "cells": ["{Power board / Car|0} W", "{derived/car/today|0} Wh",
//                  "${derived/car/cost/today|2}"]}
//     ]
//   }
//
// A cell is a template, as a "lines" line is: its numbers at a reading's size, its words
// and units small and grey (ui.templateInto). A row's pills are the "leds" part's, in
// the row rather than the heading (ui.pillsInto), so a tile of appliances can say which
// is running beside each one's figures (owner, shannstainable, 21 Nov 2026).

(function () {
  "use strict";

  EmonUI.part("table", function (spec, body, tile, ui) {
    var columns = spec.columns || [];
    var table = ui.el("table", "tbl");
    if (columns.length) {
      var hr = ui.el("tr");
      hr.appendChild(ui.el("th", null, ""));
      columns.forEach(function (c) { hr.appendChild(ui.el("th", null, c)); });
      table.appendChild(hr);
    }
    var feeds = [];
    var updates = [];
    (spec.rows || []).forEach(function (row) {
      var tr = ui.el("tr");
      var name = ui.el("td", "tn");
      name.appendChild(ui.el("span", "k", row.label || ""));
      var leds = row.leds || [];
      if (leds.length) {
        var pills = ui.el("span", "tp");
        name.appendChild(pills);
        updates.push(ui.pillsInto(pills, leds, tile));
        leds.forEach(function (l) { if (l.feed) feeds.push(l.feed); });
      }
      tr.appendChild(name);
      (row.cells || []).forEach(function (text) {
        var td = ui.el("td", "sub");
        updates.push(ui.templateInto(td, text));
        feeds = feeds.concat(ui.templateFeeds(text));
        tr.appendChild(td);
      });
      table.appendChild(tr);
    });
    body.appendChild(table);

    return {
      feeds: feeds,
      update: function (view) {
        updates.forEach(function (u) { u(view); });
      }
    };
  });
}());
