"""Instant paint switching: paint groups, the swap check, paint tables (sc_explorer/paints.py) and the keyed GLB."""
import json
import os
import struct
import sys
import xml.etree.ElementTree as ET

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sc_explorer import assembly, export, materials, model, modelcache, paints, server  # noqa: E402

STENCIL = '<Material Name="livery" Shader="MeshDecal" StringGenMask="%STENCIL_MAP" Diffuse="0,0,0"><Textures/></Material>'


def test_stencil_decals_are_marked_whatever_the_palette():
    el = ET.fromstring(STENCIL)
    bare = materials._material(el, None, None)
    painted = materials._material(el, None, {"decal": "Data/x/atlas.dds", "decal_colors": [[255, 0, 0], None, None]})
    assert bare.kind == "hidden" and bare.stencil_decal
    assert painted.kind == "decal" and painted.stencil_decal
    plain = materials._material(ET.fromstring('<Material Name="hull" Shader="Illum"><Textures/></Material>'), None, None)
    assert not plain.stencil_decal


def _glb_json(glb):
    n = struct.unpack_from("<I", glb, 12)[0]
    return json.loads(glb[20:20 + n])


def _glb_bin(glb):
    n = struct.unpack_from("<I", glb, 12)[0]
    m = struct.unpack_from("<I", glb, 20 + n)[0]
    return glb[28 + n:28 + n + m]


def _mat(name="hull", kind="solid", color=(0.5, 0.25, 0.125), **kw):
    return materials.Material(name, "Illum", kind, color, **kw)


def test_glb_material_matches_the_glb():
    mat = _mat(emissive=(0.2, 0.1, 0.0))
    fields, base, normal, uv_scale, sh = export.glb_material(mat, True, None, 1024, lite=True, group=4)
    assert fields["name"] == f"solid|hull|{export._sid(mat)}|g4"
    assert fields["color"] == [round(float(c) * 255) / 255 for c in export._srgb(mat.color)]   # uint8, like trimesh
    assert fields["alpha"] == 1.0 and fields["emissive"] == [float(c) for c in export._srgb((0.2, 0.1, 0.0))]
    assert fields["alpha_mode"] == "OPAQUE" and fields["alpha_cutoff"] is None and fields["visible"]
    assert not fields["texture"] and not fields["normal_texture"] and sh is not None
    glass = export.glb_material(_mat("pane", "glass", (0.8, 0.8, 0.8)), True, None, 1024, lite=True)[0]
    assert glass["alpha_mode"] == "BLEND" and glass["name"] == "glass|pane|"
    assert glass["color"] == [round(c * 255) / 255 for c in materials.glass_look(_mat("pane", "glass", (0.8, 0.8, 0.8)))[0]]


def test_screen_names_keep_their_suffix_last():
    mon = materials.Material("mfd", "DisplayScreen", "screen", (0.01, 0.01, 0.01), emissive=(0.1, 0.5, 0.7), rtt=True)
    hud = materials.Material("hud", "UIPlane", "screen", (0.01, 0.01, 0.01), holo=True)
    assert export.screen_fields(mon, 3)["name"] == "screen|mfd|g3|rtt"
    assert export.screen_fields(hud, 3)["name"] == "screen|hud|g3|holo"
    assert export.screen_fields(mon, None)["name"] == "screen|mfd|rtt"
    assert export.screen_fields(mon, 3)["emissive"] == [0.1, 0.5, 0.7]


def test_keyed_form_turns_bare_stencil_decals_into_hidden_decals():
    bare = _mat("livery", "hidden", (0, 0, 0), stencil_decal=True)
    mat, off = export.keyed_form(bare)
    assert mat.kind == "decal" and off
    fields = export.glb_material(mat, True, None, 1024, lite=True, group=2, off=True)[0]
    assert fields["name"] == "decal|livery||g2" and fields["alpha"] == 0.0 and fields["alpha_mode"] == "BLEND"
    assert not fields["visible"]
    assert export.keyed_form(_mat()) == (_mat(), False)
    painted = _mat("livery", "decal", (1, 1, 1), stencil_decal=True)
    assert export.glb_material(painted, True, None, 1024, lite=True, group=2)[0]["alpha_mode"] == "BLEND"


def _part(mat, mtl="a.mtl", mid=0, n=1, seed=0, node="", room=-1):
    rng = np.random.default_rng(seed)
    v = rng.random((3 * n, 3))
    f = np.arange(3 * n).reshape(-1, 3)
    uv = rng.random((3 * n, 2)).astype(np.float32)
    uv2 = rng.random((3 * n, 2)).astype(np.float32)
    return model.Part("p", mat, v, f, "x", uvs=uv, mtl_path=mtl, mat_id=mid, node=node, room=room, uvs2=uv2)


