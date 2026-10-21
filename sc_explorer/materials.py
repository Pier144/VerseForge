"""Material (.mtl) loading: sub-material names, a display colour, textures and a visibility class."""
from dataclasses import dataclass

from . import cryxml


@dataclass
class Material:
    name: str
    shader: str
    kind: str          # "solid", "decal", "glass", "hidden"
    color: tuple       # linear RGB 0..1
    diffuse: str | None = None     # colour texture (source path as written in the .mtl)
    normal: str | None = None      # tangent-space normal map (_ddn / _ddna)
    tiling: float = 1.0            # UV repeat of the diffuse texture (layer materials)
    layer_normal: bool = False     # normal map comes from the tiled layer, not the object
    alpha_test: float = 0.0
    metal: bool = False


def srgb_to_linear(rgb8):
    c = [x / 255.0 for x in rgb8]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


def _floats(text, default):
    try:
        v = tuple(float(x) for x in text.split(","))
        return v[:3] if len(v) >= 3 else default
    except (AttributeError, ValueError):
        return default


def classify(name, shader):
    n, s = name.lower(), shader.lower()
    if s == "nodraw" or "proxy" in n or "nodraw" in n or "physics" in n:
        return "hidden"
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


def _layer(archive, path):
    """Colour, diffuse and normal texture of a tileable layer material (materials/layers/…)."""
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
    color = _floats(root.get("Diffuse"), (1.0, 1.0, 1.0))
    metal = max(color) < 0.02
    if metal:  # PBR metals: no diffuse, the specular colour is the metal's colour
        color = _floats(root.get("Specular"), (0.6, 0.6, 0.6))
    return color, diffuse, normal, metal


def _material(el, archive=None, palette=None):
    name = el.get("Name", "")
    shader = el.get("Shader", "")
    color = _floats(el.get("Diffuse"), (0.6, 0.6, 0.6))
    diffuse, normal = _texture_slots(el)
    mat = Material(name, shader, classify(name, shader), color, diffuse, normal)
    try:
        mat.alpha_test = float(el.get("AlphaTest", "0"))
    except ValueError:
        pass
    layers = [l for l in el.findall("MatLayers/Layer") if not (l.get("Name") or "").lower().startswith("wear")]
    layer = layers[0] if layers else el.find("MatLayers/Layer")
    if layer is not None and layer.get("TintColor"):
        tint = _floats(layer.get("TintColor"), color)
        if color == (1.0, 1.0, 1.0) or shader.lower().startswith(("layerblend", "hardsurface")):
            info = _layer(archive, layer.get("Path"))
            base = info[0] if info else (1.0, 1.0, 1.0)
            color = tuple(t * b for t, b in zip(tint, base))
            # PaletteTint 1/2/3: colour from entry A/B/C of the item's tint palette (DataCore); unknown -> dark grey
            slot = layer.get("PaletteTint", "0")
            if slot in ("1", "2", "3") and palette and palette.get("ABC"[int(slot) - 1]):
                color = tuple(p * b for p, b in zip(srgb_to_linear(palette["ABC"[int(slot) - 1]]), base))
            elif slot not in ("0", ""):
                color = tuple(c * 0.22 for c in tint)
            mat.color = color
            if info:
                _, l_diff, l_norm, mat.metal = info
                mat.diffuse = l_diff
                try:
                    mat.tiling = float(layer.get("UVTiling", "1")) or 1.0
                except ValueError:
                    pass
                if not mat.normal and l_norm:
                    mat.normal, mat.layer_normal = l_norm, True
    return mat


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
    return None
