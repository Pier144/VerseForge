import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { AmmoScreen, isFire, isReload } from "./screen.js";
import { vertexNormals } from "./normals.js";
import { GameLook } from "./gamelook.js";
import { hangarTexture } from "./hangar.js";
import { Backdrops, BACKDROPS } from "./backdrops.js";

const $ = (s) => document.querySelector(s);
const api = async (url, opts) => {
  const r = await fetch(url, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch { /* not json */ }
    throw new Error(msg);
  }
  return r;
};

// ---------------------------------------------------------------- texts built by the script
const STRINGS = {
  loading: "Loading…", loadingOf: "Loading {name}…", width: "Width", length: "Length", height: "Height",
  triangles: "Triangles", parts: "Parts", materials: "Materials", variant: "Variant / paint",
  loadFailed: "Could not load the model: {error}", exported: "Exported {name} (copy saved to {dir})",
  exportsDir: "exports", exportFailed: "Export failed: {error}", print3d: "3D print: {error}",
  loadPrepare: "Preparing the model on the server…", loadDownload: "Downloading {done} / {total} MB",
  loadDownloadNoSize: "Downloading {done} MB", loadTextures: "Game textures {done} / {total}", loadScene: "Building the scene…", loadShaders: "Preparing shaders…",
  printReady: "Ready: {size} mm, {volume} cm³, {closed}.", closedYes: "watertight ✓", closedNo: "not fully closed",
  downloadStl: "Download STL", printDone: "Printable STL of {name} ready", results: "{n} results",
  resultsOf: "{n} results · showing {shown}", all: "All", openSettings: "open Settings to fix the path",
  serverDown: "Server not reachable…", saved: "Settings saved", kindDecal: "decal", kindGlass: "glass", kindProxy: "proxy", kindScreen: "screen",
};
const T = (key, vars = {}) => (STRINGS[key] ?? key).replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? "");
const num = (n) => n.toLocaleString("en-US");

const CAT_LABELS = {};
const KIND_LABELS = { solid: "", decal: "kindDecal", glass: "kindGlass", hidden: "kindProxy", screen: "kindScreen" };
const SUBCATS = {};
const state = { cat: "", sub: "", current: null, kinds: { decal: false, glass: true, hidden: false, screen: true }, matOff: new Set(), printJob: null, tex: true, variant: null, full: false,
  look: true, swapXY: false, light: "hangar", interior: false, cut: 1 };
try { state.tex = localStorage.getItem("vf.tex") !== "0"; } catch { /* storage unavailable */ }
try { state.light = localStorage.getItem("vf.light") === "studio" ? "studio" : "hangar"; } catch { /* storage unavailable */ }

// ---------------------------------------------------------------- dropdown
// Drawn by the page instead of the native <select> popup: Chromium (and Qt WebEngine) left the rows the mouse
// had passed over highlighted. The <select> stays underneath, invisible, so its value and "change" event work as before.
function dropdown(sel) {
  const wrap = document.createElement("div");
  wrap.className = "dd";
  sel.before(wrap);
  sel.classList.add("dd-native");
  sel.tabIndex = -1;
  sel.setAttribute("aria-hidden", "true");
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "dd-btn";
  btn.setAttribute("aria-haspopup", "listbox");
  const list = document.createElement("ul");
  list.className = "dd-list";
  list.setAttribute("role", "listbox");
  list.hidden = true;
  wrap.append(sel, btn, list);
  let active = -1;

  const sync = () => { btn.textContent = sel.selectedOptions[0]?.text ?? ""; };
  const setActive = (i) => {
    active = i;
    [...list.children].forEach((li, k) => li.classList.toggle("active", k === i));
    list.children[i]?.scrollIntoView({ block: "nearest" });
  };
  const close = () => { list.hidden = true; wrap.classList.remove("open"); btn.setAttribute("aria-expanded", "false"); };
  const pick = (i) => {
    close();
    btn.focus();
    if (i < 0 || i === sel.selectedIndex) return;
    sel.selectedIndex = i;
    sync();
    sel.dispatchEvent(new Event("change"));
  };
  const open = () => {
    list.innerHTML = "";
    [...sel.options].forEach((o, i) => {
      const li = document.createElement("li");
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", String(o.selected));
      li.textContent = o.text;
      li.onmouseenter = () => setActive(i);
      li.onclick = () => pick(i);
      list.appendChild(li);
    });
    list.hidden = false;
    wrap.classList.add("open");
    btn.setAttribute("aria-expanded", "true");
    setActive(sel.selectedIndex);
  };

  btn.addEventListener("click", () => (list.hidden ? open() : close()));
  btn.addEventListener("keydown", (e) => {
    const n = sel.options.length;
    if (list.hidden) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); open(); }
      return;
    }
    if (e.key === "ArrowDown") { e.preventDefault(); setActive(Math.min(active + 1, n - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive(Math.max(active - 1, 0)); }
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(active); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }   // not the settings dialog
    else if (e.key === "Tab") close();
  });
  document.addEventListener("pointerdown", (e) => { if (!wrap.contains(e.target)) close(); });
  sel.addEventListener("change", sync);
  sync();
  return { sync };
}

// ---------------------------------------------------------------- toast
let toastTimer;
function toast(msg, isErr = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.toggle("err", isErr);
  t.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), isErr ? 7000 : 3500);
}

// ---------------------------------------------------------------- 3D viewer
const wrap = $("#canvasWrap");
const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.outputColorSpace = THREE.SRGBColorSpace;
wrap.prepend(renderer.domElement);

const scene = new THREE.Scene();
// lighting: "hangar" (dark hall with strip lights, like the game) or the original white "studio"
const envs = { studio: null, hangar: null };
const lightRig = { hemi: null, sun: null };
function setLighting(kind) {
  if (!envs[kind]) envs[kind] = kind === "hangar" ? hangarTexture(renderer)
    : new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environment = envs[kind];
  const h = kind === "hangar";
  renderer.toneMapping = h ? THREE.AgXToneMapping : THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = h ? 1.1 : 1.0;
  if (lightRig.hemi) {
    // the backdrop tints and scales the fill and key lights (space: warm or white sun, desk lamp, studio softbox)
    const b = backdrop?.light;
    lightRig.hemi.intensity = (h ? 0.25 : 0.6) * (b ? b.hemiK : 1);
    lightRig.hemi.color.set(b ? b.sky : 0xdde8ff);
    lightRig.hemi.groundColor.set(b ? b.ground : 0x202830);
    lightRig.sun.intensity = (h ? 2.2 : 1.4) * (b ? b.sunK : 1);
    lightRig.sun.color.set(b ? b.sun : 0xffffff);
  }
  updateShadows();
}
// shadows: always with the hangar light, and whenever the backdrop has a floor to cast them on
function updateShadows() {
  const on = state.light === "hangar" || !!backdrop?.hasGround;
  renderer.shadowMap.enabled = on;
  if (lightRig.sun) lightRig.sun.castShadow = on;
  modelRoot?.traverse((o) => {
    if (!o.isMesh) return;
    o.castShadow = on && meshKind(o) !== "decal" && !o.material.transparent;
    o.receiveShadow = on && !o.material.userData?.pom;
    o.material.needsUpdate = true;
  });
  backdrop?.group.traverse((o) => { if (o.isMesh) o.material.needsUpdate = true; });
  renderer.shadowMap.needsUpdate = true;
}
const camera = new THREE.PerspectiveCamera(40, 1, 0.001, 10000);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
lightRig.hemi = new THREE.HemisphereLight(0xdde8ff, 0x202830, 0.6);
scene.add(lightRig.hemi);
const sun = new THREE.DirectionalLight(0xffffff, 1.4);
sun.position.set(3, 5, 4);
sun.shadow.mapSize.set(4096, 4096);
sun.shadow.bias = -0.0002;
sun.shadow.normalBias = 0.02;
scene.add(sun, sun.target);
lightRig.sun = sun;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
// the shadow map is redrawn only when something moves (model loaded, animation playing, light changed), not on
// every frame: orbiting the camera does not change it
renderer.shadowMap.autoUpdate = false;

