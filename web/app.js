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

// ---------------------------------------------------------------- language (the server keeps it in config.json)
const STRINGS = {
  en: {
    starting: "Starting…", settings: "Settings", settingsBtn: "⚙ Settings", searchPh: "Search: P4-AR, Gladius, Morozov, multitool…",
    mainOnly: "Main models only", emptyMsg: "Search for an item on the left and click it to view it in 3D.",
    emptyHint: "Drag to rotate · wheel to zoom · right button to pan", loading: "Loading…", loadingOf: "Loading {name}…",
    frame: "⤢ Frame", frameT: "Frame (F)", wire: "▦ Wireframe", wireT: "Wireframe (W)", rotate: "⟳ Rotate", rotateT: "Auto-rotate (R)",
    grid: "# Grid", gridT: "Grid (G)", bg: "◐ Background", bgT: "Light/dark background", shot: "📷 Screenshot", shotT: "Save PNG image",
    tex: "Textures", texT: "Game textures (colour and normal map). Turn off to see only the material colours",
    decals: "Decals", glass: "Glass", proxy: "Proxy/physics", noModel: "No model selected.", export: "Export",
    glbT: "Binary glTF with materials and textures (Blender, Windows 3D Viewer…)", objT: "OBJ + MTL + textures in a zip",
    stlT: "Raw STL in millimetres, game surfaces as they are", expDecals: "include decals in OBJ/STL", expTex: "textures in GLB/OBJ",
    print: "3D printing", printHint: "Creates a solid, closed STL (in mm), ready for the slicer. Uses Blender in the background; large objects can take a few minutes.",
    fill: "fill interior", printBtn: "Create printable STL", openExports: "📂 Open exports folder", materials: "Materials",
    clickHide: "(click to hide)", related: "Other files in the folder", cfgP4k: "Data.p4k path", cfgExport: "Exports folder",
    cfgBlender: "Blender (blender.exe, for 3D printing)", autoDetected: "detected automatically", cfgLang: "Language",
    cancel: "Cancel", save: "Save", width: "Width", length: "Length", height: "Height", triangles: "Triangles", parts: "Parts",
    variant: "Variant / paint", loadFailed: "Could not load the model: {error}", exported: "Exported {name} (copy saved to {dir})",
    exportsDir: "exports", exportFailed: "Export failed: {error}", print3d: "3D print: {error}",
    printReady: "Ready: {size} mm, {volume} cm³, {closed}.", closedYes: "closed ✓", closedNo: "not fully closed",
    downloadStl: "Download STL", printDone: "Printable STL of {name} ready", results: "{n} results", resultsOf: "{n} results (first {shown})",
    all: "All", openSettings: "open Settings to fix the path", serverDown: "Server not reachable…", saved: "Settings saved",
    kindDecal: "decal", kindGlass: "glass", kindProxy: "proxy",
  },
  it: {
    starting: "Avvio…", settings: "Impostazioni", settingsBtn: "⚙ Impostazioni", searchPh: "Cerca: P4-AR, Gladius, Morozov, multitool…",
    mainOnly: "Solo modelli principali", emptyMsg: "Cerca un oggetto a sinistra e cliccalo per vederlo in 3D.",
    emptyHint: "Trascina per ruotare · rotella per lo zoom · tasto destro per spostare", loading: "Caricamento…", loadingOf: "Caricamento di {name}…",
    frame: "⤢ Inquadra", frameT: "Inquadra (F)", wire: "▦ Wireframe", wireT: "Wireframe (W)", rotate: "⟳ Ruota", rotateT: "Rotazione automatica (R)",
    grid: "# Griglia", gridT: "Griglia (G)", bg: "◐ Sfondo", bgT: "Sfondo chiaro/scuro", shot: "📷 Screenshot", shotT: "Salva immagine PNG",
    tex: "Texture", texT: "Texture del gioco (colore e rilievo). Disattiva per vedere solo i colori dei materiali",
    decals: "Decal", glass: "Vetri", proxy: "Proxy/fisica", noModel: "Nessun modello selezionato.", export: "Esporta",
    glbT: "glTF binario con materiali e texture (Blender, Windows 3D Viewer…)", objT: "OBJ + MTL + texture in uno zip",
    stlT: "STL grezzo in millimetri, superfici del gioco così come sono", expDecals: "includi decal in OBJ/STL", expTex: "texture in GLB/OBJ",
    print: "Stampa 3D", printHint: "Crea un STL solido e chiuso (in mm), pronto per lo slicer. Usa Blender in background; per oggetti grandi può richiedere qualche minuto.",
    fill: "riempi interno", printBtn: "Crea STL per stampa", openExports: "📂 Apri cartella esportazioni", materials: "Materiali",
    clickHide: "(clic per nascondere)", related: "Altri file nella cartella", cfgP4k: "Percorso di Data.p4k", cfgExport: "Cartella esportazioni",
    cfgBlender: "Blender (blender.exe, per la stampa 3D)", autoDetected: "rilevato automaticamente", cfgLang: "Lingua",
    cancel: "Annulla", save: "Salva", width: "Larghezza", length: "Lunghezza", height: "Altezza", triangles: "Triangoli", parts: "Parti",
    variant: "Variante / verniciatura", loadFailed: "Impossibile caricare il modello: {error}", exported: "Esportato {name} (copia salvata in {dir})",
    exportsDir: "esportazioni", exportFailed: "Esportazione fallita: {error}", print3d: "Stampa 3D: {error}",
    printReady: "Pronto: {size} mm, {volume} cm³, {closed}.", closedYes: "chiuso ✓", closedNo: "non del tutto chiuso",
    downloadStl: "Scarica STL", printDone: "STL per la stampa di {name} pronto", results: "{n} risultati", resultsOf: "{n} risultati (primi {shown})",
    all: "Tutto", openSettings: "apri le Impostazioni per correggere il percorso", serverDown: "Server non raggiungibile…", saved: "Impostazioni salvate",
    kindDecal: "decal", kindGlass: "vetro", kindProxy: "proxy",
  },
};
let lang = "en";
const T = (key, vars = {}) => (STRINGS[lang][key] ?? STRINGS.en[key] ?? key).replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? "");
const num = (n) => n.toLocaleString(lang === "it" ? "it-IT" : "en-US");

