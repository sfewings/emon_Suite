// The height of the visible viewport, measured rather than assumed, written onto #app.
//
// Taken from enchantee_racing/static/viewport.js, where the reasons are recorded at
// length: `100vh` on iOS is not the visible area, `100dvh` needs Safari 15.4 and the
// boat's iPad is on 12, and window.innerHeight is right everywhere. One difference: this
// sets min-height, not height. A house page is longer than a phone and scrolls; a kiosk
// page is laid out to fit and fills the screen either way.
//
// Loaded above the body so the height is set before the first paint.
//
// var and function, to match the race app and run on iOS 12.

(function () {
  "use strict";

  var last = null;

  function measure() {
    var app = document.getElementById("app");
    if (!app) return;
    var h = window.innerHeight;
    // iOS fires resize during a scroll as the toolbar moves; write nothing unchanged.
    if (!h || h === last) return;
    last = h;
    app.style.minHeight = h + "px";
  }

  measure();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", measure);
  }
  window.addEventListener("resize", measure);
  // iOS reports the old size during orientationchange and settles a moment later.
  window.addEventListener("orientationchange", function () {
    setTimeout(measure, 250);
  });
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) measure();
  });
}());
