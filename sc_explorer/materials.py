"""Material (.mtl) loading: sub-material names, a display colour, textures and a visibility class."""
import re
from dataclasses import dataclass

from . import cryxml


@dataclass
class Material:
    name: str
    shader: str
    kind: str          # "solid", "decal", "glass", "hidden", "screen"
    color: tuple       # linear RGB 0..1
    diffuse: str | None = None     # colour texture (source path as written in the .mtl)
    normal: str | None = None      # tangent-space normal map (_ddn / _ddna)
    tiling: float = 1.0            # UV repeat of the diffuse texture (layer materials)
    layer_normal: bool = False     # normal map comes from the tiled layer, not the object
    alpha_test: float = 0.0
    metal: bool = False
    stencil_colors: tuple | None = None   # stencil decal: diffuse is the palette's R/G/B mask, coloured with these
    emissive: tuple | None = None         # linear RGB of self-lit parts (Illum with Glow)
    # game shading (CryEngine spec/gloss model), used by the viewer's game-look materials
    spec: tuple = (0.04, 0.04, 0.04)      # reflectance at normal incidence (F0), linear RGB
    gloss: float = 0.5                    # smoothness 0..1 (Shininess / 255 x layer GlossMult or paint glossiness)
    gloss_map: str | None = None          # _ddna whose alpha is the gloss of the tiled layer (repeats `tiling` times)
    obj_gloss: str | None = None          # _ddna whose alpha is the gloss of the object itself (plain UVs)
    hal: str | None = None                # LayerBlend _hal map: G = ambient occlusion, B = brightness
    shader_name: str = ""
    spec_map: str | None = None           # _spec texture: reflectance colour per pixel (x spec)
    spec_tiled: bool = False              # spec_map belongs to the tiled layer
    opacity: float = 1.0                  # decal strength (Opacity x DecalDiffuseOpacity): dirt 0.08, text 0.3
    pom: bool = False                     # POM mesh decal: shades the paint under it (multiplier + relief), no colour
    height_map: str | None = None         # POM decal height (_displ): cavities darken
    stencil_map: str | None = None        # camo/livery mask on hull paints (HardSurface %STENCIL_MAP): R/G/B layers
    stencil: dict | None = None           # {tiling, uv2, opacity, colors: 3 linear RGB} for stencil_map
    detail_normal: str | None = None      # normal map of the tiled layer (repeats `tiling` times)
    albedo: tuple | None = None           # diffuse colour of the game shading (None = `color`); black for metals
    holo: bool = False                    # screen kind: a holographic HUD projection (see-through), not a panel


SCREEN_RGB = (110, 205, 235)       # default screen light (sRGB): the cold cyan of the game's holo UI


def palette_linear(rgb8):
    """Palette colours (tint and spec) are linearised by the game with gamma 2, not the sRGB curve."""
    return tuple((x / 255.0) ** 2 for x in rgb8)


def srgb_to_linear(rgb8):
    c = [x / 255.0 for x in rgb8]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


def _floats(text, default):
    try:
        v = tuple(float(x) for x in text.split(","))
        return v[:3] if len(v) >= 3 else default
    except (AttributeError, ValueError):
        return default


# the damage layer of ship hulls: girders, cables and plating that the game shows only where the hull is shot
# through (a damage map cuts holes in the hull). It lies just under the skin: drawn with an intact hull it showed
# through from a distance (Anvil Hawk). Real interior framework (internal_framework, girders, trims) stays.
DAMAGE_LAYER = re.compile(r"^(ext_)?(damage_)?internals?_(pom|tile|structure|mesh)(_alpha|_core)?$"
                          r"|^(ext_)?damage_(structure|poms?)(_alpha)?$")


