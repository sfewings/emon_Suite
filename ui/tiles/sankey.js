// sankey: where the energy came from, and where it went (DESIGN 6.2, 6.5).
//
//   "sankey": {"periods": ["now", "today", "yesterday", "week", "month"],
//              "default": "today", "height": 260}
//
// Sources on the left, the house in the middle, loads on the right, each ribbon as wide
// as its share. The flows themselves are not in the page: they are the site's derived.yml
// `sankey:` block, served by /api/energy, so one description answers every period and the
// page says only how to show it (energy.py).
//
// "now" is live, in W, and costs the server nothing. The other periods are Influx
// queries behind a cache, so this asks for them a minute at a time, not every poll.
// Loads that nothing measures arrive as one "Other" ribbon, the remainder, so the
// diagram always balances; a figure the server could only estimate is marked "≈".
//
// SVG in a fixed viewBox scaled to the tile: iOS 12 has no ResizeObserver, and the boat
// reads the same page on a phone, an iPad and a kiosk.

(function () {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";
  var W = 400;                 // viewBox width; the height is the tile's "height"
  var PAD = 8;                 // top and bottom margin, in viewBox units
  var GAP = 7;                 // between two nodes in the same column
  var BAR = 9;                 // width of a node's bar
  var HUB = 12;                // width of the house bar
  var LEFT = 92;               // x of the left column's bars
  var RIGHT = W - 92 - BAR;
  var MIN_BAND = 1.2;          // a flow too small to see still gets a hairline
  var REFRESH_MS = { now: 5000 };
  var REFRESH_OTHER_MS = 60000;

  EmonUI.part("sankey", function (spec, body, tile, ui) {
    var periods = spec.periods && spec.periods.length
      ? spec.periods : ["now", "today", "yesterday", "week", "month"];
    var period = periods.indexOf(spec.default) === -1 ? periods[0] : spec.default;
    var height = typeof spec.height === "number" ? spec.height : 260;
    var doc = null;
    var error = null;
    var pending = false;
    var fetched = 0;

    var tabs = ui.el("div", "sk-tabs");
    var buttons = periods.map(function (p) {
      var b = ui.el("button", "sk-tab", labelOf(p));
      b.type = "button";
      b.onclick = function () {
        if (period === p) return;
        period = p;
        doc = null;
        error = null;
        fetched = 0;
        mark();
        load();
      };
      tabs.appendChild(b);
      return { p: p, el: b };
    });
    body.appendChild(tabs);

    // width and height as attributes, not CSS alone: iOS 12 lays an SVG that has only a
    // viewBox out at 300 px wide (test_ui.test_every_svg_gets_a_width_and_height).
    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("class", "sankey");
    svg.setAttribute("viewBox", "0 0 " + W + " " + height);
    svg.setAttribute("width", String(W));
    svg.setAttribute("height", String(height));
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    body.appendChild(svg);

    var note = ui.el("div", "sub line sk-note");
    body.appendChild(note);

    function labelOf(p) {
      return { now: "Now", today: "Today", yesterday: "Yesterday",
               week: "7 days", month: "30 days" }[p] || p;
    }

    function mark() {
      buttons.forEach(function (b) {
        b.el.className = "sk-tab" + (b.p === period ? " on" : "");
      });
    }
    mark();

    function load() {
      // A tile on a page the reader has left keeps its timer; it must not keep asking.
      if (pending || !document.body.contains(svg)) return;
      pending = true;
      var asked = period;
      ui.getJSON(ui.base + "/api/energy?period=" + encodeURIComponent(period))
        .then(function (d) {
          pending = false;
          if (asked !== period) return;     // the reader moved on while it was in flight
          doc = d;
          error = null;
          fetched = Date.now();
          draw();
        })
        .catch(function (ex) {
          pending = false;
          if (asked !== period) return;
          error = String(ex && ex.message ? ex.message : ex);
          fetched = Date.now();
          draw();
        });
    }

    // --- drawing ------------------------------------------------------------------------

    function svgEl(tag, attrs, text) {
      var e = document.createElementNS(NS, tag);
      for (var k in attrs) {
        if (attrs.hasOwnProperty(k)) e.setAttribute(k, String(attrs[k]));
      }
      if (text !== undefined) e.textContent = text;
      return e;
    }

    // A band between two vertical spans, the curve easing from one column to the other.
    function ribbon(x0, y0a, y0b, x1, y1a, y1b) {
      var cx = (x0 + x1) / 2;
      return "M" + x0 + "," + y0a +
        "C" + cx + "," + y0a + " " + cx + "," + y1a + " " + x1 + "," + y1a +
        "L" + x1 + "," + y1b +
        "C" + cx + "," + y1b + " " + cx + "," + y0b + " " + x0 + "," + y0b + "Z";
    }

    // Wh reads better in kWh once a period is long enough; W stays W.
    function scaleOf(unit, biggest) {
      if (unit === "Wh" && biggest >= 10000) return { div: 1000, unit: "kWh", decimals: 1 };
      return { div: 1, unit: unit, decimals: 0 };
    }

    function draw() {
      while (svg.firstChild) svg.removeChild(svg.firstChild);
      note.className = "sub line sk-note";
      if (error !== null) {
        svg.appendChild(svgEl("text", { x: W / 2, y: height / 2, "class": "sk-empty",
                                        "text-anchor": "middle" }, "no energy data"));
        note.textContent = error;
        note.className = "sub line sk-note bad";
        return;
      }
      if (doc === null) {
        svg.appendChild(svgEl("text", { x: W / 2, y: height / 2, "class": "sk-empty",
                                        "text-anchor": "middle" }, "loading"));
        return;
      }

      var sources = doc.flows.filter(function (f) { return f.side === "source" && f.value > 0; });
      var loads = doc.flows.filter(function (f) { return f.side === "load" && f.value > 0; });
      var total = sources.reduce(function (a, f) { return a + f.value; }, 0);
      var loadTotal = loads.reduce(function (a, f) { return a + f.value; }, 0);
      var biggest = Math.max(total, loadTotal);
      if (!biggest) {
        svg.appendChild(svgEl("text", { x: W / 2, y: height / 2, "class": "sk-empty",
                                        "text-anchor": "middle" }, "nothing flowing"));
        note.textContent = doc.failed && doc.failed.length
          ? "no data for " + doc.failed.join(", ") : "";
        return;
      }
      var sc = scaleOf(doc.unit, biggest);

      // One scale for both columns, so a column that carries less is visibly narrower.
      var tallest = Math.max(sources.length, loads.length);
      var usable = height - 2 * PAD - GAP * Math.max(0, tallest - 1);
      var perUnit = usable / biggest;

      var room = height - 2 * PAD;

      // A column is centred as a block, its own gaps included, so the two sides and the
      // house line up however many nodes each has.
      function column(list, x, anchorX, anchor) {
        var block = list.reduce(function (a, f) { return a + Math.max(MIN_BAND, f.value * perUnit); }, 0)
          + GAP * Math.max(0, list.length - 1);
        var y = PAD + (room - block) / 2;
        return list.map(function (f) {
          var h = Math.max(MIN_BAND, f.value * perUnit);
          var node = { f: f, y0: y, y1: y + h };
          svg.appendChild(svgEl("rect", { x: x, y: y, width: BAR, height: h, rx: 1.5,
                                          "class": "sk-node f-" + f.domain }));
          var mid = y + h / 2;
          svg.appendChild(svgEl("text", { x: anchorX, y: mid - 1, "text-anchor": anchor,
                                          "class": "sk-label" }, f.label));
          svg.appendChild(svgEl("text", { x: anchorX, y: mid + 9, "text-anchor": anchor,
                                          "class": "sk-value" },
                                ui.fmt(f.value / sc.div, sc.decimals) + " " + sc.unit +
                                (f.approx ? " ≈" : "")));
          y = node.y1 + GAP;
          return node;
        });
      }

      var left = column(sources, LEFT, LEFT - 6, "end");
      var right = column(loads, RIGHT, RIGHT + BAR + 6, "start");

      // The house: as tall as the larger side, centred, so the two columns read against it.
      var hubH = Math.max(MIN_BAND, biggest * perUnit);
      var hubY = PAD + (room - hubH) / 2;
      var hubX = (W - HUB) / 2;

      // Ribbons, drawn before the hub bar so the bar sits on top of their ends.
      var at = hubY + (hubH - total * perUnit) / 2;
      left.forEach(function (n) {
        var h = n.y1 - n.y0;
        svg.appendChild(svgEl("path", { d: ribbon(LEFT + BAR, n.y0, n.y1, hubX, at, at + h),
                                        "class": "sk-flow f-" + n.f.domain }));
        at += h;
      });
      at = hubY + (hubH - loadTotal * perUnit) / 2;
      right.forEach(function (n) {
        var h = n.y1 - n.y0;
        svg.appendChild(svgEl("path", { d: ribbon(hubX + HUB, at, at + h, RIGHT, n.y0, n.y1),
                                        "class": "sk-flow f-" + n.f.domain }));
        at += h;
      });

      svg.appendChild(svgEl("rect", { x: hubX, y: hubY, width: HUB, height: hubH,
                                      rx: 1.5, "class": "sk-hub" }));
      svg.appendChild(svgEl("text", { x: W / 2, y: PAD - 1, "text-anchor": "middle",
                                      "class": "sk-label" }, doc.hub));
      svg.appendChild(svgEl("text", { x: W / 2, y: height - 1, "text-anchor": "middle",
                                      "class": "sk-value" },
                            ui.fmt(total / sc.div, sc.decimals) + " " + sc.unit));

      var bits = [];
      if (doc.period !== "now") bits.push(span(doc));
      // The sources and the named loads are different meters; what they disagree by is
      // worth seeing rather than hiding inside "Other".
      if (doc.balance < 0) bits.push("loads exceed sources by " +
        ui.fmt(-doc.balance / sc.div, sc.decimals) + " " + sc.unit);
      if (doc.failed && doc.failed.length) bits.push("no data for " + doc.failed.join(", "));
      note.textContent = bits.join(" · ");
      if (doc.failed && doc.failed.length) note.className = "sub line sk-note warn";
    }

    function span(d) {
      var from = new Date(d.from * 1000), to = new Date(d.to * 1000);
      var hm = function (x) { return pad(x.getHours()) + ":" + pad(x.getMinutes()); };
      var day = function (x) { return x.getDate() + " " + MONTHS[x.getMonth()]; };
      if (d.period === "today") return "since midnight";
      if (d.period === "yesterday") return day(from);
      return day(from) + " " + hm(from) + " to " + day(to) + " " + hm(to);
    }
    var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    function pad(n) { return n < 10 ? "0" + n : String(n); }

    load();

    return {
      feeds: [],      // the flows live in derived.yml, so this tile shows no age of its own
      update: function () {
        var every = REFRESH_MS[period] || REFRESH_OTHER_MS;
        if (Date.now() - fetched >= every) load();
      }
    };
  });
}());
