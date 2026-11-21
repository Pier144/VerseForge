// Skin Lab: make a paint of your own from one of the game's (docs/superpowers/specs/2026-11-21-skin-lab-colori-design.md).
// A skin is a small JSON (sc_explorer/skins.py): the paint it starts from, the colours and finishes of the palette
// entries A, B, C and of the glass, and the colours of single materials that have one of their own (armour, weapon
// parts). While a colour is dragged the model is recoloured here (gamelook.js retint); a moment later the server
// builds the same paint from a draft kept in memory and it is swapped in like any paint. Nothing is written until
// Save. The app (app.js) hands over what the lab needs in `ctx`.
//
// The panels are built as HTML text, like the rest of the app: every piece of text that does not come from this
// file (skin names, which may come from a file someone else made, material and paint names, translations) goes
// through ctx.esc() first.
import { retint } from "./gamelook.js";

const SLOTS = ["A", "B", "C"];
const SLOT_NAMES = { A: "labPrimary", B: "labSecondary", C: "labTertiary", glass: "labGlass" };
const FINISHES = ["base", "gloss", "satin", "matte", "metal"];
const FIN_NAMES = { base: "finBase", gloss: "finGloss", satin: "finSatin", matte: "finMatte", metal: "finMetal" };
const PARTS_SHOWN = 10;            // rows of the "Part colours" list before "Show all"
const CONFIRM_MS = 300;            // quiet time after the last touch before the server confirms the paint
const HEX = /^#?([0-9a-f]{6})$/i;

