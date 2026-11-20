"""Index of DataCore entities by geometry.

- "adb": which Mannequin animation database (.adb) gives an object's clips their meaning;
- "vehicles": for ships and ground vehicles, the factory loadout as a tree of {port, geometry, adb, children, and
  hidden: true when the port is flagged "invisible"}
  plus the landing-gear legs ({port: hull bone, geometry}), used by the "Full ship" assembly, and the object
  containers of the interior ({file: .socpak, bone, pos, rot});
- "classes": entity class GUID -> [geometry, material], for the entities placed inside object containers;
- "names": geometry -> the name keys (global.ini, lower case, no "@") of the entities that use it, the entity named
  like the file first. An empty list means the game has entities for that geometry but none with a name."""
from . import cryxml
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

    def tree(self, entries, depth=0, hidden=frozenset()):
        """hidden: lower-case names of the ports flagged "invisible" (the game does not draw what they carry)."""
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
            children = self.tree(sub if sub else self.entries(comps), depth + 1, _invisible_item_ports(comps))
            # the record's material override: variant paints, and invisible stand-ins (an effects material that the
            # game draws transparent, e.g. the Nox's retro thrusters reuse the Vanduul Scythe's thruster model)
            node = {"port": port, "geometry": geo, "adb": adb, "material": _geometry_material(comps),
                    "children": children}
            if port.lower() in hidden:
                node["hidden"] = True
            out.append(node)
        return out


def _flagged_invisible(flags):
    return "invisible" in (flags or "").lower().split()


def _invisible_item_ports(comps):
    """Ports of an item (DataCore SItemPortContainerComponentParams) whose flags include "invisible"."""
    out = set()
    for c in comps:
        if c.type == "SItemPortContainerComponentParams" and c.has("Ports"):
            for p in c["Ports"] or []:
                if p is not None and p.has("Flags") and _flagged_invisible(p["Flags"]):
                    out.add((p["Name"] or "").lower())
    return frozenset(out)


def _vehicle_definition(comps):
    for c in comps:
        if c.type == "VehicleComponentParams" and c.has("vehicleDefinition"):
            return _data_path(c["vehicleDefinition"] or "")
    return ""


def invisible_vehicle_ports(xml_bytes):
    """Item ports a vehicle implementation XML flags "invisible" (<Part class="ItemPort"><ItemPort flags=...>): the
    game does not draw what they carry, e.g. the X1's six GravLev emitters, 10 cm boxes that hang outside the hull."""
    out = set()
    root = cryxml.parse(xml_bytes)
    for part in root.iter("Part"):
        if (part.get("class") or "").lower() != "itemport":
            continue
        ip = part.find("ItemPort")
        if ip is not None and _flagged_invisible(ip.get("flags")):
            out.add((part.get("name") or "").lower())
    return frozenset(out)


def vehicle_parts(xml_bytes):
    """What a vehicle implementation XML hangs on the hull itself, outside any loadout: tank treads
    (<Part class="Tread"><Tread filename=...cdf>) and road wheels (<Part class="SubPartWheel"><SubPart filename=...>),
    each on the hull node of the part's name. Wheels that only exist for the physics (..._invisible, ..._hidden) are
    left out. [{"port", "geometry"}]"""
    out = []
    root = cryxml.parse(xml_bytes)
    for part in root.iter("Part"):
        cls, name = (part.get("class") or "").lower(), part.get("name") or ""
        tag = {"tread": "Tread", "subpartwheel": "SubPart"}.get(cls)
        if not tag or not name:
            continue
        geo = next((e.get("filename") for e in part.iter(tag) if e.get("filename")), "")
        stem = geo.rsplit("/", 1)[-1].lower()
        if geo and "invisible" not in stem and "hidden" not in stem:
            out.append({"port": name, "geometry": _data_path(geo)})
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


def _name_key(key):
    return (key or "").lstrip("@").strip().lower()


def _item_name(comps):
    """Name key of an item (SAttachableComponentParams > AttachDef > Localization > Name), "" without one."""
    for c in comps:
        if c.type == "SAttachableComponentParams":
            try:
                return _name_key(c["AttachDef"]["Localization"]["Name"])
            except (KeyError, TypeError):
                return ""
    return ""


