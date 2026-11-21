"""'Full ship': a vehicle hull with its factory loadout and landing-gear legs mounted on their ports.

Every component hangs from the hull node (or the parent component's node) named like its item port, so hull
animations carry it along (a thruster on a moving wing). Animated components keep their own skeleton under a
"port/" name prefix; their clips are mixed with the hull's by clip name, so the hull's "Landing Gear: Deploy"
(clip landing_gear_extend) also unfolds the legs, whose clips have the same name."""
import re
from dataclasses import replace

import numpy as np

from . import animations, model, rig


def _ensure_skeleton(archive, m):
    """Static objects get their node hierarchy too: item ports are nodes/helpers of the geometry."""
    if m.skeleton:
        return m
    bones = rig.skeleton(archive, m.path)
    if not bones:
        return m
    known = {b.name.lower(): b.name for b in bones}
    parts = [replace(p, node=known.get(p.node.lower(), "")) for p in m.parts]
    return replace(m, parts=parts, skeleton=bones)


def twin(archive, path):
    """`path` if the archive has it, else the file the game data meant:
    - the same geometry under a sibling extension, when only that one exists: a .cgf named as .cga and the reverse
      (three screens in the Perseus' habs), a .cdf that only exists as .cga (the Cutter's front landing gear on the
      Command Module);
    - the same file name in another folder, when the archive has exactly one (a Javelin screen that moved to the
      Aegis kit folder)."""
    if not path or archive.exists(path):
        return path
    stem, dot, ext = path.rpartition(".")
    for other in {"cga": ("cgf",), "cgf": ("cga",), "cdf": ("cga", "cgf")}.get(ext.lower(), ()) if dot else ():
        if archive.exists(f"{stem}.{other}"):
            return f"{stem}.{other}"
    if ext.lower() in ("cga", "cgf"):
        index = getattr(archive, "geometry_by_name", None)
        if index is None and hasattr(archive, "names"):
            index = {}
            for n in archive.names:
                if n[-4:].lower() in (".cga", ".cgf"):
                    n = n.replace("\\", "/")
                    n = n[5:] if n[:5].lower() == "data/" else n
                    index.setdefault(n.rsplit("/", 1)[-1].lower(), []).append(n)
            try:
                archive.geometry_by_name = index          # built once, at the first file that is not where it should be
            except AttributeError:
                pass
        same = (index or {}).get(path.replace("\\", "/").rsplit("/", 1)[-1].lower(), [])
        if len(same) == 1:
            return same[0]
    return path


def find_port(lookup, name):
    """Index of the node an item port names (`lookup`: lowercase node name -> index), or None. A port and its node
    may differ by underscores only (Perseus: port hardpoint_lifesupport, node hardpoint_life_support): accepted when
    exactly one node matches that way."""
    i = lookup.get(name)
    if i is not None:
        return i
    key = name.replace("_", "")
    hits = {i for n, i in lookup.items() if n.replace("_", "") == key}
    return hits.pop() if len(hits) == 1 else None


INVISIBLE_MATERIALS = ("objects/vfx/mesheffects/particle_transparent_meshes/",)


def invisible(mtl):
    """Item records that dress their geometry in an effects "transparent" material: drawn invisible in game."""
    m = (mtl or "").replace("\\", "/").lower()
    return bool(m) and m.startswith(INVISIBLE_MATERIALS)


