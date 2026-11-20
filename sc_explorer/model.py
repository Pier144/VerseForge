"""Assemble a viewable model (list of parts in object space, metres, Z up / Y forward) from an asset path."""
import re
from dataclasses import dataclass, field, replace

import numpy as np

from . import cryxml, ivo, materials, rig

GEOMETRY_EXT = (".cgf", ".cga", ".skin", ".chr", ".cdf")


@dataclass
class Part:
    name: str
    material: materials.Material
    vertices: np.ndarray
    faces: np.ndarray
    source: str
    uvs: np.ndarray | None = None    # per vertex, as stored in the game (V down, like glTF)
    mtl_path: str = ""               # .mtl file and sub-material index, to re-resolve paint variants
    mat_id: int = -1
    node: str = ""                   # bone/node the part follows when animated ("" = object root)
    vbones: np.ndarray | None = None     # skinned meshes: dominant bone index per vertex (into bone_names)
    bone_names: tuple | None = None
    uvs2: np.ndarray | None = None       # second UV set (stencils), same layout as uvs
    room: int = -1                       # interiors: index into Model.rooms, -1 = no room (hull, structure)


@dataclass
class Model:
    path: str
    parts: list = field(default_factory=list)
    warnings: list = field(default_factory=list)   # (i18n key, {args}) tuples
    cache: dict = field(default_factory=dict)      # encoded GLBs for the viewer
    skeleton: list = field(default_factory=list)   # rig.Bone list, only for animated models
    animations: list = field(default_factory=list) # animations.AnimRef list (the actions the viewer offers)
    anim_sets: list = field(default_factory=list)  # animations.AnimSet per animated instance (clip sources)
    rooms: list = field(default_factory=list)      # interiors: {name, key, container, centre} per room (assembly)

    def bounds(self):
        if not self.parts:
            return np.zeros(3), np.zeros(3)
        v = np.vstack([p.vertices for p in self.parts])
        return v.min(0), v.max(0)

    def stats(self):
        lo, hi = self.bounds()
        return {
            "parts": len(self.parts),
            "triangles": int(sum(len(p.faces) for p in self.parts)),
            "vertices": int(sum(len(p.vertices) for p in self.parts)),
            "size_m": [round(float(x), 4) for x in (hi - lo)],
            "materials": sorted({(p.material.name, p.material.kind) for p in self.parts}),
        }


DEFAULT_MAT = materials.Material("default", "", "solid", (0.6, 0.6, 0.6))


def quat_matrix(q):
    """Quaternion (x, y, z, w) -> 3x3 rotation."""
    x, y, z, w = q
    n = x * x + y * y + z * z + w * w
    if n < 1e-12:
        return np.eye(3)
    s = 2.0 / n
    return np.array([
        [1 - s * (y * y + z * z), s * (x * y - z * w), s * (x * z + y * w)],
        [s * (x * y + z * w), 1 - s * (x * x + z * z), s * (y * z - x * w)],
        [s * (x * z - y * w), s * (y * z + x * w), 1 - s * (x * x + y * y)],
    ])


def _transform(v, m):
    return v @ m[:3, :3].T + m[:3, 3]


def _mesh_source(archive, path, main):
    companion = path + "m"
    if archive.exists(companion):
        return ivo.IvoFile(archive.read(companion))
    return main


def lod0_path(path):
    """'ship_lod1.cgf' -> 'ship.cgf'; None when `path` is not a LOD file."""
    m = re.fullmatch(r"(.*[^/\\])_lod\d+(\.\w+)", path, re.I)
    return m.group(1) + m.group(2) if m else None


def _lod0_nodes(archive, path):
    """Node table of the LOD0 of a LOD file ([] when there is none)."""
    base = lod0_path(path)
    try:
        return ivo.nodes(ivo.IvoFile(archive.read(base))) if base and archive.exists(base) else []
    except Exception:
        return []


def placed_bounds(archive, path):
    """(min, max) of a geometry file as its nodes place it, without its materials; None when it has no mesh."""
    main = ivo.IvoFile(archive.read(path))
    node_list = ivo.nodes(main)
    md = ivo.mesh(_mesh_source(archive, path, main), node_space=bool(node_list))
    if md is None:
        return None
    by_node = {}
    for s in md.subsets:
        f = md.indices[s.first_index:s.first_index + s.num_indices] + s.vertex_base
        if len(f) >= 3 and f.max() < len(md.positions):
            by_node.setdefault(s.node, []).append(f)
    lo = hi = None
    for node, fl in by_node.items():
        v = md.positions[np.unique(np.concatenate(fl))]
        if node_list and node < len(node_list):
            v = _transform(v, node_list[node].world)
        lo = v.min(0) if lo is None else np.minimum(lo, v.min(0))
        hi = v.max(0) if hi is None else np.maximum(hi, v.max(0))
    return None if lo is None else (lo, hi)


