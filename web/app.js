import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { AmmoScreen, ShipScreens, isFire, isReload } from "./screen.js";
import { vertexNormals } from "./normals.js";
import { GameLook } from "./gamelook.js";
import { hangarTexture } from "./hangar.js";
import { Backdrops, BACKDROPS } from "./backdrops.js";
import { Batches } from "./batching.js";
import { PaintSwap, groupOf } from "./paint.js";

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

// ---------------------------------------------------------------- texts
// Every text, in the chosen language, comes from the server (i18n.js asked for it and has already written the fixed
// texts of the page); the English originals are in sc_explorer/i18n.py (UI) and in index.html (data-t keys).
const I18N = await window.vfI18n;
const STRINGS = I18N.strings;
const T = (key, vars = {}) => (STRINGS[key] ?? key).replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? "");
const num = (n) => n.toLocaleString(I18N.lang);
// "{n} comment" / "{n} comments": the key for one, the key for any other number
const plural = (n, one, many) => T(n === 1 ? one : many, { n });

const CAT_LABELS = {};
const KIND_LABELS = { solid: "", decal: "kindDecal", glass: "kindGlass", hidden: "kindProxy", screen: "kindScreen" };
const SUBCATS = {};
const state = { cat: "", sub: "", current: null, kinds: { decal: true, glass: true, hidden: false, screen: true }, matOff: new Set(), printJob: null, tex: true, variant: null, full: true,
  look: true, swapXY: false, light: "hangar", interior: false, cut: 1 };
try { state.tex = localStorage.getItem("vf.tex") !== "0"; } catch { /* storage unavailable */ }
try { state.light = localStorage.getItem("vf.light") === "studio" ? "studio" : "hangar"; } catch { /* storage unavailable */ }

// On/off switches and the viewer's pills are drawn from an "is-on" class kept in step with their checkbox, not from
// `:checked`: the Chromium of the Windows desktop window sometimes kept the old `:checked` style after a click ("Main
// models" stayed drawn on while the list already showed every file). Code that sets `.checked` directly is covered too.
const checkedProp = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "checked");
document.querySelectorAll(".switch input[type=checkbox], .pill input[type=checkbox]").forEach((box) => {
  const sync = () => box.closest(".switch, .pill").classList.toggle("is-on", checkedProp.get.call(box));
  Object.defineProperty(box, "checked", {
    configurable: true,
    get() { return checkedProp.get.call(box); },
    set(v) { checkedProp.set.call(box, v); sync(); },
  });
  box.addEventListener("change", sync);
  sync();
});

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

  // options with data-colors ("r,g,b;r,g,b;r,g,b", or "" for a paint without its own colours) show three swatches
  // before their text: the paint menu
  const fill = (node, o) => {
    node.textContent = "";
    node.classList.remove("sw");
    if (!o) return;
    if (!("colors" in o.dataset)) { node.textContent = o.text; return; }
    node.classList.add("sw");
    const dots = document.createElement("span");
    dots.className = "dots";
    const cols = o.dataset.colors ? o.dataset.colors.split(";") : [];
    if (!cols.length) dots.classList.add("stock");
    for (let i = 0; i < 3; i++) {
      const d = document.createElement("i");
      if (cols[i]) d.style.background = `rgb(${cols[i]})`;
      dots.append(d);
    }
    const label = document.createElement("span");
    label.className = "lbl";
    label.textContent = o.text;
    node.append(dots, label);
  };
  const sync = () => fill(btn, sel.selectedOptions[0]);
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
      fill(li, o);
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
// preserveDrawingBuffer off: keeping the buffer costs a copy every frame, and with the heavy models close up that extra
// GPU work made the desktop window show half-composed frames (panels missing). Code that reads the canvas (snapshot,
// report picture) draws a frame first with drawNow(), in the same task, so the buffer is still there.
const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: false, alpha: true });
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
        if (meshKind(o) === "glass" && !o.userData.glass) { o.userData.glass = true; glassLook(o); }
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

// glass, as the game draws it: what lies behind is multiplied by the colour the glass lets through (its transmission,
// from the paint's glass colour: the GLB body colour is 0.35 x transmission, see materials.glass_look) and the
// reflections are added on top. Nothing of it is lit, so a bronze bridge window seen from inside stays a tinted view
// instead of an orange wall, and dark visors (X1) read as glossy black. Front faces only, like the game's glass
// materials (not two-sided): a pane modelled with its thickness tints once, not twice.
const GLASS_BODY = 0.35;
// tint layer colour of a glass whose GLB body colour (linear) is `c`; paint.js recolours glass with it
function glassTint(c) {
  const t = new THREE.Color(c[0], c[1], c[2]).multiplyScalar(1 / GLASS_BODY);
  t.r = Math.min(0.92, Math.max(0.04, t.r)); t.g = Math.min(0.92, Math.max(0.04, t.g)); t.b = Math.min(0.92, Math.max(0.04, t.b));
  return t;
}
function glassLook(o) {
  const m = o.material;
  const t = glassTint([m.color.r, m.color.g, m.color.b]);
  const tint = new THREE.MeshBasicMaterial({
    name: m.name, color: t, transparent: true, depthWrite: false, side: THREE.FrontSide, toneMapped: false,
    blending: THREE.CustomBlending, blendEquation: THREE.AddEquation, blendSrc: THREE.ZeroFactor, blendDst: THREE.SrcColorFactor,
  });
  const layer = new THREE.Mesh(o.geometry, tint);     // no name: kind and material name come from the parent
  layer.userData.glass = true;                         // (traversals running while it is added skip it)
  layer.renderOrder = o.renderOrder - 1;               // tint first, reflections over it
  o.add(layer);
  m.color.setRGB(0, 0, 0);                             // the reflection layer: specular only, added to the frame
  m.flatShading = false;                               // GLTFLoader shades the lite GLB flat (it has no normals): the
  m.needsUpdate = true;                                // reflections broke at every triangle; ours are computed, smooth
  m.opacity = 1;
  m.transparent = true;
  m.depthWrite = false;
  m.side = THREE.FrontSide;
  m.roughness = 0.05;
  m.metalness = 0;
  m.envMapIntensity = 1.0;
  m.blending = THREE.AdditiveBlending;
  m.userData.swatch = t;                               // material list swatch: the glass colour, not black
}

// animation state (see "animations" below); declared here because the render loop starts right away
const anim = { mixer: null, clips: new Map(), list: [], actions: new Map(), current: null, dragging: false, landed: null };
const clock = new THREE.Clock();
let shipScreens = null;  // MFD pages drawn on a ship's monitors (screen.js)
let ammoScreen = null;   // weapon display drawn on its DisplayScreen (screen.js)
let paintSwap = null;    // instant paint changes of the model on screen (paint.js), null when it needs a reload
let retiredSwap = null;  // the PaintSwap of the model still on screen while the next one loads (freed when it goes)
let currentInfo = null;  // /api/model/info of the model on screen (screens are rebuilt from it after a paint change)
window.__verseforge = { get root() { return modelRoot; }, anim, get screen() { return ammoScreen; }, get shipScreens() { return shipScreens; }, get rooms() { return rooms; }, showRooms: (ids) => showRooms(ids),
  camera, controls, renderer, scene, frame: () => frame(), load: (item) => loadModel(item), state: () => state, setLighting,
  get backdrop() { return backdrop; }, get batches() { return batches; },
  get batching() { return BATCH_ON; }, set batching(on) { BATCH_ON = !!on; }, get look() { return gameLook; }, stats,
  get paint() { return paintSwap; }, get info() { return currentInfo; }, changePaint: (tag, o) => changePaint(tag, o), invalidate: (ms) => invalidate(ms), tick: () => tick() };   // for automated checks (tools/, tests)
