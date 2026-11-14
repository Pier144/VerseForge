"""Object containers (.socpak): the interiors of ships (rooms, corridors, props) placed by the vehicle record.

A .socpak is a zip. Its main <name>.soc is a CryEngine chunk file ('CrCh') with:
- chunk 0x10 "IncludedObjects": the list of geometry files, then the placed brushes. Each brush record (type 1)
  holds a world bounding box, the index of its geometry and a 3x4 row-major [rotation | position] matrix (doubles);
- chunk 0x4: a CryXmlB <Entities> list. GeomEntity entities carry a geometry path; the others (doors, lockers,
  screens, ...) name an entity class whose geometry comes from DataCore (EntityClassGUID).
Positions are in the container's space; the vehicle record mounts each container on a hull bone / offset."""
import io
import math
import struct
import zipfile
from dataclasses import dataclass

import numpy as np

from . import cryxml

CHUNK_OBJECTS = 0x10
CHUNK_ENTITIES = 0x4
STR_LEN = 256
GEOMETRY_EXT = (".cgf", ".cga", ".cdf", ".skin", ".chr")


@dataclass
class Placement:
    geometry: str           # path relative to Data/
    matrix: np.ndarray      # 4x4, container space
    material: str = ""      # material override (entities), "" = the geometry's own
    kind: str = "brush"     # "brush" | "entity"


def _data_path(p):
    p = (p or "").replace("\\", "/")
    return p[5:] if p.lower().startswith("data/") else p


def _chunks(d):
    if d[:4] != b"CrCh":
        raise ValueError("not a CrCh chunk file")
    _, _, count, table = struct.unpack_from("<4sIII", d, 0)
    out = []
    for i in range(count):
        typ, ver, cid, size, off = struct.unpack_from("<HHIII", d, table + 16 * i)
        out.append((typ, ver, off, size))
    return out


def _brushes(d, off, size):
    """Placed geometry of an IncludedObjects chunk -> [Placement]."""
    end = off + size
    p = off + 4
    n = struct.unpack_from("<I", d, p)[0]
    p += 4
    cgfs = [d[p + STR_LEN * i:p + STR_LEN * (i + 1)].split(b"\0")[0].decode("utf-8", "replace") for i in range(n)]
    p += STR_LEN * n
    n_mtl, n_pal = struct.unpack_from("<HH", d, p)
    p += 4 + STR_LEN * (n_mtl + n_pal) + 28 + 4
    out = []
    # records vary in length (unknown trailing fields): scan 4-byte steps for type-1 records whose values make sense
    while p + 168 <= end:
        if struct.unpack_from("<I", d, p)[0] != 1:
            p += 4
            continue
        lo = struct.unpack_from("<3d", d, p + 4)
        hi = struct.unpack_from("<3d", d, p + 28)
        gid = struct.unpack_from("<H", d, p + 60)[0]
        m = np.array(struct.unpack_from("<12d", d, p + 64)).reshape(3, 4)
        ok = (gid < len(cgfs) and np.isfinite(m).all() and all(math.isfinite(v) and abs(v) < 1e5 for v in lo + hi)
              and all(a <= b + 1e-3 for a, b in zip(lo, hi)))
        if ok:
            scale = np.linalg.norm(m[:, :3], axis=0)
            ok = bool((scale > 1e-3).all() and (scale < 1e3).all())
        if not ok:
            p += 4
            continue
        mat = np.eye(4)
        mat[:3, :4] = m
        geo = _data_path(cgfs[gid])
        if geo.lower().endswith(GEOMETRY_EXT):
            out.append(Placement(geo, mat))
        p += 168
    return out


def _ang3_matrix(rx, ry, rz):
    """CryEngine Ang3 (degrees, applied Z * Y * X) -> 3x3."""
    x, y, z = (math.radians(a) for a in (rx, ry, rz))
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    rxm = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    rym = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rzm = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rzm @ rym @ rxm


def _quat_matrix(w, x, y, z):
    n = w * w + x * x + y * y + z * z
    if n < 1e-12:
        return np.eye(3)
    s = 2.0 / n
    return np.array([[1 - s * (y * y + z * z), s * (x * y - z * w), s * (x * z + y * w)],
                     [s * (x * y + z * w), 1 - s * (x * x + z * z), s * (y * z - x * w)],
                     [s * (x * z - y * w), s * (y * z + x * w), 1 - s * (x * x + y * y)]])


def _floats(text, n, default):
    try:
        v = [float(x) for x in (text or "").split(",")]
        return v if len(v) == n else default
    except ValueError:
        return default


def entity_matrix(e):
    """Pos / Rotate (quaternion w,x,y,z) / Scale of an <Entity> -> 4x4."""
    pos = _floats(e.get("Pos"), 3, [0.0, 0.0, 0.0])
    rot = _floats(e.get("Rotate"), 4, [1.0, 0.0, 0.0, 0.0])
    scl = _floats(e.get("Scale"), 3, [1.0, 1.0, 1.0])
    m = np.eye(4)
    m[:3, :3] = _quat_matrix(*rot) * np.array(scl)
    m[:3, 3] = pos
    return m


def _entities(d, off, size, classes):
    """Entities with geometry -> [Placement]. classes: {entity class GUID (lower): geometry path} from DataCore."""
    try:
        root = cryxml.parse(d[off:off + size])
    except Exception:
        return []
    out = []
    for e in root.iter("Entity"):
        geo = ""
        # inline geometry (GeomEntity: PropertiesDataCore/EntityGeometryResource/.../Geometry path="...")
        for el in e.iter():
            path = el.get("path") or ""
            if path.lower().endswith(GEOMETRY_EXT):
                geo = path
                break
        if not geo:
            geo = (classes or {}).get((e.get("EntityClassGUID") or "").lower(), "")
        mtl = e.get("Material") or ""
        geo = _data_path(geo)
        if geo and geo.lower().endswith(GEOMETRY_EXT):
            out.append(Placement(geo, entity_matrix(e), _data_path(mtl), "entity"))
    return out


def read(archive, socpak, classes=None):
    """Placements of a .socpak's main object container (container space). Missing file -> []."""
    p = _data_path(socpak)
    if not archive.exists(p):
        return []
    z = zipfile.ZipFile(io.BytesIO(archive.read(p)))
    stem = p.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    names = {n.lower(): n for n in z.namelist()}
    main = names.get(f"{stem}.soc".lower())
    if main is None:
        return []
    d = z.read(main)
    out = []
    for typ, ver, off, size in _chunks(d):
        if typ == CHUNK_OBJECTS:
            out += _brushes(d, off, size)
        elif typ == CHUNK_ENTITIES and d[off:off + 7] == b"CryXmlB":
            out += _entities(d, off, size, classes)
    return out


def mount_matrix(c, bone_world=None):
    """Container placement on the hull: the hull bone it names when present, else its Offset (QuatT)."""
    if bone_world is not None:
        return np.asarray(bone_world, np.float64)
    m = np.eye(4)
    m[:3, :3] = _ang3_matrix(*c.get("rot", (0.0, 0.0, 0.0)))
    m[:3, 3] = c.get("pos", (0.0, 0.0, 0.0))
    return m