def load_full(archive, path, vehicle, adb_path=None):
    hull = _ensure_skeleton(archive, model.load_model(archive, path, adb_path))
    out = replace(hull, parts=list(hull.parts), skeleton=list(hull.skeleton), animations=list(hull.animations),
                  anim_sets=list(hull.anim_sets), warnings=list(hull.warnings), cache={})
    if not out.parts or not out.skeleton:
        return out
    lookup = {b.name.lower(): i for i, b in enumerate(out.skeleton)}
    hull_clips = {r.clip.lower() for r in out.animations}
    ids = {r.id for r in out.animations}
    loaded = {}
    stats = {"missing": 0, "mounted": 0}

    def load(geo, adb, mtl=""):
        key = (geo.lower(), adb or "", (mtl or "").lower())
        if key not in loaded:
            try:
                m = _ensure_skeleton(archive, model.load_model(archive, geo, adb or None))
                if mtl and archive.exists(mtl):
                    m = model.with_variant(m, archive, mtl)      # the item record's own material
                loaded[key] = m
            except Exception as e:      # one broken component never hides the ship
                out.warnings.append(("warn_part_error", {"path": geo, "error": str(e)}))
                loaded[key] = None
        return loaded[key]

    gear_links = _gear_links(out.animations)
    if gear_links:
        out.anim_sets = [replace(st, refs=_merge_siblings(st.refs, gear_links)) if st.prefix == "" else st
                         for st in out.anim_sets]

    families = {}       # (prefix, port name without its number) -> the bone that family of ports moves with
    carriers = {}       # prefix of a mounted component -> (component, index of its first bone, names its clips move)

    def holder(port_i, prefix):
        """The bone an item mounted on port_i moves with. Normally the port itself. But some clips move only a few
        ports of a family and the piece around them all: the Nova's missile reload lowers the rack and four of its
        twelve missile ports (hardpoint_s1_missile_201-204); the other eight, children of the root, stayed in the
        air with their missiles. Such a port follows the moving piece whose geometry holds it."""
        if prefix not in carriers:
            return port_i
        comp, base, moved = carriers[prefix]
        j = port_i - base
        if not moved or not 0 <= j < len(comp.skeleton):
            return port_i
        bones = comp.skeleton

        def moves(k):
            while k >= 0:
                if bones[k].name in moved:
                    return True
                k = bones[k].parent
            return False

        stem = re.sub(r"\d+$", "", bones[j].name)
        if moves(j) or stem == bones[j].name or not any(re.sub(r"\d+$", "", n) == stem for n in moved):
            return port_i
        if (prefix, stem) in families:
            return port_i if families[prefix, stem] is None else families[prefix, stem]
        index = {b.name: k for k, b in enumerate(bones)}

        def around(at):
            best = None
            for p in comp.parts:
                k = index.get(p.node)
                if k is None or not moves(k) or not len(p.vertices):
                    continue
                lo, hi = p.vertices.min(0) - 0.15, p.vertices.max(0) + 0.15
                if (at >= lo).all() and (at <= hi).all():
                    # the piece nearest the root among those that hold it (the rack, not the arm that swings on it),
                    # then the smallest
                    depth, q = 0, k
                    while bones[q].parent >= 0:
                        depth, q = depth + 1, bones[q].parent
                    rank = (depth, float(np.prod(hi - lo)))
                    if best is None or rank < best[0]:
                        best = (rank, k)
            return None if best is None else best[1]

        # the whole family goes with the piece that holds most of it: the ports at the rack's edge fall inside the
        # arm's box only, and would swing with it
        votes = [around(b.world[:3, 3]) for k, b in enumerate(bones)
                 if re.sub(r"\d+$", "", b.name) == stem and not moves(k)]
        votes = [v for v in votes if v is not None]
        families[prefix, stem] = base + max(set(votes), key=votes.count) if votes else None
        return port_i if families[prefix, stem] is None else families[prefix, stem]

    solid = [p.vertices for p in hull.parts if len(p.vertices) and p.material.kind != "hidden"]
    reach = ((np.min([v.min(0) for v in solid], axis=0) - 3.0, np.max([v.max(0) for v in solid], axis=0) + 3.0)
             if solid else (np.full(3, -np.inf), np.full(3, np.inf)))

    def placed_port(node, prefix, parent_i):
        """A port no node of the model carries, placed as the game does: by its offset from the node it names (the
        root when it names none). It becomes a node of its own. None when the game gives it no place: no offset and
        no node other than the root (relays, spare shield generators: listed in the loadout, drawn nowhere)."""
        place = node.get("place")
        if not place:
            return None
        root = parent_i if parent_i is not None else next((i for i, b in enumerate(out.skeleton) if b.parent < 0), 0)
        at = find_port(lookup, (prefix + place["helper"]).lower()) if place["helper"] else None
        moved = any(place["pos"]) or any(place["rot"])
        if at is None:
            at = root
        if not moved and (at == root or out.skeleton[at].parent < 0):
            return None
        from . import containers
        local = containers.mount_matrix(place)
        out.skeleton.append(rig.Bone(prefix + node["port"], at, local, out.skeleton[at].world @ local))
        lookup.setdefault((prefix + node["port"]).lower(), len(out.skeleton) - 1)
        return len(out.skeleton) - 1

    def mount(node, prefix, depth, parent_i=None, gear=False):
        port_i = find_port(lookup, (prefix + node["port"]).lower())
        placed = False
        if port_i is None:
            port_i = placed_port(node, prefix, parent_i)
            placed = port_i is not None and depth == 0
        if port_i is None and parent_i is not None:
            # modular items (gun barrels, jump module in a quantum drive) are modelled in their parent's space and
            # their ports are not geometry nodes: hang them from the parent's origin
            port_i = parent_i
        geo = twin(archive, node["geometry"])
        if not archive.exists(geo):
            stats["missing"] += 1                        # the game's files do not have this part
            return
        if port_i is None:
            return                                       # listed in the loadout, placed nowhere: not drawn in game
        if node.get("hidden") or invisible(node.get("material")):
            # a port flagged "invisible" (X1 GravLev boxes) or an invisible stand-in: nothing to draw, but what hangs
            # from it still does
            if depth < 4:
                for child in node.get("children") or []:
                    mount(child, prefix + node["port"] + "/", depth + 1, port_i)
            return
        comp = load(geo, node.get("adb"), node.get("material"))
        if comp is None or not comp.parts:
            return
        stats["mounted"] += 1
        port = out.skeleton[port_i]
        w = port.world
        pre = prefix + node["port"] + "/"
        base = len(out.skeleton)
        names = {b.name for b in comp.skeleton}
        mount_i = base if comp.skeleton else port_i      # the component's root bone, or the port itself
        hold_i = holder(port_i, prefix)                  # what the item moves with: the port, almost always
        hold = out.skeleton[hold_i]
        for b in comp.skeleton:
            local = b.local if b.parent >= 0 or hold_i == port_i else np.linalg.inv(hold.world) @ w @ b.world
            out.skeleton.append(rig.Bone(pre + b.name, base + b.parent if b.parent >= 0 else hold_i, local,
                                         w @ b.world))
            lookup.setdefault((pre + b.name).lower(), len(out.skeleton) - 1)
        carriers[pre] = (comp, base, {s.targets[h] for s in comp.anim_sets for r in s.refs for h in r.targets
                                      if h in s.targets})
        for p in comp.parts:
            node_name = pre + p.node if p.node in names else hold.name
            v = p.vertices @ w[:3, :3].T + w[:3, 3]
            if placed and len(v) and ((v.min(0) < reach[0]).any() or (v.max(0) > reach[1]).any()):
                # a piece of an item placed by its offset that leaves the hull by metres is drawn at rest where the
                # game never shows it: the poles of the 890 Jump's entrance lift, 12 m below the ship
                continue
            out.parts.append(replace(p, vertices=v, node=node_name, name=f"{node['port']} / {p.name}"))
        for s in comp.anim_sets:
            refs = _link_gear(s.refs, gear_links) if gear else s.refs
            out.anim_sets.append(animations.AnimSet(pre + s.prefix, refs,
                                                    {h: pre + n for h, n in s.targets.items()}))
        for r in (_link_gear(comp.animations, gear_links) if gear else comp.animations):
            # clips the hull already plays (same name) are driven by the hull's actions; the rest are offered once
            # (component poses are left out: they are states of other variants of the part, e.g. pl01_opened)
            if r.clip.lower() in hull_clips or r.id in ids or r.pose:
                continue
            ids.add(r.id)
            # listed under the port that carries the part ("Dashboard Pilot: Deploy"); the same part on several ports
            # (four thrusters) shares one action, which plays on all of them
            group = "Landing Gear" if gear else _port_title((prefix + node["port"]).split("/")[0])
            label = r.label if r.group == group else (r.group if r.label in ("Play", "Default") else
                                                       f"{r.group} {r.label}")
            out.animations.append(replace(r, group=group, label=label))
        if depth < 4:
            for child in node.get("children") or []:
                mount(child, pre, depth + 1, mount_i)

    for g in vehicle.get("gears") or []:
        if "fake" in g["geometry"].rsplit("/", 1)[-1].lower():     # static stand-ins of the real legs
            continue
        mount({"port": g["port"], "geometry": g["geometry"], "adb": "", "children": []}, "", 0, gear=True)
    for f in vehicle.get("fixed") or []:          # tank treads and road wheels, from the vehicle's definition
        mount({"port": f["port"], "geometry": f["geometry"], "adb": "", "children": []}, "", 0)
    for n in vehicle.get("tree") or []:
        mount(n, "", 0)
    if stats["missing"]:
        out.warnings.append(("warn_ports_missing", {"n": stats["missing"]}))
    return out


