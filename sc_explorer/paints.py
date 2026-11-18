"""Instant paint switching (web/paint.js). The viewer's GLB of a model with several paints groups its parts by where
their material comes from, which does not depend on the paint, so every paint has the same geometry; a paint is then
just a table of materials, one per group, written as the GLB would write them (export.glb_material)."""
from . import export, materials


def group_keys(ref_model, fixed_from=None):
    """Group number of every part of `ref_model`, the model in its reference paint (variant_list()[0]). A paint only
    changes a part's material through its .mtl path and sub-material index (model.with_variant), so parts sharing
    both, and their reference material, share their material in every paint. Parts without a .mtl path are never
    repainted (model.with_variant leaves them alone): grouped by material.
    fixed_from: index of the first interior part. Interior parts never change with the paint, so they get their own
    groups even when they share a .mtl slot with a hull part."""
    index, out, memo = {}, [], {}
    for i, p in enumerate(ref_model.parts):
        k = memo.get(id(p.material))              # repr() once per material object: interiors have ~60k parts
        if k is None:
            k = memo[id(p.material)] = repr(p.material)
        key = ("mat", k) if not p.mtl_path or p.mat_id < 0 else ("slot", p.mtl_path, p.mat_id, k)
        if fixed_from is not None and i >= fixed_from:
            key = ("fixed", key)
        out.append(index.setdefault(key, len(index)))
    return out


def uv_scale(mat):
    """The repeat the GLB multiplies into a material's UVs (materials.shading, export.material_textures)."""
    if mat.kind not in ("solid", "decal") or not mat.diffuse or abs(mat.tiling - 1.0) <= 1e-3:
        return 1.0
    return 1.0 if (mat.normal and not mat.layer_normal) else mat.tiling


def _look(mat):
    """What has to stay the same for a material to be swapped in place: kind and name (mesh names, switches), UV
    repeat (baked into the GLB) and how the viewer draws it (batches and shadows depend on transparency)."""
    if mat.stencil_decal:
        # always a BLEND decal in a keyed GLB (export.glb_material); the UV repeat is baked into the UVs
        return ("stencil", mat.name, uv_scale(mat))
    if mat.kind == "screen":
        return ("screen", mat.name, mat.holo, mat.rtt)   # the name's |holo / |rtt ending (app.js)
    glows = bool(mat.emissive and any(mat.emissive))
    see = mat.kind == "glass" or (mat.kind == "decal" and (mat.pom or (mat.opacity < 1 and not glows)))
    return (mat.kind, mat.name, uv_scale(mat), see, mat.pom, mat.alpha_test > 0)


def check(ref, model, groups):
    """True when `model` (another paint of the same model, same full/interior) can take the place of `ref` by
    swapping materials only."""
    if len(ref.parts) != len(model.parts) or len(groups) != len(ref.parts):
        return False
    first, reprs = {}, {}

    def text(mat):                                  # repr() once per material object (interiors have ~60k parts)
        k = reprs.get(id(mat))
        if k is None:
            k = reprs[id(mat)] = repr(mat)
        return k

    for g, a, b in zip(groups, ref.parts, model.parts):
        if a.node != b.node or len(a.faces) != len(b.faces):
            return False
        mb = b.material
        if g in first:
            if first[g] is not mb and text(first[g]) != text(mb):
                return False                       # parts of one group must share their material in this paint too
        else:
            first[g] = mb
            if _look(a.material) != _look(mb):
                return False
    return True


def swatches(palette):
    """The paint's three colours (entries A, B, C, sRGB 0-255) for the menu, or None (no palette, or all black)."""
    cols = [(palette or {}).get(k) for k in "ABC"]
    if not all(cols) or not any(any(c) for c in cols):
        return None
    return [list(c) for c in cols]


def paint_table(model, groups, textures, tex_size=1024, fixed_from=None):
    """{"groups": one entry per group (the material in `model`'s paint as the GLB writes it, or None for groups that
    never change: proxies, and with fixed_from the groups that start at or after that part, the interior's),
    "shading": the game-look description of every shading id used}."""
    out = [None] * ((max(groups) + 1) if groups else 0)
    has_uv = {g for g, p in zip(groups, model.parts) if p.uvs is not None}   # a merged mesh has UVs if any part has
    shading, seen = {}, set()
    for i, (g, p) in enumerate(zip(groups, model.parts)):
        if g in seen:
            continue
        seen.add(g)
        if fixed_from is not None and i >= fixed_from:
            continue
        mat = p.material
        if mat.kind == "screen":
            out[g] = export.screen_fields(mat, g)
            continue
        mat, off = export.keyed_form(mat)
        if mat.kind == "hidden":
            continue
        fields, _, _, _, sh = export.glb_material(mat, g in has_uv, textures, tex_size, lite=True, group=g, off=off)
        out[g] = fields
        if sh and not off:
            shading[materials.shading_id(sh)] = sh
    return {"groups": out, "shading": shading}
