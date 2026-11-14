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

    def load(geo, adb):
        key = (geo.lower(), adb or "")
        if key not in loaded:
            try:
                loaded[key] = _ensure_skeleton(archive, model.load_model(archive, geo, adb or None))
            except Exception as e:      # one broken component never hides the ship
                out.warnings.append(("warn_part_error", {"path": geo, "error": str(e)}))
                loaded[key] = None
        return loaded[key]

    gear_links = _gear_links(out.animations)
    if gear_links:
        out.anim_sets = [replace(st, refs=_merge_siblings(st.refs, gear_links)) if st.prefix == "" else st
                         for st in out.anim_sets]

    def mount(node, prefix, depth, parent_i=None, gear=False):
        port_i = lookup.get((prefix + node["port"]).lower())
        if port_i is None and parent_i is not None:
            # modular items (gun barrels, jump module in a quantum drive) are modelled in their parent's space and
            # their ports are not geometry nodes: hang them from the parent's origin
            port_i = parent_i
        geo = node["geometry"]
        if port_i is None or not archive.exists(geo):
            stats["missing"] += 1
            return
        comp = load(geo, node.get("adb"))
        if comp is None or not comp.parts:
            return
        stats["mounted"] += 1
        port = out.skeleton[port_i]
        w = port.world
        pre = prefix + node["port"] + "/"
        base = len(out.skeleton)
        names = {b.name for b in comp.skeleton}
        mount_i = base if comp.skeleton else port_i      # the component's root bone, or the port itself
        for b in comp.skeleton:
            out.skeleton.append(rig.Bone(pre + b.name, base + b.parent if b.parent >= 0 else port_i, b.local,
                                         w @ b.world))
            lookup.setdefault((pre + b.name).lower(), len(out.skeleton) - 1)
        for p in comp.parts:
            node_name = pre + p.node if p.node in names else port.name
            out.parts.append(replace(p, vertices=p.vertices @ w[:3, :3].T + w[:3, 3], node=node_name,
                                     name=f"{node['port']} / {p.name}"))
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
                  anim_sets=list(base.anim_sets), warnings=list(base.warnings), cache={})
    ocs = (vehicle or {}).get("containers") or []
    if not ocs or not out.parts:
        return out
    bones = {b.name.lower(): b for b in out.skeleton}
    if not bones:
        bones = {b.name.lower(): b for b in (rig.skeleton(archive, base.path) or [])}
    geo_cache = {}
    failed = 0
    added = 0

    def geometry(path, mtl):
        key = (path.lower(), (mtl or "").lower())
        if key not in geo_cache:
            try:
                # LOD1 when the game has one: about half the triangles (7.1 -> 3.1 M on the Perseus), same look
                stem, ext = path.rsplit(".", 1)
                lod1 = f"{stem}_lod1.{ext}"
                m = model.load_model(archive, lod1 if archive.exists(lod1) else path, animated=False)
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
        except Exception as e:
            out.warnings.append(("warn_part_error", {"path": oc["file"], "error": str(e)}))
            continue
        for pl in placed:
            parts = geometry(pl.geometry, pl.material)
            if not parts:
                failed += parts is None
                continue
            w = mount @ pl.matrix
            for p in parts:
                out.parts.append(replace(p, vertices=p.vertices @ w[:3, :3].T + w[:3, 3], node=node,
                                         name=f"{INTERIOR_PREFIX} / {stem} / {p.name}", vbones=None,
                                         bone_names=None))
                added += 1
            if added > max_parts:
                out.warnings.append(("warn_interior_truncated", {"n": added}))
                return out
    if failed:
        out.warnings.append(("warn_interior_missing", {"n": failed}))
    return out
