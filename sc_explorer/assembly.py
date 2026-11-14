"""'Full ship': a vehicle hull with its factory loadout and landing-gear legs mounted on their ports.

Every component hangs from the hull node (or the parent component's node) named like its item port, so hull
animations carry it along (a thruster on a moving wing). Animated components keep their own skeleton under a
"port/" name prefix; their clips are mixed with the hull's by clip name, so the hull's "Landing Gear: Deploy"
(clip landing_gear_extend) also unfolds the legs, whose clips have the same name."""
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


def _gear_links(hull_actions):
    """(deploy clip, retract clip) of the hull's landing-gear actions, or None. Their clip names differ per ship
    (landing_gear_extend, LandingGear_Deploy, landing_dummy_deploy...), the legs always have *_extend."""
    land = [r for r in hull_actions if "land" in r.group.lower()]
    dep = next((r for r in land if r.label.lower() in ("deploy", "extend", "open")), None)
    ret = next((r for r in land if r.label.lower() in ("retract", "close")), None)
    return (dep, ret) if dep else None


def _link_gear(refs, links):
    """Leg clips renamed after the hull's gear clips, so one action moves doors and legs together."""
    if not links:
        return refs
    dep, ret = links
    ext = next((r for r in refs if r.clip.lower().endswith(("extend", "deploy"))), None)
    own_ret = next((r for r in refs if r.clip.lower().endswith("retract")), None)
    out = [r for r in refs if r is not ext and r is not own_ret]
    if ext:
        out.append(replace(ext, clip=dep.clip, reverse_keys=dep.speed < 0))
    if ret and ret.clip != dep.clip:
        if own_ret:
            out.append(replace(own_ret, clip=ret.clip, reverse_keys=ret.speed < 0))
        elif ext:
            out.append(replace(ext, clip=ret.clip, reverse_keys=ret.speed > 0))
    return out


def _port_title(port):
    p = port.strip("$")
    low = p.lower()
    for pre in ("hardpoint_", "hardpoint"):
        if low.startswith(pre):
            p = p[len(pre):]
            break
    return animations._title(p) or port
