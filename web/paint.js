// Instant paint switching (docs/superpowers/specs/2026-11-18-vernici-istantanee-design.md).
// The server gives every paint of a model the same geometry, its parts grouped by paint group: the "g<n>" field of
// the GLB material names (sc_explorer/paints.py). A paint is then a table of one material per group.
import * as THREE from "three";
import { layout } from "./batching.js";

// The paint group written in a keyed GLB material name, or null. The group sits at a fixed place: PBR names are
// "kind|name|sid|g12" (4 fields, plain ones have 3), screens are "screen|name|g3|rtt", "screen|name|g3|holo" or
// "screen|name|g3" (plain ones: "screen|name|rtt", "screen|name"). Only that exact field counts, so a material
// that is merely NAMED "g2" is never read as a group.
export function groupOf(material) {
  const parts = (material?.name || "").split("|");
  const field = parts[0] === "screen" ? parts[2] : parts.length === 4 ? parts[3] : null;
  return field && /^g\d+$/.test(field) ? Number(field.slice(1)) : null;
}

const KEEP = 3;                                   // paints kept built: the three most recent (stock stays recent while comparing)
const NO_HOOK = THREE.Object3D.prototype.onBeforeRender;
const kindOf = (name) => name.split("|")[0] || "solid";
const meshKind = (o) => kindOf(o.name || o.parent?.name || "");

// the material GLTFLoader makes from a glTF material of the viewer's lite GLB: what the game look expects as `old`.
// The lite GLB has no normals or tangents, so GLTFLoader makes its materials flat shaded and flips the normal map's
// green channel (GLTFLoader.js assignFinalMaterial); its textures repeat.
function standIn(e, map, normal) {
  const m = new THREE.MeshStandardMaterial({ name: e.name, metalness: e.metallic, roughness: e.roughness, flatShading: true });
  m.color.setRGB(e.color[0], e.color[1], e.color[2]);          // glTF factors are linear, like Color.setRGB
  m.opacity = e.alpha;
  if (e.emissive) m.emissive.setRGB(e.emissive[0], e.emissive[1], e.emissive[2]);
  if (e.alpha_mode === "BLEND") { m.transparent = true; m.depthWrite = false; }
  else if (e.alpha_mode === "MASK") m.alphaTest = e.alpha_cutoff ?? 0.5;
  if (map) m.map = map;
  if (normal) { m.normalMap = normal; m.normalScale.set(1, -1); }
  return m;
}

// three vertices of `g` with every attribute it has (but the batch's own batchId, which BatchedMesh refuses in a
// geometry it is given): compiles a shader's BatchedMesh variant cheaply
function tinyLike(g) {
  const t = new THREE.BufferGeometry();
  for (const [n, a] of Object.entries(g.attributes)) {
    if (n === "batchId") continue;
    t.setAttribute(n, new THREE.BufferAttribute(a.array.slice(0, 3 * a.itemSize), a.itemSize, a.normalized));
  }
  t.setIndex([0, 1, 2]);
  return t;
}

// Builds a paint's materials the way the loader and the game look would, compiles them off screen, then swaps them in
// on one frame. Glass keeps its material: only the colour of its tint layer changes (app.js glassLook). Screens are
// left to app.js (afterPaint), which rebuilds the screen classes that draw on them.
export class PaintSwap {
  // gameLook: the model's GameLook (textures shared with the paint loaded first); batches: its Batches; root: the
  // model; compile(root, section): app.js compileShaders; section: the model has an interior; look: GameLook.build
  // options; query: "path=..&full=..&interior=.." of the model; glassTint([r,g,b]) -> THREE.Color; tag: paint on screen
  constructor({ gameLook, batches, root, compile, section, look, query, glassTint, tag }) {
    Object.assign(this, { gameLook, batches, root, compile, section, look, query, glassTint });
    this.meshes = new Map();                      // group -> meshes in the scene (batched pieces are in `batches`)
    root.traverse((o) => {
      const g = o.userData.group;
      if (!o.isMesh || o.isBatchedMesh || g == null) return;
      if (!this.meshes.has(g)) this.meshes.set(g, []);
      this.meshes.get(g).push(o);
    });
    this.paints = new Map();                      // tag -> { mats: Map(group -> material), tints, textures }, oldest first
    this.current = tag;
    this.seq = 0;
    this.disposed = false;
    this.paints.set(tag, this.snapshot());        // the paint on screen: going back to it costs nothing
  }

