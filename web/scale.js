// Scale references: what tells how big the model is, and dresses the floor around it.
//  - "ruler": a ruler on the floor, drawn like a technical drawing: thin lines with ticks along the model's length and
//    width, the numbers and the totals written flat on the floor, turned towards the default camera (at -x, -z), and
//    a staff for the height with its value at its foot
//  - "pilot": a pilot from the game standing by the nose, his height written beside him
//  - "scene": a hangar floor in use, with things from the game: an ordnance area (missiles, torpedoes, ammunition),
//    a cargo area (boxes, containers, a forklift) and a tools corner, each a tidy group, drawn to a side of the model
//    (the same way for the same model, until shuffled), and work lights in mirrored pairs turned to the hull
// Everything sits on the model's floor (the bottom of its box) and is rebuilt when the model or the choice changes.
import * as THREE from "three";

export const SCALE_IDS = ["ruler", "pilot", "scene"];

const PILOT = "Objects/props/flair/flightsuit_locker/m_rsi_explorer_light_01_merged.cgf";
const B = "Objects/buildingsets/human/";
const CARGO = B + "lowtech/prop/storage/cargo/";
const LAMPS = [
  B + "common/light/work/tripod/set_a/common_light_work_tripod_set_a_assembled_a.cgf",
  B + "common/light/work/tripod/set_a/common_light_work_tripod_set_a_assembled_b.cgf",
];
// What the scene is made of: three working areas, each a few rows of things that belong together, the low ones
// towards the model. An entry is one thing: p its model, n how many side by side (a number, or [min, max]), turn: a
// quarter turn (long things lie along the row), set: several of it as one (stack: a block of boxes two wide with
// more on top, line: spaced in a line), spin: parked at whatever angle, more: one more of it every so many metres of
// model (bigger ships get bigger areas).
const P = {
  scu1: CARGO + "cargo_exp_1_125x125x125_a.cgf", scu2: CARGO + "cargo_liquid_2SCU_1_a.cgf",
  scu8: CARGO + "cargo_liquid_8SCU_1_a.cgf", scu32: CARGO + "cargo_liquid_32SCU_1_a.cgf",
  forklift: B + "universal/prop/uee/forklift/forklift_machine_1_a.cgf",
  stacker: B + "universal/prop/uee/forklift/forklift_standing_1_a.cgf",
  trolley: B + "universal/prop/machine/trolley/trolley_pallet_powered_1_a.cgf",
  missilesL: B + "lowtech/charlie/int/prop/uee_lawless_prop_missilestack_large.cgf",
  missilesM: B + "lowtech/charlie/int/prop/uee_lawless_prop_missilestack_medium.cgf",
  torpedo: "Objects/Spaceships/Ammo/Torpedoes/TALN/TALN_Argos_S9.cga",
  ammo: B + "lowtech/charlie/int/prop/uee_lawless_prop_ammocrate_01.cgf",
  toolcart: B + "lowtech/charlie/int/prop/uee_lawless_prop_toolcart.cgf",
  chest: B + "shop/alpha/shippart/dumpersdepot/prop/prop_dumper_int_tool_chest_a.cgf",
  bench: B + "lowtech/prop/workbench/workbench_mobile_1_a.cgf",
  ladder: B + "hightech/prop/maintenance/ladder/ladder_mobile_1_a.cgf",
  barrel: B + "lowtech/prop/furniture/barrel/barrel_a.cgf",
  cone: B + "universal/prop/maintenance/cone_1_a.cgf",
  barrier: B + "lowtech/prop/barrier/barrier_foldable_1_a.cgf",
};
const ZONES = {
  // ordnance: missiles and torpedoes laid out to be loaded, ammunition beside them, coned off
  ordnance: [
    [{ p: P.cone, set: { n: [4, 6], line: true } }, { p: P.ammo, n: [2, 3] }, { p: P.missilesM, n: [2, 3], more: 40 }],
    [{ p: P.missilesL, n: [2, 3], more: 30 }, { p: P.torpedo, n: [1, 2], turn: 1, more: 50 }],
  ],
  // cargo: boxes stacked by size, the containers behind them, a forklift and a pallet truck at work
  cargo: [
    [{ p: P.scu1, set: { n: [4, 6], stack: true } }, { p: P.scu1, set: { n: [3, 5], stack: true }, more: 40 },
      { p: P.scu2, n: [1, 2] }, { p: P.trolley, spin: 0.5 }, { p: P.forklift, spin: 0.7 }],
    [{ p: P.scu32, turn: 1, more: 45 }, { p: P.scu8, n: [1, 2], more: 60 }],
  ],
  // tools: the mechanics' corner
  tools: [
    [{ p: P.barrel, set: { n: [2, 3] } }, { p: P.toolcart }, { p: P.chest }, { p: P.bench }],
    [{ p: P.ladder, turn: 1 }, { p: P.stacker, spin: 0.4 }, { p: P.barrier, set: { n: [1, 2], line: true } }],
  ],
};
const SCENERY = [...new Set(Object.values(P))].map((path) => ({ path }));

