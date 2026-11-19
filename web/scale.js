// Scale references: what tells how big the model is.
//  - a ruler on the floor, drawn like a technical drawing: thin lines with ticks along the model's length and width,
//    the numbers and the totals written flat on the floor, turned towards the default camera (at -x, -z), and a staff
//    for the height with its value at its foot
//  - things from the game standing in a row in front of the model: a pilot, cargo boxes, a forklift, missiles…
// Everything sits on the model's floor (the bottom of its box) and is rebuilt when the model or the choice changes.
import * as THREE from "three";

const PROPS = "Objects/buildingsets/human/";
// in the row from the camera's side to the far one: the small ones in front, so the big ones never hide them
export const SCALE_ITEMS = [
  { id: "pilot", path: "Objects/props/flair/flightsuit_locker/m_rsi_explorer_light_01_merged.cgf", says: "height" },
  { id: "scu1", path: PROPS + "lowtech/prop/storage/cargo/cargo_exp_1_125x125x125_a.cgf", says: "1 SCU" },
  { id: "torpedo", path: "Objects/Spaceships/Ammo/Torpedoes/TALN/TALN_Argos_S9.cga", says: "length" },
  { id: "missiles", path: PROPS + "lowtech/charlie/int/prop/uee_lawless_prop_missilestack_large.cgf", says: "length" },
  { id: "forklift", path: PROPS + "universal/prop/uee/forklift/forklift_machine_1_a.cgf", says: "length" },
  { id: "scu32", path: PROPS + "lowtech/prop/storage/cargo/cargo_liquid_32SCU_1_a.cgf", says: "32 SCU" },
];
export const SCALE_IDS = ["ruler", ...SCALE_ITEMS.map((i) => i.id)];

const STEPS = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500];
const INK = {                      // lines, tick numbers, totals: on a dark floor and on a light one
  light: { line: 0x6fb6ff, num: "#9cc9f5", text: "#d6ebff" },
  dark: { line: 0x1d4f86, num: "#27507c", text: "#12304f" },
};
const FONT = "system-ui, 'Segoe UI', sans-serif";

export class ScaleRefs {
  constructor(scene, { loadProp, onChange }) {
    this.group = new THREE.Group();
    this.group.name = "__scale__";
    scene.add(this.group);
    this.loadProp = loadProp;      // async (path) -> Object3D of a game object (shared: cloned here)
    this.onChange = onChange;      // (arrived) something was drawn or changed; arrived: a game object came in later
    this.on = new Set();           // "ruler" and item ids
    this.box = null;
    this.dark = false;             // dark ink, for light floors
    this.generation = 0;
    this.sizes = new Map();        // item id -> its box size, once loaded
  }

  get active() { return this.on.size > 0; }

  // what frames the whole thing: the model's box and everything drawn around it
  bounds() {
    if (!this.active || !this.box) return null;
    this.group.updateMatrixWorld(true);
    const b = new THREE.Box3().setFromObject(this.group);
    return b.isEmpty() ? null : b.union(this.box);
  }

  set(id, on) {
    if (on) this.on.add(id); else this.on.delete(id);
    return this.build();
  }

  // box: the model as it is drawn (metres, y up); dark: the floor is light
  fit(box, dark = this.dark) {
    this.box = box && !box.isEmpty() ? box.clone() : null;
    this.dark = dark;
    return this.build();
  }

  clear() {
    for (const o of [...this.group.children]) {
      this.group.remove(o);
      o.traverse((m) => {
        if (!m.isMesh || m.userData.prop) return;      // game objects share their geometry and materials
        m.geometry.dispose();
        m.material.map?.dispose();
        m.material.dispose();
      });
    }
  }