def _paint(colors, livery=True, camo=False):
    """A fake model in one paint: hull (2 parts, a.mtl #0), trim (a.mtl #1), glass (b.mtl #0), a livery sticker.
    camo: the hull paint has a stencil (camo) mask, as the Perseus camo paints have and its stock paint has not."""
    stencil = {"stencil_map": "camo.dds", "stencil": {"tiling": 1.0, "uv2": True, "opacity": 1.0,
                                                       "colors": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}} if camo else {}
    hull, trim = _mat("hull", color=colors[0], **stencil), _mat("trim", color=colors[1])
    glass = _mat("pane", "glass", colors[2])
    sticker = _mat("livery", "decal" if livery else "hidden", (1, 1, 1), stencil_decal=True)
    parts = [_part(hull, seed=1), _part(hull, seed=2), _part(trim, mid=1, seed=3), _part(glass, "b.mtl", seed=4),
             _part(sticker, "a.mtl", 2, seed=5)]
    return model.Model("ship.cga", parts=parts)


def test_merged_by_material_with_groups_keeps_paint_independent_meshes():
    a = _paint([(0.5, 0.5, 0.5), (0.5, 0.5, 0.5), (0.8, 0.8, 0.8)])
    groups = [0, 0, 1, 2, 3]
    today = export.merged_by_material(a.parts)
    keyed = export.merged_by_material(a.parts, paint_groups=groups)
    assert len(today) == 4 and len(keyed) == 4                          # hull, trim, glass, livery either way
    assert [item[-1] for item in keyed] == [0, 1, 2, 3]                 # the group comes last
    assert len(export.merged_by_material(a.parts, paint_groups=[0, 0, 0, 1, 2])) == 3


def test_two_paints_give_the_same_geometry():
    groups = [0, 0, 1, 2, 3]
    a = _paint([(0.5, 0.5, 0.5), (0.2, 0.2, 0.2), (0.8, 0.8, 0.8)], livery=False)
    b = _paint([(0.9, 0.1, 0.1), (0.9, 0.1, 0.1), (0.3, 0.3, 0.3)], camo=True)
    ga, gb = export.to_glb(a, lite=True, groups=groups), export.to_glb(b, lite=True, groups=groups)
    ja, jb = _glb_json(ga), _glb_json(gb)
    assert _glb_bin(ga) == _glb_bin(gb)
    assert ja["accessors"] == jb["accessors"] and [n["name"] for n in ja["nodes"]] == [n["name"] for n in jb["nodes"]]
    names = sorted(m["name"] for m in ja["materials"])
    assert all("|g" in n for n in names)
    off = next(m for m in ja["materials"] if m["name"].startswith("decal|livery|"))
    assert off["alphaMode"] == "BLEND" and off["pbrMetallicRoughness"]["baseColorFactor"][3] == 0.0
    sticker_node = next(n for n in ja["nodes"] if n["name"].startswith("decal|livery|"))
    assert "TEXCOORD_0" in ja["meshes"][sticker_node["mesh"]]["primitives"][0]["attributes"]
    hull_node = next(n for n in ja["nodes"] if n["name"].startswith("solid|hull|"))
    assert "_UV2" in ja["meshes"][hull_node["mesh"]]["primitives"][0]["attributes"]      # also without camo


def test_glb_without_groups_is_unchanged():
    a = _paint([(0.5, 0.5, 0.5), (0.2, 0.2, 0.2), (0.8, 0.8, 0.8)], livery=False)
    names = [m["name"] for m in _glb_json(export.to_glb(a, lite=True))["materials"]]
    assert not any("|g" in n for n in names)
    assert not any(n.startswith("decal|livery") for n in names)          # a bare sticker stays a hidden proxy


def test_groups_follow_the_material_slot():
    a = _paint([(0.5, 0.5, 0.5), (0.5, 0.5, 0.5), (0.8, 0.8, 0.8)])
    assert paints.group_keys(a) == [0, 0, 1, 2, 3]                       # equal colours, different slots: apart
    loose = model.Part("p", _mat("x"), np.zeros((3, 3)), np.arange(3).reshape(1, 3), "x")   # no .mtl: by material
    m = model.Model("m", parts=a.parts + [loose, loose])
    assert paints.group_keys(m)[-2:] == [4, 4]