const STEPS = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500];
const INK = {                      // lines, tick numbers, totals: on a dark floor and on a light one
  light: { line: 0x6fb6ff, num: "#9cc9f5", text: "#d6ebff" },
  dark: { line: 0x1d4f86, num: "#27507c", text: "#12304f" },
};
const FONT = "system-ui, 'Segoe UI', sans-serif";
const SPOTS = [0xffd9a8, 0xcfe0ff];           // the two work lights that really light the hull: warm and cool

// seeded random numbers: the same model gets the same scene every time
function rng(text) {
  let h = 1779033703 ^ text.length;
  for (let i = 0; i < text.length; i++) { h = Math.imul(h ^ text.charCodeAt(i), 3432918353); h = (h << 13) | (h >>> 19); }
  return () => {
    h = Math.imul(h ^ (h >>> 16), 2246822507); h = Math.imul(h ^ (h >>> 13), 3266489909);
    return ((h ^= h >>> 16) >>> 0) / 4294967296;
  };
}

function glowTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 256;
  const g = c.getContext("2d"), r = g.createRadialGradient(128, 128, 0, 128, 128, 128);
  r.addColorStop(0, "rgba(255,255,255,1)"); r.addColorStop(0.25, "rgba(255,255,255,.45)"); r.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = r; g.fillRect(0, 0, 256, 256);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

export class ScaleRefs {
  constructor(scene, { loadProp, onChange }) {
    this.group = new THREE.Group();
    this.group.name = "__scale__";
    this.core = new THREE.Group();        // ruler and pilot: what Frame keeps in view
    this.dress = new THREE.Group();       // the scene around
    this.group.add(this.core, this.dress);
    scene.add(this.group);
    // The work lights that reach the hull. They stay in the scene for good, dark when the scene is off: adding or
    // removing a light changes every shader of the model and has them all compiled again (a stall on big ships).
    this.spots = SPOTS.map((color, i) => {
      const s = new THREE.SpotLight(color, 0, 0, 0.85, 0.8, 0);
      s.name = `__work_light_${i}__`;
      s.castShadow = false;
      scene.add(s, s.target);
      return s;
    });
    this.loadProp = loadProp;      // async (path) -> Object3D of a game object (shared: cloned here)
    this.onChange = onChange;      // something was drawn or changed
    this.on = new Set();           // of SCALE_IDS
    this.box = null;
    this.dark = false;             // dark ink, for light floors
    this.key = "";                 // what the scene's random numbers start from (the model's path)
    this.salt = 0;                 // shuffled so many times
    this.generation = 0;
    this.boxes = new Map();        // path -> box of the loaded game object
    this.glow = glowTexture();
  }

  get active() { return this.on.size > 0; }

  // what frames the picture: the model with the ruler and the pilot (the scene around is left to chance)
  bounds() {
    if (!this.box || !this.core.children.length) return null;
    this.core.updateMatrixWorld(true);
    const b = new THREE.Box3().setFromObject(this.core);
    return b.isEmpty() ? null : b.union(this.box);
  }

  set(id, on) {
    if (on) this.on.add(id); else this.on.delete(id);
    return this.build();
  }

