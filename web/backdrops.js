// Viewer backdrops: what is drawn behind the model, and the light that goes with it.
//  - "plain" / "inverted": the page's own background (CSS), transparent canvas (PNG snapshots stay transparent)
//  - "pyro" / "stanton": 360° space panoramas built by the server from the game's sky textures (/api/backdrop/…)
//  - "workbench": a modelling workshop: a room with a table, a green cutting mat with a centimetre grid, game props
//    (lamp, toolboxes, tool chest, shelves) and a window onto Stanton's sky. Big models sit on the mat as a scale
//    model (1:72, 1:144…, chosen so they are 20-40 cm long); small ones (weapons, helmets) at real size
//  - "studio": a seamless photo-studio floor that fades into the background
import * as THREE from "three";

export const BACKDROPS = ["plain", "inverted", "pyro", "stanton", "workbench", "studio"];

// light per backdrop, relative to the chosen lighting (hangar / studio): sun colour and strength, sky/ground fill,
// and where the key light comes from (in model radii from the centre; the default camera is at -x, -z)
const LIGHT = {
  pyro: { sun: 0xffc690, sunK: 1.3, sky: 0x8a5034, ground: 0x120806, hemiK: 0.7, dir: [2, 3, 2.5] },
  stanton: { sun: 0xfff2e2, sunK: 1.25, sky: 0x3a6066, ground: 0x05080a, hemiK: 0.7, dir: [2, 3, 2.5] },
  workbench: { sun: 0xffdcb0, sunK: 1.3, sky: 0xfff0dc, ground: 0x4a3626, hemiK: 0.9, dir: [-2.6, 3.2, -0.4] },
  studio: { sun: 0xffffff, sunK: 1.2, sky: 0xffffff, ground: 0xa0a6ae, hemiK: 1.0, dir: [-2.4, 3.4, -1.6] },
};

// the workshop, in metres around the table top (y = 0, floor 76 cm below). The default camera looks from -x, -z:
// the window wall is at +z behind the model, the table's far end at +x.
const TABLE_H = 0.76;
const FLOOR = -TABLE_H, CEIL = 2.44;
// game props. On the table, placed from its corners (dx, dz: metres in from the far/near end and back/front edge);
// on the floor, against the walls. yaw: degrees (props face +z once exported, so -90 faces -x)
const TABLE_PROPS = [
  { path: "Objects/buildingsets/human/lowtech/prop/light/lamp/lamp_desk_3_a.cgf", end: 1, dx: 0.3, side: 1, dz: 0.2, yaw: 215 },
  { path: "Objects/buildingsets/human/universal/prop/storage/toolbox/storage_toolbox_1_a.cgf", end: -1, dx: 0.3, side: 1, dz: 0.24, yaw: 180 },
  { path: "Objects/buildingsets/human/universal/prop/maintence/tool/tool_power_1_drill_a.cgf", end: 1, dx: 0.25, side: -1, dz: 0.25, yaw: -150 },
  { path: "Objects/buildingsets/human/shop/alpha/shippart/dumpersdepot/int/prop/dumper_int_prop_wrench_01.cgf", end: 0, dx: 0, side: 1, dz: 0.08, yaw: 4 },
];
const WALL_PROPS = [   // wall: which wall ("x1" right, "x0" left, "z1" window wall); at: position along it
  { path: "Objects/buildingsets/human/shop/alpha/shippart/dumpersdepot/prop/prop_dumper_int_tool_chest_a.cgf", wall: "x1", at: -0.5, yaw: -90 },
  { path: "Objects/buildingsets/human/lowtech/prop/workbench/workbench_mobile_1_a.cgf", wall: "x1", at: -2.5, yaw: -90 },
  { path: "Objects/buildingsets/human/lowtech/charlie/int/prop/uee_lawless_prop_toolcart.cgf", wall: "x0", at: -1.2, yaw: 90 },
  { path: "Objects/persistent_universe/uee/lowtech/nyx/int/Shop_kit_Structure_shelf_b_01x02x02.cgf", wall: "z1", at: 1, yaw: 180 },
  { path: "Objects/buildingsets/human/universal/prop/toolbox/box_toolbox_1_a_075x0375x0375.cgf", wall: "z1", at: -1, yaw: 180 },
];

// scale models: the usual kit scales
const SCALES = [2, 4, 6, 8, 12, 16, 18, 24, 32, 35, 48, 72, 100, 144, 200, 288, 350, 500, 700, 1000, 1400, 2000,
  2500, 3000, 4000, 5000, 7000, 10000];

