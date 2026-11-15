"""Animation discovery and decoding against the installed game. Run:  python -m pytest tests  (skipped if Data.p4k is missing)."""
import os
import sys
import zlib

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sc_explorer import caf, dba, ivo  # noqa: E402
from sc_explorer.p4k import P4kArchive  # noqa: E402
from sc_explorer.server import CACHE_DIR, load_config  # noqa: E402

P4K = load_config()["p4k_path"]
pytestmark = pytest.mark.skipif(not os.path.isfile(P4K), reason="Data.p4k not found")

P6LR_ANIM = "Animations/fps_weapons/weapons_v7/behr/sniper/p6lr/"
GLADIUS = "Objects/Spaceships/Ships/AEGS/Gladius/AEGS_Gladius.cga"
GEAR_DBA = "Animations/Spaceships/Ships/AEGS/LandingGear/Gladius.dba"
SHIP_DBA = "Animations/Spaceships/Ships/AEGS/Gladius.dba"


def _info(*a, **k):
    """/api/model/info as a dict (the endpoint answers with ready-made JSON, cached on disk)."""
    import json
    from sc_explorer import server
    return json.loads(server.model_info(*a, **k).body)


@pytest.fixture(scope="module")
def archive():
    a = P4kArchive(P4K, CACHE_DIR)
    a.load()
    return a


def _names(f):
    return [b["name"] for b in ivo.bones(f)] or [n.name for n in ivo.nodes(f)]


# ------------------------------------------------------------------ .caf
def test_caf_clip(archive):
    c = caf.read(archive.read(P6LR_ANIM + "bsnp_behr_p6lr_fire_bolt_01.caf"))
    assert c.info.fps > 0 and c.info.duration > 0 and not c.info.additive
    assert c.tracks
    rots = [t.rot for t in c.tracks.values() if t.rot is not None]
    assert rots and all(np.allclose(np.linalg.norm(r, axis=1), 1, atol=1e-2) for r in rots)


def test_caf_additive(archive):
    assert caf.header(archive.read(P6LR_ANIM + "bsnp_behr_p6lr_has_ammo_pose.caf")).additive


# ------------------------------------------------------------------ .dba
def test_dba_landing_gear(archive):
    data = archive.read(GEAR_DBA)
    names = [n.rsplit("/", 1)[-1] for n in dba.headers(data)]
    assert len(names) == 9
    assert "landinggear_front_extend.caf" in names
    chr_ = ivo.IvoFile(archive.read("Objects/Spaceships/Ships/AEGS/LandingGear/Gladius/AEGS_Gladius_LandingGear_Front_CHR.chr"))
    bones = {zlib.crc32(n.encode()) for n in _names(chr_)}
    key = next(k for k in dba.headers(data) if k.endswith("/landinggear_front_extend.caf"))
    clip = dba.read(data, key)
    assert clip.info.duration > 0
    assert set(clip.tracks) <= bones


def test_dba_ship_nodes(archive):
    data = archive.read(SHIP_DBA)
    key = next(k for k in dba.headers(data) if k.endswith("/canopy_open.caf"))
    clip = dba.read(data, key)
    nodes = {zlib.crc32(n.encode()): n for n in _names(ivo.IvoFile(archive.read(GLADIUS)))}
    assert [nodes.get(h) for h in clip.tracks] == ["Canopy"]


# ------------------------------------------------------------------ DataCore index
@pytest.fixture(scope="module")
def entity_index(archive):
    from sc_explorer import entities
    dcb = next(n for n in archive.names if n.lower().endswith(".dcb"))
    return entities.build(archive.read(dcb))


P6LR = "Objects/fps_weapons/weapons_v7/behr/sniper/p6lr/bsnp_fps_behr_p6lr.cdf"


def test_entity_adb(entity_index):
    from sc_explorer import entities
    assert entities.adb_for(entity_index, GLADIUS).endswith("Gladius_SCItem/AEGS_Gladius_SCItem_Anims.adb")
    assert entities.adb_for(entity_index, P6LR).endswith("Items/Weapons/FPS/behr_sniper_ballistic_01.adb")


