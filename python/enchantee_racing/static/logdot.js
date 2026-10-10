// The dot on the Log link while event_recorder is recording (DESIGN 9.13).
//
// Server state, like the theme: /api/state carries recording.active, decided in store.py
// from the recorder's own once-a-second status, so every device lights it together and a
// recorder that stops talking puts it out. Each page calls LogDot.apply from the poll it
// already makes, beside Theme.apply.
//
// Shared by index.html, map.html and gar.html. hud.html has the link but not the dot: it
// polls /hud/data, which keeps the Node-RED flow's shape (DESIGN 9.1), and that carries no
// recording state.
//
// var and function to match the rest of the front end.

(function () {
  "use strict";

  var lit = null;

  function apply(recording) {
    var active = !!(recording && recording.active);
    if (active === lit) return;
    lit = active;
    Array.prototype.forEach.call(document.querySelectorAll("#nav a.log"), function (a) {
      if (active) {
        a.classList.add("rec");
        a.setAttribute("aria-label", "Log, recording");
      } else {
        a.classList.remove("rec");
        a.removeAttribute("aria-label");
      }
    });
  }

  window.LogDot = { apply: apply };
}());
