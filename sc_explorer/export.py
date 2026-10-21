"""Model -> GLB / OBJ (+MTL and textures, zipped) / STL."""
import io
import zipfile

import numpy as np
import trimesh
from PIL import Image

# CryEngine is Z-up/Y-forward; glTF and OBJ are Y-up.
Z_UP_TO_Y_UP = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], np.float64)


def _srgb(c):
    c = np.clip(np.asarray(c, np.float64), 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def select(model, include_hidden=False, include_decals=True, include_glass=True):
    out = []
    for p in model.parts:
        k = p.material.kind
        if (k == "hidden" and not include_hidden) or (k == "decal" and not include_decals) or (k == "glass" and not include_glass):
            continue
        out.append(p)
    return out


def merged_by_material(parts):
    """Merge parts sharing a material so the viewer gets few draw calls -> [(material, verts, faces, uvs|None)]."""
    groups = {}
    for p in parts:
        groups.setdefault(id(p.material), []).append(p)
    out = []
    for ps in groups.values():
        verts, faces, uvs, off = [], [], [], 0
        for p in ps:
            verts.append(p.vertices)
            faces.append(p.faces + off)
            uvs.append(p.uvs if p.uvs is not None else np.zeros((len(p.vertices), 2), np.float32))
            off += len(p.vertices)
        has_uv = any(p.uvs is not None for p in ps)
        out.append((ps[0].material, np.vstack(verts), np.vstack(faces), np.vstack(uvs) if has_uv else None))
    return out


# ------------------------------------------------------------------ textures
def _tiled(img, tiling, size):
    """Repeat a tileable layer texture `tiling` times inside one size x size image (same UVs as the normal map)."""
    reps = max(1, round(tiling))
    tile = img.resize((max(4, size // reps),) * 2, Image.LANCZOS)
    out = Image.new(img.mode, (tile.width * reps,) * 2)
    for y in range(reps):
        for x in range(reps):
            out.paste(tile, (x * tile.width, y * tile.height))
    return out


def material_textures(mat, cache, size):
    """(base colour image | None, normal image | None, uv scale) for a material. Images carry .format for trimesh."""
    if cache is None or mat.kind in ("hidden", "glass"):
        return None, None, 1.0
    key = ("mat", mat.diffuse, mat.normal, mat.tiling, mat.layer_normal, mat.kind, mat.alpha_test, size)
    hit = cache.memo(key)
    if hit is not None:
        return hit
    base = cache.get(mat.diffuse, size) if mat.diffuse else None
    normal = cache.get(mat.normal, size, normal=True) if mat.normal else None
    uv_scale = 1.0
    if base is not None and abs(mat.tiling - 1.0) > 1e-3:
        if normal is not None and not mat.layer_normal:
            base = _tiled(base, mat.tiling, size)      # object normal map uses the plain UVs: bake the repeat
        else:
            uv_scale = mat.tiling                      # everything tiles together: just scale the UVs
    if base is not None:
        cut = mat.kind == "decal" or mat.alpha_test > 0
        has_alpha = base.mode == "RGBA" and cut and base.getchannel("A").getextrema()[0] < 250
        base = base.copy() if has_alpha else base.convert("RGB")
        base.format = "PNG" if has_alpha else "JPEG"
    if normal is not None:
        normal = normal.copy()
        normal.format = "JPEG"
    out = (base, normal, uv_scale)
    cache.memo(key, out)
    return out


def to_glb(model, include_hidden=True, textures=None, tex_size=1024):
    scene = trimesh.Scene()
    for i, (mat, v, f, uv) in enumerate(merged_by_material(select(model, include_hidden=include_hidden))):
        name, kind = mat.name, mat.kind
        base, normal, uv_scale = material_textures(mat, textures, tex_size) if uv is not None else (None, None, 1.0)
        rgb = _srgb(mat.color)
        alpha = 0.35 if kind == "glass" else 1.0
        if base is not None and base.mode == "RGBA":
            alpha_mode = "BLEND" if kind == "decal" else "MASK"
        else:
            alpha_mode = "BLEND" if kind == "glass" else "OPAQUE"
        pbr = trimesh.visual.material.PBRMaterial(
            name=f"{kind}|{name}", baseColorFactor=[*rgb, alpha], baseColorTexture=base, normalTexture=normal,
            metallicFactor=0.85 if mat.metal else 0.3, roughnessFactor=0.45 if mat.metal else 0.6,
            alphaMode=alpha_mode, alphaCutoff=(mat.alpha_test or 0.5) if alpha_mode == "MASK" else None,
            doubleSided=True)
        mesh = trimesh.Trimesh(v @ Z_UP_TO_Y_UP.T, f, process=False)
        if base is not None or normal is not None:
            # trimesh expects OpenGL UVs (V up) and flips them back when writing glTF
            t = uv.astype(np.float64) * uv_scale
            mesh.visual = trimesh.visual.TextureVisuals(uv=np.column_stack([t[:, 0], 1.0 - t[:, 1]]), material=pbr)
        else:
            mesh.visual = trimesh.visual.TextureVisuals(material=pbr)
        scene.add_geometry(mesh, node_name=f"{kind}|{name}|{i}", geom_name=f"{kind}|{name}|{i}")
    return scene.export(file_type="glb", include_normals=True)


def _safe(name):
    return "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in name) or "mat"


def to_obj_zip(model, stem, include_decals=True, textures=None, tex_size=2048):
    obj, mtl = io.StringIO(), io.StringIO()
    obj.write(f"# {model.path}\n# Esportato da VerseForge - metri, Y in alto\nmtllib {stem}.mtl\n")
    files, used = {}, set()
    off = vt_off = 1
    for i, (mat, v, f, uv) in enumerate(merged_by_material(select(model, include_decals=include_decals))):
        safe = _safe(mat.name)
        if safe in used:
            safe = f"{safe}_{i}"
        used.add(safe)
        color = mat.color
        mtl.write(f"newmtl {safe}\nKd {color[0]:.4f} {color[1]:.4f} {color[2]:.4f}\n" + ("d 0.35\n" if mat.kind == "glass" else ""))
        base, normal, uv_scale = material_textures(mat, textures, tex_size) if uv is not None else (None, None, 1.0)
        for img, tag in ((base, "map_Kd"), (normal, "map_Bump")):
            if img is None:
                continue
            ext = "png" if img.format == "PNG" else "jpg"
            fname = f"textures/{safe}_{'diff' if tag == 'map_Kd' else 'normal'}.{ext}"
            buf = io.BytesIO()
            img.save(buf, format=img.format, **({"quality": 92} if ext == "jpg" else {}))
            files[fname] = buf.getvalue()
            mtl.write(f"{tag} {fname}\n" + ("map_d " + fname + "\n" if tag == "map_Kd" and ext == "png" else ""))
        mtl.write("\n")
        obj.write(f"g {safe}\nusemtl {safe}\n")
        vy = v @ Z_UP_TO_Y_UP.T
        obj.write("".join(f"v {a:.6f} {b:.6f} {c:.6f}\n" for a, b, c in vy))
        if base is not None or normal is not None:
            t = uv.astype(np.float64) * uv_scale
            obj.write("".join(f"vt {a:.6f} {1.0 - b:.6f}\n" for a, b in t))
            obj.write("".join(f"f {a + off}/{a + vt_off} {b + off}/{b + vt_off} {c + off}/{c + vt_off}\n" for a, b, c in f))
            vt_off += len(t)
        else:
            obj.write("".join(f"f {a + off} {b + off} {c + off}\n" for a, b, c in f))
        off += len(v)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{stem}.obj", obj.getvalue())
        z.writestr(f"{stem}.mtl", mtl.getvalue())
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def to_stl(model, include_decals=False):
    """Single STL in millimetres, Z up (slicer convention). Raw game surfaces: see print export for a solid."""
    parts = select(model, include_decals=include_decals, include_glass=True)
    v = np.vstack([p.vertices for p in parts]) * 1000.0
    off = np.cumsum([0] + [len(p.vertices) for p in parts[:-1]])
    f = np.vstack([p.faces + o for p, o in zip(parts, off)])
    return trimesh.Trimesh(v, f, process=False).export(file_type="stl")