  shuffle() {
    this.salt++;
    return this.build();
  }

  // box: the model as it is drawn (metres, y up); dark: the floor is light; key: the model
  fit(box, dark = this.dark, key = this.key) {
    this.box = box && !box.isEmpty() ? box.clone() : null;
    this.dark = dark;
    this.key = key;
    return this.build();
  }

  clear() {
    for (const part of [this.core, this.dress]) {
      for (const o of [...part.children]) {
        part.remove(o);
        o.traverse((m) => {
          if (m.userData.prop || !(m.isMesh || m.isSprite)) return;      // game objects share geometry and materials
          if (m.isMesh) m.geometry.dispose();
          if (m.material.map !== this.glow) m.material.map?.dispose();
          m.material.dispose();
        });
      }
    }
    for (const s of this.spots) s.intensity = 0;
  }

  async load(path) {
    const o = await this.loadProp(path).catch(() => null);      // missing in this game version: one thing less
    if (o && !this.boxes.has(path)) this.boxes.set(path, new THREE.Box3().setFromObject(o));
    return o;
  }

  copy(src) {
    const o = src.clone(true);
    o.traverse((m) => { if (m.isMesh) { m.userData.prop = true; m.castShadow = true; m.receiveShadow = true; } });
    return o;
  }

  async build() {
    const gen = ++this.generation;
    this.clear();
    if (!this.box || !this.active) { this.onChange?.(); return; }
    const box = this.box, size = box.getSize(new THREE.Vector3()), mid = box.getCenter(new THREE.Vector3());
    const big = Math.max(size.x, size.y, size.z, 0.001);
    const lay = this.layout(box, size, big);
    if (this.on.has("ruler")) this.ruler(box, size, mid, big, lay);
    this.onChange?.();
    if (this.on.has("pilot")) {
      const src = await this.load(PILOT);
      if (gen !== this.generation) return;
      if (src) this.pilot(src, box, big, lay);
      this.onChange?.();
    }
    if (this.on.has("scene") && big >= 2.5) {             // nothing to dress around a rifle
      const paths = [...SCENERY.map((s) => s.path), ...LAMPS];
      const loaded = await Promise.all(paths.map((p) => this.load(p)));
      if (gen !== this.generation) return;
      this.scenery(new Map(paths.map((p, i) => [p, loaded[i]])), box, size, mid, big, lay);
      this.onChange?.();
    }
  }

  // the measures everything is placed by
  layout(box, size, big) {
    const off = big * 0.08, tk = off * 0.2, hn = big * 0.036, ht = big * 0.075;
    const band = tk + hn * 1.7 + ht * 1.4;               // how far the writing reaches outside a ruler line
    // the pilot stands between the nose and the width ruler when he fits there (about 0.6 m deep, 0.4 m clear of
    // both); in front of a small vehicle there is no room (Cyclone: he stood 0.23 m from the nose, touching its
    // wheel, his height written over the ruler): he stands beyond the ruler's writing instead
    const pz = off >= 1.4 ? box.min.z - Math.min(Math.max(0.7, off * 0.45), 1.2) : box.min.z - off - band - 0.8;
    return { off, tk, hn, ht, fine: big * 0.0028, xl: box.min.x - off, zf: box.min.z - off, zb: box.max.z + off * 0.5, band,
      pilot: new THREE.Vector3((box.min.x + box.max.x) / 2 - Math.max(1.2, size.x * 0.22), box.min.y, pz) };
  }

  textSize(big) { return Math.min(1.6, Math.max(0.45, big * 0.03)); }

  pilot(src, box, big, lay) {
    const b = this.boxes.get(PILOT), s = b.getSize(new THREE.Vector3()), at = lay.pilot, y0 = box.min.y;
    const o = this.copy(src);
    o.position.set(at.x - (b.min.x + b.max.x) / 2, y0 - b.min.y, at.z - (b.min.z + b.max.z) / 2);
    this.core.add(o);
    const ink = INK[this.dark ? "dark" : "light"], h = this.textSize(big);
    // his height beside him, on the camera's side
    this.text(this.len(s.y), new THREE.Vector3(at.x - s.x / 2 - h * 1.9, y0, at.z), Math.PI, h, ink.text, big);
    if (big > 40) {               // a ring on the floor finds the pilot next to a capital ship
      const r = Math.max(0.9, big * 0.02);
      const ring = new THREE.Mesh(new THREE.RingGeometry(r * 0.93, r, 64), this.flat(ink.line));
      ring.rotation.x = -Math.PI / 2;
      ring.position.set(at.x, y0 + big * 0.0012, at.z);
      this.core.add(ring);
    }
  }