function setLang(l) {
  if (!STRINGS[l] || (l === lang && document.documentElement.lang === l)) return false;
  lang = l;
  document.documentElement.lang = l;
  document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = T(el.dataset.i18n); });
  document.querySelectorAll("[data-i18n-title]").forEach((el) => { el.title = T(el.dataset.i18nTitle); });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => { el.placeholder = T(el.dataset.i18nPlaceholder); });
  return true;
}

const CAT_LABELS = {};
const KIND_LABELS = { solid: "", decal: "kindDecal", glass: "kindGlass", hidden: "kindProxy" };
const state = { cat: "", current: null, kinds: { decal: false, glass: true, hidden: false }, matOff: new Set(), printJob: null, tex: true, variant: null };
try { state.tex = localStorage.getItem("vf.tex") !== "0"; } catch { /* storage unavailable */ }

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

function resize() {
  const w = wrap.clientWidth, h = wrap.clientHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / Math.max(h, 1);
  camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(wrap);
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
  const dist = radius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2)) * 1.05;
  camera.near = dist / 1000;
  camera.far = dist * 100;
  camera.updateProjectionMatrix();
  // three/quarter view from the front-left (models are Y-up, forward = -Z after export)
  camera.position.copy(center).add(new THREE.Vector3(-0.9, 0.55, -1.0).normalize().multiplyScalar(dist));
  controls.target.copy(center);
  controls.update();
  sun.position.copy(center).add(new THREE.Vector3(radius * 2, radius * 3, radius * 2.5));
}

function buildGrid(box) {
  if (grid) scene.remove(grid);
  const size = box.getSize(new THREE.Vector3());
  const span = Math.max(size.x, size.z) * 1.6;
  const step = Math.pow(10, Math.floor(Math.log10(span / 10)));
  const cells = Math.ceil(span / step);
  grid = new THREE.GridHelper(cells * step, cells, 0x2f4a60, 0x1c2a36);
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
  $("#info").innerHTML = `<h2>${esc(item.name)}</h2><div class="path">${esc(item.path)}</div><p class="muted">${T("loading")}</p>`;
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
    $("#info").innerHTML = `<h2>${esc(item.name)}</h2><div class="path">${esc(item.path)}</div><p class="warn">${esc(e.message)}</p>`;
    toast(T("loadFailed", { error: e.message }), true);
  } finally {
    $("#loading").classList.add("hidden");
  }
}

function fmtLen(m) {
  if (m >= 10) return `${m.toFixed(2)} m`;
  if (m >= 1) return `${m.toFixed(3)} m`;
  return `${(m * 1000).toFixed(1)} mm`;
}