# ------------------------------------------------------------------ discovery
def test_find_ship(archive, entity_index):
    from sc_explorer import animations, entities
    refs = animations.find(archive, GLADIUS, entities.adb_for(entity_index, GLADIUS))
    by_id = {r.id: r for r in refs}
    assert len(refs) >= 25
    assert by_id["canopy/open"].clip == "canopy_close" and by_id["canopy/open"].speed < 0
    assert by_id["landing_gear/deploy"].clip == "landing_gear_extend"
    assert by_id["landing_gear/deploy"].dba.endswith("Gladius.dba")
    assert len(by_id) == len(refs)


def test_find_weapon(archive, entity_index):
    from sc_explorer import animations, entities
    refs = animations.find(archive, P6LR, entities.adb_for(entity_index, P6LR))
    ids = {r.id for r in refs}
    assert {"fire/bolt", "reload/full"} <= ids
    assert not any("has_ammo" in r.clip for r in refs)          # additive offsets are left out
    clips, warns = animations.load_clips(archive, refs)
    assert not warns and set(clips) == {r.clip for r in refs}


def test_find_none(archive):
    from sc_explorer import animations
    assert animations.find(archive, "Objects/fps_weapons/attachments/magazines/behr/mgzn_s03_behr_p6lr.cgf") == []


# ------------------------------------------------------------------ rig
def test_rig_static_models_unchanged(archive):
    from sc_explorer import model
    for path in ("Objects/fps_weapons/attachments/magazines/behr/mgzn_s03_behr_p6lr.cgf",
                 "Objects/Spaceships/Ships/AEGS/Gladius/AEGS_Gladius_Int.cga"):
        m = model.load_model(archive, path)
        assert not m.skeleton and not m.animations
        assert all(p.vbones is None or p.bone_names for p in m.parts)


def test_rig_weapon(archive, entity_index):
    from sc_explorer import entities, model
    m = model.load_model(archive, P6LR, entities.adb_for(entity_index, P6LR))
    names = {b.name for b in m.skeleton}
    assert "bolt" in names and m.animations
    assert any(p.node == "bolt" for p in m.parts)
    assert {p.node for p in m.parts} <= names | {""}
    v = model.with_variant(m, archive)
    assert v.animations == m.animations and v.skeleton is m.skeleton and v.cache is not m.cache


def test_rig_ship(archive, entity_index):
    from sc_explorer import entities, model
    m = model.load_model(archive, GLADIUS, entities.adb_for(entity_index, GLADIUS))
    assert any(p.node == "Canopy" for p in m.parts)
    assert {r.id for r in m.animations} >= {"canopy/open", "landing_gear/deploy"}


# ------------------------------------------------------------------ animated GLB
KINDS = {"solid", "glass", "decal", "hidden", "proxy"}


def _glb_json(glb):
    import json
    import struct
    length = struct.unpack_from("<I", glb, 12)[0]
    return json.loads(glb[20:20 + length])


@pytest.mark.parametrize("path", [P6LR, GLADIUS])
def test_animated_glb(archive, entity_index, path):
    from sc_explorer import animations, entities, export, model
    m = model.load_model(archive, path, entities.adb_for(entity_index, path))
    src, warns = animations.sources(archive, m)
    assert not warns
    js = _glb_json(export.to_glb(m, sources=src))
    assert js.get("animations")
    n_nodes = len(js["nodes"])
    for a in js["animations"]:
        for c in a["channels"]:
            assert 0 <= c["target"]["node"] < n_nodes
            assert "matrix" not in js["nodes"][c["target"]["node"]]
    mesh_nodes = [n["name"] for n in js["nodes"] if "mesh" in n]
    assert mesh_nodes and all(n.split("|")[0] in KINDS for n in mesh_nodes)
    if path == GLADIUS:
        names = {a["name"] for a in js["animations"]}
        assert {"canopy_close", "landing_gear_extend"} <= names