def classify(name, shader):
    n, s = name.lower(), shader.lower()
    if s == "nodraw" or "proxy" in n or "nodraw" in n or "physics" in n or DAMAGE_LAYER.match(n):
        return "hidden"
    # DisplayScreen / UIPlane: dashboard screens and the holographic HUD, whose picture the game's UI draws live
    # ($RenderToTexture). Shown switched on, without content; the viewer's "Screens" switch hides them
    if s in ("displayscreen", "uiplane"):
        return "screen"
    if s in ("meshdecal", "decal") or any(k in n for k in ("decal", "pom", "stencil", "glow", "emissive")):
        return "decal"
    if s.startswith("glass") or "glass" in n or "canopy" in n or "visor" in n:
        return "glass"
    return "solid"


def _is_normal(path):
    stem = path.lower().rsplit(".", 1)[0]
    return stem.endswith(("_ddn", "_ddna")) or "_ddna_" in stem or "_ddn_" in stem


def _texture_slots(el, normal_slots=("TexSlot2", "TexSlot3")):
    """(diffuse, normal) from a <Textures> block. Slot numbers differ per shader, so file suffixes win."""
    diffuse = normal = None
    for t in el.findall("Textures/Texture"):
        f, slot = t.get("File") or "", t.get("Map")
        if not f or f.lower().startswith("$"):
            continue
        if _is_normal(f):
            if normal is None and slot in normal_slots:
                normal = f
        elif slot == "TexSlot1" and diffuse is None:
            diffuse = f
    return diffuse, normal


def _slot(el, name):
    for t in el.findall("Textures/Texture"):
        f = t.get("File") or ""
        if t.get("Map") == name and f and not f.startswith("$"):
            return f
    return None


def _spec_map(el):
    """The _spec texture of a material, whatever slot the shader keeps it in (Illum 4, MeshDecal 2, Layer 6)."""
    for t in el.findall("Textures/Texture"):
        f = t.get("File") or ""
        stem = f.lower().rsplit(".", 1)[0]
        if not f.startswith("$") and (stem.endswith("_spec") or "_spec_" in stem):
            return f
    return None


def _shininess(el, default=255.0):
    try:
        return max(0.0, min(1.0, float(el.get("Shininess", default)) / 255.0))
    except ValueError:
        return default / 255.0


def _layer(archive, path):
    """A tileable layer material (materials/layers/…): {color, diffuse, normal, metal, spec, gloss, tint_mode}."""
    if not archive or not path:
        return None
    p = path.replace("\\", "/")
    p = p if p.lower().endswith(".mtl") else p + ".mtl"
    if not archive.exists(p):
        return None
    try:
        root = cryxml.parse(archive.read(p))
    except Exception:
        return None
    diffuse, normal = _texture_slots(root)
    diff = _floats(root.get("Diffuse"), (1.0, 1.0, 1.0))
    spec = _floats(root.get("Specular"), (0.04, 0.04, 0.04))
    color = diff
    metal = max(diff) < 0.02
    if metal:  # PBR metals: no diffuse, the specular colour is the metal's colour
        color = _floats(root.get("Specular"), (0.6, 0.6, 0.6))
    pp = root.find("PublicParams")
    try:
        tint_mode = int(pp.get("TintMode", "0")) if pp is not None else 0
    except ValueError:
        tint_mode = 0
    return {"color": color, "diffuse": diffuse, "normal": normal, "metal": metal, "diff": diff, "spec": spec,
            "gloss": _shininess(root), "tint_mode": tint_mode, "spec_map": _spec_map(root)}