// Render on demand: a frame is drawn only when something changed (camera moving or settling, an animation or the
// auto-rotate running, a texture/material update, a shadow redraw request, an explicit invalidate()), plus once a
// second as a safety net. A still model leaves the GPU idle instead of redrawing it 60 times a second.
// textures and materials announce their changes through `needsUpdate`: listen to it (texture loads, the ammo
// screen's canvas, game-look materials being built)
for (const proto of [THREE.Texture.prototype, THREE.Material.prototype]) {
  const d = Object.getOwnPropertyDescriptor(proto, "needsUpdate");
  if (d?.set) Object.defineProperty(proto, "needsUpdate", { ...d, set(v) { d.set.call(this, v); if (v) invalidate(); } });
}
// Big models: pieces sharing a material are drawn as one batch (batching.js). Off with ?batch=0 in the address or
// localStorage vf.batch = "0" (every piece its own draw call, as before 1.15).
let BATCH_ON = !/[?&]batch=0/.test(location.search);
try { if (localStorage.getItem("vf.batch") === "0") BATCH_ON = false; } catch { /* storage unavailable */ }
const BATCH_MIN_MESHES = 300;  // smaller models are quick as they are
let batches = new Batches();
let poseDirty = false;         // an animation moved the nodes: the batches need their transforms again
let holdRender = false;        // true while a model is being sent to the GPU piece by piece (warmUp)
// Linux (Qt WebEngine / Chrome: ANGLE on OpenGL, seen with Mesa): after the window is resized at start-up the GL
// state three.js keeps in its cache stops matching the driver's, and the depth test no longer works: inner parts and
// the floor grid showed through the hull. Re-sending the state before each frame costs a few dozen calls and fixes it.
const RESYNC_GL = /Linux/.test(navigator.userAgent) && !/Android/.test(navigator.userAgent);
// "vf-moving" on <html> (style.css): no glass blur on the panels while the view moves and through the render tail
// after it, so Chromium does not blur a changing 3D view under every panel on every frame (half-composed frames in the
// Qt window with heavy scenes). Only real motion counts: a click in a panel also draws a few frames, but the view under
// the panels stays the same then, and the glass must not blink on every click.
// Only the Qt window needs it (Linux, and Windows without WebView2): there frames reach the window before Chromium
// has finished composing them. A real Chromium window (WebView2, a browser) keeps the glass on all the time.
const QT_WINDOW = /QtWebEngine/.test(navigator.userAgent);
let motionUntil = 0, moving = false;
function setMoving(on) {
  if (on === moving || !QT_WINDOW) return;
  moving = on;
  document.documentElement.classList.toggle("vf-moving", on);
}
// switch the glass off as soon as a move begins (pointer down, wheel, section slider), one frame before the view
// changes: restyling every panel in the same frame as the first heavy 3D frame was enough to flash
function markMotion() {
  motionUntil = Math.max(motionUntil, performance.now() + RENDER_TAIL);
  setMoving(true);
}
function tick() {
  const dt = clock.getDelta();
  const now = performance.now();
  if (holdRender) return;
  let draw = now <= renderUntil, motion = false;
  if (poseDirty && !anim.mixer) syncPose();
  if (anim.mixer) {
    const running = anim.dragging || anim.mixer._actions.some((a) => a.isRunning());
    motion = running;
    if (running || now <= renderUntil) {
      anim.mixer.update(dt);
      poseDirty = true;
      syncTimeline();
    }
    if (poseDirty) syncPose();
    if (running) {
      draw = true;
      if (renderer.clippingPlanes.length) cullAboveCut();     // moving parts may cross the section plane
      if (renderer.shadowMap.enabled) renderer.shadowMap.needsUpdate = true;
    }
  }
  if (controls.update()) draw = motion = true; // true while the camera moves (dragging, damping, auto-rotate)
  if (controls.autoRotate) motion = true;
  if (motion || renderer.shadowMap.needsUpdate) draw = true;
  if (draw) tailUntil = now + RENDER_TAIL;     // something changed: keep drawing for a while after it
  if (motion) motionUntil = tailUntil;
  setMoving(now < motionUntil);
  if (!draw && now > tailUntil && now - lastRender <= 1000) return;
  if (RESYNC_GL) renderer.resetState();
  renderer.render(scene, camera);
  lastRender = now;
  stats.frames++;
}
renderer.setAnimationLoop(tick);
controls.addEventListener("start", markMotion);
function syncPose() {
  poseDirty = false;
  batches.sync();
  if (renderer.shadowMap.enabled) renderer.shadowMap.needsUpdate = true;
}
// draw the scene right now: the drawing buffer is not preserved, so read the canvas only after this, in the same task
function drawNow() {
  if (poseDirty) syncPose();
  if (RESYNC_GL) renderer.resetState();
  renderer.render(scene, camera);
}
// user input on the canvas: keep drawing a little while (the camera's damping finishes after the pointer stops)
for (const ev of ["pointerdown", "pointermove", "wheel"]) renderer.domElement.addEventListener(ev, () => invalidate(300), { passive: true });
// any click or change in the panels (animations, rest pose, layers, menus) may change the scene: a few frames
for (const ev of ["click", "input", "change", "keydown"]) document.addEventListener(ev, () => invalidate(400), { passive: true });

function frame(around = null) {
  if (!modelRoot) return;
  const box = around || new THREE.Box3().setFromObject(modelRoot);
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
    let kindOn = kind === "solid" ? true : state.kinds[kind] ?? true;
    if (resin !== "off" && kind !== "solid" && kind !== "glass") kindOn = false;   // decals, screens: not printed
    o.visible = kindOn && !state.matOff.has(meshMat(o));
  });
}

function applyWireframe() {
  invalidate();
  modelRoot?.traverse((o) => { if (o.isMesh) o.material.wireframe = wireframe; });
}

// ---------------------------------------------------------------- resin print look
// The model as it comes off a resin printer: one colour, satin surface, no paint, decals or screens, and the print
// layers (0.05 mm) along the height, visible only up close like on a real print. Small items (weapons, armour,
// props) are taken as printed 1:1; anything longer than 2.5 m as scaled down to 200 mm on its longest side.
const RESIN = {
  grey: { color: 0x8c9194, roughness: 0.42, clearcoat: 0.2 },
  white: { color: 0xe4e1d9, roughness: 0.46, clearcoat: 0.15 },
  black: { color: 0x1d1f22, roughness: 0.36, clearcoat: 0.35 },
  clear: { color: 0xf6edd6, roughness: 0.06, clearcoat: 0.6, transmission: 0.95, thickness: 0.15, ior: 1.5 },
};
const RESIN_LAYER_MM = 0.05, RESIN_PLATE_MM = 200, RESIN_LIFE_SIZE_M = 2.5;
const resinLayer = { value: 0.001 };                 // layer height in model units (metres), set per model
const resinMats = {};
let resin = "off";
try { resin = localStorage.getItem("vf.resin") || "off"; } catch { /* storage unavailable */ }
if (!(resin in RESIN)) resin = "off";

function resinMaterial(kind) {
  if (resinMats[kind]) return resinMats[kind];
  const p = RESIN[kind];
  const m = new THREE.MeshPhysicalMaterial({ color: p.color, roughness: p.roughness, metalness: 0, clearcoat: p.clearcoat,
    clearcoatRoughness: 0.3, transmission: p.transmission || 0, thickness: p.thickness || 0, ior: p.ior || 1.5,
    side: THREE.DoubleSide, envMapIntensity: 0.8 });
  m.name = `resin|${kind}`;
  m.onBeforeCompile = (s) => {
    s.uniforms.resinLayer = resinLayer;
    s.vertexShader = s.vertexShader
      .replace("#include <common>", "#include <common>\nvarying float vResinY;")
      .replace("#include <worldpos_vertex>", `#include <worldpos_vertex>
#ifdef USE_BATCHING
vResinY = (modelMatrix * batchingMatrix * vec4(transformed, 1.0)).y;   // in a batch: the piece's own transform
#else
vResinY = (modelMatrix * vec4(transformed, 1.0)).y;
#endif`);
    s.fragmentShader = s.fragmentShader
      .replace("#include <common>", "#include <common>\nvarying float vResinY;\nuniform float resinLayer;")
      .replace("#include <normal_fragment_maps>", `#include <normal_fragment_maps>
  {
    // one ridge per layer; faded out where a layer is smaller than a pixel (no shimmering from afar)
    float t = vResinY / resinLayer;
    float fade = 1.0 - smoothstep(0.15, 0.45, fwidth(t));
    float slope = cos(6.2831853 * t) * fade;
    vec3 up = normalize((viewMatrix * vec4(0.0, 1.0, 0.0, 0.0)).xyz);
    normal = normalize(normal + up * slope * 0.35);
    diffuseColor.rgb *= 1.0 - 0.05 * fade * (0.5 + 0.5 * sin(6.2831853 * t));
  }`);
  };
  m.customProgramCacheKey = () => "resin";
  return (resinMats[kind] = m);
}

