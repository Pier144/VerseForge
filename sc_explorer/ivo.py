"""Parser for Star Citizen '#ivo' geometry files (.cgf/.cga/.skin/.chr and their *m mesh companions)."""
import struct
from dataclasses import dataclass, field

import numpy as np

MESH_INFO = 0x92914444
MESH_DATA = 0xB8757777
MTL_NAME = 0x83353333
NODES = 0x70697FDA
BONES = 0xC2011111

S_INDICES = 0xEECDC168
S_VERTS_FLOAT = 0x91329AE9      # float3 position, color, half2 uv (20 bytes)
S_VERTS_SNORM = 0xB3A70D5E      # snorm16x4 position, color, half2 uv (16 bytes)
KNOWN_STREAMS = {S_INDICES, S_VERTS_FLOAT, S_VERTS_SNORM, 0xB95E9A1B, 0x6ECA3708, 0x9CF3F615, 0x38A581FE,
                 0x677C7B23, 0xD9EED421, 0xEE057252, 0x9D51C5EE}


class IvoError(Exception):
    pass


class IvoFile:
    def __init__(self, data: bytes):
        if data[:4] != b"#ivo":
            raise IvoError("not an #ivo file")
        self.data = data
        count, table = struct.unpack_from("<II", data, 8)
        entries = [struct.unpack_from("<IIQ", data, table + 16 * i) for i in range(count)]
        offsets = sorted(e[2] for e in entries) + [len(data)]
        self.chunks = {}
        for typ, ver, off in entries:
            end = min(o for o in offsets if o > off) if any(o > off for o in offsets) else len(data)
            self.chunks.setdefault(typ, (ver, off, end - off))

    def chunk(self, typ):
        return self.chunks.get(typ)


@dataclass
class Node:
    name: str
    world: np.ndarray            # 3x4 object-space transform
    parent: int
    kind: int                    # 0 = mesh, 2 = helper


@dataclass
class Subset:
    material: int
    node: int
    first_index: int
    num_indices: int
    first_vertex: int
    vertex_base: int
    num_vertices: int


@dataclass
class MeshData:
    positions: np.ndarray
    uvs: np.ndarray | None
    indices: np.ndarray
    subsets: list = field(default_factory=list)


def material_name(ivo: IvoFile):
    c = ivo.chunk(MTL_NAME)
    if not c:
        return None
    raw = ivo.data[c[1]:c[1] + min(c[2], 256)]
    return raw.split(b"\0", 1)[0].decode("utf-8", "replace") or None


def nodes(ivo: IvoFile):
    c = ivo.chunk(NODES)
    if not c:
        return []
    d, o = ivo.data, c[1]
    _, n_nodes, _n_meshes, n_extra, n_subsets, str_size, _, _ = struct.unpack_from("<8I", d, o)
    base = o + 64
    names_at = base + 208 * n_nodes + 2 * n_extra + 2 * n_subsets
    names = d[names_at:names_at + str_size].split(b"\0") if str_size else []
    out = []
    for i in range(n_nodes):
        r = base + 208 * i
        world = np.array(struct.unpack_from("<12f", d, r), np.float64).reshape(3, 4)
        _, _, _, parent, kind = struct.unpack_from("<I4H", d, r + 108)
        name = names[i].decode("utf-8", "replace") if i < len(names) else f"node{i}"
        out.append(Node(name, world, -1 if parent in (0xFFFF, n_nodes) or i == 0 else parent, kind))
    return out


