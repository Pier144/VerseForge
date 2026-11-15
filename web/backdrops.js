// Viewer backdrops: what is drawn behind the model, and the light that goes with it.
//  - "plain" / "inverted": the page's own background (CSS), transparent canvas (PNG snapshots stay transparent)
//  - "pyro" / "stanton": 360° space panoramas built by the server from the game's sky textures (/api/backdrop/…)
//  - "workbench": a modelling workshop: a room with a table, a green cutting mat with a centimetre grid, game props
//    (lamp, toolboxes, tool chest, wall shelves with paints, tools and miniatures) and a window onto Stanton's sky
//    in the side wall. Big models sit on the mat as a scale
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
// the shelf wall is at +z behind the model, the table's far end at +x, the window in the -x wall (on the right).
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
const WALL_PROPS = [   // wall: which wall ("x1" far end, "x0" window wall, "z1" shelf wall); at: position along it
  { path: "Objects/buildingsets/human/shop/alpha/shippart/dumpersdepot/prop/prop_dumper_int_tool_chest_a.cgf", wall: "x1", at: -0.5, yaw: -90 },
  { path: "Objects/buildingsets/human/lowtech/prop/workbench/workbench_mobile_1_a.cgf", wall: "x1", at: -2.5, yaw: -90 },
  { path: "Objects/buildingsets/human/lowtech/charlie/int/prop/uee_lawless_prop_toolcart.cgf", wall: "x0", at: -3.3, yaw: 90 },
  { path: "Objects/persistent_universe/uee/lowtech/nyx/int/Shop_kit_Structure_shelf_b_01x02x02.cgf", wall: "z1", at: 1, yaw: 180 },
  { path: "Objects/buildingsets/human/universal/prop/toolbox/box_toolbox_1_a_075x0375x0375.cgf", wall: "z1", at: -1, yaw: 180 },
];
// the wall behind the table (+z) carries three plain shelves above the table. y: height of the shelf's underside
// above the table top, x: its middle (metres)
const SHELF = "Objects/buildingsets/human/lowtech/charlie/int/prop/uee_lawless_prop_shelfwall_1x_01.cgf";
const SHELVES = [{ path: SHELF, x: 0, y: 0.5 }, { path: SHELF, x: 0, y: 0.95 }, { path: SHELF, x: 0, y: 1.4 }];
// what stands on them: shelf (index in SHELVES), x along it from its middle (metres), yaw (degrees; 180 turns most
// game props to face the room, the figures face it as they are)
const PROP = "Objects/buildingsets/human/universal/prop/";
const SHELF_PROPS = [
  // bottom shelf: paints, sprays, glue
  { path: PROP + "dressing/can/can_paint_1_a.cgf", shelf: 0, x: -0.82, yaw: 180 },
  { path: PROP + "dressing/can/can_paint_2_a.cgf", shelf: 0, x: -0.62, yaw: 180 },
  { path: PROP + "dressing/can/can_spray_1_a.cgf", shelf: 0, x: -0.42, yaw: 180 },
  { path: PROP + "dressing/can/can_spray_2_a.cgf", shelf: 0, x: -0.32, yaw: 180 },
  { path: PROP + "dressing/bottle/bottle_spray_1_a.cgf", shelf: 0, x: -0.2, yaw: 210 },
  { path: PROP + "dressing/personal/personal_toothpaste_1_a.cgf", shelf: 0, x: 0.02, yaw: 260 },   // the glue tube
  { path: PROP + "dressing/personal/personal_toothpaste_1_b.cgf", shelf: 0, x: 0.12, yaw: 280 },
  { path: PROP + "food/jar/jar_glass_1_empty_a.cgf", shelf: 0, x: 0.3, yaw: 180 },
  { path: "Objects/props/cinematic/painting/brush_paint_1_a.cgf", shelf: 0, x: 0.55, yaw: 192 },
  { path: PROP + "dressing/can/can_paint_1_a.cgf", shelf: 0, x: 0.8, yaw: 180 },
  // middle shelf: hand tools and figures
  { path: "Objects/buildingsets/human/lowtech/prop/tool/tool_manual_2_pliers_a.cgf", shelf: 1, x: -0.82, yaw: 250 },
  { path: "Objects/buildingsets/human/lowtech/prop/tool/tool_manual_2_screwdriver_a.cgf", shelf: 1, x: -0.68, yaw: 275 },
  { path: "Objects/buildingsets/human/lowtech/prop/tool/tool_manual_2_cutters_a.cgf", shelf: 1, x: -0.54, yaw: 260 },
  { path: "Objects/buildingsets/human/hightech/prop/cgbot/accessory/tool_multi_a.cgf", shelf: 1, x: -0.36, yaw: 180 },
  { path: "Objects/props/flair/figure/figure_marine_1_a.cgf", shelf: 1, x: 0.2 },
  { path: "Objects/props/flair/figure/figure_worker_1_a.cgf", shelf: 1, x: 0.5 },
  { path: "Objects/props/flair/figure/figure_vanduul_1_a.cgf", shelf: 1, x: 0.8 },
  // top shelf: miniatures and a clamp
  { path: "Objects/props/flair/model_spaceships/anvil/carrack_model_1_toy_a.cgf", shelf: 2, x: -0.78, yaw: 270 },
  { path: "Objects/props/flair/model_spaceships/misc/flair_misc_hullc_toy_1_a.cgf", shelf: 2, x: -0.55, yaw: 270 },
  { path: PROP + "tchotchke/model/model_ship_2_hornet_a.cgf", shelf: 2, x: -0.05, yaw: 20 },
  { path: PROP + "accessory/tool/tool_clamp_a.cgf", shelf: 2, x: 0.6, yaw: 270 },
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

// seeded random numbers: the room looks the same every time it is built
function rng(seed) {
  return () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
}

// wood grain on a plank-sized strip of a canvas
function grain(g, rnd, x0, y0, w, h, n, scale = 1) {
  for (let i = 0; i < n; i++) {
    const y = y0 + rnd() * h, a = 0.05 + rnd() * 0.12, amp = (2 + rnd() * 6) * scale, f = (0.004 + rnd() * 0.01) / scale;
    g.strokeStyle = rnd() < 0.5 ? `rgba(60,34,18,${a})` : `rgba(170,120,80,${a * 0.7})`;
    g.lineWidth = (0.6 + rnd() * 1.8) * scale;
    g.beginPath();
    const ph = rnd() * 100;
    for (let x = x0; x <= x0 + w; x += 16 * scale) g.lineTo(x, y + Math.sin(x * f + ph) * amp);
    g.stroke();
  }
  for (let i = 0; i < n / 10; i++) {   // knots
    const kx = x0 + rnd() * w, ky = y0 + rnd() * h, r = (3 + rnd() * 7) * scale;
    const k = g.createRadialGradient(kx, ky, 0, kx, ky, r * 2.2);
    k.addColorStop(0, "rgba(45,26,12,0.45)"); k.addColorStop(1, "rgba(45,26,12,0)");
    g.fillStyle = k; g.fillRect(kx - r * 3, ky - r * 3, r * 6, r * 6);
  }
}

// wood: warm planks with grain, drawn once (the table top)
function woodTexture() {
  const S = 2048;
  const [c, g] = canvas(S, S);
  g.fillStyle = "#7a5233"; g.fillRect(0, 0, S, S);
  const plank = S / 4, rnd = rng(11);
  for (let p = 0; p < 4; p++) {
    const y0 = p * plank, tone = 0.86 + rnd() * 0.24;
    g.fillStyle = `rgb(${Math.round(122 * tone)},${Math.round(82 * tone)},${Math.round(51 * tone)})`;
    g.fillRect(0, y0, S, plank);
    grain(g, rnd, 0, y0, S, plank, 120, 2);
    g.fillStyle = "rgba(30,18,10,0.55)"; g.fillRect(0, y0, S, 3);   // plank seam
  }
  // a used work surface: a few rings, scratches and glue spots
  for (let i = 0; i < 40; i++) {
    const x = rnd() * S, y = rnd() * S, l = 30 + rnd() * 160, a = rnd() * Math.PI;
    g.strokeStyle = `rgba(${rnd() < 0.5 ? "225,190,150" : "40,24,12"},${0.08 + rnd() * 0.12})`;
    g.lineWidth = 1 + rnd() * 1.5;
    g.beginPath(); g.moveTo(x, y); g.lineTo(x + Math.cos(a) * l, y + Math.sin(a) * l); g.stroke();
  }
  for (let i = 0; i < 4; i++) {
    const x = rnd() * S, y = rnd() * S, r = 40 + rnd() * 30;
    g.strokeStyle = "rgba(50,30,15,0.12)"; g.lineWidth = 5;
    g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.stroke();
  }
  const t = texture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.anisotropy = 16;
  return t;
}

// floor boards drawn for the whole floor (no repeat): staggered planks, worn where people walk, darker by the walls
const canvasCache = new Map();
function floorTexture(wM, dM) {
  const key = `floor:${wM.toFixed(2)}:${dM.toFixed(2)}`;
  if (!canvasCache.has(key)) {
    const ppm = Math.min(2048 / Math.max(wM, dM), 400);        // pixels per metre
    const [c, g] = canvas(Math.round(wM * ppm), Math.round(dM * ppm));
    const rnd = rng(23), pw = 0.16 * ppm;                       // 16 cm boards along x
    g.fillStyle = "#4a3324"; g.fillRect(0, 0, c.width, c.height);
    for (let y0 = 0, row = 0; y0 < c.height; y0 += pw, row++) {
      let x0 = -rnd() * 1.6 * ppm;
      while (x0 < c.width) {
        const len = (1.2 + rnd() * 1.4) * ppm, tone = 0.8 + rnd() * 0.3;
        g.fillStyle = `rgb(${Math.round(92 * tone)},${Math.round(64 * tone)},${Math.round(44 * tone)})`;
        g.fillRect(x0, y0, len, pw);
        grain(g, rnd, x0, y0, len, pw, 14, 1);
        g.fillStyle = "rgba(20,12,6,0.6)";
        g.fillRect(x0, y0, 2, pw); g.fillRect(x0, y0, len, 1.5);   // seams
        x0 += len;
      }
    }
    // wear in the middle (lighter, duller), dust and shade along the walls
    const mid = g.createRadialGradient(c.width / 2, c.height / 2, 0, c.width / 2, c.height / 2, Math.max(c.width, c.height) * 0.45);
    mid.addColorStop(0, "rgba(190,160,120,0.10)"); mid.addColorStop(1, "rgba(190,160,120,0)");
    g.fillStyle = mid; g.fillRect(0, 0, c.width, c.height);
    edgeShade(g, c.width, c.height, 0.25 * ppm, 0.45);
    canvasCache.set(key, c);
  }
  const t = texture(canvasCache.get(key));
  t.anisotropy = 16;
  return t;
}

// darkening towards the edges of a surface: the soft shade of a room's corners
function edgeShade(g, w, h, size, a, sides = "tblr") {
  const band = (x0, y0, x1, y1, rx, ry, rw, rh) => {
    const l = g.createLinearGradient(x0, y0, x1, y1);
    l.addColorStop(0, `rgba(25,20,15,${a})`); l.addColorStop(1, "rgba(25,20,15,0)");
    g.fillStyle = l; g.fillRect(rx, ry, rw, rh);
  };
  if (sides.includes("t")) band(0, 0, 0, size, 0, 0, w, size);
  if (sides.includes("b")) band(0, h, 0, h - size, 0, h - size, w, size);
  if (sides.includes("l")) band(0, 0, size, 0, 0, 0, size, h);
  if (sides.includes("r")) band(w, 0, w - size, 0, w - size, 0, size, h);
}

// a wall's own plaster (wM × hM metres, no repeat): blotchy paint, grime rising from the floor, scuffs at kicking
// height, a few streaks running down, darker corners. floor/ceil: whether the bottom/top edge meets them
function wallTexture(wM, hM, seed, { floor = true, ceil = true, sides = "lr", streaks = true } = {}) {
  const key = `wall:${wM.toFixed(2)}:${hM.toFixed(2)}:${seed}:${floor}:${ceil}:${sides}:${streaks}`;
  if (!canvasCache.has(key)) {
    const ppm = Math.min(1024 / Math.max(wM, hM), 220);
    const W = Math.max(8, Math.round(wM * ppm)), H = Math.max(8, Math.round(hM * ppm));
    const [c, g] = canvas(W, H);
    const rnd = rng(seed);
    g.fillStyle = "#d9d4cb"; g.fillRect(0, 0, W, H);
    for (let i = 0; i < 60; i++) {            // uneven paint
      const x = rnd() * W, y = rnd() * H, r = (0.2 + rnd() * 0.8) * ppm;
      const b = g.createRadialGradient(x, y, 0, x, y, r);
      const col = rnd() < 0.6 ? "190,182,168" : "236,232,224";
      b.addColorStop(0, `rgba(${col},${0.05 + rnd() * 0.08})`); b.addColorStop(1, `rgba(${col},0)`);
      g.fillStyle = b; g.fillRect(x - r, y - r, r * 2, r * 2);
    }
    for (let i = 0; i < W * H / 60; i++) {    // speckle
      g.fillStyle = `rgba(${rnd() < 0.5 ? "120,110,96" : "255,255,250"},${0.04 + rnd() * 0.06})`;
      g.fillRect(rnd() * W, rnd() * H, 1 + rnd(), 1 + rnd());
    }
    if (floor) {                               // grime rising from the floor, scuffs at kicking height
      const f = g.createLinearGradient(0, H, 0, H - 0.6 * ppm);
      f.addColorStop(0, "rgba(70,55,40,0.28)"); f.addColorStop(1, "rgba(70,55,40,0)");
      g.fillStyle = f; g.fillRect(0, H - 0.6 * ppm, W, 0.6 * ppm);
      for (let i = 0; i < wM * 3; i++) {
        const x = rnd() * W, y = H - (0.1 + rnd() * 0.45) * ppm, l = (0.05 + rnd() * 0.25) * ppm;
        g.strokeStyle = `rgba(55,45,35,${0.08 + rnd() * 0.12})`; g.lineWidth = 1 + rnd() * 2;
        g.beginPath(); g.moveTo(x, y); g.lineTo(x + l, y + (rnd() - 0.5) * 6); g.stroke();
      }
    }
    for (let i = 0; i < (streaks ? wM * 0.8 : 0); i++) {       // streaks running down from the top
      const x = rnd() * W, y0 = ceil ? 0 : rnd() * H * 0.3, l = (0.3 + rnd() * 1.2) * ppm, w = (0.02 + rnd() * 0.05) * ppm;
      const s = g.createLinearGradient(0, y0, 0, y0 + l);
      s.addColorStop(0, "rgba(110,95,75,0.10)"); s.addColorStop(1, "rgba(110,95,75,0)");
      g.fillStyle = s; g.fillRect(x, y0, w, l);
    }
    for (let i = 0; i < 3; i++) {              // a few smudges at hand height
      const x = rnd() * W, y = H - (0.9 + rnd() * 0.8) * ppm, r = (0.05 + rnd() * 0.12) * ppm;
      const b = g.createRadialGradient(x, y, 0, x, y, r);
      b.addColorStop(0, "rgba(60,50,40,0.12)"); b.addColorStop(1, "rgba(60,50,40,0)");
      g.fillStyle = b; g.fillRect(x - r, y - r, r * 2, r * 2);
    }
    edgeShade(g, W, H, 0.35 * ppm, 0.22, (floor ? "b" : "") + (ceil ? "t" : "") + sides);
    canvasCache.set(key, c);
  }
  return texture(canvasCache.get(key));
}

// fine plaster relief, tiled (bump map)
let plaster = null;
function plasterBump() {
  if (!plaster) {
    const S = 256, [c, g] = canvas(S, S), img = g.createImageData(S, S), rnd = rng(5);
    for (let i = 0; i < S * S; i++) {
      const v = 120 + rnd() * 30;
      img.data[i * 4] = img.data[i * 4 + 1] = img.data[i * 4 + 2] = v; img.data[i * 4 + 3] = 255;
    }
    g.putImageData(img, 0, 0);
    g.globalAlpha = 0.5; g.filter = "blur(1px)"; g.drawImage(c, 0, 0); g.filter = "none"; g.globalAlpha = 1;
    plaster = c;
  }
  const t = texture(plaster, false);
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
        m.material.bumpMap?.dispose();
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
    // the window is in the -x wall (on the right of the default view), towards the shelf wall
    const winLen = Math.min(2.4, Z1 - Z0 - 1.6);
    const WIN = { z0: Z1 - 0.6 - winLen, z1: Z1 - 0.6, y0: 0.22, y1: 1.92 };
    const g = new THREE.Group();
    g.userData.layout = { tw, td, X0, X1, Z0, Z1 };
    g.name = "workshop";
    if (!this.wood) this.wood = woodTexture();
    const std = (o) => new THREE.MeshStandardMaterial({ roughness: 0.85, metalness: 0, ...o });
    const box = (w, h, d, x, y, z, m, shadow = true, name = "") => {
      const b = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m);
      b.name = name;     // names the parts in exports of the room
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
    box(tw, 0.04, td, 0, -0.02, 0, std({ map: top, roughness: 0.55 }), true, "table_top");
    const legM = std({ color: 0x2b2b2e, roughness: 0.5, metalness: 0.6 });
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
      box(0.05, TABLE_H - 0.04, 0.05, sx * (tw / 2 - 0.06), FLOOR + (TABLE_H - 0.04) / 2, sz * (td / 2 - 0.06), legM, false,
        "table_leg");
    }
    // floor: boards drawn for the whole floor, worn in the middle, darker along the walls
    box(X1 - X0, 0.02, Z1 - Z0, cx, FLOOR - 0.01, cz, std({ map: floorTexture(X1 - X0, Z1 - Z0), roughness: 0.72 }), true, "floor");
    // ceiling and walls: each its own plaster (uneven paint, grime from the floor, streaks, shaded corners) over a
    // fine tiled relief
    let seed = 101;
    const plasterM = (wM, hM, opts, tint = 0xffffff) => {
      const bump = plasterBump();
      bump.repeat.set(wM / 0.7, hM / 0.7);
      return std({ map: wallTexture(wM, hM, seed++, opts), bumpMap: bump, bumpScale: 0.8, color: tint, roughness: 0.95 });
    };
    const fullH = { floor: true, ceil: true };
    box(X1 - X0, 0.02, Z1 - Z0, cx, CEIL + 0.01, cz,
      plasterM(X1 - X0, Z1 - Z0, { floor: false, ceil: false, sides: "tblr", streaks: false }, 0xf2efe9), false, "ceiling");
    box(0.1, H, Z1 - Z0, X1 + 0.05, FLOOR + H / 2, cz, plasterM(Z1 - Z0, H, fullH), true, "wall_far");
    box(X1 - X0, H, 0.1, cx, FLOOR + H / 2, Z0 - 0.05, plasterM(X1 - X0, H, fullH), true, "wall_near");
    box(X1 - X0, H, 0.1, cx, FLOOR + H / 2, Z1 + 0.05, plasterM(X1 - X0, H, fullH), true, "wall_shelves");   // the shelves hang on it
    // side wall with a wide window onto space (the Stanton panorama is the scene background, seen through it)
    const xw = X0 - 0.05, wz = (WIN.z0 + WIN.z1) / 2, wy = (WIN.y0 + WIN.y1) / 2, wl = WIN.z1 - WIN.z0;
    box(0.1, H, WIN.z0 - Z0, xw, FLOOR + H / 2, (Z0 + WIN.z0) / 2, plasterM(WIN.z0 - Z0, H, { ...fullH, sides: "l" }), true, "wall_window");
    box(0.1, H, Z1 - WIN.z1, xw, FLOOR + H / 2, (WIN.z1 + Z1) / 2, plasterM(Z1 - WIN.z1, H, { ...fullH, sides: "r" }), true, "wall_window");
    box(0.1, WIN.y0 - FLOOR, wl, xw, (FLOOR + WIN.y0) / 2, wz, plasterM(wl, WIN.y0 - FLOOR, { floor: true, ceil: false, sides: "" }), true, "wall_window");
    box(0.1, CEIL - WIN.y1, wl, xw, (WIN.y1 + CEIL) / 2, wz, plasterM(wl, CEIL - WIN.y1, { floor: false, ceil: true, sides: "" }), true, "wall_window");
    const frameM = std({ color: 0x3a3d42, roughness: 0.4, metalness: 0.7 });
    const fw = 0.06;
    box(0.16, fw, wl + fw, xw, WIN.y0, wz, frameM, true, "window_frame");
    box(0.16, fw, wl + fw, xw, WIN.y1, wz, frameM, true, "window_frame");
    for (const fz of [WIN.z0, wz, WIN.z1]) box(0.16, WIN.y1 - WIN.y0, fw, xw, wy, fz, frameM, true, "window_frame");
    box(0.3, 0.04, wl + 0.2, xw + 0.12, WIN.y0 - 0.02, wz, std({ color: 0xcfc9bf }), true, "window_sill");
    // skirting boards all round
    const skirtM = std({ color: 0x4d4741, roughness: 0.6 }), sk = 0.08, st = 0.015;
    box(X1 - X0, sk, st, cx, FLOOR + sk / 2, Z1 - st / 2, skirtM, true, "skirting");
    box(X1 - X0, sk, st, cx, FLOOR + sk / 2, Z0 + st / 2, skirtM, true, "skirting");
    box(st, sk, Z1 - Z0, X1 - st / 2, FLOOR + sk / 2, cz, skirtM, true, "skirting");
    box(st, sk, Z1 - Z0, X0 + st / 2, FLOOR + sk / 2, cz, skirtM, true, "skirting");
    g.userData.window = new THREE.Vector3(xw - 2, wy + 0.6, wz);   // where the daylight comes from (this.day)
    return g;
  }

  // game props around the table, loaded one by one (they come with the game look of the model viewer)
  async furnish(room, generation) {
    if (!this.loadProp) return;
    const { tw, td, X0, X1, Z1 } = room.userData.layout;
    const place = [
      // end 0: along the middle of the table (behind the mat, towards the shelf wall)
      ...TABLE_PROPS.map((p) => ({ ...p, x: p.end ? p.end * (tw / 2 - p.dx) : 0, y: 0, z: p.side * (td / 2 - p.dz) })),
      ...WALL_PROPS.map((p) => ({ ...p, y: FLOOR, wallGap: 0.06 })),
      // shelves before what stands on them: each records where its top is
      ...SHELVES.map((p, i) => ({ ...p, yaw: 0, shelfIndex: i })),   // this shelf model faces the room as it is
      ...SHELF_PROPS.map((p) => ({ ...p })),   // copies: their x is turned into a room position below
    ];
    const shelves = [];      // shelf index -> its box once placed (room coordinates)
    for (const p of place) {
      if (p.shelf !== undefined) {         // on a shelf: centred on its depth, resting on its top
        const s = shelves[p.shelf];
        if (!s) continue;
        const sc = s.getCenter(new THREE.Vector3());
        p.x = sc.x + p.x; p.y = s.max.y; p.z = sc.z;
      }
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
      if (p.shelfIndex !== undefined) p.z = Z1 - bs.z / 2 - 0.01;   // a shelf: back against the shelf wall
      obj.position.set(p.x - bc.x, p.y - b.min.y, p.z - bc.z);
      obj.name = p.path.split("/").pop().replace(/\.cg[af]$/, "");   // names the props in exports of the room
      if (p.shelfIndex !== undefined) {
        obj.updateMatrixWorld(true);
        shelves[p.shelfIndex] = new THREE.Box3().setFromObject(obj);
      }
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