def _verb(clip):
    """deploy / retract / compress, read from any word of a clip name (lg_foot_deploy_main_left, LandingGear_Deploy,
    landing_gear_extend_a...), or None."""
    words = set(re.split(r"[^a-z]+", clip.lower()))
    if words & {"deploy", "extend"}:
        return "deploy"
    if "retract" in words:
        return "retract"
    if "compress" in words:
        return "compress"
    return None


def _gear_links(hull_actions):
    """{verb: hull action} of the hull's landing-gear group. Their clip names differ per ship (landing_gear_extend,
    LandingGear_Deploy, landing_dummy_deploy, lg_arm_deploy_main_left...); the legs' clips are matched by verb."""
    land = [r for r in hull_actions if "land" in r.group.lower()]
    links = {}
    for r in land:
        label = r.label.lower()
        verb = ("deploy" if label in ("deploy", "extend", "open") else "retract" if label in ("retract", "close")
                else "compress" if label == "compress" else None)
        if verb and verb not in links:
            links[verb] = r
    return links if "deploy" in links else None


def _merge_siblings(refs, links):
    """Hull clips that only differ by a side suffix after the verb (Reclaimer: lg_arm_deploy_main_left / _aux_right...)
    play together with the action's clip: the game runs one per leg scope, the viewer one for the whole gear."""
    out = []
    for r in refs:
        for verb, act in links.items():
            words = act.clip.lower().split("_")
            if verb not in (_verb(act.clip),) or r.clip == act.clip:
                continue
            cut = next((i for i, w in enumerate(words) if _verb(w) == verb), None)
            if cut is None or cut == len(words) - 1:
                continue                      # no suffix after the verb: nothing to gather
            stem = "_".join(words[:cut + 1]) + "_"
            if r.clip.lower().startswith(stem):
                r = replace(r, clip=act.clip)
                break
        out.append(r)
    return out


