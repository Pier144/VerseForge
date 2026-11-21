// Game-look materials: the game's spec/gloss shading rebuilt on three.js MeshPhysicalMaterial.
//
// The server describes each textured material (/api/model/info -> shading, keyed by the id stored in the GLB
// material name "kind|name|id"):
//   albedo, spec (F0)   linear colours; the game has no metalness: metals are a black albedo with a coloured F0
//   gloss               smoothness 0..1 (Shininess/255 x GlossMult, or the paint's glossiness)
//   tiling              repeats of the layer textures (color_map, detail_normal, gloss_map)
//   gloss_map           _ddna of the layer: its alpha is the layer's gloss (tiled)
//   obj_gloss           _ddna of the object: its alpha is the object's gloss (plain UVs)
//   normal_map          object normal map (plain UVs); detail_normal is the tiled layer normal
//   hal                 LayerBlend _hal map: G = ambient occlusion, B = brightness (x B*0.4+0.8)
// Roughness = 1 - gloss (CryEngine's GGX alpha is (1-gloss)^2, three.js uses roughness^2).
import * as THREE from "three";

const TEX_SIZE = 1024;
const DECAL_SIZE = 2048;   // decal sheets pack dozens of small labels and grilles: they need the full resolution
// Progressive loading: every texture is first fetched at SMALL_SIZE (a 1/16 of the bytes), the model is shown with
// those, then each one is swapped for the full size as it arrives and the small copy is freed.
const SMALL_SIZE = 256;

function texUrl(path, kind, size = TEX_SIZE) {
  const bust = GameLook.bust ? `&_=${GameLook.bust}` : "";   // benchmarks: bypass the browser's HTTP cache
  return `/api/texture?path=${encodeURIComponent(path)}&kind=${kind}&size=${size}${bust}`;
}

// every texture a game-look material may hold: the standard maps, the extra map kept in userData and the uniforms of
// the patched shader (userData.gameUniforms) or of the decal shader (uniforms)
function swapRefs(m, from, to) {
  for (const k of ["map", "normalMap", "roughnessMap", "specularColorMap"]) if (m[k] === from) m[k] = to;
  if (m.userData.detailNormal === from) m.userData.detailNormal = to;
  for (const u of [m.uniforms, m.userData.gameUniforms]) {
    if (u) for (const v of Object.values(u)) if (v && v.value === from) v.value = to;
  }
}

// Skin Lab: recolour paint layers in place, with the numbers the server would give them (materials.py: the palette
// colour, gamma 2, times the layer's base; the palette's reflectance and glossiness). Only values change, never a
// define or a texture, so nothing is compiled again. `pal`: the skin's effective palette (skins.effective):
// {A, B, C: [r, g, b] | null, spec: {A..}, gloss: {A..}, materials: {name: {color, spec, gloss}}}, sRGB 0-255.
// A layer the palette says nothing about goes back to what the server gave it. Returns how many were set.
const lin2 = (c) => (c / 255) ** 2;
export function retint(materials, pal) {
  let n = 0;
  for (const m of materials) {
    const u = m?.userData?.gameUniforms;
    if (m?.userData?.stencilTinted && u?.gameStencilColors && pal.A && pal.B && pal.C) {
      ["A", "B", "C"].forEach((k, i) => u.gameStencilColors.value[i]?.set(lin2(pal[k][0]), lin2(pal[k][1]), lin2(pal[k][2])));
    }
    const t = m?.userData?.tint;
    if (!t || !u) continue;
    const own = t.slot.startsWith("m:");
    const e = own ? pal.materials?.[t.slot.slice(2)]
      : pal[t.slot] ? { color: pal[t.slot], spec: pal.spec?.[t.slot], gloss: pal.gloss?.[t.slot] } : null;
    const col = e?.color ? e.color.map(lin2) : null;
    if (col) m.color.setRGB(t.base[0] * col[0], t.base[1] * col[1], t.base[2] * col[2]);
    else m.color.setRGB(...t.was.albedo);
    let spec = t.was.spec;
    if (e?.spec) spec = e.spec.map(lin2);
    else if (col && t.spec_base) spec = t.spec_base.map((s, i) => s * col[i]);   // metal layers: the colour tints F0
    m.specularColor.setRGB(spec[0] / 0.04, spec[1] / 0.04, spec[2] / 0.04);
    u.gameGloss.value = e?.gloss != null ? e.gloss / 255 : t.was.gloss;
    n++;
  }
  return n;
}