  // the materials on screen now, by group (the game material while the resin look is on): only the groups a paint
  // rebuilds (solids and decals); glass keeps its material and only its tint is recorded, screens belong to the
  // screen classes (app.js), proxies never change
  snapshot() {
    const mats = new Map(), tints = new Map();
    const take = (g, o) => { if (!mats.has(g)) mats.set(g, o.userData.gameMaterial || o.material); };
    for (const [g, list] of this.meshes) {
      const kind = meshKind(list[0]);
      if (kind === "solid" || kind === "decal") take(g, list[0]);
      const layer = list[0].children.find((c) => c.userData.glass);
      if (layer) tints.set(g, (layer.userData.gameMaterial || layer.material).color.clone());
    }
    for (const b of this.batches.list) if (b.userData.group != null) take(b.userData.group, b);   // solids only
    return { mats, tints, textures: [], paint: null };
  }

  // the /api/model/paint answer of a kept paint (null for the paint loaded first): no request needed to show it again
  answer(tag) {
    return this.paints.get(tag)?.paint || null;
  }

  // Show paint `tag` (`paint`: the /api/model/paint answer). False when a newer request took over meanwhile.
  async apply(tag, paint) {
    const seq = ++this.seq;
    this.stamp = paint.stamp;                     // in the texture URLs: see PaintSwap.image
    let built = this.paints.get(tag);
    if (!built) {
      built = await this.build(tag, paint, () => seq !== this.seq || this.disposed);
      if (seq !== this.seq || this.disposed) { this.free(built); return false; }
    }
    built.paint = paint;
    this.assign(built);
    this.current = tag;
    this.paints.delete(tag);
    this.paints.set(tag, built);                  // most recent last
    this.evict();
    return true;
  }

  async build(tag, paint, stale) {
    const mats = new Map(), tints = new Map(), textures = [], slots = [], made = new Map(), jobs = [];
    try {
      paint.groups.forEach((e, g) => {
        if (!e) return;
        const kind = kindOf(e.name);
        if (kind === "screen") return;            // app.js afterPaint: the screen classes own those materials
        const sample = this.meshes.get(g)?.[0] || this.batches.byGroup(g)[0];
        if (!sample) return;                      // not drawn in this GLB (proxies, interior-only groups)
        if (kind === "glass") { tints.set(g, this.glassTint(e.color)); return; }
        // groups that look the same share one material (as the game look shares them on load); a group with its own
        // images keeps its own
        const key = JSON.stringify({ ...e, name: e.name.replace(/\|g\d+/, "") }) + (e.texture || e.normal_texture ? `#${g}` : "");
        if (!made.has(key)) made.set(key, this.material(tag, g, e, kind, paint, sample.geometry, slots, textures, stale));
        jobs.push(made.get(key).then((m) => mats.set(g, m)));
      });
      await Promise.all(jobs);
      if (stale()) return { mats, tints, textures, paint };   // a newer request took over: the caller frees it
      await this.precompile(mats);
      // full sizes follow, as on load (not for a build a newer request already replaced: it is thrown away)
      if (!stale()) this.gameLook.full = this.gameLook.upgrade([...new Set(mats.values())], slots);
      return { mats, tints, textures, paint };
    } catch (err) {
      // free what was made so far (nothing of it is on screen), then let the caller see the failure
      const done = await Promise.allSettled([...made.values()]);
      this.free({ mats: new Map(done.filter((r) => r.status === "fulfilled").map((r, i) => [i, r.value])), textures });
      throw err;
    }
  }

  async material(tag, g, e, kind, paint, geometry, slots, textures, stale) {
    const [map, normal] = await Promise.all([
      e.texture ? this.image(tag, g, "base", textures) : null,
      e.normal_texture ? this.image(tag, g, "normal", textures) : null]);
    const old = standIn(e, map, normal);
    const sid = e.name.split("|")[2];
    const sh = sid && paint.shading?.[sid];
    let m = old;
    if (sh && (kind === "solid" || kind === "decal") && !stale()) {
      const made = await this.gameLook.build(sh, old, kind, this.look, geometry, slots);
      if (made) { m = made; if (made !== old) old.dispose(); }
    }
    m.side = THREE.DoubleSide;                    // as loadModel sets every material
    if (!m.isMeshPhysicalMaterial) m.envMapIntensity = 0.6;
    m.visible = e.visible !== false;              // livery stickers this paint does not have
    return m;
  }

  async image(tag, g, map, textures) {
    const url = `/api/model/paint/texture?${this.query}&variant=${encodeURIComponent(tag)}&group=${g}&map=${map}&v=${encodeURIComponent(this.stamp || "")}`;
    try {
      const t = await new THREE.TextureLoader().loadAsync(url);
      t.flipY = false;                            // glTF images, like the GLB's
      t.wrapS = t.wrapT = THREE.RepeatWrapping;   // GLTFLoader's default without a sampler
      if (map === "base") t.colorSpace = THREE.SRGBColorSpace;
      try { this.gameLook.renderer.initTexture(t); } catch { /* uploaded at the first frame instead */ }
      textures.push(t);
      return t;
    } catch {
      return null;                                // no image for this group: drawn without it, as the GLB would
    }
  }