function applyResin() {
  invalidate(300);
  document.querySelectorAll("#resinMenu [data-resin]").forEach((b) => b.classList.toggle("on", b.dataset.resin === resin));
  $('[data-act="resin"]')?.classList.toggle("on", resin !== "off");
  if (!modelRoot) { $("#resinScale").textContent = ""; return; }
  const size = new THREE.Box3().setFromObject(modelRoot).getSize(new THREE.Vector3());
  const longest = Math.max(size.x, size.y, size.z, 1e-6);
  const scale = longest <= RESIN_LIFE_SIZE_M ? 1 : longest * 1000 / RESIN_PLATE_MM;   // model mm per printed mm
  resinLayer.value = RESIN_LAYER_MM * scale / 1000;
  $("#resinScale").textContent = resin === "off" ? "" : scale === 1
    ? T("resinLife", { layer: RESIN_LAYER_MM })
    : T("resinScaled", { scale: Math.round(scale), plate: RESIN_PLATE_MM, layer: RESIN_LAYER_MM });
  const mat = resin === "off" ? null : resinMaterial(resin);
  modelRoot.traverse((o) => {
    if (!o.isMesh) return;
    if (mat) {
      if (!o.userData.gameMaterial) o.userData.gameMaterial = o.material;
      o.material = mat;
    } else if (o.userData.gameMaterial) {
      o.material = o.userData.gameMaterial;
      delete o.userData.gameMaterial;
    }
  });
  applyWireframe();
  applyVisibility();
  renderer.shadowMap.needsUpdate = true;
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

async function loadModel(item, keepView = false, opts = {}) {
  if (state.current?.path !== item.path) state.variant = null;
  state.current = item;
  // The old model stays on screen while this one loads, so its paint (textures included) must stay alive: a swap in
  // progress is only cancelled here, and the PaintSwap is freed together with the model below. Meanwhile paint
  // changes reload.
  if (paintSwap) { paintSwap.seq++; retiredSwap = paintSwap; paintSwap = null; }
  // opts.paint: show this paint without making it the chosen one (Compare with stock on a model that must reload)
  const paintTag = opts.paint ?? state.variant;
  if (!keepView) state.matOff.clear();
  const v = (paintTag != null ? `&variant=${encodeURIComponent(paintTag)}` : "") + `&full=${state.full}` +
    `&interior=${state.interior}`;
  const swapQuery = paintQuery(item);   // the model this load shows, for its paint requests
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
    if (opts.paint == null) { state.variant = info.variant; state.comparing = false; }
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
    shipScreens?.dispose();
    shipScreens = null;
    retiredSwap?.dispose();
    retiredSwap = null;
    if (modelRoot) {
      scene.remove(modelRoot);
      modelRoot.traverse((o) => { if (o.isMesh) { o.geometry.dispose(); (o.userData.gameMaterial || o.material).dispose(); } });
    }
    batches.dispose();
    batches = new Batches();
    modelRoot = gltf.scene;
    // paint group of each piece (keyed GLBs only, paint.js): read from the GLB material before the game look
    // replaces it, since the game look shares one material between groups that look the same
    if (info.keyed_glb) modelRoot.traverse((o) => { if (o.isMesh) o.userData.group = groupOf(o.material); });
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
        // livery stickers this paint does not have (only keyed GLBs write alpha 0 stickers): not drawn at all
        if (info.keyed_glb && meshKind(o) === "decal" && o.material.opacity === 0 && !o.material.userData?.pom) o.material.visible = false;
        // decals lie on the hull: they neither cast shadows nor need the shadow pass
        o.castShadow = renderer.shadowMap.enabled && meshKind(o) !== "decal" && !o.material.transparent;
        o.receiveShadow = renderer.shadowMap.enabled && !o.material.userData?.pom;
        if (o.userData.glass) return;                     // a glass tint layer added below: already set up
        o.material.side = THREE.DoubleSide;
        if (!o.material.isMeshPhysicalMaterial) o.material.envMapIntensity = 0.6;   // plain GLB look
        if (meshKind(o) === "glass") { o.userData.glass = true; glassLook(o); }
      }
    });
    let meshCount = 0;
    modelRoot.traverse((o) => { if (o.isMesh) meshCount++; });
    if (BATCH_ON && meshCount >= BATCH_MIN_MESHES) {
      const mine = batches;
      await mine.build(modelRoot, () => new Promise((r) => setTimeout(r, 0)));
      if (state.current !== item || mine !== batches) return;
    }
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
    startScreens(item, info);
    applyWireframe();
    applyVisibility();
    if (resin !== "off") applyResin();
    buildGrid(new THREE.Box3().setFromObject(modelRoot));
    renderer.shadowMap.needsUpdate = true;
    if (!keepView) frame();
    // Compare on a model that must reload: the panel keeps the chosen paint (menu, decal sheet)
    const chosen = opts.paint != null && currentInfo?.path === item.path ? currentInfo.stickers : info.stickers;
    showInfo(item, opts.paint != null ? { ...info, variant: state.variant, stickers: chosen } : info);
    currentInfo = { ...info, path: item.path, stickers: opts.paint != null ? chosen : info.stickers };
    if (info.keyed_glb && state.tex && state.look) {
      paintSwap = new PaintSwap({ gameLook, batches, root: modelRoot, compile: compileShaders, section: !!info.interior,
        look: { swapNormalXY: state.swapXY, sun }, query: swapQuery, glassTint, tag: info.variant });
      paintSwap.path = item.path;                 // the model it paints (a failed load gives it back only to that one)
    }
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
    buildRooms(info.interior ? info.rooms || [] : [], info.decks || []);
    applySection();
    $("#fullLabel").textContent = T(info.ground_vehicle ? "fullVehicle" : "fullShip");
    loadRelated(item);
  } catch (e) {
    // failed before the old model went away (it is still on screen, with its paint): paint changes swap again
    if (state.current === item && retiredSwap?.root === modelRoot && retiredSwap.path === item.path) {
      paintSwap = retiredSwap;
      retiredSwap = null;
    }
    $("#info").innerHTML = infoHead(item) + `<p class="warn">${esc(e.message)}</p>`;
    toast(T("loadFailed", { error: e.message }), true);
  } finally {
    $("#loading").classList.add("hidden");
  }
}

// the weapon ammo display and the ships' MFD pages, drawn on the model's screens. The names are read from the game
// material, which the resin look keeps in userData.gameMaterial (a paint change rebuilds the screens with it on)
function startScreens(item, info) {
  const screens = [];
  let anyScreen = false;
  const matName = (o) => (o.userData.gameMaterial || o.material).name;
  modelRoot.traverse((o) => {
    if (!o.isMesh || meshKind(o) !== "screen") return;
    anyScreen = true;
    if (o.geometry.attributes.uv && !matName(o).endsWith("|holo")) screens.push(o);   // HUD veils: no ammo
  });
  $("#scrPill").classList.toggle("hidden", !anyScreen);
  if (screens.length && info.ammo) ammoScreen = new AmmoScreen(screens, info.ammo, info.screen);
  else if (info.screen?.kit) {
    // ships: the monitors the game draws live get MFD pages built on the game's own graphics
    const monitors = screens.filter((o) => matName(o).endsWith("|rtt"));
    if (monitors.length) shipScreens = new ShipScreens(monitors, info.screen, { name: item.name, size: info.stats.size_m });
  }
}

const paintQuery = (item) => `path=${encodeURIComponent(item.path)}&full=${state.full}&interior=${state.interior}`;

// Show paint `tag`: swapped in place when the model allows it (paint.js), else reloaded as before.
// keepChoice: Compare with stock, the menu and the exports keep the chosen paint. The last request wins.
let paintToken = 0;
async function changePaint(tag, { keepChoice = false } = {}) {
  const item = state.current, token = ++paintToken, swap = paintSwap;
  if (!item) return;
  if (!keepChoice) state.variant = tag;
  const reload = () => loadModel(item, true, keepChoice ? { paint: tag } : {});
  if (!swap) return reload();
  // another model or paint was asked meanwhile, or the model was reloaded (Full ship, Interiors, textures): a newer
  // choice is on its way, so this request neither swaps nor reloads over it
  const stale = () => state.current !== item || token !== paintToken || paintSwap !== swap;
  // a slow change (the first one after a restart builds the reference interior, seconds) gets a quiet sign on the
  // paint menu, not the loading screen; it goes away however the request ends
  const busyTimer = setTimeout(() => $("#info .variant")?.classList.add("busy"), 800);
  try {
    // the paint of the model on screen: its own query (state.full and state.interior may have changed since it loaded)
    const paint = swap.answer(tag) ||
      await api(`/api/model/paint?${swap.query}&variant=${encodeURIComponent(tag)}`).then((r) => r.json());
    if (stale()) return;
    if (!paint.swappable) return reload();
    if (!(await swap.apply(tag, paint)) || stale()) return;
    afterPaint(item, tag, paint);
  } catch (e) {
    if (stale()) return;
    toast(T("loadFailed", { error: e.message }), true);
    return reload();
  } finally {
    clearTimeout(busyTimer);
    $("#info .variant")?.classList.remove("busy");
  }
}

