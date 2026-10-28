// gauge: a bar from min to max, in the tile's hue (DESIGN 6.2).
//
//   "gauge": {"feed": "Inverter One / batteryCapacity", "min": 0, "max": 100}

(function () {
  "use strict";

  EmonUI.part("gauge", function (spec, body, tile, ui) {
    var bar = ui.el("div", "bar");
    var fill = ui.el("i");
    bar.appendChild(fill);
    body.appendChild(bar);
    var min = typeof spec.min === "number" ? spec.min : 0;
    var max = typeof spec.max === "number" ? spec.max : 100;

    return {
      feeds: spec.feed ? [spec.feed] : [],
      update: function (view) {
        var v = view.value(spec.feed);
        var pct = typeof v === "number" && max > min ? (v - min) / (max - min) * 100 : 0;
        fill.style.width = Math.max(0, Math.min(100, pct)).toFixed(1) + "%";
      }
    };
  });
}());