// Compressed formats this GPU takes as they are: the server then sends the game's own blocks (DDS) instead of a
// decoded JPEG/PNG, and they stay compressed in video memory (4-8x smaller than RGBA8). ?gputex=0 turns it off.
function gpuFormats(renderer) {
  try {
    if (new URLSearchParams(location.search).get("gputex") === "0") return "";
  } catch { /* no location (tests) */ }
  const ext = renderer.extensions;
  if (!renderer.capabilities.isWebGL2) return "";   // partial mip chains need WebGL2 texture storage
  return [
    ext.has("WEBGL_compressed_texture_s3tc") && ext.has("WEBGL_compressed_texture_s3tc_srgb") && "s3tc",
    ext.has("EXT_texture_compression_rgtc") && "rgtc",
    ext.has("EXT_texture_compression_bptc") && "bptc",
  ].filter(Boolean).join(",");
}

// DXGI code of the server's DDS answers -> three.js format (+ how normal maps store X/Y: "rg" 0..1, "srg" -1..1)
const DDS_FORMATS = {
  71: [THREE.RGBA_S3TC_DXT1_Format],          // BC1 (1-bit alpha kept, like the decoded path)
  74: [THREE.RGBA_S3TC_DXT3_Format],          // BC2
  77: [THREE.RGBA_S3TC_DXT5_Format],          // BC3
  80: [THREE.RED_RGTC1_Format],               // BC4 (gloss)
  83: [THREE.RED_GREEN_RGTC2_Format, "rg"],   // BC5 normal map
  84: [THREE.SIGNED_RED_GREEN_RGTC2_Format, "srg"],
  98: [THREE.RGBA_BPTC_Format],               // BC7
};
const BLOCK_BYTES = { 71: 8, 74: 16, 77: 16, 80: 8, 83: 16, 84: 16, 98: 16 };

// GLSL: how a normal map stores X/Y (defines GAME_N_RG / GAME_N_SRG): two-channel BC5 maps get Z rebuilt
function unpackNormalGlsl(macro, define) {
  return `#if defined( ${define}_RG )
  #define ${macro}( t ) gameRebuildZ( ( t ).xy * 2.0 - 1.0 )
#elif defined( ${define}_SRG )
  #define ${macro}( t ) gameRebuildZ( ( t ).xy )
#else
  #define ${macro}( t ) ( ( t ).xyz * 2.0 - 1.0 )
#endif`;
}
const REBUILD_Z_GLSL = "vec3 gameRebuildZ( vec2 xy ) { return vec3( xy, sqrt( clamp( 1.0 - dot( xy, xy ), 0.0, 1.0 ) ) ); }";

function normalDefine(tex, prefix) {
  const enc = tex?.userData?.normalEnc;
  return enc === "rg" ? `${prefix}_RG` : enc === "srg" ? `${prefix}_SRG` : null;
}

function ddsTexture(buf) {
  const v = new DataView(buf);
  const height = v.getUint32(12, true), width = v.getUint32(16, true), levels = Math.max(1, v.getUint32(28, true));
  const dxgi = v.getUint32(128, true);
  const [format, normalEnc] = DDS_FORMATS[dxgi] || [];
  if (format === undefined) throw new Error(`DDS format ${dxgi}`);
  const mipmaps = [];
  let off = 148;
  for (let i = 0; i < levels; i++) {
    const w = Math.max(1, width >> i), h = Math.max(1, height >> i);
    const size = Math.ceil(w / 4) * Math.ceil(h / 4) * BLOCK_BYTES[dxgi];
    if (off + size > buf.byteLength) break;
    mipmaps.push({ data: new Uint8Array(buf, off, size), width: w, height: h });
    off += size;
  }
  const t = new THREE.CompressedTexture(mipmaps, width, height, format);
  if (mipmaps.length === 1) t.minFilter = THREE.LinearFilter;
  t.userData.normalEnc = normalEnc || "rgb";
  t.needsUpdate = true;
  return t;
}

