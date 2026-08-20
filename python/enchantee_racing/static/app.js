/*
  Race screen. No build step and no framework: this has to be editable from a laptop on a
  jetty (CLAUDE.md).

  Render only. Every decision about a race is the server's, so two devices cannot disagree
  about which leg the boat is on (DESIGN 2). This polls one endpoint, writes numbers into
  elements that already exist, and posts a body when a button is pressed.
*/
(function () {
  "use strict";

  var POLL_MS = 500;
  var STALE_S = 15;          // wind and motor readings dim past this
  var METRES_TO_NM = 1 / 1852;
  var NM_ABOVE_M = 500;      // metres below, nautical miles above (DESIGN 9.4)

  // Built from wherever this page is served, so it works at /race/ behind nginx, at / on
  // its own port, and under mDNS, AP mode or a raw IP alike.
  var base = location.pathname.replace(/\/+$/, "");
  var el = {};
  ["pip", "notice", "countdown", "line-distance", "line-unit", "line-time", "mark-name",
   "distance", "distance-unit", "bearing", "cog", "relative", "elapsed", "secondary",
   "series", "cards", "final-elapsed", "final-course", "final-secondary", "wake"
  ].forEach(function (id) { el[id] = document.getElementById(id); });

  var BLANK = "---";

  // --- formatting -----------------------------------------------------

  function pad(n) { return (n < 10 ? "0" : "") + n; }

  function clock(seconds) {
    if (seconds === null || seconds === undefined) return "--:--";
    var negative = seconds < 0;
    var whole = Math.floor(Math.abs(seconds));
    var text = pad(Math.floor(whole / 60) % 60) + ":" + pad(whole % 60);
    if (whole >= 3600) text = Math.floor(whole / 3600) + ":" + text;
    return (negative ? "-" : "") + text;
  }

  function hms(seconds) {
    if (seconds === null || seconds === undefined) return "--:--:--";
    var whole = Math.floor(seconds);
    return Math.floor(whole / 3600) + ":" + pad(Math.floor(whole / 60) % 60) + ":" +
           pad(whole % 60);
  }

  // Metres under 500, nautical miles above, unit label switched with the value and no
  // animation on the change. Nobody wants 0.08 nm on final approach, or 4830 m on a long
  // leg (DESIGN 9.4).
  function distance(metres, valueNode, unitNode) {
    if (metres === null || metres === undefined) {
      valueNode.textContent = BLANK;
      return;
    }
    if (metres < NM_ABOVE_M) {
      valueNode.textContent = String(Math.round(metres));
      unitNode.textContent = "m";
    } else {
      valueNode.textContent = (metres * METRES_TO_NM).toFixed(2);
      unitNode.textContent = "nm";
    }
  }

  function degrees(value) {
    if (value === null || value === undefined) return BLANK;
    return ("00" + (((Math.round(value) % 360) + 360) % 360)).slice(-3);
  }

  // Signed, port negative, the same convention the HUD uses for TWA and AWA. A third
  // relative angle in a different convention would be a trap (DESIGN 9.3).
  function signed(value) {
    if (value === null || value === undefined) return BLANK;
    var whole = Math.round(value);
    return (whole > 0 ? "+" : "") + whole;
  }

  // --- posting --------------------------------------------------------

  var inFlight = false;

  function post(path, body) {
    if (inFlight) return;          // one command at a time: a double tap is one advance
    inFlight = true;
    wake();
    fetch(base + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
      cache: "no-store"
    }).then(function (r) { return r.json(); })
      .then(function (d) { if (d && d.race) render({ race: d.race }); announce(d.events); })
      .catch(function () {})
      .then(function () { inFlight = false; });
  }

  function on(id, handler) {
    var node = document.getElementById(id);
    if (node) node.addEventListener("click", handler);
  }

  on("hooter-10", function () { post("/api/timer", { hooter: 10 }); });
  on("hooter-5", function () { post("/api/timer", { hooter: 5 }); });
  on("hooter-1", function () { post("/api/timer", { hooter: 1 }); });
  on("nudge-minus", function () { post("/api/timer", { nudge: -1 }); });
  on("nudge-plus", function () { post("/api/timer", { nudge: 1 }); });
  on("cancel", function () { post("/api/timer", { hooter: null }); });
  on("next", function () { post("/api/advance", { dir: 1 }); });
  on("back", function () { post("/api/advance", { dir: -1 }); });
  on("reset", function () { post("/api/reset"); });
  on("to-hud", function () { location.href = base + "/hud"; });
  on("to-hud-2", function () { location.href = base + "/hud"; });

  // Sync to the next whole minute, because someone always taps late (DESIGN 10). Worked
  // out here rather than server-side: it is a statement about the countdown the crew can
  // see, and the arithmetic is the same either way.
  on("sync", function () {
    if (latest.race === null || latest.race.countdown === null) return;
    var remainder = latest.race.countdown % 60;
    var shift = remainder > 30 ? 60 - remainder : -remainder;
    post("/api/timer", { nudge: shift });
  });

  // Deliberate, with a confirm: an accidental tap ends the race (DESIGN 11.6).
  on("shorten", function () {
    if (window.confirm("Shorten course? The next crossing of the line ends the race.")) {
      post("/api/shorten");
    }
  });

  on("night", function () { document.body.classList.toggle("night"); });

  // --- course selection ------------------------------------------------

  var chosenSeries = null;

  function loadCourses() {
    fetch(base + "/api/courses", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(drawCourses)
      .catch(function () {});
  }

  function drawCourses(data) {
    var names = Object.keys(data.series || {});
    if (chosenSeries === null) chosenSeries = names[0] || null;

    el.series.innerHTML = "";
    names.forEach(function (id) {
      var button = document.createElement("button");
      button.textContent = data.series[id].name || id;
      if (id === chosenSeries) button.className = "primary";
      button.addEventListener("click", function () {
        chosenSeries = id;
        drawCourses(data);
      });
      el.series.appendChild(button);
    });

    el.cards.innerHTML = "";
    (data.courses || []).filter(function (c) { return c.series === chosenSeries; })
      .forEach(function (course) {
        var card = document.createElement("button");
        card.className = "card";
        if (!course.raceable) card.setAttribute("disabled", "disabled");

        var flags = document.createElement("div");
        flags.className = "flags";
        // Both flags, so the crew matches what is flying rather than reading text. The
        // division flag is per start rather than per course for some series, so it may be
        // absent; the numeral pendant always identifies the course (DESIGN 8).
        [course.flags.division, course.flags.numeral].forEach(function (flag) {
          if (!flag) return;
          var img = document.createElement("img");
          img.src = "static/flags/" + flag + ".svg";
          img.alt = flag;
          flags.appendChild(img);
        });
        card.appendChild(flags);

        var no = document.createElement("div");
        no.className = "no";
        no.textContent = course.course_no;
        card.appendChild(no);

        var nm = document.createElement("div");
        nm.className = "nm";
        nm.textContent = course.distance_nm.toFixed(2) + " nm";
        if (course.wind_note) nm.textContent += " · " + course.wind_note;
        card.appendChild(nm);

        card.addEventListener("click", function () {
          if (course.raceable) post("/api/select", { course: course.id });
        });
        el.cards.appendChild(card);
      });
  }

  // --- rendering --------------------------------------------------------

  var latest = { race: null };
  var mode = null;

  function render(data) {
    var r = data.race;
    latest.race = r;
    if (r === null || r === undefined) {
      setMode("idle");
      return;
    }
    setMode(r.mode);

    // prestart
    el.countdown.textContent = clock(r.countdown);
    if (r.line) {
      distance(r.line.distance_m, el["line-distance"], el["line-unit"]);
      el["line-time"].textContent = clock(r.line.seconds);
    } else {
      el["line-distance"].textContent = BLANK;
      el["line-time"].textContent = "--:--";
    }

    // racing. nav is null whenever the numbers cannot be known: no fix, or a fix past the
    // 5 s cutoff. Blanked rather than dimmed, because a dimmed number still reads as a
    // number in spray (DESIGN 9.5).
    el["mark-name"].textContent = r.leg_name || BLANK;
    if (r.nav) {
      distance(r.nav.distance_m, el.distance, el["distance-unit"]);
      el.bearing.textContent = degrees(r.nav.bearing);
      el.relative.textContent = signed(r.nav.relative);
    } else {
      el.distance.textContent = BLANK;
      el.bearing.textContent = BLANK;
      el.relative.textContent = BLANK;
    }
    el.elapsed.textContent = hms(r.elapsed);

    var bits = [];
    bits.push("leg <b>" + (r.leg + 1) + "</b> of <b>" + r.legs + "</b>");
    if (r.rounding) bits.push("round <b>" + r.rounding + "</b>");
    if (r.nav && r.nav.leg_type) bits.push("<b>" + r.nav.leg_type + "</b>");
    if (r.finish_armed) bits.push("<b>finish armed</b>");
    if (r.shortened) bits.push('<span class="warn">shortened</span>');
    if (r.breaches) bits.push('<span class="warn">' + r.breaches + " breach</span>");
    el.secondary.innerHTML = bits.join(" · ");

    // finished
    el["final-elapsed"].textContent = hms(r.elapsed);
    el["final-course"].textContent = r.course || BLANK;
    el["final-secondary"].textContent = r.breaches
      ? r.breaches + " breach logged" : "";
  }

  function setMode(next) {
    if (next === mode) return;
    mode = next;
    document.body.className = document.body.className
      .replace(/\bmode-\S+/g, "").trim() + " mode-" + next;
    if (next === "idle") loadCourses();
  }

  function renderHud(state) {
    // COG comes from the HUD half of the payload, and sits beside the bearing so the helm
    // reads the delta without arithmetic (DESIGN 9.2).
    var field = state.fields && state.fields.cog;
    el.cog.textContent = field ? degrees(field.v) : BLANK;
    el.cog.classList.toggle("stale", !field || field.age > STALE_S);
  }

  // --- events, shown briefly and never blocking -------------------------

  var noticeTimer = null;

  function notice(text) {
    el.notice.textContent = text;
    el.notice.classList.add("show");
    if (noticeTimer) clearTimeout(noticeTimer);
    noticeTimer = setTimeout(function () { el.notice.classList.remove("show"); }, 4000);
  }

  // Notices come from watching the state change, not from the event list.
  //
  // Events are drained by whichever request gets to them first, so a breach detected on
  // the server while three phones are polling would reach exactly one of them. The state
  // is the same for every device, so a notice derived from it appears on all three, which
  // is the point of every device rendering the same server state (DESIGN 9.9).
  var previous = null;

  function announceChanges(r) {
    if (r === null || r === undefined) { previous = null; return; }
    if (previous !== null) {
      if (r.breaches > previous.breaches) notice("Crossed a no-cross line");
      else if (r.shortened && !previous.shortened) notice("Course shortened");
      else if (r.mode === "finished" && previous.mode !== "finished") notice("Finished");
      else if (r.mode === "racing" && previous.mode === "prestart") notice("Start");
    }
    previous = r;
  }

  // A POST tells the device that pressed the button what it caused, which is worth showing
  // immediately rather than on its next poll. Only the early-start warning needs saying
  // out loud; the rest are visible in the state.
  function announce(events) {
    if (!events) return;
    events.forEach(function (event) {
      if (event.type === "early") notice("Over early");
    });
  }

  // --- polling ----------------------------------------------------------

  var failures = 0;

  function tick() {
    fetch(base + "/api/state", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (state) {
        failures = 0;
        el.pip.classList.remove("down");
        render(state);
        renderHud(state);
        announceChanges(state.race);
      })
      .catch(function () { if (++failures > 3) el.pip.classList.add("down"); });
  }

  // --- keeping the screen alive and the audio unlocked -------------------

  var wakeStarted = false;
  var audio = null;

  function wake() {
    if (el.wake) {
      var playing = el.wake.play();
      if (playing && playing.then) {
        playing.then(function () { wakeStarted = true; }).catch(function () {});
      }
    }
    // The first tap of any control is a free user gesture, which is the only moment an
    // AudioContext can be unlocked (DESIGN 10).
    if (audio === null && window.AudioContext) {
      try { audio = new AudioContext(); } catch (e) { audio = false; }
    }
    if (audio && audio.state === "suspended") audio.resume();
  }

  if (el.wake) {
    el.wake.addEventListener("pause", function () { if (wakeStarted) wake(); });
  }
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) { tick(); wake(); }
  });
  document.body.addEventListener("click", wake);

  // Audio at each minute and at the final ten seconds. Vibration works on Android and
  // never on iOS, so audio is primary (DESIGN 10).
  var lastBeep = null;

  function beep(seconds) {
    if (!audio || audio === false) return;
    var oscillator = audio.createOscillator();
    var gain = audio.createGain();
    oscillator.connect(gain);
    gain.connect(audio.destination);
    oscillator.frequency.value = seconds === 0 ? 880 : 660;
    gain.gain.value = 0.2;
    oscillator.start();
    oscillator.stop(audio.currentTime + (seconds === 0 ? 0.6 : 0.12));
  }

  function maybeBeep() {
    var r = latest.race;
    if (!r || r.countdown === null || r.mode !== "prestart") { lastBeep = null; return; }
    var remaining = Math.round(r.countdown);
    if (remaining === lastBeep) return;
    if (remaining <= 10 && remaining >= 0) { lastBeep = remaining; beep(remaining); }
    else if (remaining > 0 && remaining % 60 === 0) { lastBeep = remaining; beep(remaining); }
  }

  setInterval(function () { tick(); maybeBeep(); }, POLL_MS);
  tick();
  loadCourses();
}());
