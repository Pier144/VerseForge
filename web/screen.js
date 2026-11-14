// Weapon ammo display. In the game the screens are drawn live by the UI; here the weapon's DisplayScreen gets a
// canvas with the magazine count (capacity from the game data), which the Fire and Reload animations change.
import * as THREE from "three";

const FONT = '"Bahnschrift SemiCondensed", "Bahnschrift", "Segoe UI", sans-serif';
const WARN = "#ff8a3d";

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
    for (const m of meshes) {
      m.material = m.material.clone();
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
  }
}

// which actions shoot and which reload (names come from the game: Fire, Fire Last, Reload Full/Empty...)
export const isFire = (a) => /fire|shoot|trigger/i.test(a.group) && !/reload/i.test(a.group);
export const isReload = (a) => /reload/i.test(a.group) || /reload/i.test(a.label);
