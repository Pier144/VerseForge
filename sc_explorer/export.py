"""Model -> GLB / OBJ (+MTL and textures, zipped) / STL."""
import re
import io
import zipfile
import zlib
from dataclasses import replace

import numpy as np
import trimesh
from PIL import Image

from . import materials

# CryEngine is Z-up/Y-forward; glTF and OBJ are Y-up.
Z_UP_TO_Y_UP = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], np.float64)


def _srgb(c):
    c = np.clip(np.asarray(c, np.float64), 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def select(model, include_hidden=False, include_decals=True, include_glass=True, include_holo=True):
    out = []
    for p in model.parts:
        k = p.material.kind
        if (k == "hidden" and not include_hidden) or (k == "decal" and not include_decals) or (k == "glass" and not include_glass):
            continue
        if p.material.holo and not include_holo:      # HUD veils floating in the air: nothing to print
            continue
        out.append(p)
    return out


def _lite_key(mat):
    """What a material looks like in the viewer's lite GLB once the game look has rebuilt it: the game look makes one
    three.js material per shading id and takes only the colour, glow and metal flag from the GLB (see _glb_mesh and
    gamelook.js). Materials equal on these are drawn the same: one group, one draw call. None = not rebuilt."""
    if mat.stencil_colors or mat.kind not in ("solid", "decal"):
        return None
    sid = _sid(mat)
    if not sid:
        return None
    return ("lite", mat.kind, mat.name, sid, tuple(mat.color), tuple(mat.emissive) if mat.emissive else None,
            mat.metal, bool(mat.stencil_map))


def merged_by_material(parts, uv2=False, lite=False, rooms=False, paint_groups=None):
    """Merge parts sharing a material so the viewer gets few draw calls -> [(material, verts, faces, uvs|None)].
    uv2=True adds a fifth item: the second UV set (stencils) when every part of the group has one, else None.
    rooms=True lets the viewer show one room of an interior alone, and adds a last item. Solid pieces are kept
    apart by room (the viewer batches them back into one draw call per material): the item is the room index, -1 for
    none. See-through pieces (decals, glass, screens) cannot be batched, so they stay one mesh per material with
    their triangles in room order: the item is the list of (room, first face, face count) runs.
    lite=True also merges materials that only differ in what the game look replaces anyway (_lite_key).
    paint_groups: list aligned with `parts` (keyed GLB, paints.py): parts merge by group instead of by material, so
    every paint gets the same meshes; each item then ends with its group number."""
    # grouped by the material's content, not the object: interiors load each prop on its own, so equal materials
    # come as separate copies (3,400 draw calls on the Perseus interior instead of a few hundred)
    buckets, keys = {}, {}
    for i, p in enumerate(parts):
        if paint_groups is not None:
            k = ("g", paint_groups[i])
        else:
            k = keys.get(id(p.material))
            if k is None:
                k = keys[id(p.material)] = (_lite_key(p.material) if lite else None) or repr(p.material)
        buckets.setdefault((k, p.room) if rooms and p.material.kind == "solid" else k, []).append((i, p))
    out = []
    for entries in buckets.values():
        ps = [p for _, p in entries]
        verts, faces, uvs, off = [], [], [], 0
        runs = None
        if rooms and ps[0].material.kind != "solid" and any(p.room >= 0 for p in ps):
            ps = sorted(ps, key=lambda p: p.room)          # stable: the order inside a room is kept
            runs, first = [], 0
            for p in ps:
                if runs and runs[-1][0] == p.room:
                    runs[-1][2] += len(p.faces)
                else:
                    runs.append([p.room, first, len(p.faces)])
                first += len(p.faces)
        for p in ps:
            verts.append(p.vertices)
            faces.append(p.faces + off)
            uvs.append(p.uvs if p.uvs is not None else np.zeros((len(p.vertices), 2), np.float32))
            off += len(p.vertices)
        has_uv = any(p.uvs is not None for p in ps)
        item = (ps[0].material, np.vstack(verts), np.vstack(faces), np.vstack(uvs) if has_uv else None)
        if uv2:
            item += (np.vstack([p.uvs2 for p in ps]) if all(p.uvs2 is not None for p in ps) else None,)
        if rooms:
            item += (runs if runs is not None else ps[0].room if ps[0].material.kind == "solid" else -1,)
        if paint_groups is not None:
            item += (paint_groups[entries[0][0]],)
        out.append(item)
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


def _stencil(mask, colors):
    """Palette stencil atlas (R/G/B masks) -> RGBA sticker: each channel takes its palette colour, alpha from the mask
    (soft edge around the game's AlphaTest)."""
    m = np.asarray(mask.convert("RGB"), np.float32) / 255.0
    s = m.sum(2, keepdims=True) + 1e-6
    col = (m / s) @ np.asarray(colors, np.float32)
    alpha = np.clip((m.max(2) - 0.05) / 0.06, 0, 1) * 255
    return Image.fromarray(np.dstack([col, alpha]).clip(0, 255).astype(np.uint8), "RGBA")


def material_textures(mat, cache, size):
    """(base colour image | None, normal image | None, uv scale) for a material. Images carry .format for trimesh."""
    if cache is None or mat.kind in ("hidden", "glass"):
        return None, None, 1.0
    key = ("mat", mat.diffuse, mat.normal, mat.tiling, mat.layer_normal, mat.kind, mat.alpha_test, mat.stencil_colors,
           size)
    hit = cache.memo(key)
    if hit is not None:
        return hit
    base = cache.get(mat.diffuse, size) if mat.diffuse else None
    if base is not None and mat.stencil_colors:
        base = _stencil(base, mat.stencil_colors)
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


_SCREEN_IMG = None


def screen_image():
    """A switched-on screen without content: dark glass, fine scanlines, soft vignette (emissive map, 256 px)."""
    global _SCREEN_IMG
    if _SCREEN_IMG is None:
        n = 256
        y, x = np.mgrid[0:n, 0:n] / (n - 1.0)
        lines = 0.78 + 0.22 * (np.arange(n)[:, None] % 4 < 2)
        grid = 1.0 + 0.25 * ((np.arange(n)[:, None] % 32 == 0) | (np.arange(n)[None, :] % 32 == 0))
        vign = 1.0 - 0.55 * (((x - 0.5) ** 2 + (y - 0.5) ** 2) / 0.5)
        v = np.clip(0.42 * lines * grid * vign, 0, 1)
        img = Image.fromarray((np.dstack([v, v, v]) * 255).astype(np.uint8), "RGB")
        img.format = "PNG"
        _SCREEN_IMG = img
    return _SCREEN_IMG


def _sid(mat):
    sh = materials.shading(mat)
    return materials.shading_id(sh) if sh else ""


def _q(values):
    """Colour factors as trimesh stores them in the GLB (uint8): the viewer's paint tables must match bit for bit."""
    return [float(np.round(np.clip(float(c), 0.0, 1.0) * 255.0) / 255.0) for c in values]


def keyed_form(mat):
    """(material, off) for a keyed GLB (paints.py). A livery stencil decal is hidden when its paint has no atlas
    (materials.py); in a keyed GLB it keeps one shape in every paint: a decal with UVs, `off` (never drawn) here."""
    if mat.stencil_decal and mat.kind == "hidden":
        return replace(mat, kind="decal"), True
    return mat, False


def glb_material(mat, has_uv, textures, tex_size, lite=False, group=None, off=False):
    """The glTF material _glb_mesh writes for `mat`: (fields, base image | None, normal image | None, uv scale,
    shading | None). `fields` is the JSON form the viewer rebuilds when it swaps paints (paints.paint_table):
    {name, color, alpha, metallic, roughness, emissive, alpha_mode, alpha_cutoff, texture, normal_texture, visible}.
    group: paint group of a keyed GLB, written into the name; off: see keyed_form."""
    kind = mat.kind
    sh = materials.shading(mat) if lite and not off else None
    if off:
        base, normal, uv_scale = None, None, 1.0
    elif sh and not mat.stencil_colors:
        base, normal, uv_scale = None, None, sh["uv_scale"]
    else:
        base, normal, uv_scale = material_textures(mat, textures, tex_size) if has_uv else (None, None, 1.0)
    rgb = _srgb(mat.color)
    alpha = 1.0
    metallic, rough = (0.85, 0.45) if mat.metal else (0.3, 0.6)
    if kind == "glass":
        # see-through as much as the glass lets light through, smooth and reflective (materials.glass_look)
        # (the body colour goes in linear, as glTF wants: sRGB-encoded it lit up as a pale grey veil)
        body, alpha = materials.glass_look(mat)
        rgb, metallic, rough = np.asarray(body), 0.0, 0.05
    if off:
        alpha_mode, alpha = "BLEND", 0.0
    elif group is not None and mat.stencil_decal:
        alpha_mode = "BLEND"                       # keyed GLB: one shape in every paint (see keyed_form)
    elif base is not None and base.mode == "RGBA":
        alpha_mode = "BLEND" if kind == "decal" else "MASK"
    else:
        alpha_mode = "BLEND" if kind == "glass" else "OPAQUE"
    color = _q([*rgb, alpha])
    fields = {"name": f"{kind}|{mat.name}|{'' if off else _sid(mat)}" + (f"|g{group}" if group is not None else ""),
              "color": color[:3], "alpha": color[3], "metallic": metallic, "roughness": rough,
              "emissive": [float(c) for c in _srgb(mat.emissive)] if mat.emissive else None,
              "alpha_mode": alpha_mode,
              "alpha_cutoff": (mat.alpha_test or 0.5) if alpha_mode == "MASK" else None,
              "texture": base is not None, "normal_texture": normal is not None, "visible": not off}
    return fields, base, normal, uv_scale, sh


def screen_fields(mat, group=None):
    """Name and glow of a screen material as _screen_mesh writes them. The group goes before the |rtt / |holo
    suffix: the viewer finds monitors and HUD veils by that ending (app.js)."""
    tail = "|holo" if mat.holo else "|rtt" if mat.rtt else ""
    glow = [float(c) for c in (mat.emissive or (0.15, 0.6, 0.8))]
    return {"name": f"screen|{mat.name}" + (f"|g{group}" if group is not None else "") + tail, "emissive": glow}


def _glb_mesh(mat, v, f, uv, textures, tex_size, axis=True, uv2=None, lite=False, group=None, off=False):
    """lite: for the viewer's game look, which loads the textures itself (/api/texture): materials it rebuilds get
    their UVs but no embedded images (saves encoding and hashing them on every load).
    group / off: keyed GLB (paints.py, keyed_form)."""
    if mat.kind == "screen":
        return _screen_mesh(mat, v, f, uv, axis, group)
    fields, base, normal, uv_scale, sh = glb_material(mat, uv is not None, textures, tex_size, lite, group, off)
    pbr = trimesh.visual.material.PBRMaterial(
        name=fields["name"], baseColorFactor=[*fields["color"], fields["alpha"]], baseColorTexture=base,
        normalTexture=normal, metallicFactor=fields["metallic"], roughnessFactor=fields["roughness"],
        alphaMode=fields["alpha_mode"], alphaCutoff=fields["alpha_cutoff"],
        emissiveFactor=fields["emissive"], doubleSided=True)
    mesh = trimesh.Trimesh(v @ Z_UP_TO_Y_UP.T if axis else v, f, process=False)
    if uv is not None and (base is not None or normal is not None or sh or off):
        # trimesh expects OpenGL UVs (V up) and flips them back when writing glTF
        t = uv.astype(np.float64) * uv_scale
        mesh.visual = trimesh.visual.TextureVisuals(uv=np.column_stack([t[:, 0], 1.0 - t[:, 1]]), material=pbr)
    else:
        mesh.visual = trimesh.visual.TextureVisuals(material=pbr)
    if uv2 is not None and (mat.stencil_map or group is not None):
        # custom glTF attribute (three.js reads it as "_uv2"): the camo/livery stencil is laid out on it. A keyed GLB
        # always carries it: a camo paint can put a stencil on a hull the stock paint leaves plain (Perseus)
        mesh.vertex_attributes["_UV2"] = uv2.astype(np.float32)
    return mesh


def _screen_mesh(mat, v, f, uv, axis, group=None):
    # glTF colour factors are linear: the screen's colours go in as they are (sRGB-encoding them again turned the
    # near-black glass mid grey and washed the glow out to white)
    sf = screen_fields(mat, group)
    glow = sf["emissive"]
    if mat.holo:
        # holographic HUD: a faint glowing veil you see through (the material name ends in "|holo")
        pbr = trimesh.visual.material.PBRMaterial(
            name=sf["name"], baseColorFactor=[*glow, 0.16], metallicFactor=0.0, roughnessFactor=1.0,
            emissiveFactor=glow, emissiveTexture=screen_image(), alphaMode="BLEND", doubleSided=True)
    else:
        pbr = trimesh.visual.material.PBRMaterial(
            name=sf["name"], baseColorFactor=[*(float(c) for c in mat.color), 1.0], metallicFactor=0.0,
            roughnessFactor=0.15, emissiveFactor=glow, emissiveTexture=screen_image(), doubleSided=True)
    mesh = trimesh.Trimesh(v @ Z_UP_TO_Y_UP.T if axis else v, f, process=False)
    if uv is not None:
        mesh.visual = trimesh.visual.TextureVisuals(uv=np.column_stack([uv[:, 0], 1.0 - uv[:, 1]]).astype(np.float64),
                                                    material=pbr)
    else:
        mesh.visual = trimesh.visual.TextureVisuals(material=pbr)
    return mesh


def _selected_groups(model, parts, groups):
    """The paint groups of the parts select() kept (groups is aligned with model.parts)."""
    if groups is None:
        return None
    keep = {id(p) for p in parts}
    return [int(g) for g, p in zip(groups, model.parts) if id(p) in keep]


def to_glb(model, include_hidden=True, textures=None, tex_size=1024, sources=None, lite=False, merge=None, groups=None):
    """sources: animations.sources() -> animated GLB for models with a skeleton.
    lite: viewer GLB (see _glb_mesh); also without normals, which the viewer computes (a third of the file).
    merge: fewer meshes for the viewer (default: with lite): parts that never move leave the still nodes of an animated
    model for the root (see _to_glb_animated) and, in a lite GLB, materials the game look draws the same are merged
    (_lite_key). User exports keep the plain layout.
    groups: paint group of every part (paints.group_keys), for the viewer's keyed GLB: see paints.py."""
    merge = lite if merge is None else merge
    parts = select(model, include_hidden=include_hidden)
    pg = _selected_groups(model, parts, groups)
    if sources and model.skeleton:
        return _to_glb_animated(model, parts, textures, tex_size, sources, lite, merge, pg)
    scene = trimesh.Scene()
    for i, item in enumerate(merged_by_material(parts, uv2=True, lite=lite and merge, rooms=True, paint_groups=pg)):
        mat, v, f, uv, uv2, room = item[:6]
        g = item[6] if pg is not None else None
        mat, off = keyed_form(mat) if pg is not None else (mat, False)
        node = _node_name(mat, i, room)
        scene.add_geometry(_glb_mesh(mat, v, f, uv, textures, tex_size, uv2=uv2, lite=lite, group=g, off=off),
                           node_name=node, geom_name=node)
    return scene.export(file_type="glb", include_normals=not lite)


ROOT_NODE = "__root__"


def _node_name(mat, i, room=-1):
    """Mesh names are "kind|material|number". Interiors add the room: "|R<room>" for a piece of one room, or
    "|M" and the runs of triangles of each room ("r<room>s<first face>n<faces>", room x = none) for a mesh that
    spans several (see merged_by_material)."""
    name = f"{mat.kind}|{mat.name}|{i}"
    if isinstance(room, list):
        return name + "|M" + "_".join(f"r{'x' if r < 0 else r}s{s}n{n}" for r, s, n in room)
    return name + (f"|R{room}" if room >= 0 else "")


def _animated_bones(model, sources):
    """The bones the clips move, and those plus their ancestors (the nodes an animated GLB keeps)."""
    from .caf import ROOT_HASH
    bones = model.skeleton
    by_name = {b.name: i for i, b in enumerate(bones)}
    moved = {by_name[t[h]] for _, c, t in sources for h in c.tracks if h != ROOT_HASH and t.get(h) in by_name}
    keep = set()
    for i in moved:
        while i >= 0 and i not in keep:
            keep.add(i)
            i = bones[i].parent
    return bones, by_name, moved, keep


def node_key(name):
    """A node's name as three.js keeps it (PropertyBinding.sanitizeNodeName): the viewer names the pose by these."""
    return re.sub(r"[\[\].:/]", "", re.sub(r"\s", "_", name))


def posed(model, sources, pose):
    """The model frozen in the pose the viewer shows (landing gear down, ramp open...), for the still exports.
    pose: {node_key(bone name): 16 floats}, each node's matrix relative to the model root, column by column (three.js
    Matrix4.elements), in the GLB's own space (Z up, metres). Every part follows its nearest kept ancestor, exactly
    as in the animated GLB the pose was read from. Nodes that did not move are left alone."""
    if not pose or not sources or not model.skeleton:
        return model
    bones, by_name, _, keep = _animated_bones(model, sources)
    delta = {}
    for i in keep:
        m = pose.get(node_key(bones[i].name))
        if m is None or len(m) != 16:
            continue
        d = np.array(m, dtype=np.float64).reshape(4, 4).T @ np.linalg.inv(bones[i].world)
        if np.isfinite(d).all() and not np.allclose(d, np.eye(4), atol=1e-5):
            delta[i] = d
    if not delta:
        return model
    home = {}

    def nearest(name):
        if name not in home:
            i = by_name.get(name, -1)
            while i >= 0 and i not in keep:
                i = bones[i].parent
            home[name] = i
        return home[name]

    parts = []
    for p in model.parts:
        d = delta.get(nearest(p.node)) if p.node else None
        parts.append(p if d is None else replace(p, vertices=p.vertices @ d[:3, :3].T + d[:3, 3]))
    return replace(model, parts=parts, cache={})


def _to_glb_animated(model, parts, textures, tex_size, sources, lite=False, merge=False, groups=None):
    """Node hierarchy for the bones/nodes the clips move (and their ancestors); everything else stays merged by
    material under the root, so a ship does not explode into hundreds of draw calls."""
    from . import anim_glb
    bones, by_name, moved, keep = _animated_bones(model, sources)
    scene = trimesh.Scene()
    axis = np.eye(4)
    axis[:3, :3] = Z_UP_TO_Y_UP
    scene.graph.update(frame_from=scene.graph.base_frame, frame_to=ROOT_NODE, matrix=axis)
    done = set()

    def add_bone(i):
        if i in done:
            return
        b = bones[i]
        if b.parent >= 0:
            add_bone(b.parent)
        parent = bones[b.parent].name if b.parent >= 0 else ROOT_NODE
        scene.graph.update(frame_from=parent, frame_to=b.name, matrix=b.local)
        done.add(i)

    for i in sorted(keep):
        add_bone(i)
    kept = {bones[i].name: bones[i] for i in keep}
    # each part hangs from its nearest kept ancestor: meshes often sit on child nodes of the animated one
    # (RSI landing gear: anim_leg -> geo_piston...), and must move with it. The viewer's lite GLB hangs it from its
    # nearest *moved* ancestor instead (merge): the still ancestors of moving parts (geo_front, geo_main_wings on the
    # Perseus) never move, so their parts join the root's and are drawn with them (403 -> 243 draw calls)
    hosts = {bones[i].name for i in moved} if merge else kept
    home = {}

    def nearest(name):
        if name not in home:
            i = by_name.get(name, -1)
            while i >= 0 and bones[i].name not in hosts:
                i = bones[i].parent
            home[name] = bones[i].name if i >= 0 else ROOT_NODE
        return home[name]

    pairs = list(zip(parts, groups if groups is not None else [None] * len(parts)))
    buckets = {}
    for p, g in pairs:
        buckets.setdefault(nearest(p.node) if p.node else ROOT_NODE, []).append((p, g))
    n = 0
    for frame, items in buckets.items():
        ps = [p for p, _ in items]
        gs = [g for _, g in items] if groups is not None else None
        if frame != ROOT_NODE:
            inv = np.linalg.inv(kept[frame].world)
            ps = [replace(p, vertices=p.vertices @ inv[:3, :3].T + inv[:3, 3]) for p in ps]
        for item in merged_by_material(ps, uv2=True, lite=lite and merge, rooms=True, paint_groups=gs):
            mat, v, f, uv, uv2, room = item[:6]
            g = item[6] if gs is not None else None
            mat, off = keyed_form(mat) if gs is not None else (mat, False)
            node = _node_name(mat, n, room)
            n += 1
            scene.add_geometry(_glb_mesh(mat, v, f, uv, textures, tex_size, axis=False, uv2=uv2, lite=lite,
                                         group=g, off=off),
                               node_name=node, geom_name=node, parent_node_name=frame)
    glb = scene.export(file_type="glb", include_normals=not lite)
    return anim_glb.add_animations(glb, [(n, c, {h: v for h, v in t.items() if v in kept}) for n, c, t in sources])


def _safe(name):
    return "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in name) or "mat"


def to_obj_zip(model, stem, include_decals=True, textures=None, tex_size=2048):
    obj, mtl = io.StringIO(), io.StringIO()
    obj.write(f"# {model.path}\n# Exported by VerseForge - metres, Y up\nmtllib {stem}.mtl\n")
    files, used = {}, set()
    off = vt_off = 1
    for i, (mat, v, f, uv) in enumerate(merged_by_material(select(model, include_decals=include_decals))):
        safe = _safe(mat.name)
        if safe in used:
            safe = f"{safe}_{i}"
        used.add(safe)
        color, opacity = materials.glass_look(mat) if mat.kind == "glass" else (mat.color, None)
        mtl.write(f"newmtl {safe}\nKd {color[0]:.4f} {color[1]:.4f} {color[2]:.4f}\n" +
                  (f"d {opacity:.3f}\n" if opacity is not None else ""))
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
    parts = select(model, include_decals=include_decals, include_glass=True, include_holo=False)
    v = np.vstack([p.vertices for p in parts]) * 1000.0
    off = np.cumsum([0] + [len(p.vertices) for p in parts[:-1]])
    f = np.vstack([p.faces + o for p, o in zip(parts, off)])
    return trimesh.Trimesh(v, f, process=False).export(file_type="stl")
