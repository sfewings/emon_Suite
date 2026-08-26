// A layout and paint log for the real race screen, on the machine that shows the fault.
//
// Loaded only when the URL carries ?probe=1, by three lines in index.html. Nothing here
// runs otherwise and nothing here changes the page's own behaviour.
//
// It exists because two faults were reported from the iPad mini 3, on iOS 12, on the
// course-selection screen and nowhere else: the panel goes blank a moment after appearing,
// and the course list runs past the bottom of the screen. static/layout-check.html put the
// first guess to the device and disproved it, so this measures the real thing instead of a
// replica.
//
// The question it is built to answer: while the screen is blank, do the boxes still have
// their correct geometry? If they do, nothing is wrong with the layout and the pixels are
// simply not being painted, which is a compositing fault and has a different cure. If the
// boxes have collapsed, it is a layout fault. Everything else here is in service of that
// one distinction.
//
// It samples continuously and logs only what CHANGES, so the moment the screen goes blank
// is in the log with whatever changed at that instant beside it.
//
// var and function, ES5 only: it has to run on the browser under test.

(function () {
  "use strict";

  var MAX_LOG = 14;
  var log = [];
  var last = null;
  var t0 = Date.now();

  var box = document.createElement("div");
  box.setAttribute("style", [
    "position:fixed", "left:0", "right:0", "top:0", "z-index:99",
    "background:rgba(0,0,0,.9)", "border-bottom:2px solid #1e90ff",
    "color:#fff", "font:11px/1.4 Menlo,monospace", "padding:4px",
    "max-height:60%", "overflow:auto", "white-space:pre"
  ].join(";"));
  // This file is inserted by script, so it can finish loading either side of
  // DOMContentLoaded: waiting for that event alone means the overlay never appears when it
  // has already fired, which is what happened the first time.
  function attach(node) {
    if (document.body) document.body.appendChild(node);
    else document.addEventListener("DOMContentLoaded", function () {
      document.body.appendChild(node);
    });
  }

  attach(box);

  function rect(el) {
    if (!el) return null;
    var r = el.getBoundingClientRect();
    return { w: Math.round(r.width), h: Math.round(r.height),
             t: Math.round(r.top), b: Math.round(r.bottom) };
  }

  function paintable(el) {
    // What would stop it being painted, as the browser itself reports it. Checked up the
    // ancestor chain, because any one of them hides everything below.
    if (!el) return "gone";
    var node = el, bad = [];
    while (node && node.nodeType === 1) {
      var s = window.getComputedStyle(node);
      var id = node.id || node.className || node.tagName;
      if (s.display === "none") bad.push(id + ":display-none");
      if (s.visibility === "hidden") bad.push(id + ":hidden");
      if (parseFloat(s.opacity) === 0) bad.push(id + ":opacity-0");
      node = node.parentElement;
    }
    return bad.length ? bad.join(",") : "paintable";
  }

  function signature() {
    var app = document.getElementById("app");
    var panel = document.getElementById("panel-idle");
    var series = document.getElementById("series");
    var cards = document.getElementById("cards");
    var nav = document.getElementById("nav");
    if (!app) return null;

    var cardList = cards ? cards.children : [];
    var details = document.querySelectorAll("#cards .info");
    var offscreen = 0, lowest = 0;
    for (var i = 0; i < details.length; i++) {
      var r = details[i].getBoundingClientRect();
      if (r.bottom > lowest) lowest = Math.round(r.bottom);
      if (r.bottom > window.innerHeight + 1) offscreen++;
    }

    // The flag images: an SVG with no width or height attribute has no intrinsic size on
    // some old engines, and these are sized height:100% width:auto inside a 2.6rem box.
    var img = document.querySelector("#cards .flags img");
    var flag = img ? {
      natural: img.naturalWidth + "x" + img.naturalHeight,
      shown: Math.round(img.getBoundingClientRect().width) + "x" +
             Math.round(img.getBoundingClientRect().height),
      complete: img.complete
    } : null;

    return {
      vh: window.innerHeight,
      appInline: app.style.height || "-",
      app: rect(app),
      panel: rect(panel),
      panelPaint: paintable(panel),
      series: rect(series),
      seriesKids: series ? series.children.length : -1,
      seriesFirst: series && series.children.length ? rect(series.children[0]) : null,
      cards: rect(cards),
      cardsClient: cards ? cards.clientHeight : -1,
      cardsScroll: cards ? cards.scrollHeight : -1,
      cardsKids: cardList.length,
      cardFirst: cardList.length ? rect(cardList[0]) : null,
      cardsPaint: paintable(cards),
      flag: flag,
      details: details.length,
      detailsLowest: lowest,
      detailsOff: offscreen,
      nav: rect(nav),
      pageScroll: document.documentElement.scrollHeight - window.innerHeight,
      mode: document.body.getAttribute("data-mode") || "-"
    };
  }

  function summarise(s) {
    if (!s) return "no #app yet";
    var lines = [];
    lines.push("vh " + s.vh + "  #app " + s.app.h + " (inline " + s.appInline + ")" +
               "  mode " + s.mode);
    lines.push("panel " + s.panel.h + " [" + s.panelPaint + "]");
    lines.push("series " + s.series.h + " x" + s.seriesKids +
               (s.seriesFirst ? "  first " + s.seriesFirst.w + "x" + s.seriesFirst.h : ""));
    lines.push("cards " + s.cards.h + " client " + s.cardsClient +
               " scroll " + s.cardsScroll + " x" + s.cardsKids +
               (s.cardFirst ? "  first " + s.cardFirst.w + "x" + s.cardFirst.h : ""));
    lines.push("cards [" + s.cardsPaint + "]");
    if (s.flag) {
      lines.push("flag natural " + s.flag.natural + " shown " + s.flag.shown +
                 " loaded " + s.flag.complete);
    } else {
      lines.push("flag none");
    }
    lines.push("details x" + s.details + " lowest " + s.detailsLowest +
               " past bottom " + s.detailsOff);
    lines.push("nav " + s.nav.t + ".." + s.nav.b + " of " + s.vh +
               "  page scroll " + s.pageScroll);
    return lines.join("\n");
  }

  function draw() {
    var out = "PROBE  t+" + ((Date.now() - t0) / 1000).toFixed(1) + "s\n";
    out += summarise(last) + "\n";
    out += "--- changes ---\n";
    out += log.length ? log.join("\n") : "(none yet)";
    box.textContent = out;
  }

  function diff(a, b) {
    // Only the fields that moved, named, so the log line says what happened rather than
    // repeating the whole state.
    var moved = [];
    var keys = ["vh", "appInline", "mode", "seriesKids", "cardsKids", "cardsClient",
                "cardsScroll", "details", "detailsLowest", "detailsOff", "pageScroll",
                "panelPaint", "cardsPaint"];
    keys.forEach(function (k) {
      if (String(a[k]) !== String(b[k])) moved.push(k + " " + a[k] + "->" + b[k]);
    });
    ["app", "panel", "series", "cards", "nav", "seriesFirst", "cardFirst"].forEach(
      function (k) {
        var x = a[k], y = b[k];
        var sx = x ? x.w + "x" + x.h : "null", sy = y ? y.w + "x" + y.h : "null";
        if (sx !== sy) moved.push(k + " " + sx + "->" + sy);
      });
    if (a.flag || b.flag) {
      var fx = a.flag ? a.flag.shown + "/" + a.flag.natural : "null";
      var fy = b.flag ? b.flag.shown + "/" + b.flag.natural : "null";
      if (fx !== fy) moved.push("flag " + fx + "->" + fy);
    }
    return moved;
  }

  function tick() {
    var now = signature();
    if (!now) return;
    if (last) {
      var moved = diff(last, now);
      if (moved.length) {
        log.push("t+" + ((Date.now() - t0) / 1000).toFixed(1) + "s  " + moved.join("  "));
        if (log.length > MAX_LOG) log.shift();
      }
    }
    last = now;
    draw();
  }

  // Fast while the fault is appearing, then slower, so a long watch does not cost much.
  var fast = setInterval(tick, 200);
  setTimeout(function () { clearInterval(fast); setInterval(tick, 1000); }, 20000);
  tick();

  // A restyle on demand. This is the crew's workaround, and pressing it while the screen
  // is blank is the measurement that matters: if the numbers above do not change when the
  // picture comes back, the layout was right all along and the pixels were simply not
  // being painted.
  var button = document.createElement("button");
  button.textContent = "force restyle";
  button.setAttribute("style", [
    "position:fixed", "right:4px", "bottom:4px", "z-index:99", "min-height:2.6rem",
    "background:#111", "color:#fff", "border:2px solid #1e90ff", "border-radius:6px",
    "font:13px/1 Menlo,monospace", "padding:0 10px"
  ].join(";"));
  button.addEventListener("click", function () {
    var before = summarise(signature());
    document.body.classList.toggle("probe-restyled");
    var after = summarise(signature());
    log.push("t+" + ((Date.now() - t0) / 1000).toFixed(1) + "s  RESTYLE: geometry " +
             (before === after ? "UNCHANGED (a paint fault, not a layout fault)"
                               : "CHANGED (a layout fault)"));
    tick();
  });
  attach(button);

  // Two bisect switches, so the device can name the layer at fault without another build.
  //
  // The blanking is measured as a paint fault, and the page has exactly two things that
  // ask iOS for a composited layer: the touch-scrolling hint on #cards, now removed, and
  // the wake-lock video, which plays for ever at opacity 0 behind everything on z-index
  // -1. If the panel still blanks, one of these two will say which.
  function switcher(label, x, fn) {
    var b = document.createElement("button");
    b.textContent = label;
    b.setAttribute("style", [
      "position:fixed", "right:4px", "bottom:" + x + "px", "z-index:99",
      "min-height:2.6rem", "background:#111", "color:#fff",
      "border:2px solid #ffa500", "border-radius:6px",
      "font:13px/1 Menlo,monospace", "padding:0 10px"
    ].join(";"));
    b.addEventListener("click", function () {
      log.push("t+" + ((Date.now() - t0) / 1000).toFixed(1) + "s  " + fn());
      tick();
    });
    attach(b);
  }

  // Put the composited scroller back, so a page that stops blanking without it can be made
  // to blank again on demand. That is the confirmation, not the absence of a symptom.
  switcher("touch scroll on", 48, function () {
    var cards = document.getElementById("cards");
    if (!cards) return "no #cards";
    var on = cards.style.webkitOverflowScrolling === "touch";
    cards.style.webkitOverflowScrolling = on ? "auto" : "touch";
    return "touch scrolling " + (on ? "off" : "ON, watch for the blank");
  });

  // Take the wake-lock video out of the compositor. It is the other layer, and if the
  // blanking survives the scroller fix this is the next suspect.
  switcher("kill wake video", 92, function () {
    var wake = document.getElementById("wake");
    if (!wake) return "no #wake";
    try { wake.pause(); } catch (e) { /* nothing to do about it */ }
    wake.removeAttribute("src");
    wake.style.display = "none";
    return "wake video stopped and hidden; the screen will sleep now";
  });
}());