let gameLook = new GameLook(renderer);   // game-look materials (gamelook.js)
// what is drawn behind the model (backdrops.js); the choice is remembered
const backdrop = new Backdrops(scene, renderer, wrap);
try { backdrop.kind = BACKDROPS.includes(localStorage.getItem("vf.bg")) ? localStorage.getItem("vf.bg") : "plain"; } catch { /* storage unavailable */ }
// game props of the workshop backdrop: loaded once per session, with their own game-look textures (kept when the
// model changes, unlike the model's)
const propLook = new GameLook(renderer);
propLook.onChange = () => invalidate(100);
const propCache = new Map();
backdrop.loadProp = (path) => {
  if (!propCache.has(path)) {
    propCache.set(path, (async () => {
      const q = `path=${encodeURIComponent(path)}`;
      const [info, buf] = await Promise.all([
        api(`/api/model/info?${q}`).then((r) => r.json()),
        api(`/api/model/glb?${q}&anim=false&lite=true`).then((r) => r.arrayBuffer()),
      ]);
      const root = (await new GLTFLoader().parseAsync(buf, "")).scene;
      root.traverse((o) => {
        if (!o.isMesh) return;
        if (!o.geometry.attributes.normal) vertexNormals(o.geometry);
        o.visible = !["hidden", "screen"].includes(meshKind(o));     // collision proxies and dead screens
        o.receiveShadow = true;                                      // as placed in the room: compiled that way
        if (meshKind(o) === "glass") { o.material.transparent = true; o.material.opacity = 0.35; o.material.depthWrite = false; }
      });
      await propLook.apply(root, info.shading, { sun });
      // shaders compiled in parallel before the prop is shown (each prop used to freeze the view a moment as it arrived),
      // with and without the section plane: props stay for the next models, and an interior may be cut by a deck
      try { await compileShaders(root, true); } catch { /* compiled at its first frame instead */ }
      return root;
    })().catch((e) => { propCache.delete(path); throw e; }));
  }
  return propCache.get(path);
};
let grid = null;
let modelRoot = null;
let wireframe = false;
setLighting(state.light);
document.querySelector('[data-act="light"]')?.classList.toggle("on", state.light === "hangar");

// render on demand (see the render loop below): frames are drawn until `renderUntil`
let renderUntil = 0;           // keep drawing until this time (ms)
let lastRender = 0;
// After anything changed, frames go on for a while before the loop goes idle. In the desktop app (Qt WebEngine) a
// frame composed while the GPU is busy can reach the window half drawn (3D view without the panels, which Chromium
// draws last); it stays on screen until the next frame, i.e. up to the 1 s safety frame when nothing else draws.
// Drawing on for 2 s replaces it within a frame (tools/flash_check.py: 9 flashes in 2 Perseus rounds -> 0).
const RENDER_TAIL = 2000;
let tailUntil = 0;
const stats = { frames: 0 };   // frames actually drawn (for checks: __verseforge.stats)
function invalidate(ms = 0) { renderUntil = Math.max(renderUntil, performance.now() + ms); }

// Part of the canvas hidden behind the floating panels (the viewer fills the whole window):
// the camera is shifted so the model is centred in the area that stays visible.
function covered() {
  const w = wrap.clientWidth, h = wrap.clientHeight;
  if (getComputedStyle(wrap.parentElement).position !== "fixed") return { l: 0, r: 0, t: 0, w, h };
  const vis = (el) => el && el.offsetParent !== null ? el.getBoundingClientRect() : null;
  const side = vis($(".sidebar")), panel = vis($(".panel")), top = vis($(".topbar"));
  return { l: side ? side.right : 0, r: panel ? w - panel.left : 0, t: top ? top.bottom : 0, w, h };
}

function resize() {
  const { l, r, t, w, h } = covered();
  renderer.setSize(w, h, false);
  camera.aspect = w / Math.max(h, 1);
  if (l || r || t) camera.setViewOffset(w, h, (r - l) / 2, -t / 2, w, h);
  else camera.clearViewOffset();
  camera.updateProjectionMatrix();
  invalidate();
}
new ResizeObserver(resize).observe(wrap);
window.addEventListener("resize", resize);
resize();

// animation state (see "animations" below); declared here because the render loop starts right away
const anim = { mixer: null, clips: new Map(), list: [], actions: new Map(), current: null, dragging: false, landed: null };
const clock = new THREE.Clock();
let ammoScreen = null;   // weapon display drawn on its DisplayScreen (screen.js)
window.__verseforge = { get root() { return modelRoot; }, anim, get screen() { return ammoScreen; },
  camera, controls, renderer, scene, frame: () => frame(), load: (item) => loadModel(item), state: () => state, setLighting,
  get backdrop() { return backdrop; }, get look() { return gameLook; }, stats, invalidate: (ms) => invalidate(ms), tick: () => tick() };   // for automated checks (tools/, tests)
// Render on demand: a frame is drawn only when something changed (camera moving or settling, an animation or the
// auto-rotate running, a texture/material update, a shadow redraw request, an explicit invalidate()), plus once a
// second as a safety net. A still model leaves the GPU idle instead of redrawing it 60 times a second.
// textures and materials announce their changes through `needsUpdate`: listen to it (texture loads, the ammo
// screen's canvas, game-look materials being built)
for (const proto of [THREE.Texture.prototype, THREE.Material.prototype]) {
  const d = Object.getOwnPropertyDescriptor(proto, "needsUpdate");
  if (d?.set) Object.defineProperty(proto, "needsUpdate", { ...d, set(v) { d.set.call(this, v); if (v) invalidate(); } });
}
let holdRender = false;        // true while a model is being sent to the GPU piece by piece (warmUp)
function tick() {
  const dt = clock.getDelta();
  const now = performance.now();
  if (holdRender) return;
  let draw = now <= renderUntil;
  if (anim.mixer) {
    const running = anim.dragging || anim.mixer._actions.some((a) => a.isRunning());
    if (running || now <= renderUntil) {
      anim.mixer.update(dt);
      syncTimeline();
    }
    if (running) {
      draw = true;
      if (renderer.shadowMap.enabled) renderer.shadowMap.needsUpdate = true;
    }
  }
  if (controls.update()) draw = true;          // true while the camera moves (dragging, damping, auto-rotate)
  if (controls.autoRotate || renderer.shadowMap.needsUpdate) draw = true;
  if (draw) tailUntil = now + RENDER_TAIL;     // something changed: keep drawing for a while after it
  else if (now > tailUntil && now - lastRender <= 1000) return;
  renderer.render(scene, camera);
  lastRender = now;
  stats.frames++;
}
renderer.setAnimationLoop(tick);
// user input on the canvas: keep drawing a little while (the camera's damping finishes after the pointer stops)
for (const ev of ["pointerdown", "pointermove", "wheel"]) renderer.domElement.addEventListener(ev, () => invalidate(300), { passive: true });
// any click or change in the panels (animations, rest pose, layers, menus) may change the scene: a few frames
for (const ev of ["click", "input", "change", "keydown"]) document.addEventListener(ev, () => invalidate(400), { passive: true });

function frame() {
  if (!modelRoot) return;
  const box = new THREE.Box3().setFromObject(modelRoot);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const radius = Math.max(size.length() / 2, 0.01);
  // fit the bounding sphere both vertically and horizontally inside the visible part of the canvas
  const { l, r, t, w, h } = covered();
  const half = THREE.MathUtils.degToRad(camera.fov / 2);
  const halfH = Math.atan(Math.tan(half) * camera.aspect);
  const dist = Math.max(radius / Math.sin(half) * h / Math.max(h - t, 1),
                        radius / Math.sin(halfH) * w / Math.max(w - l - r, 1)) * 1.05;
  camera.near = dist / 1000;
  camera.far = dist * 100;
  camera.updateProjectionMatrix();
  // three/quarter view from the front-left (models are Y-up, forward = -Z after export)
  camera.position.copy(center).add(new THREE.Vector3(-0.9, 0.55, -1.0).normalize().multiplyScalar(dist));
  controls.target.copy(center);
  controls.update();
  placeSun(center, radius);
}

