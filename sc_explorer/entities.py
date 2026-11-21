"""Index of DataCore entities by geometry.

- "adb": which Mannequin animation database (.adb) gives an object's clips their meaning;
- "vehicles": for ships and ground vehicles, the factory loadout as a tree of {port, geometry, adb, children, and
  hidden: true when the port is flagged "invisible"}; the geometry is the item's variant for the port's tags when
  it has one (a "right" flap on a port flagged "right")
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
    def __init__(self, dc, exists=None):
        self.dc = dc
        self.exists = exists        # exists(path) -> bool, or None when the archive is not at hand
        self.by_name = {}
        self._info = {}
        self._tagged = {}
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

    def tagged(self, ri, tags):
        """(geometry, material) of the variant of an item for a port with these tags, or None: the first SubGeometry
        of its record whose Tags are all among them. One item serves both sides of a ship this way: the Avenger's
        retro thruster is the left flap, with the mirrored one as a SubGeometry tagged "right".
        A variant may have variants of its own, and the deepest one that fits is the one mounted: the Ares' wing
        rack is tagged "CRUS_Starfighter", and inside it "Left" and "Right"."""
        if not tags:
            return None
        if ri not in self._tagged:
            def variants(node, depth=0):
                subs = []
                for s in ((node["SubGeometry"] if node.has("SubGeometry") else None) or []) if depth < 4 else []:
                    try:
                        want = frozenset((s["Tags"] or "").lower().split()) if s is not None else None
                        if not want:
                            continue
                        data = s["Geometry"]
                        geo = _data_path(data["Geometry"]["path"]) if data is not None else ""
                        # a variant whose file the game no longer ships leaves the item as it is (Javelin:
                        # aegs_javelin_support_engine_lower.cga)
                        if not (geo and (self.exists is None or self.exists(geo))):
                            geo = ""
                        mtl = data["Material"] if geo else None
                        subs.append((want, geo, _data_path(mtl["path"]) if mtl is not None else "",
                                     variants(s, depth + 1)))
                    except (KeyError, TypeError):
                        pass
                return subs

            tree = []
            for c in self.info(ri)[2]:
                if c.type == "SGeometryResourceParams":
                    try:
                        tree = variants(c["Geometry"])
                    except (KeyError, TypeError):
                        pass
                    break
            self._tagged[ri] = tree

        def pick(subs):
            for want, geo, mtl, inner in subs:
                if want <= tags:
                    deeper = pick(inner)
                    if deeper or geo:
                        return deeper or (geo, mtl)
            return None
        return pick(self._tagged[ri])

    def entries(self, comps):
        for c in comps:
            if c.type == "SEntityComponentDefaultLoadoutParams":
                lo = c["loadout"]
                return lo["entries"] if lo is not None and lo.has("entries") else []
        return []

    def tree(self, entries, depth=0, hidden=frozenset(), tags=None, places=None):
        """hidden: lower-case names of the ports flagged "invisible" (the game does not draw what they carry).
        tags: {lower-case port name: its tags}, which choose the variant of the item mounted there (tagged).
        places: {lower-case port name: where the port is when no node of the model has its name} (_item_port_places)."""
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
            # the record's material override: variant paints, and invisible stand-ins (an effects material that the
            # game draws transparent, e.g. the Nox's retro thrusters reuse the Vanduul Scythe's thruster model)
            mtl = _geometry_material(comps)
            side = self.tagged(ri, (tags or {}).get(port.lower()))
            if side:
                geo, mtl = side[0], side[1] or mtl
            nested = e["loadout"]
            sub = nested["entries"] if nested is not None and nested.has("entries") else None
            children = self.tree(sub if sub else self.entries(comps), depth + 1, _invisible_item_ports(comps),
                                 _item_port_tags(comps), _item_port_places(comps))
            node = {"port": port, "geometry": geo, "adb": adb, "material": mtl, "children": children}
            if port.lower() in (places or {}):
                node["place"] = places[port.lower()]
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


def _item_port_places(comps):
    """{lower-case port name: {"helper", "pos", "rot"}} of the ports the game places by an offset from a node (DataCore:
    AttachmentImplementation.Helper): the node's name ("" = the root) and the offset from it, metres and Ang3 degrees.
    Many ports have no node of their own in the model: the PDC turrets of the Idris hang 39 m ahead of its root, the
    MOLE's spare ore pods, the Valkyrie's gun racks. Ports with neither a helper nor an offset are left out."""
    out = {}
    for c in comps:
        if c.type == "SItemPortContainerComponentParams" and c.has("Ports"):
            for p in c["Ports"] or []:
                try:
                    h = p["AttachmentImplementation"]["Helper"]["Helper"]
                    pos = [float(h["Offset"]["Position"][k]) for k in ("x", "y", "z")]
                    rot = [float(h["Offset"]["Rotation"][k]) for k in ("x", "y", "z")]
                    helper = h["Name"] or ""
                except Exception:           # no attachment data on this port
                    continue
                if helper or any(pos) or any(rot):
                    out[(p["Name"] or "").lower()] = {"helper": helper, "pos": pos, "rot": rot}
    return out


def _item_port_tags(comps):
    """{lower-case port name: its tags} of an item's own ports (DataCore: the words of Flags, PortTags and Tags)."""
    out = {}
    for c in comps:
        if c.type == "SItemPortContainerComponentParams" and c.has("Ports"):
            for p in c["Ports"] or []:
                if p is None:
                    continue
                words = " ".join(str(p[k] or "") for k in ("Flags", "PortTags", "Tags") if p.has(k))
                if words.strip():
                    out[(p["Name"] or "").lower()] = frozenset(words.lower().split())
    return out


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


