"""Ship interiors (object containers) and the viewer's lite GLB. Needs Data.p4k."""
import json
import os
import struct
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sc_explorer import assembly, containers, entities, export, model  # noqa: E402
from sc_explorer.p4k import P4kArchive  # noqa: E402
from sc_explorer.server import CACHE_DIR, load_config  # noqa: E402

P4K = load_config()["p4k_path"]
pytestmark = pytest.mark.skipif(not os.path.isfile(P4K), reason="Data.p4k not found")
PERSEUS = "Objects/Spaceships/Ships/RSI/perseus/exterior/rsi_perseus.cga"


@pytest.fixture(scope="module")
def archive():
    a = P4kArchive(P4K, CACHE_DIR)
    a.load()
    return a


@pytest.fixture(scope="module")
def index(archive):
    dcb = next(n for n in archive.names if n.lower().endswith(".dcb"))
    return entities.build(archive.read(dcb))


def _glb_json(glb):
    n = struct.unpack_from("<I", glb, 12)[0]
    return json.loads(glb[20:20 + n])


def test_vehicle_lists_its_containers(index):
    v = entities.vehicle_for(index, PERSEUS)
    files = {c["file"].rsplit("/", 1)[-1] for c in v["containers"]}
    assert {"rsi_perseus_habs.socpak", "rsi_perseus_nose.socpak", "rsi_perseus_cargo.socpak"} <= files
    habs = next(c for c in v["containers"] if c["file"].endswith("habs.socpak"))
    assert habs["bone"] == "hardpoint_oc_habs" and habs["pos"] == [0.0, -12.0, -2.0]


def test_container_placements(archive, index):
    pl = containers.read(archive, "ObjectContainers/Ships/RSI/Perseus/rsi_perseus_habs.socpak",
                         entities.classes_of(index))
    brushes = [p for p in pl if p.kind == "brush"]
    ents = [p for p in pl if p.kind == "entity"]
    assert len(brushes) > 400 and len(ents) > 20
    for p in pl:
        scale = np.linalg.norm(p.matrix[:3, :3], axis=0)
        assert (scale > 0.01).all() and (scale < 100).all() and np.abs(p.matrix[:3, 3]).max() < 100


def test_interior_assembly(archive, index):
    base = model.load_model(archive, PERSEUS)
    m = assembly.load_interior(archive, base, entities.vehicle_for(index, PERSEUS), entities.classes_of(index))
    inner = [p for p in m.parts if p.name.startswith(assembly.INTERIOR_PREFIX)]
    assert len(inner) > 3000
    # LOD1 interior meshes use their LOD0's materials (LOD files name no .mtl): no fallback "matN" materials
    assert not [p for p in inner if p.material.name.startswith("mat") and not p.mtl_path]
    tri = sum(len(p.faces) for p in inner)
    assert 1_500_000 < tri < 5_000_000          # LOD1: about 3 M triangles instead of 7 M
    hull_lo, hull_hi = base.bounds()
    outside = [p for p in inner if (p.vertices.min(0) < hull_lo - 2).any() or (p.vertices.max(0) > hull_hi + 2).any()]
    assert len(outside) < len(inner) * 0.002      # the rooms sit inside the hull (a ladder .cga is still off)


def test_merge_by_material_content(archive):
    a = model.load_model(archive, "objects/spaceships/ships/rsi/perseus/interior/bunks/rsi_perseus_bunks_floor.cgf",
                         animated=False)
    b = model.load_model(archive, "objects/spaceships/ships/rsi/perseus/interior/bunks/rsi_perseus_bunks_floor.cgf",
                         animated=False)
    merged = export.merged_by_material(a.parts + b.parts)
    assert len(merged) == len(export.merged_by_material(a.parts))   # equal materials from two loads: one group


def test_lite_glb_has_uvs_but_no_normals_or_game_textures(archive):
    from sc_explorer import textures
    m = model.load_model(archive, "Objects/fps_weapons/weapons_v7/volt/smg/quartz/esmg_fps_volt_quartz.cdf")
    tc = textures.TextureCache(archive)
    full, lite = export.to_glb(m, textures=tc), export.to_glb(m, textures=tc, lite=True)
    jf, jl = _glb_json(full), _glb_json(lite)
    attrs = [p["attributes"] for mesh in jl["meshes"] for p in mesh["primitives"]]
    assert not any("NORMAL" in a for a in attrs) and any("TEXCOORD_0" in a for a in attrs)
    assert len(jl.get("images", [])) < len(jf.get("images", [])) and len(lite) < len(full)


NOX = "Objects/Spaceships/Ships/XIAN/Nox/XIAN_Nox.cga"


def test_invisible_loadout_items_are_skipped(archive, index):
    # the Nox's retro thrusters reuse the Vanduul Scythe's model dressed in an effects "transparent" material: in
    # game they are invisible, drawn as they are they were a big grey box over the tail
    v = entities.vehicle_for(index, NOX)
    retro = [n for n in v["tree"] if n["port"].startswith("hardpoint_thruster_retro")]
    assert retro and all(assembly.invisible(n["material"]) for n in retro)
    m = assembly.load_full(archive, NOX, v)
    mats = {p.material.name for p in m.parts}
    assert "vs_panels_a" not in mats and "base_metal" not in mats
    assert any(p.name.startswith("hardpoint_weapon_left") for p in m.parts)    # the rest is still mounted


def test_decks_found_in_the_interior(archive, index):
    base = model.load_model(archive, PERSEUS)
    m = assembly.load_interior(archive, base, entities.vehicle_for(index, PERSEUS), entities.classes_of(index))
    d = assembly.decks(m)
    assert 3 <= len(d) <= 6 and all(b - a >= assembly.DECK_MIN_GAP for a, b in zip(d, d[1:]))