  // Compile the new shaders before they are used, and upload their textures, so the swap frame does not stall. A
  // shader is compiled per material and geometry attribute layout, so one stand-in is made for each distinct pair: a
  // Mesh for the pieces drawn alone, a tiny BatchedMesh for the batches (whose shaders differ).
  async precompile(mats) {
    const stage = new THREE.Group(), seen = new Set(), sizes = new Map();
    const lay = (g) => { if (!sizes.has(g)) sizes.set(g, layout(g)); return sizes.get(g); };
    try {
      for (const [g, m] of mats) {
        for (const o of this.meshes.get(g) || []) {
          const key = `${m.uuid}|${lay(o.geometry)}`;
          if (!seen.has(key)) { seen.add(key); stage.add(new THREE.Mesh(o.geometry, m)); }
        }
        for (const b of this.batches.byGroup(g)) {
          const tiny = tinyLike(b.geometry);          // without the batch's own batchId, so its layout is the loose one
          const key = `${m.uuid}|batch|${layout(tiny)}`;
          if (seen.has(key)) { tiny.dispose(); continue; }
          seen.add(key);
          const mesh = new THREE.BatchedMesh(1, 3, 3, m);
          mesh.addGeometry(tiny);
          stage.add(mesh);
        }
      }
      await this.compile(stage, this.section);
    } catch { /* compiled at the first frame instead */ }
    stage.traverse((o) => { if (o.isBatchedMesh) o.dispose(); });
    try {
      // every texture the materials use (the same places GameLook.upgrade looks at)
      const used = new Set();
      for (const m of new Set(mats.values())) {
        const refs = [m.map, m.normalMap, m.roughnessMap, m.specularColorMap, m.userData.detailNormal,
          ...[m.uniforms, m.userData.gameUniforms].flatMap((u) => (u ? Object.values(u).map((v) => v?.value) : []))];
        for (const t of refs) if (t?.isTexture) used.add(t);
      }
      for (const t of used) this.gameLook.renderer.initTexture(t);
    } catch { /* uploaded at the first frame instead */ }
  }

  // castShadow, receiveShadow and the batches (opaque only) were set up for the paint loaded first: the server's
  // swap check (paints._look) only lets through paints that draw every group with the same transparency
  assign(built) {
    const put = (o, m) => { if (o.userData.gameMaterial) o.userData.gameMaterial = m; else o.material = m; };
    for (const [g, m] of built.mats) {
      const hook = m.userData.beforeRender;       // POM decals: light direction per frame
      for (const o of this.meshes.get(g) || []) {
        put(o, m);
        o.onBeforeRender = hook ? (r, sc, cam) => hook(cam) : NO_HOOK;
      }
      for (const b of this.batches.byGroup(g)) { put(b, m); b.hook = hook || null; }
    }
    for (const [g, t] of built.tints) {
      for (const o of this.meshes.get(g) || []) {
        const layer = o.children.find((c) => c.userData.glass);
        if (layer) (layer.userData.gameMaterial || layer.material).color.copy(t);
        (o.userData.gameMaterial || o.material).userData.swatch = t;   // material list colour
      }
    }
  }

  evict() {
    while (this.paints.size > KEEP) {
      const [tag, built] = this.paints.entries().next().value;
      if (tag === this.current) break;
      this.paints.delete(tag);
      this.free(built);
    }
  }

  // the materials on screen (game materials while the resin look is on)
  live() {
    const out = new Set();
    for (const list of this.meshes.values()) for (const o of list) out.add(o.userData.gameMaterial || o.material);
    for (const b of this.batches.list) out.add(b.userData.gameMaterial || b.material);
    return out;
  }

  // free a paint that is not on screen; a material still shown (one kept by groups this paint did not rebuild) stays
  free(built) {
    const live = this.live();
    for (const m of new Set(built.mats.values())) if (!live.has(m)) m.dispose();
    for (const t of built.textures) t.dispose();
  }

  // the model is going away: cancel a swap in progress, free the kept paints that are not on screen and the textures
  // of the one on screen (loadModel frees its materials with the model)
  dispose() {
    this.disposed = true;
    this.seq++;
    for (const [tag, built] of this.paints) {
      if (tag !== this.current) this.free(built);
      else for (const t of built.textures) t.dispose();   // (re-uploaded if drawn again, so safe if a reload is cancelled)
    }
    this.paints.clear();
  }
}