def test_check_accepts_a_recoloured_paint():
    ref = _paint([(0.5, 0.5, 0.5), (0.2, 0.2, 0.2), (0.8, 0.8, 0.8)], livery=False)
    other = _paint([(0.9, 0.1, 0.1), (0.1, 0.9, 0.1), (0.3, 0.3, 0.3)], camo=True)  # sticker shows up, camo added
    assert paints.check(ref, other, paints.group_keys(ref))


def _recolour(m, i, **changes):
    parts = list(m.parts)
    parts[i] = model.Part(**{**parts[i].__dict__, "material": materials.Material(**{**parts[i].material.__dict__, **changes})})
    return model.Model(m.path, parts=parts)


def test_check_refuses_what_a_swap_cannot_do():
    ref = _paint([(0.5, 0.5, 0.5), (0.2, 0.2, 0.2), (0.8, 0.8, 0.8)])
    g = paints.group_keys(ref)
    assert not paints.check(ref, _recolour(ref, 2, kind="glass"), g)                       # kind
    assert not paints.check(ref, _recolour(ref, 2, name="other"), g)                       # name
    assert not paints.check(ref, _recolour(ref, 2, diffuse="t.dds", tiling=4.0), g)        # UV repeat
    assert not paints.check(ref, _recolour(ref, 0, color=(1, 0, 0)), g)                    # one part of a group alone
    assert not paints.check(ref, model.Model(ref.path, parts=ref.parts[:-1]), g)           # part count
    dec = _paint([(0.5, 0.5, 0.5), (0.2, 0.2, 0.2), (0.8, 0.8, 0.8)])
    dec.parts[2] = model.Part(**{**dec.parts[2].__dict__, "material": _mat("trim", "decal", (0.2, 0.2, 0.2))})
    see = model.Model(dec.path, parts=list(dec.parts))
    see.parts[2] = model.Part(**{**see.parts[2].__dict__, "material": _mat("trim", "decal", (0.2, 0.2, 0.2), opacity=0.5)})
    assert not paints.check(dec, see, paints.group_keys(dec))                              # decal turns see-through
    mon = materials.Material("mfd", "DisplayScreen", "screen", (0.01, 0.01, 0.01), rtt=True)
    assert paints._look(mon) != paints._look(materials.Material("mfd", "DisplayScreen", "screen", (0.01, 0.01, 0.01)))


def test_swatches():
    assert paints.swatches(None) is None
    assert paints.swatches({"A": [0, 0, 0], "B": [0, 0, 0], "C": [0, 0, 0]}) is None
    assert paints.swatches({"A": [100, 100, 100], "B": [150, 150, 150], "C": [174, 121, 31]}) == \
        [[100, 100, 100], [150, 150, 150], [174, 121, 31]]
    assert paints.swatches({"A": [1, 2, 3], "B": None, "C": [4, 5, 6]}) is None


def test_paint_table():
    ref = _paint([(0.5, 0.5, 0.5), (0.2, 0.2, 0.2), (0.8, 0.8, 0.8)], livery=False)
    g = paints.group_keys(ref)
    out = paints.paint_table(ref, g, None)
    groups, shading = out["groups"], out["shading"]
    assert len(groups) == 4 and groups[0]["name"].startswith("solid|hull|") and groups[0]["name"].endswith("|g0")
    assert groups[2]["name"] == "glass|pane||g2" and groups[2]["alpha_mode"] == "BLEND"
    assert groups[3]["name"] == "decal|livery||g3" and not groups[3]["visible"]
    sid = groups[0]["name"].split("|")[2]
    assert shading[sid] == materials.shading(ref.parts[0].material)
    assert paints.paint_table(ref, g, None, fixed_from=2)["groups"][1:] == [None, None, None]


def test_check_guards_its_inputs():
    ref = _paint([(0.5, 0.5, 0.5), (0.2, 0.2, 0.2), (0.8, 0.8, 0.8)])
    assert paints.check(ref, ref, paints.group_keys(ref))
    assert not paints.check(ref, ref, [])                                  # zip would stop early


def test_interior_parts_never_share_a_hull_group():
    ref = _paint([(0.5, 0.5, 0.5), (0.2, 0.2, 0.2), (0.8, 0.8, 0.8)])
    twin = ref.parts[0]                                                    # same .mtl slot and material as a hull part
    m = model.Model("m", parts=ref.parts + [twin])
    assert paints.group_keys(m)[-1] == paints.group_keys(m)[0]
    keys = paints.group_keys(m, fixed_from=len(ref.parts))
    assert keys[-1] not in keys[:-1] and keys[:-1] == paints.group_keys(ref)


