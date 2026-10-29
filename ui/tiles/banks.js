// banks: a card for each battery bank, its cells, charge and readings (DESIGN 6.2, 6.6).
//
//   "banks": {"periods": ["now", "today", "yesterday", "week", "month"], "default": "now"}
//
// The banks themselves are the site's derived.yml `banks:` block, served by /api/banks,
// as the Sankey's flows are (banks.py). This says only how to show them.
//
// "Now": each cell's bar rises to its present voltage, the lowest and highest marked and
// the spread between them given beneath. A past period: each bar spans the lowest to the
// highest that cell reached, with a tick at its last reading, so a cell that sags further
// or peaks higher than its neighbours stands out. The cell that went lowest and the cell
// that went highest are named. A bank whose "cells" are offsets about zero (Bank 3's
// series mid-points, `warn_abs`) is drawn about a centre line instead.
//
// Every reading has its now (or last) value, and for a period its lowest and highest.
// "now" is live and costs the server nothing; a period is Influx queries behind a cache,
// so it is asked for a minute at a time.

(function () {
  "use strict";

  var REFRESH_MS = { now: 5000 };
  var REFRESH_OTHER_MS = 60000;
  var LABELS = { now: "Now", today: "Today", yesterday: "Yesterday", week: "7 days", month: "30 days" };

  EmonUI.part("banks", function (spec, body, tile, ui) {
    var periods = spec.periods && spec.periods.length
      ? spec.periods : ["now", "today", "yesterday", "week", "month"];
    var period = periods.indexOf(spec.default) === -1 ? periods[0] : spec.default;
    var doc = null;
    var error = null;
    var pending = false;
    var fetched = 0;

    var tabs = ui.el("div", "sk-tabs");
    var buttons = periods.map(function (p) {
      var b = ui.el("button", "sk-tab", LABELS[p] || p);
      b.type = "button";
      b.onclick = function () {
        if (period === p) return;
        period = p;
        doc = null;
        error = null;
        fetched = 0;
        mark();
        draw();
        load();
      };
      tabs.appendChild(b);
      return { p: p, el: b };
    });
    body.appendChild(tabs);
    var grid = ui.el("div", "banks");
    body.appendChild(grid);
    var note = ui.el("div", "sub line sk-note");
    body.appendChild(note);

    function mark() {
      buttons.forEach(function (b) { b.el.className = "sk-tab" + (b.p === period ? " on" : ""); });
    }
    mark();

    function load() {
      if (pending || !document.body.contains(grid)) return;
      pending = true;
      var asked = period;
      if (asked !== "now" && !doc) note.textContent = "asking Influx for " + (LABELS[asked] || asked).toLowerCase() + "\u2026";
      ui.getJSON(ui.base + "/api/banks?period=" + encodeURIComponent(period))
        .then(function (d) {
          pending = false;
          if (asked !== period) return;
          doc = d;
          error = null;
          fetched = Date.now();
          draw();
        })
        .catch(function (ex) {
          pending = false;
          if (asked !== period) return;
          error = String(ex && ex.message ? ex.message : ex);
          fetched = Date.now();
          draw();
        });
    }

    // --- formatting ---------------------------------------------------------------------

    function num(v) { return typeof v === "number" && isFinite(v); }

    function withUnit(v, d, u) {
      if (!num(v)) return "\u2014";
      return ui.fmt(v, d) + (u ? " " + ui.unit(u) : "");
    }

    // A spread in V reads better in mV.
    function spreadText(d, u) {
      return u === "V" ? ui.fmt(d * 1000, 0) + " mV" : ui.fmt(d, 3) + (u ? " " + u : "");
    }

    function energyText(wh) {
      if (!num(wh)) return "\u2014";
      return Math.abs(wh) >= 1000 ? ui.fmt(wh / 1000, 1) + " kWh" : ui.fmt(wh, 0) + " Wh";
    }

    // --- drawing ------------------------------------------------------------------------

    function draw() {
      grid.innerHTML = "";
      if (!doc) {
        note.textContent = error ? "could not load: " + error : note.textContent;
        note.className = "sub line sk-note" + (error ? " bad" : "");
        return;
      }
      doc.banks.forEach(function (b) { grid.appendChild(card(b, doc.period)); });
      var bits = [];
      if (doc.period !== "now") bits.push(span(doc));
      if (doc.failed && doc.failed.length) bits.push("no data for " + doc.failed.join(", "));
      note.textContent = bits.join(" \u00b7 ");
      note.className = "sub line sk-note" + (doc.failed && doc.failed.length ? " warn" : "");
    }

    function card(b, p) {
      var past = p !== "now";
      var c = ui.el("div", "bank");
      var head = ui.el("div", "bank-h");
      var t = ui.el("div", "bank-t");
      t.appendChild(ui.el("b", null, b.title));
      if (b.note) t.appendChild(ui.el("span", "bank-n", b.note));
      head.appendChild(t);
      if (b.soc) {
        var soc = ui.el("div", "bank-soc");
        soc.appendChild(ui.el("span", "v", num(b.soc.now) ? ui.fmt(b.soc.now, 0) : "\u2014"));
        soc.appendChild(ui.el("small", null, "%"));
        if (past && num(b.soc.min)) soc.appendChild(ui.el("div", "bank-r", ui.fmt(b.soc.min, 0) + "\u2013" + ui.fmt(b.soc.max, 0) + " %"));
        head.appendChild(soc);
      }
      c.appendChild(head);
      if (b.soc) {
        var bar = ui.el("div", "bar");
        var fill = ui.el("i");
        fill.style.width = (num(b.soc.now) ? Math.max(0, Math.min(100, b.soc.now)) : 0) + "%";
        bar.appendChild(fill);
        c.appendChild(bar);
      }
      if (b.cells && b.cells.items && b.cells.items.length) cells(c, b.cells, past);
      if (b.values && b.values.length) c.appendChild(values(b.values, past));
      if (b.energy) {
        c.appendChild(ui.el("div", "sub line", "In " + energyText(b.energy["in"]) +
          " \u00b7 Out " + energyText(b.energy.out)));
      }
      return c;
    }

    function cells(card, spec, past) {
      var items = spec.items;
      var centred = num(spec.warn_abs);
      var u = spec.unit || "V";
      var d = num(spec.decimals) ? spec.decimals : 3;
      // The scale: the readings themselves, padded, so a difference of a few mV in a
      // 3.3 V cell is still visible; about zero for offsets.
      var vals = [];
      items.forEach(function (x) {
        [x.now, x.min, x.max].forEach(function (v) { if (num(v)) vals.push(v); });
      });
      var lo, hi;
      if (centred) {
        var m = spec.warn_abs;
        vals.forEach(function (v) { m = Math.max(m, Math.abs(v)); });
        lo = -m; hi = m;
      } else if (vals.length) {
        lo = Math.min.apply(null, vals); hi = Math.max.apply(null, vals);
        var pad = Math.max((hi - lo) * 0.6, 0.005);
        lo -= pad; hi += pad * 0.25;
      } else { lo = 0; hi = 1; }
      var frac = function (v) { return Math.max(0, Math.min(1, (v - lo) / (hi - lo))); };

      var lowLabel = spec.low ? spec.low.label : null;
      var highLabel = spec.high ? spec.high.label : null;
      var row = ui.el("div", "cells bank-cells" + (centred ? " centred" : ""));
      items.forEach(function (x) {
        var cell = ui.el("div", "cell");
        var cls = [];
        if (x.label === lowLabel) cls.push("lo");
        if (x.label === highLabel) cls.push("hi");
        var worst = past ? (num(x.min) && Math.abs(x.min) > Math.abs(x.max || 0) ? x.min : x.max) : x.now;
        if (centred && num(worst) && Math.abs(worst) > spec.warn_abs) cls.push("warn");
        if (!num(x.now) && !num(x.min)) cls.push("none");
        cell.className = "cell " + cls.join(" ");
        var bar = ui.el("div", "cbar");
        var fill = ui.el("i");
        if (past && num(x.min) && num(x.max)) {
          fill.style.bottom = (frac(x.min) * 100).toFixed(1) + "%";
          fill.style.height = Math.max(2, (frac(x.max) - frac(x.min)) * 100).toFixed(1) + "%";
          if (num(x.now)) {
            var tick = ui.el("b", "ctick");
            tick.style.bottom = (frac(x.now) * 100).toFixed(1) + "%";
            bar.appendChild(tick);
          }
        } else if (num(x.now)) {
          var base = centred ? frac(0) : 0;
          var top = frac(x.now);
          fill.style.bottom = (Math.min(base, top) * 100).toFixed(1) + "%";
          fill.style.height = Math.max(1, Math.abs(top - base) * 100).toFixed(1) + "%";
        }
        bar.appendChild(fill);
        cell.appendChild(bar);
        cell.appendChild(ui.el("div", "cl", x.label));
        cell.title = x.label + ": " + (past
          ? withUnit(x.min, d, u) + " to " + withUnit(x.max, d, u) + ", last " + withUnit(x.now, d, u)
          : withUnit(x.now, d, u));
        row.appendChild(cell);
      });
      card.appendChild(row);

      var bits = [];
      if (spec.low) bits.push((past ? "Lowest " : "Low ") + spec.low.label + ": " + withUnit(spec.low.value, d, u));
      if (spec.high) bits.push((past ? "highest " : "high ") + spec.high.label + ": " + withUnit(spec.high.value, d, u));
      var warn = false;
      if (!past && num(spec.spread)) {
        bits.push("\u0394 " + spreadText(spec.spread, u));
        warn = num(spec.warn_spread) && spec.spread > spec.warn_spread;
      }
      // Not for a period: over a day or a month every cell swings from empty to full, so
      // its lowest and highest say where the charge went, not that the cells disagree.
      // Imbalance is the spread at one moment, which "now" shows.
      var line = ui.el("div", "sub line" + (warn ? " warn" : ""), bits.join(" \u00b7 "));
      card.appendChild(line);
    }

    function values(list, past) {
      var table = ui.el("table", "bank-v");
      if (past) {
        var hr = ui.el("tr");
        ["", "last", "low", "high"].forEach(function (h) { hr.appendChild(ui.el("th", null, h)); });
        table.appendChild(hr);
      }
      list.forEach(function (v) {
        var tr = ui.el("tr");
        tr.appendChild(ui.el("td", "k", v.label));
        tr.appendChild(ui.el("td", null, withUnit(v.now, v.decimals, v.unit)));
        if (past) {
          tr.appendChild(ui.el("td", "r", withUnit(v.min, v.decimals, v.unit)));
          tr.appendChild(ui.el("td", "r", withUnit(v.max, v.decimals, v.unit)));
        }
        table.appendChild(tr);
      });
      return table;
    }

    var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    function pad(n) { return n < 10 ? "0" + n : String(n); }
    function span(d) {
      var from = new Date(d.from * 1000), to = new Date(d.to * 1000);
      var hm = function (x) { return pad(x.getHours()) + ":" + pad(x.getMinutes()); };
      var day = function (x) { return x.getDate() + " " + MONTHS[x.getMonth()]; };
      if (d.period === "today") return "since midnight";
      if (d.period === "yesterday") return day(from);
      return day(from) + " " + hm(from) + " to " + day(to) + " " + hm(to);
    }

    load();

    return {
      feeds: [],      // the banks live in derived.yml, so this tile shows no age of its own
      update: function () {
        var every = REFRESH_MS[period] || REFRESH_OTHER_MS;
        if (Date.now() - fetched >= every) load();
      }
    };
  });
}());
