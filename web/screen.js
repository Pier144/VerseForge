// Weapon ammo display. In the game the screens are drawn live by the UI; here the weapon's DisplayScreen gets a
// canvas with the magazine count (capacity from the game data), which the Fire and Reload animations change.
import * as THREE from "three";

const FONT = '"Bahnschrift SemiCondensed", "Bahnschrift", "Segoe UI", sans-serif';
const WARN = "#ff8a3d";

// The screen classes draw on a clone of each screen's material. dispose() puts the mesh's own material back (also
// where the resin look keeps it, userData.gameMaterial) and frees the clone: a paint change rebuilds the screens with
// the new paint's glow (app.js afterPaint).
function cloneMaterials(meshes) {
  const originals = meshes.map((m) => m.material);
  for (const m of meshes) m.material = m.material.clone();
  return { originals, clones: meshes.map((m) => m.material) };
}
function restoreMaterials(meshes, { originals, clones }) {
  meshes.forEach((m, i) => {
    if (m.userData.gameMaterial === clones[i]) m.userData.gameMaterial = originals[i];
    else if (m.material === clones[i]) m.material = originals[i];
    clones[i].dispose();
  });
}

// world size of one unit of U and of V on the first triangle -> width / height of the screen
function aspectOf(mesh) {
  const g = mesh.geometry;
  const pos = g.attributes.position, uv = g.attributes.uv;
  const idx = g.index ? g.index.array : [0, 1, 2];
  const p = [0, 1, 2].map((k) => new THREE.Vector3().fromBufferAttribute(pos, idx[k]));
  const t = [0, 1, 2].map((k) => new THREE.Vector2().fromBufferAttribute(uv, idx[k]));
  const e1 = p[1].clone().sub(p[0]), e2 = p[2].clone().sub(p[0]);
  const d1 = t[1].clone().sub(t[0]), d2 = t[2].clone().sub(t[0]);
  const det = d1.x * d2.y - d2.x * d1.y;
  if (Math.abs(det) < 1e-9) return 1.6;
  const dPdu = e1.clone().multiplyScalar(d2.y).sub(e2.clone().multiplyScalar(d1.y)).divideScalar(det);
  const dPdv = e2.clone().multiplyScalar(d1.x).sub(e1.clone().multiplyScalar(d2.x)).divideScalar(det);
  const a = dPdu.length() / Math.max(dPdv.length(), 1e-9);
  return Math.min(Math.max(a, 0.25), 4);
}

export class AmmoScreen {
  constructor(meshes, ammo, look) {
    this.max = ammo.max;
    this.low = Math.max(1, Math.round(ammo.max * (ammo.low || 0.1)));
    this.count = ammo.max;
    this.accent = look?.accent || "#6ecdeb";
    this.maker = (look?.maker || "").toUpperCase();
    this.reloading = false;
    const aspect = aspectOf(meshes[0]);
    this.canvas = document.createElement("canvas");
    this.canvas.width = 512;
    this.canvas.height = Math.round(512 / aspect);
    this.texture = new THREE.CanvasTexture(this.canvas);
    this.texture.flipY = false;                    // glTF UVs: V grows downwards, like canvas Y
    this.texture.colorSpace = THREE.SRGBColorSpace;
    this.meshes = meshes;
    this.saved = cloneMaterials(meshes);
    for (const m of meshes) {
      m.material.emissiveMap = this.texture;
      m.material.emissive = new THREE.Color(0xffffff);
      m.material.emissiveIntensity = 1.4;
    }
    this.draw();
  }

  fire() {
    if (this.reloading) return;
    this.count = Math.max(0, this.count - 1);
    this.draw();
  }

  reload(seconds) {
    this.reloading = true;
    this.draw();
    clearTimeout(this.timer);
    this.timer = setTimeout(() => { this.reloading = false; this.count = this.max; this.draw(); }, seconds * 1000);
  }

  reset() {
    clearTimeout(this.timer);
    this.reloading = false;
    this.count = this.max;
    this.draw();
  }