// What depends on the materials, redone after a paint was swapped in. The resin look can stay on: paint.js and the
// screen classes both write into userData.gameMaterial while it is on, so the resin material is never touched.
function afterPaint(item, tag, paint) {
  ammoScreen?.dispose();                          // puts each screen's own material back
  ammoScreen = null;
  shipScreens?.dispose();
  shipScreens = null;
  modelRoot.traverse((o) => {
    const e = o.isMesh && meshKind(o) === "screen" ? paint.groups[o.userData.group] : null;
    const m = e?.emissive ? o.userData.gameMaterial || o.material : null;   // the glow of this paint's screens
    if (m?.emissive) m.emissive.setRGB(e.emissive[0], e.emissive[1], e.emissive[2]);
  });
  currentInfo = { ...currentInfo, screen: paint.screen };
  // the decal sheet is of the chosen paint: the panel does not follow the stock paint shown by Compare, and is set
  // again when Compare goes back
  if (tag === state.variant) {
    currentInfo.stickers = paint.stickers;
    $("#decalBox").classList.toggle("hidden", !paint.stickers);
  }
  startScreens(item, currentInfo);
  applyWireframe();
  applyVisibility();
  showMaterials();
  renderer.shadowMap.needsUpdate = true;
  invalidate(300);
  stats.paints = (stats.paints || 0) + 1;         // for tools/paint_check.py
}

function fmtLen(m) {
  if (m >= 10) return `${m.toFixed(2)}<small>m</small>`;
  if (m >= 1) return `${m.toFixed(3)}<small>m</small>`;
  return `${(m * 1000).toFixed(1)}<small>mm</small>`;
}

const plainLen = (m) => fmtLen(m).replace(/<small>(\w+)<\/small>/, " $1");
// width × length × height on one line: metres, or millimetres for small things
function fmtSize(size) {
  const mm = Math.max(...size) < 1;
  const one = (v) => mm ? (v * 1000).toFixed(v >= 0.1 ? 0 : 1) : v.toFixed(2);
  return `${size.map(one).join(" × ")} ${mm ? "mm" : "m"}`;
}

function infoHead(item) {
  const sub = item.subtitle || CAT_LABELS[item.category] || "";
  return `<div class="info-head">
      ${sub ? `<div class="eyebrow">${esc(sub)}</div>` : ""}
      <h2 title="${esc(item.path)}">${esc(item.name)}</h2>
    </div>`;
}

function showInfo(item, info) {
  const s = info.stats;
  const [x, y, z] = s.size_m;
  const sizes = `${T("width")} ${plainLen(x)} · ${T("length")} ${plainLen(y)} · ${T("height")} ${plainLen(z)}`;
  $("#info").innerHTML = `${infoHead(item)}
    <div class="specs" title="${esc(sizes)}">
      <b>${fmtSize(s.size_m)}</b>${T("triangles")} ${num(s.triangles)} · ${T("parts")} ${num(s.parts)} · ${T("materials")} ${s.materials.length}
    </div>
    ${info.variants.length > 1 ? `<div class="variant"><div class="paint-head"><span>${T("variant")}</span><b id="paintName"></b></div>
      <div id="paintGrid" class="paint-grid" role="radiogroup" aria-label="${esc(T("variant"))}"></div>
      <select id="variantSel" hidden>${info.variants.map((v) => `<option value="${esc(v.tag)}"${v.tag === info.variant ? " selected" : ""}>${esc(v.label)}</option>`).join("")}</select></div>` : ""}
    ${info.warnings.map((w) => `<div class="warn">${esc(w)}</div>`).join("")}`;
  const variantSel = $("#variantSel");
  if (variantSel) {
    // one tile per paint, in the paint's three colours (hatched: no colours of its own); the hidden <select> stays
    // the value everything else reads and drives (tools/, the change event)
    const grid = $("#paintGrid"), name = $("#paintName");
    const label = (tag) => info.variants.find((v) => v.tag === tag)?.label || "";
    const mark = () => {
      grid.querySelectorAll(".paint-sw").forEach((b) => {
        b.classList.toggle("on", b.dataset.tag === variantSel.value);
        b.setAttribute("aria-checked", b.dataset.tag === variantSel.value);
      });
      name.textContent = name.title = label(variantSel.value);
      name.classList.remove("peek");
    };
    info.variants.forEach((v) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "paint-sw" + (v.colors ? "" : " stock");
      b.dataset.tag = v.tag;
      b.setAttribute("role", "radio");
      b.setAttribute("aria-label", v.label);
      if (v.colors) {
        const [c1, c2, c3] = v.colors.map((c) => `rgb(${c[0]},${c[1]},${c[2]})`);
        b.style.background = `linear-gradient(135deg, ${c1} 0 52%, ${c2} 52% 80%, ${c3} 80%)`;
      }
      // the name of the paint under the pointer takes the place of the chosen one's while it is there
      b.addEventListener("pointerenter", () => { name.textContent = v.label; name.classList.toggle("peek", v.tag !== variantSel.value); });
      b.addEventListener("click", () => {
        if (variantSel.value === v.tag && !state.comparing) return;
        variantSel.value = v.tag;
        variantSel.dispatchEvent(new Event("change"));
      });
      grid.append(b);
    });
    grid.addEventListener("pointerleave", mark);
    mark();
    grid.querySelector(".paint-sw.on")?.scrollIntoView({ block: "nearest" });
    variantSel.addEventListener("change", (e) => {
      mark();
      state.comparing = false;
      changePaint(e.target.value);
      showCompare(info);
    });
    showCompare(info);
  }
  $("#exportBox").classList.remove("hidden");
  $("#printBox").classList.remove("hidden");
  $("#decalBox").classList.toggle("hidden", !info.stickers);
  $("#decalStatus").textContent = "";
  decalLength = Math.max(x, y, z);
  showDecalSize();
}

// "Compare with stock paint" under the paint menu: shows the stock paint without changing the chosen one
function showCompare(info) {
  const stock = info.variants.find((v) => v.stock);
  let btn = $("#cmpStock");
  if (!stock || state.variant === stock.tag) { btn?.remove(); state.comparing = false; return; }
  if (!btn) {
    btn = document.createElement("button");
    btn.id = "cmpStock";
    btn.type = "button";
    btn.className = "cmp";
    $("#info .variant").after(btn);
    btn.onclick = () => {
      state.comparing = !state.comparing;
      changePaint(state.comparing ? stock.tag : state.variant, { keepChoice: true });
      showCompare(info);
    };
  }
  btn.classList.toggle("on", !!state.comparing);
  btn.textContent = "⇄ " + T(state.comparing ? "showingStock" : "compareStock");
}