def _link_gear(refs, links):
    """Leg clips renamed after the hull's gear clips, so one action moves doors and legs together."""
    if not links:
        return refs
    dep, ret, comp = links["deploy"], links.get("retract"), links.get("compress")
    by_verb = {}
    for r in sorted(refs, key=lambda r: (len(r.clip), r.clip)):       # landing_gear_extend before _extend_a
        by_verb.setdefault(_verb(r.clip), r)
    ext, own_ret, own_comp = by_verb.get("deploy"), by_verb.get("retract"), by_verb.get("compress")
    out = [r for r in refs if r is not ext and r is not own_ret and r is not own_comp]
    if ext:
        out.append(replace(ext, clip=dep.clip, reverse_keys=dep.speed < 0))
    if ret and ret.clip != dep.clip:
        if own_ret:
            out.append(replace(own_ret, clip=ret.clip, reverse_keys=ret.speed < 0))
        elif ext:
            out.append(replace(ext, clip=ret.clip, reverse_keys=ret.speed > 0))
    if own_comp:
        out.append(replace(own_comp, clip=comp.clip) if comp and comp.clip != dep.clip else own_comp)
    return out


def _port_title(port):
    p = port.strip("$")
    low = p.lower()
    for pre in ("hardpoint_", "hardpoint"):
        if low.startswith(pre):
            p = p[len(pre):]
            break
    return animations._title(p) or port


# ------------------------------------------------------------------ interiors
INTERIOR_PREFIX = "interior"
# interiors use their own palettes (rsi_interior_default...), not the hull paint: a neutral light/mid/dark grey
INTERIOR_PALETTE = {"A": [150, 152, 155], "B": [92, 94, 98], "C": [58, 60, 63]}


