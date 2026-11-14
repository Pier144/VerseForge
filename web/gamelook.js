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

function texUrl(path, kind) {
  return `/api/texture?path=${encodeURIComponent(path)}&kind=${kind}&size=${TEX_SIZE}`;
}

export class GameLook {
  constructor(renderer) {
    this.loader = new THREE.TextureLoader();
    this.textures = new Map();          // url -> Promise<Texture | null>
    this.maxAniso = renderer.capabilities.getMaxAnisotropy();
  }

  texture(path, kind, repeat = 1) {
    if (!path) return Promise.resolve(null);
    const url = texUrl(path, kind);
    if (!this.textures.has(url)) {
      this.textures.set(url, this.loader.loadAsync(url).then((t) => {
        t.colorSpace = kind === "color" ? THREE.SRGBColorSpace : THREE.NoColorSpace;
        t.wrapS = t.wrapT = THREE.RepeatWrapping;
        t.anisotropy = Math.min(8, this.maxAniso);
        t.flipY = false;                 // glTF UV convention (the GLB's own textures are not flipped either)
        return t;
      }).catch(() => null));
    }
    return this.textures.get(url).then((t) => {
      if (!t || repeat === 1) return t;
      const c = t.clone();               // same image, own UV transform
      c.repeat.set(repeat, repeat);
      c.needsUpdate = true;
      return c;
    });
  }

  dispose() {
    for (const p of this.textures.values()) p.then((t) => t?.dispose());
    this.textures.clear();
  }

  // Replace the materials of `root` that have a shading description. Returns the number of materials changed.
  async apply(root, shading, opts = {}) {
    if (!shading) return 0;
    const jobs = [];
    const made = new Map();              // shading id -> Promise<material>
    root.traverse((o) => {
      if (!o.isMesh || !o.material) return;
      const id = (o.material.name || "").split("|")[2];
      const sh = id && shading[id];
      if (!sh) return;
      const kind = (o.material.name || "").split("|")[0];
      if (kind !== "solid" && kind !== "decal") return;
      if (!made.has(id)) made.set(id, this.build(sh, o.material, kind, opts, o.geometry));
      jobs.push(made.get(id).then((m) => { if (m) { o.material = m; } }));
    });
    await Promise.all(jobs);
    return made.size;
  }

  async build(sh, old, kind, opts, geometry) {
    const us = sh.uv_scale || 1;
    const t = (sh.tiling || 1) / us;   // repeat of the tiled textures on the GLB's UVs
    const [specMap, colorMap, detailN, objN, glossMap, objGloss, hal] = await Promise.all([
      this.texture(sh.spec_map, "color", sh.spec_tiled ? t : 1 / us),
      kind === "solid" ? this.texture(sh.color_map, "color", t) : Promise.resolve(null),
      this.texture(sh.detail_normal, "normal", t),
      this.texture(sh.normal_map, "normal", 1),
      this.texture(sh.gloss_map, "gloss", t),
      this.texture(sh.obj_gloss, "gloss", 1),
      this.texture(sh.hal, "hal", 1),
    ]);
    const st = sh.stencil;
    const stencil = st && kind === "solid" ? await this.texture(sh.stencil_map, "mask", 1) : null;
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
    if (kind === "decal") {
      // decals keep their own colour/alpha texture and only take the game's reflectance and gloss
      m.map = old.map;
      m.color.copy(old.color);
      m.transparent = old.transparent;
      m.alphaTest = old.alphaTest;
      m.depthWrite = old.depthWrite;
      m.polygonOffset = true;
      m.polygonOffsetFactor = -2;
      m.opacity = old.opacity;
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
    const defs = [objGloss && "GAME_OBJ_GLOSS", hal && "GAME_HAL", m.userData.detailNormal && "GAME_DETAIL_NORMAL",
      flip && "GAME_SWAP_XY", stencil && "GAME_STENCIL", stencilUv2 && "GAME_STENCIL_UV2"].filter(Boolean);
    m.onBeforeCompile = (s) => {
      Object.assign(s.uniforms, u);
      for (const d of defs) s.defines[d] = "";
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
  vec3 mapN = gameNormal( texture2D( normalMap, vNormalMapUv ).xyz * 2.0 - 1.0 );
  #ifdef GAME_DETAIL_NORMAL
    vec3 detN = gameNormal( texture2D( gameDetailNormal, vGameUv * gameDetailRepeat * gameUvScale ).xyz * 2.0 - 1.0 );
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