# ------------------------------------------------------------------ server
def test_server_animations():
    from sc_explorer import server
    if not server.state.status["ready"]:
        server.state.load()
    assert server.state.status["ready"], server.state.status
    info = _info(GLADIUS)
    by_id = {a["id"]: a for a in info["animations"]}
    assert by_id["canopy/open"]["speed"] < 0 and by_id["canopy/open"]["clip"] == "canopy_close"
    glb = server.model_glb(GLADIUS, tex=False).body
    assert b'"animations"' in glb and b"canopy_close" in glb
    assert b'"animations"' not in server.model_glb(GLADIUS, tex=False, anim=False).body
    assert _info("Objects/fps_weapons/attachments/magazines/behr/mgzn_s03_behr_p6lr.cgf")["animations"] == []


def test_find_tool_skips_additive_by_name(archive, entity_index):
    from sc_explorer import animations, entities
    path = "Objects/fps_weapons/gadgets/grin/multitool/gdgt_fps_grin_multitool.cdf"
    refs = animations.find(archive, path, entities.adb_for(entity_index, path))
    assert refs and not any(r.clip.endswith("_add") for r in refs)


def test_vehicle_loadout(entity_index):
    from sc_explorer import entities
    v = entities.vehicle_for(entity_index, GLADIUS)
    assert {g["port"] for g in v["gears"]} == {"helper_landing_gear_front", "helper_landing_gear_rear_left",
                                                "helper_landing_gear_rear_right"}
    ports = {n["port"].lower(): n for n in v["tree"]}
    assert ports["hardpoint_thruster_main_left"]["geometry"].lower().endswith(".cga")
    assert ports["hardpoint_gun_nose"]["children"]          # gimbal mount -> gun
    assert entities.vehicle_for(entity_index, P6LR) is None


# ------------------------------------------------------------------ full ship
SHIPS = [GLADIUS, "Objects/Spaceships/Ships/DRAK/Cutlass/DRAK_Cutlass_Black.cga",
         "Objects/Spaceships/Ships/AEGS/Avenger/AEGS_Avenger.cga", "Objects/Spaceships/Ships/RSI/Aurora/Exterior/RSI_Aurora.cga",
         "Objects/Spaceships/Ships/RSI/perseus/exterior/rsi_perseus.cga",
         "Objects/Spaceships/Ships/RSI/Polaris/Exterior/rsi_polaris.cga",
         "Objects/Spaceships/Ships/AEGS/Reclaimer/Exterior/AEGS_Reclaimer.cga"]   # per-leg clips with side suffixes


@pytest.mark.parametrize("path", SHIPS)
def test_full_ship_gear_follows_hull(archive, entity_index, path):
    from sc_explorer import animations, assembly, entities, model
    hull = model.load_model(archive, path, entities.adb_for(entity_index, path))
    full = assembly.load_full(archive, path, entities.vehicle_for(entity_index, path), entities.adb_for(entity_index, path))
    assert full.stats()["triangles"] > hull.stats()["triangles"]
    assert hull.stats()["triangles"] == model.load_model(archive, path).stats()["triangles"]   # hull untouched
    gear_ports = {g["port"] for g in entities.vehicle_for(entity_index, path)["gears"]}
    deploy = next(r for r in full.animations if "land" in r.group.lower() and r.label.lower() in ("deploy", "extend"))
    src, warns = animations.sources(archive, full)
    moved = {t[h] for n, c, t in src if n == deploy.clip for h in c.tracks if h in t}
    owners = {name.split("/")[0] if "/" in name else "" for name in moved}
    assert "" in owners and gear_ports <= owners          # the hull doors and every leg move together
    assert len({r.id for r in full.animations}) == len(full.animations)