def lod_fits(archive, lod, path):
    """Does a loaded LOD model lie where its LOD0 (`path`) does? A few LOD files keep some pieces in another space
    than the rest (25 of the 10,500 used by ship interiors: the Polaris bridge ceiling 56 m away, a Perseus ladder
    41 m, the button of the Fortune's storage 20 m): those are not used."""
    try:
        ref = placed_bounds(archive, path)
    except Exception:
        return True
    if ref is None or not lod.parts:
        return True
    lo, hi = lod.bounds()
    pad = 0.5 * (ref[1] - ref[0]) + 0.5
    return bool((lo >= ref[0] - pad).all() and (hi <= ref[1] + pad).all())


def load_geometry(archive, path, transform=None, material_path=None, label=None):
    """Parts of one .cgf/.cga/.skin/.chr file, already placed by its node hierarchy."""
    main = ivo.IvoFile(archive.read(path))
    node_list = ivo.nodes(main)
    src = _mesh_source(archive, path, main)
    md = ivo.mesh(src, node_space=bool(node_list))
    if md is None:
        return []
    if not node_list:
        # a LOD file (x_lod1.cgf) has no node table: its subsets name the nodes of the LOD0 and its positions are in
        # their space. Without them the pieces of a multi-node object land in the wrong place (the three blocks of
        # the Avenger's cockpit stuck out through the canopy)
        borrowed = _lod0_nodes(archive, path)
        if borrowed and all(s.node < len(borrowed) for s in md.subsets):
            node_list, md = borrowed, ivo.mesh(src, node_space=True)
    vbones = bone_names = None
    if path.lower().endswith((".skin", ".chr")):
        vb = ivo.vertex_bones(src)
        names = tuple(b["name"] for b in ivo.bones(main))
        if vb is not None and len(vb) == len(md.positions) and names:
            vbones, bone_names = vb, names
    mtl = material_path or materials.resolve_path(archive, path, ivo.material_name(main))
    mats = materials.load(archive, mtl)
    groups = {}
    for s in md.subsets:
        f = md.indices[s.first_index:s.first_index + s.num_indices]
        if len(f) < 3:
            continue
        f = f[:len(f) // 3 * 3].reshape(-1, 3) + s.vertex_base
        if f.max() >= len(md.positions):
            continue
        groups.setdefault((s.node, s.material), []).append(f)
    stem = path.replace("\\", "/").rsplit("/", 1)[-1]
    parts = []
    for (node, mat_id), fl in groups.items():
        faces = np.vstack(fl)
        used, inverse = np.unique(faces, return_inverse=True)
        verts = md.positions[used]
        if node_list and node < len(node_list):
            verts = _transform(verts, node_list[node].world)
        if transform is not None:
            verts = _transform(verts, transform)
        mat = mats[mat_id] if mat_id < len(mats) else materials.Material(f"mat{mat_id}", "", "solid", DEFAULT_MAT.color)
        node_name = node_list[node].name if node_list and node < len(node_list) else ""
        name = " / ".join(x for x in (label or stem, node_name, mat.name) if x)
        uvs = md.uvs[used] if md.uvs is not None else None
        parts.append(Part(name, mat, verts, inverse.reshape(-1, 3).astype(np.int64), path, uvs, mtl or "", mat_id,
                          node_name, vbones[used] if vbones is not None else None, bone_names,
                          md.uvs2[used] if md.uvs2 is not None and len(md.uvs2) == len(md.positions) else None))
    return parts


def _bone_matrix(bone, rel_rot=None, rel_pos=None):
    m = np.eye(4)
    m[:3, :3] = quat_matrix(bone["wq"])
    m[:3, 3] = bone["wp"]
    if rel_rot is not None or rel_pos is not None:
        r = np.eye(4)
        if rel_rot is not None:
            w, x, y, z = rel_rot
            r[:3, :3] = quat_matrix((x, y, z, w))
        if rel_pos is not None:
            r[:3, 3] = rel_pos
        m = m @ r
    return m


def _floats(text, n):
    try:
        v = [float(x) for x in text.split(",")]
        return v if len(v) == n else None
    except (AttributeError, ValueError):
        return None


def _data_path(p):
    p = p.replace("\\", "/")
    return p[5:] if p.lower().startswith("data/") else p


def load_cdf(archive, path, model):
    root = cryxml.parse(archive.read(path))
    m = root.find("Model")
    skeleton = []
    if m is not None and m.get("File"):
        chr_path = _data_path(m.get("File"))
        if archive.exists(chr_path):
            chr_file = ivo.IvoFile(archive.read(chr_path))
            skeleton = ivo.bones(chr_file)
            if ivo.mesh(_mesh_source(archive, chr_path, chr_file)) is not None:
                model.parts += load_geometry(archive, chr_path, material_path=_mtl(archive, m.get("Material")))
    bones = {b["name"].lower(): b for b in skeleton}
    for att in root.iter("Attachment"):
        binding = att.get("Binding")
        if not binding:
            continue
        geo = _data_path(binding)
        if not archive.exists(geo):
            model.warnings.append(("warn_attachment_missing", {"path": geo}))
            continue
        transform = None
        if att.get("Type") == "CA_BONE":
            bone = bones.get((att.get("BoneName") or "").lower())
            if bone is None:
                model.warnings.append(("warn_bone_missing", {"bone": att.get("BoneName")}))
                continue
            transform = _bone_matrix(bone, _floats(att.get("RelRotation"), 4), _floats(att.get("RelPosition"), 3))
        try:
            new = load_geometry(archive, geo, transform, _mtl(archive, att.get("Material")), att.get("AName"))
            if att.get("Type") == "CA_BONE":
                for p in new:
                    p.node = att.get("BoneName") or ""
            model.parts += new
        except Exception as e:  # keep the rest of the assembly
            model.warnings.append(("warn_part_error", {"path": geo, "error": str(e)}))


def _mtl(archive, name):
    if not name:
        return None
    p = _data_path(name)
    p = p if p.lower().endswith(".mtl") else p + ".mtl"
    return p if archive.exists(p) else None


def load_model(archive, path, adb_path=None, animated=True):
    """adb_path: the entity's Mannequin database (entities.adb_for), for readable animation names.
    animated=False skips the animation lookup (static props placed in ship interiors)."""
    model = Model(path)
    ext = path.lower().rsplit(".", 1)[-1]
    if ext == "cdf":
        load_cdf(archive, path, model)
    else:
        model.parts = load_geometry(archive, path)
        if not model.parts and ext == "chr":
            model.warnings.append(("warn_chr_skeleton",))
    if not model.parts and not model.warnings:
        model.warnings.append(("warn_no_geometry",))
    if model.parts and animated:
        try:
            rig.attach(archive, model, adb_path)
        except Exception as e:          # the model still shows, just without animations
            model.warnings.append(("warn_anim_error", {"clip": "*", "error": str(e)}))
    return model


def main_mtl(parts):
    """The model's main .mtl: the path with the most faces, the one a livery .mtl replaces (None without any)."""
    weight, spelt = {}, {}          # counted whatever the case of the path, given back as first spelt
    for p in parts:
        if p.mtl_path:
            weight[p.mtl_path.lower()] = weight.get(p.mtl_path.lower(), 0) + len(p.faces)
            spelt.setdefault(p.mtl_path.lower(), p.mtl_path)
    return spelt[max(weight, key=weight.get)] if weight else None


def with_variant(model, archive, material=None, palette=None):
    """Copy of `model` with a paint variant: `material` replaces the model's main .mtl, `palette` tints layers."""
    main = main_mtl(model.parts)
    override = _mtl(archive, material) if material else None
    cache = {}
    parts = []
    for p in model.parts:
        # the same file whatever its case: a tank's treads name the hull's .mtl as TMBL_Nova.mtl, the hull as tmbl_nova.mtl
        swapped = bool(override) and bool(main) and (p.mtl_path or "").lower() == main.lower()
        path = override if swapped else p.mtl_path
        if not path or p.mat_id < 0:
            parts.append(p)
            continue
        if path not in cache:
            try:
                cache[path] = materials.load(archive, path, palette)
            except Exception:
                cache[path] = []
        mats = cache[path]
        mat = mats[p.mat_id] if p.mat_id < len(mats) else None
        if swapped and (mat is None or (mat.name and not mat.name.strip("- "))):
            # a livery .mtl marks what it does not repaint with "--" placeholders (or ends early): those parts keep
            # the main .mtl's own material, with the paint's palette (Perseus landing gear on the full ship)
            if main not in cache:
                try:
                    cache[main] = materials.load(archive, main, palette)
                except Exception:
                    cache[main] = []
            own = cache[main]
            mat = own[p.mat_id] if p.mat_id < len(own) else None
        parts.append(replace(p, material=mat) if mat is not None else p)
    return replace(model, parts=parts, warnings=list(model.warnings), cache={})
