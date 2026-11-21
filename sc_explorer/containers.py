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
import zlib
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


def _main_soc(archive, socpak):
    """Bytes of a .socpak's main <name>.soc, or None."""
    p = _data_path(socpak)
    if not archive.exists(p):
        return None
    z = zipfile.ZipFile(io.BytesIO(archive.read(p)))
    stem = p.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    names = {n.lower(): n for n in z.namelist()}
    main = names.get(f"{stem}.soc".lower())
    return z.read(main) if main is not None else None


# ------------------------------------------------------------------ rooms
@dataclass
class Room:
    """A room of the ship as the game defines it (Room_RN entity: atmosphere, audio, map). Its extent is the
    GenericShape areas that name it: boxes, outlines pulled up to a height, or closed meshes."""
    guid: str
    name: str                # entity name (Room_RN_habs_bunks)
    label: str = ""          # localisation key of the name the game shows ("@vehicle_room_crew"), often missing
    volumes: list = None     # [(4x4 container space -> shape space, "box" | "shape" | "mesh", data, volume m3)]

    def centre(self):
        """Middle of the largest volume, container space (None without volumes)."""
        if not self.volumes:
            return None
        inv, kind, data, _ = max(self.volumes, key=lambda v: v[3])
        if kind == "box":
            c = (np.asarray(data[0]) + np.asarray(data[1])) / 2
        elif kind == "mesh":
            c = (data.reshape(-1, 3).min(0) + data.reshape(-1, 3).max(0)) / 2
        else:
            pts, h = data
            c = np.array([*np.mean(pts, axis=0), h / 2])
        m = np.linalg.inv(inv)
        return m[:3, :3] @ c + m[:3, 3]


def _quat_t(text):
    """'Q : w,x,y,z | T : x,y,z' -> 4x4."""
    m = np.eye(4)
    try:
        q, t = (part.split(":", 1)[1] for part in (text or "").split("|"))
        m[:3, :3] = _quat_matrix(*[float(x) for x in q.split(",")])
        m[:3, 3] = [float(x) for x in t.split(",")]
    except (IndexError, ValueError, TypeError):
        return np.eye(4)
    return m


def _inside_polygon(pts, x, y):
    inside = False
    n = len(pts)
    for i in range(n):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            inside = not inside
    return inside


_RAY = np.array([0.5377, 0.2913, 0.7912])      # no wall of a ship runs exactly along this direction


def _inside_mesh(tris, p):
    """Is p inside the closed triangle mesh? A ray from p crosses its surface an odd number of times."""
    a, e1, e2 = tris[:, 0], tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]
    h = np.cross(_RAY, e2)
    det = (e1 * h).sum(1)
    ok = np.abs(det) > 1e-12
    inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
    s = p - a
    u = (s * h).sum(1) * inv
    q = np.cross(s, e1)
    v = (q @ _RAY) * inv
    t = (e2 * q).sum(1) * inv
    return int((ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-9)).sum()) % 2 == 1


def rooms(archive, socpak):
    """The rooms of a .socpak's main container with their volumes (container space). No room data -> []."""
    d = _main_soc(archive, socpak)
    if d is None:
        return []
    out = {}
    shapes = []
    for typ, ver, off, size in _chunks(d):
        if typ != CHUNK_ENTITIES or d[off:off + 7] != b"CryXmlB":
            continue
        try:
            root = cryxml.parse(d[off:off + size])
        except Exception:
            continue
        for e in root.iter("Entity"):
            cls = (e.get("EntityClass") or "").lower()
            guid = (e.get("EntityCryGUID") or "").lower()
            if cls.startswith("room") and "connector" not in cls and guid:
                comp = e.find("PropertiesDataCore/EntityComponentRoom")
                label = (comp.get("roomName") if comp is not None else "") or ""
                out[guid] = Room(guid, e.get("Name") or "", "" if "null" in label.lower() else label, [])
            area = e.find("AreaComponent")
            if area is not None:
                shapes.append((e, area))
    for e, area in shapes:
        owners = [(x.get("EntityCryGUID") or "").lower() for x in area.findall("Entities/Entity")]
        owners = [g for g in owners if g in out]
        # "..._portal" shapes are the doorways of a room, not its extent
        if not owners or "portal" in (e.get("Name") or "").lower():
            continue
        base = entity_matrix(e)
        for seg in area.findall("Segment"):
            inv = np.linalg.inv(base @ _quat_t(seg.get("transform_ls")))
            if seg.get("Type") == "Box":
                lo, hi = _floats(seg.get("BoxMin"), 3, None), _floats(seg.get("BoxMax"), 3, None)
                if lo is None or hi is None:
                    continue
                vol = (inv, "box", (lo, hi), float(np.prod(np.subtract(hi, lo))))
            elif seg.get("Type") == "Trimesh":
                pts = [_floats(p.get("pos") or p.get("Pos"), 3, None) for p in seg.findall("Point")]
                if any(p is None for p in pts) or len(pts) < 12 or len(pts) % 3:
                    continue
                tris = np.array(pts, np.float64).reshape(-1, 3, 3)
                signed = float((tris[:, 0] * np.cross(tris[:, 1], tris[:, 2])).sum() / 6)
                vol = (inv, "mesh", tris, abs(signed))
            else:
                pts = [_floats(p.get("Pos"), 3, None) for p in seg.findall("Points/Point")]
                pts = [(p[0], p[1]) for p in pts if p is not None]
                h = _floats(seg.get("Height"), 1, [0.0])[0]
                if len(pts) < 3 or h <= 0:
                    continue
                x, y = np.array(pts).T
                area2 = abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))) / 2
                vol = (inv, "shape", (pts, h), area2 * h)
            for g in owners:
                out[g].volumes.append(vol)
    return list(out.values())


