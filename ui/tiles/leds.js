// leds: pills, on or off (DESIGN 6.2), shown in the tile's heading row.
//
//   "leds": [ {"feed": "derived/car/charging", "on": "charging", "off": "idle"},
//             {"feed": "Leaf / range", "test": "fresh", "on": "home", "off": "away"},
//             {"feed": "derived/battery/midpoint/over1V", "on": "mid-point > 1 V",
//              "off": "", "bad": true} ]
//
// test "value" (the default): on when the value is 1 or more. test "fresh": on while the
// feed is reporting, within the tile's fresh age, which is how Node-RED's "home" light for
// a car worked. "bad" shows on in the warning colour. An empty label hides the pill.
// "big": a larger, bolder pill, for one that is the point of its tile (a car home or away).

(function () {
  "use strict";

  EmonUI.part("leds", function (list, body, tile, ui) {
    var row = ui.el("span", "leds");
    var head = tile.el.querySelector(".h");
    head.insertBefore(row, head.lastChild);
    return {
      feeds: list.map(function (i) { return i.feed; }).filter(Boolean),
      update: ui.pillsInto(row, list, tile)    // shared with tiles/table.js
    };
  });
}());