# the editor's own boxes and cubes (hologram or no-draw materials): the Basher's light container parks four of them a
# kilometre from the ship, which was then framed as a dot
EDITOR_PRIMITIVES = "objects/default/"


def _lod0_mtl(archive, path):
    """.mtl file named by a geometry (its MtlName chunk), resolved like the model loader does; "" if none."""
    from . import ivo, materials
    try:
        name = ivo.material_name(ivo.IvoFile(archive.read(path)))
    except Exception:
        return ""
    return materials.resolve_path(archive, path, name) or ""


def load_interior(archive, base, vehicle, classes, max_parts=60000):
    """Copy of `base` (a hull, or a full ship) with the rooms of its object containers placed inside: walls, floors,
    pipes, lights (brushes) and props (doors, lockers, screens: entity classes with geometry). Static: their own
    animations are not loaded. Each container hangs from its hull bone, so it follows the hull."""
    from . import containers
    out = replace(base, parts=list(base.parts), skeleton=list(base.skeleton), animations=list(base.animations),
                  anim_sets=list(base.anim_sets), warnings=list(base.warnings), cache={}, rooms=[])
    ocs = (vehicle or {}).get("containers") or []
    if not ocs or not out.parts:
        return out
    bones = {b.name.lower(): b for b in out.skeleton}
    if not bones:
        bones = {b.name.lower(): b for b in (rig.skeleton(archive, base.path) or [])}
    geo_cache = {}
    failed = 0
    absent = 0
    added = 0
    # the hull's box with a margin: an object wholly beyond it was left there by the game's designers, parked away
    # from the ship (see the test); landing gear, ramps and lifts reach out of the hull by less than this
    hull_lo = np.min([p.vertices.min(0) for p in base.parts if len(p.vertices)], axis=0)
    hull_hi = np.max([p.vertices.max(0) for p in base.parts if len(p.vertices)], axis=0)
    reach = np.maximum(0.15 * (hull_hi - hull_lo), 3.0)
    hull_lo, hull_hi = hull_lo - reach, hull_hi + reach

    def geometry(path, mtl, archive):
        key = (path.lower(), (mtl or "").lower())
        if key not in geo_cache:
            try:
                path = twin(archive, path)
                # LOD1 when the game has one: about half the triangles (7.1 -> 3.1 M on the Perseus), same look
                stem, ext = path.rsplit(".", 1)
                lod1 = f"{stem}_lod1.{ext}"
                m = model.load_model(archive, lod1 if archive.exists(lod1) else path, animated=False)
                if m.parts and m.path == lod1 and not model.lod_fits(archive, m, path):
                    m = model.load_model(archive, path, animated=False)
                if m.parts and m.path == lod1:
                    # LOD files have no material name: they use the LOD0's .mtl, by the same sub-material indices
                    mtl0 = _lod0_mtl(archive, path)
                    if not mtl0:
                        m = model.load_model(archive, path, animated=False)
                    else:
                        m = replace(m, parts=[replace(p, mtl_path=mtl0) if not p.mtl_path else p for p in m.parts])
                if not m.parts and archive.exists(lod1):
                    m = model.load_model(archive, path, animated=False)
                if m.parts:
                    m = model.with_variant(m, archive, mtl or None, INTERIOR_PALETTE)
                geo_cache[key] = m.parts
            except Exception:
                geo_cache[key] = None
        return geo_cache[key]

    for oc in ocs:
        bone = bones.get((oc.get("bone") or "").lower())
        mount = containers.mount_matrix(oc, bone.world if bone is not None else None)
        node = bone.name if bone is not None and out.skeleton else ""
        stem = oc["file"].rsplit("/", 1)[-1].rsplit(".", 1)[0]
        try:
            placed = containers.read(archive, oc["file"], classes)
            files = containers.Packed(archive, oc["file"])      # designer brushes live inside the .socpak
        except Exception as e:
            out.warnings.append(("warn_part_error", {"path": oc["file"], "error": str(e)}))
            continue
        # the rooms the game defines in this container (containers.rooms): each placed object joins the room
        # whose volume holds its middle
        try:
            here = [r for r in containers.rooms(archive, oc["file"]) if r.volumes]
        except Exception:
            here = []
        first = len(out.rooms)
        for r in here:
            c = r.centre()
            out.rooms.append({"name": r.name, "key": r.label, "container": stem,
                              "centre": [float(x) for x in (mount[:3, :3] @ c + mount[:3, 3])], "parts": 0})
        for pl in placed:
            if pl.geometry.lower().replace("\\", "/").startswith(EDITOR_PRIMITIVES):
                continue
            parts = geometry(pl.geometry, pl.material, files)
            if not parts:
                if parts is None:
                    # a file the game's own data does not have is not this program's failure
                    there = files.exists(twin(files, pl.geometry))
                    failed, absent = failed + there, absent + (not there)
                continue
            w = mount @ pl.matrix
            room = -1
            if here:
                lo = np.min([p.vertices.min(0) for p in parts if len(p.vertices)], axis=0)
                hi = np.max([p.vertices.max(0) for p in parts if len(p.vertices)], axis=0)
                mid = (lo + hi) / 2
                k = containers.room_of(here, pl.matrix[:3, :3] @ mid + pl.matrix[:3, 3])
                room = first + k if k >= 0 else -1
            moved = [p.vertices @ w[:3, :3].T + w[:3, 3] for p in parts if len(p.vertices)]
            if not moved:
                continue
            lo = np.min([v.min(0) for v in moved], axis=0)
            hi = np.max([v.max(0) for v in moved], axis=0)
            if (hi < hull_lo).any() or (lo > hull_hi).any():
                continue
            for p, v in zip([p for p in parts if len(p.vertices)], moved):
                out.parts.append(replace(p, vertices=v, node=node,
                                         name=f"{INTERIOR_PREFIX} / {stem} / {p.name}", vbones=None,
                                         bone_names=None, room=room))
                if room >= 0:
                    out.rooms[room]["parts"] += 1
                added += 1
            if added > max_parts:
                out.warnings.append(("warn_interior_truncated", {"n": added}))
                return out
    if failed:
        out.warnings.append(("warn_interior_missing", {"n": failed}))
    if absent:
        out.warnings.append(("warn_interior_absent", {"n": absent}))
    return out


