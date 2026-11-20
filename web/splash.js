// The start-up animation: the logo is printed like a 3D print. A head lays the five layers of the planet from the
// bottom up (still hot, then cooling), runs round it and leaves the ring; the name rises under it and the window
// fades in. Vectors animated by the browser and sounds made here: no video, no audio file.
// Shown once per window (not again when the page reloads for another language), never with "reduce motion";
// a click or a key skips it. The sound follows Settings > Sound at startup and needs a window that lets a page
// play without a click (the desktop window does; a browser tab stays silent).
(() => {
  const root = document.getElementById("splash");
  if (!root) return;
  let seen = false;
  try { seen = sessionStorage.getItem("vf.splash") === "1"; sessionStorage.setItem("vf.splash", "1"); } catch { /* storage unavailable */ }
  if (seen || !root.animate || matchMedia("(prefers-reduced-motion: reduce)").matches) { root.remove(); return; }

  const NS = "http://www.w3.org/2000/svg";
  const R = 26, CX = 50, CY = 50, RX = 40, RY = 11, TILT = -18 * Math.PI / 180;
  const LAYERS = [0, 1, 2, 3, 4].map((i) => [24 + i * 11.04, 24 + i * 11.04 + 7.84]);     // top to bottom, as in logo.svg
  const dark = document.documentElement.dataset.mode !== "light";
  // planet, a layer just laid, and the colour behind the planet without / with the glow (the ring's gap is drawn in it)
  const C = dark ? { planet: "#f5f5f7", hot: "#4da6ff", bg: "#06070b", lit: "#071b32", head: "#9fd0ff" }
                 : { planet: "#0e1222", hot: "#0a84ff", bg: "#eef1f6", lit: "#cae0f7", head: "#0a84ff" };
  // its colours stay as they started, even if the saved light/dark setting arrives from the server half-way
  root.style.background = C.bg; root.style.color = C.planet; root.style.setProperty("--sp-head", C.head);
  const E = { out: "cubic-bezier(.16,1,.3,1)", inOut: "cubic-bezier(.65,0,.35,1)", soft: "cubic-bezier(.33,1,.68,1)", in: "cubic-bezier(.5,0,.75,0)" };
  const easeInOut = (p) => (p < .5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2);

  // ---------------------------------------------------------------- the logo, in pieces that can move
  const half = (y) => Math.sqrt(Math.max(0, R * R - (y - CY) * (y - CY)));
  const svg = (tag, attrs, parent) => {
    const el = document.createElementNS(NS, tag);
    for (const k in attrs) el.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(el);
    return el;
  };
  const html = (cls, parent) => { const el = document.createElement("div"); el.className = cls; parent.appendChild(el); return el; };
  // points of the tilted ring at equal steps of length, from its right end and clockwise like the stroke:
  // 0 to .5 is the half in front of the planet, .5 to 1 the half behind it
  const ringPoint = (() => {
    const n = 720, pts = [], len = [0];
    for (let i = 0; i <= n; i++) {
      const t = i / n * 2 * Math.PI, x = RX * Math.cos(t), y = RY * Math.sin(t);
      pts.push([CX + x * Math.cos(TILT) - y * Math.sin(TILT), CY + x * Math.sin(TILT) + y * Math.cos(TILT)]);
      if (i) len.push(len[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
    }
    return (p) => {
      const target = Math.min(1, Math.max(0, p)) * len[n];
      let lo = 0, hi = n;
      while (hi - lo > 1) { const m = (lo + hi) >> 1; if (len[m] <= target) lo = m; else hi = m; }
      const f = (target - len[lo]) / ((len[hi] - len[lo]) || 1);
      return [pts[lo][0] + (pts[hi][0] - pts[lo][0]) * f, pts[lo][1] + (pts[hi][1] - pts[lo][1]) * f];
    };
  })();

  const box = html("sp-box", root), markBox = html("sp-markbox", box), glow = html("sp-glow", markBox);
  const mark = svg("svg", { class: "sp-mark", viewBox: "0 0 100 100" }, markBox);
  const defs = svg("defs", {}, mark);
  svg("rect", { x: -60, y: 50, width: 220, height: 110 }, svg("clipPath", { id: "spFront" }, defs));
  svg("circle", { cx: CX, cy: CY, r: R }, svg("clipPath", { id: "spDisc" }, defs));
  const tilt = "rotate(-18 50 50)", ellipse = { cx: CX, cy: CY, rx: RX, ry: RY, pathLength: 1 };
  const draw = [svg("ellipse", { ...ellipse, class: "sp-ring" }, svg("g", { transform: tilt }, mark))];       // the whole ring, behind
  const headUnder = svg("circle", { class: "sp-head", r: 2.2 }, mark);
  const layers = LAYERS.map(([y1, y2]) => {
    const a = half(y1), b = half(y2);      // a slice of the planet between two heights
    return svg("path", { class: "sp-layer", fill: C.planet,
      d: `M${CX - a},${y1} L${CX + a},${y1} A${R},${R} 0 0 1 ${CX + b},${y2} L${CX - b},${y2} A${R},${R} 0 0 1 ${CX - a},${y1} Z` }, mark);
  });
  // the ring passing in front of the planet: a gap in the colour behind the planet (only over the planet), then the ring
  const cut = svg("ellipse", { ...ellipse, class: "sp-cut", stroke: C.lit },
    svg("g", { "clip-path": "url(#spFront)" }, svg("g", { transform: tilt }, svg("g", { "clip-path": "url(#spDisc)" }, mark))));
  draw.push(cut, svg("ellipse", { ...ellipse, class: "sp-ring" }, svg("g", { "clip-path": "url(#spFront)" }, svg("g", { transform: tilt }, mark))));
  const headOver = svg("circle", { class: "sp-head", r: 2.2 }, mark);
  const word = html("sp-word", box);
  const letters = [..."VerseForge"].map((ch) => { const s = document.createElement("span"); s.textContent = ch; word.appendChild(s); return s; });

  // ---------------------------------------------------------------- the timeline (milliseconds)
  const anims = [];
  const tw = (els, kf, o) => [].concat(els).forEach((el) => anims.push(el.animate(kf, { fill: "both", easing: E.out, ...o })));
  const T0 = 120, STEP = 150, LAY = 135, RING_AT = T0 + 4 * STEP + LAY + 110, RING = 720, END = RING_AT + RING + 500;
  const sounds = [];                      // [time, play(when)] for the sound, scheduled once it is known to be wanted and allowed
  const path = [];                        // the head: [time, x, y, easing to the next point]
  [4, 3, 2, 1, 0].forEach((li, k) => {
    const [y1, y2] = LAYERS[li], w = Math.max(half(y1), half(y2)), y = (y1 + y2) / 2, ltr = k % 2 === 0, st = T0 + k * STEP;
    const o = ltr ? "left center" : "right center", x0 = CX + (ltr ? -w : w), x1 = CX + (ltr ? w : -w);
    tw(layers[li], [{ transform: "scaleX(0)", transformOrigin: o }, { transform: "scaleX(1)", transformOrigin: o }], { delay: st, duration: LAY, easing: "linear" });
    tw(layers[li], [{ fill: C.hot }, { fill: C.planet }], { delay: st, duration: 620, easing: E.soft });
    path.push([st, x0, y, "linear"], [st + LAY, x1, y, E.inOut]);
    sounds.push([st, (snd) => snd.motor(st, LAY, k, x0, x1)]);
  });
  // the ring is not there at all before its turn (a dash pattern that ends exactly at the start leaves a speck there),
  // then it is drawn from its right end, the head leading
  const ringKf = [];
  for (let i = 0; i <= 40; i++) {
    const e = easeInOut(i / 40), p = ringPoint(e);
    ringKf.push({ strokeDashoffset: 1.05 * (1 - e) });
    path.push([RING_AT + RING * i / 40, p[0], p[1], "linear"]);
  }
  tw(draw, ringKf, { delay: RING_AT, duration: RING, easing: "linear" });
  tw(draw, [{ visibility: "hidden" }, { visibility: "visible" }], { delay: RING_AT, duration: 1, easing: "steps(1, start)" });
  sounds.push([RING_AT, (snd) => snd.sweep(RING_AT, RING)], [RING_AT + RING - 60, (snd) => snd.chime(RING_AT + RING - 60)]);
  // the head: over everything, then under the planet for the far half of the ring
  const d = RING_AT + RING - T0, headO = { delay: T0, duration: d, easing: "linear" }, sw = (RING_AT + RING / 2 - T0) / d;
  tw([headOver, headUnder], path.map(([t, x, y, easing]) => ({ transform: `translate(${x.toFixed(2)}px, ${y.toFixed(2)}px)`, offset: (t - T0) / d, easing })), headO);
  tw(headOver, [{ opacity: 0, offset: 0 }, { opacity: 1, offset: .04 }, { opacity: 1, offset: sw }, { opacity: 0, offset: sw + .0005 }, { opacity: 0, offset: 1 }], headO);
  tw(headUnder, [{ opacity: 0, offset: 0 }, { opacity: 0, offset: sw }, { opacity: 1, offset: sw + .0005 }, { opacity: 1, offset: .93 }, { opacity: 0, offset: 1 }], headO);
  // the glow behind (the gap of the ring follows its colour), then the name, letter by letter
  tw(glow, [{ opacity: 0 }, { opacity: 1 }], { delay: RING_AT - 100, duration: 1200, easing: E.soft });
  tw(cut, [{ stroke: C.bg }, { stroke: C.lit }], { delay: RING_AT - 100, duration: 1200, easing: E.soft });
  letters.forEach((el, i) => tw(el, [{ transform: "translateY(115%)", opacity: 0 }, { transform: "none", opacity: 1 }], { delay: RING_AT + 180 + i * 26, duration: 720 }));
  tw(word, [{ letterSpacing: ".06em" }, { letterSpacing: "-.01em" }], { delay: RING_AT + 180, duration: 1100 });

  // ---------------------------------------------------------------- the end: the window fades in under it
  const started = performance.now();
  let leaving = false, audio = null;
  function leave(fast) {
    if (leaving) return;
    leaving = true;
    clearTimeout(timer);
    removeEventListener("keydown", skip, true);
    root.style.pointerEvents = "none";
    if (audio && fast) audio.hush();
    box.animate([{ transform: "none" }, { transform: "scale(1.06)" }], { duration: fast ? 260 : 520, easing: E.in, fill: "both" });
    root.animate([{ opacity: 1 }, { opacity: 0 }], { duration: fast ? 260 : 520, easing: E.in, fill: "both" }).finished
      .catch(() => { /* cancelled: remove it anyway */ }).then(() => root.remove());
  }
  const skip = () => leave(true);
  const timer = setTimeout(() => leave(false), END + 200);
  root.addEventListener("pointerdown", skip);
  addEventListener("keydown", skip, true);

  // ---------------------------------------------------------------- the sound
  // stepper-motor notes rising with the layers (D minor pentatonic), air round the ring, a soft bell on D at the end
  function makeSound(ctx) {
    const NOTES = [146.83, 174.61, 196.00, 220.00, 261.63];
    const out = ctx.createGain(), bus = ctx.createGain();
    const dl = ctx.createDelay(.5), fb = ctx.createGain(), wet = ctx.createGain(), lp = ctx.createBiquadFilter();     // a little room
    dl.delayTime.value = .12; fb.gain.value = .3; wet.gain.value = .2; lp.type = "lowpass"; lp.frequency.value = 2400;
    out.connect(ctx.destination); out.connect(dl); dl.connect(lp); lp.connect(fb); fb.connect(dl); lp.connect(wet); wet.connect(ctx.destination);
    bus.connect(out);
    const noise = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate), ch = noise.getChannelData(0);
    for (let i = 0; i < ch.length; i++) ch[i] = Math.random() * 2 - 1;
    const base = ctx.currentTime - (performance.now() - started) / 1000, at = (ms) => base + ms / 1000;
    const pan = (x) => Math.max(-1, Math.min(1, (x - CX) / 45));
    return {
      hush() { out.gain.setTargetAtTime(0, ctx.currentTime, .03); },
      // the head laying a layer: the note of a stepper motor, moving with the head
      motor(ms, durMs, step, x0, x1) {
        const t = at(ms), dur = durMs / 1000, f = NOTES[step], g = ctx.createGain(), p = ctx.createStereoPanner(), f1 = ctx.createBiquadFilter();
        f1.type = "lowpass"; f1.frequency.value = 1500; f1.Q.value = 2;
        [["sawtooth", 1, .11], ["square", 2.005, .035]].forEach(([type, mul, level]) => {
          const o = ctx.createOscillator(), og = ctx.createGain(); o.type = type; og.gain.value = level;
          o.frequency.setValueAtTime(f * mul * .96, t); o.frequency.exponentialRampToValueAtTime(f * mul, t + dur * .35);
          o.connect(og); og.connect(f1); o.start(t); o.stop(t + dur + .02);
        });
        g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(1, t + .008);
        g.gain.setValueAtTime(1, t + dur - .03); g.gain.linearRampToValueAtTime(0, t + dur);
        p.pan.setValueAtTime(pan(x0), t); p.pan.linearRampToValueAtTime(pan(x1), t + dur);
        f1.connect(g); g.connect(p); p.connect(bus);
      },
      // the head running round the ring: air and a rising tone, right to left in front and back again behind
      sweep(ms, durMs) {
        const t = at(ms), dur = durMs / 1000, src = ctx.createBufferSource(), bp = ctx.createBiquadFilter(), g = ctx.createGain(), p = ctx.createStereoPanner();
        src.buffer = noise; src.loop = true; bp.type = "bandpass"; bp.Q.value = 1.4;
        bp.frequency.setValueAtTime(500, t); bp.frequency.exponentialRampToValueAtTime(2600, t + dur * .55); bp.frequency.exponentialRampToValueAtTime(900, t + dur);
        g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(.2, t + dur * .5); g.gain.linearRampToValueAtTime(0, t + dur);
        p.pan.setValueAtTime(.7, t); p.pan.linearRampToValueAtTime(-.7, t + dur * .5); p.pan.linearRampToValueAtTime(.7, t + dur);
        src.connect(bp); bp.connect(g); g.connect(p); p.connect(bus); src.start(t); src.stop(t + dur + .02);
        const o = ctx.createOscillator(), og = ctx.createGain(); o.type = "triangle";
        o.frequency.setValueAtTime(293.66, t); o.frequency.exponentialRampToValueAtTime(587.33, t + dur);
        og.gain.setValueAtTime(0, t); og.gain.linearRampToValueAtTime(.07, t + dur * .6); og.gain.linearRampToValueAtTime(0, t + dur);
        o.connect(og); og.connect(p); o.start(t); o.stop(t + dur + .02);
      },
      // the logo is whole: a soft bell with a low body under it
      chime(ms) {
        const t = at(ms);
        [[587.33, .13, 1.5], [880, .07, 1.1], [1174.66, .035, .8]].forEach(([f, level, decay]) => {
          const o = ctx.createOscillator(), g = ctx.createGain(); o.frequency.value = f;
          g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(level, t + .006); g.gain.exponentialRampToValueAtTime(.0001, t + decay);
          o.connect(g); g.connect(bus); o.start(t); o.stop(t + decay + .05);
        });
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.frequency.setValueAtTime(110, t); o.frequency.exponentialRampToValueAtTime(73.42, t + .25);
        g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(.16, t + .01); g.gain.exponentialRampToValueAtTime(.0001, t + .5);
        o.connect(g); g.connect(bus); o.start(t); o.stop(t + .6);
      },
    };
  }
  (async () => {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    const wait = (ms) => new Promise((r) => setTimeout(r, ms));
    // wanted? (the setting lives with the others on the server; no answer in time = no sound)
    const wanted = await Promise.race([fetch("/api/status").then((r) => r.json()).then((s) => s.start_sound !== false, () => false), wait(400).then(() => false)]);
    if (!wanted || leaving) return;
    // allowed? a page may play without a click only where the window lets it; otherwise the context never starts,
    // and it is closed so that nothing plays late, at the first click
    const ctx = new Ctx();
    await Promise.race([ctx.resume().catch(() => { /* not allowed */ }), wait(300)]);
    if (ctx.state !== "running" || leaving) { ctx.close(); return; }
    audio = makeSound(ctx);
    const now = performance.now() - started + 30;
    sounds.forEach(([t, play]) => { if (t >= now) play(audio); });
    setTimeout(() => ctx.close(), END + 2500);
  })().catch(() => { /* no sound: the animation does not depend on it */ });
})();
