import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

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
  printReady: "Ready: {size} mm, {volume} cm³, {closed}.", closedYes: "watertight ✓", closedNo: "not fully closed",
  downloadStl: "Download STL", printDone: "Printable STL of {name} ready", results: "{n} results",
  resultsOf: "{n} results · showing {shown}", all: "All", openSettings: "open Settings to fix the path",
  serverDown: "Server not reachable…", saved: "Settings saved", kindDecal: "decal", kindGlass: "glass", kindProxy: "proxy",
};
const T = (key, vars = {}) => (STRINGS[key] ?? key).replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? "");
const num = (n) => n.toLocaleString("en-US");

const CAT_LABELS = {};
const KIND_LABELS = { solid: "", decal: "kindDecal", glass: "kindGlass", hidden: "kindProxy" };
const state = { cat: "", current: null, kinds: { decal: false, glass: true, hidden: false }, matOff: new Set(), printJob: null, tex: true, variant: null };
try { state.tex = localStorage.getItem("vf.tex") !== "0"; } catch { /* storage unavailable */ }

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
scene.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;
const camera = new THREE.PerspectiveCamera(40, 1, 0.001, 10000);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
scene.add(new THREE.HemisphereLight(0xdde8ff, 0x202830, 0.6));
const sun = new THREE.DirectionalLight(0xffffff, 1.4);
sun.position.set(3, 5, 4);
scene.add(sun);

let grid = null;
let modelRoot = null;
let wireframe = false;

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
}
new ResizeObserver(resize).observe(wrap);
window.addEventListener("resize", resize);
resize();

renderer.setAnimationLoop(() => {
  controls.update();
  renderer.render(scene, camera);
});

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
  sun.position.copy(center).add(new THREE.Vector3(radius * 2, radius * 3, radius * 2.5));
}

function cssColor(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v ? new THREE.Color(v) : new THREE.Color(fallback);
}

function buildGrid(box) {
  if (grid) scene.remove(grid);
  const size = box.getSize(new THREE.Vector3());
  const span = Math.max(size.x, size.z) * 1.6;
  const step = Math.pow(10, Math.floor(Math.log10(span / 10)));
  const cells = Math.ceil(span / step);
  grid = new THREE.GridHelper(cells * step, cells, cssColor("--grid-major", "#2f4a60"), cssColor("--grid-minor", "#1c2a36"));
  grid.position.set((box.min.x + box.max.x) / 2, box.min.y, (box.min.z + box.max.z) / 2);
  grid.visible = $('[data-act="grid"]').classList.contains("on");
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
  if (!modelRoot) return;
  modelRoot.traverse((o) => {
    if (!o.isMesh) return;
    const kind = meshKind(o);
    const kindOn = kind === "solid" ? true : state.kinds[kind];
    o.visible = kindOn && !state.matOff.has(meshMat(o));
  });
}

function applyWireframe() {
  modelRoot?.traverse((o) => { if (o.isMesh) o.material.wireframe = wireframe; });
}