function showMaterials() {
  const mats = new Map();
  modelRoot.traverse((o) => {
    if (!o.isMesh) return;
    const name = meshMat(o);
    // shader materials (POM decal overlays) have no .color: they keep the GLB colour in userData.swatch
    const m0 = o.userData.gameMaterial || o.material;     // the game material, also while the resin look is on
    const c = m0.userData?.swatch || m0.color;
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
  syncPose();                    // right away: the backdrop and the section box are fitted to this pose
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
  $("#expPoseRow").classList.toggle("hidden", !anim.list.length);
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
      b.title = `${a.group} · ${a.label} (${a.duration.toFixed(1)} s` + (a.speed < 0 ? `, ${T("animReversed")})` : ")");
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
  poseDirty = true;
});
$("#animTime").addEventListener("change", () => { anim.dragging = false; });
$("#animLoop").addEventListener("change", (e) => {
  anim.actions.forEach((act) => act.setLoop(e.target.checked ? THREE.LoopRepeat : THREE.LoopOnce, Infinity));
});
$("#animReset").addEventListener("click", () => {
  if (!anim.mixer) return;
  anim.mixer.stopAllAction();
  poseDirty = true;
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
document.querySelectorAll("#resinMenu [data-resin]").forEach((b) => b.addEventListener("click", () => {
  $("#resinMenu").classList.add("hidden");
  resin = b.dataset.resin;
  try { localStorage.setItem("vf.resin", resin); } catch { /* storage unavailable */ }
  applyResin();
}));
$("#layersBtn").addEventListener("click", () => $("#layersBtn").classList.toggle("on", !$("#layersMenu").classList.toggle("hidden")));
document.addEventListener("pointerdown", (e) => {
  if (!e.target.closest("#layersWrap")) { $("#layersMenu").classList.add("hidden"); $("#layersBtn").classList.remove("on"); }
  if (!e.target.closest("#bgMenu, [data-act=\"bg\"]")) $("#bgMenu").classList.add("hidden");
  if (!e.target.closest("#resinMenu, [data-act=\"resin\"]")) $("#resinMenu").classList.add("hidden");
});
applyResin();
// the space panoramas come from the game files: a saved one is put back once the catalogue is ready (pollStatus)
const savedBackdrop = backdrop.kind;
backdrop.set(["pyro", "stanton", "workbench"].includes(savedBackdrop) ? "plain" : savedBackdrop);
// Panels hidden: the top bar, the list and the right panel go away and the view is centred on the whole window.
// Not remembered: the app always starts with its panels.
function showPanels(on) {
  document.documentElement.classList.toggle("vf-bare", !on);
  $('[data-act="panels"]').classList.toggle("on", !on);
  resize();
}

// Icon-only buttons say their name at once on hover, in a tip drawn here: the browser's own tooltip takes a second.
// The text is the element's title (kept in the page's language by i18n.js), moved aside while the tip is used.
const tip = document.body.appendChild(Object.assign(document.createElement("div"), { id: "tip", className: "hidden" }));
const TIPPED = ".toolbar .tool, .ptabs button:not(.on)";
document.addEventListener("pointerover", (e) => {
  const el = e.target.closest?.(TIPPED);
  if (!el) { tip.classList.add("hidden"); return; }
  if (el.title) { el.dataset.tip = el.title; el.setAttribute("aria-label", el.title); el.removeAttribute("title"); }
  if (!el.dataset.tip) return;
  tip.textContent = el.dataset.tip;
  tip.classList.remove("hidden");
  const r = el.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight, above = r.top > innerHeight / 2;
  tip.style.left = `${Math.max(8, Math.min(innerWidth - w - 8, r.left + r.width / 2 - w / 2))}px`;
  tip.style.top = `${above ? r.top - h - 8 : r.bottom + 8}px`;
});
document.addEventListener("pointerdown", () => tip.classList.add("hidden"), true);

// Right panel: one tab at a time (animations, export, 3D print with the decal sheet, materials with the folder).
// The boxes are shown and hidden by the code that fills them; a tab exists while one of its boxes does.
const ptabs = { wanted: "anim", boxes: [...document.querySelectorAll(".panel .box[data-ptab]")] };
try { ptabs.wanted = localStorage.getItem("vf.ptab") || ptabs.wanted; } catch { /* storage unavailable */ }
function syncTabs() {
  const live = new Set(ptabs.boxes.filter((b) => !b.classList.contains("hidden")).map((b) => b.dataset.ptab));
  const buttons = [...document.querySelectorAll("#ptabs button")];
  const shown = live.has(ptabs.wanted) ? ptabs.wanted : buttons.find((b) => live.has(b.dataset.ptab))?.dataset.ptab || "";
  buttons.forEach((b) => {
    b.hidden = !live.has(b.dataset.ptab);
    b.classList.toggle("on", b.dataset.ptab === shown);
    b.setAttribute("aria-selected", b.dataset.ptab === shown);
  });
  $("#ptabs").classList.toggle("hidden", live.size < 2);
  $(".panel").dataset.ptab = shown;
}
document.querySelectorAll("#ptabs button").forEach((b) => b.addEventListener("click", () => {
  ptabs.wanted = b.dataset.ptab;
  try { localStorage.setItem("vf.ptab", ptabs.wanted); } catch { /* storage unavailable */ }
  syncTabs();
}));
const tabWatch = new MutationObserver(syncTabs);
ptabs.boxes.forEach((b) => tabWatch.observe(b, { attributes: true, attributeFilter: ["class"] }));
syncTabs();

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
  if (a === "panels") showPanels(document.documentElement.classList.contains("vf-bare"));
  if (a === "bg") $("#bgMenu").classList.toggle("hidden");
  if (a === "resin") $("#resinMenu").classList.toggle("hidden");
  if (a === "shot") {
    const link = document.createElement("a");
    link.download = `${(state.current?.path.split("/").pop() || "model").replace(/\.\w+$/, "")}.png`;
    drawNow();
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
// Pieces lying wholly above the section plane are not drawn at all (layer 0 off: not drawn, no shadow, not picked).
// The plane would discard every pixel of them anyway, but only after their vertices and part of their shading had run:
// with the Perseus interior cut at 73% the frames went past 16 ms and the desktop window flashed half-drawn frames.
const cullBox = new THREE.Box3();
// Rooms: the interior's pieces carry their room in the mesh name ("...|R<id>", from the game's own room volumes).
// With rooms chosen, only their pieces are drawn: the hull and the other rooms are left out like the parts above
// the section plane, and the Section slider then slices just those rooms.
const rooms = { list: [], on: new Set(), whole: null, decks: [] };
function roomId(o) {
  if (o.userData.room === undefined) {
    const m = /\|R(\d+)$/.exec(o.name || o.parent?.name || "");
    o.userData.room = m ? +m[1] : -1;
  }
  return o.userData.room;
}
// See-through meshes span several rooms ("...|M" + runs of triangles per room, in room order): the chosen rooms'
// triangles are moved to the front of the index and only those are drawn.
function roomRuns(o) {
  if (o.userData.runs === undefined) {
    const m = /\|M((?:r(?:x|\d+)s\d+n\d+_?)+)$/.exec(o.name || "");
    o.userData.runs = m && o.geometry?.index
      ? [...m[1].matchAll(/r(x|\d+)s(\d+)n(\d+)/g)].map((r) => [r[1] === "x" ? -1 : +r[1], +r[2] * 3, +r[3] * 3]) : null;
  }
  return o.userData.runs;
}
function drawRuns(o) {
  const runs = roomRuns(o);
  if (!runs) return;
  const index = o.geometry.index;
  if (!o.userData.fullIndex) o.userData.fullIndex = index.array.slice();
  const full = o.userData.fullIndex;
  let n = 0;
  if (!rooms.on.size) { index.array.set(full); n = full.length; }
  else for (const [room, first, count] of runs) {
    if (!rooms.on.has(room)) continue;
    index.array.set(full.subarray(first, first + count), n);
    n += count;
  }
  index.needsUpdate = true;
  o.geometry.setDrawRange(0, n);
  o.userData.noRoom = n === 0;
}
const roomHidden = (o) => (o.geometry && roomRuns(o) ? o.userData.noRoom === true
  : !o.name && o.parent?.geometry && roomRuns(o.parent) ? o.parent.userData.noRoom === true : !rooms.on.has(roomId(o)));
function roomsBox() {
  const box = batches.boxOf((n) => rooms.on.has(roomId(n)), new THREE.Box3());
  modelRoot.traverse((o) => {
    if (!o.isMesh || o.isBatchedMesh || !rooms.on.has(roomId(o))) return;
    if (!o.geometry.boundingBox) o.geometry.computeBoundingBox();
    box.union(cullBox.copy(o.geometry.boundingBox).applyMatrix4(o.matrixWorld));
  });
  return box;
}
function showRooms(ids) {
  if (!modelRoot) return;
  rooms.on = new Set(ids);
  if (poseDirty) syncPose();
  modelRoot.updateMatrixWorld(true);
  let box = rooms.on.size ? roomsBox() : null;
  if (box && box.isEmpty()) { rooms.on.clear(); box = null; }
  modelRoot.traverse((o) => { if (o.isMesh && !o.isBatchedMesh && o.name) drawRuns(o); });
  sectionBox = rooms.on.size ? box : rooms.whole;
  state.cut = 1;
  buildDecks(rooms.on.size ? [] : rooms.decks);
  applySection();
  frame(rooms.on.size ? box : null);
  const names = rooms.list.filter((r) => rooms.on.has(r.id)).map((r) => r.name);
  $("#roomsBtn").textContent = names.length === 1 ? names[0] : names.length ? T("roomsN", { n: names.length }) : T("rooms");
  $("#roomsBtn").classList.toggle("on", names.length > 0);
  document.querySelectorAll("#roomsMenu [data-room]").forEach((b) =>
    b.classList.toggle("on", b.dataset.room === "all" ? !rooms.on.size : rooms.on.has(+b.dataset.room)));
  invalidate();
}
function buildRooms(list = [], floors = []) {
  rooms.list = list;
  rooms.on = new Set();
  rooms.whole = sectionBox;
  rooms.decks = floors;
  const menu = $("#roomsMenu");
  menu.replaceChildren();
  menu.classList.add("hidden");
  $("#roomsWrap").hidden = !sectionBox || list.length < 2;
  $("#roomsBtn").textContent = T("rooms");
  $("#roomsBtn").classList.remove("on");
  if ($("#roomsWrap").hidden) return;
  const item = (id, label) => {
    const b = document.createElement("button");
    b.dataset.room = id;
    b.textContent = label;
    b.setAttribute("role", "menuitemcheckbox");
    menu.appendChild(b);
    return b;
  };
  item("all", T("roomsAll")).classList.add("on");
  // rooms under the deck whose floor they stand on (a room's height is its middle)
  const deckOf = (r) => Math.max(1, floors.filter((f) => f <= r.y + 0.3).length);
  const groups = new Map();
  for (const r of [...list].sort((a, b) => a.name.localeCompare(b.name))) {
    const d = floors.length > 1 ? deckOf(r) : 0;
    if (!groups.has(d)) groups.set(d, []);
    groups.get(d).push(r);
  }
  for (const d of [...groups.keys()].sort((a, b) => a - b)) {
    if (d) {
      const h = document.createElement("div");
      h.className = "bg-head";
      h.textContent = T("deckN", { n: d });
      menu.appendChild(h);
    }
    for (const r of groups.get(d)) item(r.id, r.name);
  }
}
$("#roomsBtn").addEventListener("click", () => $("#roomsMenu").classList.toggle("hidden"));
$("#roomsMenu").addEventListener("click", (e) => {
  const b = e.target.closest("[data-room]");
  if (!b) return;
  markMotion();
  if (b.dataset.room === "all") { $("#roomsMenu").classList.add("hidden"); showRooms([]); return; }
  const id = +b.dataset.room;
  if (e.ctrlKey || e.shiftKey || e.metaKey) {          // add to (or take from) the rooms shown
    const next = new Set(rooms.on);
    if (next.has(id)) next.delete(id); else next.add(id);
    showRooms(next);
  } else {
    $("#roomsMenu").classList.add("hidden");
    showRooms([id]);
  }
});
document.addEventListener("click", (e) => {
  if (!e.target.closest("#roomsWrap")) $("#roomsMenu").classList.add("hidden");
});

function cullAboveCut() {
  if (!modelRoot) return;
  const y = renderer.clippingPlanes.length ? sectionPlane.constant : Infinity;
  if (poseDirty) syncPose();
  modelRoot.updateMatrixWorld();
  const lone = rooms.on.size > 0;
  batches.cullAbove(y, lone ? roomHidden : null);
  modelRoot.traverse((o) => {
    if (!o.isMesh || o.isBatchedMesh) return;
    let above = lone && roomHidden(o);
    if (!above && y !== Infinity && !o.isSkinnedMesh) {
      if (!o.geometry.boundingBox) o.geometry.computeBoundingBox();
      above = cullBox.copy(o.geometry.boundingBox).applyMatrix4(o.matrixWorld).min.y > y;
    }
    if (above) o.layers.disable(0); else o.layers.enable(0);
  });
}
function applySection() {
  const on = !!sectionBox && state.cut < 0.999;
  if (on) sectionPlane.constant = THREE.MathUtils.lerp(sectionBox.min.y, sectionBox.max.y, state.cut);
  renderer.clippingPlanes = on ? [sectionPlane] : [];
  cullAboveCut();
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
$("#cut").addEventListener("input", (e) => { markMotion(); state.cut = e.target.value / 1000; applySection(); });

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
    mk(String(i + 1), T("deckTitle", { n: i + 1 }), Math.min(1, (top - sectionBox.min.y) / span));
  });
  mk(T("all"), T("roomsAll"), 1);
}

// "Full ship": on from the start, a choice to turn it off is remembered for the session; shown only for ships and vehicles that have a factory loadout
try { state.full = sessionStorage.getItem("vf.full") !== "0"; } catch { /* storage unavailable */ }
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
  if (e.key === "Escape" && document.documentElement.classList.contains("vf-bare") && !document.querySelector("dialog[open]")) { showPanels(true); return; }
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const k = { f: "reset", w: "wire", r: "rotate", g: "grid", h: "panels" }[e.key.toLowerCase()];
  if (k) act(k);
});

