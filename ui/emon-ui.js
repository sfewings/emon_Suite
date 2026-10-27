// emon-ui: pages of tiles over emon_live's /api/state (DESIGN 4.5, 6.1, 6.2).
//
// No build step, no framework, no CDN: editable on the Pi with a text editor, and served
// as is. var and function, no arrow functions, no optional chaining, no flexbox gap:
// the boat's iPad mini 3 runs iOS 12 (enchantee_racing/CLAUDE.md).
//
// A page is data. site/site.json names the pages; site/pages/<id>.json lists the tiles;
// each tile names feeds as emon_config names them (DESIGN 5). A tile is built from parts,
// in this order, each one optional:
//
//   values   a grid of readings, each with an optional "sub" line under it
//   dial     round gauges, side by side
//   compass  bearings on a rose, or angles off the bow
//   cell-bar one bar per battery cell
//   gauge    a bar from min to max
//   trail    a sparkline of one feed, kept by this page since it opened
//   grafana  a Grafana panel in a frame
//   leds     pills, on or off
//   lines    small lines of text
//
// Text anywhere may carry {feed} placeholders, {feed|N} for N decimal places, or
// {feed|time} for a time in seconds since the epoch, shown as "Today 18:54".
// The parts are in tiles/*.js; this file is the engine they plug into.