// Send a model's geometry, textures and shaders to the GPU a few pieces at a time before its first real frame: the
// first frame of a big interior used to do it all at once and froze the page for 1-2 s. Each piece is drawn on its
// own into a 1x1 corner of the canvas (layer 31, lights included): the same canvas and the same tone mapping as a real
// frame, so exactly the shaders the real frames will use get built. With shadows on, each piece also goes through
// the shadow pass alone (the lights' shadow cameras look at layer 31 only), which builds the shadow shaders three.js
// makes internally; the real shadow map is redrawn whole afterwards. Normal frames are held meanwhile.
const WARM_LAYER = 31;
async function warmUp(root, cancelled) {
  const meshes = [];
  root.traverse((o) => { if (o.isMesh && o.visible) meshes.push(o); });
  if (meshes.length < 2) return;
  const cam = camera.clone();
  cam.layers.set(WARM_LAYER);
  const lights = [], shadowCams = [];
  scene.traverse((o) => {
    if (!o.isLight) return;
    if (!o.layers.isEnabled(WARM_LAYER)) { o.layers.enable(WARM_LAYER); lights.push(o); }
    if (o.castShadow && o.shadow?.camera) { shadowCams.push([o.shadow.camera, o.shadow.camera.layers.mask]); o.shadow.camera.layers.set(WARM_LAYER); }
  });
  const shadows = renderer.shadowMap.enabled && shadowCams.length > 0;
  const bg = scene.background;
  const vp = renderer.getViewport(new THREE.Vector4()), sc = renderer.getScissor(new THREE.Vector4());
  const scTest = renderer.getScissorTest(), autoClear = renderer.autoClear;
  holdRender = true;
  const shadowWanted = renderer.shadowMap.needsUpdate;
  try {
    scene.background = null;                     // nothing else to draw in the warm-up passes
    renderer.autoClear = false;
    renderer.setViewport(0, 0, 1, 1);
    renderer.setScissor(0, 0, 1, 1);
    renderer.setScissorTest(true);
    let i = 0;
    while (i < meshes.length && !cancelled()) {
      const t0 = performance.now();
      while (i < meshes.length && performance.now() - t0 < 12) {
        const m = meshes[i++];
        const culled = m.frustumCulled;
        m.frustumCulled = false;
        m.layers.enable(WARM_LAYER);
        renderer.shadowMap.needsUpdate = shadows;      // this piece alone in the shadow pass
        renderer.render(scene, cam);
        m.layers.disable(WARM_LAYER);
        m.frustumCulled = culled;
      }
      await new Promise((r) => setTimeout(r, 0));
    }
  } finally {
    renderer.setViewport(vp);
    renderer.setScissor(sc);
    renderer.setScissorTest(scTest);
    renderer.autoClear = autoClear;
    for (const l of lights) l.layers.disable(WARM_LAYER);
    for (const [c, mask] of shadowCams) c.layers.mask = mask;
    scene.background = bg;
    renderer.shadowMap.needsUpdate = shadowWanted || shadows || renderer.shadowMap.needsUpdate;
    holdRender = false;
    invalidate();
  }
}

// the backdrop's floor goes under the model as it stands now (a full ship has its landing gear down by then)
function fitBackdrop() {
  if (!modelRoot) return;
  modelRoot.updateMatrixWorld(true);
  backdrop.fit(new THREE.Box3().setFromObject(modelRoot));
  updateShadows();
}
backdrop.onChange = (full = true) => {
  if (!full) { renderer.shadowMap.needsUpdate = true; return; }      // a workshop prop arrived
  setLighting(state.light);
  if (modelRoot) {
    const box = new THREE.Box3().setFromObject(modelRoot);
    placeSun(box.getCenter(new THREE.Vector3()), Math.max(box.getSize(new THREE.Vector3()).length() / 2, 0.01));
    if (grid) grid.visible = $('[data-act="grid"]').classList.contains("on") && !backdrop.hasGround;
  }
  document.querySelectorAll("#bgMenu [data-bg]").forEach((b) => b.classList.toggle("on", b.dataset.bg === backdrop.kind));
  $('[data-act="bg"]').classList.toggle("on", backdrop.kind !== "plain");
};

// key light: from the backdrop's side (space sun, desk lamp…); with a floor the shadow map also covers the ground
function placeSun(center, radius) {
  const d = backdrop.light?.dir || [2, 3, 2.5];
  sun.position.copy(center).add(new THREE.Vector3(d[0], d[1], d[2]).multiplyScalar(radius));
  sun.target.position.copy(center);
  const sc = sun.shadow.camera, span = backdrop.hasGround ? 2.2 : 1.1;
  sc.left = sc.bottom = -radius * span; sc.right = sc.top = radius * span;
  sc.near = radius * 0.5; sc.far = radius * 10;
  sc.updateProjectionMatrix();
  sun.shadow.normalBias = radius * 0.0015;
  renderer.shadowMap.needsUpdate = true;
}

function cssColor(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v ? new THREE.Color(v) : new THREE.Color(fallback);
}

function buildGrid(box) {
  invalidate();
  if (grid) scene.remove(grid);
  const size = box.getSize(new THREE.Vector3());
  const span = Math.max(size.x, size.z) * 1.6;
  const step = Math.pow(10, Math.floor(Math.log10(span / 10)));
  const cells = Math.ceil(span / step);
  grid = new THREE.GridHelper(cells * step, cells, cssColor("--grid-major", "#2f4a60"), cssColor("--grid-minor", "#1c2a36"));
  grid.position.set((box.min.x + box.max.x) / 2, box.min.y, (box.min.z + box.max.z) / 2);
  grid.visible = $('[data-act="grid"]').classList.contains("on") && !backdrop.hasGround;   // the floor has its own
  scene.add(grid);
}

function meshKind(obj) {
  const n = obj.name || obj.parent?.name || "";
  return n.split("|")[0] || "solid";
}
function meshMat(obj) {
  const n = obj.name || obj.parent?.name || "";
  return n.split("|")[1] || n;
}

function applyVisibility() {
  invalidate();
  if (!modelRoot) return;
  modelRoot.traverse((o) => {
    if (!o.isMesh) return;
    const kind = meshKind(o);
    const kindOn = kind === "solid" ? true : state.kinds[kind] ?? true;
    o.visible = kindOn && !state.matOff.has(meshMat(o));
  });
}

function applyWireframe() {
  invalidate();
  modelRoot?.traverse((o) => { if (o.isMesh) o.material.wireframe = wireframe; });
}

// loading overlay: pct null = indeterminate bar (waiting for the server), else 0-100
function progress(pct, stage) {
  const bar = $(".load-bar");
  bar.classList.toggle("indeterminate", pct == null);
  $("#loadBarFill").style.width = pct == null ? "" : `${Math.max(2, Math.min(100, pct)).toFixed(1)}%`;
  $("#loadPct").textContent = pct == null ? "" : `${Math.round(pct)}%`;
  $("#loadStage").textContent = stage || "";
}

// read a fetch Response to an ArrayBuffer, reporting (bytes so far, total | 0) as chunks arrive
async function readWithProgress(res, onProgress) {
  const total = +res.headers.get("Content-Length") || 0;
  if (!res.body || !res.body.getReader) return res.arrayBuffer();
  const reader = res.body.getReader();
  const chunks = [];
  let done = 0, last = 0;
  for (;;) {
    const { done: end, value } = await reader.read();
    if (end) break;
    chunks.push(value);
    done += value.length;
    const now = performance.now();
    if (now - last > 50) { onProgress(done, total); last = now; }
  }
  onProgress(done, total);
  const out = new Uint8Array(done);
  let off = 0;
  for (const c of chunks) { out.set(c, off); off += c.length; }
  return out.buffer;
}