def test_check_refuses_a_sticker_with_another_uv_repeat():
    ref = _paint([(0.5, 0.5, 0.5), (0.2, 0.2, 0.2), (0.8, 0.8, 0.8)])
    ref.parts[4].material.diffuse = "atlas.dds"
    other = _recolour(ref, 4, tiling=4.0)
    assert not paints.check(ref, other, paints.group_keys(ref))


def _table_vs_glb(m, groups):
    js = _glb_json(export.to_glb(m, lite=True, groups=groups))
    table = paints.paint_table(m, groups, None)["groups"]
    seen = 0
    for mat in js["materials"]:
        entry = table[int(mat["name"].rsplit("|g", 1)[1].split("|")[0])]
        assert entry is not None and entry["name"] == mat["name"]
        pbr = mat["pbrMetallicRoughness"]
        if "|rtt" in mat["name"] or "|holo" in mat["name"] or mat["name"].startswith("screen|"):
            assert entry["emissive"] == mat["emissiveFactor"]
        else:
            assert [*entry["color"], entry["alpha"]] == pbr["baseColorFactor"]
            assert entry["metallic"] == pbr["metallicFactor"] and entry["roughness"] == pbr["roughnessFactor"]
            assert entry["emissive"] == mat.get("emissiveFactor")
            assert entry["alpha_mode"] == mat.get("alphaMode", "OPAQUE")
        seen += 1
    return seen


def test_paint_table_matches_the_glb():
    b = _paint([(0.9, 0.1, 0.1), (0.9, 0.1, 0.1), (0.3, 0.3, 0.3)], camo=True)
    assert _table_vs_glb(b, paints.group_keys(b)) == 4
    mon = materials.Material("mfd", "DisplayScreen", "screen", (0.01, 0.01, 0.01), emissive=(0.1, 0.5, 0.7), rtt=True)
    hud = materials.Material("hud", "UIPlane", "screen", (0.01, 0.01, 0.01), holo=True)
    s = model.Model("s", parts=b.parts + [_part(mon, "c.mtl", 0, seed=6), _part(hud, "c.mtl", 1, seed=7)])
    assert _table_vs_glb(s, paints.group_keys(s)) == 6


def test_animated_keyed_glb_is_paint_independent():
    import zlib
    from types import SimpleNamespace
    from sc_explorer import caf, rig
    hull = rig.Bone("hull", -1, np.eye(4), np.eye(4))
    leg_w = np.eye(4)
    leg_w[:3, 3] = (0, 0, -1)
    leg = rig.Bone("leg", 0, leg_w.copy(), leg_w)
    clip = caf.Clip(caf.ClipInfo(0, 30, 1, 0, 30), {zlib.crc32(b"leg"): caf.Track(
        rot_t=np.array([0, 30], np.float32), rot=np.array([[0, 0, 0, 1], [0, 0, 0.7071, 0.7071]], np.float32))})
    sources = [("deploy", clip, {zlib.crc32(b"leg"): "leg"})]

    def build(colors, **kw):
        m = _paint(colors, **kw)
        parts = [model.Part(**{**p.__dict__, "node": "leg" if i in (1, 2) else "hull"}) for i, p in enumerate(m.parts)]
        return model.Model("ship.cga", parts=parts, skeleton=[hull, leg])

    groups = [0, 0, 1, 2, 3]
    a = build([(0.5, 0.5, 0.5), (0.2, 0.2, 0.2), (0.8, 0.8, 0.8)], livery=False)
    b = build([(0.9, 0.1, 0.1), (0.9, 0.1, 0.1), (0.3, 0.3, 0.3)], camo=True)
    ga = export.to_glb(a, lite=True, sources=sources, groups=groups)
    gb = export.to_glb(b, lite=True, sources=sources, groups=groups)
    ja, jb = _glb_json(ga), _glb_json(gb)
    assert "animations" in ja and _glb_bin(ga) == _glb_bin(gb)
    assert [n["name"] for n in ja["nodes"]] == [n["name"] for n in jb["nodes"]]
    assert all("|g" in m["name"] for m in ja["materials"])