export class GameLook {
  static progressive = true;            // false: load the full sizes straight away (old behaviour, for comparisons)
  static bust = "";                     // set by benchmarks to a fresh value per run

  constructor(renderer) {
    this.renderer = renderer;
    this.swapQueue = [];                // full-size textures waiting to be uploaded and swapped in (see swapIn)
    this.swapTimer = null;
    this.loader = new THREE.TextureLoader();
    this.gpu = gpuFormats(renderer);    // "s3tc,rgtc,bptc" or "" (decoded images only)
    this.textures = new Map();          // url -> Promise<Texture | null>
    this.ready = new Map();             // url -> Texture, once loaded (texture() hands out a full size that is already here)
    this.owned = new Set();             // every texture object made here (clones too), freed by dispose()
    this.maxAniso = renderer.capabilities.getMaxAnisotropy();
    this.requested = 0;                 // textures asked for / finished, for the loading bar
    this.finished = 0;
    this.onProgress = null;             // (finished, requested)
    this.onChange = null;               // a full-size texture replaced a small one: redraw
    this.full = Promise.resolve();      // resolves when every full-size texture is in place
    this.disposed = false;
  }

  // the texture at `size` (as a clone with its own UV repeat when repeat != 1); progressive: a SMALL_SIZE copy,
  // listed in `slots` for upgrade() to replace
  texture(path, kind, repeat = 1, size = TEX_SIZE, slots = null) {
    if (!path) return Promise.resolve(null);
    // a full size already loaded (an earlier paint upgraded it, and upgrade() freed the small copy) is used directly
    const small = GameLook.progressive && slots && size > SMALL_SIZE && !this.ready.has(texUrl(path, kind, size));
    return this.load(path, kind, repeat, small ? SMALL_SIZE : size, true).then((t) => {
      // an image smaller than SMALL_SIZE is already the whole texture
      if (t && small && Math.max(t.image.width, t.image.height) >= SMALL_SIZE) slots.push({ tex: t, path, kind, repeat, size });
      return t;
    });
  }

  load(path, kind, repeat, size, counted) {
    const url = texUrl(path, kind, size);
    if (!this.textures.has(url)) {
      if (counted) {
        this.requested++;
        this.onProgress?.(this.finished, this.requested);
      }
      const tick = () => { if (counted) { this.finished++; this.onProgress?.(this.finished, this.requested); } };
      this.textures.set(url, this.fetchTexture(url).finally(tick).then((t) => {
        t.colorSpace = kind === "color" ? THREE.SRGBColorSpace : THREE.NoColorSpace;
        t.wrapS = t.wrapT = THREE.RepeatWrapping;
        t.anisotropy = Math.min(8, this.maxAniso);
        t.flipY = false;                 // glTF UV convention (the GLB's own textures are not flipped either)
        this.owned.add(t);
        this.ready.set(url, t);
        return t;
      }).catch(() => null));
    }
    return this.textures.get(url).then((t) => {
      if (!t || repeat === 1) return t;
      const c = t.clone();               // same image, own UV transform
      c.repeat.set(repeat, repeat);
      c.needsUpdate = true;
      this.owned.add(c);
      return c;
    });
  }

  // The game's blocks when the server could send them (DDS), else the decoded JPEG/PNG through an <img> as before.
  async fetchTexture(url) {
    if (!this.gpu) return this.loader.loadAsync(url);
    const r = await fetch(`${url}&gpu=${this.gpu}`);
    if (!r.ok) throw new Error(`texture ${r.status}`);
    if ((r.headers.get("Content-Type") || "").includes("dds")) return ddsTexture(await r.arrayBuffer());
    const blobUrl = URL.createObjectURL(await r.blob());
    try {
      return await this.loader.loadAsync(blobUrl);
    } finally {
      URL.revokeObjectURL(blobUrl);
    }
  }

