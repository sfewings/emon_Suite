// GAR: the wind dial, as the Garmin GMI 20 lays it out (DESIGN 9.12).
//
// One svg holds the dial, the four corners and the band. This file draws the dial's scale,
// arranges the three parts for the screen it is on, polls /api/state, and eases the needles
// round so a half-second poll does not make them jump.
//
// var and function to match the rest of the front end, which has an iOS 12 floor.

(function () {
  "use strict";

  var POLL_MS = 500;
  var STALE_S = 15;              // wind and motor dim past this, as on the HUD (DESIGN 9.5)
  var NM_ABOVE_M = 500, METRES_TO_NM = 1 / 1852;

  // Relative to where this page is served, so it works behind /race/ and on its own port.
  var base = location.pathname.replace(/\/[^\/]*$/, "");

  var SVG = "http://www.w3.org/2000/svg";
  var svg = document.getElementById("gar");
  var wrap = svg.parentNode;
  var pip = document.getElementById("pip");

  function $(id) { return document.getElementById(id); }

  function norm180(a) { return ((((a + 180) % 360) + 360) % 360) - 180; }
  function fmt1(v)      { return v.toFixed(1); }
  function fmtSigned(v) { return String(Math.round(v)); }
  function fmt3(v)      { return ("00" + ((((Math.round(v) % 360) + 360) % 360))).slice(-3); }

  function el(name, attrs, parent) {
    var node = document.createElementNS(SVG, name);
    Object.keys(attrs).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (parent) parent.appendChild(node);
    return node;
  }

  // --- the dial's scale, drawn once ------------------------------------------------------

  var R = 200;

  // A point at angle a degrees off the bow, clockwise, at radius r.
  function polar(a, r) {
    var t = a * Math.PI / 180;
    return [r * Math.sin(t), -r * Math.cos(t)];
  }

  // An annular sector between two angles, for the close-hauled sectors.
  function sector(a0, a1, r0, r1) {
    var p0 = polar(a0, r1), p1 = polar(a1, r1), p2 = polar(a1, r0), p3 = polar(a0, r0);
    return "M" + p0 + " A" + r1 + "," + r1 + " 0 0,1 " + p1 +
           " L" + p2 + " A" + r0 + "," + r0 + " 0 0,0 " + p3 + " Z";
  }

  (function drawScale() {
    var g = $("dial-scale");
    // 30 to 60 each side, which is where the Garmin draws them: close hauled is somewhere
    // in there for most boats, and the point is a band to read the needle against, not a
    // polar for this one.
    el("path", { "class": "sector-port", d: sector(-60, -30, 158, 186) }, g);
    el("path", { "class": "sector-stbd", d: sector(30, 60, 158, 186) }, g);
    for (var a = 0; a < 360; a += 10) {
      var major = a % 30 === 0;
      var p0 = polar(a, major ? 160 : 174), p1 = polar(a, 196);
      el("line", { "class": major ? "tick major" : "tick",
                   x1: p0[0], y1: p0[1], x2: p1[0], y2: p1[1] }, g);
    }
    // Magnitudes, not signed: the side is the colour of the sector and which half of the
    // dial the number is on. 0 is left off, the hull's bow says where it is.
    for (var n = 30; n <= 180; n += 30) {
      [n, -n].forEach(function (s) {
        if (s === -180) return;
        var p = polar(s, 138);
        var t = el("text", { "class": "scale-num", x: p[0], y: p[1] + 8,
                             "text-anchor": "middle", "font-size": 22 }, g);
        t.textContent = String(n);
      });
    }
  }());

  // --- layout ----------------------------------------------------------------------------
  //
  // Three arrangements of the same three parts, in viewBox units, and the one that draws
  // the dial largest on this screen wins. Worked out on each resize rather than chosen by
  // orientation, because the answer depends on the shape of the space and not on which
  // way up the device is: a split-screen iPad in landscape is a portrait space.
  //
  //   tall   corners above and below the dial, band under that     phones, upright
  //   wide   corners beside the dial, band under it                 the iPad either way
  //   side   corners beside the dial, band beside that              phones on their side

  var DIAL = 440;                // the dial's square: radius 200, room for the diamond
  var CW = 150, CH = 92;         // a corner block
  var BAND = 130;                // the band's height under the dial
  var BAND_W = 270;              // its width beside it
  var M_LBL = 14;                // a motor block's label size

  // The four motor blocks, under the top corners and above the bottom ones, between the
  // given top and bottom edges. Each is a label then a value of `size`, fitted to `w`.
  function motorBlocks(left, right, top, bottom, w, size) {
    var h = M_LBL + 2 + size;
    return { w: w, size: size,
             at: { tl: [left, top], tr: [right, top],
                   bl: [left, bottom - h], br: [right, bottom - h] } };
  }

  var LAYOUTS = [
    { name: "tall", w: DIAL, h: CH + DIAL + CH + BAND,
      dial: [DIAL / 2, CH + DIAL / 2],
      corners: { tl: [8, 0], tr: [DIAL - 8, 0],
                 bl: [8, CH + DIAL], br: [DIAL - 8, CH + DIAL] },
      // Inside the dial's square, in the four corners outside the rim. Small, because
      // that is all the room there is: 30 at 66 wide keeps a four-digit rpm clear of the
      // mark diamond's tip by about ten units.
      motor: motorBlocks(8, DIAL - 8, CH + 2, CH + DIAL - 2, 66, 30),
      band: { x: 0, y: CH + DIAL + CH, w: DIAL, h: BAND, vertical: false } },
    { name: "wide", w: DIAL + 2 * CW, h: DIAL + BAND,
      dial: [CW + DIAL / 2, DIAL / 2],
      corners: { tl: [8, 12], tr: [DIAL + 2 * CW - 8, 12],
                 bl: [8, DIAL - CH - 12], br: [DIAL + 2 * CW - 8, DIAL - CH - 12] },
      // The columns beside the dial, which are empty between their two corners.
      motor: motorBlocks(8, DIAL + 2 * CW - 8, 12 + CH + 10, DIAL - CH - 12 - 10, CW - 16, 44),
      band: { x: 0, y: DIAL, w: DIAL + 2 * CW, h: BAND, vertical: false } },
    { name: "side", w: DIAL + 2 * CW + BAND_W, h: DIAL,
      dial: [CW + DIAL / 2, DIAL / 2],
      corners: { tl: [8, 12], tr: [DIAL + 2 * CW - 8, 12],
                 bl: [8, DIAL - CH - 12], br: [DIAL + 2 * CW - 8, DIAL - CH - 12] },
      motor: motorBlocks(8, DIAL + 2 * CW - 8, 12 + CH + 10, DIAL - CH - 12 - 10, CW - 16, 44),
      band: { x: DIAL + 2 * CW, y: 0, w: BAND_W, h: DIAL, vertical: true } }
  ];

  var layout = null;
  var fitted = [];               // [node, max width, base size], refitted on every change

  function fitText(node, maxW, size) {
    node.setAttribute("font-size", size);
    var w = 0;
    try { w = node.getComputedTextLength(); } catch (e) { /* not rendered yet */ }
    if (w > maxW && w > 0) node.setAttribute("font-size", Math.floor(size * maxW / w));
  }
  function refit(node) {
    for (var i = 0; i < fitted.length; i++) {
      if (fitted[i][0] === node) { fitText(node, fitted[i][1], fitted[i][2]); return; }
    }
  }
  function setFit(node, maxW, size) {
    for (var i = 0; i < fitted.length; i++) {
      if (fitted[i][0] === node) { fitted[i] = [node, maxW, size]; break; }
    }
    if (i === fitted.length) fitted.push([node, maxW, size]);
    fitText(node, maxW, size);
  }

  function place(node, x, y, anchor) {
    node.setAttribute("x", x);
    node.setAttribute("y", y);
    if (anchor) node.setAttribute("text-anchor", anchor);
  }

  function arrange() {
    var cw = wrap.clientWidth, ch = wrap.clientHeight;
    if (!cw || !ch) return;
    var best = null, scale = 0;
    LAYOUTS.forEach(function (l) {
      var s = Math.min(cw / l.w, ch / l.h);
      if (s > scale + 1e-6) { scale = s; best = l; }
    });

    // The size in pixels as attributes, which is what iOS 12 needs (CLAUDE.md).
    svg.setAttribute("width", cw);
    svg.setAttribute("height", ch);
    if (best === layout) { refitAll(); return; }
    layout = best;
    svg.setAttribute("viewBox", "0 0 " + best.w + " " + best.h);

    $("dial").setAttribute("transform", "translate(" + best.dial + ")");

    // Each corner: its label on the top line, its value under it, against the outside edge.
    Object.keys(best.corners).forEach(function (k) {
      var g = $("c-" + k);
      var at = best.corners[k];
      g.setAttribute("transform", "translate(" + at + ")");
      var anchor = g.getAttribute("data-side") === "left" ? "start" : "end";
      Array.prototype.forEach.call(g.querySelectorAll(".c-lbl"), function (t) {
        place(t, 0, 20, anchor);
        t.setAttribute("font-size", 17);
      });
      Array.prototype.forEach.call(g.querySelectorAll(".c-val"), function (t) {
        place(t, 0, 80, anchor);
        setFit(t, CW - 16, 60);
      });
    });

    // Each motor block: the same against the outside edge, smaller.
    var m = best.motor;
    Object.keys(m.at).forEach(function (k) {
      var g = $("m-" + k);
      g.setAttribute("transform", "translate(" + m.at[k] + ")");
      var anchor = g.getAttribute("data-side") === "left" ? "start" : "end";
      var lbl = g.querySelector(".m-lbl"), val = g.querySelector(".m-val");
      place(lbl, 0, M_LBL, anchor);
      lbl.setAttribute("font-size", M_LBL);
      place(val, 0, M_LBL + 2 + m.size * 0.8, anchor);
      setFit(val, m.w, m.size);
    });

    arrangeBand(best.band);
    refitAll();
  }

  function arrangeBand(b) {
    $("band").setAttribute("transform", "translate(" + b.x + "," + b.y + ")");
    var rule = $("band-rule");
    if (b.vertical) {
      rule.setAttribute("x1", 0); rule.setAttribute("y1", 8);
      rule.setAttribute("x2", 0); rule.setAttribute("y2", b.h - 8);
    } else {
      rule.setAttribute("x1", 8); rule.setAttribute("y1", 0);
      rule.setAttribute("x2", b.w - 8); rule.setAttribute("y2", 0);
    }

    // Not racing: SOG, as large as the band allows.
    place($("b-sog-lbl"), 14, 26, "start");
    $("b-sog-lbl").setAttribute("font-size", 17);
    var big = b.vertical ? Math.min(150, b.w * 0.5) : b.h * 0.78;
    place($("b-sog"), b.w / 2, b.vertical ? b.h / 2 + big * 0.36 : b.h - 14, "middle");
    setFit($("b-sog"), b.w - 28, big);

    // Racing: the mark's name across the top, then three cells across or down.
    var top = 38;
    place($("r-name"), 14, 28, "start");
    setFit($("r-name"), b.w - 28, 24);
    for (var i = 0; i < 3; i++) {
      var cell = $("b-cell-" + i);
      var x, y, w, h;
      if (b.vertical) { w = b.w; h = (b.h - top) / 3; x = 0; y = top + i * h; }
      else { w = b.w / 3; h = b.h - top; x = i * w; y = top; }
      cell.setAttribute("transform", "translate(" + x + "," + y + ")");
      var texts = cell.getElementsByTagName("text");
      place(texts[0], 14, 18, "start");
      texts[0].setAttribute("font-size", 15);
      place(texts[1], w - 14, h - 10, "end");
      setFit(texts[1], w - 28, Math.min(h - 28, 90));
    }
  }

  function refitAll() {
    fitted.forEach(function (f) { fitText(f[0], f[1], f[2]); });
  }

  // --- painting --------------------------------------------------------------------------

  function put(node, text) {
    if (node.textContent === text) return;
    node.textContent = text;
    refit(node);
  }

  function live(f) {
    return f && f.v !== null && f.v !== undefined && isFinite(f.v);
  }

  // A {v, age} reading into a text node: dashes when absent, dimmed when old.
  function reading(node, f, format, blank) {
    put(node, live(f) ? format(f.v) : blank);
    node.classList.toggle("stale", !f || f.age > STALE_S);
  }

  var CORNERS = {
    twd: fmt3, awa: fmtSigned, tws: fmt1, twa: fmtSigned,
    rpm: fmtSigned, cur: fmt1, ctrl: fmtSigned, mot: fmtSigned
  };
  var BLANK = { tws: "--.-", cur: "--.-" };

  // The two swaps, both the HUD's idiom: every set pre-rendered and one hidden by a class.
  // `onValue` is the attribute value of the set that shows when `on` is true.
  function swap(attr, onValue, on) {
    var changed = false;
    Array.prototype.forEach.call(svg.querySelectorAll("[" + attr + "]"), function (g) {
      var off = (g.getAttribute(attr) === onValue) !== on;
      if (g.classList.contains("off") !== off) {
        g.classList.toggle("off", off);
        changed = true;
      }
    });
    return changed;
  }

  // --- the needles -----------------------------------------------------------------------
  //
  // Eased toward the latest angle rather than set to it, because a value that arrives
  // twice a second makes a needle that jumps twice a second, and the eye reads a jump as
  // a change. Always the short way round: from -170 to 170 is twenty degrees through the
  // stern, not three hundred and forty through the bow. The rotation is the transform
  // attribute, set from script, which every SVG engine back to iOS 12 honours; CSS
  // transitions on SVG transforms do not reliably.

  function Needle(id) {
    this.node = $(id);
    this.at = null;
    this.target = null;
  }
  Needle.prototype.set = function (angle, stale) {
    if (angle === null) {
      this.node.classList.add("off");
      this.at = this.target = null;
      return;
    }
    this.node.classList.remove("off");
    this.node.classList.toggle("stale", !!stale);
    this.target = angle;
    if (this.at === null) this.draw(angle);   // first sight: no sweep in from the bow
    animate();
  };
  Needle.prototype.draw = function (angle) {
    this.at = angle;
    this.node.setAttribute("transform", "rotate(" + angle.toFixed(1) + ")");
  };
  // One frame's step. Returns whether there is still somewhere to go.
  Needle.prototype.step = function () {
    if (this.target === null || this.at === null) return false;
    var d = norm180(this.target - this.at);
    if (Math.abs(d) < 0.2) {
      if (d !== 0) this.draw(this.target);
      return false;
    }
    this.draw(norm180(this.at + d * 0.25));
    return true;
  };

  var needles = {
    heel: new Needle("heel-line"),
    lwy: new Needle("lwy-line"),
    awa: new Needle("awa-needle"),
    twa: new Needle("twa-pointer"),
    mark: new Needle("mark-diamond")
  };

  var frame = null;
  function animate() {
    if (frame !== null) return;
    frame = window.requestAnimationFrame(function tick() {
      var moving = false;
      Object.keys(needles).forEach(function (k) {
        if (needles[k].step()) moving = true;
      });
      frame = moving ? window.requestAnimationFrame(tick) : null;
    });
  }

  // --- the heel trail --------------------------------------------------------------------
  //
  // The solid heel line is the newest reading, eased like the needles. Behind it, the
  // readings of the last HEEL_TRAIL_S, each fading with its age, so a roll shows as a fan
  // and a steady heel as one line. Display only, so kept here and not on the server: a
  // page opened mid-roll starts with no trail, which costs nothing.
  //
  // Each reading is keyed by when the server got it, which is the poll's clock less its
  // age and stays put across polls, so a reading polled twice is one line not two. The
  // lines are a fixed set made once and reused, rather than made and dropped per reading.

  var HEEL_TRAIL_S = 15;
  var HEEL_TRAIL_MAX = 24;        // the IMU sends at about 1 Hz, so room to spare
  var heelTrail = [];             // {t, v}, oldest first
  var heelLines = [];
  (function () {
    var g = $("heel-trail");
    for (var i = 0; i < HEEL_TRAIL_MAX; i++) {
      heelLines.push(el("line", { x1: -118, y1: 0, x2: 118, y2: 0, "class": "off" }, g));
    }
  }());

  function paintHeelTrail(heel, now) {
    if (live(heel)) {
      var t = now - heel.age;
      var last = heelTrail[heelTrail.length - 1];
      // The same reading again, or y and z landing either side of a poll: one line.
      if (last && Math.abs(t - last.t) < 0.3) last.v = heel.v;
      else heelTrail.push({ t: t, v: heel.v });
    }
    while (heelTrail.length && (now - heelTrail[0].t > HEEL_TRAIL_S ||
                                heelTrail.length > HEEL_TRAIL_MAX + 1)) {
      heelTrail.shift();
    }
    // All but the newest, which is the solid line drawn over them.
    var older = heelTrail.length - 1;
    for (var i = 0; i < HEEL_TRAIL_MAX; i++) {
      var line = heelLines[i], h = i < older ? heelTrail[older - 1 - i] : null;
      if (!h) { line.setAttribute("class", "off"); continue; }
      line.setAttribute("class", "");
      line.setAttribute("transform", "rotate(" + h.v.toFixed(1) + ")");
      line.setAttribute("opacity", (0.6 * (1 - (now - h.t) / HEEL_TRAIL_S)).toFixed(2));
    }
  }

  function paint(d) {
    var f = d.fields || {};
    Object.keys(CORNERS).forEach(function (k) {
      reading($(k), f[k], CORNERS[k], BLANK[k] || "---");
    });
    reading($("aws"), f.aws, fmt1, "--.-");

    // Leeway is blanked by the server below a knot, where COG is noise (DESIGN 9.12).
    reading($("lwy"), d.leeway, fmtSigned, "---");
    needles.lwy.set(live(d.leeway) ? d.leeway.v : null, d.leeway && d.leeway.age > STALE_S);

    // Heel, positive to starboard, and a positive rotation is clockwise on screen, so the
    // starboard end of the line goes down as the starboard rail does.
    needles.heel.set(live(d.heel) ? d.heel.v : null, d.heel && d.heel.age > STALE_S);
    paintHeelTrail(d.heel, d.now / 1000);

    needles.awa.set(live(f.awa) ? f.awa.v : null, f.awa && f.awa.age > STALE_S);
    needles.twa.set(live(f.twa) ? f.twa.v : null, f.twa && f.twa.age > STALE_S);

    paintBand(d, f);
  }

  function paintBand(d, f) {
    var r = d.race || null;
    var racing = !!(r && r.mode === "racing");
    // nav is null before the first fix and once it is more than 5 s old, and then
    // distance, bearing and the diamond go blank, never dim (DESIGN 9.5).
    var nav = (racing && r.nav) || null;

    reading($("b-sog"), f.sog, fmt1, "--.-");
    reading($("r-sog"), f.sog, fmt1, "--.-");

    put($("r-mark"), (r && r.leg_name) || "---");
    refit($("r-name"));
    if (nav && nav.distance_m !== null && nav.distance_m !== undefined) {
      if (nav.distance_m < NM_ABOVE_M) {
        put($("r-dist"), String(Math.round(nav.distance_m)));
        put($("r-dist-lbl"), "DIST m");
      } else {
        put($("r-dist"), (nav.distance_m * METRES_TO_NM).toFixed(2));
        put($("r-dist-lbl"), "DIST nm");
      }
    } else {
      put($("r-dist"), "---");
    }
    put($("r-brg"), nav && nav.bearing !== null ? fmt3(nav.bearing) : "---");

    // The diamond is off the bow by heading, not by COG as the HUD's "off the bow" is.
    // On this dial the wind angles are measured from the heading, and the mark has to be
    // on the same footing for the one thing it is there to show: how far it sits from the
    // wind, which is then the same arithmetic as the leg type (DESIGN 9.12).
    var hdg = f.hdg;
    var markAngle = (nav && nav.bearing !== null && live(hdg) && hdg.age <= STALE_S)
      ? norm180(nav.bearing - hdg.v) : null;
    needles.mark.set(markAngle, false);
  }

  // --- the poll --------------------------------------------------------------------------

  var failures = 0;
  function tick() {
    fetch(base + "/api/state", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        failures = 0;
        pip.classList.remove("down");
        var swapped = swap("data-mode", "motor", !!d.motor);
        swapped = swap("data-race", "on", !!(d.race && d.race.mode === "racing")) || swapped;
        paint(d);
        window.Theme.apply(d.theme);
        if (swapped) refitAll();   // a hidden set had nothing to measure
      })
      .catch(function () { if (++failures > 3) pip.classList.add("down"); });
  }

  arrange();
  window.addEventListener("resize", arrange);
  window.addEventListener("orientationchange", function () { setTimeout(arrange, 250); });
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) { arrange(); tick(); }
  });
  setInterval(tick, POLL_MS);
  tick();

  // --- keeping the screen awake, as the HUD does (DESIGN 9.8) -----------------------------
  //
  // The Wake Lock API needs a secure context and never works over this boat's plain HTTP,
  // and costs nothing to ask for. The hidden looping muted video is what actually works,
  // and it has to be started from a gesture, so the tap handler below starts it.

  var lock = null;
  function requestLock() {
    if (!("wakeLock" in navigator) || lock) return;
    navigator.wakeLock.request("screen").then(function (l) {
      lock = l;
      l.addEventListener("release", function () { lock = null; });
    }).catch(function () {});
  }

  var wake = $("wake");
  var wakeStarted = false;
  function playWake() {
    if (!wake) return;
    var playing = wake.play();
    if (playing && playing.then) {
      playing.then(function () { wakeStarted = true; }).catch(function () {});
    }
  }
  if (wake) {
    // iOS pauses it in the background and does not resume it. Only chase it once it has
    // legitimately started, or a refused autoplay becomes a retry loop.
    wake.addEventListener("pause", function () { if (wakeStarted) playWake(); });
  }
  function keepAwake() { requestLock(); playWake(); }
  document.addEventListener("visibilitychange", function () { if (!document.hidden) keepAwake(); });
  document.body.addEventListener("click", keepAwake);

  // Cross-page navigation by script, not by the anchor: added to the Home Screen, a real
  // anchor to another document leaves iOS's standalone context and reopens in an in-app
  // browser. The href stays on the anchor so it still resolves relatively (DESIGN 9.8.1).
  Array.prototype.forEach.call(document.querySelectorAll("#nav a[href]"), function (a) {
    a.addEventListener("click", function (event) {
      event.preventDefault();
      location.assign(a.href);
    });
  });
}());
