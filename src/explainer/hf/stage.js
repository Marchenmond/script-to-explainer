/* script-to-explainer: motion layer. Every visual is a pure function of time t (seconds).
 * Python (explainer.stage) decides WHAT happens and WHEN (assets/stage-data.js); this file decides HOW it moves:
 * closed-form springs, one morphing card, text with blur, word marks, a pointer ring, counters, camera, parallax.
 * A single paused GSAP timeline is only the clock: HyperFrames seeks it and draw(t) repaints everything. */
(function () {
  "use strict";
  var S = window.STAGE, W = 1920, H = 1080, FPS = S.fps, DUR = S.duration;
  var C = { base: "#1e1e2e", mantle: "#181825", crust: "#11111b", line: "#45475a", text: "#cdd6f4", sub: "#a6adc8",
            accent: "#cba6f7", warm: "#fab387", gold: "#f9e2af" };
  var CARD_X = 70, CARD_Y = 90, CARD_W = 980, CARD_H = 750;
  var FLOOR = S.floor_y;

  // ---------------------------------------------------------------- springs (closed form, unit step response)
  var SP = {};
  Object.keys(S.springs).forEach(function (k) { SP[k] = S.springs[k]; });
  function step(sp, t) {
    if (t <= 0) return 0;
    var w = sp[0], z = sp[1], e;
    if (z < 1) {
      var wd = w * Math.sqrt(1 - z * z);
      e = Math.exp(-z * w * t);
      return 1 - e * (Math.cos(wd * t) + (z * w / wd) * Math.sin(wd * t));
    }
    if (z === 1) return 1 - (1 + w * t) * Math.exp(-w * t);
    var s = Math.sqrt(z * z - 1), r1 = -w * (z - s), r2 = -w * (z + s);
    return 1 - (r2 * Math.exp(r1 * t) - r1 * Math.exp(r2 * t)) / (r2 - r1);
  }
  // value = first value + sum of closed-form springs, one per change of target (like a retargeted spring)
  function track(ev, sp, t) {
    var v = ev[0].v;
    for (var i = 1; i < ev.length; i++) { if (t > ev[i].t) v += (ev[i].v - ev[i - 1].v) * step(sp, t - ev[i].t); else break; }
    return v;
  }
  function clamp(x, a, b) { return x < a ? a : (x > b ? b : x); }
  function eo3(u) { u = clamp(u, 0, 1); return 1 - Math.pow(1 - u, 3); }
  function lerp(a, b, u) { return a + (b - a) * u; }
  function hex(c) { var n = parseInt(c.slice(1), 16); return [n >> 16, (n >> 8) & 255, n & 255]; }
  function rgb(a) { return "rgb(" + Math.round(a[0]) + "," + Math.round(a[1]) + "," + Math.round(a[2]) + ")"; }
  function mix(a, b, u) { return [lerp(a[0], b[0], u), lerp(a[1], b[1], u), lerp(a[2], b[2], u)]; }

  // ---------------------------------------------------------------- DOM helpers
  function el(tag, cls, parent, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    if (parent) parent.appendChild(e);
    return e;
  }
  function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
  var root = document.getElementById("root");
  var bgA = el("div", "layer", root), bgB = el("div", "layer", root);
  bgB.innerHTML = '<div class="blob b1"></div><div class="blob b2"></div>';
  bgA.className = "layer grid";
  var world = el("div", "layer world", root);
  var topbar = el("div", "topbar", world), floorBand = el("div", "floorband", world), floorLine = el("div", "floorline", world);
  var card = el("div", "card", world), sidebar = el("div", "sidebar", card);
  var shadow = el("div", "shadow", world);
  var ring = el("div", "ring", world), pulse = el("div", "pulse", world);
  var bitBox = el("div", "bitbox", root);
  var capBox = el("div", "captions", root);

  // ---------------------------------------------------------------- scenes
  var scenes = S.scenes.map(function (sc, i) {
    var o = { i: i, t0: sc.t0, t1: sc.t1, sc: sc, targets: {}, items: [], lines: [], parts: [] };
    var sl = sc.slide, kind = sl.type;
    var box = el("div", "content " + kind, world);
    o.box = box;
    if (kind === "title") {
      if (sl.kicker) { o.kicker = el("div", "kicker", box, esc(sl.kicker.toUpperCase())); o.parts.push(o.kicker); o.targets.kicker = o.kicker; }
      var tt = el("div", "ttitle", box);
      String(sl.title || "").split("\n").forEach(function (ln) { var l = el("div", "tline", tt, esc(ln)); o.lines.push(l); });
      o.title = tt; o.targets.title = tt;
      if (sl.subtitle) { o.sub = el("div", "subtitle", box, esc(sl.subtitle)); o.targets.subtitle = o.sub; }
    } else if (kind === "bullets") {
      o.title = el("div", "btitle", box, esc(sl.title || "")); o.targets.title = o.title;
      var counts = S.counts.filter(function (c) { return c.scene === i && c.item != null; });
      (sl.items || []).forEach(function (it, j) {
        var row = el("div", "item", box);
        row.style.top = (160 + j * 130) + "px";
        var dot = el("div", "dot", row), txt = el("div", "itext", row);
        var cnt = counts.filter(function (c) { return c.item === j; })[0];
        var html = esc(it);
        if (cnt) html = html.replace(String(cnt.to), '<span class="num">0</span>');
        txt.innerHTML = html;
        var item = { row: row, dot: dot, txt: txt, num: txt.querySelector(".num"), cnt: cnt };
        o.items.push(item); o.targets["item:" + j] = txt;
      });
    } else {
      o.title = el("div", "htitle", box, esc(sl.title || "")); o.targets.title = o.title;
      var hl = el("div", "hl", box);
      String(sl.highlight || "").split(/(\s+)/).forEach(function (w) {
        if (/^\s+$/.test(w) || w === "") { hl.appendChild(document.createTextNode(" ")); return; }
        var sp = el("span", "w", hl, esc(w));
        var key = w.toLowerCase().replace(/[^a-z0-9]/g, "");
        if (key) o.targets["word:" + key] = sp;
      });
      o.hl = hl; o.targets.highlight = hl;
      if (sl.subtitle) { o.sub = el("div", "subtitle", box, esc(sl.subtitle)); o.targets.subtitle = o.sub; }
      var bc = S.counts.filter(function (c) { return c.scene === i && c.target === "badge"; })[0];
      if (bc) { o.badge = el("div", "badge", box, '<span class="num">0</span>'); o.badgeCount = bc; o.badgeNum = o.badge.querySelector(".num"); }
    }
    return o;
  });

  // marks (word highlights): band + colour + pulse, attached to a target element
  var marks = S.marks.map(function (m) {
    var sc = scenes[m.scene], target = sc.targets[m.target];
    if (!target) throw new Error("scene " + (m.scene + 1) + ": emph target " + m.target + " not found");
    target.classList.add("markable");
    var band = target.querySelector(":scope > .mk") || el("span", "mk", target);
    return { m: m, target: target, band: band };
  });

  // ---------------------------------------------------------------- card morph tracks
  var CS = S.card_states;
  function cardState(sc) { return CS[sc.slide.type]; }
  var evs = { w: [], h: [], r: [], top: [], bc: [], bar: [] };
  scenes.forEach(function (o, i) {
    var st = cardState(o.sc), t = i === 0 ? 0 : o.t0;
    evs.w.push({ t: t, v: st.w }); evs.h.push({ t: t, v: st.h }); evs.r.push({ t: t, v: st.radius });
    evs.top.push({ t: t, v: CARD_Y + (CARD_H - st.h) / 2 });
    evs.bc.push({ t: t, v: hex(C[st.border] || st.border) });
    evs.bar.push({ t: t, v: st.side_bar ? 1 : 0 });
  });
  function trackColor(ev, sp, t) {
    var v = ev[0].v.slice();
    for (var i = 1; i < ev.length; i++) { if (t > ev[i].t) { var s = step(sp, t - ev[i].t); for (var k = 0; k < 3; k++) v[k] += (ev[i].v[k] - ev[i - 1].v[k]) * s; } }
    return v;
  }

  // ---------------------------------------------------------------- measured layout (once, at setup)
  function measure() {
    var wr = world.getBoundingClientRect();
    scenes.forEach(function (o) {
      o.xy = {};
      Object.keys(o.targets).forEach(function (k) {
        var r = o.targets[k].getBoundingClientRect();
        o.xy[k] = [r.left - wr.left + r.width / 2, r.top - wr.top + r.height / 2];
      });
    });
  }

  // ---------------------------------------------------------------- Bit
  function sprite(parent, clip) {
    var s = el("div", "slice", parent); s.style.clipPath = clip;
    var body = el("div", "sp", s), mouth = el("div", "sp", s);
    return { s: s, body: body, mouth: mouth };
  }
  function bitLayer() {
    var g = el("div", "bitg", bitBox);
    var L = sprite(g, "inset(392px 0 0 0)"), U = sprite(g, "inset(0 0 112px 0)");
    return { g: g, L: L, U: U };
  }
  var bitA = bitLayer(), bitB = bitLayer();
  var SHEET = "assets/bit/poses.png", SHEETB = "assets/bit/poses_blink.png";
  var MOUTHS = ["assets/bit/mouth_fechada.png", "assets/bit/mouth_meio.png", "assets/bit/mouth_aberta.png"];
  function setLayer(b, idx, blink, mouth, lift) {
    var col = idx % 16, row = Math.floor(idx / 16), pos = (-col * 512) + "px " + (-row * 512) + "px";
    var sheet = "url(" + (blink ? SHEETB : SHEET) + ")";
    [b.L.body, b.U.body].forEach(function (e) { e.style.backgroundImage = sheet; e.style.backgroundPosition = pos; });
    b.U.mouth.style.backgroundImage = "url(" + MOUTHS[mouth] + ")"; b.U.mouth.style.backgroundPosition = pos;
    b.U.s.style.transform = "translateY(" + (-8 * lift) + "px)";
  }
  var bitRows = S.bit.frames;

  // ---------------------------------------------------------------- captions
  var chunks = S.captions.map(function (c) {
    var box = el("div", "capchunk", capBox), words = [];
    c.lines.forEach(function (line) {
      var ln = el("div", "capline", box);
      line.forEach(function (w, k) {
        var sp = el("span", "cw", ln, esc(w.w) + (k < line.length - 1 ? " " : ""));
        words.push({ e: sp, t0: w.t0, t1: w.t1 });
      });
    });
    return { c: c, box: box, words: words, last: -1 };
  });

  // ---------------------------------------------------------------- camera
  var camEv = { cx: [], cy: [], z: [] };
  S.camera.forEach(function (c) { camEv.cx.push({ t: c.t, v: c.cx }); camEv.cy.push({ t: c.t, v: c.cy }); camEv.z.push({ t: c.t, v: c.zoom }); });
  function camAt(t) {
    var z = track(camEv.z, SP.CAM, t), cx = track(camEv.cx, SP.CAM, t), cy = track(camEv.cy, SP.CAM, t);
    var ic = S.idle_camera, ph = (1 - Math.cos(2 * Math.PI * t / ic.period_s)) / 2;
    z *= 1 + (ic.zoom_to - 1) * ph;
    cx += ic.pan_px * Math.sin(2 * Math.PI * t / ic.period_s);
    z = clamp(z, 1, 1.2);
    cx = clamp(cx, W / 2 / z, W - W / 2 / z); cy = clamp(cy, H / 2 / z, H - H / 2 / z);
    return { cx: cx, cy: cy, z: z };
  }
  function place(elm, f, cam, extraX, extraY) {
    var z = 1 + (cam.z - 1) * f, cx = W / 2 + (cam.cx - W / 2) * f - (extraX || 0), cy = H / 2 + (cam.cy - H / 2) * f - (extraY || 0);
    elm.style.transform = "translate(" + (W / 2) + "px," + (H / 2) + "px) scale(" + z.toFixed(4) + ") translate(" + (-cx).toFixed(2) + "px," + (-cy).toFixed(2) + "px)";
  }

  // ---------------------------------------------------------------- pointer ring
  var rings = S.rings.map(function (r) { return r; });
  function ringXY(r) { var sc = scenes[r.scene]; var p = sc.xy[r.target]; if (!p) throw new Error("ring target " + r.target + " not found"); return p; }
  var ringPos = { x: [], y: [], show: [] };
  var ringHand = [];
  function bitRow(t) { return bitRows[clamp(Math.round(t * FPS), 0, bitRows.length - 1)]; }
  function buildRing() {
    var prevOut = -9;
    rings.forEach(function (r, k) {
      var p = ringXY(r), spawn = r.t_in - prevOut > 0.45;
      if (spawn) {
        var row = bitRow(r.t_in), cam = camAt(r.t_in);
        var sx = (row[0] - cam.cx) * cam.z + W / 2 - 215, sy = (FLOOR - cam.cy) * cam.z + H / 2 - 190;
        var hx = (sx - W / 2) / cam.z + cam.cx, hy = (sy - H / 2) / cam.z + cam.cy;
        ringPos.x.push({ t: r.t_in, v: hx }); ringPos.y.push({ t: r.t_in, v: hy });
        ringPos.x.push({ t: r.t_in + 0.03, v: p[0] }); ringPos.y.push({ t: r.t_in + 0.03, v: p[1] });
        ringPos.show.push({ t: r.t_in, v: 1, sp: SP.FAST });
      } else {
        ringPos.x.push({ t: r.t_in, v: p[0] }); ringPos.y.push({ t: r.t_in, v: p[1] });
      }
      var next = rings[k + 1];
      if (!next || next.t_in - r.t_out > 0.45) ringPos.show.push({ t: r.t_out, v: 0, sp: SP.SOFT });
      prevOut = r.t_out;
    });
  }
  function showAt(t) {
    var ev = ringPos.show, v = 0, prev = 0;
    for (var i = 0; i < ev.length; i++) { if (t > ev[i].t) { v += (ev[i].v - prev) * step(ev[i].sp, t - ev[i].t); prev = ev[i].v; } }
    return v;
  }
  function trackXY(ev, t) { if (!ev.length) return 0; var v = ev[0].v; for (var i = 1; i < ev.length; i++) { if (t > ev[i].t) v += (ev[i].v - ev[i - 1].v) * step(SP.FAST, t - ev[i].t); } return v; }

  // ---------------------------------------------------------------- draw(t)
  function textIn(elm, t, te, dy, dx) {
    var p = step(SP.FAST, t - te), k = Math.max(0, 1 - p);
    elm.style.opacity = clamp((t - te) / 0.16, 0, 1).toFixed(3);
    elm.style.transform = "translate(" + (dx ? (-dx * (1 - p)).toFixed(1) : 0) + "px," + (dy ? (dy * (1 - p)).toFixed(1) : 0) + "px)";
    elm.style.filter = k > 0.01 ? "blur(" + (8 * k).toFixed(2) + "px)" : "none";
    return p;
  }
  var lastCount = {};
  function setNum(e, v, key) { var s = String(v); if (lastCount[key] !== s) { e.textContent = s; lastCount[key] = s; } }
  function countVal(c, t) { var u = clamp((t - c.t) / (c.ms / 1000), 0, 1); return Math.round(lerp(c.from, c.to, eo3(u))); }

  function draw(t) {
    var cam = camAt(t), row = bitRow(t), bx = row[0];
    // background
    place(bgA, S.background.parallax_cam[0], cam, S.background.parallax_bit_grid * (bx - 1500));
    bgA.style.backgroundPosition = (((S.background.grid_drift_px_s * t) % 60) + 60) % 60 + "px 0px";
    place(bgB, S.background.parallax_cam[1], cam, S.background.blobs_drift_px_s * t + S.background.parallax_bit * (bx - 1500));
    place(world, 1, cam);

    // card morph
    var cs = SP.MORPH, cw = track(evs.w, cs, t), ch = track(evs.h, cs, t), cr = track(evs.r, cs, t), ct = track(evs.top, cs, t);
    var bc = trackColor(evs.bc, cs, t), bar = track(evs.bar, cs, t);
    var intro = step(SP.FAST, t - 0.05);
    card.style.left = CARD_X + "px"; card.style.top = ct.toFixed(1) + "px"; card.style.width = cw.toFixed(1) + "px"; card.style.height = ch.toFixed(1) + "px";
    card.style.borderRadius = cr.toFixed(1) + "px"; card.style.borderColor = rgb(bc);
    card.style.opacity = clamp(t / 0.25, 0, 1).toFixed(3);
    card.style.transform = "scale(" + (0.94 + 0.06 * intro).toFixed(4) + ")";
    sidebar.style.opacity = clamp(bar, 0, 1).toFixed(3);

    // scenes
    scenes.forEach(function (o) {
      var vis = t >= o.t0 - 0.05 && (t < o.t1 + 0.6 || o.i === scenes.length - 1) && (o.i === 0 || t >= o.t0);
      o.box.style.display = vis ? "block" : "none";
      if (!vis) return;
      var te = (o.i === 0 ? 0.15 : o.t0 + 0.1), leave = o.i === scenes.length - 1 ? 1e9 : o.t1;
      var lv = clamp((t - leave) / 0.12, 0, 1);
      o.box.style.opacity = (1 - lv).toFixed(3);
      o.box.style.filter = lv > 0 ? "blur(" + (12 * lv).toFixed(1) + "px)" : "none";
      var k = 0;
      if (o.kicker) textIn(o.kicker, t, te + 0.09 * k++, 20);
      if (o.lines.length) o.lines.forEach(function (l) { textIn(l, t, te + 0.09 * k++, 44); }); else if (o.title) textIn(o.title, t, te + 0.09 * k++, 44);
      if (o.hl) textIn(o.hl, t, te + 0.09 * k++ + 0.05, 36);
      if (o.sub) textIn(o.sub, t, te + 0.09 * k++, 28);
      if (o.badge) {
        var bp = step(SP.POP, t - te - 0.2);
        o.badge.style.opacity = clamp((t - te - 0.2) * 5, 0, 1); o.badge.style.transform = "scale(" + (bp).toFixed(3) + ")";
        var bv = countVal(o.badgeCount, t); setNum(o.badgeNum, bv, "b" + o.i);
        var done = clamp((t - o.badgeCount.t - o.badgeCount.ms / 1000) / 0.5, 0, 1);
        o.badgeNum.style.display = "inline-block"; o.badgeNum.style.transform = "scale(" + (1 + 0.03 * Math.sin(Math.PI * done)).toFixed(3) + ")";
      }
      // bullets: reveal at the spoken word, older ones soften
      var rv = S.reveals.filter(function (r) { return r.scene === o.i; });
      o.items.forEach(function (it, j) {
        var r = rv.filter(function (x) { return x.item === j; })[0], tr = r ? r.t : 1e9;
        var p = step(SP.FAST, t - tr), q = step(SP.FAST, t - tr - 0.1), kq = Math.max(0, 1 - q);
        it.dot.style.transform = "scale(" + clamp(p, 0, 1.12).toFixed(3) + ")";
        var newer = rv.filter(function (x) { return x.item > j && t > x.t; }).length > 0;
        var soft = newer ? step(SP.SOFT, t - Math.min.apply(null, rv.filter(function (x) { return x.item > j; }).map(function (x) { return x.t; }))) : 0;
        it.row.style.opacity = (clamp((t - tr) * 6, 0, 1) * lerp(1, 0.55, clamp(soft, 0, 1))).toFixed(3);
        it.txt.style.transform = "translateX(" + (-34 * (1 - q)).toFixed(1) + "px)";
        it.txt.style.filter = kq > 0.01 ? "blur(" + (8 * kq).toFixed(2) + "px)" : "none";
        if (it.num) { setNum(it.num, countVal(it.cnt, t), "n" + o.i + "_" + j); }
      });
    });

    // marks
    marks.forEach(function (mk) {
      var m = mk.m, u = (t - m.t) / 0.22, grow = eo3(u);
      var gone = mk.m.target.indexOf("item:") === 0 ? 0 : clamp((t - (m.t_word + 1.0)) / 0.3, 0, 1);
      mk.band.style.transform = "scaleX(" + grow.toFixed(3) + ")"; mk.band.style.opacity = ((1 - gone) * (t > m.t - 0.01 ? 1 : 0)).toFixed(3);
      var pu = clamp((t - m.t) / 0.5, 0, 1), pulse = (m.style === "pop" ? 0.08 : 0.04) * Math.sin(Math.PI * pu) * (0.6 + 0.4 * step(SP.POP, t - m.t));
      mk.target.style.color = grow > 0.02 && gone < 1 ? rgb(mix(hex(C.text), hex(C.gold), grow * (1 - gone))) : "";
      mk.target.style.setProperty("--pop", (1 + pulse).toFixed(4));
    });

    // card / shadow / floor in world space
    shadow.style.left = (bx - 100) + "px"; shadow.style.top = (FLOOR + 4 - 14) + "px";
    shadow.style.transform = "scale(" + row[5] + ")";

    // ring
    var sh = clamp(showAt(t), 0, 1.1);
    if (ringPos.x.length) {
      var rx = trackXY(ringPos.x, t), ry = trackXY(ringPos.y, t);
      var click = rings.filter(function (r) { return t >= r.t_click && t < r.t_click + 0.35; })[0];
      var squash = click ? 1 - 0.18 * Math.sin(Math.PI * (t - click.t_click) / 0.35) : 1;
      ring.style.opacity = clamp(sh, 0, 1).toFixed(3);
      ring.style.transform = "translate(" + (rx - 28).toFixed(1) + "px," + (ry - 28).toFixed(1) + "px) scale(" + (clamp(sh, 0, 1.1) * squash).toFixed(3) + ")";
      if (click) {
        var u2 = (t - click.t_click) / 0.35, rr = 28 + 40 * u2;
        pulse.style.opacity = (1 - u2).toFixed(3);
        pulse.style.transform = "translate(" + (rx - rr).toFixed(1) + "px," + (ry - rr).toFixed(1) + "px)";
        pulse.style.width = pulse.style.height = (rr * 2).toFixed(1) + "px";
      } else pulse.style.opacity = 0;
    }

    // Bit: screen space, whole-pixel scale 8 (the camera moves him, never scales him)
    var sx = (bx - cam.cx) * cam.z + W / 2, sy = (FLOOR - cam.cy) * cam.z + H / 2;
    bitBox.style.transform = "translate(" + Math.round(sx - 256) + "px," + Math.round(sy + 40 - 512 + (row[1] - 850)) + "px)";
    var blink = row[2], mouth = row[3], lift = row[4];
    setLayer(bitA, row[6], blink, mouth, lift);
    if (row[9] > 0.001) { bitB.g.style.display = "block"; setLayer(bitB, row[8], blink, mouth, lift); bitB.g.style.opacity = row[9]; } else bitB.g.style.display = "none";
    bitA.g.style.opacity = 1;

    // captions: karaoke fill, no bar
    chunks.forEach(function (ck) {
      var on = t >= ck.c.t0 - 0.05 && t < ck.c.t1 + 0.1;
      ck.box.style.opacity = on ? clamp(Math.min((t - ck.c.t0 + 0.05) / 0.1, (ck.c.t1 + 0.1 - t) / 0.1), 0, 1).toFixed(3) : 0;
      ck.box.style.display = on ? "block" : "none";
      if (!on) return;
      var prevEnd = ck.c.t0;
      ck.words.forEach(function (w) {
        var p = w.t0 == null ? (t >= prevEnd ? 1 : 0) : clamp((t - w.t0) / Math.max(0.05, w.t1 - w.t0), 0, 1);
        if (w.t1 != null) prevEnd = w.t1;
        var s = (p * 100).toFixed(0) + "%";
        if (w.last !== s) { w.e.style.setProperty("--p", s); w.last = s; }
      });
    });
  }

  function build() {
    measure();
    buildRing();
    var st = { t: 0 };
    var tl = gsap.timeline({ paused: true });
    tl.to(st, { t: DUR, duration: DUR, ease: "none", onUpdate: function () { draw(st.t); } }, 0);
    draw(0);
    window.__timelines = window.__timelines || {};
    window.__timelines["explainer"] = tl;
    window.__stageReady = true;
  }
  var fonts = ['700 40px "JetBrains Mono"', '400 40px "JetBrains Mono"'];
  Promise.all(fonts.map(function (f) { return document.fonts.load(f); })).then(function () { return document.fonts.ready; }).then(build);
})();
