"""Skeleton of an animated model, and which bone/node each part follows.

Only models the game links animations to get a skeleton; the others keep loading exactly as before. Skinned meshes
stay rigid: each triangle follows the dominant bone of its first vertex (fine for mechanical objects)."""
import zlib
from dataclasses import dataclass, replace

import numpy as np

from . import animations, cryxml, ivo


@dataclass
class Bone:
    name: str
    parent: int
    local: np.ndarray       # 4x4 rest transform relative to the parent (Cry space, Z up)
    world: np.ndarray       # 4x4 rest transform in object space


def _quat_matrix(q):
    from .model import quat_matrix
    return quat_matrix(q)


def skeleton(archive, path):
    p = path.replace("\\", "/")
    ext = p.rsplit(".", 1)[-1].lower()
    if ext == "cdf":
        m = cryxml.parse(archive.read(p)).find("Model")
        f = (m.get("File") or "").replace("\\", "/") if m is not None else ""
        p, ext = (f[5:] if f.lower().startswith("data/") else f), "chr"
        if not p or not archive.exists(p):
            return []
    f = ivo.IvoFile(archive.read(p))
    raw = []
    if ext in ("chr", "skin"):
        for b in ivo.bones(f):
            w = np.eye(4)
            w[:3, :3] = _quat_matrix(b["wq"])
            w[:3, 3] = b["wp"]
            raw.append((b["name"], b["parent"], w))
    else:
        for n in ivo.nodes(f):
            w = np.eye(4)
            w[:3, :4] = n.world
            raw.append((n.name, n.parent, w))
    parents = [p if 0 <= p < len(raw) else -1 for _, p, _ in raw]
    for i in range(len(parents)):          # a malformed file must not loop forever: cut any cycle at its start
        seen, j = {i}, parents[i]
        while j >= 0:
            if j in seen:
                parents[i] = -1
                break
            seen.add(j)
            j = parents[j]
    out = []
    for (name, _, w), parent in zip(raw, parents):
        local = np.linalg.inv(raw[parent][2]) @ w if parent >= 0 else w.copy()
        out.append(Bone(name, parent, local, w))
    return out


def _split_skinned(p, known):
    """Split a skinned part into one part per dominant bone (bone names mapped to the skeleton by name)."""
    tri_bone = p.vbones[p.faces[:, 0]]
    out = []
    for bi in np.unique(tri_bone):
        name = p.bone_names[bi] if 0 <= bi < len(p.bone_names) else ""
        faces = p.faces[tri_bone == bi]
        used, inverse = np.unique(faces, return_inverse=True)
        out.append(replace(p, vertices=p.vertices[used], faces=inverse.reshape(-1, 3).astype(np.int64),
                           uvs=p.uvs[used] if p.uvs is not None else None, node=known.get(name.lower(), ""),
                           uvs2=p.uvs2[used] if p.uvs2 is not None else None,
                           vbones=None, bone_names=None))
    return out


def attach(archive, model, adb_path=None):
    """Find the model's animations; when there are some, give it a skeleton and tag each part with its node."""
    bones = skeleton(archive, model.path)
    if not bones:
        return
    refs = animations.find(archive, model.path, adb_path, names=[b.name for b in bones])
    if not refs:
        return
    known = {b.name.lower(): b.name for b in bones}
    parts = []
    for p in model.parts:
        if p.vbones is not None and p.bone_names:
            parts += _split_skinned(p, known)
        else:
            parts.append(replace(p, node=known.get(p.node.lower(), "")))
    model.parts, model.skeleton, model.animations = parts, bones, refs
    model.anim_sets = [animations.AnimSet("", refs, {zlib.crc32(b.name.encode()): b.name for b in bones})]
