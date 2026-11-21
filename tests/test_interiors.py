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


NOVA = "Objects/Vehicles/TMBL/Nova/TMBL_Nova.cga"


def test_tank_treads_and_wheels_are_mounted(archive, index):
    # treads and road wheels are not loadout items: the vehicle's implementation XML hangs them on the hull
    # (<Part class="Tread">, <Part class="SubPartWheel">); the wheels that only exist for the physics stay out
    v = entities.vehicle_for(index, NOVA)
    fixed = {f["port"]: f["geometry"].lower() for f in v["fixed"]}
    assert fixed["hardpoint_tread_left"].endswith("tmbl_nova_tread_left.cdf")
    assert not [g for g in fixed.values() if "hidden" in g or "invisible" in g]
    m = assembly.load_full(archive, NOVA, v)
    assert any(p.name.startswith("hardpoint_tread_left") and len(p.vertices) > 1000 for p in m.parts)
    assert any(p.name.startswith("hardpoint_wheel") for p in m.parts)


def test_items_on_ports_a_clip_forgets_follow_their_rack(archive, index):
    # the Nova's missile reload lowers the rack and moves four of its missile ports (201-204); the other ports hang
    # from the launcher's root, and their missiles stayed in the air: they follow the rack that holds them
    m = assembly.load_full(archive, NOVA, entities.vehicle_for(index, NOVA))
    parents = {b.name: m.skeleton[b.parent].name for b in m.skeleton if b.name.endswith("/FSKI_Ignite_S2")}
    one = "hardpoint_primary_turret/hardpoint_missile_launcher/hardpoint_s1_missile_"
    assert parents[one + "201/FSKI_Ignite_S2"].endswith("hardpoint_s1_missile_201")
    assert parents[one + "101/FSKI_Ignite_S2"].endswith("4x_missile_launcher_02")
    assert parents[one + "304/FSKI_Ignite_S2"].endswith("4x_missile_launcher_02")


AVENGER = "Objects/Spaceships/Ships/AEGS/Avenger/AEGS_Avenger.cga"


def test_tagged_port_gets_the_geometry_of_its_side(index):
    # one item, AEGS_Avenger_Thruster_Retro, sits on both retro ports: its main geometry is the left flap and a
    # SubGeometry tagged "right" the mirrored one, picked by the port's "right" flag. Mounted as the left one, the
    # right flap hung askew under the wing root
    v = entities.vehicle_for(index, AVENGER)
    geo = {n["port"]: n["geometry"].lower() for n in v["tree"]}
    assert geo["hardpoint_thruster_left_retro"].endswith("aegs_avenger_thruster_retro_left.cga")
    assert geo["hardpoint_thruster_right_retro"].endswith("aegs_avenger_thruster_retro_right.cga")


def test_port_tags_of_a_vehicle_definition():
    xml = (b'<Vehicle><Parts><Part name="hull" class="Animated"><Parts>'
           b'<Part name="hardpoint_retro_R" class="ItemPort"><ItemPort flags="maneuver uneditable Right"/></Part>'
           b'<Part name="hardpoint_seat" class="ItemPort"><ItemPort/></Part>'
           b'</Parts></Part></Parts></Vehicle>')
    assert entities.vehicle_port_tags(xml) == {"hardpoint_retro_r": frozenset({"maneuver", "uneditable", "right"})}


def test_lod_files_are_placed_by_the_nodes_of_lod0(archive):
    # a _lod1 file has no node table: its pieces are in the space of the LOD0's nodes. Read without them, the three
    # blocks of the Avenger's cockpit were shifted and stuck out through the canopy
    stem = "Objects/Spaceships/Ships/AEGS/Avenger/Interior/aegs_avenger_cockpit"
    lod0 = model.load_model(archive, stem + ".cgf", animated=False)
    lod1 = model.load_model(archive, stem + "_lod1.cgf", animated=False)
    (lo0, hi0), (lo1, hi1) = lod0.bounds(), lod1.bounds()
    assert np.abs(lo1 - lo0).max() < 0.05 and np.abs(hi1 - hi0).max() < 0.05
    assert {p.node for p in lod1.parts} <= {p.node for p in lod0.parts} and all(p.node for p in lod1.parts)
    for p in lod1.parts:                                    # each piece inside the same piece of the LOD0
        same = [q.vertices for q in lod0.parts if q.node == p.node and q.mat_id == p.mat_id]
        assert same, p.name
        v = np.vstack(same)
        assert (p.vertices.min(0) > v.min(0) - 0.05).all() and (p.vertices.max(0) < v.max(0) + 0.05).all(), p.name