function canvas(w, h) {
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  return [c, c.getContext("2d")];
}

function texture(c, srgb = true) {
  const t = new THREE.CanvasTexture(c);
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  return t;
}

// vertical gradient behind everything (screen-space background), with a soft lighter glow low in the middle
function gradient(top, mid, bottom) {
  const [c, g] = canvas(16, 512);
  const lin = g.createLinearGradient(0, 0, 0, 512);
  lin.addColorStop(0, top); lin.addColorStop(0.62, mid); lin.addColorStop(1, bottom);
  g.fillStyle = lin; g.fillRect(0, 0, 16, 512);
  return texture(c);
}

// radial alpha: opaque in the middle, fading to nothing at the rim (the floor melts into the background)
function radialAlpha(inner = 0.35) {
  const [c, g] = canvas(512, 512);
  const r = g.createRadialGradient(256, 256, 256 * inner, 256, 256, 256);
  r.addColorStop(0, "#fff"); r.addColorStop(1, "#000");
  g.fillStyle = r; g.fillRect(0, 0, 512, 512);
  return texture(c, false);
}

// wood: warm planks with grain, drawn once
function woodTexture() {
  const [c, g] = canvas(1024, 1024);
  g.fillStyle = "#7a5233"; g.fillRect(0, 0, 1024, 1024);
  const plank = 1024 / 4;
  let seed = 11;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  for (let p = 0; p < 4; p++) {
    const y0 = p * plank, tone = 0.86 + rnd() * 0.24;
    g.fillStyle = `rgb(${Math.round(122 * tone)},${Math.round(82 * tone)},${Math.round(51 * tone)})`;
    g.fillRect(0, y0, 1024, plank);
    for (let i = 0; i < 70; i++) {       // grain lines
      const y = y0 + rnd() * plank, a = 0.05 + rnd() * 0.12, amp = 2 + rnd() * 6, f = 0.004 + rnd() * 0.01;
      g.strokeStyle = rnd() < 0.5 ? `rgba(60,34,18,${a})` : `rgba(170,120,80,${a * 0.7})`;
      g.lineWidth = 0.6 + rnd() * 1.8;
      g.beginPath();
      for (let x = 0; x <= 1024; x += 16) g.lineTo(x, y + Math.sin(x * f + i) * amp);
      g.stroke();
    }
    g.fillStyle = "rgba(30,18,10,0.55)"; g.fillRect(0, y0, 1024, 2);   // plank seam
  }
  const t = texture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  return t;
}

// self-healing cutting mat: 1 cm grid, 5 cm bolder, 10 cm numbered, 45° guides, scale label
function matTexture(wCm, hCm, scale) {
  const ppc = Math.max(12, Math.min(32, Math.floor(4096 / wCm)));     // pixels per centimetre
  const [c, g] = canvas(wCm * ppc, hCm * ppc);
  g.fillStyle = "#1f5443"; g.fillRect(0, 0, c.width, c.height);
  const line = (x0, y0, x1, y1, w, col) => { g.strokeStyle = col; g.lineWidth = w; g.beginPath(); g.moveTo(x0, y0); g.lineTo(x1, y1); g.stroke(); };
  for (let x = 1; x < wCm; x++) {
    const major = x % 10 === 0, mid = x % 5 === 0;
    line(x * ppc, ppc, x * ppc, c.height - ppc, major ? 2.2 : mid ? 1.5 : 0.8, major ? "#b9dccb" : mid ? "#7fb39b" : "#4f8a72");
  }
  for (let y = 1; y < hCm; y++) {
    const major = y % 10 === 0, mid = y % 5 === 0;
    line(ppc, y * ppc, c.width - ppc, y * ppc, major ? 2.2 : mid ? 1.5 : 0.8, major ? "#b9dccb" : mid ? "#7fb39b" : "#4f8a72");
  }
  // 45° guides from the corners
  g.setLineDash([ppc * 0.6, ppc * 0.4]);
  const s = Math.min(wCm, hCm) - 2;
  line(ppc, c.height - ppc, (1 + s) * ppc, c.height - (1 + s) * ppc, 1, "#9fd0b8");
  line(c.width - ppc, c.height - ppc, c.width - (1 + s) * ppc, c.height - (1 + s) * ppc, 1, "#9fd0b8");
  g.setLineDash([]);
  // rulers along the border
  g.fillStyle = "#d8efe2";
  g.font = `${Math.round(ppc * 0.55)}px system-ui, sans-serif`;
  g.textAlign = "center"; g.textBaseline = "middle";
  for (let x = 0; x <= wCm - 2; x += 1) {
    const px = (x + 1) * ppc;
    line(px, 0, px, ppc * (x % 5 === 0 ? 0.55 : 0.3), 1, "#d8efe2");
    if (x % 10 === 0 && x) g.fillText(String(x), px, ppc * 0.75);
  }
  for (let y = 0; y <= hCm - 2; y += 1) {
    const py = (y + 1) * ppc;
    line(0, py, ppc * (y % 5 === 0 ? 0.55 : 0.3), py, 1, "#d8efe2");
  }
  g.textAlign = "right"; g.textBaseline = "alphabetic";
  g.font = `600 ${Math.round(ppc * 0.8)}px system-ui, sans-serif`;
  g.fillStyle = "rgba(216,239,226,0.85)";
  g.fillText(scale > 1 ? `SCALE 1:${scale}` : "SCALE 1:1", c.width - ppc * 1.4, c.height - ppc * 1.35);
  g.font = `${Math.round(ppc * 0.5)}px system-ui, sans-serif`;
  g.fillStyle = "rgba(216,239,226,0.55)";
  g.fillText("VERSEFORGE  ·  CM", c.width - ppc * 1.4, c.height - ppc * 2.35);
  return texture(c);
}

