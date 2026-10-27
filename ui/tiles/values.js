// values: a grid of readings (DESIGN 6.2).
//
//   "values": [ {"feed": "Power board / Consumed", "label": "Consuming", "big": true,
//                "decimals": 0, "unit": "W", "domain": "solar",
//                "sub": "{derived/consumed/today|0} Wh today"} ],
//   "cols": 4
//
// "tint" colours the number as that reading is coloured on every boat screen ("sog", "twa",
// "rpm" and the rest: emon-ui.css, reading colours); it wins over "domain".
// "unit" overrides the feed's own; "" hides it. "format": "time" shows a time in seconds
// since the epoch as "Today 18:54", in place of decimals. "domain" colours the number
// with another domain's hue (Producing, on the Power tile). "sub" is a template line
// beneath.

(function () {
  "use strict";

  EmonUI.part("values", function (list, body, tile, ui) {
    var cols = Math.max(1, Math.min(4, tile.spec.cols || list.length || 1));
    var grid = ui.el("div", "kv c" + cols);
    var feeds = [];
    var cells = list.map(function (item) {
      var cell = ui.el("div");
      if (item.label) cell.appendChild(ui.el("div", "k", item.label));
      var v = ui.el("div", "v" + (item.big ? " big" : "") +
        (item.tint ? " r-" + item.tint : item.domain ? " t-" + item.domain : ""));
      var num = ui.el("span");
      var small = ui.el("small");
      v.appendChild(num);
      v.appendChild(small);
      cell.appendChild(v);
      var sub = null;
      if (item.sub) {
        sub = ui.el("div", "sub");
        cell.appendChild(sub);
        feeds = feeds.concat(ui.templateFeeds(item.sub));
      }
      if (item.feed) feeds.push(item.feed);
      grid.appendChild(cell);
      return { item: item, num: num, small: small, sub: sub };
    });
    body.appendChild(grid);

    return {
      feeds: feeds,
      update: function (view) {
        cells.forEach(function (c) {
          var value = c.item.feed ? view.value(c.item.feed) : null;
          var time = c.item.format === "time";
          // An item with no feed of its own is a label and its "sub" line, no number.
          c.num.textContent = c.item.feed ? ui.fmtAs(value, time ? "time" : c.item.decimals) : "";
          var u = time ? "" : c.item.unit !== undefined ? c.item.unit : (c.item.feed ? view.unit(c.item.feed) : "");
          c.small.textContent = value === null ? "" : u;
          if (c.sub) c.sub.textContent = view.fill(c.item.sub);
        });
      }
    };
  });
}());