async function loadModel(item, keepView = false) {
  if (state.current?.path !== item.path) state.variant = null;
  state.current = item;
  if (!keepView) state.matOff.clear();
  const v = (state.variant != null ? `&variant=${encodeURIComponent(state.variant)}` : "") + `&full=${state.full}` +
    `&interior=${state.interior}`;
  document.querySelectorAll(".results li").forEach((li) => li.classList.toggle("active", li.dataset.path === item.path));
  $("#empty").classList.add("hidden");
  $("#loading").classList.remove("hidden");
  $("#loadingText").textContent = T("loadingOf", { name: item.name });
  progress(null, T("loadPrepare"));
  if (!keepView) $("#info").innerHTML = infoHead(item) + `<p class="hint">${T("loading")}</p>`;
  try {
    const [infoRes, glbRes] = await Promise.all([
      api(`/api/model/info?path=${encodeURIComponent(item.path)}${v}`),
      // lite: the game look loads its own textures, and normals are computed here (a third of the file)
      api(`/api/model/glb?path=${encodeURIComponent(item.path)}&tex=${state.tex}&lite=${state.tex && state.look}${v}`),
    ]);
    if (state.current !== item) return;  // user clicked something else meanwhile
    const info = await infoRes.json();
    state.variant = info.variant;
    // download: 0-70 % of the bar, parsing 70-75 %, game textures 75-100 %
    const buf = await readWithProgress(glbRes, (done, total) => {
      if (state.current !== item) return;
      const mb = (n) => (n / 1048576).toFixed(n < 10485760 ? 1 : 0);
      if (total) progress(70 * done / total, T("loadDownload", { done: mb(done), total: mb(total) }));
      else progress(null, T("loadDownloadNoSize", { done: mb(done) }));
    });
    if (state.current !== item) return;
    progress(70, T("loadScene"));
    const gltf = await new GLTFLoader().parseAsync(buf, "");
    if (state.current !== item) return;
    // normals of the lite GLB, computed mesh by mesh with breaks so the page keeps breathing on big interiors
    const noNormals = [];
    gltf.scene.traverse((o) => { if (o.isMesh && !o.geometry.attributes.normal) noNormals.push(o.geometry); });
    let slice = performance.now();
    for (const g of noNormals) {
      vertexNormals(g);
      if (performance.now() - slice > 12) { await new Promise((r) => setTimeout(r, 0)); slice = performance.now(); }
    }
    if (state.current !== item) return;
    progress(75, T("loadScene"));
    stopAnimations();
    ammoScreen?.dispose();
    ammoScreen = null;
    if (modelRoot) {
      scene.remove(modelRoot);
      modelRoot.traverse((o) => { if (o.isMesh) { o.geometry.dispose(); o.material.dispose(); } });
    }
    modelRoot = gltf.scene;
    gameLook.dispose();
    gameLook = new GameLook(renderer);
    gameLook.onProgress = (done, total) => {
      if (state.current === item && total) progress(75 + 25 * done / total, T("loadTextures", { done, total }));
    };
    gameLook.onChange = () => invalidate(100);   // a full-size texture took the place of its small copy
    if (state.tex && state.look) await gameLook.apply(modelRoot, info.shading, { swapNormalXY: state.swapXY, sun });
    if (state.current !== item) return;
    modelRoot.traverse((o) => {
      if (o.isMesh) {
        // decals lie on the hull: they neither cast shadows nor need the shadow pass
        o.castShadow = renderer.shadowMap.enabled && meshKind(o) !== "decal" && !o.material.transparent;
        o.receiveShadow = renderer.shadowMap.enabled && !o.material.userData?.pom;
        o.material.side = THREE.DoubleSide;
        if (!o.material.isMeshPhysicalMaterial) o.material.envMapIntensity = 0.6;   // plain GLB look
        if (meshKind(o) === "glass") { o.material.transparent = true; o.material.opacity = 0.35; o.material.depthWrite = false; }
      }
    });
    // compile the shaders before the model is shown, in parallel and without blocking the page
    // (KHR_parallel_shader_compile): compiling them all in the first frame froze the view for 1-2 s on big ships
    progress(99, T("loadShaders"));
    try { await compileShaders(modelRoot, !!info.interior); } catch { /* compiled at the first frame instead */ }
    if (state.current !== item) return;
    scene.add(modelRoot);
    await warmUp(modelRoot, () => state.current !== item);
    if (state.current !== item) return;
    anim.clips = new Map(gltf.animations.map((c) => [c.name, c]));
    anim.mixer = gltf.animations.length ? new THREE.AnimationMixer(modelRoot) : null;
    const screens = [];
    let anyScreen = false;
    modelRoot.traverse((o) => {
      if (!o.isMesh || meshKind(o) !== "screen") return;
      anyScreen = true;
      if (o.geometry.attributes.uv && !o.material.name.endsWith("|holo")) screens.push(o);   // HUD veils: no ammo
    });
    $("#scrPill").classList.toggle("hidden", !anyScreen);
    if (screens.length && info.ammo) ammoScreen = new AmmoScreen(screens, info.ammo, info.screen);
    applyWireframe();
    applyVisibility();
    buildGrid(new THREE.Box3().setFromObject(modelRoot));
    renderer.shadowMap.needsUpdate = true;
    if (!keepView) frame();
    showInfo(item, info);
    showMaterials();
    showAnimations(info.animations || []);
    anim.landed = info.full ? anim.list.find((a) => /land/i.test(a.group) && /^(deploy|extend|open)$/i.test(a.label)) : null;
    settleLanded();
    fitBackdrop();
    // the section plane cuts the whole scene: the backdrop's room (rebuilt for each model) and the grid need their
    // section shaders too
    if (info.interior) for (const o of [backdrop.group, grid]) compileShaders(o, true).catch(() => {});
    renderer.shadowMap.needsUpdate = true;
    $("#fullPill").classList.toggle("hidden", !info.can_full);
    $("#intPill").classList.toggle("hidden", !info.can_interior);
    $("#cutBox").classList.toggle("hidden", !info.interior);
    sectionBox = info.interior ? new THREE.Box3().setFromObject(modelRoot) : null;
    buildDecks(info.decks || []);
    applySection();
    $("#fullLabel").textContent = info.ground_vehicle ? "Full vehicle" : "Full ship";
    loadRelated(item);
  } catch (e) {
    $("#info").innerHTML = infoHead(item) + `<p class="warn">${esc(e.message)}</p>`;
    toast(T("loadFailed", { error: e.message }), true);
  } finally {
    $("#loading").classList.add("hidden");
  }
}

function fmtLen(m) {
  if (m >= 10) return `${m.toFixed(2)}<small>m</small>`;
  if (m >= 1) return `${m.toFixed(3)}<small>m</small>`;
  return `${(m * 1000).toFixed(1)}<small>mm</small>`;
}

function infoHead(item) {
  const sub = item.subtitle || CAT_LABELS[item.category] || "";
  return `<div class="info-head">
      ${sub ? `<div class="eyebrow">${esc(sub)}</div>` : ""}
      <h2>${esc(item.name)}</h2>
      <div class="path" title="${esc(item.path)}">${esc(item.path)}</div>
    </div>`;
}