  // swap the small textures listed in `slots` for their full size in `materials`, as each one arrives; the small
  // copies are disposed
  async upgrade(materials, slots) {
    if (!slots.length) return;
    const users = new Map(slots.map((s) => [s.tex, []]));   // small texture -> materials holding it
    for (const m of materials) {
      const refs = [m.map, m.normalMap, m.roughnessMap, m.specularColorMap, m.userData.detailNormal,
        ...[m.uniforms, m.userData.gameUniforms].flatMap((u) => (u ? Object.values(u).map((v) => v?.value) : []))];
      for (const r of new Set(refs)) users.get(r)?.push(m);
    }
    // one full-size request per small texture: the largest size asked for it (a texture used both as a decal at
    // DECAL_SIZE and on a hull at TEX_SIZE shares one small copy)
    const wanted = new Map();
    for (const s of slots) if ((wanted.get(s.tex)?.size || 0) < s.size) wanted.set(s.tex, s);
    await new Promise((r) => setTimeout(r, 0));             // let the first frame (small textures) be drawn first
    await Promise.all([...wanted.values()].map(async (s) => {
      const big = this.disposed ? null : await this.load(s.path, s.kind, s.repeat, s.size, false);
      if (this.disposed || !big) return;                    // model changed meanwhile, or no full size: keep the small one
      await this.swapIn(big, () => {
        for (const m of users.get(s.tex)) swapRefs(m, s.tex, big);
        s.tex.dispose();
        this.owned.delete(s.tex);
      });
    }));
  }

  // Full-size textures arrive in bursts: uploading a dozen of them in the same frame made the view stutter. They are
  // queued and uploaded to the GPU a few at a time (about 6 ms per slice, then a frame to breathe), each swapped in
  // right after its upload.
  swapIn(big, apply) {
    return new Promise((resolve) => {
      this.swapQueue.push({ big, apply, resolve });
      if (!this.swapTimer) this.swapTimer = setTimeout(() => this.drainSwaps(), 0);
    });
  }

  drainSwaps() {
    this.swapTimer = null;
    const t0 = performance.now();
    while (this.swapQueue.length && performance.now() - t0 < 6) {
      const { big, apply, resolve } = this.swapQueue.shift();
      if (!this.disposed) {
        try { this.renderer.initTexture(big); } catch { /* uploaded at the next render instead */ }
        apply();
      }
      resolve();
    }
    if (this.swapQueue.length) this.swapTimer = setTimeout(() => this.drainSwaps(), 16);
    this.onChange?.();
  }