(function () {
  "use strict";

  var base = location.pathname.replace(/\/[^\/]*$/, "");

  var DEFAULTS = { title: "emon", poll: 2, fresh: 60, gone: 300 };
  var DOMAINS = ["power", "solar", "batt", "heat", "water", "rain", "car", "other"];
  var UNITS = { degC: "°C", deg: "°", pulse: "", count: "" };
  var MINUS = "−";
  var DASH = "—";
  var NNBSP = " ";   // narrow no-break space, between thousands
  var PARTS = ["values", "dial", "compass", "cell-bar", "gauge", "trail", "grafana", "leds", "lines"];

  var parts = {};          // name -> factory(spec, el, tile) returning update(view)
  var site = null;
  var page = null;
  var tiles = [];          // {el, spec, fresh, gone, feeds, updates}
  var state = { feeds: {}, theme: null };
  var received = null;     // Date.now() when the last state arrived
  var timer = null;

  // --- formatting ----------------------------------------------------------------------

  function group(digits) {
    if (digits.length < 5) return digits;   // 2867, but 18 452: as the proposal mockup
    var out = "";
    for (var i = digits.length; i > 0; i -= 3) {
      out = digits.slice(Math.max(0, i - 3), i) + (out ? NNBSP + out : "");
    }
    return out;
  }

  // A number for display. decimals undefined: chosen by size, as a person would.
  function fmt(v, decimals) {
    if (v === null || v === undefined || v === "") return DASH;
    if (typeof v !== "number") return String(v);
    if (!isFinite(v)) return DASH;
    var d = decimals;
    if (d === undefined || d === null) {
      var a = Math.abs(v);
      d = a >= 100 || Math.round(v) === v ? 0 : a >= 10 ? 1 : 2;
    }
    var s = Math.abs(v).toFixed(d);
    var dot = s.indexOf(".");
    var whole = dot === -1 ? s : s.slice(0, dot);
    var frac = dot === -1 ? "" : s.slice(dot);
    var neg = v < 0 && Number(s) !== 0;
    return (neg ? MINUS : "") + group(whole) + frac;
  }

  function unit(u) {
    if (u === undefined || u === null) return "";
    return UNITS.hasOwnProperty(u) ? UNITS[u] : u;
  }

  // A time in seconds since the epoch: "Today 18:54", "Yesterday 18:54", "Mon 18:54",
  // or "22 Oct 18:54". Today and yesterday by this device's calendar, which is the one
  // its reader means; the time itself came from the server.
  var DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function fmtTime(v) {
    if (typeof v !== "number" || !isFinite(v) || v <= 0) return DASH;
    var d = new Date(v * 1000);
    var midnight = new Date();
    midnight.setHours(0, 0, 0, 0);
    var days = Math.floor((midnight.getTime() - d.getTime()) / 86400000) + 1;
    var hm = pad(d.getHours()) + ":" + pad(d.getMinutes());
    if (d.getTime() >= midnight.getTime()) return "Today " + hm;
    if (days === 1) return "Yesterday " + hm;
    if (days < 7) return DAYS[d.getDay()] + " " + hm;
    return d.getDate() + " " + MONTHS[d.getMonth()] + " " + hm;
  }

  // One value as a template or a values item asks: decimals, or "time".
  function fmtAs(v, how) {
    return how === "time" ? fmtTime(v) : fmt(v, how);
  }

  // "12 s", "3 m 10 s", "2 h 5 m", "3 d".
  function fmtAge(s) {
    if (s === null || s === undefined) return "";
    s = Math.max(0, Math.floor(s));
    if (s < 60) return s + " s";
    if (s < 3600) return Math.floor(s / 60) + " m" + (s < 600 ? " " + (s % 60) + " s" : "");
    if (s < 86400) return Math.floor(s / 3600) + " h " + Math.floor((s % 3600) / 60) + " m";
    return Math.floor(s / 86400) + " d";
  }

  // --- feeds and templates -------------------------------------------------------------

  // {name} or {name|N}. Returns [{text}|{feed, decimals}] pieces.
  function parseTemplate(text) {
    var out = [];
    var pos = 0;
    while (true) {
      var start = text.indexOf("{", pos);
      if (start === -1) break;
      var end = text.indexOf("}", start);
      if (end === -1) break;
      if (start > pos) out.push({ text: text.slice(pos, start) });
      var inner = text.slice(start + 1, end);
      var bar = inner.lastIndexOf("|");
      var piece = { feed: (bar === -1 ? inner : inner.slice(0, bar)).trim() };
      var how = bar === -1 ? "" : inner.slice(bar + 1).trim();
      if (/^\d+$/.test(how)) piece.decimals = Number(how);
      else if (how === "time") piece.decimals = "time";
      if (piece.feed) out.push(piece);
      pos = end + 1;
    }
    if (pos < text.length) out.push({ text: text.slice(pos) });
    return out;
  }

  function templateFeeds(text) {
    return parseTemplate(text).filter(function (p) { return p.feed; }).map(function (p) { return p.feed; });
  }

  // The view a part renders from: values, units and ages for one tile, at one moment.
  function makeView(tile) {
    var extra = received === null ? 0 : (Date.now() - received) / 1000;
    return {
      tile: tile,
      has: function (name) { return state.feeds.hasOwnProperty(name); },
      age: function (name) {
        var f = state.feeds[name];
        return f && f.age !== null && f.age !== undefined ? f.age + extra : null;
      },
      // A feed past its tile's "gone" reads as no value: the page never shows a stale
      // number as if it were current (DESIGN D6).
      value: function (name) {
        var f = state.feeds[name];
        if (!f) return null;
        var a = this.age(name);
        if (a !== null && a >= tile.gone) return null;
        return f.v;
      },
      lastValue: function (name) {
        var f = state.feeds[name];
        return f ? f.v : null;
      },
      unit: function (name) {
        var f = state.feeds[name];
        return f ? unit(f.u) : "";
      },
      fill: function (text) {
        var self = this;
        return parseTemplate(text).map(function (p) {
          return p.feed ? fmtAs(self.value(p.feed), p.decimals) : p.text;
        }).join("");
      }
    };
  }

  // --- DOM -----------------------------------------------------------------------------

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }

  function buildTile(spec, defaults) {
    var tile = {
      spec: spec,
      fresh: num(spec.fresh, defaults.fresh),
      gone: num(spec.gone, defaults.gone),
      feeds: [],
      updates: []
    };
    var domain = DOMAINS.indexOf(spec.domain) === -1 ? "other" : spec.domain;
    var root = el("section", "tile d-" + domain + (spec.span === 2 ? " w2" : ""));
    var head = el("div", "h");
    head.appendChild(el("b", null, spec.title || ""));
    tile.headRight = el("i", "age");
    head.appendChild(tile.headRight);
    root.appendChild(head);
    tile.body = el("div", "body");
    root.appendChild(tile.body);
    tile.foot = el("div", "foot");
    root.appendChild(tile.foot);
    tile.el = root;

    if (spec.headline) tile.feeds = tile.feeds.concat(templateFeeds(spec.headline));
    PARTS.forEach(function (name) {
      if (spec[name] === undefined || !parts[name]) return;
      var made = parts[name](spec[name], tile.body, tile, api);
      tile.updates.push(made.update);
      tile.feeds = tile.feeds.concat(made.feeds || []);
    });
    return tile;
  }

  function num(v, fallback) {
    return typeof v === "number" && isFinite(v) ? v : fallback;
  }

  // Fresh, ageing (fading from full to 40 % opacity) or gone, from the newest of the
  // tile's feeds (DESIGN D6, proposal "Data age, three states").
  function updateTile(tile) {
    var view = makeView(tile);
    // A tile that names no feeds (a Grafana frame) has no age to show.
    if (!tile.feeds.length) {
      tile.updates.forEach(function (u) { u(view); });
      return;
    }
    var newest = null;
    tile.feeds.forEach(function (name) {
      var a = view.age(name);
      if (a !== null && (newest === null || a < newest)) newest = a;
    });
    var gone = newest === null || newest >= tile.gone;
    var ageing = !gone && newest > tile.fresh;
    tile.el.classList.toggle("dead", gone);
    tile.el.classList.toggle("ageing", ageing);
    tile.body.style.opacity = ageing
      ? String(1 - 0.6 * (newest - tile.fresh) / (tile.gone - tile.fresh)) : "";

    var ageText = newest === null ? "no data" : gone ? "no data " + fmtAge(newest) : fmtAge(newest);
    var ageClass = "age" + (gone ? " bad" : ageing ? " warn" : "");
    if (tile.spec.headline) {
      tile.headRight.textContent = view.fill(tile.spec.headline);
      tile.headRight.className = "head";
      tile.foot.textContent = ageText;
      tile.foot.className = "foot " + ageClass;
    } else {
      tile.headRight.textContent = ageText;
      tile.headRight.className = ageClass;
      tile.foot.textContent = "";
    }
    // Gone: the values blank, but the last known one stays in small type with its time,
    // so it is not lost (proposal, "Data age, three states").
    var first = (tile.spec.values || [])[0];
    if (gone && first && first.feed && view.lastValue(first.feed) !== null) {
      var at = new Date(Date.now() - (view.age(first.feed) || 0) * 1000);
      tile.foot.textContent = "last " + fmt(view.lastValue(first.feed), first.decimals) + " " +
        view.unit(first.feed) + " at " + pad(at.getHours()) + ":" + pad(at.getMinutes());
      tile.foot.className = "foot age";
    }
    tile.updates.forEach(function (u) { u(view); });
  }

  function render() {
    tiles.forEach(updateTile);
    var stale = 0;
    tiles.forEach(function (t) { if (t.el.classList.contains("dead")) stale += 1; });
    var status = document.getElementById("status");
    if (status) {
      var since = received === null ? null : (Date.now() - received) / 1000;
      var offline = since === null || since > Math.max(10, 3 * site.poll);
      var now = new Date();
      var clock = pad(now.getHours()) + ":" + pad(now.getMinutes()) + ":" + pad(now.getSeconds());
      status.textContent = offline
        ? (since === null ? "connecting" : "offline " + fmtAge(since))
        : "live · " + clock + (stale ? " · " + stale + " stale" : "");
      status.className = offline ? "offline" : "";
    }
  }

  function pad(n) { return n < 10 ? "0" + n : String(n); }

  // --- pages ---------------------------------------------------------------------------

  function pageId() {
    var h = location.hash.replace(/^#/, "");
    if (h) return h;
    return site.default || (site.pages.filter(function (p) { return p.id; })[0] || {}).id || "_all";
  }

  function buildMenu() {
    var menu = document.getElementById("menu");
    if (!menu) return;
    menu.innerHTML = "";
    var shown = site.pages.filter(function (p) { return p.id || p.link; });
    if (shown.length < 2) return;   // a site with one page shows no menu (DESIGN 6.1)
    shown.forEach(function (p) {
      var a = el("a", null, p.title || p.id);
      a.href = p.link ? p.link : "#" + p.id;
      if (p.id) a.setAttribute("data-page", p.id);
      menu.appendChild(a);
    });
  }

  function markMenu(id) {
    Array.prototype.forEach.call(document.querySelectorAll("#menu a"), function (a) {
      a.classList.toggle("on", a.getAttribute("data-page") === id);
    });
  }

  // Every feed known, one tile per group: what a page is written from.
  function allFeedsPage() {
    var groups = {};
    Object.keys(state.feeds).sort().forEach(function (name) {
      var slash = name.indexOf(" / ");
      var g = slash === -1 ? name.split("/").slice(0, 2).join("/") : name.slice(0, slash);
      (groups[g] = groups[g] || []).push(name);
    });
    return {
      title: "All feeds",
      tiles: Object.keys(groups).map(function (g) {
        return {
          title: g, domain: "other", span: 2, gone: 86400 * 365,
          values: groups[g].map(function (name) {
            var slash = name.indexOf(" / ");
            return { feed: name, label: slash === -1 ? name.slice(g.length + 1) || name : name.slice(slash + 3) };
          }),
          cols: 4
        };
      })
    };
  }

  function show(id) {
    var main = document.getElementById("tiles");
    main.innerHTML = "";
    tiles = [];
    markMenu(id);
    var load = id === "_all"
      ? fetchState(true).then(allFeedsPage)
      : getJSON(base + "/site/pages/" + encodeURIComponent(id) + ".json");
    return load.then(function (p) {
      page = p || { title: "Not found", tiles: [] };
      // "cols" fixes the page's columns from tablet width up, so a boat page lays out
      // the same on the iPad and the kiosk; a phone keeps its own (emon-ui.css).
      var cols = Math.max(0, Math.min(4, Math.floor(num(page.cols, 0))));
      main.className = cols ? "p" + cols : "";
      var defaults = { fresh: num(page.fresh, site.fresh), gone: num(page.gone, site.gone) };
      (page.tiles || []).forEach(function (spec) {
        var t = buildTile(spec, defaults);
        tiles.push(t);
        main.appendChild(t.el);
      });
      if (!(page.tiles || []).length) main.appendChild(el("p", "empty", "No tiles on page " + id + "."));
      document.title = (page.title ? page.title + " · " : "") + site.title;
      render();
    }).catch(function () {
      main.appendChild(el("p", "empty", "Page " + id + " could not be loaded."));
    });
  }

  // --- data ----------------------------------------------------------------------------

  function getJSON(url) {
    return fetch(url, { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error(url + " " + r.status);
      return r.json();
    });
  }

  function fetchState(all) {
    return getJSON(base + "/api/state" + (all || pageId() === "_all" ? "?all=1" : "")).then(function (s) {
      state = { feeds: s.feeds || {}, theme: s.theme };
      received = Date.now();
      if (window.Theme) window.Theme.apply(s.theme);
      tiles.forEach(function (t) { if (t.trail) t.trail(state, received); });
      return s;
    });
  }

  function poll() {
    fetchState(false).then(render, render).then(function () {
      timer = setTimeout(poll, site.poll * 1000);
    });
  }

  function start() {
    getJSON(base + "/site/site.json").catch(function () { return {}; }).then(function (s) {
      site = {};
      Object.keys(DEFAULTS).forEach(function (k) { site[k] = DEFAULTS[k]; });
      Object.keys(s || {}).forEach(function (k) { site[k] = s[k]; });
      site.pages = site.pages || [];
      var title = document.getElementById("title");
      if (title) title.textContent = site.title;
      // "menu": "large" doubles the page tabs, for a touch screen at arm's length.
      document.body.classList.toggle("menu-large", site.menu === "large");
      buildMenu();
      window.addEventListener("hashchange", function () { show(pageId()); });
      // Ages tick between polls, from the server's ages plus the time since they came.
      setInterval(render, 1000);
      return fetchState(false).catch(function () { return null; }).then(function () {
        return show(pageId());
      });
    }).then(function () {
      timer = setTimeout(poll, site.poll * 1000);
    });
  }

  var api = {
    el: el, fmt: fmt, fmtAs: fmtAs, fmtTime: fmtTime, fmtAge: fmtAge, unit: unit,
    parseTemplate: parseTemplate, templateFeeds: templateFeeds
  };

  window.EmonUI = {
    part: function (name, factory) { parts[name] = factory; },
    start: start,
    api: api
  };
}());