def test_full_ship_glb(archive, entity_index):
    from sc_explorer import animations, assembly, entities, export
    full = assembly.load_full(archive, GLADIUS, entities.vehicle_for(entity_index, GLADIUS),
                              entities.adb_for(entity_index, GLADIUS))
    src, _ = animations.sources(archive, full)
    js = _glb_json(export.to_glb(full, sources=src))
    ext = next(a for a in js["animations"] if a["name"] == "landing_gear_extend")
    names = {js["nodes"][c["target"]["node"]]["name"].split("/")[0] for c in ext["channels"]}
    assert {"helper_landing_gear_front", "helper_landing_gear_rear_left", "helper_landing_gear_rear_right"} <= names


def test_server_full_flag():
    from sc_explorer import server
    if not server.state.status["ready"]:
        server.state.load()
    info = _info(GLADIUS, full=True)
    assert info["can_full"] and info["full"]
    assert info["stats"]["triangles"] > _info(GLADIUS)["stats"]["triangles"]
    assert not _info(P6LR, full=True)["can_full"]


PERSEUS = "Objects/Spaceships/Ships/RSI/perseus/exterior/rsi_perseus.cga"
POLARIS = "Objects/Spaceships/Ships/RSI/Polaris/Exterior/rsi_polaris.cga"