// ---------------------------------------------------------------- export
// The pose on screen, for the still exports: every named node's matrix relative to the model root. The server keeps
// it and applies it to the parts (export.posed); "" when the model does not move or the switch is off.
async function poseParam() {
  const root = modelRoot?.getObjectByName("__root__");
  if (!root || !anim.mixer || !anim.list.length || !$("#expPose").checked) return "";
  if (poseDirty) syncPose();
  modelRoot.updateMatrixWorld(true);
  const inv = new THREE.Matrix4().copy(root.matrixWorld).invert(), m = new THREE.Matrix4(), nodes = {};
  root.traverse((o) => {
    if (o === root || !o.name || o.isMesh || o.name.includes("|")) return;
    nodes[o.name] = m.multiplyMatrices(inv, o.matrixWorld).toArray().map((x) => +x.toFixed(6));
  });
  const r = await (await api("/api/pose", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nodes }) })).json();
  return `&pose=${r.id}`;
}
document.querySelectorAll("[data-exp]").forEach((b) => b.addEventListener("click", async () => {
  if (!state.current) return;
  const fmt = b.dataset.exp;
  b.disabled = true;
  try {
    const url = `/api/export?path=${encodeURIComponent(state.current.path)}&fmt=${fmt}&decals=${$("#expDecals").checked}&tex=${$("#expTex").checked}&anim=${$("#expAnim").checked}&full=${state.full}&interior=${state.interior}` +
      (state.variant != null ? `&variant=${encodeURIComponent(state.variant)}` : "") + await poseParam();
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
    const job = await (await api(`/api/print?path=${encodeURIComponent(state.current.path)}&voxel=${voxel}&fill=${$("#fill").checked}&full=${state.full}${await poseParam()}`, { method: "POST" })).json();
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

// ---------------------------------------------------------------- decal sheets
let decalLength = 0;          // longest side of the model, metres
function decalScale() {
  return Math.min(5000, Math.max(1, parseFloat($("#decalScale").value) || 72));
}
function showDecalSize() {
  const mm = decalLength * 1000 / decalScale();
  $("#decalSize").textContent = decalLength ? T("decalSize", { size: mm >= 100 ? `${(mm / 10).toFixed(1)} cm` : `${mm.toFixed(0)} mm` }) : "";
}
try { $("#decalScale").value = localStorage.getItem("vf.decalScale") || 72; $("#decalPaper").value = localStorage.getItem("vf.decalPaper") || "a4"; } catch { /* private mode */ }
$("#decalScale").addEventListener("input", showDecalSize);
$("#btnDecals").addEventListener("click", async () => {
  if (!state.current) return;
  const btn = $("#btnDecals"), out = $("#decalStatus"), scale = decalScale(), paper = $("#decalPaper").value;
  try { localStorage.setItem("vf.decalScale", scale); localStorage.setItem("vf.decalPaper", paper); } catch { /* private mode */ }
  btn.disabled = true;
  out.textContent = T("decalWorking");
  try {
    const r = await api(`/api/decals?path=${encodeURIComponent(state.current.path)}&scale=${scale}&paper=${paper}&full=${state.full}` +
      (state.variant != null ? `&variant=${encodeURIComponent(state.variant)}` : ""));
    const blob = await r.blob();
    const name = (r.headers.get("Content-Disposition") || "").match(/filename="(.+)"/)?.[1] || "decals.zip";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    const i = JSON.parse(r.headers.get("X-Decals") || "{}");
    out.textContent = T("decalReady", { pieces: i.pieces, pages: i.pages }) +
      (i.too_small ? " " + T("decalSmall", { n: i.too_small }) : "") + (i.too_big ? " " + T("decalBig", { n: i.too_big }) : "");
    toast(T("exported", { name, dir: r.headers.get("X-Saved-To") || T("exportsDir") }));
  } catch (e) {
    out.textContent = "";
    toast(T("exportFailed", { error: e.message }), true);
  } finally {
    btn.disabled = false;
  }
});

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
  // the categories are icons: the chosen one is named here, with its number of models
  const all = total > items.length ? T("resultsOf", { n: num(total), shown: items.length }) : T("results", { n: num(total) });
  $("#count").textContent = state.cat && CAT_LABELS[state.cat] ? `${CAT_LABELS[state.cat]} · ${num(total)}` : all;
  $("#count").title = all;
  const ul = $("#results");
  ul.innerHTML = "";
  const frag = document.createDocumentFragment();
  items.forEach((it) => {
    const li = document.createElement("li");
    li.dataset.path = it.path;
    if (state.current?.path === it.path) li.classList.add("active");
    // one line: the name, then the maker; with every file listed ("Main models" off) the file name tells them apart
    const name = document.createElement("span"), sub = document.createElement("span"), files = !$("#mainOnly").checked;
    name.className = "name";
    name.textContent = it.name;
    sub.className = files ? "sub file" : "sub";
    sub.textContent = files ? it.path.split("/").pop() : it.subtitle || CAT_LABELS[it.category] || "";
    li.append(name, sub);
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
  // the sub-categories of the selected category (the makers, for ships): one menu instead of a cloud of chips
  const box = $("#subcats"), subs = SUBCATS[state.cat] || [];
  box.replaceChildren();
  box.hidden = subs.length < 2;
  if (box.hidden) return;
  const sel = document.createElement("select");
  [{ id: "", label: T("all") }, ...subs].forEach((s) =>
    sel.add(new Option(s.count != null ? `${s.label} · ${num(s.count)}` : s.label, s.id, false, s.id === state.sub)));
  sel.addEventListener("change", () => { state.sub = sel.value; runSearch(); });
  box.appendChild(sel);
  dropdown(sel);
}

$("#q").addEventListener("input", scheduleSearch);
$("#mainOnly").addEventListener("change", runSearch);

// ---------------------------------------------------------------- appearance (light / dark)
// "system" follows the OS theme; the choice is kept in config.json so the .exe remembers it too
let appearance = document.documentElement.dataset.mode === "dark" ? "dark" : "light";
try { appearance = localStorage.getItem("vf.appearance") || "system"; } catch { /* storage unavailable */ }
const systemDark = matchMedia("(prefers-color-scheme: dark)");

function applyAppearance(pref) {
  appearance = ["light", "dark"].includes(pref) ? pref : "system";
  try { localStorage.setItem("vf.appearance", appearance); } catch { /* storage unavailable */ }
  const mode = appearance === "system" ? (systemDark.matches ? "dark" : "light") : appearance;
  document.documentElement.dataset.mode = mode;
  $("#btnMode use").setAttribute("href", mode === "dark" ? "#i-sun" : "#i-moon");
  $("#btnMode").title = T(mode === "dark" ? "modeToLight" : "modeToDark");
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
  if (update?.available) pill.querySelector("span").textContent = T("updateTo", { version: update.latest });
}

function openUpdateDialog() {
  if (!update?.available) return;
  $("#updText").textContent = T("updateText", { latest: update.latest, current: update.current });
  $("#updNotes").innerHTML = notesHtml(update.notes || "") || `<p>${esc(T("updateNoNotes"))}</p>`;
  $("#updNotes").classList.toggle("hidden", !update.notes);
  $("#updGo").textContent = T(update.can_install ? "updateNow" : "updateOpenPage");
  $("#updProgress").classList.add("hidden");
  $("#updateDlg").querySelectorAll("button").forEach((b) => { b.disabled = false; });
  if (!$("#updateDlg").open) $("#updateDlg").showModal();
}

async function checkUpdates(force) {
  try {
    update = await (await api(`/api/update/check?force=${force}`)).json();
  } catch (e) {
    if (force) toast(T("updateCheckFailed", { error: e.message }), true);
    return;
  }
  showUpdatePill();
  if (force) {
    if (update.error) toast(T("githubUnreachable", { error: update.error }), true);
    else if (update.available) { $("#settings").close(); openUpdateDialog(); }
    else toast(T("upToDate", { version: update.current }));
  } else if (update.enabled && update.available && !update.skipped && !document.querySelector("dialog[open]")) {
    openUpdateDialog();
  }
}

let installing = false, launching = false;
async function pollUpdate() {
  const box = $("#updProgress");
  try {
    const job = await (await api("/api/update/progress")).json();
    box.querySelector(".bar span").style.width = `${Math.round(job.progress * 100)}%`;
    box.querySelector(".hint").textContent = job.state === "running" ? `${job.message} ${Math.round(job.progress * 100)}%` : job.message;
    launching = job.state === "launching";
    if (job.state === "error") throw new Error(job.message);
    if (job.state === "running") setTimeout(pollUpdate, 400);
    // "launching": the installer takes over and closes this window
  } catch (e) {
    installing = false;
    $("#updateDlg").querySelectorAll("button").forEach((b) => { b.disabled = false; });
    // after the app has quit for the installer the server stops answering: that is expected, not an error
    if (launching) return;
    box.classList.add("hidden");
    toast(T("updateFailed", { error: e.message }), true);
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
    toast(T("updateFailed", { error: e.message }), true);
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
// Language: the list comes from the server, each language under its own name
for (const l of I18N.languages) $("#cfgLang").append(new Option(l.name, l.code));
$("#cfgLang").value = I18N.lang;
const langDropdown = dropdown($("#cfgLang"));
const namesDropdown = dropdown($("#cfgNames"));       // the game's names: in the interface language, or English
let namesWas = "follow";
// the model on screen when the language was changed: opened again once the catalogue is back in the new language
let reopen = null;
try { reopen = sessionStorage.getItem("vf.reopen"); sessionStorage.removeItem("vf.reopen"); } catch { /* storage unavailable */ }
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
    el.textContent = s.error ? `${s.error}: ${T("openSettings")}` : s.ready ? "" : `${s.message} (${Math.round(s.progress * 100)}%)`;
    el.title = s.p4k_path;
    window.__status = s;
    if (s.ready) {
      if (backdrop.kind !== savedBackdrop) backdrop.set(savedBackdrop).catch(() => backdrop.set("plain"));
      await loadCategories();
      runSearch();
      if (reopen) {
        const path = reopen;
        reopen = null;
        api(`/api/related?path=${encodeURIComponent(path)}`).then((r) => r.json())
          .then((list) => { const it = list.find((x) => x.path === path); if (it && !state.current) loadModel(it); })
          .catch(() => { /* the model is simply not reopened */ });
      }
      return;
    }
  } catch { el.textContent = T("serverDown"); }
  setTimeout(pollStatus, 1000);
}

$("#btnSettings").addEventListener("click", async () => {
  const s = await (await api("/api/status")).json();
  $("#cfgP4k").value = s.p4k_path || "";
  $("#cfgExport").value = s.export_dir || "";
  $("#cfgBlender").value = s.blender_setting || "";
  showBlender(s);
  $("#cfgAppearance").value = appearance;
  appearanceDropdown.sync();
  $("#cfgUpdates").checked = s.check_updates !== false;
  $("#versionLine").textContent = T("versionLine", { version: s.version });
  $("#cfgLang").value = I18N.lang;
  langDropdown.sync();
  namesWas = $("#cfgNames").value = s.names === "en" ? "en" : "follow";
  namesDropdown.sync();
  $("#cfgDiskCache").checked = s.disk_cache !== false;
  showCacheSize(s.disk_cache_bytes, s.disk_cache_limit);
  $("#settings").showModal();
});
// saved on the Save button's click (the dialog's "close" event can come late or not at all in a hidden window)
$("#cfgSave").addEventListener("click", async () => {
  const p = new URLSearchParams({ p4k_path: $("#cfgP4k").value, export_dir: $("#cfgExport").value, blender: $("#cfgBlender").value,
    appearance: $("#cfgAppearance").value, check_updates: $("#cfgUpdates").checked, disk_cache: $("#cfgDiskCache").checked,
    lang: $("#cfgLang").value, names: $("#cfgNames").value });
  applyAppearance($("#cfgAppearance").value);
  try {
    const saved = await (await api(`/api/config?${p}`, { method: "POST" })).json();
    if (saved.lang !== I18N.lang || saved.names !== namesWas) {
      // another language (or the game's names in another one): the page starts again, on the same model
      try {
        localStorage.setItem("vf.lang", saved.lang);
        if (state.current) sessionStorage.setItem("vf.reopen", state.current.path);
      } catch { /* storage unavailable */ }
      location.reload();
      return;
    }
    showBlender(saved);
    toast(T("saved"));
    pollStatus();
  } catch (e) { toast(e.message, true); }
});

// Blender (Settings): the path typed (the program or its folder; empty = automatic) and what it leads to
function showBlender(s) {
  const typed = (s.blender_setting || "").trim();
  $("#cfgBlender").placeholder = T(!typed && s.blender ? "blenderAuto" : "blenderPath");
  $("#blenderLine").textContent = s.blender ? T("blenderUsing", { path: s.blender })
    : T(typed ? "blenderNotThere" : "blenderNotFound");
  $("#blenderLine").classList.toggle("missing", !s.blender);
}

// disk cache (Settings → Cache): how much it holds, and a button to empty it
const gb = (n) => (n >= 1073741824 ? `${(n / 1073741824).toFixed(1)} GB` : `${Math.round(n / 1048576)} MB`);
function showCacheSize(bytes = 0, limit = 0) {
  $("#cacheLine").textContent = limit ? T("cacheUse", { size: gb(bytes), limit: gb(limit) }) : T("cacheUseNoLimit", { size: gb(bytes) });
}
$("#btnClearCache").addEventListener("click", async () => {
  try {
    const r = await (await api("/api/cache/clear", { method: "POST" })).json();
    showCacheSize(r.bytes, (await (await api("/api/status")).json()).disk_cache_limit);
    toast(T("cacheCleared"));
  } catch (e) { toast(e.message, true); }
});

// ---------------------------------------------------------------- feedback: reports become public GitHub issues
// The server builds the text (and removes personal data); here: the form, the picture of the view, the list.
const rep = { kind: "bug", timer: 0 };
const JSON_POST = (body) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function gpuName() {
  try {
    const gl = renderer.getContext();
    const ext = gl.getExtension("WEBGL_debug_renderer_info");
    return String(gl.getParameter(ext ? ext.UNMASKED_RENDERER_WEBGL : gl.RENDERER));
  } catch { return ""; }
}

function reportFields() {
  return { kind: rep.kind, title: $("#repTitle").value.trim(), description: $("#repText").value.trim(),
    picture: $("#repPicture").checked, details: $("#repDetails").checked,
    model: state.current?.path || null, variant: state.variant ?? null, gpu: gpuName() };
}

// the 3D view as a JPEG in base64 (no "data:" prefix), at most 2 MB; transparent parts get the page background
function viewPicture() {
  const src = renderer.domElement;
  const bg = getComputedStyle(document.body).backgroundColor || "#10141b";
  for (const [side, quality] of [[1600, 0.85], [1200, 0.75], [900, 0.7]]) {
    const k = Math.min(1, side / Math.max(src.width, src.height));
    const c = document.createElement("canvas");
    c.width = Math.max(1, Math.round(src.width * k));
    c.height = Math.max(1, Math.round(src.height * k));
    const g = c.getContext("2d");
    g.fillStyle = bg;
    g.fillRect(0, 0, c.width, c.height);
    drawNow();
    g.drawImage(src, 0, 0, c.width, c.height);
    const b64 = c.toDataURL("image/jpeg", quality).split(",")[1];
    if (b64.length * 0.75 <= 2_000_000) return b64;
  }
  return null;
}

function reportReady() {
  const f = reportFields();
  // same rule as the service: at least 4 characters that are not spaces
  $("#repSend").disabled = f.title.replace(/\s/g, "").length < 4 || f.description.length < 10;
}

async function refreshPreview() {
  if (!$("#repPreviewBox").open) return;
  try {
    const c = await (await api("/api/report/preview", JSON_POST(reportFields()))).json();
    $("#repPreview").textContent = `${c.title}\n\n${c.body.replace("<!-- screenshot -->", "[picture of the 3D view]")}`;
  } catch (e) { $("#repPreview").textContent = e.message; }
}

function reportChanged() {
  reportReady();
  clearTimeout(rep.timer);
  rep.timer = setTimeout(refreshPreview, 400);
}

function showReportError(text, offerGitHub = false) {
  $("#repError").textContent = text;
  $("#repError").classList.toggle("hidden", !text);
  $("#repFallback").classList.toggle("hidden", !offerGitHub);
}

const REPORT_ERRORS = {
  rate: () => T("repRate"),
  invalid: (detail) => detail || T("repInvalid"),
  unavailable: () => T("repUnavailable"),
  network: () => T("repNetwork"),
  local: (detail) => (detail ? T("repLocal", { detail }) : T("repLocalNoDetail")),
};

async function loadMyReports() {
  const list = $("#repList");
  list.replaceChildren();
  $("#repMineNote").textContent = T("loading");
  try {
    const { reports, news } = await (await api("/api/report/mine")).json();
    const STATES = { open: T("repOpen"), closed: T("repClosed"), removed: T("repRemoved") };
    for (const r of reports) {
      const comments = r.comments ? `${plural(r.comments, "repCommentsOne", "repCommentsMany")} · ` : "";
      const btn = el("button", r.new ? "rep-item is-new" : "rep-item");
      btn.type = "button";
      btn.append(el("span", "rep-num", `#${r.number}`), el("span", "rep-title", r.title),
        el("span", `rep-state ${r.state || ""}`, STATES[r.state] || ""),
        el("span", "rep-meta", (r.news ? `${T("repNewSince", { n: r.news })} · ` : "") + comments + r.date));
      btn.addEventListener("click", () => api("/api/report/open", JSON_POST({ number: r.number })).catch((e) => toast(e.message, true)));
      const li = el("li");
      li.append(btn);
      list.append(li);
    }
    $("#repMineNote").textContent = T(!reports.length ? "repNone"
      : reports.some((r) => r.state == null) ? "repStatusUnavailable" : "repClickOpen");
    // shown now, so no longer news (the highlight stays in this list until it is reopened)
    if (news) api("/api/report/seen", { method: "POST" }).then(() => showReportNews(0)).catch(() => {});
  } catch (e) { $("#repMineNote").textContent = e.message; }
}

// the Feedback button turns blue when a sent report was closed, reopened or got replies since the user last looked
// news = notifications: one per new comment, one per report closed or reopened
function showReportNews(news) {
  const b = $("#btnReport");
  b.classList.toggle("has-news", news > 0);
  $("#reportCount").textContent = news > 99 ? "99+" : String(news);
  $("#reportCount").classList.toggle("hidden", !(news > 0));
  b.title = news > 0 ? plural(news, "repNewsOne", "repNewsMany") : T("reportTitle");
}
showReportNews(0);

// GitHub is asked at most once a minute (the server keeps statuses 60 s) with one request for all reports, and
// never when nothing was sent: every 5 minutes, and when the window comes back to the front
let reportCheckedAt = 0;
async function checkReportNews() {
  reportCheckedAt = Date.now();
  try {
    const { news } = await (await api("/api/report/mine")).json();
    showReportNews(news);
  } catch { /* offline: try again later */ }
}
setTimeout(checkReportNews, 4000);                       // after the update check, which shares GitHub's public limit
setInterval(checkReportNews, 5 * 60 * 1000);
const recheckReports = () => { if (!document.hidden && Date.now() - reportCheckedAt > 60 * 1000) checkReportNews(); };
window.addEventListener("focus", recheckReports);
document.addEventListener("visibilitychange", recheckReports);

function showReportTab(tab) {
  document.querySelectorAll("#reportDlg .tab").forEach((b) => b.classList.toggle("is-on", b.dataset.tab === tab));
  $("#repNew").classList.toggle("hidden", tab !== "new");
  $("#repMine").classList.toggle("hidden", tab !== "mine");
  if (tab === "mine") loadMyReports();
}

$("#btnReport").addEventListener("click", () => {
  showReportTab($("#btnReport").classList.contains("has-news") ? "mine" : "new");
  showReportError("");
  reportReady();
  $("#reportDlg").showModal();
});
document.querySelectorAll("#reportDlg .tab").forEach((b) => b.addEventListener("click", () => showReportTab(b.dataset.tab)));
document.querySelectorAll("#reportDlg .kind").forEach((b) => b.addEventListener("click", () => {
  rep.kind = b.dataset.kind;
  document.querySelectorAll("#reportDlg .kind").forEach((k) => k.classList.toggle("is-on", k === b));
  reportChanged();
}));
for (const id of ["#repTitle", "#repText"]) $(id).addEventListener("input", reportChanged);
for (const id of ["#repPicture", "#repDetails"]) $(id).addEventListener("change", reportChanged);
$("#repPreviewBox").addEventListener("toggle", refreshPreview);
// Enter in the title would submit the dialog's form and close it
$("#repTitle").addEventListener("keydown", (e) => { if (e.key === "Enter") e.preventDefault(); });

$("#repSend").addEventListener("click", async () => {
  const f = reportFields();
  if (f.picture) f.screenshot = viewPicture();
  const btn = $("#repSend");
  showReportError("");
  btn.disabled = true;
  btn.textContent = T("repSending");
  try {
    const r = await fetch("/api/report", JSON_POST(f));
    const out = await r.json().catch(() => ({}));
    // 502 = the service answered with an error kind; anything else failed here, in the local server
    if (!r.ok) throw r.status === 502 ? out : { kind: "local", detail: out.detail };
    if (out.saved === false) toast(T("repSentUnsaved", { n: out.number }), true);
    else toast(T("repSent", { n: out.number }));
    $("#repTitle").value = "";
    $("#repText").value = "";
    showReportTab("mine");
  } catch (e) {
    const kind = REPORT_ERRORS[e?.kind] ? e.kind : "network";
    showReportError(REPORT_ERRORS[kind](e?.detail), kind === "network" || kind === "unavailable");
  } finally {
    btn.textContent = T("repSend");
    reportReady();
  }
});

$("#repFallback").addEventListener("click", () =>
  api("/api/report/open", JSON_POST({ fallback: reportFields() })).catch((e) => toast(e.message, true)));

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

pollStatus();
