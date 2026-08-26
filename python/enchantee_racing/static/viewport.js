// The height of the visible viewport, measured rather than assumed, and written straight
// onto #app as pixels.
//
// #app is the full height of the screen, and expressing that in CSS alone does not work
// everywhere the app runs. `100vh` on iOS is not the visible area: in a standalone web app
// with a translucent status bar it includes space the status bar sits over, and in Safari
// proper it includes the collapsing toolbar. `100dvh` is the right answer and needs Safari
// 15.4, where the boat's iPad is on 12. window.innerHeight is the visible height on every
// version of everything, so this reads it.
//
// It goes on the element's own style attribute, in px. The first version set a custom
// property on documentElement instead and let the stylesheet say
// `height: var(--app-h, 100dvh)`, which is tidier.
//
// This is a simplification and NOT a fix for anything, which is worth saying because it
// was written as one. Two faults on the iPad mini, the course list running off the bottom
// of the screen and the panel going blank a moment after appearing, looked like one fault
// with a tidy explanation: that a var()-derived height is not a definite height on iOS 12,
// so the flex chain below had nothing to resolve against and a re-measure restyled without
// re-laying out. static/layout-check.html put all three ways of setting the height in
// front of the iPad and they came back identical: #app 1024 of an innerHeight of 1024, no
// page scroll, every button on screen, and re-measuring blanking nothing. The theory was
// wrong and both faults are still open (DESIGN 9.8.1).
//
// One mechanism is still simpler than two, so the inline height stays. The stylesheet
// keeps 100vh and then 100dvh ahead of it, so a browser with no JavaScript still gets the
// best answer it can.
//
// Loaded before the body content on purpose, so the height is set on #app the moment it
// exists and there is no flash at the wrong size.
//
// Shared by index.html and map.html. hud.html is deliberately self-contained, no external
// script and no external stylesheet (DESIGN 9.1), and reserves the navigation's height by
// hand for reasons recorded there, so it is left alone.
//
// var and function to match the rest of the front end.

(function () {
  "use strict";

  var last = null;

  function measure() {
    var app = document.getElementById("app");
    if (!app) return;
    var h = window.innerHeight;
    // Unchanged means nothing is written. iOS fires resize during a scroll as the toolbar
    // moves, and a restyle per scroll event is both wasted and, on the machine this file
    // exists for, visible.
    if (!h || h === last) return;
    last = h;
    app.style.height = h + "px";
  }

  // #app does not exist yet when this runs, this being loaded above the body so that the
  // height is set before the first paint rather than after a visible reflow. So: once now,
  // in case the order ever changes, and once the moment the document is parsed.
  measure();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", measure);
  }

  window.addEventListener("resize", measure);
  // iOS reports the old size during orientationchange and settles a moment later, which
  // hud.html's fit() already had to learn.
  window.addEventListener("orientationchange", function () {
    setTimeout(measure, 250);
  });
  // Coming back from the background can change it too, on a phone that was rotated or
  // split-screened while away.
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) measure();
  });
}());