@pytest.mark.parametrize("path", [PERSEUS, POLARIS])
def test_full_ship_gear_meshes_follow_animated_nodes(archive, entity_index, path):
    """Meshes sitting on child nodes of an animated node (RSI legs: anim_leg -> geo_*) must hang under it in the GLB,
    or the leg stays out while its joints move."""
    from sc_explorer import animations, assembly, entities, export
    full = assembly.load_full(archive, path, entities.vehicle_for(entity_index, path), entities.adb_for(entity_index, path))
    src, _ = animations.sources(archive, full)
    js = _glb_json(export.to_glb(full, sources=src))
    nodes = js["nodes"]
    parent = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}
    deploy = next(r for r in full.animations if "land" in r.group.lower() and r.label.lower() == "deploy")
    anim = next(a for a in js["animations"] if a["name"] == deploy.clip)
    animated = {c["target"]["node"] for c in anim["channels"]}
    gear_ports = {g["port"] for g in entities.vehicle_for(entity_index, path)["gears"]}

    def tris(i):
        mesh = js["meshes"][nodes[i]["mesh"]]
        return sum(js["accessors"][pr["indices"]]["count"] // 3 for pr in mesh["primitives"])

    for port in gear_ports:
        total = sum(len(p.faces) for p in full.parts if p.name.startswith(port + " /") and p.material.kind != "hidden")
        moving = 0
        for i, n in enumerate(nodes):
            if "mesh" not in n:
                continue
            j, chain = i, []
            while j in parent:
                j = parent[j]
                chain.append(j)
            if any(nodes[k]["name"].startswith(port + "/") for k in chain) and any(k in animated for k in chain):
                moving += tris(i)
        assert moving > total * 0.9, (port, moving, total)    # all but the mounting bracket (node 0 used to stay behind)


def test_adb_fragment_fallback(archive, entity_index):
    """Polaris: the first Landing_Gear fragments name the legs' clip; the hull's (Landing_Deploy, -1 for Retract)
    come after and must be used. Gladius: the untagged Compress only repeats Deploy and is not offered."""
    from sc_explorer import animations, entities
    refs = {r.id: r for r in animations.find(archive, POLARIS, entities.adb_for(entity_index, POLARIS))}
    assert refs["landing_gear/deploy"].clip == "Landing_Deploy" and refs["landing_gear/deploy"].speed > 0
    assert refs["landing_gear/retract"].clip == "Landing_Deploy" and refs["landing_gear/retract"].speed < 0
    gl = {r.id: r for r in animations.find(archive, GLADIUS, entities.adb_for(entity_index, GLADIUS))}
    assert "landing_gear/compress" not in gl


def test_planar_positions_no_jump(archive):
    """0xC2 positions are stored axis by axis: read key by key, the Perseus leg sat still for half the clip, jumped
    4 m up and came down again. The deploy must start where the retract ends and move smoothly."""
    from sc_explorer import animations
    leg = next(n for n in archive.names if n.replace("\\", "/").lower().endswith(
        "landinggear/perseus/rsi_perseus_landing_gear_back_left.cga")).replace("\\", "/")[5:]
    refs = [r for r in animations.find(archive, leg) if r.clip in ("landing_gear_deploy", "landing_gear_retract")]
    clips, _ = animations.load_clips(archive, refs)
    h = zlib.crc32(b"anim_leg")
    dep, ret = clips["landing_gear_deploy"].tracks[h], clips["landing_gear_retract"].tracks[h]
    assert np.abs(np.diff(dep.pos, axis=0)).max() < 0.5
    assert np.allclose(dep.pos[0], ret.pos[-1], atol=0.05) and np.allclose(dep.pos[-1], ret.pos[0], atol=0.05)


# ------------------------------------------------------------------ stencil decals and glow
def test_stencil_decal_uses_paint_atlas():
    """Quartz: stencil_decal ($TintPaletteDecal) used to be exported without texture -> black slabs on the magazine
    well. With the paint's stencil atlas the big quads are transparent (empty atlas area) and the small one shows
    the VOLT logo; without a paint the stencil is not drawn at all."""
    from sc_explorer import export, model, server
    if not server.state.status["ready"]:
        server.state.load()
    arch = server.state.archive
    q = next(n for n in arch.names if n.replace("\\", "/").lower().endswith(
        "smg/quartz/esmg_fps_volt_quartz.cdf")).replace("\\", "/")[5:]
    m = server.state.get_model(q)
    sten = [p for p in m.parts if p.material.name == "stencil_decal"]
    assert sten and all(p.material.stencil_colors and p.material.kind == "decal" for p in sten)
    img, _, _ = export.material_textures(sten[0].material, server.state.textures, 1024)
    assert img is not None and img.mode == "RGBA"
    a = np.asarray(img)[..., 3]
    h, w = a.shape
    big = max(sten, key=lambda p: np.ptp(p.vertices, 0).max())
    uv = big.uvs
    # the 148 mm quads: their atlas area is empty (transparent), like in the game
    tri = big.faces[np.argmax(np.ptp(big.vertices[big.faces].reshape(-1, 9), 1))]
    x0, y0 = (uv[tri].min(0) * [w, h]).astype(int)
    x1, y1 = (uv[tri].max(0) * [w, h]).astype(int)
    assert (a[y0:y1, x0:x1] > 128).mean() < 0.05
    plain = model.load_model(arch, q)                     # no paint -> nothing to draw
    assert all(p.material.kind == "hidden" for p in plain.parts if p.material.name == "stencil_decal")
    glow = next(p.material for p in m.parts if p.material.name == "glow_mat")
    assert glow.emissive and max(glow.emissive) > 0.5


def test_screens_and_ammo():
    """DisplayScreen materials become lit screens (emissive picture in the GLB); weapons report their magazine
    capacity so the viewer can draw the ammo count on them."""
    from sc_explorer import export, server
    if not server.state.status["ready"]:
        server.state.load()
    arch = server.state.archive
    q = next(n for n in arch.names if n.replace("\\", "/").lower().endswith(
        "smg/quartz/esmg_fps_volt_quartz.cdf")).replace("\\", "/")[5:]
    info = _info(q)
    assert info["ammo"] == {"max": 45, "low": pytest.approx(0.1)}
    assert info["screen"]["accent"].startswith("#") and info["screen"]["maker"]
    js = _glb_json(server.model_glb(q, tex=False).body)
    screens = [m for m in js["materials"] if m["name"].startswith("screen|")]
    assert screens and all("emissiveTexture" in m and max(m["emissiveFactor"]) > 0.3 for m in screens)
    assert any(n["name"].startswith("screen|") for n in js["nodes"] if "mesh" in n)
    assert _info(GLADIUS)["ammo"] is None