  // POM mesh decals (panel seams, rivets, vents, grilles) have no colour of their own in the game: their texture
  // multiplies the paint under them and their normal/height maps add relief. Drawn as a cheap unlit multiply
  // overlay: framebuffer x mix(1, texture x relief x cavity, coverage).
  async pomDecal(sh, old, opts, slots) {
    const [height, map, normal] = await Promise.all([
      this.texture(sh.height_map, "mask", 1, DECAL_SIZE, slots),
      this.texture(sh.color_map, "color", 1, DECAL_SIZE, slots),
      this.texture(sh.normal_map, "normal", 1, DECAL_SIZE, slots),
    ]);
    const nEnc = normalDefine(normal || old.normalMap, "GAME_N");
    const m = new THREE.ShaderMaterial({
      name: old.name,
      uniforms: {
        map: { value: map || old.map },
        normalMap: { value: normal || old.normalMap },
        heightMap: { value: height },
        strength: { value: sh.opacity ?? 1 },
        alphaCut: { value: Math.max(0.02, Math.min(0.9, sh.alpha_test || 0.5)) },
        lightDir: { value: new THREE.Vector3(0.4, 0.8, 0.45).normalize() },
      },
      defines: { ...(normal || old.normalMap ? { HAS_NORMAL: "" } : {}), ...(height ? { HAS_HEIGHT: "" } : {}),
        ...(nEnc ? { [nEnc]: "" } : {}) },
      clipping: true,      // the "Interiors" section plane cuts decals too
      vertexShader: `#include <clipping_planes_pars_vertex>
#include <batching_pars_vertex>
varying vec2 vUv;
varying vec3 vNormalV;
varying vec3 vViewPos;
void main() {
  vUv = uv;
  vec3 objNormal = normal;
  vec4 objPos = vec4( position, 1.0 );
#ifdef USE_BATCHING
  // drawn in a batch (batching.js): the piece's own transform comes from the batch's texture
  mat4 bm = getBatchingMatrix( batchId );
  mat3 bm3 = mat3( bm );
  objNormal = bm3 * ( objNormal / vec3( dot( bm3[ 0 ], bm3[ 0 ] ), dot( bm3[ 1 ], bm3[ 1 ] ), dot( bm3[ 2 ], bm3[ 2 ] ) ) );
  objPos = bm * objPos;
#endif
  vNormalV = normalize( normalMatrix * objNormal );
  vec4 mvPosition = modelViewMatrix * objPos;
  vViewPos = mvPosition.xyz;
  gl_Position = projectionMatrix * mvPosition;
  #include <clipping_planes_vertex>
}`,
      fragmentShader: `#include <clipping_planes_pars_fragment>
uniform sampler2D map;
uniform sampler2D normalMap;
uniform sampler2D heightMap;
uniform float strength;
uniform float alphaCut;
uniform vec3 lightDir;
varying vec2 vUv;
varying vec3 vNormalV;
varying vec3 vViewPos;
${REBUILD_Z_GLSL}
${unpackNormalGlsl("GAME_UNPACK_N", "GAME_N")}
float shade( vec3 n ) {      // key light + a soft light from the viewer, never fully black
  return 0.35 + 0.45 * max( dot( n, lightDir ), 0.0 ) + 0.3 * max( n.z, 0.0 );
}
void main() {
  #include <clipping_planes_fragment>
  vec4 d = texture2D( map, vUv );
  float cov = smoothstep( alphaCut - 0.08, alphaCut + 0.08, d.a );
  if ( cov <= 0.0 ) discard;
  vec3 N = normalize( vNormalV ) * ( gl_FrontFacing ? 1.0 : -1.0 );
  float relief = 1.0;
#ifdef HAS_NORMAL
  vec3 q0 = dFdx( vViewPos ), q1 = dFdy( vViewPos );
  vec2 st0 = dFdx( vUv ), st1 = dFdy( vUv );
  vec3 q1p = cross( q1, N ), q0p = cross( N, q0 );
  vec3 T = q1p * st0.x + q0p * st1.x;
  vec3 B = q1p * st0.y + q0p * st1.y;
  float det = max( dot( T, T ), dot( B, B ) );
  float sc = det == 0.0 ? 0.0 : inversesqrt( det );
  vec3 tn = GAME_UNPACK_N( texture2D( normalMap, vUv ) );
  vec3 Np = normalize( T * ( tn.x * sc ) + B * ( tn.y * sc ) + N * tn.z );
  relief = clamp( shade( Np ) / max( shade( N ), 1e-3 ), 0.0, 1.0 );
#endif
  float cav = 1.0;
#ifdef HAS_HEIGHT
  cav = mix( 0.62, 1.0, smoothstep( 0.0, 0.85, texture2D( heightMap, vUv ).r ) );
#endif
  vec3 f = clamp( d.rgb * relief * cav, 0.0, 1.0 );
  f = pow( f, vec3( 1.0 / 2.2 ) );            // the framebuffer holds sRGB values
  gl_FragColor = vec4( mix( vec3( 1.0 ), f, cov * strength ), 1.0 );
}`,
      transparent: true,
      depthWrite: false,
      side: THREE.DoubleSide,
      blending: THREE.CustomBlending,
      blendEquation: THREE.AddEquation,
      blendSrc: THREE.ZeroFactor,
      blendDst: THREE.SrcColorFactor,
      polygonOffset: true,
      polygonOffsetFactor: -2,
      toneMapped: false,
      forceSinglePass: true,   // three.js draws transparent double-sided meshes twice otherwise
    });
    m.userData.pom = true;
    m.userData.swatch = old.color ? old.color.clone() : new THREE.Color(0.8, 0.8, 0.8);   // material list swatch
    const sun = opts.sun;
    if (sun) {
      const w = new THREE.Vector3();
      m.userData.beforeRender = (cam) => {
        w.subVectors(sun.position, sun.target.position).normalize();
        m.uniforms.lightDir.value.copy(w).transformDirection(cam.matrixWorldInverse);
      };
    }
    return m;
  }