def _material(el, archive=None, palette=None):
    name = el.get("Name", "")
    shader = el.get("Shader", "")
    color = _floats(el.get("Diffuse"), (0.6, 0.6, 0.6))
    diffuse, normal = _texture_slots(el)
    mat = Material(name, shader, classify(name, shader), color, diffuse, normal)
    mat.shader_name = shader
    mat.spec = _floats(el.get("Specular"), (0.04, 0.04, 0.04))
    mat.gloss = _shininess(el)
    mat.spec_map = _spec_map(el)
    if normal and "_ddna" in normal.lower():
        mat.obj_gloss = normal
    if shader.lower().startswith("layerblend"):
        mat.hal = _slot(el, "TexSlot13")
    try:
        mat.alpha_test = float(el.get("AlphaTest", "0"))
    except ValueError:
        pass
    # MeshDecal + STENCIL_MAP: a palette stencil sticker. HardSurface + STENCIL_MAP is a camo paint on the hull (the
    # stencil only patterns the paint) and must stay a solid surface, or whole hull panels vanish
    if "%STENCIL_MAP" in (el.get("StringGenMask") or "") and shader.lower() in ("meshdecal", "decal"):
        # texture "$TintPaletteDecal": the paint's stencil atlas. Without a paint there is nothing to draw (the
        # decal's own colour is black and used to show as a black slab)
        if palette and palette.get("decal"):
            mat.diffuse = palette["decal"]
            mat.stencil_colors = tuple(tuple(c) if c else (230, 230, 230) for c in palette.get("decal_colors") or [None] * 3)
            mat.kind = "decal"
        else:
            mat.kind = "hidden"
    gen = el.get("StringGenMask") or ""
    # decal shaders with no picture of their own: placeholders filled by liveries, ship names drawn live
    # ($RenderToTexture). Drawn as they are they were plain white slabs over the hull (Cutlass Black)
    if mat.kind == "decal" and shader.lower() in ("meshdecal", "decal") and not mat.diffuse and not mat.normal \
            and not mat.stencil_colors:
        mat.kind = "hidden"
    if mat.kind == "decal":
        pp = el.find("PublicParams")
        mat.opacity = max(0.0, min(1.0, _pp_float(el, "Opacity", 1.0) * _pp_float(pp, "DecalDiffuseOpacity", 1.0)))
        # POM decals: MeshDecal, and Illum meshes flagged %DECAL (Aopoa/Xi'an ships). Their texture is a near-white
        # multiplier (seams, outlines): drawn as plain colour it showed as white or black slabs on the hull
        s = shader.lower()
        # (Illum decals with a real colour of their own - buttons, stitches - keep it: only the "pom" atlases)
        illum_pom = s.startswith("illum") and "%DECAL" in gen and (
            "pom" in name.lower() or "pom" in (mat.diffuse or "").lower().rsplit("/", 1)[-1])
        if "%PARALLAX_OCCLUSION_MAPPING" in gen and not mat.stencil_colors and (s == "meshdecal" or illum_pom):
            mat.pom = True
            # MeshDecal keeps the height in TexSlot4; Illum keeps its _spec there
            mat.height_map = _slot(el, "TexSlot4") if s == "meshdecal" else None
    if "%STENCIL_MAP" in gen and mat.kind == "solid":
        _hull_stencil(mat, el, palette)
    if mat.kind == "screen":
        # UIPlane HUDs (RTT_HUD, UI_HUD_RTT) are projections in the air in front of the pilot: a faint see-through veil
        mat.holo = shader.lower() == "uiplane" and "hud" in name.lower()
        accent = (palette or {}).get("decal_colors") or [None]
        # the paint's first stencil colour when it is a real colour (VOLT green); greys and whites -> holo cyan
        rgb = accent[0] if accent[0] and max(accent[0]) >= 100 and max(accent[0]) - min(accent[0]) >= 60 else SCREEN_RGB
        mat.emissive = srgb_to_linear(rgb)
        mat.color = (0.01, 0.012, 0.015)
    try:
        glow = float(el.get("Glow", "0") or 0)
    except ValueError:
        glow = 0.0
    if glow > 0 and shader.lower().startswith("illum"):
        mat.emissive = color
    layers = [l for l in el.findall("MatLayers/Layer") if not (l.get("Name") or "").lower().startswith("wear")]
    layer = layers[0] if layers else el.find("MatLayers/Layer")
    if layer is not None and layer.get("TintColor"):
        tint = _floats(layer.get("TintColor"), color)
        if color == (1.0, 1.0, 1.0) or shader.lower().startswith(("layerblend", "hardsurface")):
            info = _layer(archive, layer.get("Path"))
            base = info["color"] if info else (1.0, 1.0, 1.0)
            color = tuple(t * b for t, b in zip(tint, base))
            if info:
                mat.spec = info["spec"]
                if info["tint_mode"] == 2:      # metal layers: the tint colours the reflection
                    mat.spec = tuple(t * c for t, c in zip(tint, mat.spec))
                try:
                    mat.gloss = info["gloss"] * float(layer.get("GlossMult", "1"))
                except ValueError:
                    mat.gloss = info["gloss"]
            # PaletteTint 1/2/3: colour from entry A/B/C of the item's tint palette (DataCore); unknown -> dark grey
            slot = layer.get("PaletteTint", "0")
            key = "ABC"[int(slot) - 1] if slot in ("1", "2", "3") else None
            paint = None
            if key and palette and palette.get(key):
                paint = palette_linear(palette[key])
                color = tuple(p * b for p, b in zip(paint, base))
                # the paint entry also sets reflectance and glossiness
                if (palette.get("spec") or {}).get(key):
                    mat.spec = palette_linear(palette["spec"][key])
                if (palette.get("gloss") or {}).get(key) is not None:
                    mat.gloss = palette["gloss"][key] / 255.0
            elif slot not in ("0", ""):
                color = tuple(c * 0.22 for c in tint)
            mat.color = color
            if info:
                mat.albedo = tuple(t * d for t, d in zip(paint or tint, info["diff"]))
            if info:
                l_diff, l_norm, mat.metal = info["diffuse"], info["normal"], info["metal"]
                mat.diffuse = l_diff
                mat.detail_normal = l_norm
                if info["spec_map"] and not (key and (palette or {}).get("spec", {}).get(key)):
                    mat.spec_map, mat.spec_tiled = info["spec_map"], True
                if l_norm and "_ddna" in l_norm.lower():
                    mat.gloss_map = l_norm
                try:
                    mat.tiling = float(layer.get("UVTiling", "1")) or 1.0
                except ValueError:
                    pass
                if not mat.normal and l_norm:
                    mat.normal, mat.layer_normal = l_norm, True
    return mat