  // ------------------------------------------------------------------ the scene around the model
  scenery(props, box, size, mid, big, lay) {
    const rnd = rng(`${this.key}#${this.salt}`), y0 = box.min.y, taken = [];
    const margin = Math.max(1.5, big * 0.05);
    const pick = (a, b) => a + rnd() * (b - a);
    // where nothing may stand ([x0, x1, z0, z1]): the model's footprint, the rulers with their writing, the pilot
    const keep = [
      [box.min.x - margin, box.max.x + margin, box.min.z - margin, box.max.z + margin],
      [lay.xl - lay.band, lay.xl + lay.tk * 2, box.min.z - lay.off, lay.zb + lay.ht * 4],
      [box.min.x - lay.off, box.max.x + lay.off, lay.zf - lay.band, lay.zf + lay.tk * 2],
      [lay.pilot.x - 3, lay.pilot.x + 1.5, lay.pilot.z - 1.5, lay.pilot.z + 1.5],
    ];
    const apart = (a, b, gap) => a[1] + gap < b[0] || a[0] - gap > b[1] || a[3] + gap < b[2] || a[2] - gap > b[3];
    const free = (r) => keep.every((k) => apart(r, k, 0)) && taken.every((k) => apart(r, k, 0.5));

    // Work lights: in pairs, mirrored across the model's long axis and evenly spaced along it, just outside the
    // rulers on both sides, each turned to the model. The front pair lights what the default camera sees.
    const lamps = LAMPS.filter((p) => props.get(p)), heads = [];
    const out = lay.off + lay.band + 1.5, pairs = lamps.length ? Math.min(6, Math.max(2, Math.round(size.z / 14))) : 0;
    for (let i = 0; i < pairs; i++) {
      const path = lamps[i % lamps.length], b = this.boxes.get(path), s = b.getSize(new THREE.Vector3());
      const z = box.min.z + (i + 0.5) / pairs * size.z;
      for (const side of [-1, 1]) {
        const x = side < 0 ? box.min.x - out : box.max.x + out;
        const o = this.copy(props.get(path)), turn = new THREE.Group();
        o.position.set(-(b.min.x + b.max.x) / 2, y0 - b.min.y, -(b.min.z + b.max.z) / 2);
        turn.add(o);
        turn.rotation.y = Math.atan2(mid.x - x, mid.z - z) + Math.PI;      // the lamps' front is their -z
        turn.position.set(x, 0, z);
        this.dress.add(turn);
        taken.push([x - 0.8, x + 0.8, z - 0.8, z + 0.8]);
        heads.push({ x, z, y: y0 + s.y * 0.88, side, i });
        this.lampGlow(heads[heads.length - 1], mid, y0, big);
      }
    }
    this.spots.forEach((sp, n) => {
      const h = heads.find((q) => q.i === 0 && q.side === (n ? 1 : -1));
      if (!h) return;
      sp.position.set(h.x, h.y, h.z);
      sp.target.position.set(mid.x, box.min.y + size.y * 0.45, mid.z);
      sp.target.updateMatrixWorld();
      sp.intensity = this.dark ? 0.9 : 2.0;
    });

    // The working areas: on the far side of the model and behind it (the default camera looks from the front left),
    // each parallel to the side it stands by, its low things towards the model. Which area goes where is drawn.
    const slots = [{ side: "right", t: 0.27 }, { side: "right", t: 0.75 }, { side: "rear", t: 0.3 }, { side: "rear", t: 0.72 }];
    for (let n = slots.length - 1; n > 0; n--) { const k = Math.floor(rnd() * (n + 1)); [slots[n], slots[k]] = [slots[k], slots[n]]; }
    Object.keys(ZONES).forEach((name, n) => {
      const zone = this.zone(ZONES[name], props, y0, big, rnd), slot = slots[n];
      if (!zone) return;
      const right = slot.side === "right", w = right ? zone.d : zone.w, d = right ? zone.w : zone.d;      // on the floor
      for (let tries = 0; tries < 24; tries++) {
        // first where it was drawn, then sliding along the side, then a step further out
        const t = Math.min(0.95, Math.max(0.05, slot.t + [0, 0.12, -0.12, 0.24, -0.24, 0.36][tries % 6] + pick(-0.03, 0.03)));
        const far = margin + 0.8 + Math.floor(tries / 6) * 2.5;
        const x = right ? box.max.x + far + w / 2 : box.min.x + t * size.x;
        const z = right ? box.min.z + t * size.z : box.max.z + far + d / 2;
        const r = [x - w / 2, x + w / 2, z - d / 2, z + d / 2];
        if (!free(r)) continue;
        zone.obj.rotation.y = right ? Math.PI / 2 : 0;       // its front (-z) towards the model
        zone.obj.position.set(x, 0, z);
        this.dress.add(zone.obj);
        taken.push(r);
        break;
      }
    });
  }