function showInfo(item, info) {
  const s = info.stats;
  const [x, y, z] = s.size_m;
  const stat = (k, v) => `<div class="stat"><span class="k">${T(k)}</span><span class="v">${v}</span></div>`;
  $("#info").innerHTML = `${infoHead(item)}
    <div class="stats">
      ${stat("width", fmtLen(x))}${stat("length", fmtLen(y))}${stat("height", fmtLen(z))}
      ${stat("triangles", num(s.triangles))}${stat("parts", s.parts)}${stat("materials", s.materials.length)}
    </div>
    ${info.variants.length > 1 ? `<div class="variant"><span>${T("variant")}</span>
      <select id="variantSel">${info.variants.map((v) => `<option value="${esc(v.tag)}"${v.tag === info.variant ? " selected" : ""}>${esc(v.label)}</option>`).join("")}</select></div>` : ""}
    ${info.warnings.map((w) => `<div class="warn">${esc(w)}</div>`).join("")}`;
  const variantSel = $("#variantSel");
  if (variantSel) {
    dropdown(variantSel);
    variantSel.addEventListener("change", (e) => {
      state.variant = e.target.value;
      loadModel(state.current, true);
    });
  }
  $("#exportBox").classList.remove("hidden");
  $("#printBox").classList.remove("hidden");
}

function showMaterials() {
  const mats = new Map();
  modelRoot.traverse((o) => {
    if (!o.isMesh) return;
    const name = meshMat(o);
    // shader materials (POM decal overlays) have no .color: they keep the GLB colour in userData.swatch
    const c = o.material.color || o.material.userData?.swatch;
    if (!mats.has(name)) mats.set(name, { kind: meshKind(o), color: c ? c.getHexString() : "888888" });
  });
  const ul = $("#mats");
  ul.innerHTML = "";
  [...mats.entries()].sort().forEach(([name, m]) => {
    const li = document.createElement("li");
    li.innerHTML = `<span class="swatch" style="background:#${m.color}"></span><span class="mname">${esc(name)}</span><span class="kind">${KIND_LABELS[m.kind] ? T(KIND_LABELS[m.kind]) : ""}</span>`;
    li.title = name;
    li.classList.toggle("off", state.matOff.has(name));
    li.onclick = () => {
      state.matOff.has(name) ? state.matOff.delete(name) : state.matOff.add(name);
      li.classList.toggle("off", state.matOff.has(name));
      applyVisibility();
    };
    ul.appendChild(li);
  });
  $("#matCount").textContent = mats.size;
  $("#matBox").classList.toggle("hidden", mats.size === 0);
}

// ---------------------------------------------------------------- animations
// Several actions can stay applied at once (canopy open + gear down); a new action only replaces the ones that
// move the same nodes. Each action ends clamped on its last frame, so "Open" leaves the part open.
function stopAnimations() {
  if (anim.mixer) { anim.mixer.stopAllAction(); if (modelRoot) anim.mixer.uncacheRoot(modelRoot); }
  anim.mixer = null;
  anim.actions.clear();
  anim.current = null;
}

// a full ship starts "landed": the legs are modelled extended, so the gear doors open to match them
function settleLanded() {
  if (!anim.landed || !anim.mixer) return;
  playAnimation(anim.landed);
  const c = anim.current;
  c.act.time = c.act.timeScale < 0 ? 0 : c.clip.duration;
  anim.mixer.update(0);
  renderer.shadowMap.needsUpdate = true;
}

const trackNodes = (clip) => new Set(clip.tracks.map((t) => t.name.split(".")[0]));

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function showAnimations(list) {
  anim.list = list.filter((a) => anim.clips.has(a.clip));
  $("#animBox").classList.toggle("hidden", !anim.list.length);
  $("#expAnimRow").classList.toggle("hidden", !anim.list.length);
  $("#animCount").textContent = anim.list.length || "";
  const groups = new Map();
  anim.list.forEach((a) => { if (!groups.has(a.group)) groups.set(a.group, []); groups.get(a.group).push(a); });
  const root = $("#animGroups");
  root.replaceChildren();
  groups.forEach((acts, g) => {
    const row = el("div", "anim-group");
    const label = el("span", "g", g);
    label.title = g;
    const buttons = el("span", "acts");
    acts.forEach((a) => {
      const b = el("button", "anim-act", a.label);
      b.title = `${a.group} · ${a.label} — ${a.duration.toFixed(1)} s` + (a.speed < 0 ? " (reversed)" : "");
      b.dataset.id = a.id;
      b.onclick = () => playAnimation(a);
      buttons.appendChild(b);
    });
    row.append(label, buttons);
    root.appendChild(row);
  });
  resetTimeline();
}

function resetTimeline() {
  $("#animPlay").disabled = $("#animTime").disabled = true;
  $("#animTime").value = 0;
  $("#animClock").textContent = "0.0 s";
  setPlayIcon(false);
}

function setPlayIcon(playing) {
  $("#animPlay use").setAttribute("href", playing ? "#i-pause" : "#i-play");
}

function playAnimation(a) {
  const clip = anim.clips.get(a.clip);
  if (!clip || !anim.mixer) return;
  const nodes = trackNodes(clip);
  for (const [id, act] of anim.actions) {
    const other = act.getClip();
    if (other === clip || [...trackNodes(other)].some((n) => nodes.has(n))) { act.stop(); anim.actions.delete(id); }
  }
  const act = anim.mixer.clipAction(clip);
  act.reset();
  act.setLoop($("#animLoop").checked ? THREE.LoopRepeat : THREE.LoopOnce, Infinity);
  act.clampWhenFinished = true;
  act.timeScale = a.speed || 1;
  // backwards: start a hair before the end, or a LoopOnce action counts as already finished on its first update
  if (act.timeScale < 0) act.time = Math.max(clip.duration - 1e-3, 0);
  act.play();
  anim.actions.set(a.id, act);
  anim.current = { a, act, clip };
  if (ammoScreen && isReload(a)) ammoScreen.reload(clip.duration / Math.abs(act.timeScale || 1) * 0.6);
  else if (ammoScreen && isFire(a)) ammoScreen.fire();
  document.querySelectorAll(".anim-act").forEach((b) => b.classList.toggle("on", b.dataset.id === a.id));
  $("#animPlay").disabled = $("#animTime").disabled = false;
}

const animRunning = (c) => c && !c.act.paused && c.act.isRunning();

function syncTimeline() {
  const c = anim.current;
  setPlayIcon(animRunning(c));
  if (!c) return;
  const d = c.clip.duration || 1;
  const t = Math.min(Math.max(c.act.time, 0), d);
  if (!anim.dragging) $("#animTime").value = Math.round((t / d) * 1000);
  $("#animClock").textContent = `${t.toFixed(1)} / ${d.toFixed(1)} s`;
}

$("#animPlay").addEventListener("click", () => {
  const c = anim.current;
  if (!c) return;
  if (animRunning(c)) { c.act.paused = true; return; }
  const d = c.clip.duration;
  const atEnd = c.act.timeScale > 0 ? c.act.time >= d - 1e-3 : c.act.time <= 1e-3;
  if (atEnd) { playAnimation(c.a); return; }
  c.act.paused = false;
  c.act.enabled = true;
  c.act.play();
});
$("#animTime").addEventListener("input", (e) => {
  const c = anim.current;
  if (!c) return;
  anim.dragging = true;
  c.act.paused = true;
  c.act.enabled = true;
  c.act.time = (e.target.value / 1000) * c.clip.duration;
  anim.mixer.update(0);
});
$("#animTime").addEventListener("change", () => { anim.dragging = false; });
$("#animLoop").addEventListener("change", (e) => {
  anim.actions.forEach((act) => act.setLoop(e.target.checked ? THREE.LoopRepeat : THREE.LoopOnce, Infinity));
});
$("#animReset").addEventListener("click", () => {
  if (!anim.mixer) return;
  anim.mixer.stopAllAction();
  anim.actions.clear();
  anim.current = null;
  document.querySelectorAll(".anim-act").forEach((b) => b.classList.remove("on"));
  resetTimeline();
  ammoScreen?.reset();
  settleLanded();
  renderer.shadowMap.needsUpdate = true;
});