  draw() {
    const c = this.canvas, g = c.getContext("2d"), W = c.width, H = c.height;
    const low = this.count <= this.low, col = low ? WARN : this.accent;
    g.fillStyle = "#000";
    g.fillRect(0, 0, W, H);
    // faint scanlines, like the game's screen glass
    g.fillStyle = "rgba(255,255,255,0.035)";
    for (let y = 0; y < H; y += 4) g.fillRect(0, y, W, 2);
    const pad = Math.round(H * 0.08);
    g.textBaseline = "alphabetic";
    // maker and state line
    g.fillStyle = this.accent;
    g.globalAlpha = 0.75;
    g.font = `600 ${Math.round(H * 0.13)}px ${FONT}`;
    g.textAlign = "left";
    g.fillText(this.maker, pad, pad + H * 0.12);
    g.textAlign = "right";
    g.fillStyle = col;
    const state = this.reloading ? "RELOADING" : this.count === 0 ? "EMPTY" : low ? "LOW AMMO" : "READY";
    g.fillText(state, W - pad, pad + H * 0.12);
    g.globalAlpha = 1;
    // big count and capacity
    const big = Math.round(H * 0.5);
    g.font = `700 ${big}px ${FONT}`;
    g.textAlign = "center";
    g.fillStyle = col;
    g.shadowColor = col;
    g.shadowBlur = H * 0.05;
    const text = this.reloading ? "--" : String(this.count).padStart(2, "0");
    g.fillText(text, W * 0.44, H * 0.68);
    const right = W * 0.44 + g.measureText(text).width / 2;
    g.shadowBlur = 0;
    g.font = `500 ${Math.round(H * 0.16)}px ${FONT}`;
    g.textAlign = "left";
    g.globalAlpha = 0.7;
    g.fillText(`/${this.max}`, right + pad * 0.4, H * 0.68);
    g.globalAlpha = 1;
    // one segment per round (grouped when the magazine is large)
    const n = Math.min(this.max, 30), per = this.max / n;
    const x0 = pad, x1 = W - pad, y = H - pad - H * 0.08, h = H * 0.08, gap = Math.max(2, (x1 - x0) * 0.008);
    const w = (x1 - x0 - gap * (n - 1)) / n;
    const lit = this.reloading ? 0 : Math.ceil(this.count / per);
    for (let i = 0; i < n; i++) {
      g.fillStyle = col;
      g.globalAlpha = i < lit ? 0.95 : 0.15;
      g.fillRect(x0 + i * (w + gap), y, w, h);
    }
    g.globalAlpha = 1;
    this.texture.needsUpdate = true;
  }

  dispose() {
    clearTimeout(this.timer);
    this.texture.dispose();
    restoreMaterials(this.meshes, this.saved);
  }
}

// which actions shoot and which reload (names come from the game: Fire, Fire Last, Reload Full/Empty...)
export const isFire = (a) => /fire|shoot|trigger/i.test(a.group) && !/reload/i.test(a.group);
export const isReload = (a) => /reload/i.test(a.group) || /reload/i.test(a.label);

// ---------------------------------------------------------------------------------------------------------------
// Ship screens. The game draws its dashboard monitors live, so the files hold no finished picture; they do hold the
// pieces the MFDs are built from (backgrounds, power triangle, frames: sc_explorer/screens.py picks the maker's set
// or the generic one). The pages below are drawn on those pieces. Every monitor of the ship takes one of four pages
// from a single atlas texture: its UVs are moved to the cell of its page and shape.
const PAGES = ["status", "power", "radar", "target"];
const SHAPES = [{ w: 512, h: 288 }, { w: 512, h: 384 }, { w: 384, h: 512 }];   // wide, 4:3, tall
const CELL = 512;

function loadImage(path) {
  return new Promise((resolve) => {
    if (!path) return resolve(null);
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = `/api/texture?path=${encodeURIComponent(path)}&size=512`;
  });
}

