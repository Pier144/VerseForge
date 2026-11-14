"""Reader for #ivo animation databases (.dba): many clips packed in one file, used by ships and vehicles.

Layout: chunk META = u32 count, u32 (unused), count x 48-byte entries (same fields as the .caf info chunk, then a
quaternion and a position), then the original .caf paths, NUL separated, in entry order. Chunk BLOCKS = the
"#dba" track blocks back to back, each 12 + 28 x bones bytes, with the same layout as a .caf "#caf" block."""
import struct

from . import caf

META = 0xF7351608
BLOCKS = 0x194FBC50


def entries(data):
    """[(lowercase .caf path, ClipInfo, block offset)] in file order."""
    ch = caf._chunks(data)
    if META not in ch or BLOCKS not in ch:
        raise ValueError("not an animation database")
    meta = ch[META]
    n = struct.unpack_from("<I", data, meta)[0]
    infos = [caf.info_from(data, meta + 8 + 48 * i) for i in range(n)]
    names = data[meta + 8 + 48 * n:].split(b"\0")[:n]
    c = data.find(b"#dba", ch[BLOCKS], ch[BLOCKS] + 64)
    if c < 0:
        raise ValueError("animation database blocks not found")
    out = []
    for name, info in zip(names, infos):
        if data[c:c + 4] != b"#dba":
            raise ValueError(f"animation database block {len(out)} misplaced")
        out.append((name.decode("utf-8", "replace").replace("\\", "/").lower(), info, c))
        c += 12 + 28 * struct.unpack_from("<H", data, c + 4)[0]
    return out


def headers(data):
    return {name: info for name, info, _ in entries(data)}


def read(data, name):
    name = name.replace("\\", "/").lower()
    for n, info, off in entries(data):
        if n == name:
            return caf.read_block(data, off, info)
    raise KeyError(name)