ROOM_MARGIN = 0.35      # metres: walls and floors sit on the edge of a room's volume


def room_of(room_list, point):
    """Index of the room whose volume holds `point` (container space): the smallest one when several do (a toilet
    inside the crew quarters). -1 = between rooms (structure)."""
    best, best_vol = -1, float("inf")
    p4 = np.array([*point, 1.0])
    for i, r in enumerate(room_list):
        for inv, kind, data, vol in r.volumes or ():
            if vol >= best_vol:
                continue
            x, y, z = (inv @ p4)[:3]
            if kind == "box":
                lo, hi = data
                ok = (lo[0] - ROOM_MARGIN <= x <= hi[0] + ROOM_MARGIN and lo[1] - ROOM_MARGIN <= y <= hi[1] + ROOM_MARGIN
                      and lo[2] - ROOM_MARGIN <= z <= hi[2] + ROOM_MARGIN)
            elif kind == "mesh":
                ok = _inside_mesh(data, np.array([x, y, z]))
            else:
                pts, h = data
                ok = -ROOM_MARGIN <= z <= h + ROOM_MARGIN and _inside_polygon(pts, x, y)
            if ok:
                best, best_vol = i, vol
    return best


def read(archive, socpak, classes=None):
    """Placements of a .socpak's main object container (container space). Missing file -> []."""
    d = _main_soc(archive, socpak)
    if d is None:
        return []
    out = []
    for typ, ver, off, size in _chunks(d):
        if typ == CHUNK_OBJECTS:
            out += _brushes(d, off, size)
        elif typ == CHUNK_ENTITIES and d[off:off + 7] == b"CryXmlB":
            out += _entities(d, off, size, classes)
    return out


class Packed:
    """The archive, plus the files a .socpak carries inside itself: brushes drawn in the editor ("designer" objects)
    are named "<container>//Brush/designer_0.cgf" and live in the container's own zip (a wall of the Idris hangar)."""

    def __init__(self, archive, socpak):
        self.archive, self.socpak, self._zip = archive, _data_path(socpak), None

    def __getattr__(self, name):                 # everything else is the archive's
        return getattr(self.archive, name)

    def _member(self, path):
        p = (path or "").replace("\\", "/")
        if "//" not in p:
            return None
        if self._zip is None:
            try:
                data = self.archive.read(self.socpak)
                z = zipfile.ZipFile(io.BytesIO(data))
                self._zip = (z, {i.filename.replace("\\", "/").lower(): i for i in z.infolist()}, data)
            except Exception:
                self._zip = (None, {}, b"")
        return self._zip[1].get(p.rsplit("//", 1)[0].rsplit("/", 1)[-1].lower() + "/" + p.rsplit("//", 1)[1].lower())

    def exists(self, path):
        return self.archive.exists(path) or self._member(path) is not None

    def read(self, path):
        if self.archive.exists(path):
            return self.archive.read(path)
        m = self._member(path)
        if m is None:
            raise FileNotFoundError(path)
        z, _, data = self._zip
        # the names in the zip's directory and in its local headers differ by their slashes, which zipfile refuses:
        # the entry is read by hand
        o = m.header_offset
        o += 30 + int.from_bytes(data[o + 26:o + 28], "little") + int.from_bytes(data[o + 28:o + 30], "little")
        raw = data[o:o + m.compress_size]
        if m.compress_type == zipfile.ZIP_STORED:
            return raw
        if m.compress_type == zipfile.ZIP_DEFLATED:
            return zlib.decompress(raw, -15)
        return z.read(m)


def mount_matrix(c, bone_world=None):
    """Container placement on the hull: the hull bone it names when present, else its Offset (QuatT)."""
    if bone_world is not None:
        return np.asarray(bone_world, np.float64)
    m = np.eye(4)
    m[:3, :3] = _ang3_matrix(*c.get("rot", (0.0, 0.0, 0.0)))
    m[:3, 3] = c.get("pos", (0.0, 0.0, 0.0))
    return m