def _pp_float(pp, name, default):
    try:
        return float(pp.get(name, default)) if pp is not None else default
    except ValueError:
        return default


def _hull_stencil(mat, el, palette):
    """Camo / livery stencil of a hull paint: a mask whose R, G and B layers are painted over the base paint.
    With StencilTintOverride the layers take the paint's entries A, B, C; otherwise StencilDiffuseColor 1-3."""
    path = _slot(el, "TexSlot7")
    if not path:
        return
    pp = el.find("PublicParams")
    if _pp_float(pp, "StencilTintOverride", 0) >= 0.5 and palette and all(palette.get(k) for k in "ABC"):
        colors = [palette_linear(palette[k]) for k in "ABC"]
    else:
        colors = [_floats(pp.get(n) if pp is not None else None, (1.0, 1.0, 1.0))
                  for n in ("StencilDiffuseColor", "StencilDiffuseColor2", "StencilDiffuseColor3")]
    mat.stencil_map = path
    mat.stencil = {"tiling": _pp_float(pp, "StencilTiling", 1.0), "uv2": _pp_float(pp, "UseUV2ForStencil", 0) >= 0.5,
                   "opacity": _pp_float(pp, "StencilOpacity", 1.0),
                   "colors": [[round(c, 5) for c in col] for col in colors]}


def load(archive, path, palette=None):
    """Return the list of sub-materials of a .mtl (by index), or [] when it cannot be found."""
    if not path:
        return []
    cand = path if path.lower().endswith(".mtl") else path + ".mtl"
    if not archive.exists(cand):
        return []
    root = cryxml.parse(archive.read(cand))
    subs = root.find("SubMaterials")
    if subs is None:
        return [_material(root, archive, palette)]
    return [_material(el, archive, palette) for el in subs if el.tag == "Material"]


