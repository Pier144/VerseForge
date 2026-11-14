"""Reader for compiled #ivo animation clips (.caf). The same track blocks are packed inside .dba databases.

Tracks are keyed by the CRC32 of the exact bone/node name; values are parent-relative (glTF-style local TRS),
rotations as xyzw quaternions."""
import math
import struct
from dataclasses import dataclass, field

import numpy as np

ANIM_INFO = 0x4733C6ED
CAF_DATA = 0xA9496CB5
ROOT_HASH = 0x16F4F95B          # locator track that moves the whole object: never applied


@dataclass
class ClipInfo:
    flags: int
    fps: int
    n_bones: int
    start: int
    end: int

    @property
    def additive(self):
        return bool(self.flags & 1)

    @property
    def duration(self):
        return (self.end - self.start) / self.fps if self.fps else 0.0

    @property
    def pose(self):
        return self.end - self.start <= 1          # a single key (some poses store two identical frames)


@dataclass
class Track:
    rot_t: np.ndarray | None = None      # (n,) frames
    rot: np.ndarray | None = None        # (n, 4) xyzw
    pos_t: np.ndarray | None = None
    pos: np.ndarray | None = None        # (n, 3)


@dataclass
class Clip:
    info: ClipInfo
    tracks: dict = field(default_factory=dict)     # name hash -> Track


def info_from(data, off):
    flags, fps, nb, _, start, end = struct.unpack_from("<IHHIII", data, off)
    return ClipInfo(flags, fps, nb, start, end)


def _quat48(b, o):
    m1, m2, m3 = struct.unpack_from("<3H", b, o)
    comp = (m3 << 32) | (m2 << 16) | m1
    idx = comp >> 46
    res = [0.0] * 4
    shift = 0
    s = 0.0
    for i in range(4):
        if i == idx:
            continue
        v = (((comp >> shift) & 0x7FFF) - 16383.0) / 23170.0
        res[i] = v
        s += v * v
        shift += 15
    res[idx] = math.sqrt(max(0.0, 1.0 - s))
    return res


def _times(b, o, n, fmt):
    if fmt == 0x40:
        return list(b[o:o + n])
    if fmt == 0x41:
        return list(struct.unpack_from("<%dH" % n, b, o))
    if fmt == 0x42:
        start, end = struct.unpack_from("<2H", b, o)
        nbits = end - start + 1
        bits = b[o + 4:o + 4 + (nbits + 7) // 8]
        out = [start + i for i in range(nbits) if bits[i >> 3] >> (i & 7) & 1]
        if len(out) != n:
            raise ValueError(f"key bitmask has {len(out)} keys, expected {n}")
        return out
    raise ValueError(f"unknown key time format 0x{fmt:x}")


def _rots(b, o, n, fmt):
    if fmt == 0x82:
        return [_quat48(b, o + 6 * i) for i in range(n)]
    if fmt == 0x80:
        return [list(struct.unpack_from("<4f", b, o + 16 * i)) for i in range(n)]
    raise ValueError(f"unknown rotation format 0x{fmt:x}")


def _poss(b, o, n, fmt):
    if fmt == 0xC0:
        return [list(struct.unpack_from("<3f", b, o + 12 * i)) for i in range(n)]
    if fmt in (0xC1, 0xC2):
        hdr = struct.unpack_from("<6f", b, o)
        scale, off = hdr[:3], hdr[3:]
        active = [k for k in range(3) if scale[k] < 1e30]     # FLT_MAX scale = axis does not move
        # u16 per moving axis: 0xC1 stores them key by key (x0 z0 x1 z1...), 0xC2 axis by axis (x0 x1... z0 z1...).
        # With a single moving axis both read the same; read the wrong way, a two-axis track jumps half-way
        # (Perseus legs: flat for half the keys, then a 4 m jump)
        raw = np.frombuffer(b, np.uint16, n * len(active), o + 24).astype(np.float64)
        raw = raw.reshape(n, len(active)) if fmt == 0xC1 else raw.reshape(len(active), n).T
        out = np.tile(np.asarray(off, np.float64), (n, 1))
        for j, k in enumerate(active):
            out[:, k] = off[k] + raw[:, j] * scale[k]
        return out.tolist()
    raise ValueError(f"unknown position format 0x{fmt:x}")


def read_block(data, c, info):
    """Tracks of the #caf / #dba block at offset c (offsets inside are relative to each bone descriptor)."""
    if data[c:c + 4] not in (b"#caf", b"#dba"):
        raise ValueError("animation block marker not found")
    nb = struct.unpack_from("<H", data, c + 4)[0]
    hashes = struct.unpack_from("<%dI" % nb, data, c + 12)
    blk = c + 12 + 4 * nb
    tracks, skipped = {}, []
    for i in range(nb):
        base = blk + 24 * i
        tr = Track()
        for kind, eo in (("rot", 0), ("pos", 12)):
            n, f, to, do = struct.unpack_from("<HHII", data, base + eo)
            if n == 0:
                continue
            try:
                t = np.array(_times(data, base + to, n, f & 0xFF), np.float32)
                if kind == "rot":
                    tr.rot_t, tr.rot = t, np.array(_rots(data, base + do, n, f >> 8), np.float32)
                else:
                    tr.pos_t, tr.pos = t, np.array(_poss(data, base + do, n, f >> 8), np.float32)
            except ValueError:
                # a key format not decoded yet (e.g. rotation 0x83, seen only in character clips): that track
                # keeps its rest pose, the rest of the clip still plays
                skipped.append(hashes[i])
        tracks[hashes[i]] = tr
    return Clip(info, tracks)


def _chunks(data):
    if data[:4] != b"#ivo":
        raise ValueError("not an #ivo file")
    count, table = struct.unpack_from("<II", data, 8)
    return {struct.unpack_from("<I", data, table + 16 * i)[0]: struct.unpack_from("<Q", data, table + 16 * i + 8)[0]
            for i in range(count)}


def header(data):
    ch = _chunks(data)
    if ANIM_INFO not in ch:
        raise ValueError("animation info chunk missing")
    return info_from(data, ch[ANIM_INFO])


def reversed_clip(clip):
    """The same clip played backwards (keys mirrored in time)."""
    total = clip.info.start + clip.info.end
    tracks = {}
    for h, tr in clip.tracks.items():
        tracks[h] = Track(None if tr.rot_t is None else (total - tr.rot_t)[::-1].copy(),
                          None if tr.rot is None else tr.rot[::-1].copy(),
                          None if tr.pos_t is None else (total - tr.pos_t)[::-1].copy(),
                          None if tr.pos is None else tr.pos[::-1].copy())
    return Clip(clip.info, tracks)


def block_hashes(data, c):
    """Name hashes of the bones/nodes a #caf/#dba block animates, without decoding the keys."""
    nb = struct.unpack_from("<H", data, c + 4)[0]
    return struct.unpack_from("<%dI" % nb, data, c + 12)


def hashes(data):
    ch = _chunks(data)
    return block_hashes(data, ch[CAF_DATA]) if CAF_DATA in ch else ()


def read(data):
    ch = _chunks(data)
    if ANIM_INFO not in ch or CAF_DATA not in ch:
        raise ValueError("not a compiled animation")
    return read_block(data, ch[CAF_DATA], info_from(data, ch[ANIM_INFO]))