  // one working area: its rows laid out side by side, front row first; { obj, w, d } centred on its origin, front at -z
  zone(rows, props, y0, big, rnd) {
    const inner = new THREE.Group(), box = new THREE.Box3(), one = new THREE.Box3();
    let z = 0;
    for (const row of rows) {
      let x = 0, depth = 0;
      for (const item of row) {
        const src = props.get(item.p);
        if (!src) continue;
        const [lo, hi] = Array.isArray(item.n) ? item.n : [item.n || 1, item.n || 1];
        const n = lo + Math.floor(rnd() * (hi - lo + 1)) + (item.more ? Math.floor(big / item.more) : 0);
        for (let k = 0; k < n; k++) {
          const o = this.cluster({ path: item.p, ...(item.set || {}) }, src, y0, rnd).obj;
          o.rotation.y = (item.turn || 0) * Math.PI / 2 + (rnd() - 0.5) * (item.spin ? item.spin * 2 : 0.06);
          o.updateMatrixWorld(true);
          one.setFromObject(o);
          o.position.x += x - one.min.x;
          o.position.z += z - one.min.z + (rnd() - 0.5) * 0.12;
          inner.add(o);
          x += one.max.x - one.min.x + 0.45;
          depth = Math.max(depth, one.max.z - one.min.z);
        }
        x += 0.5;                                  // a little more room between different things
      }
      z += depth + 0.9;
    }
    if (!inner.children.length) return null;
    inner.updateMatrixWorld(true);
    box.setFromObject(inner);
    inner.position.set(-(box.min.x + box.max.x) / 2, 0, -(box.min.z + box.max.z) / 2);
    const obj = new THREE.Group();
    obj.add(inner);
    return { obj, w: box.max.x - box.min.x, d: box.max.z - box.min.z };
  }