  dispose() {
    this.disposed = true;
    clearTimeout(this.swapTimer);
    for (const q of this.swapQueue) q.resolve();          // nothing left to swap into
    this.swapQueue.length = 0;
    for (const t of this.owned) t.dispose();
    this.owned.clear();
    // textures still on their way are freed when they land
    for (const p of this.textures.values()) p.then((t) => t?.dispose());
    this.textures.clear();
  }

  // Replace the materials of `root` that have a shading description. Returns the number of materials changed.
  async apply(root, shading, opts = {}) {
    if (!shading) return 0;
    const jobs = [];
    const made = new Map();              // shading id -> Promise<material>
    const slots = [];                    // progressive: the small textures of these materials, for upgrade()
    root.traverse((o) => {
      if (!o.isMesh || !o.material) return;
      const id = (o.material.name || "").split("|")[2];
      const sh = id && shading[id];
      if (!sh) return;
      const kind = (o.material.name || "").split("|")[0];
      if (kind !== "solid" && kind !== "decal") return;
      if (!made.has(id)) made.set(id, this.build(sh, o.material, kind, opts, o.geometry, slots));
      jobs.push(made.get(id).then((m) => {
        if (!m) return;
        o.material = m;
        if (m.userData.beforeRender) o.onBeforeRender = (r, sc, cam) => m.userData.beforeRender(cam);
      }));
    });
    await Promise.all(jobs);
    const mats = await Promise.all(made.values());
    this.full = this.upgrade(mats.filter(Boolean), slots);
    return made.size;
  }