// the generic set is white on clear: it takes the screen's colour
function tinted(img, colour) {
  const c = document.createElement("canvas");
  c.width = img.width;
  c.height = img.height;
  const g = c.getContext("2d");
  g.drawImage(img, 0, 0);
  g.globalCompositeOperation = "source-in";
  g.fillStyle = colour;
  g.fillRect(0, 0, c.width, c.height);
  return c;
}

// the separate monitors inside one mesh (the server merges all screens that share a material)
function islands(geometry) {
  const pos = geometry.attributes.position, n = pos.count;
  const parent = new Int32Array(n), first = new Map();
  for (let i = 0; i < n; i++) {
    const k = `${Math.round(pos.getX(i) * 1e4)},${Math.round(pos.getY(i) * 1e4)},${Math.round(pos.getZ(i) * 1e4)}`;
    if (first.has(k)) parent[i] = first.get(k);
    else { first.set(k, i); parent[i] = i; }
  }
  const find = (i) => { while (parent[i] !== i) { parent[i] = parent[parent[i]]; i = parent[i]; } return i; };
  const idx = geometry.index ? geometry.index.array : Array.from({ length: n }, (_, i) => i);
  for (let t = 0; t + 2 < idx.length; t += 3) {
    const a = find(idx[t]);
    parent[find(idx[t + 1])] = a;
    parent[find(idx[t + 2])] = a;
  }
  const groups = new Map();
  for (let i = 0; i < n; i++) {
    const r = find(i);
    if (!groups.has(r)) groups.set(r, []);
    groups.get(r).push(i);
  }
  return [...groups.values()];
}

export class ShipScreens {
  constructor(meshes, look, ship) {
    this.accent = look?.kit?.accent || look?.accent || "#6ecdeb";
    this.maker = (look?.maker || "").toUpperCase();
    this.kit = look?.kit || {};
    this.ship = ship;
    this.canvas = document.createElement("canvas");
    this.canvas.width = CELL * PAGES.length;
    this.canvas.height = CELL * SHAPES.length;
    this.texture = new THREE.CanvasTexture(this.canvas);
    this.texture.flipY = false;
    this.texture.colorSpace = THREE.SRGBColorSpace;
    this.texture.anisotropy = 4;
    this.count = 0;
    this.meshes = meshes;
    for (const m of meshes) this.place(m);
    this.saved = cloneMaterials(meshes);
    for (const m of meshes) {
      m.material.emissiveMap = this.texture;
      m.material.emissive = new THREE.Color(0xffffff);
      m.material.emissiveIntensity = 1.25;
    }
    this.draw({});
    this.ready = Promise.all(["bg", "tri_fill", "tri_frame", "panel"].map((k) => loadImage(this.kit[k]))).then((imgs) => {
      if (this.disposed) return;
      const [bg, triFill, triFrame, panel] = imgs.map((img, i) =>
        img && /\/pu generic\/pu_/.test(this.kit[["bg", "tri_fill", "tri_frame", "panel"][i]] || "") && i > 0 ? tinted(img, this.accent) : img);
      this.draw({ bg, triFill, triFrame, panel });
    });
  }