def mesh(ivo: IvoFile, node_space=False) -> MeshData | None:
    """node_space: snorm positions are decoded in the space of their node (second bounding box of the header,
    the union of the node-local boxes), to be placed by the node transforms. Needed for multi-node .cga such as
    large ships; LOD files without a node table use the first (object space) box."""
    c = ivo.chunk(MESH_DATA)
    if not c:
        return None
    d, o, end = ivo.data, c[1], c[1] + c[2]
    _, _, nv, ni, ns, _ = struct.unpack_from("<6I", d, o)
    bmin = np.array(struct.unpack_from("<3f", d, o + 24))
    bmax = np.array(struct.unpack_from("<3f", d, o + 36))
    if node_space:
        lmin = np.array(struct.unpack_from("<3f", d, o + 48))
        lmax = np.array(struct.unpack_from("<3f", d, o + 60))
        if (lmax >= lmin).all() and (lmax > lmin).any():
            bmin, bmax = lmin, lmax
    p = o + 168
    subsets = []
    for _ in range(ns):
        mat_node, fi, nidx, fv, vbase, nvs = struct.unpack_from("<6I", d, p)
        subsets.append(Subset(mat_node & 0xFFFF, mat_node >> 16, fi, nidx, fv, vbase, nvs))
        p += 48
    indices = positions = uvs = None
    while p + 8 <= end:
        typ, bpe = struct.unpack_from("<II", d, p)
        if typ not in KNOWN_STREAMS:
            # some files pad the stream table to 16 bytes (or more): look ahead for the next known stream marker
            nxt = next((q for q in range(p + 4, min(p + 128, end - 8), 4)
                        if struct.unpack_from("<I", d, q)[0] in KNOWN_STREAMS), None)
            if nxt is None:
                break
            p = nxt
            continue
        if bpe == 0 or bpe > 64:
            break
        count = ni if typ == S_INDICES else nv
        if p + 8 + count * bpe > end:
            break
        if typ == S_INDICES:
            indices = np.frombuffer(d, np.uint16 if bpe == 2 else np.uint32, count, p + 8).astype(np.int64)
        elif typ == S_VERTS_FLOAT and positions is None:
            a = np.frombuffer(d, np.uint8, count * bpe, p + 8).reshape(count, bpe)
            positions = a[:, :12].copy().view(np.float32).astype(np.float64)
            if bpe >= 20:
                uvs = a[:, 16:20].copy().view(np.float16).astype(np.float32)
        elif typ == S_VERTS_SNORM and positions is None:
            a = np.frombuffer(d, np.uint8, count * bpe, p + 8).reshape(count, bpe)
            raw = a[:, :6].copy().view(np.int16).astype(np.float64) / 32767.0
            scale = np.maximum(np.abs(bmax - bmin) / 2.0, 1.0)
            positions = raw * scale + (bmin + bmax) / 2.0
            if bpe >= 16:
                uvs = a[:, 12:16].copy().view(np.float16).astype(np.float32)
        p += 8 + count * bpe
        p += (-p) % 8
    if indices is None or positions is None:
        raise IvoError("mesh streams not found (unsupported vertex format)")
    return MeshData(positions, uvs, indices, subsets)


S_BONEMAP = 0x677C7B23           # 4 x u16 bone index + 4 x u8 weight (12 bytes)


def vertex_bones(ivo: IvoFile):
    """Dominant bone index per vertex of a skinned mesh (indices into the .skin's own bone list), or None."""
    c = ivo.chunk(MESH_DATA)
    if not c:
        return None
    d, o, end = ivo.data, c[1], c[1] + c[2]
    _, _, nv, ni, ns, _ = struct.unpack_from("<6I", d, o)
    p = o + 168 + 48 * ns
    while p + 8 <= end:
        typ, bpe = struct.unpack_from("<II", d, p)
        if typ not in KNOWN_STREAMS:
            nxt = next((q for q in range(p + 4, min(p + 128, end - 8), 4)
                        if struct.unpack_from("<I", d, q)[0] in KNOWN_STREAMS), None)
            if nxt is None:
                return None
            p = nxt
            continue
        count = ni if typ == S_INDICES else nv
        if typ == S_BONEMAP and bpe == 12:
            a = np.frombuffer(d, np.uint8, count * 12, p + 8).reshape(count, 12)
            idx = a[:, :8].copy().view(np.uint16)
            return idx[np.arange(count), a[:, 8:12].argmax(1)].astype(np.int64)
        p += 8 + count * bpe
        p += (-p) % 8
    return None


def bones(ivo: IvoFile):
    """Compiled skeleton: list of dicts with name, parent, world quaternion (xyzw) and position."""
    c = ivo.chunk(BONES)
    if not c:
        return []
    d, o, size = ivo.data, c[1], c[2]
    n = struct.unpack_from("<I", d, o)[0]
    if n == 0 or 4 + 68 * n > size:
        return []
    b = o + 4
    names = d[b + 68 * n:o + size].split(b"\0")
    out = []
    for i in range(n):
        r = struct.unpack_from("<IIi4f3f4f3f", d, b + 68 * i)
        out.append({"name": names[i].decode("utf-8", "replace") if i < len(names) else f"bone{i}",
                    "parent": r[2], "wq": np.array(r[10:14]), "wp": np.array(r[14:17])})
    return out
