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


def test_decal_opacity_and_pom(archive):
    mats = {m.name: m for m in materials.load(archive, "Objects/Spaceships/Ships/RSI/perseus/rsi_perseus_a.mtl")}
    pom = mats["Decal_POM_A"]
    assert pom.kind == "decal" and pom.pom and pom.height_map.lower().endswith("_displ.tif")
    assert mats["Decal_Dirt"].opacity == pytest.approx(0.08, abs=1e-3) and not mats["Decal_Dirt"].pom
    assert mats["Decal_Text"].opacity == pytest.approx(0.3, abs=1e-3)
    sh = materials.shading(pom)
    assert sh["pom"] and sh["height_map"] and sh["alpha_test"] > 0.5


def test_armour_does_not_load_the_player_animation_set(archive):
    # armour shares the human skeleton: it must not pull in thousands of body clips (loading took minutes)
    from sc_explorer import model
    m = model.load_model(archive, "Objects/Characters/Human/male_v7/armor/qrt/quirinus/m_qrt_utility_heavy_core_01.cdf")
    assert m.parts and not m.anim_sets and not m.animations


NOX_MTL = "Objects/Spaceships/Ships/XIAN/Nox/XIAN_Nox.mtl"


def test_illum_pom_decals_shade_the_paint(archive):
    # Aopoa/Xi'an POM decals use Illum + %DECAL: a near-white multiplier atlas, not white or black slabs
    mats = {m.name: m for m in materials.load(archive, NOX_MTL)}
    for name in ("decals_pom", "decals_pom2"):
        assert mats[name].kind == "decal" and mats[name].pom and mats[name].height_map is None
    assert not mats["decals_diff"].pom          # plain colour decal, no parallax


def test_ui_planes_are_screens(archive):
    # UIPlane: the Nox's dashboard screens are lit screens, its flight HUD a see-through holographic veil
    mats = {m.name: m for m in materials.load(archive, NOX_MTL)}
    assert mats["screen_rtt"].kind == "screen" and not mats["screen_rtt"].holo
    assert mats["UI_HUD_RTT"].kind == "screen" and mats["UI_HUD_RTT"].holo


def test_material_name_with_dash(archive):
    # the KLWE repeater names "KLWE_las_rep_s1_3"; the file is Weapons/KLWE/KLWE_las_rep_s1-3.mtl, two folders up
    geo = "Objects/Spaceships/Weapons/KLWE/KLWE_Merged_Weapons/KLWE_Las_Rep_S1/KLWE_Las_Rep_S1_L1.cga"
    p = materials.resolve_path(archive, geo, "KLWE_las_rep_s1_3")
    assert p and p.lower() == "objects/spaceships/weapons/klwe/klwe_las_rep_s1-3.mtl"
    assert materials.resolve_path(archive, geo, "no_such_material_xyz") is None


def test_empty_decals_are_hidden(archive):
    # a texture-less placeholder and the live ship-name decal ($RenderToTexture) were white slabs on the hull
    mats = {m.name: m for m in materials.load(
        archive, "Objects/Spaceships/Ships/DRAK/Cutlass/cutlass_black/DRAK_Cutlass_Black.mtl")}
    assert mats["decal_placeholder"].kind == "hidden" and mats["RTT_Text_To_Decal"].kind == "hidden"
    assert mats["Decals_EXT"].kind == "decal" and mats["POM_EXT"].kind == "decal"


def test_hull_damage_layer_is_hidden(archive):
    # girders and cables under the skin, shown in game only where the hull is shot through: with an intact hull they
    # showed through it from a distance (Anvil Hawk)
    mats = {m.name: m for m in materials.load(archive, NOX_MTL)}
    assert mats["internal_mesh"].kind == "hidden" and mats["internal_pom"].kind == "hidden"
    assert materials.classify("internal_framework", "Illum") == "solid"     # real framework stays


def test_pom_in_a_name_is_a_decal_only_with_the_decal_flag():
    # "pom" also names surfaces with relief (thruster nozzles, grates, trims, ramps): without %DECAL they are solid
    # geometry, which vanished with the Decals switch off
    assert materials.classify("Thruster_POM", "Illum", "%NORMAL_MAP%PARALLAX_OCCLUSION_MAPPING") == "solid"
    assert materials.classify("trim_greeble_nopom", "HardSurface", "") == "solid"
    assert materials.classify("internal_pom_new", "HardSurface", "") == "solid"
    assert materials.classify("Decal_POM_A", "Illum", "%NORMAL_MAP%DECAL%PARALLAX_OCCLUSION_MAPPING") == "decal"
    # the damage layer under the skin: drawn, it covered the 890 Jump's white hull in black patches
    assert materials.classify("internal_damage_pom", "Illum", "") == "hidden"
    assert materials.classify("pom_glow", "Illum", "") == "decal"                # other decal words still count


def test_glass_takes_the_paints_glass_colour(archive):
    # GlassPBR %USE_TINT_PALETTE: the paint's glass colour replaces the Diffuse (the Gladius' gold 0.82,0.55,0.25 is
    # its default paint's 234,195,136 in sRGB); the Frostbite paint has a blue canopy in game
    path = "Objects/Spaceships/Ships/AEGS/Gladius/AEGS_Gladius.mtl"
    plain = {m.name: m for m in materials.load(archive, path)}
    frost = {m.name: m for m in materials.load(archive, path, {"glass": [93, 122, 161]})}
    assert plain["glass_ext"].color[0] > plain["glass_ext"].color[2]           # gold
    assert frost["glass_ext"].color == materials.srgb_to_linear((93, 122, 161))  # blue
    assert frost["glass_int"].color == plain["glass_int"].color                 # no %USE_TINT_PALETTE: unchanged


def test_glass_look_hides_behind_dark_glass_and_keeps_clear_glass_clear():
    from sc_explorer.materials import Material
    visor = Material("Glass_NoRefract", "GlassPBR", "glass", (0.107, 0.107, 0.107))
    pane = Material("glass_int", "GlassPBR", "glass", (0.77, 0.84, 0.73))
    assert materials.glass_look(visor)[1] > 0.85 and materials.glass_look(pane)[1] < 0.3


def test_tint_darkens_the_reflection_of_spec_mapped_layers(archive):
    # the Perseus bridge frames: HardSurface over RSI_panel_primary_a_metal_worn_rusted_a (TintMode 1, a copper-brown
    # _spec map, TintColor 0.032, GlossMult 0) = dark worn metal; untinted the reflection shone like rust
    mats = materials.load(archive, "Objects/Spaceships/Ships/RSI/perseus/rsi_perseus_interior_a.mtl")
    m = next(x for x in mats if x.name == "Panel_Main_LF_Paint_Primary")
    assert m.spec_map and "rusted" in m.spec_map and max(m.spec) < 0.05


def test_uv_sets_have_no_infinite_values(archive):
    # the 400i front landing gear holds half floats that decode to infinity in its second UV set (13 vertices):
    # they went into the GLB as "max":[Infinity,...], which no JSON reader accepts, and the ship did not open
    from sc_explorer import ivo
    md = ivo.mesh(ivo.IvoFile(archive.read(
        "Objects/Spaceships/Ships/ORIG/LandingGear/400i/ORIG_400i_LandingGear_Front_SKIN.skinm")), True)
    assert md.uvs2 is not None and np.isfinite(md.uvs2).all()
    assert md.uvs is None or np.isfinite(md.uvs).all()
