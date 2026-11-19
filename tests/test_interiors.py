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
    return entities.build(archive.read(dcb), entities.archive_reader(archive))


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


def test_lite_merge_joins_materials_the_game_look_draws_the_same():
    from sc_explorer.materials import Material
    from sc_explorer.model import Part
    a = Material("Paint", "Illum", "solid", (0.5, 0.5, 0.5), diffuse="paint_diff.dds", gloss=0.7)
    b = Material("Paint", "HardSurface", "solid", (0.5, 0.5, 0.5), diffuse="paint_diff.dds", gloss=0.7)
    c = Material("Paint", "Illum", "solid", (0.5, 0.5, 0.5), diffuse="paint_diff.dds", gloss=0.2)    # other gloss
    tri = np.array([[0, 1, 2]])
    parts = [Part(f"p{i}", m, np.eye(3, dtype=np.float32), tri, "test") for i, m in enumerate((a, b, c))]
    assert len(export.merged_by_material(parts)) == 3                 # user exports: every material on its own
    assert len(export.merged_by_material(parts, lite=True)) == 2      # viewer: a and b get the same game-look material


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


X1 = "Objects/Spaceships/Ships/ORIG/X1/ORIG_X1.cga"


def test_ports_flagged_invisible_are_not_drawn(archive, index):
    # the X1's vehicle XML flags its six GravLev ports "invisible": their items are 10 cm boxes that hung outside
    # the hull as dark blocks
    v = entities.vehicle_for(index, X1)
    grav = [n for n in v["tree"] if n["port"].startswith("hardpoint_gravlev")]
    assert len(grav) == 6 and all(n.get("hidden") for n in grav)
    assert not next(n for n in v["tree"] if n["port"] == "hardpoint_pilot_seat").get("hidden")
    m = assembly.load_full(archive, X1, v)
    assert not [p for p in m.parts if p.name.startswith("hardpoint_gravlev")]
    assert any(p.name.startswith("hardpoint_pilot_seat") for p in m.parts)      # the rest is still mounted


def test_displacement_mapped_pom_decals_shade_the_paint(archive):
    # Origin's Decal_POM_B uses %DISPLACEMENT_MAPPING instead of %PARALLAX_OCCLUSION_MAPPING: still a POM decal
    # (a multiplier over the paint), not a pale slab of its own colour
    m = model.load_model(archive, X1)
    pom = {p.material.name: p.material.pom for p in m.parts if p.material.name.startswith("Decal_POM")}
    assert pom.get("Decal_POM_A") and pom.get("Decal_POM_B")


def test_flat_pom_atlas_decals_shade_the_paint(archive):
    # the M50's Poms_EXT: a near-white "pom" atlas with only a normal map (no height) and MtlFlags bit 0x20000000,
    # drawn as colour it laid white outlines and logos over the red paint; the colour decals stay colour
    from sc_explorer import materials
    mats = {m.name: m for m in materials.load(archive, "Objects/Spaceships/Ships/ORIG/M50/ORIG_M50.mtl")}
    assert mats["Poms_EXT"].kind == "decal" and mats["Poms_EXT"].pom
    assert mats["decals"].kind == "decal" and not mats["decals"].pom


def test_decks_found_in_the_interior(archive, index):
    base = model.load_model(archive, PERSEUS)
    m = assembly.load_interior(archive, base, entities.vehicle_for(index, PERSEUS), entities.classes_of(index))
    d = assembly.decks(m)
    assert 3 <= len(d) <= 6 and all(b - a >= assembly.DECK_MIN_GAP for a, b in zip(d, d[1:]))


def test_port_and_file_names_that_differ_slightly():
    # a port and its node may differ by underscores; ambiguous or unrelated names are still not matched
    lookup = {"hardpoint_life_support": 3, "hardpoint_cooler_1": 4, "a_b": 5, "ab_": 6}
    assert assembly.find_port(lookup, "hardpoint_cooler_1") == 4
    assert assembly.find_port(lookup, "hardpoint_lifesupport") == 3
    assert assembly.find_port(lookup, "ab") is None and assembly.find_port(lookup, "hardpoint_radar") is None

    class Files:
        def exists(self, path):
            return path in ("a/screen.cgf", "a/door.cga", "a/both.cga", "a/both.cgf")
    assert assembly.twin(Files(), "a/screen.cga") == "a/screen.cgf"      # only the sibling exists
    assert assembly.twin(Files(), "a/door.cgf") == "a/door.cga"
    assert assembly.twin(Files(), "a/both.cga") == "a/both.cga"          # the named file wins
    assert assembly.twin(Files(), "a/none.cga") == "a/none.cga" and assembly.twin(Files(), "") == ""


def test_perseus_mounts_everything(archive, index):
    # the life support hangs from port hardpoint_lifesupport, a node spelled hardpoint_life_support; three screens of
    # the habs are placed as .cga and exist as .cgf: both used to be skipped, with a warning each
    v = entities.vehicle_for(index, PERSEUS)
    full = assembly.load_full(archive, PERSEUS, v, entities.adb_for(index, PERSEUS))
    assert not [w for w in full.warnings if w[0] == "warn_ports_missing"]
    assert any(p.name.startswith("hardpoint_lifesupport / ") for p in full.parts)
    m = assembly.load_interior(archive, full, v, entities.classes_of(index))
    assert not [w for w in m.warnings if w[0] == "warn_interior_missing"]