export class Backdrops {
  constructor(scene, renderer, wrap) {
    this.scene = scene;
    this.renderer = renderer;
    this.wrap = wrap;
    this.kind = "plain";
    this.group = new THREE.Group();
    this.group.name = "__backdrop__";
    scene.add(this.group);
    // the workshop's daylight from the window. It always stays in the scene (off when not needed): adding or removing
    // a light changes every shader of the model and had them all recompiled, a 1-2 s stall on big ships
    this.day = new THREE.DirectionalLight(0xc8d8ff, 0);
    this.day.name = "__window_light__";
    scene.add(this.day, this.day.target);
    this.pano = {};          // name -> equirect texture
    this.wood = null;
    this.box = null;
    this.scale = 1;
    this.generation = 0;     // bumped on every rebuild: props still loading for an old room are dropped
    this.loadProp = null;    // async (path) -> Object3D, set by the viewer (game props of the workshop)
    this.onChange = null;    // called when the backdrop's look changed (full = false: only a prop was added)
  }

  get hasGround() { return this.kind === "workbench" || this.kind === "studio"; }
  get light() { return LIGHT[this.kind] || null; }

  async set(kind) {
    if (!BACKDROPS.includes(kind)) kind = "plain";
    this.kind = kind;
    this.wrap.classList.toggle("alt", kind === "inverted");
    this.scene.background = null;
    this.scene.backgroundIntensity = 1;
    if (kind === "pyro" || kind === "stanton" || kind === "workbench") {
      // the workshop's window looks out on Stanton's sky
      const sky = kind === "workbench" ? "stanton" : kind;
      if (!this.pano[sky]) {
        this.pano[sky] = await new THREE.TextureLoader().loadAsync(`/api/backdrop/${sky}?r=4`);
        this.pano[sky].mapping = THREE.EquirectangularReflectionMapping;
        this.pano[sky].colorSpace = THREE.SRGBColorSpace;
      }
      if (this.kind !== kind) return;      // changed again while loading
      this.scene.background = this.pano[sky];
      this.scene.backgroundIntensity = sky === "pyro" ? 1.15 : 1.35;
    } else if (kind === "studio") {
      this.scene.background = gradient("#9aa0a8", "#c3c8cf", "#d4d8dd");
    }
    this.fit(this.box);
    this.onChange?.();
  }

  // place the floor under the model (box: the model's bounding box, world units = metres)
  fit(box) {
    this.box = box;
    this.generation++;
    for (const o of [...this.group.children]) {
      this.group.remove(o);
      o.traverse((m) => {
        // game props are clones sharing the loaded geometry and materials: those stay for the next room
        if (!m.isMesh || m.userData.prop) return;
        m.geometry.dispose();
        if (m.material.map && m.material.map !== this.wood) m.material.map.dispose();
        m.material.alphaMap?.dispose();
        m.material.dispose();
      });
    }
    this.day.intensity = 0;
    if (!box || box.isEmpty() || !this.hasGround) return;
    const size = box.getSize(new THREE.Vector3()), c = box.getCenter(new THREE.Vector3());
    const y = box.min.y - Math.max(size.y, 0.001) * 0.002;   // a hair below the landing gear / feet
    if (this.kind === "workbench") this.workbench(size, c, y);
    else this.studio(size, c, y);
  }