  // move the UVs of every monitor of the mesh to its page in the atlas
  place(mesh) {
    const g = mesh.geometry, uv = g.attributes.uv, pos = g.attributes.position;
    const W = this.canvas.width, H = this.canvas.height;
    const p = new THREE.Vector3(), lo = new THREE.Vector3(), hi = new THREE.Vector3();
    const list = islands(g).map((verts) => {
      let u0 = Infinity, v0 = Infinity, u1 = -Infinity, v1 = -Infinity;
      lo.setScalar(Infinity);
      hi.setScalar(-Infinity);
      for (const i of verts) {
        u0 = Math.min(u0, uv.getX(i)); u1 = Math.max(u1, uv.getX(i));
        v0 = Math.min(v0, uv.getY(i)); v1 = Math.max(v1, uv.getY(i));
        p.fromBufferAttribute(pos, i);
        lo.min(p);
        hi.max(p);
      }
      return { verts, u0, v0, u1, v1, key: lo.x + hi.x + (lo.y + hi.y) * 0.37 + (lo.z + hi.z) * 0.11 };
    }).filter((s) => s.u1 - s.u0 > 1e-4 && s.v1 - s.v0 > 1e-4).sort((a, b) => a.key - b.key);
    for (const s of list) {
      // the world size of the monitor: lengths along U and along V over the island
      let du = 0, dv = 0;
      const a = s.verts[0];
      const pa = new THREE.Vector3().fromBufferAttribute(pos, a);
      for (const i of s.verts) {
        const d = p.fromBufferAttribute(pos, i).distanceTo(pa);
        const fu = Math.abs(uv.getX(i) - uv.getX(a)), fv = Math.abs(uv.getY(i) - uv.getY(a));
        if (fu > 1e-4 && fv < fu * 0.25) du = Math.max(du, d / fu);
        if (fv > 1e-4 && fu < fv * 0.25) dv = Math.max(dv, d / fv);
      }
      const aspect = du && dv ? (du * (s.u1 - s.u0)) / (dv * (s.v1 - s.v0)) : 4 / 3;
      const row = aspect > 1.55 ? 0 : aspect > 0.85 ? 1 : 2;
      const col = this.count++ % PAGES.length;
      const cell = SHAPES[row];
      for (const i of s.verts) {
        const nu = (uv.getX(i) - s.u0) / (s.u1 - s.u0), nv = (uv.getY(i) - s.v0) / (s.v1 - s.v0);
        uv.setXY(i, (col * CELL + nu * cell.w) / W, (row * CELL + nv * cell.h) / H);
      }
    }
    uv.needsUpdate = true;
  }

  draw(img) {
    const g = this.canvas.getContext("2d");
    g.fillStyle = "#000";
    g.fillRect(0, 0, this.canvas.width, this.canvas.height);
    SHAPES.forEach((cell, row) => PAGES.forEach((page, col) => {
      g.save();
      g.translate(col * CELL, row * CELL);
      g.beginPath();
      g.rect(0, 0, cell.w, cell.h);
      g.clip();
      this.page(g, page, cell.w, cell.h, img);
      g.restore();
    }));
    this.texture.needsUpdate = true;
  }

  page(g, page, W, H, img) {
    const col = this.accent, pad = Math.round(W * 0.05), u = Math.min(W, H) / 100;
    g.fillStyle = "#03070b";
    g.fillRect(0, 0, W, H);
    if (img.bg) { g.globalAlpha = 0.95; g.drawImage(img.bg, 0, 0, W, H); g.globalAlpha = 1; }
    g.fillStyle = "rgba(255,255,255,0.03)";
    for (let y = 0; y < H; y += 4) g.fillRect(0, y, W, 1);
    // header: page name, maker
    const title = { status: "SELF STATUS", power: "POWER", radar: "RADAR", target: "TARGET" }[page];
    g.textBaseline = "alphabetic";
    g.font = `600 ${Math.round(u * 6)}px ${FONT}`;
    g.fillStyle = col;
    g.textAlign = "left";
    g.fillText(`// ${title}`, pad, pad + u * 5);
    g.globalAlpha = 0.6;
    g.textAlign = "right";
    g.fillText(this.maker, W - pad, pad + u * 5);
    g.globalAlpha = 0.5;
    g.fillRect(pad, pad + u * 8, W - pad * 2, 1);
    g.globalAlpha = 1;
    const top = pad + u * 12, bottom = H - pad;
    if (page === "status") this.statusPage(g, pad, top, W - pad * 2, bottom - top, u, img);
    else if (page === "power") this.powerPage(g, pad, top, W - pad * 2, bottom - top, u, img);
    else if (page === "radar") this.radarPage(g, pad, top, W - pad * 2, bottom - top, u);
    else this.targetPage(g, pad, top, W - pad * 2, bottom - top, u, img);
  }