def resolve_path(archive, geometry_path, mtl_name):
    """MtlName chunks hold either a bare name (same folder) or a path relative to Data/."""
    if not mtl_name:
        return None
    folder = geometry_path.replace("\\", "/").rsplit("/", 1)[0]
    name = mtl_name.replace("\\", "/")
    for cand in (name, f"{folder}/{name}", f"{folder}/{name.rsplit('/', 1)[-1]}"):
        c = cand if cand.lower().endswith(".mtl") else cand + ".mtl"
        if archive.exists(c):
            return c
    # some names differ from the file by "-"/"_" and the file sits a folder or two up (KLWE_las_rep_s1_3 ->
    # Weapons/KLWE/KLWE_las_rep_s1-3.mtl): the closest .mtl with the same name, within two folders up
    found = _mtl_index(archive).get(_mtl_key(name.rsplit("/", 1)[-1]))
    if found:
        parts = folder.lower().split("/")
        for up in range(3):
            base = "/".join(parts[:len(parts) - up]) + "/"
            near = [p for p in found if p.lower().startswith(base)]
            if near:
                return min(near, key=lambda p: (p.count("/"), p.lower()))
    return None


def _mtl_key(name):
    stem = name.lower()
    stem = stem[:-4] if stem.endswith(".mtl") else stem
    return stem.replace("-", "_")


def _mtl_index(archive):
    """{name key: [paths]} of every .mtl in the archive (built once per archive)."""
    idx = getattr(archive, "_mtl_index", None)
    if idx is None:
        idx = {}
        for n in archive.names:
            if n.lower().endswith(".mtl"):
                p = n.replace("\\", "/")
                p = p[5:] if p.lower().startswith("data/") else p
                idx.setdefault(_mtl_key(p.rsplit("/", 1)[-1]), []).append(p)
        archive._mtl_index = idx
    return idx


def shading(mat):
    """Parameters of the game's spec/gloss shading for the viewer (None for kinds it leaves alone).
    Colours are linear; texture paths go through /api/texture. `tiling` repeats the layer textures (colour, normal,
    gloss_map); obj_gloss and hal use the plain UVs."""
    if mat.kind not in ("solid", "decal"):
        return None
    return {"albedo": [round(c, 5) for c in (mat.albedo or mat.color)],
            "spec": [round(c, 5) for c in mat.spec],
            "gloss": round(max(0.0, min(1.0, mat.gloss)), 4),
            "tiling": mat.tiling,
            # the GLB's UVs are already multiplied by the tiling when everything on the material tiles (export.py)
            "uv_scale": mat.tiling if (mat.diffuse and abs(mat.tiling - 1.0) > 1e-3
                                       and not (mat.normal and not mat.layer_normal)) else 1.0,
            "color_map": mat.diffuse if not mat.stencil_colors else None,
            "normal_map": None if mat.layer_normal else mat.normal,
            "detail_normal": mat.detail_normal,
            "gloss_map": mat.gloss_map,
            "spec_map": mat.spec_map,
            "spec_tiled": mat.spec_tiled,
            "obj_gloss": mat.obj_gloss if mat.obj_gloss != mat.gloss_map else None,
            "hal": mat.hal,
            "opacity": round(mat.opacity, 4),
            "pom": mat.pom,
            "height_map": mat.height_map,
            "alpha_test": mat.alpha_test,
            "stencil_map": mat.stencil_map,
            "stencil": mat.stencil,
            "shader": mat.shader_name}


def shading_id(sh):
    """Short stable key of a shading dict (stored in the GLB material name as kind|name|id)."""
    import json
    import zlib
    return "%08x" % zlib.crc32(json.dumps(sh, sort_keys=True).encode())