  async build() {
    const gen = ++this.generation;
    this.clear();
    if (!this.box || !this.active) { this.onChange?.(false); return; }
    const box = this.box, size = box.getSize(new THREE.Vector3()), mid = box.getCenter(new THREE.Vector3());
    const big = Math.max(size.x, size.y, size.z, 0.001);
    const want = SCALE_ITEMS.filter((i) => this.on.has(i.id));
    // the row's place is kept from the sizes known so far: the ruler moves out of its way at once
    const row = this.row(want, box, big);
    if (this.on.has("ruler")) this.ruler(box, size, mid, big, row.depth);
    this.onChange?.(false);
    const loaded = await Promise.all(want.map((i) => this.loadProp(i.path).catch(() => null)));
    if (gen !== this.generation) return;
    let fresh = false;
    want.forEach((i, n) => {
      if (!loaded[n]) return;
      if (!this.sizes.has(i.id)) { this.sizes.set(i.id, new THREE.Box3().setFromObject(loaded[n])); fresh = true; }
    });
    if (fresh) return this.build();               // lay the row out again with the real sizes
    want.forEach((i, n) => { if (loaded[n]) this.stand(i, loaded[n], row.at.get(i.id), box, big); });
    this.onChange?.(true);
  }

  // where each item of the row stands: side by side in front of the nose, their backs on one line
  row(want, box, big) {
    const gap = 0.5, clear = Math.max(0.6, big * 0.04), at = new Map(), label = this.textSize(big) * 3.4;
    const sizes = want.map((i) => this.sizes.get(i.id)?.getSize(new THREE.Vector3()) || new THREE.Vector3(1, 2, 1));
    const slots = sizes.map((s) => Math.max(s.x, label));          // room for what is written in front of each
    const total = slots.reduce((w, s) => w + s, 0) + gap * Math.max(want.length - 1, 0);
    let x = (box.min.x + box.max.x) / 2 - total / 2, depth = 0;
    want.forEach((i, n) => {
      at.set(i.id, { x: x + slots[n] / 2, zBack: box.min.z - clear });
      x += slots[n] + gap;
      depth = Math.max(depth, sizes[n].z);
    });
    return { at, depth: want.length ? depth + clear + this.textSize(big) * 2.2 : 0 };
  }

  textSize(big) { return Math.min(1.6, Math.max(0.5, big * 0.03)); }

  stand(item, src, at, box, big) {
    const b = this.sizes.get(item.id), s = b.getSize(new THREE.Vector3()), y0 = box.min.y;
    const o = src.clone(true);
    o.traverse((m) => { if (m.isMesh) { m.userData.prop = true; m.castShadow = true; m.receiveShadow = true; } });
    o.position.set(at.x - (b.min.x + b.max.x) / 2, y0 - b.min.y, at.zBack - b.max.z);
    this.group.add(o);
    const ink = INK[this.dark ? "dark" : "light"], h = this.textSize(big), zFront = at.zBack - s.z;
    const says = item.says === "height" ? this.len(s.y) : item.says === "length" ? this.len(s.z) : item.says;
    this.text(says, new THREE.Vector3(at.x, y0, zFront - h * 0.9), Math.PI, h, ink.text, big);
    if (item.id === "pilot" && big > 40) {        // a ring on the floor finds the pilot next to a capital ship
      const r = Math.max(0.9, big * 0.02);
      const ring = new THREE.Mesh(new THREE.RingGeometry(r * 0.93, r, 64), this.flat(ink.line));
      ring.rotation.x = -Math.PI / 2;
      ring.position.set(at.x, y0 + big * 0.0012, at.zBack - s.z / 2);
      this.group.add(ring);
    }
  }

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

  // a flat strip on the floor from a to b (or a thin post when it goes up)
  bar(a, b, t, mat, post = false) {
    const d = new THREE.Vector3().subVectors(b, a);
    const m = new THREE.Mesh(new THREE.BoxGeometry(t, post ? t : t * 0.25, d.length()), mat);
    m.position.copy(a).addScaledVector(d, 0.5);
    m.lookAt(b);
    this.group.add(m);
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
    this.group.add(turn);
    return turn;
  }

  ruler(box, size, mid, big, rowDepth) {
    const ink = INK[this.dark ? "dark" : "light"], P = (x, y, z) => new THREE.Vector3(x, y, z);
    const mm = big < 1, step = STEPS.find((s) => big / s <= 12) || 1000, minor = step / 5;
    const off = big * 0.08, tk = off * 0.2, hn = big * 0.036, ht = big * 0.075, fine = big * 0.0028;
    const y0 = box.min.y, yl = y0 + big * 0.001;
    const xl = box.min.x - off, zf = box.min.z - off - rowDepth, zb = box.max.z + off * 0.5;
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

    // width: in front of the nose (beyond the row of game objects), read from the front
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