  statusPage(g, x, y, w, h, u) {
    const col = this.accent, [sx, sy, sz] = this.ship.size || [0, 0, 0];
    g.textAlign = "left";
    g.fillStyle = "#e9f6fb";
    g.font = `700 ${Math.round(u * 9)}px ${FONT}`;
    let name = (this.ship.name || "").toUpperCase();
    while (name.length > 4 && g.measureText(name).width > w) name = name.slice(0, -1);
    g.fillText(name, x, y + u * 8);
    g.fillStyle = col;
    g.globalAlpha = 0.7;
    g.font = `500 ${Math.round(u * 4.6)}px ${FONT}`;
    g.fillText(`L ${sy.toFixed(1)} m   W ${sx.toFixed(1)} m   H ${sz.toFixed(1)} m`, x, y + u * 15);
    g.globalAlpha = 1;
    const rows = [["HULL", 1], ["SHIELDS", 1], ["POWER", 0.82], ["COOLING", 0.64], ["H2 FUEL", 0.93], ["QT FUEL", 0.88]];
    const y0 = y + u * 22, step = Math.min((y + h - y0) / rows.length, u * 12), bar = Math.max(4, step * 0.34);
    g.font = `600 ${Math.round(Math.min(u * 5, step * 0.5))}px ${FONT}`;
    rows.forEach(([label, v], i) => {
      const yy = y0 + i * step;
      g.fillStyle = col;
      g.globalAlpha = 0.85;
      g.textAlign = "left";
      g.fillText(label, x, yy + bar);
      g.textAlign = "right";
      g.fillText(`${Math.round(v * 100)}%`, x + w, yy + bar);
      const bx = x + w * 0.3, bw = w * 0.52, n = 20, gap = 2, sw = (bw - gap * (n - 1)) / n;
      for (let k = 0; k < n; k++) {
        g.globalAlpha = k < Math.round(v * n) ? 0.95 : 0.15;
        g.fillRect(bx + k * (sw + gap), yy, sw, bar);
      }
      g.globalAlpha = 1;
    });
  }

  powerPage(g, x, y, w, h, u, img) {
    const col = this.accent, s = Math.min(w * 0.62, h * 0.86), cx = x + w * 0.4, cy = y + h * 0.5;
    if (img.triFill) { g.globalAlpha = 0.55; g.drawImage(img.triFill, cx - s / 2, cy - s / 2, s, s); g.globalAlpha = 1; }
    if (img.triFrame) g.drawImage(img.triFrame, cx - s / 2, cy - s / 2, s, s);
    else {
      g.strokeStyle = col;
      g.lineWidth = 2;
      g.beginPath();
      g.moveTo(cx, cy - s * 0.42);
      g.lineTo(cx + s * 0.46, cy + s * 0.38);
      g.lineTo(cx - s * 0.46, cy + s * 0.38);
      g.closePath();
      g.stroke();
    }
    g.fillStyle = "#e9f6fb";
    g.beginPath();
    g.arc(cx, cy + s * 0.1, u * 1.6, 0, Math.PI * 2);
    g.fill();
    g.fillStyle = col;
    g.font = `600 ${Math.round(u * 5)}px ${FONT}`;
    g.textAlign = "center";
    g.fillText("WPN", cx, cy - s * 0.46);
    g.textAlign = "left";
    g.fillText("SHD", cx - s * 0.5, cy + s * 0.5);
    g.textAlign = "right";
    g.fillText("ENG", cx + s * 0.5, cy + s * 0.5);
    // output column
    const bx = x + w * 0.8, bw = w * 0.2, n = 10, gap = 3, bh = (h * 0.8 - gap * (n - 1)) / n;
    g.textAlign = "left";
    g.globalAlpha = 0.8;
    g.fillText("OUTPUT", bx, y + u * 5);
    for (let k = 0; k < n; k++) {
      g.globalAlpha = n - k <= 8 ? 0.9 : 0.15;
      g.fillRect(bx, y + u * 8 + k * (bh + gap), bw, bh);
    }
    g.globalAlpha = 1;
  }

