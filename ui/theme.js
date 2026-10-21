// Day and night, applied from server state on every poll.
//
// The theme is emon_live's state, not this browser's, so every screen on a site switches
// together, a page that reloads comes up in the site's theme, and any screen can change it
// (DESIGN 4.4). The race app learned that the hard way; its static/theme.js records how.
// This is the same mechanism against emon_live's /api/settings.
//
// The toggle's label is the theme one tap switches to, not the one in force.
//
// var and function, to match the race app and run on iOS 12.

(function () {
  "use strict";

  // Relative to where the page is served, so it works at / and behind a prefix alike.
  var base = location.pathname.replace(/\/[^\/]*$/, "");

  var current = null;
  var OTHER = { day: "night", night: "day" };
  var LABEL = { day: "Night", night: "Day" };

  function buttons() {
    return document.querySelectorAll("[data-theme-toggle]");
  }

  // Idempotent, and called on every poll. Nothing is written when nothing changed.
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
    apply(want);   // at once, rather than leave the tap looking like it did nothing
    fetch(base + "/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ theme: want })
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      // The server is the authority: if it refused, this puts the page back.
      .then(function (d) { if (d && d.theme) apply(d.theme); })
      .catch(function () { /* the next poll corrects it */ });
  }

  document.addEventListener("DOMContentLoaded", function () {
    Array.prototype.forEach.call(buttons(), function (b) {
      b.addEventListener("click", post);
    });
  });

  window.Theme = { apply: apply };
}());
