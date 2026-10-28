// grafana: a Grafana panel in a frame (DESIGN 6.2, PLAN 3).
//
//   "grafana": {"src": "../grafana/d-solo/boat/enchantee?orgId=1&panelId=2&from=now-1h&to=now&refresh=30s",
//               "height": 260}
//
// The URL as Grafana's "Share, embed" gives it, made relative so that it works behind
// nginx, by IP and by name alike. Unless it names a theme itself, the frame follows the
// page's day and night, reloading when the theme changes. A tile with only a frame names
// no feeds, so the engine shows no age for it.

(function () {
  "use strict";

  EmonUI.part("grafana", function (spec, body, tile, ui) {
    var frame = ui.el("iframe", "grafana");
    frame.setAttribute("frameborder", "0");
    frame.setAttribute("scrolling", "no");
    frame.style.height = (typeof spec.height === "number" ? spec.height : 240) + "px";
    body.appendChild(frame);
    var src = spec.src || "";
    var themed = src && !/[?&]theme=/.test(src);
    var shown = null;

    return {
      feeds: [],
      update: function () {
        var want = themed
          ? src + (src.indexOf("?") === -1 ? "?" : "&") + "theme=" +
            (document.body.classList.contains("night") ? "dark" : "light")
          : src;
        if (want !== shown) {
          shown = want;
          frame.setAttribute("src", want);
        }
      }
    };
  });
}());