  // one thing, or a few of it together (stacked boxes, a line of cones); centred on its own origin
  cluster(kind, src, y0, rnd) {
    const b = this.boxes.get(kind.path), s = b.getSize(new THREE.Vector3()), obj = new THREE.Group();
    const n = kind.n ? kind.n[0] + Math.floor(rnd() * (kind.n[1] - kind.n[0] + 1)) : 1;
    const one = (x, y, z, yaw) => {
      const o = this.copy(src), t = new THREE.Group();
      o.position.set(-(b.min.x + b.max.x) / 2, -b.min.y, -(b.min.z + b.max.z) / 2);
      t.add(o);
      t.position.set(x, y0 + y, z);
      t.rotation.y = yaw;
      obj.add(t);
    };
    const gap = 0.12, stepX = s.x + gap, stepZ = s.z + gap;
    let rx = s.x / 2, rz = s.z / 2;
    if (kind.line) {
      const step = Math.max(s.x, s.z) * (s.x < 0.6 ? 3 : 1.15);
      for (let i = 0; i < n; i++) one((i - (n - 1) / 2) * step, 0, (rnd() - 0.5) * 0.15, (rnd() - 0.5) * 0.3);
      rx = step * n / 2;
    } else if (kind.stack) {
      // a block two wide, the last ones on top of the first
      const ground = Math.min(n, 4), cols = Math.min(2, ground), rows = Math.ceil(ground / cols);
      for (let i = 0; i < n; i++) {
        const j = i % ground, up = Math.floor(i / ground);
        one((j % cols - (cols - 1) / 2) * stepX + (rnd() - 0.5) * 0.06, up * s.y, (Math.floor(j / cols) - (rows - 1) / 2) * stepZ + (rnd() - 0.5) * 0.06, (rnd() - 0.5) * 0.08);
      }
      rx = cols * stepX / 2; rz = rows * stepZ / 2;
    } else {
      for (let i = 0; i < n; i++) one((i - (n - 1) / 2) * (stepX + 0.25), 0, (rnd() - 0.5) * 0.3, (rnd() - 0.5) * 0.5);
      rx = n * (stepX + 0.25) / 2;
    }
    return { obj, r: Math.hypot(rx, rz) };
  }

  // what a lit lamp looks like without costing a real light: a glare at its head and a pool of light on the floor
  lampGlow(head, mid, y0, big) {
    const warm = 0xffe6c0, k = this.dark ? 0.35 : 1;
    const glare = new THREE.Sprite(new THREE.SpriteMaterial({ map: this.glow, color: warm, blending: THREE.AdditiveBlending,
      transparent: true, opacity: 0.9 * k, depthWrite: false, fog: false }));
    glare.scale.setScalar(Math.max(1.6, big * 0.035));
    glare.position.set(head.x, head.y, head.z);
    this.dress.add(glare);
    const len = Math.min(16, Math.max(6, big * 0.3));
    const pool = new THREE.Mesh(new THREE.PlaneGeometry(len * 0.75, len),
      new THREE.MeshBasicMaterial({ map: this.glow, color: warm, blending: THREE.AdditiveBlending, transparent: true,
        opacity: 0.36 * k, depthWrite: false, fog: false }));
    pool.rotation.x = -Math.PI / 2;
    const turn = new THREE.Group(), dx = mid.x - head.x, dz = mid.z - head.z, d = Math.hypot(dx, dz) || 1;
    turn.rotation.y = Math.atan2(dx, dz);
    turn.position.set(head.x + dx / d * len * 0.38, y0 + big * 0.0008, head.z + dz / d * len * 0.38);
    turn.add(pool);
    this.dress.add(turn);
  }

  // ------------------------------------------------------------------ drawing
  // lengths as the panel writes them: metres, or millimetres for small things
  len(m) {
    if (m >= 10) return `${m.toFixed(1)} m`;
    if (m >= 1) return `${m.toFixed(2)} m`;
    return `${(m * 1000).toFixed(m >= 0.1 ? 0 : 1)} mm`;
  }

  flat(color, opacity = 1) {
    // solid ink writes depth: a see-through floor is drawn after it and must not cover it
    return new THREE.MeshBasicMaterial({ color, transparent: opacity < 1, opacity, depthWrite: opacity === 1, fog: false });
  }

  // a flat strip on the floor from a to b (post: as thick as wide, for what stands up)
  bar(a, b, t, mat, post = false) {
    const d = new THREE.Vector3().subVectors(b, a);
    const m = new THREE.Mesh(new THREE.BoxGeometry(t, post ? t : t * 0.25, d.length()), mat);
    m.position.copy(a).addScaledVector(d, 0.5);
    m.lookAt(b);
    this.core.add(m);
    return m;
  }

