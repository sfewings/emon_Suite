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
   "series", "cards", "final-elapsed", "final-course", "final-secondary", "wake",
   "mark-round", "nav", "resume", "next"
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
  // Next off the last leg finishes the race, so on that leg it asks first, for the same
  // reason Shorten does: an accidental tap ends a race, and a POST that has arrived is too
  // late to ask about.
  on("next", function () {
    var r = latest.race;
    if (r && r.legs && r.leg >= r.legs - 1) {
      if (!window.confirm("Finish the race now?")) return;
    }
    post("/api/advance", { dir: 1 });
  });

  // Back off leg 1 has no leg to go to, so it goes to the course list. A view change and
  // not a race command: the race carries on, and the Race button there comes back to it
  // (DESIGN 9.6).
  on("back", function () {
    var r = latest.race;
    if (r && r.leg === 0) {
      viewing = "idle";
      showPanel();
      wake();
      return;
    }
    post("/api/advance", { dir: -1 });
  });

  on("start-now", function () { post("/api/timer", { hooter: 0 }); });
  on("resume", function () { viewing = null; showPanel(); wake(); });
  on("reset", function () { post("/api/reset"); });

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

  // Tapping a screen name is a view change and never a command: looking at the course list
  // during a race must not end the race (DESIGN 9.6). `viewing` holds the override until
  // the mode changes, at which point every device follows the mode again, which is the
  // property that has to survive.
  var viewing = null;

  Array.prototype.forEach.call(el.nav.querySelectorAll("button[data-show]"), function (b) {
    b.addEventListener("click", function () {
      viewing = b.getAttribute("data-show");
      showPanel();
      wake();
    });
  });

  // Race is this whole page, so its nav entry means "show whatever panel the race is
  // actually in" and clears any view the crew has tapped away to (DESIGN 9.6).
  function panelFor(name) {
    return name === "race" ? (mode || "idle") : name;
  }

  var PANELS = ["idle", "prestart", "racing", "finished"];

  // The one place a panel is chosen. There were two, this and setMode, each doing its
  // own surgery on body.className, and two writers of one string is a bug waiting to
  // happen however carefully each is written. It happened: a mangled regex here left
  // the previous mode class in place, so tapping Back put mode-racing and mode-idle on
  // the body at once and the CSS displayed both panels, one under the other.
  //
  // classList over an explicit list, rather than a pattern over the whole string, so
  // that failure mode cannot come back: there is no expression to get wrong.
  function showPanel() {
    var panel = panelFor(viewing || "race");
    if (PANELS.indexOf(panel) < 0) panel = "idle";
    PANELS.forEach(function (name) {
      document.body.classList.remove("mode-" + name);
    });
    document.body.classList.add("mode-" + panel);

    // The way back into a running race, shown only when there is one to go back to.
    el.resume.hidden = !(mode && mode !== "idle");
    if (panel === "idle") loadCourses();
  }

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
    // The rounding side sits next to the mark name, as the chart's turn arrow rather than
    // the word, and comes from the leg rather than the mark's default so a course that
    // deviates from the register still reads correctly (DESIGN 9.2). The class picks which
    // of the two inline icons shows; the word goes on the label, so it is still there for
    // anything reading the page out rather than looking at it.
    //
    // Tested against the known two rather than passed through, so a value the config should
    // never hold cannot put an arbitrary class on the element.
    var round = el["mark-round"];
    var side = (r.rounding === "port" || r.rounding === "starboard") ? r.rounding : null;
    round.classList.remove("port", "starboard");
    round.hidden = side === null;
    if (side) {
      round.classList.add(side);
      round.setAttribute("aria-label", "round to " + side);
    } else {
      round.removeAttribute("aria-label");
    }
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
    el.next.textContent = (r.legs && r.leg >= r.legs - 1) ? "Finish" : "Next mark";

    // Secondary row, in the order DESIGN 9.2 lists it: leg number and total, then the leg
    // after this one, which is the part that is about preparing rather than steering. The
    // transit angle is signed to port or starboard and the name is the mark it turns onto.
    var bits = [];
    bits.push("leg <b>" + (r.leg + 1) + "</b> of <b>" + r.legs + "</b>");
    if (r.nav && r.nav.next_name) {
      var onward = "then <b>" + r.nav.next_name + "</b>";
      if (r.nav.transit !== null && r.nav.transit !== undefined) {
        onward += " <b>" + signed(r.nav.transit) + "°</b>";
      }
      if (r.nav.next_leg_type) onward += " <b>" + r.nav.next_leg_type + "</b>";
      bits.push(onward);
    }
    if (r.finish_armed) bits.push("<b>finish armed</b>");
    if (r.shortened) bits.push('<span class="warn">shortened</span>');
    if (r.breaches) bits.push('<span class="warn">' + r.breaches + " breach</span>");
    el.secondary.innerHTML = bits.join(" · ");

    // finished
    el["final-elapsed"].textContent = hms(r.elapsed);
    el["final-course"].textContent = r.course || BLANK;
    var closing = ["leg " + r.legs + " of " + r.legs];
    if (r.shortened) closing.push("shortened");
    if (r.breaches) closing.push(r.breaches + " breach logged");
    el["final-secondary"].textContent = closing.join(" · ");
  }

  function setMode(next) {
    if (next === mode) return;
    mode = next;
    // A mode change wins over whatever the crew has tapped away to look at, so every
    // device follows the race together, which is the property that has to survive
    // (DESIGN 9.6). Panel selection then goes through the one path.
    viewing = null;
    showPanel();
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
    // Start fetching the countdown clips on the gesture rather than on the next poll:
    // setting the timer is itself a tap, so this always runs before a countdown does.
    loadVoice();
  }

  if (el.wake) {
    el.wake.addEventListener("pause", function () { if (wakeStarted) wake(); });
  }
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) return;
    tick();
    wake();
    // The audio clock stops while the page is in the background, so anything scheduled
    // against it is now late by however long the phone was away. Forget the plan and let
    // the next poll rebuild it against the clock as it now stands (DESIGN 10.1).
    planned = null;
  });
  document.body.addEventListener("click", wake);

  // --- countdown audio ---------------------------------------------------
  //
  // A voice at each minute, and one recording through the final ten seconds ending in the
  // horn at T-0 (DESIGN 10). Vibration works on Android and never on iOS, so audio is
  // the primary cue.
  //
  // Scheduled, not triggered. The poll runs at 2 Hz, so noticing T-0 and playing a sound
  // then would put the gun up to half a second out, and half a second is a boat length on
  // the line. Instead each clip is handed to the audio clock with the time it should
  // start, which is sample-accurate, and the final recording is started at an offset into
  // itself so its horn lands on T-0 however late we came to it.

  // Seconds before T-0 that each clip starts. The final one starts at HORN_AT because
  // that is where its horn sits: file time HORN_AT lines up with T-0, which is the
  // contract with scripts/gen_audio.py, and tests/test_audio.py checks the two agree.
  var HORN_AT = 10.0;
  var CUES = [];
  for (var minute = 10; minute >= 1; minute--) {
    CUES.push({ key: "min-" + minute, at: minute * 60 });
  }
  CUES.push({ key: "final", at: HORN_AT });

  // A deadline that moves by less than this is the poll jitter, not the crew: rescheduling
  // on jitter would restart a clip that is already playing.
  var REPLAN_S = 0.3;

  var buffers = {};
  var voiceReady = false;     // every clip decoded; until then the fallback beeps
  var playing = [];
  var planned = null;         // T-0 in audio-clock time, as currently scheduled

  function loadVoice() {
    if (!audio || audio === false || loadVoice.started) return;
    loadVoice.started = true;
    var pending = CUES.length;
    CUES.forEach(function (cue) {
      fetch(base + "/static/audio/" + cue.key + ".m4a", { cache: "force-cache" })
        .then(function (r) { return r.arrayBuffer(); })
        .then(function (encoded) {
          // The promise form is not universal on older Safari, so accept either.
          return new Promise(function (resolve, reject) {
            var result = audio.decodeAudioData(encoded, resolve, reject);
            if (result && result.then) result.then(resolve, reject);
          });
        })
        .then(function (buffer) {
          buffers[cue.key] = buffer;
          if (--pending === 0) voiceReady = true;
        })
        .catch(function () { /* the beep fallback covers whatever did not arrive */ });
    });
  }

  function silence() {
    playing.forEach(function (source) { try { source.stop(); } catch (e) {} });
    playing = [];
  }

  function schedule(deadline) {
    var now = audio.currentTime;
    CUES.forEach(function (cue) {
      var buffer = buffers[cue.key];
      if (!buffer) return;
      var when = deadline - cue.at;
      var offset = 0;
      if (when < now) {
        // Already due. Start it part-way in, so the rest of it still lines up: this is
        // what keeps the horn on T-0 when the page is opened at T-4.
        offset = now - when;
        if (offset >= buffer.duration) return;   // finished before we got here
        when = now;
      }
      var source = audio.createBufferSource();
      source.buffer = buffer;
      source.connect(audio.destination);
      source.start(when, offset);
      playing.push(source);
    });
  }

  // The fallback, kept from the first version of this: if the clips did not load, a bare
  // tone at each minute and each of the last ten seconds is far better than a silent gun.
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

  function updateAudio() {
    if (!audio || audio === false) return;
    loadVoice();
    var r = latest.race;
    var mode = r ? r.mode : null;

    if (!voiceReady) { maybeBeep(); return; }

    if (mode === "prestart" && r.countdown !== null) {
      // The payload describes a moment already a little in the past, by whatever the
      // request took. On a boat's own wifi that is a few milliseconds and not worth
      // modelling; the nudge exists for anything that matters (DESIGN 10).
      var deadline = audio.currentTime + r.countdown;
      if (planned === null || Math.abs(deadline - planned) > REPLAN_S) {
        silence();
        planned = deadline;
        schedule(deadline);
      }
      return;
    }

    // No longer counting down. Racing means the gun has just gone and the horn is still
    // sounding, so leave it alone: cutting it off at T-0 would silence the one cue that
    // matters. Anything else means the countdown was abandoned, so stop.
    if (mode !== "racing") silence();
    planned = null;
    lastBeep = null;
  }

  setInterval(function () { tick(); updateAudio(); }, POLL_MS);
  tick();
  loadCourses();
}());
