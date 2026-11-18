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