async function loadRelated(item) {
  try {
    const list = await (await api(`/api/related?path=${encodeURIComponent(item.path)}`)).json();
    const others = list.filter((r) => r.path !== item.path);
    const ul = $("#related");
    ul.innerHTML = "";
    others.forEach((r) => {
      const li = document.createElement("li");
      li.innerHTML = `<span class="mname">${esc(r.path.split("/").pop())}</span><span class="badge">${r.ext}</span>`;
      li.title = r.name;
      li.onclick = () => loadModel(r);
      ul.appendChild(li);
    });
    $("#relCount").textContent = others.length;
    $("#relBox").classList.toggle("hidden", others.length === 0);
  } catch { $("#relBox").classList.add("hidden"); }
}

// ---------------------------------------------------------------- toolbar
document.querySelectorAll(".toolbar [data-act]").forEach((b) => b.addEventListener("click", () => act(b.dataset.act, b)));
// backdrop menu (opens above the toolbar button)
document.querySelectorAll("#bgMenu [data-bg]").forEach((b) => b.addEventListener("click", async () => {
  $("#bgMenu").classList.add("hidden");
  try { localStorage.setItem("vf.bg", b.dataset.bg); } catch { /* storage unavailable */ }
  try {
    await backdrop.set(b.dataset.bg);
  } catch (e) {
    toast(T("loadFailed", { error: e.message }), true);
    await backdrop.set("plain");
  }
}));
document.addEventListener("pointerdown", (e) => {
  if (!e.target.closest(".bg-wrap")) $("#bgMenu").classList.add("hidden");
});
// the space panoramas come from the game files: a saved one is put back once the catalogue is ready (pollStatus)
const savedBackdrop = backdrop.kind;
backdrop.set(["pyro", "stanton", "workbench"].includes(savedBackdrop) ? "plain" : savedBackdrop);
function act(a, b = document.querySelector(`[data-act="${a}"]`)) {
  if (a === "reset") frame();
  if (a === "wire") { wireframe = !wireframe; b.classList.toggle("on", wireframe); applyWireframe(); }
  if (a === "rotate") { controls.autoRotate = !controls.autoRotate; b.classList.toggle("on", controls.autoRotate); }
  if (a === "grid") { b.classList.toggle("on"); if (grid) grid.visible = b.classList.contains("on") && !backdrop.hasGround; invalidate(); }
  if (a === "light") {
    state.light = state.light === "hangar" ? "studio" : "hangar";
    b.classList.toggle("on", state.light === "hangar");
    try { localStorage.setItem("vf.light", state.light); } catch { /* storage unavailable */ }
    setLighting(state.light);
  }
  if (a === "bg") $("#bgMenu").classList.toggle("hidden");
  if (a === "shot") {
    const link = document.createElement("a");
    link.download = `${(state.current?.path.split("/").pop() || "model").replace(/\.\w+$/, "")}.png`;
    link.href = renderer.domElement.toDataURL("image/png");
    link.click();
  }
}
// "Interiors": the ship's rooms, seen through a horizontal section (clipping plane) set with the slider
let sectionBox = null;
const sectionPlane = new THREE.Plane(new THREE.Vector3(0, -1, 0), 0);
// The section plane needs its own version of every shader. Left to the first deck click, they were all compiled in
// one frame (Perseus interior 1.7 s) and the desktop window showed the 3D view without its panels meanwhile.
// three.js compiles for the clipping state of the last frame it drew (compile() does not set it up): an empty frame
// drawn off screen into a 1x1 target sets that state, so compileAsync can build each variant in parallel.
const clipProbe = { target: new THREE.WebGLRenderTarget(1, 1), scene: new THREE.Scene() };
function setClipState(planes) {
  const target = renderer.getRenderTarget(), own = renderer.clippingPlanes;
  renderer.clippingPlanes = planes;
  renderer.setRenderTarget(clipProbe.target);
  renderer.render(clipProbe.scene, camera);
  renderer.setRenderTarget(target);
  renderer.clippingPlanes = own;
}
// compile `root`'s shaders without the section plane and, if `section`, with it too
async function compileShaders(root, section) {
  if (!root) return;
  const own = renderer.clippingPlanes, jobs = [];
  try {
    for (const planes of section ? [[], [sectionPlane]] : [[]]) {
      setClipState(planes);
      jobs.push(renderer.compileAsync(root, camera, scene));
    }
  } finally {
    setClipState(own);
  }
  await Promise.all(jobs);
}
function applySection() {
  const on = !!sectionBox && state.cut < 0.999;
  if (on) sectionPlane.constant = THREE.MathUtils.lerp(sectionBox.min.y, sectionBox.max.y, state.cut);
  renderer.clippingPlanes = on ? [sectionPlane] : [];
  $("#cut").value = Math.round(state.cut * 1000);
  $("#cutVal").textContent = `${Math.round(state.cut * 100)}%`;
  document.querySelectorAll("#decks button").forEach((b) => b.classList.remove("on"));
  renderer.shadowMap.needsUpdate = true;
}
try { state.interior = sessionStorage.getItem("vf.int") === "1"; } catch { /* storage unavailable */ }
$("#intOn").checked = state.interior;
$("#intOn").addEventListener("change", (e) => {
  state.interior = e.target.checked;
  try { sessionStorage.setItem("vf.int", state.interior ? "1" : "0"); } catch { /* storage unavailable */ }
  if (state.current) loadModel(state.current, true);
});
$("#cut").addEventListener("input", (e) => { state.cut = e.target.value / 1000; applySection(); });

// Decks: the ship's floors, found by the server in the interior (info.decks, floor heights in metres). Each deck
// button cuts the ship just under that deck's ceiling: everything above is taken away, the deck stays whole.
const DECK_HEADROOM = 2.4;
function buildDecks(floors = []) {
  const box = $("#decks");
  box.replaceChildren();
  if (!sectionBox) floors = [];
  box.hidden = floors.length < 2;
  if (box.hidden) return;
  const span = sectionBox.max.y - sectionBox.min.y;
  const mk = (label, title, cut) => {
    const btn = document.createElement("button");
    btn.textContent = label;
    btn.title = title;
    btn.onclick = () => { state.cut = cut; applySection(); btn.classList.add("on"); };
    box.appendChild(btn);
  };
  floors.forEach((f, i) => {
    const top = Math.min(f + DECK_HEADROOM, (floors[i + 1] ?? Infinity) - 0.2);
    mk(String(i + 1), `Deck ${i + 1}: remove everything above it`, Math.min(1, (top - sectionBox.min.y) / span));
  });
  mk("All", "Whole ship", 1);
}

// "Full ship": remembered for the session, shown only for ships and vehicles that have a factory loadout
try { state.full = sessionStorage.getItem("vf.full") === "1"; } catch { /* storage unavailable */ }
$("#fullOn").checked = state.full;
$("#fullOn").addEventListener("change", (e) => {
  state.full = e.target.checked;
  try { sessionStorage.setItem("vf.full", state.full ? "1" : "0"); } catch { /* storage unavailable */ }
  if (state.current) loadModel(state.current, true);
});
$("#texOn").checked = state.tex;
$("#texOn").addEventListener("change", (e) => {
  state.tex = e.target.checked;
  try { localStorage.setItem("vf.tex", state.tex ? "1" : "0"); } catch { /* storage unavailable */ }
  if (state.current) loadModel(state.current, true);
});
document.querySelectorAll("[data-kind]").forEach((c) => c.addEventListener("change", () => {
  state.kinds[c.dataset.kind] = c.checked;
  applyVisibility();
}));
window.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
  const k = { f: "reset", w: "wire", r: "rotate", g: "grid" }[e.key.toLowerCase()];
  if (k) act(k);
});

