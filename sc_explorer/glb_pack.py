"""Smaller viewer GLB: quantized vertex data (KHR_mesh_quantization) packed with meshoptimizer
(EXT_meshopt_compression, sc_explorer/meshopt.py); three.js's GLTFLoader reads both (MeshoptDecoder, vendored).

Only the viewer's lite GLB goes through here; exports stay plain float glTF.
- positions -> normalized int16 on one grid per parent node (meshes hanging from the same node share it, so seams
  between materials stay closed), centred on the node's origin; the node gets the scale back in its matrix. Grids
  coarser than `max_step` metres keep floats.
- UVs in 0..1 (or -1..1) -> normalized uint16 (int16): finer than the game's own half floats.
- indices -> uint16 when the mesh has fewer than 65,536 vertices."""
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from . import meshopt
from .anim_glb import _join, _split

FLOAT, SHORT, USHORT, UINT = 5126, 5122, 5123, 5125
EXT = "KHR_mesh_quantization"
MESHOPT = "EXT_meshopt_compression"
_SIZE = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
_COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
MAX_STEP = 0.002          # metres: coarsest position grid allowed (1 mm worst error)


def _node_matrix(n):
    if "matrix" in n:
        return np.array(n["matrix"], np.float64).reshape(4, 4).T
    m = np.eye(4)
    x, y, z, w = n.get("rotation", (0, 0, 0, 1))
    m[:3, :3] = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                 [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                 [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    m[:3, :3] *= np.asarray(n.get("scale", (1, 1, 1)), np.float64)
    m[:3, 3] = n.get("translation", (0, 0, 0))
    return m


def pack(glb, max_step=MAX_STEP, compress=True):
    js, bin_ = _split(glb)
    acc, views, nodes = js.get("accessors", []), js.get("bufferViews", []), js.get("nodes", [])
    users = {}
    for a in acc:
        if "bufferView" in a:
            users[a["bufferView"]] = users.get(a["bufferView"], 0) + 1
    anim_nodes = {c["target"].get("node") for an in js.get("animations", []) for c in an.get("channels", [])}

    def read(i, dtype, width):
        a = acc[i]
        v = views[a["bufferView"]]
        if a["componentType"] != FLOAT or v.get("byteStride") or users[a["bufferView"]] != 1:
            return None
        o = v.get("byteOffset", 0) + a.get("byteOffset", 0)
        return np.frombuffer(bin_, dtype, a["count"] * width, o).reshape(-1, width)

    new = {}          # bufferView -> (bytes, byteStride | None)
    quant = False

    # indices and UVs: per accessor
    for mesh in js.get("meshes", []):
        for prim in mesh["primitives"]:
            ia = prim.get("indices")
            if ia is not None and acc[ia]["componentType"] == UINT and acc[ia].get("max", [1 << 16])[0] < 65536 \
                    and users[acc[ia]["bufferView"]] == 1:
                a, v = acc[ia], views[acc[ia]["bufferView"]]
                idx = np.frombuffer(bin_, np.uint32, a["count"], v.get("byteOffset", 0) + a.get("byteOffset", 0))
                new[a["bufferView"]] = (idx.astype(np.uint16).tobytes(), None)
                a["componentType"] = USHORT
            for name in ("TEXCOORD_0", "_UV2"):
                i = prim["attributes"].get(name)
                if i is None or acc[i]["bufferView"] in new:
                    continue
                uv = read(i, np.float32, 2)
                if uv is None or not len(uv):
                    continue
                lo, hi = float(uv.min()), float(uv.max())
                if lo >= 0 and hi <= 1:
                    q, ct = np.round(uv * 65535.0).astype(np.uint16), USHORT
                elif lo >= -1 and hi <= 1:
                    q, ct = np.round(uv * 32767.0).astype(np.int16), SHORT
                    quant = True
                else:
                    continue
                a = acc[i]
                new[a["bufferView"]] = (q.tobytes(), None)
                a.update(componentType=ct, normalized=True)
                a["min"] = [int(x) for x in q.min(0)]
                a["max"] = [int(x) for x in q.max(0)]

    # positions: one grid per parent node. trimesh shares the arrays of identical parts between meshes, so an
    # accessor is quantized only when every node drawing it uses the same grid, and a node only when all of its
    # positions are quantized
    parent = {c: p for p, n in enumerate(nodes) for c in n.get("children", [])}
    mesh_nodes = {}
    for ni, n in enumerate(nodes):
        if "mesh" in n:
            mesh_nodes.setdefault(n["mesh"], []).append(ni)
    node_pos = {ni: [pr["attributes"]["POSITION"] for pr in js["meshes"][n["mesh"]]["primitives"]
                     if "POSITION" in pr["attributes"]] for ni, n in enumerate(nodes) if "mesh" in n}
    pos_nodes = {}
    for ni, ps in node_pos.items():
        for i in ps:
            pos_nodes.setdefault(i, set()).add(ni)
    ok_node = {ni for ni, n in enumerate(nodes) if "mesh" in n and len(mesh_nodes[n["mesh"]]) == 1
               and ni not in anim_nodes and not n.get("children")}      # instanced or animated: leave alone
    while True:
        bad = {i for i, ns in pos_nodes.items()
               if not ns <= ok_node or len({parent.get(ni, -1) for ni in ns}) != 1 or read(i, np.float32, 3) is None}
        drop = {ni for ni in ok_node if any(i in bad for i in node_pos[ni])}
        if not drop:
            break
        ok_node -= drop
    groups = {}
    for ni in sorted(ok_node):
        groups.setdefault(parent.get(ni, -1), []).append(ni)
    for members in groups.values():
        prims = sorted({i for ni in members for i in node_pos[ni]})
        if not prims:
            continue
        lo = np.min([acc[i]["min"] for i in prims], 0)
        hi = np.max([acc[i]["max"] for i in prims], 0)
        # centred on the node's own origin: the node keeps its position (three.js sorts transparent meshes by it, an
        # offset changed which glass is drawn first) and only gains a uniform scale
        half = float(max(np.abs(lo).max(), np.abs(hi).max()))
        if half <= 0 or half / 32767.0 > max_step:
            continue
        center = np.zeros(3)
        deq = np.eye(4)
        deq[:3, :3] *= half
        for i in prims:
            p = read(i, np.float32, 3)
            q = np.zeros((len(p), 4), np.int16)
            q[:, :3] = np.clip(np.round((p - center) / half * 32767.0), -32767, 32767)
            a = acc[i]
            new[a["bufferView"]] = (q.tobytes(), 8)
            a.update(componentType=SHORT, normalized=True)
            a["min"] = [int(x) for x in q[:, :3].min(0)]
            a["max"] = [int(x) for x in q[:, :3].max(0)]
        for ni in members:
            n = nodes[ni]
            m = _node_matrix(n) @ deq
            for k in ("translation", "rotation", "scale"):
                n.pop(k, None)
            n["matrix"] = [float(x) for x in m.T.ravel()]
        quant = True

    if not new and not compress:
        return glb
    for a in acc:
        if a.get("bufferView") in new:
            a.pop("byteOffset", None)
    # mesh views meshopt can take: vertex streams (stride a multiple of 4) and triangle indices
    codec = {}
    if compress:
        for mesh in js.get("meshes", []):
            for prim in mesh["primitives"]:
                for i in list(prim["attributes"].values()) + [prim.get("indices")]:
                    if i is None or "bufferView" not in acc[i] or users[acc[i]["bufferView"]] != 1:
                        continue
                    a = acc[i]
                    size = _SIZE[a["componentType"]]
                    if i == prim.get("indices"):
                        if a.get("max", [1 << 30])[0] < (1 << 30):
                            codec[a["bufferView"]] = ("INDICES", size, a["count"])
                    else:
                        stride = views[a["bufferView"]].get("byteStride") or new.get(a["bufferView"], (0, 0))[1]                             or size * _COMPONENTS[a["type"]]
                        if stride % 4 == 0 and stride <= 256:
                            codec[a["bufferView"]] = ("ATTRIBUTES", stride, a["count"])
    # rebuild the binary chunk with every view 4-byte aligned; compressed views keep their place in a fallback
    # buffer without data (buffer 1), their bytes go to the GLB chunk
    datas = {}
    for vi, v in enumerate(views):
        if v.get("buffer", 0) != 0:
            continue
        data, stride = new.get(vi, (None, None))
        if data is None:
            o = v.get("byteOffset", 0)
            data = bin_[o:o + v["byteLength"]]
        elif stride:
            v["byteStride"] = stride
        datas[vi] = data

    encoded = {}
    if codec:
        idx = [vi for vi in codec if codec[vi][0] == "INDICES"]
        att = [vi for vi in codec if codec[vi][0] == "ATTRIBUTES"]
        encoded.update(zip(idx, meshopt.encode_index_sequences(
            [np.frombuffer(datas[vi], np.uint16 if codec[vi][1] == 2 else np.uint32, codec[vi][2]) for vi in idx])))
        # numpy lets go of the GIL in its loops: chunks of blocks encode side by side
        with ThreadPoolExecutor(max(1, min(8, (os.cpu_count() or 2) - 1))) as pool:
            encoded.update(zip(att, meshopt.encode_vertex_buffers(
                [(datas[vi][:codec[vi][2] * codec[vi][1]], codec[vi][1]) for vi in att], pool)))
    out, off, foff = [], 0, 0
    for vi, data in datas.items():
        v = views[vi]
        if vi in encoded:
            mode, st, count = codec[vi]
            enc = encoded[vi]
            v.update(buffer=1, byteOffset=foff, byteLength=len(data))
            v["extensions"] = {MESHOPT: {"buffer": 0, "byteOffset": off, "byteLength": len(enc), "byteStride": st,
                                         "count": count, "mode": mode}}
            foff += len(data) + (-len(data) % 4)
            data = enc
        else:
            v["byteOffset"], v["byteLength"] = off, len(data)
        out.append(data)
        pad = -len(data) % 4
        if pad:
            out.append(bytes(pad))
        off += len(data) + pad
    js["buffers"][0]["byteLength"] = off
    exts = ({EXT} if quant else set()) | ({MESHOPT} if codec else set())
    if codec:
        js["buffers"].append({"byteLength": foff, "extensions": {MESHOPT: {"fallback": True}}})
    if exts:
        for key in ("extensionsUsed", "extensionsRequired"):
            js[key] = sorted(set(js.get(key, [])) | exts)
    return _join(js, b"".join(out))
