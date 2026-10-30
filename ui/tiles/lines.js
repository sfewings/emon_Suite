// lines: lines of text with {feed} placeholders (DESIGN 6.2). The numbers at a reading's
// size, the words and units small and grey (ui.templateInto).
//
//   "lines": ["Rail {Main battery monitor / Rail|2} V", "Out to 9am {derived/battery/out/to9am|0} Wh"]

(function () {
  "use strict";

  EmonUI.part("lines", function (list, body, tile, ui) {
    if (typeof list === "string") list = [list];
    var els = list.map(function (text) {
      var d = ui.el("div", "sub line");
      body.appendChild(d);
      return { update: ui.templateInto(d, text) };
    });
    var feeds = [];
    list.forEach(function (t) { feeds = feeds.concat(ui.templateFeeds(t)); });

    return {
      feeds: feeds,
      update: function (view) {
        els.forEach(function (l) { l.update(view); });
      }
    };
  });
}());