  // text lying on the floor; yaw turns it to who reads it (PI: from the front, -PI/2: from the left side)
  text(str, at, yaw, h, ink, big, weight = 600) {
    const c = document.createElement("canvas"), g = c.getContext("2d"), font = `${weight} 96px ${FONT}`;
    g.font = font;
    const w = Math.ceil(g.measureText(str).width) + 16;
    c.width = w; c.height = 128;
    g.font = font; g.fillStyle = ink; g.textBaseline = "middle"; g.fillText(str, 8, 68);
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = 16;
    const m = new THREE.Mesh(new THREE.PlaneGeometry(h * w / 128, h),
      new THREE.MeshBasicMaterial({ map: t, transparent: true, depthWrite: false, fog: false }));
    m.rotation.x = -Math.PI / 2;
    const turn = new THREE.Group();
    turn.rotation.y = yaw;
    turn.position.set(at.x, at.y + big * 0.0012, at.z);
    turn.add(m);
    this.core.add(turn);
    return turn;
  }

  ruler(box, size, mid, big, lay) {
    const ink = INK[this.dark ? "dark" : "light"], P = (x, y, z) => new THREE.Vector3(x, y, z);
    const mm = big < 1, step = STEPS.find((s) => big / s <= 12) || 1000, minor = step / 5;
    const { tk, hn, ht, fine, xl, zf, zb } = lay;
    const y0 = box.min.y, yl = y0 + big * 0.001;
    const line = this.flat(ink.line), faint = this.flat(ink.line, 0.4);
    const num = (d) => String(+(mm ? d * 1000 : d).toFixed(mm ? 0 : 1));
    const ticks = (len, each) => { for (let i = 0; i * minor <= len + 1e-9; i++) each(i * minor, i % 5 === 0); };

    // length: along the left side, 0 at the nose, read from the left
    this.bar(P(xl, yl, box.min.z), P(xl, yl, box.max.z), fine, line);
    for (const z of [box.min.z, box.max.z]) {
      this.bar(P(xl - tk * 1.6, yl, z), P(xl + tk * 1.6, yl, z), fine, line);
      this.bar(P(xl + tk * 1.6, yl, z), P(mid.x, yl, z), fine * 0.6, faint);
    }
    ticks(size.z, (d, major) => {
      this.bar(P(xl - (major ? tk : tk * 0.45), yl, box.min.z + d), P(xl, yl, box.min.z + d), fine * 0.8, line);
      if (major && d > 0 && size.z - d > step * 0.4) this.text(num(d), P(xl - tk - hn * 0.9, y0, box.min.z + d), -Math.PI / 2, hn, ink.num, big, 500);
    });
    this.text(this.len(size.z), P(xl - tk - hn * 1.7 - ht * 0.7, y0, mid.z), -Math.PI / 2, ht, ink.text, big);

    // width: in front of the nose, read from the front
    this.bar(P(box.min.x, yl, zf), P(box.max.x, yl, zf), fine, line);
    for (const x of [box.min.x, box.max.x]) {
      this.bar(P(x, yl, zf - tk * 1.6), P(x, yl, zf + tk * 1.6), fine, line);
      this.bar(P(x, yl, zf + tk * 1.6), P(x, yl, mid.z), fine * 0.6, faint);
    }
    ticks(size.x, (d, major) => {
      this.bar(P(box.max.x - d, yl, zf - (major ? tk : tk * 0.45)), P(box.max.x - d, yl, zf), fine * 0.8, line);
      if (major && d > 0 && size.x - d > step * 0.4) this.text(num(d), P(box.max.x - d, y0, zf - tk - hn * 0.9), Math.PI, hn, ink.num, big, 500);
    });
    this.text(this.len(size.x), P(mid.x, y0, zf - tk - hn * 1.7 - ht * 0.7), Math.PI, ht, ink.text, big);

    // height: a thin staff past the tail, its value written at its foot
    this.bar(P(xl, y0, zb), P(xl, box.max.y, zb), fine, line, true);
    ticks(size.y, (d, major) => this.bar(P(xl, y0 + d, zb), P(xl + (major ? tk : tk * 0.45), y0 + d, zb), fine * 0.8, line, true));
    this.bar(P(xl, box.max.y, zb), P(xl + tk * 1.6, box.max.y, zb), fine, line, true);
    this.text("↑ " + this.len(size.y), P(xl - tk - hn * 1.7 - ht * 0.7, y0, zb + ht * 1.2), -Math.PI / 2, ht, ink.text, big);
  }
}