// ---------------------------------------------------------------- export
document.querySelectorAll("[data-exp]").forEach((b) => b.addEventListener("click", async () => {
  if (!state.current) return;
  const fmt = b.dataset.exp;
  b.disabled = true;
  try {
    const url = `/api/export?path=${encodeURIComponent(state.current.path)}&fmt=${fmt}&decals=${$("#expDecals").checked}&tex=${$("#expTex").checked}&anim=${$("#expAnim").checked}&full=${state.full}&interior=${state.interior}` +
      (state.variant != null ? `&variant=${encodeURIComponent(state.variant)}` : "");
    const r = await api(url);
    const blob = await r.blob();
    const name = (r.headers.get("Content-Disposition") || "").match(/filename="(.+)"/)?.[1] || `model.${fmt}`;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    toast(T("exported", { name, dir: r.headers.get("X-Saved-To") || T("exportsDir") }));
  } catch (e) {
    toast(T("exportFailed", { error: e.message }), true);
  } finally {
    b.disabled = false;
  }
}));

$("#btnPrint").addEventListener("click", async () => {
  if (!state.current) return;
  const btn = $("#btnPrint");
  btn.disabled = true;
  const voxel = parseFloat($("#voxel").value) || 0;
  try {
    const job = await (await api(`/api/print?path=${encodeURIComponent(state.current.path)}&voxel=${voxel}&fill=${$("#fill").checked}&full=${state.full}`, { method: "POST" })).json();
    pollPrint(job.id, state.current.name);
  } catch (e) {
    toast(e.message, true);
    btn.disabled = false;
  }
});

async function pollPrint(id, name) {
  const out = $("#printStatus");
  try {
    const job = await (await api(`/api/print/${id}`)).json();
    if (job.state === "running") {
      out.textContent = `${job.message} (${Math.round(job.progress * 100)}%)`;
      setTimeout(() => pollPrint(id, name), 1500);
      return;
    }
    $("#btnPrint").disabled = false;
    if (job.state === "error") {
      out.textContent = "";
      toast(T("print3d", { error: job.message }), true);
      return;
    }
    const i = job.info || {};
    out.innerHTML = `${esc(T("printReady", { size: i.size_mm?.join(" × "), volume: i.volume_cm3, closed: T(i.watertight ? "closedYes" : "closedNo") }))} <a href="/api/print/${id}/file">${T("downloadStl")}</a>`;
    toast(T("printDone", { name }));
  } catch (e) {
    $("#btnPrint").disabled = false;
    out.textContent = e.message;
  }
}

$("#btnOpenExports").addEventListener("click", () => api("/api/open-exports", { method: "POST" }).catch((e) => toast(e.message, true)));

// ---------------------------------------------------------------- search
let searchTimer, searchSeq = 0;
function scheduleSearch() { clearTimeout(searchTimer); searchTimer = setTimeout(runSearch, 180); }

async function runSearch() {
  const seq = ++searchSeq;
  const q = $("#q").value.trim();
  const params = new URLSearchParams({ q, cat: state.cat, sub: state.sub, main: $("#mainOnly").checked, limit: 400 });
  try {
    const data = await (await api(`/api/search?${params}`)).json();
    if (seq !== searchSeq) return;
    renderResults(data);
  } catch (e) {
    $("#count").textContent = e.message;
  }
}

function renderResults({ total, items }) {
  $("#count").textContent = total > items.length ? T("resultsOf", { n: num(total), shown: items.length }) : T("results", { n: num(total) });
  const ul = $("#results");
  ul.innerHTML = "";
  const frag = document.createDocumentFragment();
  items.forEach((it) => {
    const li = document.createElement("li");
    li.dataset.path = it.path;
    if (state.current?.path === it.path) li.classList.add("active");
    const sub = it.subtitle || CAT_LABELS[it.category] || "";
    li.innerHTML = `<div class="name"><span>${esc(it.name)}</span><span class="badge">${it.ext}</span></div>
      <div class="sub">${sub ? `${esc(sub)} · ` : ""}<span class="file">${esc(it.path.split("/").pop())}</span></div>`;
    li.title = it.path;
    li.onclick = () => loadModel(it);
    frag.appendChild(li);
  });
  ul.appendChild(frag);
  ul.scrollTop = 0;
}

async function loadCategories() {
  const cats = await (await api("/api/categories")).json();
  const box = $("#cats");
  box.innerHTML = "";
  // a grid of tiles: icon, short name, number of models; the full name is the tooltip
  const mk = (id, label, n, title) => {
    const c = chip(id, label, n);
    const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    icon.setAttribute("class", "i");
    icon.setAttribute("aria-hidden", "true");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", `#c-${id || "all"}`);
    icon.appendChild(use);
    c.prepend(icon);
    c.title = n != null ? `${title || label} · ${num(n)}` : title || label;
    // half-width tiles: big counts in short form (55,413 -> 55k), the exact number is in the tooltip
    if (id && n >= 10000) c.querySelector(".n").textContent = `${Math.round(n / 1000)}k`;
    c.onclick = () => { state.cat = state.cat === id ? "" : id; state.sub = ""; loadCategoriesUI(); runSearch(); };
    return c;
  };
  const all = mk("", T("all"), cats.reduce((s, c) => s + c.count, 0));
  all.classList.add("all");
  box.appendChild(all);
  cats.forEach((c) => {
    CAT_LABELS[c.id] = c.label;
    SUBCATS[c.id] = c.subs;
    box.appendChild(mk(c.id, c.short || c.label, c.count, c.label));
  });
  loadCategoriesUI();
}
function chip(id, label, n) {
  const c = document.createElement("button");
  c.className = "chip";
  const l = document.createElement("span");
  l.className = "l";
  l.textContent = label;
  c.appendChild(l);
  if (n != null) {
    const s = document.createElement("span");
    s.className = "n";
    s.textContent = num(n);
    c.appendChild(s);
  }
  c.dataset.id = id;
  return c;
}
function loadCategoriesUI() {
  $("#cats").querySelectorAll(".chip").forEach((c) => c.classList.toggle("on", c.dataset.id === state.cat));
  // the sub-categories of the selected category, in a second row
  const box = $("#subcats"), subs = SUBCATS[state.cat] || [];
  box.replaceChildren();
  box.hidden = subs.length < 2;
  if (box.hidden) return;
  [{ id: "", label: T("all") }, ...subs].forEach((s) => {
    const c = chip(s.id, s.label, s.count);
    c.classList.toggle("on", s.id === state.sub);
    c.onclick = () => { state.sub = state.sub === s.id ? "" : s.id; loadCategoriesUI(); runSearch(); };
    box.appendChild(c);
  });
}

$("#q").addEventListener("input", scheduleSearch);
$("#mainOnly").addEventListener("change", runSearch);

// ---------------------------------------------------------------- appearance (light / dark)
// "system" follows Windows; the choice is kept in config.json so the .exe remembers it too
let appearance = document.documentElement.dataset.mode === "dark" ? "dark" : "light";
try { appearance = localStorage.getItem("vf.appearance") || "system"; } catch { /* storage unavailable */ }
const systemDark = matchMedia("(prefers-color-scheme: dark)");

function applyAppearance(pref) {
  appearance = ["light", "dark"].includes(pref) ? pref : "system";
  try { localStorage.setItem("vf.appearance", appearance); } catch { /* storage unavailable */ }
  const mode = appearance === "system" ? (systemDark.matches ? "dark" : "light") : appearance;
  document.documentElement.dataset.mode = mode;
  $("#btnMode use").setAttribute("href", mode === "dark" ? "#i-sun" : "#i-moon");
  $("#btnMode").title = mode === "dark" ? "Switch to light" : "Switch to dark";
  if (modelRoot) buildGrid(new THREE.Box3().setFromObject(modelRoot));
}
systemDark.addEventListener("change", () => { if (appearance === "system") applyAppearance("system"); });
applyAppearance(appearance);

$("#btnMode").addEventListener("click", () => {
  applyAppearance(document.documentElement.dataset.mode === "dark" ? "light" : "dark");
  api(`/api/config?appearance=${appearance}`, { method: "POST" }).catch(() => { /* kept locally anyway */ });
});

// ---------------------------------------------------------------- updates (new releases on GitHub)
let update = null, updateChecked = false;

