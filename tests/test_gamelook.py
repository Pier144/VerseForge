"""Game-look shading: gloss maps, spec/gloss from paints and layers, camo paints kept solid. Needs Data.p4k."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sc_explorer import materials, textures  # noqa: E402
from sc_explorer.p4k import P4kArchive  # noqa: E402
from sc_explorer.server import CACHE_DIR, load_config  # noqa: E402

P4K = load_config()["p4k_path"]
pytestmark = pytest.mark.skipif(not os.path.isfile(P4K), reason="Data.p4k not found")

QUARTZ_MTL = "Objects/fps_weapons/weapons_v7/volt/smg/quartz/esmg_fps_volt_quartz_mat.mtl"
VOLT_DEFAULT = {"A": [35, 53, 66], "B": [35, 53, 66], "C": [109, 92, 50],
                "spec": {"A": [64, 101, 126], "B": [64, 101, 126], "C": [127, 108, 34]},
                "gloss": {"A": 248, "B": 244, "C": 223}}


@pytest.fixture(scope="module")
def archive():
    a = P4kArchive(P4K, CACHE_DIR)
    a.load()
    return a


def test_gloss_from_separate_alpha_file(archive):
    # _ddna gloss lives in <name>.dds.a (+ .dds.<n>a), a DDS header without the magic
    g = textures.TextureCache(archive).gloss(
        "objects/fps_weapons/weapons_v7/volt/smg/quartz/textures/esmg_fps_volt_quartz_ddna.tif", 256)
    assert g is not None and g.mode == "L" and g.size == (256, 256)
    a = np.asarray(g)
    assert a.std() > 3 and 100 < a.mean() < 230


def test_palette_sets_spec_and_gloss(archive):
    mats = {m.name: m for m in materials.load(archive, QUARTZ_MTL, VOLT_DEFAULT)}
    paint = mats["H_plastic_pattern_01_A"]           # PaletteTint 2 -> entry B
    assert paint.spec == pytest.approx(materials.palette_linear([64, 101, 126]))
    assert paint.gloss == pytest.approx(244 / 255)
    assert paint.albedo[2] > paint.albedo[0]         # dark slate blue
    sh = materials.shading(paint)
    assert sh["gloss_map"] and sh["obj_gloss"] and sh["hal"] and sh["tiling"] > 1


def test_metal_layer_has_black_albedo_and_bright_spec(archive):
    m = {m.name: m for m in materials.load(archive, QUARTZ_MTL, VOLT_DEFAULT)}["H_metal_brushed_01_A"]
    assert max(m.albedo) < 0.05 and min(m.spec) > 0.3


def test_layer_spec_map(archive):
    mats = {m.name: m for m in materials.load(archive, "Objects/Spaceships/Ships/RSI/perseus/rsi_perseus_a.mtl")}
    m = mats["Panel_Main_LF_Primary_Metal"]
    assert m.spec_map and m.spec_map.lower().endswith("_spec.tif") and m.spec_tiled


def test_camo_paint_stays_solid(archive):
    # HardSurface + %STENCIL_MAP is a camo paint, not a stencil sticker: it must not vanish from the hull
    pal = {"A": [34, 34, 34], "B": [81, 81, 81], "C": [50, 50, 50], "decal": None}
    mats = {m.name: m for m in materials.load(archive, "Objects/Spaceships/Ships/RSI/perseus/rsi_perseus_g.mtl", pal)}
    assert mats["Panel_LF_Paint_Primary_A"].kind == "solid"


def test_camo_stencil_params(archive):
    pal = {"A": [182, 54, 42], "B": [182, 182, 182], "C": [26, 26, 26]}
    mats = {m.name: m for m in materials.load(archive, "Objects/Spaceships/Ships/RSI/perseus/rsi_perseus_g.mtl", pal)}
    m = mats["Panel_LF_Paint_Primary_A"]
    assert m.stencil_map.lower().endswith("camo_digi_stencil_01_mask.dds")
    assert m.stencil["uv2"] and m.stencil["tiling"] == 4.0
    assert m.stencil["colors"][0] == pytest.approx(materials.palette_linear([182, 54, 42]), abs=1e-4)


def test_legacy_rgb_dds_mask(archive):
    # camo masks are 24-bit RGB DDS without a FourCC (R/G/B = three camo layers)
    img, _ = textures._decode(archive, "objects/spaceships/textures/stencils/camo_digi_stencil_01_mask.dds", 256)
    assert img is not None and img.mode == "RGB" and img.size == (256, 256)
    a = np.asarray(img)
    for ch in range(3):
        assert 0.15 < (a[..., ch] > 127).mean() < 0.6


def test_second_uv_set(archive):
    from sc_explorer import ivo
    md = ivo.mesh(ivo.IvoFile(archive.read("Objects/Spaceships/Ships/RSI/perseus/exterior/rsi_perseus.cgam")), True)
    assert md.uvs2 is not None and md.uvs2.shape == (len(md.positions), 2)
    assert md.uvs2.min() > -0.1 and md.uvs2.max() < 1.1      # an atlas, unlike the tiling first set