def _vehicle_name(comps):
    for c in comps:
        if c.type == "VehicleComponentParams" and c.has("vehicleName"):
            return _name_key(c["vehicleName"])
    return ""


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


def build(data: bytes, read=None):
    """read(path) -> bytes or None: reads the vehicle implementation XMLs (port flags); without it no port is
    known to be invisible."""
    dc = DataCore(data)
    idx = _Index(dc)
    found, vehicles, ammo, classes, named = {}, {}, {}, {}, {}
    defs = {}

    def definition(comps):
        """(invisible ports, parts on the hull) of the vehicle's implementation XML."""
        path = _vehicle_definition(comps)
        if path and read is not None and path.lower() not in defs:
            got = (frozenset(), [])
            try:
                xml = read(path)
                if xml:
                    got = (invisible_vehicle_ports(xml), vehicle_parts(xml))
            except Exception:       # a broken XML only means no port is known to be invisible, no tread is mounted
                pass
            defs[path.lower()] = got
        return defs.get(path.lower(), (frozenset(), []))

    def vehicle_hidden(comps):
        return definition(comps)[0] | _invisible_item_ports(comps)
    for ri in dc.records_of("EntityClassDefinition"):
        geo, adb, comps = idx.info(ri)
        if not geo:
            continue
        classes[_guid(dc.records[ri]["guid"].tobytes())] = [geo, _geometry_material(comps)]
        rec_name = dc.record_name(ri).split(".", 1)[-1]
        named.setdefault(_norm(geo), []).append((rec_name, _item_name(comps)))
        if adb:
            found.setdefault(_norm(geo), []).append((rec_name, adb))
        got = _ammo(idx, comps)
        if got:
            ammo.setdefault(_norm(geo), got)
        if any(c.type == "VehicleComponentParams" for c in comps):
            tree = idx.tree(idx.entries(comps), hidden=vehicle_hidden(comps))
            gears = _gears(dc, comps)
            ocs = _containers(comps)
            fixed = definition(comps)[1]
            if tree or gears or ocs or fixed:
                vehicles.setdefault(_norm(geo), []).append((rec_name, {"tree": tree, "gears": gears,
                                                                       "containers": ocs, "fixed": fixed,
                                                                       "name": _vehicle_name(comps)}))
    adbs = {}
    for geo, recs in found.items():
        recs.sort()
        stem = geo.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        adbs[geo] = next((r for r in recs if r[0].lower().endswith(stem)), recs[0])[1]
    veh = {}
    for geo, recs in vehicles.items():
        stem = geo.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        recs.sort(key=lambda r: (not r[0].lower().endswith(stem), -len(r[1]["tree"]), r[0]))
        # the loadout comes from the richest record, the name from the plainest one: ANVL_Hornet.cga is the F7C,
        # the F7C-R Tracker and the F7C-S Ghost, and "ANVL_Hornet_F7C" is the ship the others are variants of
        words = set(stem.split("_"))       # rsi_constellation_gs_andromeda.cga is the Andromeda, not the Aquila
        base = min((r for r in recs if r[1]["name"]), default=recs[0],
                   key=lambda r: (not r[0].lower().endswith(stem), not set(r[0].lower().split("_")) <= words,
                                  len(r[0]), r[0]))
        veh[geo] = dict(recs[0][1], name=base[1]["name"], records=len(recs))
    names = {}
    for geo, recs in named.items():
        stem = geo.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        recs.sort(key=lambda r: (not r[0].lower().endswith(stem), len(r[0]), r[0]))
        names[geo] = list(dict.fromkeys(k for _, k in recs if k))
    return {"adb": adbs, "vehicles": veh, "ammo": ammo, "classes": classes, "names": names}


def adb_for(index, path):
    return (index or {}).get("adb", {}).get(_norm(path))


def ammo_for(index, path):
    return (index or {}).get("ammo", {}).get(_norm(path))


def classes_of(index):
    return (index or {}).get("classes", {})


def names_of(index):
    return (index or {}).get("names", {})


def vehicle_for(index, path):
    return (index or {}).get("vehicles", {}).get(_norm(path))


def archive_reader(archive):
    """build()'s read(): a file of the archive, or None when it is missing."""
    return lambda path: archive.read(path) if archive.exists(path) else None
