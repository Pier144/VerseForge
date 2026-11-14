"""Add game animation clips to a GLB written by trimesh (which has no animation support).

Every node gets TRS instead of a matrix (glTF forbids matrices on animated nodes); each clip becomes one glTF
animation named like the clip, with LINEAR samplers for rotation and translation."""
import json
import struct

import numpy as np

from .caf import ROOT_HASH


def _split(glb):
    if glb[:4] != b"glTF":
        raise ValueError("not a GLB")
    o, js, bin_ = 12, None, b""
    while o < len(glb):
        length, kind = struct.unpack_from("<I4s", glb, o)
        chunk = glb[o + 8:o + 8 + length]
        if kind == b"JSON":
            js = json.loads(chunk)
        elif kind == b"BIN\0":
            bin_ = bytes(chunk)
        o += 8 + length
    return js, bin_


def _join(js, bin_):
    j = json.dumps(js, separators=(",", ":")).encode()
    j += b" " * (-len(j) % 4)
    bin_ += b"\0" * (-len(bin_) % 4)
    body = struct.pack("<I4s", len(j), b"JSON") + j + struct.pack("<I4s", len(bin_), b"BIN\0") + bin_
    return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body


def _quat(r):
    """3x3 rotation -> quaternion xyzw."""
    t = np.trace(r)
    if t > 0:
        s = np.sqrt(t + 1.0) * 2
        q = [(r[2, 1] - r[1, 2]) / s, (r[0, 2] - r[2, 0]) / s, (r[1, 0] - r[0, 1]) / s, 0.25 * s]
    elif r[0, 0] > r[1, 1] and r[0, 0] > r[2, 2]:
        s = np.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2]) * 2
        q = [0.25 * s, (r[0, 1] + r[1, 0]) / s, (r[0, 2] + r[2, 0]) / s, (r[2, 1] - r[1, 2]) / s]
    elif r[1, 1] > r[2, 2]:
        s = np.sqrt(1.0 + r[1, 1] - r[0, 0] - r[2, 2]) * 2
        q = [(r[0, 1] + r[1, 0]) / s, 0.25 * s, (r[1, 2] + r[2, 1]) / s, (r[0, 2] - r[2, 0]) / s]
    else:
        s = np.sqrt(1.0 + r[2, 2] - r[0, 0] - r[1, 1]) * 2
        q = [(r[0, 2] + r[2, 0]) / s, (r[1, 2] + r[2, 1]) / s, 0.25 * s, (r[1, 0] - r[0, 1]) / s]
    q = np.array(q)
    return q / np.linalg.norm(q)


def _to_trs(node):
    m = np.array(node["matrix"], np.float64).reshape(4, 4).T     # glTF matrices are column-major
    scale = np.linalg.norm(m[:3, :3], axis=0)
    if np.linalg.det(m[:3, :3]) <= 0 or (scale < 1e-12).any():
        return False                                               # mirrored: leave the matrix (never animated)
    del node["matrix"]
    node["translation"] = [float(x) for x in m[:3, 3]]
    node["rotation"] = [float(x) for x in _quat(m[:3, :3] / scale)]
    if not np.allclose(scale, 1, atol=1e-6):
        node["scale"] = [float(x) for x in scale]
    return True


def _continuous(q):
    """Flip quaternions into one hemisphere so linear interpolation takes the short way."""
    q = q / np.maximum(np.linalg.norm(q, axis=1, keepdims=True), 1e-12)
    for i in range(1, len(q)):
        if np.dot(q[i], q[i - 1]) < 0:
            q[i] = -q[i]
    return q


def add_animations(glb, clips, targets):
    """clips: {name: caf.Clip}; targets: {name hash: glTF node name}. Returns the new GLB bytes."""
    js, bin_ = _split(glb)
    nodes = js.get("nodes", [])
    index = {}
    for i, n in enumerate(nodes):
        index.setdefault(n.get("name"), i)
    trs_ok = {i for i, n in enumerate(nodes) if "matrix" not in n or _to_trs(n)}
    data = bytearray(bin_)
    views, accessors = js.setdefault("bufferViews", []), js.setdefault("accessors", [])

    def push(arr, typ, minmax=False):
        data.extend(b"\0" * (-len(data) % 4))
        raw = np.ascontiguousarray(arr, np.float32).tobytes()
        views.append({"buffer": 0, "byteOffset": len(data), "byteLength": len(raw)})
        data.extend(raw)
        acc = {"bufferView": len(views) - 1, "componentType": 5126, "count": int(len(arr)), "type": typ}
        if minmax:
            acc["min"], acc["max"] = [float(np.min(arr))], [float(np.max(arr))]
        accessors.append(acc)
        return len(accessors) - 1

    anims = []
    for name in sorted(clips):
        clip = clips[name]
        fps = clip.info.fps or 30
        channels, samplers = [], []
        for h, tr in clip.tracks.items():
            node = index.get(targets.get(h)) if h != ROOT_HASH else None
            if node is None or node not in trs_ok:
                continue
            for path, t, v in (("rotation", tr.rot_t, tr.rot), ("translation", tr.pos_t, tr.pos)):
                if t is None or not len(t):
                    continue
                times = np.maximum((np.asarray(t, np.float64) - clip.info.start) / fps, 0.0)
                vals = _continuous(np.asarray(v, np.float64)) if path == "rotation" else np.asarray(v)
                samplers.append({"input": push(times, "SCALAR", True),
                                 "output": push(vals, "VEC4" if path == "rotation" else "VEC3"),
                                 "interpolation": "LINEAR"})
                channels.append({"sampler": len(samplers) - 1, "target": {"node": node, "path": path}})
        if channels:
            anims.append({"name": name, "channels": channels, "samplers": samplers})
    if anims:
        js["animations"] = js.get("animations", []) + anims
    if not js.get("buffers"):
        js["buffers"] = [{}]
    js["buffers"][0]["byteLength"] = len(data)
    return _join(js, bytes(data))
