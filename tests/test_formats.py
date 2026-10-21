"""Integration tests against the installed game. Run:  python -m pytest tests  (skipped if Data.p4k is missing)."""
import io
import json
import os
import struct
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sc_explorer import catalog, export, model, textures, variants  # noqa: E402
from sc_explorer.p4k import P4kArchive  # noqa: E402
from sc_explorer.server import CACHE_DIR, load_config  # noqa: E402

P4K = load_config()["p4k_path"]
pytestmark = pytest.mark.skipif(not os.path.isfile(P4K), reason="Data.p4k non trovato")


@pytest.fixture(scope="module")
def archive():
    a = P4kArchive(P4K, CACHE_DIR)
    a.load()
    return a


def test_cdf_weapon_assembly(archive):
    m = model.load_model(archive, "Objects/fps_weapons/weapons_v7/behr/rifle/p4ar/brfl_fps_behr_p4ar.cdf")
    s = m.stats()
    assert s["triangles"] > 20000
    assert 0.6 < s["size_m"][1] < 0.8          # P4-AR is ~68 cm long


def test_multi_node_ship(archive):
    m = model.load_model(archive, "Objects/Spaceships/Ships/AEGS/Gladius/AEGS_Gladius.cga")
    s = m.stats()
    assert s["triangles"] > 200000
    assert 15 < s["size_m"][1] < 30            # assembled hull, not parts piled at the origin


def test_exports(archive):
    m = model.load_model(archive, "Objects/fps_weapons/attachments/magazines/behr/mgzn_s03_behr_5rb_01.cgf")
    assert export.to_glb(m)[:4] == b"glTF"
    assert len(export.to_stl(m)) > 1000
    assert export.to_obj_zip(m, "mag")[:2] == b"PK"


def test_textures(archive):
    tc = textures.TextureCache(archive)
    normal = tc.get("Objects/Spaceships/Ships/AEGS/Gladius/textures/vent_metal_ddna.tif", 256, normal=True)
    assert normal.size == (256, 256) and normal.mode == "RGB"
    assert normal.getextrema()[0][0] < 100      # signed BC5 decoded, not flattened to grey
    m = model.load_model(archive, "Objects/fps_weapons/weapons_v7/behr/rifle/p4ar/brfl_fps_behr_p4ar.cdf")
    glb = export.to_glb(m, textures=tc, tex_size=256)
    n = struct.unpack_from("<I", glb, 12)[0]
    gltf = json.loads(glb[20:20 + n])
    assert len(gltf["images"]) > 5
    assert any("normalTexture" in mat for mat in gltf["materials"])
    with zipfile.ZipFile(io.BytesIO(export.to_obj_zip(m, "p4ar", textures=tc, tex_size=256))) as z:
        assert any(name.startswith("textures/") for name in z.namelist())
        assert "\nvt " in z.read("p4ar.obj").decode()


def test_paint_variants(archive):
    dcb = next(n for n in archive.names if n.lower().endswith(".dcb"))
    index = variants.build(archive.read(dcb), catalog.localization(archive))
    quartz = index["objects/fps_weapons/weapons_v7/volt/smg/quartz/esmg_fps_volt_quartz.cdf"]
    assert quartz[0]["palette"]["name"] == "volt_weapon_default"        # default paint first
    camo = next(v for v in quartz if "Jungle Camo" in v["label"])
    assert camo["material"].endswith("collector_01_mat.mtl")
    m = model.load_model(archive, "Objects/fps_weapons/weapons_v7/volt/smg/quartz/esmg_fps_volt_quartz.cdf")
    painted = model.with_variant(m, archive, quartz[0]["material"], quartz[0]["palette"])
    colors = {p.material.name: p.material.color for p in painted.parts}
    assert max(colors["H_plastic_02_A"]) < 0.2                           # palette colour, not the grey fallback


def test_catalog_search(archive):
    items = catalog.build(archive, catalog.game_names(archive))
    hits, _ = catalog.search(items, "p4-ar")
    assert hits and hits[0].name == "P4-AR Rifle"
    ships, _ = catalog.search(items, "gladius", "navi")
    assert any(it.path.endswith("AEGS_Gladius.cga") for it in ships)