  async build(sh, old, kind, opts, geometry, slots = null) {
    if (kind === "decal" && sh.pom && (sh.color_map || old.map)) return this.pomDecal(sh, old, opts, slots);
    const us = sh.uv_scale || 1;
    const t = (sh.tiling || 1) / us;   // repeat of the tiled textures on the GLB's UVs
    const [specMap, colorMap, detailN, objN, decalMap, glossMap, objGloss, hal] = await Promise.all([
      this.texture(sh.spec_map, "color", sh.spec_tiled ? t : 1 / us, TEX_SIZE, slots),
      kind === "solid" ? this.texture(sh.color_map, "color", t, TEX_SIZE, slots) : Promise.resolve(null),
      this.texture(sh.detail_normal, "normal", t, TEX_SIZE, slots),
      this.texture(sh.normal_map, "normal", 1, kind === "decal" ? DECAL_SIZE : TEX_SIZE, slots),
      kind === "decal" ? this.texture(sh.color_map, "color", 1, DECAL_SIZE, slots) : Promise.resolve(null),
      this.texture(sh.gloss_map, "gloss", t, TEX_SIZE, slots),
      this.texture(sh.obj_gloss, "gloss", 1, TEX_SIZE, slots),
      this.texture(sh.hal, "hal", 1, TEX_SIZE, slots),
    ]);
    const st = sh.stencil;
    const stencil = st && kind === "solid" ? await this.texture(sh.stencil_map, "mask", 1, TEX_SIZE, slots) : null;
    const stencilUv2 = !!(stencil && st.uv2 && geometry?.attributes?._uv2);
    const m = new THREE.MeshPhysicalMaterial({
      name: old.name,
      metalness: 0,
      roughness: 1,
      ior: 1.5,
      specularIntensity: 1,
      side: THREE.DoubleSide,
      envMapIntensity: opts.envIntensity ?? 1,
    });
    m.color.setRGB(...sh.albedo);
    // F0 = 0.04 * specularColor at ior 1.5 (clamped to 1 per channel by three.js)
    m.specularColor.setRGB(...sh.spec.map((c) => c / 0.04));
    // paint layers the Skin Lab recolours in place (retint below): where their colour comes from, and what the
    // server gave them, to go back to
    if (kind === "solid" && sh.tint) m.userData.tint = { ...sh.tint, was: { albedo: sh.albedo, spec: sh.spec, gloss: sh.gloss } };
    if (kind === "solid" && sh.stencil?.tinted) m.userData.stencilTinted = true;
    if (kind === "decal") {
      // decals keep their own colour/alpha texture and only take the game's reflectance and gloss
      m.map = decalMap || old.map;
      m.color.copy(old.color);
      m.transparent = old.transparent;
      m.alphaTest = old.alphaTest;
      m.depthWrite = old.depthWrite;
      m.polygonOffset = true;
      m.polygonOffsetFactor = -2;
      m.forceSinglePass = true;   // transparent + double-sided would cost two draws per decal
      m.opacity = old.opacity;
      const glows = old.emissive && (old.emissive.r || old.emissive.g || old.emissive.b);
      if (!glows && sh.opacity < 1) { m.opacity = sh.opacity; m.transparent = true; m.depthWrite = false; }
    } else if (colorMap) {
      m.map = colorMap;
    } else if (old.map && !sh.color_map) {
      m.map = old.map;
    }
    if (old.emissive && (old.emissive.r || old.emissive.g || old.emissive.b)) {
      m.emissive.copy(old.emissive);
      m.emissiveMap = old.emissiveMap;
    }
    // normals: object map with the tiled layer map blended in (whiteout), or whichever exists
    const flip = opts.swapNormalXY ? 1 : 0;
    if (objN && detailN) { m.normalMap = objN; m.userData.detailNormal = detailN; }
    else m.normalMap = objN || detailN || (kind === "decal" ? old.normalMap : null);
    if (m.normalMap) m.normalScale.set(1, 1);
    if (specMap) m.specularColorMap = specMap;  // F0 per pixel (sRGB texture) x specularColor
    if (glossMap) m.roughnessMap = glossMap;     // read as gloss by the patched shader below
    const u = {
      gameGloss: { value: sh.gloss },
      gameObjGloss: { value: objGloss },
      gameHal: { value: hal },
      gameDetailNormal: { value: m.userData.detailNormal || null },
      gameDetailRepeat: { value: t },
      gameUvScale: { value: us },
      gameStencil: { value: stencil },
      gameStencilTiling: { value: st ? st.tiling : 1 },
      gameStencilOpacity: { value: st ? st.opacity : 0 },
      gameStencilColors: { value: st ? st.colors.map((c) => new THREE.Vector3(...c)) : [] },
    };
    m.userData.gameUniforms = u;         // upgrade() swaps the textures held here too
    const defs = [objGloss && "GAME_OBJ_GLOSS", hal && "GAME_HAL", m.userData.detailNormal && "GAME_DETAIL_NORMAL",
      flip && "GAME_SWAP_XY", stencil && "GAME_STENCIL", stencilUv2 && "GAME_STENCIL_UV2",
      normalDefine(m.normalMap, "GAME_N"), normalDefine(m.userData.detailNormal, "GAME_DN")].filter(Boolean);
    // the defines live on the material from the start: adding them inside onBeforeCompile wrote into
    // material.defines (three.js passes that very object), so the program key changed after the first compile and
    // every material was compiled a second time at the next update (the 1-2 s stall when a big interior appeared)
    m.defines = { ...(m.defines || {}) };
    for (const d of defs) m.defines[d] = "";
    m.onBeforeCompile = (s) => {
      Object.assign(s.uniforms, u);
      s.vertexShader = s.vertexShader
        .replace("#include <uv_pars_vertex>", `#include <uv_pars_vertex>
varying vec2 vGameUv;
uniform float gameUvScale;
#ifdef GAME_STENCIL
varying vec2 vStencilUv;
uniform float gameStencilTiling;
#endif
#ifdef GAME_STENCIL_UV2
attribute vec2 _uv2;
#endif`)
        .replace("#include <uv_vertex>", `#include <uv_vertex>
vGameUv = uv / gameUvScale;
#ifdef GAME_STENCIL_UV2
vStencilUv = _uv2 * gameStencilTiling;
#elif defined( GAME_STENCIL )
vStencilUv = vGameUv * gameStencilTiling;
#endif`);
      s.fragmentShader = s.fragmentShader
        .replace("#include <uv_pars_fragment>", `#include <uv_pars_fragment>
varying vec2 vGameUv;
uniform float gameUvScale;
uniform float gameGloss;
uniform float gameDetailRepeat;
#ifdef GAME_OBJ_GLOSS
uniform sampler2D gameObjGloss;
#endif
#ifdef GAME_HAL
uniform sampler2D gameHal;
#endif
#ifdef GAME_DETAIL_NORMAL
uniform sampler2D gameDetailNormal;
#endif
#ifdef GAME_STENCIL
varying vec2 vStencilUv;
uniform sampler2D gameStencil;
uniform float gameStencilOpacity;
uniform vec3 gameStencilColors[ 3 ];
#endif
${REBUILD_Z_GLSL}
${unpackNormalGlsl("GAME_UNPACK_N", "GAME_N")}
${unpackNormalGlsl("GAME_UNPACK_DN", "GAME_DN")}
vec3 gameNormal(vec3 n) {
#ifdef GAME_SWAP_XY
  return vec3(n.y, n.x, n.z);
#else
  return n;
#endif
}`)
        .replace("#include <roughnessmap_fragment>", `float gameG = gameGloss;
#ifdef USE_ROUGHNESSMAP
  gameG *= texture2D( roughnessMap, vRoughnessMapUv ).r;
#endif
#ifdef GAME_OBJ_GLOSS
  gameG *= texture2D( gameObjGloss, vGameUv ).r;
#endif
float roughnessFactor = clamp( 1.0 - gameG, 0.0, 1.0 );`)
        .replace("#include <map_fragment>", `#include <map_fragment>
#ifdef GAME_STENCIL
  {
    // the masks are crisp shapes with soft edges: cut them at 0.5 (antialiased) like the game's hard-edged camo
    vec3 stRaw = texture2D( gameStencil, vStencilUv ).rgb;
    vec3 stW = max( fwidth( stRaw ), vec3( 0.02 ) );
    vec3 stM = smoothstep( 0.5 - stW, 0.5 + stW, stRaw ) * gameStencilOpacity;
  #ifdef USE_MAP
    vec3 stDetail = sampledDiffuseColor.rgb;   // keep the paint texture's breakup under the camo colours
  #else
    vec3 stDetail = vec3( 1.0 );
  #endif
    diffuseColor.rgb = mix( diffuseColor.rgb, gameStencilColors[ 0 ] * stDetail, stM.r );
    diffuseColor.rgb = mix( diffuseColor.rgb, gameStencilColors[ 1 ] * stDetail, stM.g );
    diffuseColor.rgb = mix( diffuseColor.rgb, gameStencilColors[ 2 ] * stDetail, stM.b );
  }
#endif
#ifdef GAME_HAL
  vec3 gameHalS = texture2D( gameHal, vGameUv ).rgb;
  diffuseColor.rgb *= gameHalS.b * 0.4 + 0.8;
#endif`)
        .replace("#include <normal_fragment_maps>", `#ifdef USE_NORMALMAP_TANGENTSPACE
  vec3 mapN = gameNormal( GAME_UNPACK_N( texture2D( normalMap, vNormalMapUv ) ) );
  #ifdef GAME_DETAIL_NORMAL
    vec3 detN = gameNormal( GAME_UNPACK_DN( texture2D( gameDetailNormal, vGameUv * gameDetailRepeat * gameUvScale ) ) );
    mapN = vec3( mapN.xy + detN.xy, mapN.z * detN.z );
  #endif
  mapN.xy *= normalScale;
  normal = normalize( tbn * mapN );
#endif`)
        .replace("#include <aomap_fragment>", `#include <aomap_fragment>
#ifdef GAME_HAL
  reflectedLight.indirectDiffuse *= gameHalS.g;
  reflectedLight.indirectSpecular *= mix( 1.0, gameHalS.g, 0.7 );
#endif`);
    };
    m.customProgramCacheKey = () => "game:" + defs.join(",");
    return m;
  }
}