function showInfo(item, info) {
  const s = info.stats;
  const [x, y, z] = s.size_m;
  $("#info").classList.remove("muted");
  $("#info").innerHTML = `
    <h2>${esc(item.name)}</h2>
    <div class="muted">${esc(item.subtitle || CAT_LABELS[item.category] || "")}</div>
    <div class="path">${esc(item.path)}</div>
    <dl class="stats">
      <dt>${T("width")}</dt><dd>${fmtLen(x)}</dd>
      <dt>${T("length")}</dt><dd>${fmtLen(y)}</dd>
      <dt>${T("height")}</dt><dd>${fmtLen(z)}</dd>
      <dt>${T("triangles")}</dt><dd>${num(s.triangles)}</dd>
      <dt>${T("parts")}</dt><dd>${s.parts}</dd>
      <dt>${T("materials")}</dt><dd>${s.materials.length}</dd>
    </dl>
    ${info.variants.length > 1 ? `<label class="variant">${T("variant")}
      <select id="variantSel">${info.variants.map((v) => `<option value="${esc(v.tag)}"${v.tag === info.variant ? " selected" : ""}>${esc(v.label)}</option>`).join("")}</select></label>` : ""}
    ${info.warnings.map((w) => `<div class="warn">⚠ ${esc(w)}</div>`).join("")}`;
  $("#variantSel")?.addEventListener("change", (e) => {
    state.variant = e.target.value;
    loadModel(state.current, true);
  });
  $("#exportBox").classList.remove("hidden");
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
    li.innerHTML = `<span class="swatch" style="background:#${m.color}"></span><span>${esc(name)}</span><span class="kind">${KIND_LABELS[m.kind] ? T(KIND_LABELS[m.kind]) : ""}</span>`;
    li.classList.toggle("off", state.matOff.has(name));
    li.onclick = () => {
      state.matOff.has(name) ? state.matOff.delete(name) : state.matOff.add(name);
      li.classList.toggle("off", state.matOff.has(name));
      applyVisibility();
    };
    ul.appendChild(li);
  });
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
      li.innerHTML = `<span>${esc(r.path.split("/").pop())}</span><span class="sub">${r.ext}</span>`;
      li.title = r.name;
      li.onclick = () => loadModel(r);
      ul.appendChild(li);
    });
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
  if (a === "bg") wrap.classList.toggle("light");
  if (a === "shot") {
    const link = document.createElement("a");
    link.download = `${(state.current?.path.split("/").pop() || "modello").replace(/\.\w+$/, "")}.png`;
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
  if (e.target.tagName === "INPUT") return;
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
    const name = (r.headers.get("Content-Disposition") || "").match(/filename="(.+)"/)?.[1] || `modello.${fmt}`;
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
    li.innerHTML = `<div class="name">${esc(it.name)}<span class="badge">${it.ext}</span></div>
      <div class="sub">${esc(it.subtitle || CAT_LABELS[it.category] || "")}</div>
      <div class="sub">${esc(it.path.split("/").pop())}</div>`;
    li.title = it.path;
    li.onclick = () => loadModel(it);
    frag.appendChild(li);
  });
  ul.appendChild(frag);
}

async function loadCategories() {
  const cats = await (await api("/api/categories")).json();
  const box = $("#cats");
  box.innerHTML = "";
  const mk = (id, label, n) => {
    const c = document.createElement("span");
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

// ---------------------------------------------------------------- status & settings
async function pollStatus() {
  try {
    const s = await (await api("/api/status")).json();
    const el = $("#status");
    el.classList.toggle("err", !!s.error);
    if (setLang(s.ui_lang)) refreshTexts();
    el.textContent = s.error ? `⚠ ${s.error} — ${T("openSettings")}` : s.message + (s.ready ? "" : ` (${Math.round(s.progress * 100)}%)`);
    el.title = s.p4k_path;
    window.__status = s;
    if (s.ready) {
      await loadCategories();
      runSearch();
      return;
    }
  } catch { $("#status").textContent = T("serverDown"); }
  setTimeout(pollStatus, 1000);
}

$("#btnSettings").addEventListener("click", async () => {
  const s = await (await api("/api/status")).json();
  $("#cfgP4k").value = s.p4k_path || "";
  $("#cfgExport").value = s.export_dir || "";
  $("#cfgBlender").value = s.blender || "";
  $("#cfgLang").value = s.ui_lang || lang;
  $("#settings").showModal();
});
$("#settings").addEventListener("close", async () => {
  if ($("#settings").returnValue !== "save") return;
  const p = new URLSearchParams({ p4k_path: $("#cfgP4k").value, export_dir: $("#cfgExport").value, blender: $("#cfgBlender").value,
    ui_lang: $("#cfgLang").value });
  try {
    await api(`/api/config?${p}`, { method: "POST" });
    if (setLang($("#cfgLang").value)) refreshTexts();
    toast(T("saved"));
    pollStatus();
  } catch (e) { toast(e.message, true); }
});

// texts built by the script (model info, results, categories) are redrawn in the new language
function refreshTexts() {
  if (state.current) loadModel(state.current, true);
  else $("#info").textContent = T("noModel");
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

pollStatus();
