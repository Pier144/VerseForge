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
