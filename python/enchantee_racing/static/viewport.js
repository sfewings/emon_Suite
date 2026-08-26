// The height of the visible viewport, measured rather than assumed.
//
// #app is the full height of the screen, and expressing that in CSS alone does not work
// everywhere the app runs. `100vh` on iOS is not the visible area: in a standalone web app
// with a translucent status bar it includes space the status bar sits over, and in Safari
// proper it includes the collapsing toolbar. `100dvh` is the right answer and needs Safari
// 15.4, where the boat's iPad is on 12. The symptom was the navigation showing half
// clipped along the bottom of the iPad, which is the same fault DESIGN 9.6 records taking
// three attempts, arriving by a different route.
//
// window.innerHeight is the visible height on every version of everything, so this reads
// it and hands it to the stylesheet as --app-h. The CSS keeps 100vh and 100dvh ahead of
// it, so a browser with no JavaScript still gets the best answer it can.
//
// Loaded before the body content on purpose, so the custom property is set before #app is
// first laid out and there is no flash of the wrong height.
//
// Shared by index.html and map.html. hud.html is deliberately self-contained, no external
// script and no external stylesheet (DESIGN 9.1), and reserves the navigation's height by
// hand for reasons recorded there, so it is left alone.
//
// var and function to match the rest of the front end.

(function () {
  "use strict";

  function measure() {
    // documentElement rather than body: #app reads the property, and the custom property
    // has to be set on an ancestor of it.
    document.documentElement.style.setProperty("--app-h", window.innerHeight + "px");
  }

  measure();
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