  radarPage(g, x, y, w, h, u) {
    const col = this.accent, r = Math.min(w, h) * 0.46, cx = x + w / 2, cy = y + h / 2;
    g.strokeStyle = col;
    g.lineWidth = 1.5;
    for (let k = 1; k <= 3; k++) {
      g.globalAlpha = 0.25 + k * 0.15;
      g.beginPath();
      g.arc(cx, cy, (r * k) / 3, 0, Math.PI * 2);
      g.stroke();
    }
    g.globalAlpha = 0.35;
    g.beginPath();
    g.moveTo(cx - r, cy); g.lineTo(cx + r, cy);
    g.moveTo(cx, cy - r); g.lineTo(cx, cy + r);
    g.stroke();
    // sweep
    const sweep = g.createConicGradient(-Math.PI * 0.75, cx, cy);
    sweep.addColorStop(0, "rgba(255,255,255,0)");
    sweep.addColorStop(0.12, col);
    sweep.addColorStop(0.121, "rgba(255,255,255,0)");
    g.globalAlpha = 0.35;
    g.fillStyle = sweep;
    g.beginPath();
    g.arc(cx, cy, r, 0, Math.PI * 2);
    g.fill();
    g.globalAlpha = 1;
    g.fillStyle = "#e9f6fb";
    g.beginPath();
    g.moveTo(cx, cy - u * 2.4); g.lineTo(cx + u * 1.8, cy + u * 2); g.lineTo(cx - u * 1.8, cy + u * 2);
    g.fill();
    g.fillStyle = col;
    for (const [dx, dy] of [[0.42, -0.3], [-0.55, 0.22], [0.18, 0.62]]) g.fillRect(cx + dx * r - u, cy + dy * r - u, u * 2, u * 2);
    g.font = `500 ${Math.round(u * 4.4)}px ${FONT}`;
    g.globalAlpha = 0.75;
    g.textAlign = "left";
    g.fillText("RNG 10 KM", x, y + h);
    g.textAlign = "right";
    g.fillText("3 CONTACTS", x + w, y + h);
    g.globalAlpha = 1;
  }

  targetPage(g, x, y, w, h, u, img) {
    const col = this.accent;
    const ph = Math.min(h * 0.36, w * 0.3);
    if (img.panel) g.drawImage(img.panel, x, y, w, ph);
    else { g.strokeStyle = col; g.globalAlpha = 0.6; g.strokeRect(x, y, w, ph); g.globalAlpha = 1; }
    g.fillStyle = "#e9f6fb";
    g.textAlign = "center";
    g.font = `700 ${Math.round(u * 8)}px ${FONT}`;
    g.fillText("NO TARGET", x + w / 2, y + ph / 2 + u * 3);
    g.fillStyle = col;
    g.textAlign = "left";
    g.font = `500 ${Math.round(u * 4.6)}px ${FONT}`;
    const rows = [["SCAN", "READY"], ["MISSILES", "SAFE"], ["WEAPONS", "ARMED"], ["COMMS", "OPEN"], ["QT DRIVE", "IDLE"]];
    const y0 = y + ph + u * 9, step = Math.min((y + h - y0) / (rows.length - 0.4), u * 9);
    rows.forEach(([k, v], i) => {
      const yy = y0 + i * step;
      if (yy > y + h) return;
      g.globalAlpha = 0.7;
      g.textAlign = "left";
      g.fillText(k, x, yy);
      g.globalAlpha = 1;
      g.textAlign = "right";
      g.fillText(v, x + w, yy);
      g.globalAlpha = 0.25;
      g.fillRect(x, yy + u * 2, w, 1);
      g.globalAlpha = 1;
    });
  }

  dispose() {
    this.disposed = true;
    this.texture.dispose();
    restoreMaterials(this.meshes, this.saved);
  }
}
