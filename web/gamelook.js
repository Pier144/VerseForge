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

function texUrl(path, kind, size = TEX_SIZE) {
  return `/api/texture?path=${encodeURIComponent(path)}&kind=${kind}&size=${size}`;
}

export class GameLook {
  constructor(renderer) {
    this.loader = new THREE.TextureLoader();
    this.textures = new Map();          // url -> Promise<Texture | null>
    this.maxAniso = renderer.capabilities.getMaxAnisotropy();
  }

  texture(path, kind, repeat = 1, size = TEX_SIZE) {
    if (!path) return Promise.resolve(null);
    const url = texUrl(path, kind, size);
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

  // POM mesh decals (panel seams, rivets, vents, grilles) have no colour of their own in the game: their texture
  // multiplies the paint under them and their normal/height maps add relief. Drawn as a cheap unlit multiply
  // overlay: framebuffer x mix(1, texture x relief x cavity, coverage).
  async pomDecal(sh, old, opts) {
    const [height, map, normal] = await Promise.all([
      this.texture(sh.height_map, "mask", 1, DECAL_SIZE),
      this.texture(sh.color_map, "color", 1, DECAL_SIZE),
      this.texture(sh.normal_map, "normal", 1, DECAL_SIZE),
    ]);
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
      defines: { ...(normal || old.normalMap ? { HAS_NORMAL: "" } : {}), ...(height ? { HAS_HEIGHT: "" } : {}) },
      vertexShader: `varying vec2 vUv;
varying vec3 vNormalV;
varying vec3 vViewPos;
void main() {
  vUv = uv;
  vNormalV = normalize( normalMatrix * normal );
  vec4 mv = modelViewMatrix * vec4( position, 1.0 );
  vViewPos = mv.xyz;
  gl_Position = projectionMatrix * mv;
}`,
      fragmentShader: `uniform sampler2D map;
uniform sampler2D normalMap;
uniform sampler2D heightMap;
uniform float strength;
uniform float alphaCut;
uniform vec3 lightDir;
varying vec2 vUv;
varying vec3 vNormalV;
varying vec3 vViewPos;
float shade( vec3 n ) {      // key light + a soft light from the viewer, never fully black
  return 0.35 + 0.45 * max( dot( n, lightDir ), 0.0 ) + 0.3 * max( n.z, 0.0 );
}
void main() {
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
  vec3 tn = texture2D( normalMap, vUv ).xyz * 2.0 - 1.0;
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
      jobs.push(made.get(id).then((m) => {
        if (!m) return;
        o.material = m;
        if (m.userData.beforeRender) o.onBeforeRender = (r, sc, cam) => m.userData.beforeRender(cam);
      }));
    });
    await Promise.all(jobs);
    return made.size;
  }

  async build(sh, old, kind, opts, geometry) {
    if (kind === "decal" && sh.pom && old.map) return this.pomDecal(sh, old, opts);
    const us = sh.uv_scale || 1;
    const t = (sh.tiling || 1) / us;   // repeat of the tiled textures on the GLB's UVs
    const [specMap, colorMap, detailN, objN, decalMap, glossMap, objGloss, hal] = await Promise.all([
      this.texture(sh.spec_map, "color", sh.spec_tiled ? t : 1 / us),
      kind === "solid" ? this.texture(sh.color_map, "color", t) : Promise.resolve(null),
      this.texture(sh.detail_normal, "normal", t),
      this.texture(sh.normal_map, "normal", 1, kind === "decal" ? DECAL_SIZE : TEX_SIZE),
      kind === "decal" ? this.texture(sh.color_map, "color", 1, DECAL_SIZE) : Promise.resolve(null),
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