  workbench(size, c, y) {
    // longest horizontal side along the mat's long side
    const along = size.x >= size.z ? "x" : "z";
    const L = Math.max(size.x, size.z), W = Math.min(size.x, size.z);
    const scale = L <= 1.2 ? 1 : (SCALES.find((s) => L / s <= 0.4) || SCALES[SCALES.length - 1]);
    this.scale = scale;
    const wCm = Math.max(60, Math.ceil((L / scale * 100 + 16) / 10) * 10);
    const hCm = Math.max(45, Math.ceil((W / scale * 100 + 16) / 5) * 5);
    const unit = scale / 100;                      // world metres per mat centimetre
    const matW = wCm * unit, matH = hCm * unit;
    const mat = new THREE.Mesh(new THREE.PlaneGeometry(matW, matH),
      new THREE.MeshStandardMaterial({ map: matTexture(wCm, hCm, scale), roughness: 0.92, metalness: 0 }));
    mat.rotation.x = -Math.PI / 2;
    if (along === "z") mat.rotation.z = Math.PI / 2;
    mat.position.set(c.x, y + unit * 0.02, c.z);
    mat.receiveShadow = true;
    this.group.add(mat);
    // the room around it, in real metres scaled like the model: the table's long side follows the mat, the window
    // wall stays behind the model as seen from the default camera (at -x, -z)
    // mat extents in real metres along x and z
    const mx = (along === "x" ? wCm : hCm) / 100, mz = (along === "x" ? hCm : wCm) / 100;
    const room = this.room(mx, mz);
    room.scale.setScalar(scale);
    room.position.set(c.x, y, c.z);
    this.group.add(room);
    room.updateMatrixWorld(true);
    this.day.position.copy(room.localToWorld(room.userData.window.clone()));
    this.day.target.position.copy(room.localToWorld(new THREE.Vector3(0, 0, 0)));
    this.day.target.updateMatrixWorld();
    this.day.intensity = 0.7;
    this.furnish(room, this.generation);
  }