def test_keyed_glb_keeps_rooms_apart_and_see_through_groups_whole():
    hull, glass = _mat("hull"), _mat("pane", "glass", (0.8, 0.8, 0.8))
    m = model.Model("m", parts=[_part(hull, seed=1, room=0), _part(hull, seed=2, room=1),
                                _part(glass, "b.mtl", seed=3, room=0), _part(glass, "b.mtl", seed=4, room=1)])
    js = _glb_json(export.to_glb(m, lite=True, groups=[0, 0, 1, 1]))
    nodes = [n["name"] for n in js["nodes"]]
    solid = [n for n in nodes if n.startswith("solid|hull|")]
    assert sorted(n.rsplit("|", 1)[1] for n in solid) == ["R0", "R1"]
    see = [n for n in nodes if n.startswith("glass|pane|")]
    assert len(see) == 1 and "|M" in see[0] and "r0s0n1" in see[0] and "r1s1n1" in see[0]
    assert sorted(x["name"] for x in js["materials"]) == [f"glass|pane||g1", f"solid|hull|{export._sid(hull)}|g0"]


def test_repaint_interior_swaps_the_hull_only():
    hull_a = _paint([(0.5, 0.5, 0.5), (0.2, 0.2, 0.2), (0.8, 0.8, 0.8)])
    hull_b = _paint([(0.9, 0.1, 0.1), (0.1, 0.9, 0.1), (0.3, 0.3, 0.3)])
    room = _part(_mat("floor"), "int.mtl", 0, seed=9, room=0)
    interior = model.Model("ship.cga", parts=list(hull_a.parts) + [room], rooms=[{"name": "bridge", "parts": 1}])
    out = assembly.repaint_interior(interior, hull_b, len(hull_a.parts))
    assert out.parts[:5] == hull_b.parts and out.parts[5] is room
    assert out.rooms == interior.rooms and out.cache == {} and out is not interior


def test_state_builds_the_interior_once_for_every_paint(monkeypatch):
    st = server.state
    hulls = {"m0": _paint([(0.5, 0.5, 0.5), (0.2, 0.2, 0.2), (0.8, 0.8, 0.8)]),
             "m1": _paint([(0.9, 0.1, 0.1), (0.1, 0.9, 0.1), (0.3, 0.3, 0.3)])}
    room = _part(_mat("floor"), "int.mtl", 0, seed=9, room=0)
    calls = []

    def fake_interior(archive, hull, vehicle, classes):
        calls.append(hull)
        return model.Model(hull.path, parts=list(hull.parts) + [room], rooms=[{"name": "bridge", "parts": 1}])

    vs = [{"tag": "0", "label": "Stock", "material": "m0", "palette": None, "stock": True},
          {"tag": "1", "label": "Red", "material": "m1", "palette": None, "stock": False}]
    monkeypatch.setattr(st, "variants", {"objects/ship.cga": vs})
    monkeypatch.setattr(st, "models", modelcache.ModelCache())
    monkeypatch.setattr(st, "can_interior", lambda p: True)
    monkeypatch.setattr(st, "can_full", lambda p: False)
    monkeypatch.setattr(st, "_base_model", lambda p, full=False: hulls["m0"])
    monkeypatch.setattr(server.model, "with_variant", lambda m, a, mtl, pal: hulls[mtl])
    monkeypatch.setattr(server.assembly, "load_interior", fake_interior)
    monkeypatch.setattr(server.entities, "vehicle_for", lambda idx, p: {})
    monkeypatch.setattr(server.entities, "classes_of", lambda idx: {})
    a = st.get_model("Objects/ship.cga", "0", False, True)
    b = st.get_model("Objects/ship.cga", "1", False, True)
    assert len(calls) == 1 and calls[0] is hulls["m0"]
    assert b.parts[:5] == hulls["m1"].parts and b.parts[5] is room and b.rooms == a.rooms
    assert st.get_model("Objects/ship.cga", None, False, True) is a
    assert st.get_model("Objects/ship.cga", "nope") is st.get_model("Objects/ship.cga", "0")


def test_livery_placeholders_keep_the_stock_material(monkeypatch):
    stock = [_mat("hull"), _mat("gear_metal"), _mat("gear_rubber")]
    livery = [_mat("hull_red", color=(1, 0, 0)), materials.Material("--", "Illum", "solid", (0.6, 0.6, 0.6))]
    files = {"a.mtl": stock, "livery.mtl": livery}
    monkeypatch.setattr(model, "_mtl", lambda archive, name: name)
    monkeypatch.setattr(model.materials, "load", lambda archive, path, palette=None: files[path])
    parts = [_part(stock[0], "a.mtl", 0, n=3, seed=1), _part(stock[1], "a.mtl", 1, seed=2),
             _part(stock[2], "a.mtl", 2, seed=3)]
    out = model.with_variant(model.Model("ship.cga", parts=parts), None, "livery.mtl", None)
    assert [p.material.name for p in out.parts] == ["hull_red", "gear_metal", "gear_rubber"]
