"""Assemble a viewable model (list of parts in object space, metres, Z up / Y forward) from an asset path."""
from dataclasses import dataclass, field, replace

import numpy as np

from . import cryxml, ivo, materials

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


@dataclass
class Model:
    path: str
    parts: list = field(default_factory=list)
    warnings: list = field(default_factory=list)   # (i18n key, {args}) tuples
    cache: dict = field(default_factory=dict)      # encoded GLBs for the viewer

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


def load_geometry(archive, path, transform=None, material_path=None, label=None):
    """Parts of one .cgf/.cga/.skin/.chr file, already placed by its node hierarchy."""
    main = ivo.IvoFile(archive.read(path))
    node_list = ivo.nodes(main)
    md = ivo.mesh(_mesh_source(archive, path, main), node_space=bool(node_list))
    if md is None:
        return []
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
        parts.append(Part(name, mat, verts, inverse.reshape(-1, 3).astype(np.int64), path, uvs, mtl or "", mat_id))
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
            model.parts += load_geometry(archive, geo, transform, _mtl(archive, att.get("Material")), att.get("AName"))
        except Exception as e:  # keep the rest of the assembly
            model.warnings.append(("warn_part_error", {"path": geo, "error": str(e)}))


def _mtl(archive, name):
    if not name:
        return None
    p = _data_path(name)
    p = p if p.lower().endswith(".mtl") else p + ".mtl"
    return p if archive.exists(p) else None


def load_model(archive, path):
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
    return model


def with_variant(model, archive, material=None, palette=None):
    """Copy of `model` with a paint variant: `material` replaces the model's main .mtl, `palette` tints layers."""
    weight = {}
    for p in model.parts:
        if p.mtl_path:
            weight[p.mtl_path] = weight.get(p.mtl_path, 0) + len(p.faces)
    main = max(weight, key=weight.get) if weight else None
    override = _mtl(archive, material) if material else None
    cache = {}
    parts = []
    for p in model.parts:
        path = override if override and p.mtl_path == main else p.mtl_path
        if not path or p.mat_id < 0:
            parts.append(p)
            continue
        if path not in cache:
            try:
                cache[path] = materials.load(archive, path, palette)
            except Exception:
                cache[path] = []
        mats = cache[path]
        parts.append(replace(p, material=mats[p.mat_id]) if p.mat_id < len(mats) else p)
    return Model(model.path, parts, list(model.warnings))