const hex = (c) => "#" + c.map((x) => Math.round(x).toString(16).padStart(2, "0")).join("");
function rgb(text) {
  const m = String(text).trim().match(HEX);
  return m ? [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16)) : null;
}
// "Panel_Main_LF_primary" -> "Panel Main LF primary"
function pretty(name) {
  const s = name.replace(/_/g, " ").replace(/\s+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}
const tile = (colors) => (colors
  ? `linear-gradient(135deg, rgb(${colors[0]}) 0 52%, rgb(${colors[1]}) 52% 80%, rgb(${colors[2]}) 80%)` : "");
const isSkinTag = (tag) => String(tag ?? "").startsWith("skin:");
// the one place markup is put into the page (see the note at the top: the text in it is escaped by the callers)
function fill(el, markup) {
  el.replaceChildren(document.createRange().createContextualFragment(markup));
}

export function initSkinLab(ctx) {
  const { $, api, T, toast, esc } = ctx;
  const root = document.documentElement;
  const lab = { on: false, entering: false, item: null, skin: null, saved: "", base: null, baseTag: null, baseGone: false,
    prev: null, comparing: false, rev: 0, timer: 0, open: null, allParts: false, mine: [], folder: "", busy: false };

  // ------------------------------------------------------------ the skin's paint, as the server computes it
  function look(colour, f, baseSpec, baseGloss) {
    const P = lab.base.presets, preset = f?.preset || "base";
    let spec = baseSpec, gloss = baseGloss, col = colour;
    if (preset === "metal") { spec = colour; gloss = P.metal; col = colour.map((c) => Math.round(c * lab.base.metal_tint)); }
    else if (preset !== "base") { spec = lab.base.dielectric; gloss = P[preset]; }
    if (f?.gloss != null) gloss = f.gloss;
    return { color: col, spec, gloss };
  }
  // skins.effective, for the live preview
  function effective() {
    const b = lab.base.palette, p = lab.skin.palette || {}, fin = p.finish || {};
    const out = { spec: {}, gloss: {}, materials: {} };
    for (const k of SLOTS) {
      const c = p[k] || b[k];
      if (!c) { out[k] = null; continue; }
      const e = look(c, fin[k], b.spec?.[k] || lab.base.dielectric, b.gloss?.[k] ?? lab.base.presets.satin);
      out[k] = e.color; out.spec[k] = e.spec; out.gloss[k] = e.gloss;
    }
    for (const [id, m] of Object.entries(lab.skin.materials || {})) {
      const preset = m.finish?.preset || "base";
      if (m.color) out.materials[id] = look(m.color, m.finish, null, null);
      else if (m.finish && ((preset !== "base" && preset !== "metal") || m.finish.gloss != null)) {
        out.materials[id] = { ...look([0, 0, 0], m.finish, null, null), color: null };
        if (preset === "metal") out.materials[id].spec = null;
      }
    }
    return out;
  }

  // ------------------------------------------------------------ what a row edits
  const isPart = (key) => key.startsWith("m:");
  const part = (key) => lab.base.materials.find((m) => m.id === key.slice(2));
  function colourOf(key) {
    if (isPart(key)) return lab.skin.materials?.[key.slice(2)]?.color || part(key).color;
    return lab.skin.palette?.[key] || lab.base.palette[key] || [128, 128, 128];
  }
  const finishOf = (key) => (isPart(key) ? lab.skin.materials?.[key.slice(2)]?.finish : lab.skin.palette?.finish?.[key]) || {};
  function glossOf(key) {
    const f = finishOf(key);
    if (f.gloss != null) return f.gloss;
    const P = lab.base.presets, preset = f.preset || "base";
    if (preset !== "base") return P[preset];
    return isPart(key) ? null : lab.base.palette.gloss?.[key] ?? P.satin;
  }
  const changed = (key) => (isPart(key) ? !!lab.skin.materials?.[key.slice(2)]
    : !!(lab.skin.palette?.[key] || lab.skin.palette?.finish?.[key]));
  function setColour(key, c) {
    if (isPart(key)) {
      lab.skin.materials ||= {};
      (lab.skin.materials[key.slice(2)] ||= {}).color = c;
    } else {
      (lab.skin.palette ||= {})[key] = c;
    }
  }
  function setFinish(key, patch) {
    const tidy = (f) => { if (f.gloss == null) delete f.gloss; return f; };
    if (isPart(key)) {
      lab.skin.materials ||= {};
      const m = (lab.skin.materials[key.slice(2)] ||= {});
      const f = m.finish = tidy({ ...(m.finish || {}), ...patch });
      if ((f.preset || "base") === "base" && f.gloss == null) delete m.finish;
      if (!m.color && !m.finish) delete lab.skin.materials[key.slice(2)];
    } else {
      const fin = ((lab.skin.palette ||= {}).finish ||= {});
      const f = fin[key] = tidy({ ...(fin[key] || {}), ...patch });
      if ((f.preset || "base") === "base" && f.gloss == null) delete fin[key];
    }
  }
  function reset(key) {
    if (isPart(key)) delete lab.skin.materials?.[key.slice(2)];
    else { delete lab.skin.palette?.[key]; delete lab.skin.palette?.finish?.[key]; }
  }

  // ------------------------------------------------------------ live preview, then the server's confirmation
  const dirty = () => JSON.stringify(lab.skin) !== lab.saved;
  // the paint on screen is the draft's (or the model was loaded with it): its materials are the lab's to recolour.
  // A game paint's materials are kept by the paint switch for later and must stay as they are.
  const draftShown = () => { const s = ctx.paintSwap(); return !s || String(s.current).startsWith("skin:draft"); };
  function touched() {
    const live = draftShown() && !lab.comparing;
    lab.comparing = false;
    if (live) { retint(ctx.liveMaterials(), effective()); ctx.invalidate(400); }
    syncButtons();
    clearTimeout(lab.timer);
    lab.timer = setTimeout(() => confirm(), live ? CONFIRM_MS : 0);
  }
  // the draft goes to the server, which answers with the paint it makes: swapped in like any paint (decals and
  // glass follow here; the layers recoloured live get the same numbers again)
  async function confirm() {
    clearTimeout(lab.timer);
    const rev = ++lab.rev, item = lab.item;
    try {
      const r = await api("/api/skins/draft", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(lab.skin) }).then((x) => x.json());
      if (rev !== lab.rev || !lab.on || lab.comparing) return;
      await ctx.changePaint(r.tag, { keepChoice: true });
      // touched again meanwhile: the paint just swapped in is already old, the live colours go back on top
      if (lab.on && lab.item === item && rev !== lab.rev && draftShown()) { retint(ctx.liveMaterials(), effective()); ctx.invalidate(300); }
    } catch (e) {
      if (lab.on) toast(T("labConfirmFail", { error: e.message }), true);
    }
  }

  // ------------------------------------------------------------ panels
  function rowHtml(key, name, title = "") {
    const c = colourOf(key), f = finishOf(key), glass = key === "glass", open = lab.open === key;
    const preset = f.preset || "base", gloss = glossOf(key);
    const paints = !isPart(key) && !glass ? ctx.gameColours() : [];
    const more = !open ? "" : `<div class="lab-row-more">
        ${paints.length ? `<div class="lab-swatches" title="${esc(T("labFromPaints"))}">${paints.map((p) =>
          `<button type="button" class="lab-sw" data-c="${hex(p)}" style="background:${hex(p)}" aria-label="${hex(p)}"></button>`).join("")}</div>` : ""}
        ${glass ? "" : `<div class="lab-fin" role="radiogroup" aria-label="${esc(T("labFinish"))}">${FINISHES.map((p) =>
          `<button type="button" role="radio" aria-checked="${p === preset}" class="${p === preset ? "on" : ""}" data-fin="${p}">${esc(T(FIN_NAMES[p]))}</button>`).join("")}</div>
        ${gloss == null ? "" : `<label class="lab-gloss"><span>${esc(T("labGlossiness"))}</span><input type="range" min="0" max="255" value="${gloss}"></label>`}`}
      </div>`;
    return `<div class="lab-row${open ? " open" : ""}${changed(key) ? " changed" : ""}" data-key="${esc(key)}">
      <div class="lab-row-top">
        <input type="color" class="lab-color" value="${hex(c)}" aria-label="${esc(name)}">
        <button type="button" class="lab-row-name" title="${esc(title || name)}"><span>${esc(name)}</span><em>${glass ? "" : esc(T(FIN_NAMES[preset]))}</em></button>
        <input type="text" class="lab-hex" value="${hex(c)}" maxlength="7" spellcheck="false" aria-label="${esc(T("labHex"))}">
        <button type="button" class="lab-reset" title="${esc(T("labReset"))}" aria-label="${esc(T("labReset"))}"${changed(key) ? "" : " disabled"}>↺</button>
      </div>${more}
    </div>`;
  }
  function renderTools() {
    const b = lab.base;
    $("#labModel").textContent = lab.item.name;
    if (document.activeElement !== $("#labName")) $("#labName").value = lab.skin.name;
    $("#labBase").textContent = lab.skin.base?.label || b.base?.label || T("labStock");
    const slots = [...b.slots, ...(b.glass ? ["glass"] : [])];
    $("#labPaintSec").classList.toggle("hidden", !slots.length);
    fill($("#labRows"), slots.map((k) => rowHtml(k, T(SLOT_NAMES[k]))).join(""));
    const parts = lab.allParts ? b.materials : b.materials.slice(0, PARTS_SHOWN);
    $("#labPartSec").classList.toggle("hidden", !b.materials.length);
    $("#labPartCount").textContent = b.materials.length || "";
    fill($("#labPartRows"), parts.map((m) => rowHtml("m:" + m.id, pretty(m.name), m.name)).join(""));
    const more = $("#labPartMore");
    more.classList.toggle("hidden", b.materials.length <= PARTS_SHOWN);
    more.textContent = lab.allParts ? T("labShowLess") : T("labShowAll", { n: b.materials.length });
    const note = $("#labNote");
    note.textContent = !slots.length && !b.materials.length ? T("labNoParts") : lab.baseGone ? T("labBaseGone") : "";
    note.classList.toggle("hidden", !note.textContent);
    syncButtons();
  }
  function syncButtons() {
    if (!lab.on || !lab.skin) return;
    const d = dirty();
    $("#labSave").disabled = lab.busy || (!d && !!lab.skin.id);
    $("#labCopy").classList.toggle("hidden", !lab.skin.id);
    $("#labExport").disabled = !lab.skin.id || d;
    $("#labDelete").disabled = !lab.skin.id;
    const cmp = $("#labCompare");
    cmp.classList.toggle("on", lab.comparing);
    cmp.textContent = "⇄ " + T(lab.comparing ? "labComparing" : "labCompare");
    $("#labState").textContent = d ? T("labNotSaved") : lab.skin.id ? T("labAllSaved") : "";
  }
  function renderLibrary() {
    fill($("#labMine"), lab.mine.length ? lab.mine.map((s) => `<button type="button" class="lab-skin${s.id === lab.skin?.id ? " on" : ""}" data-id="${esc(s.id)}">
        <span class="paint-sw${s.colors ? "" : " stock"}" style="background:${tile(s.colors)}"></span>
        <span class="lab-skin-name">${esc(s.label)}</span><em>${esc(s.base_label || "")}</em></button>`).join("")
      : `<p class="hint">${esc(T("labMineEmpty"))}</p>`);
    const game = ctx.gameVariants();
    $("#labGameSec").classList.toggle("hidden", !game.length);
    fill($("#labGame"), game.map((v) => `<button type="button" class="paint-sw${v.colors ? "" : " stock"}${v.tag === lab.baseTag && !lab.skin?.id ? " on" : ""}"
      data-tag="${esc(v.tag)}" title="${esc(v.label)}" aria-label="${esc(v.label)}" style="background:${tile(v.colors)}"></button>`).join(""));
    $("#labFolder").textContent = lab.folder ? T("labFolder", { path: lab.folder }) : "";
  }
  async function loadMine() {
    try {
      const r = await api(`/api/skins?path=${encodeURIComponent(lab.item.path)}`).then((x) => x.json());
      lab.mine = r.skins;
      lab.folder = r.folder;
    } catch { lab.mine = []; }
    renderLibrary();
  }

  // ------------------------------------------------------------ opening a skin
  async function loadBase(tag) {
    const q = `path=${encodeURIComponent(lab.item.path)}&full=${ctx.state.full}` + (tag != null ? `&variant=${encodeURIComponent(tag)}` : "");
    lab.base = await api(`/api/skins/base?${q}`).then((x) => x.json());
    lab.baseTag = lab.base.tag;
  }
  async function startNew(tag) {
    await loadBase(tag);
    lab.baseGone = false;
    lab.skin = { name: T("labNewName"), target: { model: lab.item.path, label: lab.item.name }, base: lab.base.base,
      palette: { finish: {} }, materials: {} };
    return opened();
  }
  async function openSkin(id) {
    const r = await api(`/api/skins/${encodeURIComponent(id)}`).then((x) => x.json());
    await loadBase(r.skin.base_tag);
    lab.baseGone = !r.skin.base_found;
    lab.skin = r.data;
    return opened();
  }
  function opened() {
    lab.skin.palette ||= {};
    lab.skin.palette.finish ||= {};
    lab.skin.materials ||= {};
    lab.saved = JSON.stringify(lab.skin);
    lab.comparing = false;
    lab.open = lab.base.slots[0] || (lab.base.materials[0] ? "m:" + lab.base.materials[0].id : null);
    renderTools();
    renderLibrary();
    return confirm();
  }

  // ------------------------------------------------------------ questions, asked in the panel itself
  // resolves with the id of the button pressed, or "keep"
  function ask(text, buttons, no) {
    const box = $("#labAsk");
    fill(box, `<p>${esc(text)}</p><div class="lab-btns">
      ${buttons.map(([id, label, cls]) => `<button type="button" class="${cls}" data-a="${id}">${esc(label)}</button>`).join("")}
      <button type="button" class="ghost" data-a="keep">${esc(no)}</button></div>`);
    box.classList.remove("hidden");
    return new Promise((done) => {
      box.onclick = (e) => {
        const a = e.target.closest("[data-a]")?.dataset.a;
        if (!a) return;
        box.classList.add("hidden");
        box.onclick = null;
        done(a);
      };
    });
  }
  // may the skin on the bench be left? Asks when it has unsaved changes
  async function leaveSkin() {
    if (!dirty()) return true;
    const a = await ask(T("labUnsaved"), [["save", T("save"), "primary"], ["discard", T("labDiscard"), "ghost"]], T("labKeep"));
    if (a === "save") return save();
    return a === "discard";
  }

  // ------------------------------------------------------------ library actions
  async function save(copy = false) {
    if (lab.busy) return false;
    lab.busy = true;
    syncButtons();
    try {
      const body = { ...lab.skin, name: $("#labName").value.trim() || T("labNewName") };
      if (copy) delete body.id;
      const r = await api("/api/skins", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body) }).then((x) => x.json());
      lab.skin = r.data;
      lab.skin.palette ||= {};
      lab.skin.palette.finish ||= {};
      lab.skin.materials ||= {};
      lab.saved = JSON.stringify(lab.skin);
      $("#labName").value = lab.skin.name;
      toast(T("labSaved"));
      await loadMine();
      return true;
    } catch (e) {
      toast(e.message, true);
      return false;
    } finally {
      lab.busy = false;
      syncButtons();
    }
  }
  async function remove() {
    if (!lab.skin.id) return;
    const a = await ask(T("labDeleteAsk", { name: lab.skin.name }), [["yes", T("labDelete"), "danger"]], T("cancel"));
    if (a !== "yes") return;
    try {
      await api(`/api/skins/${encodeURIComponent(lab.skin.id)}`, { method: "DELETE" });
      toast(T("labDeleted"));
      await startNew(lab.baseTag);
      await loadMine();
    } catch (e) { toast(e.message, true); }
  }
  async function exportFile() {
    try {
      const r = await api(`/api/skins/${encodeURIComponent(lab.skin.id)}/export`, { method: "POST" }).then((x) => x.json());
      toast(T("labExported", { path: r.saved }));
    } catch (e) { toast(e.message, true); }
  }
  async function importFile(file) {
    try {
      const r = await api("/api/skins/import", { method: "POST", headers: { "Content-Type": "application/octet-stream" },
        body: await file.arrayBuffer() }).then((x) => x.json());
      const s = r.skin;
      if (s.model.toLowerCase() !== lab.item.path.toLowerCase()) {
        toast(T("labImportedOther", { name: s.label, model: s.model_label }));
        return;
      }
      await loadMine();
      if (!(await leaveSkin())) return;
      toast(T("labImported", { name: s.label }));
      await openSkin(s.id);
    } catch (e) { toast(e.message, true); }
  }

  // ------------------------------------------------------------ in and out
  async function enter(opts = {}) {
    const item = ctx.state.current;
    if (!item || lab.on || lab.entering || ctx.loading()) return;
    if (!ctx.state.tex || !ctx.state.look) { toast(T("labNeedsLook"), true); return; }
    if (ctx.resinOn()) { toast(T("labNeedsNoResin"), true); return; }
    lab.entering = true;
    try {
      lab.item = item;
      lab.prev = { variant: ctx.state.variant, bg: ctx.backdrop.kind };
      lab.allParts = false;
      ctx.closeMenus();
      // paint groups in the model's file, so that paints are swapped in place (a model with one paint has none)
      ctx.state.keyed = true;
      if (!ctx.paintSwap()) await ctx.loadModel(item, true);
      if (ctx.state.current !== item) return;
      lab.on = true;
      root.classList.add("vf-lab");
      ctx.resize();
      ctx.showBackdrop("studio");
      const was = lab.prev.variant;
      const id = opts.fresh ? null : opts.skin || (isSkinTag(was) ? was.slice(5) : null);   // fresh: the "+" tile
      await loadMine();
      if (id && lab.mine.some((s) => s.id === id)) await openSkin(id);
      else await startNew(isSkinTag(was) ? null : was);
    } catch (e) {
      toast(e.message, true);
      if (lab.on) await exit(true);
    } finally {
      lab.entering = false;
    }
  }
  async function exit(force = false) {
    if (!lab.on) return;
    if (!force && !(await leaveSkin())) return;
    clearTimeout(lab.timer);
    lab.rev++;
    lab.on = false;
    root.classList.remove("vf-lab");
    $("#labAsk").classList.add("hidden");
    ctx.resize();
    ctx.showBackdrop(lab.prev.bg);
    // back in the viewer with the skin just made (when it was saved), else with the paint that was on before
    if (ctx.state.current !== lab.item) return;
    const kept = lab.skin?.id ? `skin:${lab.skin.id}` : lab.prev.variant;
    await ctx.refreshPaints(lab.item, kept);
  }

  // ------------------------------------------------------------ events
  function onTools(e) {
    const row = e.target.closest(".lab-row"), key = row?.dataset.key, t = e.target;
    if (!key) return;
    const mark = () => { row.classList.add("changed"); row.querySelector(".lab-reset").disabled = false; };
    if (t.classList.contains("lab-color") && e.type === "input") {
      setColour(key, rgb(t.value));
      row.querySelector(".lab-hex").value = t.value;
      mark();
      touched();
    } else if (t.classList.contains("lab-hex") && e.type === "change") {
      const c = rgb(t.value);
      if (!c) { t.value = hex(colourOf(key)); return; }
      setColour(key, c);
      renderTools();
      touched();
    } else if (t.matches(".lab-gloss input") && e.type === "input") {
      setFinish(key, { gloss: Number(t.value) });
      mark();
      touched();
    } else if (e.type === "click") {
      if (t.closest(".lab-reset")) { reset(key); renderTools(); touched(); }
      else if (t.closest(".lab-sw")) { setColour(key, rgb(t.closest(".lab-sw").dataset.c)); renderTools(); touched(); }
      else if (t.closest("[data-fin]")) {
        const preset = t.closest("[data-fin]").dataset.fin;
        // metal moves the colour to the reflectance: a part still on its own colour takes it as the skin's
        if (preset === "metal" && isPart(key) && !lab.skin.materials?.[key.slice(2)]?.color) setColour(key, part(key).color);
        setFinish(key, { preset, gloss: null });        // a finish brings its own glossiness
        renderTools();
        touched();
      } else if (t.closest(".lab-row-name")) { lab.open = lab.open === key ? null : key; renderTools(); }
    }
  }
  for (const ev of ["input", "change", "click"]) $("#labTools").addEventListener(ev, onTools);
  $("#labName").addEventListener("input", (e) => { lab.skin.name = e.target.value.trim() || T("labNewName"); syncButtons(); });
  $("#labPartMore").addEventListener("click", () => { lab.allParts = !lab.allParts; renderTools(); });
  $("#labCompare").addEventListener("click", async () => {
    lab.comparing = !lab.comparing;
    syncButtons();
    if (lab.comparing) { clearTimeout(lab.timer); lab.rev++; await ctx.changePaint(lab.baseTag, { keepChoice: true }); }
    else await confirm();
  });
  $("#labSave").addEventListener("click", () => save());
  $("#labCopy").addEventListener("click", () => save(true));
  $("#labExit").addEventListener("click", () => exit());
  $("#labDelete").addEventListener("click", remove);
  $("#labExport").addEventListener("click", exportFile);
  $("#labImport").addEventListener("click", () => $("#labFile").click());
  $("#labFile").addEventListener("change", (e) => { const f = e.target.files[0]; e.target.value = ""; if (f) importFile(f); });
  $("#labMine").addEventListener("click", async (e) => {
    const id = e.target.closest("[data-id]")?.dataset.id;
    if (!id || id === lab.skin.id || !(await leaveSkin())) return;
    try { await openSkin(id); } catch (err) { toast(err.message, true); }
  });
  $("#labGame").addEventListener("click", async (e) => {
    const tag = e.target.closest("[data-tag]")?.dataset.tag;
    if (tag == null || !(await leaveSkin())) return;
    try { await startNew(tag); } catch (err) { toast(err.message, true); }
  });

  // the model was loaded again under the lab (Full ship, Interiors): the skin on the bench goes back on
  function reloaded() {
    lab.comparing = false;
    syncButtons();
    return confirm();
  }

  return { enter, exit, confirm, reloaded, effective, get on() { return lab.on; }, get skin() { return lab.skin; }, state: lab };
}
