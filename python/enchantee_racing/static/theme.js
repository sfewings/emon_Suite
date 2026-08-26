// Day and night, applied from server state on every poll.
//
// The theme used to be a class this page toggled on itself and nothing else. Three faults
// were reported from the boat at once, and they are all the same fault: it could only be
// set from the one screen that carried the button, it did not reach the HUD or the map,
// and walking to either of those and back lost it. A setting held in a document cannot
// survive leaving that document, and these are three separate documents by decision
// (DESIGN 9.1 and 12.1).
//
// So the theme is server state, which is what DESIGN 9.9 already says about everything
// else here: every device renders the same state and any device can drive it. All three
// pages poll /api/state twice a second already, so the theme rides along in a request
// that was happening anyway, and a page that reloads or a phone that joins mid-race comes
// up in whatever the boat is in. The sun sets on the whole boat at once, which is why this
// is not a per-browser preference.
//
// Shared by index.html and map.html. hud.html carries its own copy, being self-contained
// by decision, and a test holds the two to each other.
//
// var and function to match the rest of the front end.

(function () {
  "use strict";

  // Relative to where this page is served, like every other fetch in this app, so it
  // works behind /race/ and on the app's own port alike (CLAUDE.md).
  var base = location.pathname.replace(/\/[^\/]*$/, "");

  var current = null;

  // The toggle's label is the theme it will switch to, not the one in force. A control
  // that names its own state needs a second affordance to say it is a control; a control
  // that names what one tap does needs nothing, and the theme in force is already obvious
  // from the fact that the whole screen is red.
  var OTHER = { day: "night", night: "day" };
  var LABEL = { day: "Night", night: "Day" };

  function buttons() {
    return document.querySelectorAll("[data-theme-toggle]");
  }

  // Idempotent, and called twice a second. Nothing is written when nothing changed.
  function apply(theme) {
    if (theme !== "day" && theme !== "night") return;
    if (theme === current) return;
    current = theme;
    document.body.classList.toggle("night", theme === "night");
    Array.prototype.forEach.call(buttons(), function (b) {
      b.textContent = LABEL[theme];
    });
  }

  function post() {
    var want = OTHER[current] || "night";
    // Applied at once rather than on the next poll: half a second of a button that has
    // visibly not worked is half a second of the crew tapping it again.
    apply(want);
    fetch(base + "/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ theme: want })
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      // The server is the authority, so if it refused, this puts the page back.
      .then(function (d) { if (d && d.theme) apply(d.theme); })
      .catch(function () { /* the next poll corrects it (DESIGN 2) */ });
  }

  Array.prototype.forEach.call(buttons(), function (b) {
    b.addEventListener("click", post);
  });

  window.Theme = { apply: apply };
}());
