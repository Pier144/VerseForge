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
