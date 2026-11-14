"""Index of DataCore entities by geometry.

- "adb": which Mannequin animation database (.adb) gives an object's clips their meaning;
- "vehicles": for ships and ground vehicles, the factory loadout as a tree of {port, geometry, adb, children}
  plus the landing-gear legs ({port: hull bone, geometry}), used by the "Full ship" assembly, and the object
  containers of the interior ({file: .socpak, bone, pos, rot});
- "classes": entity class GUID -> [geometry, material], for the entities placed inside object containers."""
from .datacore import DataCore, _guid

ADB_ROOT = "Animations/Mannequin/ADB/"
MAX_DEPTH = 4


def _norm(path):
    p = (path or "").replace("\\", "/").lower()
    return p[5:] if p.startswith("data/") else p


def _data_path(path):
    p = (path or "").replace("\\", "/")
    return p[5:] if p.lower().startswith("data/") else p


def _adb_path(adb):
    adb = (adb or "").replace("\\", "/")
    if not adb:
        return ""
    return adb if adb.lower().startswith("animations/") else ADB_ROOT + adb


class _Index:
    def __init__(self, dc):
        self.dc = dc
        self.by_name = {}
        self._info = {}
        for ri in dc.records_of("EntityClassDefinition"):
            self.by_name.setdefault(dc.record_name(ri).split(".", 1)[-1].lower(), ri)

    def info(self, ri):
        """(geometry path, adb path, components view list) of an entity record, cached."""
        if ri not in self._info:
            geo = adb = ""
            comps = [c for c in self.dc.record_view(ri)["Components"] if c is not None]
            for c in comps:
                t = c.type
                if t == "SGeometryResourceParams":
                    geo = _data_path(c["Geometry"]["Geometry"]["Geometry"]["path"])
                elif t == "SAnimationControllerParams":
                    adb = _adb_path(c["AnimationDatabase"])
            self._info[ri] = (geo, adb, comps)
        return self._info[ri]

    def entries(self, comps):
        for c in comps:
            if c.type == "SEntityComponentDefaultLoadoutParams":
                lo = c["loadout"]
                return lo["entries"] if lo is not None and lo.has("entries") else []
        return []

    def tree(self, entries, depth=0):
        out = []
        if depth >= MAX_DEPTH:
            return out
        for e in entries or []:
            if e is None:
                continue
            port = e["itemPortName"] or ""
            ri = None
            name = (e["entityClassName"] or "").lower()
            if name:
                ri = self.by_name.get(name)
            if ri is None:
                ref = e["entityClassReference"]
                ri = ref if isinstance(ref, int) else None
            if not port or ri is None:
                continue
            geo, adb, comps = self.info(ri)
            if not geo:
                continue
            nested = e["loadout"]
            sub = nested["entries"] if nested is not None and nested.has("entries") else None
            children = self.tree(sub if sub else self.entries(comps), depth + 1)
            out.append({"port": port, "geometry": geo, "adb": adb, "children": children})
        return out


def _gears(dc, comps):
    out = []
    for c in comps:
        if c.type != "VehicleComponentParams" or not c.has("landingSystem"):
            continue
        ri = c["landingSystem"]
        if not isinstance(ri, int):
            continue
        ls = dc.record_view(ri)
        for g in (ls["gears"] if ls.has("gears") else []):
            if g is None:
                continue
            geo = _data_path(g["geometry"]["path"]) if g["geometry"] is not None else ""
            if geo and g["bone"]:
                out.append({"port": g["bone"], "geometry": geo})
    return out


def _containers(comps):
    """Object containers a vehicle loads (interior rooms): .socpak file, hull bone and offset (pos, Ang3 degrees)."""
    out = []
    for c in comps:
        if c.type != "VehicleComponentParams" or not c.has("objectContainers"):
            continue
        for oc in c["objectContainers"] or []:
            if oc is None:
                continue
            f = _data_path(oc["fileName"] or "")
            if not f.lower().endswith(".socpak"):
                continue
            off = oc["Offset"]
            pos = [float(off["Position"][k]) for k in "xyz"] if off is not None else [0.0, 0.0, 0.0]
            rot = [float(off["Rotation"][k]) for k in "xyz"] if off is not None else [0.0, 0.0, 0.0]
            out.append({"file": f, "bone": oc["boneName"] or "", "pos": pos, "rot": rot})
    return out


def _geometry_material(comps):
    for c in comps:
        if c.type == "SGeometryResourceParams":
            try:
                m = c["Geometry"]["Geometry"]["Material"]
                return _data_path(m["path"]) if m is not None else ""
            except (KeyError, TypeError):
                return ""
    return ""


def _ammo(idx, comps):
    """{"max", "low"} of a weapon: its own ammo container (energy weapons) or the factory magazine's."""
    def container(cs):
        for c in cs:
            if c.type == "SAmmoContainerComponentParams":
                return {"max": int(c["maxAmmoCount"] or 0), "low": float(c["lowAmmoWarningPercentage"] or 0.1)}
        return None
    if not any(c.type == "SCItemWeaponComponentParams" for c in comps):
        return None
    for e in idx.entries(comps):
        if e is None or "magazine" not in (e["itemPortName"] or "").lower():
            continue
        ri = idx.by_name.get((e["entityClassName"] or "").lower())
        if ri is not None:
            got = container(idx.info(ri)[2])
            if got and got["max"] > 0:
                return got
    got = container(comps)
    return got if got and got["max"] > 0 else None


def build(data: bytes):
    dc = DataCore(data)
    idx = _Index(dc)
    found, vehicles, ammo, classes = {}, {}, {}, {}
    for ri in dc.records_of("EntityClassDefinition"):
        geo, adb, comps = idx.info(ri)
        if not geo:
            continue
        classes[_guid(dc.records[ri]["guid"].tobytes())] = [geo, _geometry_material(comps)]
        rec_name = dc.record_name(ri).split(".", 1)[-1]
        if adb:
            found.setdefault(_norm(geo), []).append((rec_name, adb))
        got = _ammo(idx, comps)
        if got:
            ammo.setdefault(_norm(geo), got)
        if any(c.type == "VehicleComponentParams" for c in comps):
            tree = idx.tree(idx.entries(comps))
            gears = _gears(dc, comps)
            ocs = _containers(comps)
            if tree or gears or ocs:
                vehicles.setdefault(_norm(geo), []).append((rec_name, {"tree": tree, "gears": gears,
                                                                       "containers": ocs}))
    adbs = {}
    for geo, recs in found.items():
        recs.sort()
        stem = geo.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        adbs[geo] = next((r for r in recs if r[0].lower().endswith(stem)), recs[0])[1]
    veh = {}
    for geo, recs in vehicles.items():
        stem = geo.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        recs.sort(key=lambda r: (not r[0].lower().endswith(stem), -len(r[1]["tree"]), r[0]))
        veh[geo] = recs[0][1]
    return {"adb": adbs, "vehicles": veh, "ammo": ammo, "classes": classes}


def adb_for(index, path):
    return (index or {}).get("adb", {}).get(_norm(path))


def ammo_for(index, path):
    return (index or {}).get("ammo", {}).get(_norm(path))


def classes_of(index):
    return (index or {}).get("classes", {})


def vehicle_for(index, path):
    return (index or {}).get("vehicles", {}).get(_norm(path))