def test_lod_name():
    assert model.lod0_path("a/b/ship_lod1.cgf") == "a/b/ship.cgf" and model.lod0_path("a/Ship_LOD12.cga") == "a/Ship.cga"
    assert model.lod0_path("a/b/ship.cgf") is None and model.lod0_path("a/lod1_ship.cgf") is None


def _interior_reach(archive, index, path):
    """How far (metres) the interior parts of a ship reach beyond its hull."""
    base = model.load_model(archive, path)
    m = assembly.load_interior(archive, base, entities.vehicle_for(index, path), entities.classes_of(index))
    hull = np.vstack([p.vertices for p in base.parts])
    inner = np.vstack([p.vertices for p in m.parts[len(base.parts):]])
    return float(max((hull.min(0) - inner.min(0)).max(), (inner.max(0) - hull.max(0)).max()))


def test_editor_placeholders_are_not_part_of_an_interior(archive, index):
    # the Basher's light container holds two editor primitives (objects/default/box_noproxy.cgf, primitive_cube.cgf)
    # parked a kilometre away: the ship was framed as a dot
    assert _interior_reach(archive, index, "Objects/Spaceships/Ships/GLSN/Basher/GLSN_Basher.cga") < 3


def test_lod_file_that_does_not_fit_its_lod0_is_not_used(archive, index):
    # misc_fortune_personal_storage_lod1.cga keeps its button in another space than the rest (20 m away)
    assert _interior_reach(archive, index, "Objects/Spaceships/Ships/MISC/fortune/misc_fortune.cga") < 3


def test_objects_parked_far_from_the_ship_are_left_out(archive, index):
    # the game's containers hold a few objects left far from the ship (a Carrack panel 75 m to the side, a Hammerhead
    # screen 100 m ahead, a Clipper light bar 6 m out): they widened the model's box and the ship was framed small
    assert _interior_reach(archive, index, "Objects/Spaceships/Ships/DRAK/clipper/exterior/drak_clipper.cga") < 3


def test_ports_without_a_node_are_placed_by_their_offset(archive, index):
    # the MOLE carries sixteen spare ore pods on ports no node of its model has: the game places each by an offset
    # from the root (DataCore: AttachmentImplementation.Helper). They were "factory parts not mounted"
    path = next(p for p in index["vehicles"] if p.endswith("argo_mole.cga"))
    v = entities.vehicle_for(index, path)
    pod = next(n for n in v["tree"] if n["port"] == "hardpoint_stored_pod_1")
    assert pod["place"]["pos"] == pytest.approx([-1.5, 6.5, -3.227], abs=1e-3)
    m = assembly.load_full(archive, path, v)
    pods = [p for p in m.parts if p.name.startswith("hardpoint_stored_pod_")]
    assert len({p.name.split(" / ")[0] for p in pods}) == 16
    first = np.vstack([p.vertices for p in pods if p.name.startswith("hardpoint_stored_pod_1 /")])
    mid = (first.min(0) + first.max(0)) / 2
    assert abs(mid[0] + 1.5) < 1.0 and abs(mid[1] - 6.5) < 2.0 and abs(mid[2] + 3.2) < 1.5
    assert not [w for w in m.warnings if w[0] == "warn_ports_missing"]


def test_offset_placed_items_stay_with_the_ship(archive, index):
    # the 890 Jump's lifts, hangar door and PDC turrets have no node in its model: placed by their offsets they sit in
    # and on the hull; the 25 m poles of the entrance lift, drawn at rest 12 m below the ship, are left out
    path = next(p for p in index["vehicles"] if p.endswith("orig_890jump.cga"))
    v = entities.vehicle_for(index, path)
    hull = model.load_model(archive, path)
    m = assembly.load_full(archive, path, v)
    lo = np.min([p.vertices.min(0) for p in hull.parts if len(p.vertices) and p.material.kind != "hidden"], axis=0)
    hi = np.max([p.vertices.max(0) for p in hull.parts if len(p.vertices) and p.material.kind != "hidden"], axis=0)
    for port in ("hardpoint_hangar_door", "hardpoint_cargo_lift", "hardpoint_entrance_lift", "hardpoint_PDC_01"):
        got = [p.vertices for p in m.parts if p.name.startswith(port + " /") and p.material.kind != "hidden"]
        assert got, port
        pv = np.vstack(got)
        assert (pv.min(0) > lo - 3).all() and (pv.max(0) < hi + 3).all(), port