// release notes are Markdown: keep headings, bullets and paragraphs, drop images and rules; everything is escaped
function notesHtml(md) {
  const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\*([^*\s][^*]*)\*/g, "<i>$1</i>")
    .replace(/`([^`]+)`/g, "$1").replace(/\[([^\]]+)\]\([^)]+\)/g, "$1");
  let html = "", list = false;
  for (const raw of md.split(/\r?\n/)) {
    const line = raw.trim();
    const bullet = /^[-*] (.+)/.exec(line);
    if (list && !bullet) { html += "</ul>"; list = false; }
    if (!line || /^!\[/.test(line) || /^-{3,}$/.test(line)) continue;
    if (bullet) { if (!list) { html += "<ul>"; list = true; } html += `<li>${inline(bullet[1])}</li>`; }
    else if (/^#{1,6} /.test(line)) html += `<h4>${inline(line.replace(/^#+ /, ""))}</h4>`;
    else html += `<p>${inline(line)}</p>`;
  }
  return html + (list ? "</ul>" : "");
}

function showUpdatePill() {
  const pill = $("#btnUpdate");
  pill.classList.toggle("hidden", !update?.available || update.skipped);
  if (update?.available) pill.querySelector("span").textContent = `Update to ${update.latest}`;
}

function openUpdateDialog() {
  if (!update?.available) return;
  $("#updText").textContent = `VerseForge ${update.latest} is available. You have ${update.current}.`;
  $("#updNotes").innerHTML = notesHtml(update.notes || "") || `<p>${esc("No release notes.")}</p>`;
  $("#updNotes").classList.toggle("hidden", !update.notes);
  $("#updGo").textContent = update.can_install ? "Update now" : "Open download page";
  $("#updProgress").classList.add("hidden");
  $("#updateDlg").querySelectorAll("button").forEach((b) => { b.disabled = false; });
  if (!$("#updateDlg").open) $("#updateDlg").showModal();
}

async function checkUpdates(force) {
  try {
    update = await (await api(`/api/update/check?force=${force}`)).json();
  } catch (e) {
    if (force) toast(`Could not check for updates: ${e.message}`, true);
    return;
  }
  showUpdatePill();
  if (force) {
    if (update.error) toast(`Could not reach GitHub: ${update.error}`, true);
    else if (update.available) { $("#settings").close(); openUpdateDialog(); }
    else toast(`VerseForge ${update.current} is the latest version`);
  } else if (update.enabled && update.available && !update.skipped && !document.querySelector("dialog[open]")) {
    openUpdateDialog();
  }
}

let installing = false;
async function pollUpdate() {
  const box = $("#updProgress");
  try {
    const job = await (await api("/api/update/progress")).json();
    box.querySelector(".bar span").style.width = `${Math.round(job.progress * 100)}%`;
    box.querySelector(".hint").textContent = job.state === "running" ? `${job.message} ${Math.round(job.progress * 100)}%` : job.message;
    if (job.state === "error") throw new Error(job.message);
    if (job.state === "running") setTimeout(pollUpdate, 400);
    // "launching": the installer takes over and closes this window
  } catch (e) {
    installing = false;
    $("#updateDlg").querySelectorAll("button").forEach((b) => { b.disabled = false; });
    // after the app has quit for the installer the server stops answering: that is expected, not an error
    if (box.querySelector(".hint").textContent.startsWith("Installing")) return;
    box.classList.add("hidden");
    toast(`Update failed: ${e.message}`, true);
  }
}

$("#updGo").addEventListener("click", async () => {
  if (!update?.can_install) {
    api("/api/open-release", { method: "POST" }).catch((e) => toast(e.message, true));
    $("#updateDlg").close("later");
    return;
  }
  installing = true;
  $("#updateDlg").querySelectorAll("button").forEach((b) => { b.disabled = true; });
  $("#updProgress").classList.remove("hidden");
  try {
    await api("/api/update/install", { method: "POST" });
    pollUpdate();
  } catch (e) {
    installing = false;
    $("#updateDlg").querySelectorAll("button").forEach((b) => { b.disabled = false; });
    $("#updProgress").classList.add("hidden");
    toast(`Update failed: ${e.message}`, true);
  }
});
$("#updateDlg").addEventListener("cancel", (e) => { if (installing) e.preventDefault(); });
$("#updateDlg").addEventListener("close", () => {
  if ($("#updateDlg").returnValue !== "skip" || !update) return;
  api(`/api/update/skip?version=${encodeURIComponent(update.latest)}`, { method: "POST" }).catch(() => { /* asked again next time */ });
  update.skipped = true;
  showUpdatePill();
});
$("#btnUpdate").addEventListener("click", openUpdateDialog);
$("#btnCheckUpdates").addEventListener("click", () => checkUpdates(true));

// ---------------------------------------------------------------- status & settings
const appearanceDropdown = dropdown($("#cfgAppearance"));
let appearanceLoaded = false;
async function pollStatus() {
  const el = $("#status");
  try {
    const s = await (await api("/api/status")).json();
    if (!appearanceLoaded && s.appearance) { appearanceLoaded = true; applyAppearance(s.appearance); }
    if (!updateChecked) { updateChecked = true; setTimeout(() => checkUpdates(false), 1500); }
    el.classList.toggle("err", !!s.error);
    el.classList.toggle("ready", !!s.ready && !s.error);
    // once the catalogue is ready the status line has nothing useful to say: it only shows progress and errors
    el.textContent = s.error ? `${s.error} — ${T("openSettings")}` : s.ready ? "" : `${s.message} (${Math.round(s.progress * 100)}%)`;
    el.title = s.p4k_path;
    window.__status = s;
    if (s.ready) {
      if (backdrop.kind !== savedBackdrop) backdrop.set(savedBackdrop).catch(() => backdrop.set("plain"));
      await loadCategories();
      runSearch();
      return;
    }
  } catch { el.textContent = T("serverDown"); }
  setTimeout(pollStatus, 1000);
}

$("#btnSettings").addEventListener("click", async () => {
  const s = await (await api("/api/status")).json();
  $("#cfgP4k").value = s.p4k_path || "";
  $("#cfgExport").value = s.export_dir || "";
  $("#cfgBlender").value = s.blender || "";
  $("#cfgAppearance").value = appearance;
  appearanceDropdown.sync();
  $("#cfgUpdates").checked = s.check_updates !== false;
  $("#versionLine").textContent = `You are using VerseForge ${s.version}`;
  $("#cfgDiskCache").checked = s.disk_cache !== false;
  showCacheSize(s.disk_cache_bytes, s.disk_cache_limit);
  $("#settings").showModal();
});
// saved on the Save button's click (the dialog's "close" event can come late or not at all in a hidden window)
$("#cfgSave").addEventListener("click", async () => {
  const p = new URLSearchParams({ p4k_path: $("#cfgP4k").value, export_dir: $("#cfgExport").value, blender: $("#cfgBlender").value,
    appearance: $("#cfgAppearance").value, check_updates: $("#cfgUpdates").checked, disk_cache: $("#cfgDiskCache").checked });
  applyAppearance($("#cfgAppearance").value);
  try {
    await api(`/api/config?${p}`, { method: "POST" });
    toast(T("saved"));
    pollStatus();
  } catch (e) { toast(e.message, true); }
});

// disk cache (Settings → Cache): how much it holds, and a button to empty it
const gb = (n) => (n >= 1073741824 ? `${(n / 1073741824).toFixed(1)} GB` : `${Math.round(n / 1048576)} MB`);
function showCacheSize(bytes = 0, limit = 0) {
  $("#cacheLine").textContent = `Using ${gb(bytes)}${limit ? ` of ${gb(limit)}` : ""} · older files are removed beyond that`;
}
$("#btnClearCache").addEventListener("click", async () => {
  try {
    const r = await (await api("/api/cache/clear", { method: "POST" })).json();
    showCacheSize(r.bytes, (await (await api("/api/status")).json()).disk_cache_limit);
    toast("Cache cleared");
  } catch (e) { toast(e.message, true); }
});

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

pollStatus();