def repaint_interior(interior, hull, n):
    """`interior` (load_interior on another paint's hull, whose first `n` parts are that hull) with the hull parts of
    `hull`. Rooms never depend on the hull's paint (INTERIOR_PALETTE), so they are reused instead of rebuilt."""
    return replace(interior, parts=list(hull.parts) + interior.parts[n:], warnings=list(interior.warnings), cache={},
                   rooms=list(interior.rooms))


DECK_BIN = 0.15        # metres
DECK_MIN_GAP = 1.9     # two decks are at least this far apart


def decks(m):
    """Floor heights (metres, viewer Y = game Z) of the decks of an interior model: the levels where the interior's
    level, upward-facing surfaces add up to the most area. [] when the model has no interior parts.
    In the cache of the model: computed once."""
    if "decks" in m.cache:
        return m.cache["decks"]
    bins = {}
    for p in m.parts:
        if not p.name.startswith(INTERIOR_PREFIX) or p.material.kind != "solid" or not len(p.faces):
            continue
        v = p.vertices[p.faces]                              # (n, 3, 3)
        n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
        ln = np.linalg.norm(n, axis=1)
        ok = (ln > 1e-9) & (n[:, 2] > 0.97 * ln)            # floors: facing up, level
        if not ok.any():
            continue
        k = np.round(v[ok, :, 2].mean(axis=1) / DECK_BIN).astype(int)
        area = ln[ok] / 2
        for kk in np.unique(k):
            bins[int(kk)] = bins.get(int(kk), 0.0) + float(area[k == kk].sum())
    out = []
    if bins:
        peak = max(bins.values())
        cand = sorted(((a, k) for k, a in bins.items()
                       if a >= max(2.0, peak * 0.12) and a >= bins.get(k - 1, 0) and a >= bins.get(k + 1, 0)), reverse=True)
        for _, k in cand:
            y = k * DECK_BIN
            if all(abs(y - f) >= DECK_MIN_GAP for f in out):
                out.append(y)
        out = sorted(out)[:8]
    m.cache["decks"] = [round(y, 3) for y in out]
    return m.cache["decks"]