def vehicle_port_tags(xml_bytes):
    """{lower-case port name: its tags} of a vehicle implementation XML: the words of each item port's flags
    ("maneuver orientation retro uneditable right"). Ports without flags are left out."""
    out = {}
    root = cryxml.parse(xml_bytes)
    for part in root.iter("Part"):
        if (part.get("class") or "").lower() != "itemport":
            continue
        ip = part.find("ItemPort")
        words = (ip.get("flags") or "").lower().split() if ip is not None else []
        if words:
            out[(part.get("name") or "").lower()] = frozenset(words)
    return out


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
    idx = _Index(dc, getattr(read, "exists", None))
    found, vehicles, ammo, classes, named = {}, {}, {}, {}, {}
    defs = {}

    def definition(comps):
        """(invisible ports, parts on the hull, port tags) of the vehicle's implementation XML."""
        path = _vehicle_definition(comps)
        if path and read is not None and path.lower() not in defs:
            got = (frozenset(), [], {})
            try:
                xml = read(path)
                if xml:
                    got = (invisible_vehicle_ports(xml), vehicle_parts(xml), vehicle_port_tags(xml))
            except Exception:       # a broken XML only means no port is known to be invisible, no tread is mounted
                pass
            defs[path.lower()] = got
        return defs.get(path.lower(), (frozenset(), [], {}))

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
            tree = idx.tree(idx.entries(comps), hidden=vehicle_hidden(comps),
                            tags={**_item_port_tags(comps), **definition(comps)[2]}, places=_item_port_places(comps))
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
    """build()'s read(): a file of the archive, or None when it is missing. read.exists(path) tells whether a
    geometry file is there, whichever of .cga / .cgf the game data names it with."""
    def read(path):
        return archive.read(path) if archive.exists(path) else None

    def exists(path):
        stem, dot, ext = path.rpartition(".")
        other = {"cga": "cgf", "cgf": "cga"}.get(ext.lower())
        return archive.exists(path) or bool(dot and other and archive.exists(f"{stem}.{other}"))
    read.exists = exists
    return read