async function loadModel(item, keepView = false) {
  if (state.current?.path !== item.path) state.variant = null;
  state.current = item;
  if (!keepView) state.matOff.clear();
  const v = state.variant != null ? `&variant=${encodeURIComponent(state.variant)}` : "";
  document.querySelectorAll(".results li").forEach((li) => li.classList.toggle("active", li.dataset.path === item.path));
  $("#empty").classList.add("hidden");
  $("#loading").classList.remove("hidden");
  $("#loadingText").textContent = T("loadingOf", { name: item.name });
  if (!keepView) $("#info").innerHTML = infoHead(item) + `<p class="hint">${T("loading")}</p>`;
  try {
    const [infoRes, glbRes] = await Promise.all([
      api(`/api/model/info?path=${encodeURIComponent(item.path)}${v}`),
      api(`/api/model/glb?path=${encodeURIComponent(item.path)}&tex=${state.tex}${v}`),
    ]);
    if (state.current !== item) return;  // user clicked something else meanwhile
    const info = await infoRes.json();
    state.variant = info.variant;
    const buf = await glbRes.arrayBuffer();
    const gltf = await new GLTFLoader().parseAsync(buf, "");
    if (modelRoot) {
      scene.remove(modelRoot);
      modelRoot.traverse((o) => { if (o.isMesh) { o.geometry.dispose(); o.material.dispose(); } });
    }
    modelRoot = gltf.scene;
    modelRoot.traverse((o) => {
      if (o.isMesh) {
        o.material.side = THREE.DoubleSide;
        o.material.envMapIntensity = 0.6;   // the studio environment washes dark paints out to grey
        if (meshKind(o) === "glass") { o.material.transparent = true; o.material.opacity = 0.35; o.material.depthWrite = false; }
      }
    });
    scene.add(modelRoot);
    applyWireframe();
    applyVisibility();
    buildGrid(new THREE.Box3().setFromObject(modelRoot));
    if (!keepView) frame();
    showInfo(item, info);
    showMaterials();
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
    if (!mats.has(name)) mats.set(name, { kind: meshKind(o), color: o.material.color.getHexString() });
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
function act(a, b = document.querySelector(`[data-act="${a}"]`)) {
  if (a === "reset") frame();
  if (a === "wire") { wireframe = !wireframe; b.classList.toggle("on", wireframe); applyWireframe(); }
  if (a === "rotate") { controls.autoRotate = !controls.autoRotate; b.classList.toggle("on", controls.autoRotate); }
  if (a === "grid") { b.classList.toggle("on"); if (grid) grid.visible = b.classList.contains("on"); }
  if (a === "bg") { wrap.classList.toggle("alt"); b.classList.toggle("on", wrap.classList.contains("alt")); }
  if (a === "shot") {
    const link = document.createElement("a");
    link.download = `${(state.current?.path.split("/").pop() || "model").replace(/\.\w+$/, "")}.png`;
    link.href = renderer.domElement.toDataURL("image/png");
    link.click();
  }
}
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
    const url = `/api/export?path=${encodeURIComponent(state.current.path)}&fmt=${fmt}&decals=${$("#expDecals").checked}&tex=${$("#expTex").checked}` +
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
    const job = await (await api(`/api/print?path=${encodeURIComponent(state.current.path)}&voxel=${voxel}&fill=${$("#fill").checked}`, { method: "POST" })).json();
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
  const params = new URLSearchParams({ q, cat: state.cat, main: $("#mainOnly").checked, limit: 400 });
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
  const mk = (id, label, n) => {
    const c = document.createElement("button");
    c.className = "chip" + (state.cat === id ? " on" : "");
    c.innerHTML = `${esc(label)}${n != null ? `<span class="n">${num(n)}</span>` : ""}`;
    c.onclick = () => { state.cat = state.cat === id ? "" : id; loadCategoriesUI(); runSearch(); };
    c.dataset.id = id;
    return c;
  };
  box.appendChild(mk("", T("all")));
  cats.forEach((c) => { CAT_LABELS[c.id] = c.label; box.appendChild(mk(c.id, c.label, c.count)); });
}
function loadCategoriesUI() {
  document.querySelectorAll(".chip").forEach((c) => c.classList.toggle("on", c.dataset.id === state.cat));
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

// ---------------------------------------------------------------- status & settings
const appearanceDropdown = dropdown($("#cfgAppearance"));
let appearanceLoaded = false;
async function pollStatus() {
  const el = $("#status");
  try {
    const s = await (await api("/api/status")).json();
    if (!appearanceLoaded && s.appearance) { appearanceLoaded = true; applyAppearance(s.appearance); }
    el.classList.toggle("err", !!s.error);
    el.classList.toggle("ready", !!s.ready && !s.error);
    // once the catalogue is ready the status line has nothing useful to say: it only shows progress and errors
    el.textContent = s.error ? `${s.error} — ${T("openSettings")}` : s.ready ? "" : `${s.message} (${Math.round(s.progress * 100)}%)`;
    el.title = s.p4k_path;
    window.__status = s;
    if (s.ready) {
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
  $("#settings").showModal();
});
$("#settings").addEventListener("close", async () => {
  if ($("#settings").returnValue !== "save") return;
  const p = new URLSearchParams({ p4k_path: $("#cfgP4k").value, export_dir: $("#cfgExport").value, blender: $("#cfgBlender").value,
    appearance: $("#cfgAppearance").value });
  applyAppearance($("#cfgAppearance").value);
  try {
    await api(`/api/config?${p}`, { method: "POST" });
    toast(T("saved"));
    pollStatus();
  } catch (e) { toast(e.message, true); }
});

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

pollStatus();
