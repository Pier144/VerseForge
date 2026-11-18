"""Instant paint switching: paint groups, the swap check, paint tables (sc_explorer/paints.py) and the keyed GLB."""
import json
import os
import struct
import sys
import xml.etree.ElementTree as ET

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sc_explorer import export, materials, model  # noqa: E402

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
