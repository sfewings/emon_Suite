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
// It goes on the element's own style attribute, in px. The first version of this file set
// a custom property on documentElement instead and let the stylesheet say
// `height: var(--app-h, 100dvh)`, which is tidier and broke two things on iOS 12, both
// reported from the boat and both explained by the same thing: a var()-derived height is
// not a definite height there.
//
//   - The course list ran off the bottom of the screen. #app's height is what makes the
//     flex chain below it definite: .panel takes a share of it, #cards takes a share of
//     that and scrolls inside it, and the grid's 1fr rows divide it. With the height
//     arriving through var(), none of those had a definite basis to resolve against, so
//     the rows fell back to their content and the column grew past the glass.
//
//   - The panel went blank a moment after appearing. Re-measuring changed the property on
//     the root element, which restyled #app without re-laying out its descendants, so the
//     panels were left unpainted while the navigation, being the last child and needing no
//     height of its own, stayed. Toggling day/night put a class on the body, which forces
//     a full restyle, and the page came back. That was the crew's workaround and it is
//     what identified this.
//
// An inline pixel height is a definite height on every browser and an element-level style
// change is re-laid-out reliably. The stylesheet keeps 100vh and then 100dvh ahead of it,
// so a browser with no JavaScript still gets the best answer it can.
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
