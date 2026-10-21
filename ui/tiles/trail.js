// trail: a sparkline of one feed over the last few minutes (DESIGN 6.2).
//
//   "trail": {"feed": "Power board / Consumed", "minutes": 30}
//
// Kept by this page from the polls it has made since it opened, so it starts empty and
// fills: there is no history endpoint yet. A point is added only when the feed's age says
// it is a new reading, so a feed that stopped does not draw a flat line.
//
// The SVG has width and height attributes as well as a viewBox: iOS 12 sizes an SVG with
// only a viewBox at 300 px wide (enchantee_racing/CLAUDE.md).

(function () {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";
  var W = 400, H = 34, PAD = 3;

  EmonUI.part("trail", function (spec, body, tile, ui) {
    var keep = (spec.minutes || 30) * 60 * 1000;
    var points = [];   // [ms, value]
    var lastT = null;

    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("class", "spark");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.setAttribute("width", String(W));
    svg.setAttribute("height", String(H));
    svg.setAttribute("preserveAspectRatio", "none");
    var line = document.createElementNS(NS, "polyline");
    line.setAttribute("fill", "none");
    line.setAttribute("stroke-width", "1.5");
    line.setAttribute("vector-effect", "non-scaling-stroke");
    svg.appendChild(line);
    var dot = document.createElementNS(NS, "circle");
    dot.setAttribute("r", "2.5");
    svg.appendChild(dot);
    body.appendChild(svg);

    // Called by the engine with every state document, not every render.
    tile.trail = function (state, received) {
      var f = state.feeds[spec.feed];
      if (!f || typeof f.v !== "number" || f.age === null) return;
      var t = received - f.age * 1000;   // when the reading was taken, on this page's clock
      if (lastT !== null && t <= lastT + 500) return;
      lastT = t;
      points.push([t, f.v]);
      while (points.length && points[0][0] < received - keep) points.shift();
    };

    return {
      feeds: spec.feed ? [spec.feed] : [],
      update: function () {
        if (points.length < 2) {
          line.setAttribute("points", "");
          dot.setAttribute("cx", "-10");
          return;
        }
        var now = Date.now();
        var lo = Infinity, hi = -Infinity;
        points.forEach(function (p) { lo = Math.min(lo, p[1]); hi = Math.max(hi, p[1]); });
        if (hi === lo) { hi += 1; lo -= 1; }
        var xy = points.map(function (p) {
          var x = W - (now - p[0]) / keep * W;
          var y = H - PAD - (p[1] - lo) / (hi - lo) * (H - 2 * PAD);
          return x.toFixed(1) + "," + y.toFixed(1);
        });
        line.setAttribute("points", xy.join(" "));
        var last = xy[xy.length - 1].split(",");
        dot.setAttribute("cx", last[0]);
        dot.setAttribute("cy", last[1]);
      }
    };
  });
}());