  // ---------------------------------------------------------------- the workshop room (metres, table top at y = 0)
  room(mx, mz) {
    // the table grows with the mat; the room is laid out around the table
    const tw = Math.max(1.8, mx + 1.0), td = Math.max(0.9, mz + 0.3);
    const X1 = tw / 2 + 2.2, X0 = -tw / 2 - 2.2, Z1 = td / 2 + 0.55, Z0 = Z1 - 4.8;
    const half = Math.min(1.5, (X1 - X0) / 2 - 1.3);
    const WIN = { x0: -half, x1: half, y0: 0.22, y1: 1.92 };
    const g = new THREE.Group();
    g.userData.layout = { tw, td, X0, X1, Z0, Z1 };
    g.name = "workshop";
    if (!this.wood) this.wood = woodTexture();
    const std = (o) => new THREE.MeshStandardMaterial({ roughness: 0.85, metalness: 0, ...o });
    const box = (w, h, d, x, y, z, m, shadow = true) => {
      const b = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m);
      b.position.set(x, y, z);
      b.receiveShadow = shadow;
      b.castShadow = false;
      g.add(b);
      return b;
    };
    const H = CEIL - FLOOR, cx = (X0 + X1) / 2, cz = (Z0 + Z1) / 2;
    // table: wooden top on four legs
    const top = this.wood.clone();
    top.needsUpdate = true;
    top.repeat.set(2, 1);
    box(tw, 0.04, td, 0, -0.02, 0, std({ map: top, roughness: 0.55 }));
    const legM = std({ color: 0x2b2b2e, roughness: 0.5, metalness: 0.6 });
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
      box(0.05, TABLE_H - 0.04, 0.05, sx * (tw / 2 - 0.06), FLOOR + (TABLE_H - 0.04) / 2, sz * (td / 2 - 0.06), legM, false);
    }
    // floor (dark boards), ceiling, plaster walls
    const boards = this.wood.clone();
    boards.needsUpdate = true;
    boards.repeat.set((X1 - X0) / 0.9, (Z1 - Z0) / 0.9);
    box(X1 - X0, 0.02, Z1 - Z0, cx, FLOOR - 0.01, cz, std({ map: boards, color: 0x8a8580, roughness: 0.7 }));
    const wallM = std({ color: 0xd9d4cb, roughness: 0.95 });
    box(X1 - X0, 0.02, Z1 - Z0, cx, CEIL + 0.01, cz, std({ color: 0xe8e5df }), false);
    box(0.1, H, Z1 - Z0, X0 - 0.05, FLOOR + H / 2, cz, wallM);
    box(0.1, H, Z1 - Z0, X1 + 0.05, FLOOR + H / 2, cz, wallM);
    box(X1 - X0, H, 0.1, cx, FLOOR + H / 2, Z0 - 0.05, wallM);
    // back wall with a wide window onto space (the Stanton panorama is the scene background, seen through it)
    const zw = Z1 + 0.05;
    box(WIN.x0 - X0, H, 0.1, (X0 + WIN.x0) / 2, FLOOR + H / 2, zw, wallM);
    box(X1 - WIN.x1, H, 0.1, (WIN.x1 + X1) / 2, FLOOR + H / 2, zw, wallM);
    box(WIN.x1 - WIN.x0, WIN.y0 - FLOOR, 0.1, (WIN.x0 + WIN.x1) / 2, (FLOOR + WIN.y0) / 2, zw, wallM);
    box(WIN.x1 - WIN.x0, CEIL - WIN.y1, 0.1, (WIN.x0 + WIN.x1) / 2, (WIN.y1 + CEIL) / 2, zw, wallM);
    const frameM = std({ color: 0x3a3d42, roughness: 0.4, metalness: 0.7 });
    const fw = 0.06, wx = (WIN.x0 + WIN.x1) / 2, wy = (WIN.y0 + WIN.y1) / 2;
    box(WIN.x1 - WIN.x0 + fw, fw, 0.16, wx, WIN.y0, zw, frameM);
    box(WIN.x1 - WIN.x0 + fw, fw, 0.16, wx, WIN.y1, zw, frameM);
    for (const fx of [WIN.x0, wx, WIN.x1]) box(fw, WIN.y1 - WIN.y0, 0.16, fx, wy, zw, frameM);
    box(WIN.x1 - WIN.x0 + 0.2, 0.04, 0.3, wx, WIN.y0 - 0.02, zw - 0.12, std({ color: 0xcfc9bf }));   // sill
    g.userData.window = new THREE.Vector3(wx, wy + 0.6, zw + 2);   // where the daylight comes from (this.day)
    return g;
  }

  // game props around the table, loaded one by one (they come with the game look of the model viewer)
  async furnish(room, generation) {
    if (!this.loadProp) return;
    const { tw, td, X0, X1, Z1 } = room.userData.layout;
    const place = [
      // end 0: along the middle of the table (behind the mat, towards the window)
      ...TABLE_PROPS.map((p) => ({ ...p, x: p.end ? p.end * (tw / 2 - p.dx) : 0, y: 0, z: p.side * (td / 2 - p.dz) })),
      ...WALL_PROPS.map((p) => ({ ...p, y: FLOOR, wallGap: 0.06 })),
    ];
    for (const p of place) {
      let obj;
      try {
        obj = await this.loadProp(p.path);
      } catch {
        continue;            // a prop missing in this game version: the room just has one thing less
      }
      if (!obj || this.generation !== generation || room.parent !== this.group) return;
      obj = obj.clone();
      obj.rotation.y = THREE.MathUtils.degToRad(p.yaw || 0);
      obj.updateMatrixWorld(true);
      // sit it by its bounding box: centred on (x, z), resting on y
      const b = new THREE.Box3().setFromObject(obj);
      const bc = b.getCenter(new THREE.Vector3()), bs = b.getSize(new THREE.Vector3());
      if (p.wall) {       // back against the wall, `at` metres along it
        if (p.wall === "x1") { p.x = X1 - bs.x / 2 - p.wallGap; p.z = p.at; }
        if (p.wall === "x0") { p.x = X0 + bs.x / 2 + p.wallGap; p.z = p.at; }
        if (p.wall === "z1") { p.z = Z1 - bs.z / 2 - p.wallGap; p.x = p.at * (X1 - bs.x / 2 - 0.3); }
      }
      obj.position.set(p.x - bc.x, p.y - b.min.y, p.z - bc.z);
      obj.traverse((o) => { if (o.isMesh) { o.castShadow = false; o.receiveShadow = true; o.userData.prop = true; } });
      room.add(obj);
      this.onChange?.(false);
    }
  }

  studio(size, c, y) {
    const R = Math.max(size.x, size.y, size.z) * 7;
    const floor = new THREE.Mesh(new THREE.CircleGeometry(R, 96),
      new THREE.MeshStandardMaterial({ color: 0xd2d6db, roughness: 0.95, metalness: 0, transparent: true,
        alphaMap: radialAlpha(0.18), depthWrite: false }));
    floor.rotation.x = -Math.PI / 2;
    floor.position.set(c.x, y, c.z);
    floor.receiveShadow = true;
    floor.renderOrder = -1;
    this.group.add(floor);
  }
}
