"""User skins on real models (needs Data.p4k): a ship, a weapon, an armour piece and a model with a single paint.
A skin must be swappable in place of the reference paint, colour what it names (entries of the palette, single
materials with a colour of their own), leave the rest alone, and reach the exported GLB."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sc_explorer import entities, export, materials, model, paints, skins, variants  # noqa: E402
from sc_explorer.p4k import P4kArchive  # noqa: E402
from sc_explorer.server import CACHE_DIR, load_config  # noqa: E402
from test_paints import _glb_json  # noqa: E402

P4K = load_config()["p4k_path"]
pytestmark = pytest.mark.skipif(not os.path.isfile(P4K), reason="Data.p4k not found")

MODELS = {
    "ship": "objects/spaceships/ships/aegs/gladius/aegs_gladius.cga",
    "weapon": "objects/fps_weapons/weapons_v7/volt/smg/quartz/esmg_fps_volt_quartz.cdf",
    "armour": "objects/characters/human/male_v7/armor/fta/m_fta_medium_helmet_01_prop.cdf",
    "single": "objects/fps_weapons/grenades/ksar/frag/ksar_gren_frag_01.cga",
}
RED = [255, 0, 0]


@pytest.fixture(scope="module")
def game():
    a = P4kArchive(P4K, CACHE_DIR)
    a.load()
    dcb = next(n for n in a.names if n.lower().endswith(".dcb"))
    data = a.read(dcb)
    return a, variants.build(data, {}), entities.build(data, entities.archive_reader(a))


def _load(game, kind):
    a, vs_all, index = game
    path = next(n for n in a.names if n.replace("\\", "/").lower().endswith(MODELS[kind]))
    path = path.replace("\\", "/")
    path = path[5:] if path.lower().startswith("data/") else path
    vs = vs_all.get(MODELS[kind], [])
    base = model.load_model(a, path, entities.adb_for(index, path))
    paint = lambda v: model.with_variant(base, a, v["material"], v["palette"])   # noqa: E731
    return a, vs, base, paint


def _slots(m):
    """Tint slots of the model's visible paint layers: "A"/"B"/"C" (palette) and "m:<material>" (own colour)."""
    return sorted({p.material.tint["slot"] for p in m.parts if p.material.tint and p.material.kind == "solid"})


def _skin_for(slot, finish):
    if slot.startswith("m:"):
        return {"name": "t", "materials": {slot[2:]: {"color": RED, "finish": {"preset": finish}}}}
    return {"name": "t", "palette": {slot: RED, "finish": {slot: {"preset": finish}}}}


@pytest.mark.parametrize("kind", ["ship", "weapon", "armour", "single"])
def test_a_skin_swaps_in_and_colours_what_it_names(game, kind):
    a, vs, base, paint = _load(game, kind)
    assert vs, "the model has paints in DataCore"
    ref = paint(vs[0])
    groups = paints.group_keys(ref)
    start = vs[min(1, len(vs) - 1)]                      # another paint than the reference one when there is one
    before = paint(start)
    slots = _slots(before)
    assert slots, "some material can be recoloured"
    # one palette entry (when the model uses the palette) and one material with its own colour (when it has any)
    picks = [s for s in slots if not s.startswith("m:")][:1] + [s for s in slots if s.startswith("m:")][:1]
    for slot in picks:
        painted = paint(skins.apply(start, skins.validate({**_skin_for(slot, "matte"), "target": {"model": "x"}}), "skin:t"))
        assert paints.check(ref, painted, groups), f"{slot}: a skin is swapped in like a paint"
        lin = materials.palette_linear(RED)
        hit = [p.material for p in painted.parts if p.material.tint and p.material.tint["slot"] == slot
               and p.material.kind == "solid"]
        assert hit
        for m in hit:
            sh = materials.shading(m)
            assert sh["albedo"] == pytest.approx([b * c for b, c in zip(m.tint["base"], lin)], abs=1e-4), (slot, m.name)
            assert sh["gloss"] == pytest.approx(skins.PRESETS["matte"] / 255, abs=1e-3)
            assert sh["spec"] == pytest.approx(materials.palette_linear(skins.DIELECTRIC), abs=1e-4)
            assert not sh["spec_map"]                    # the skin sets the reflectance: no map left to multiply it
        # everything else keeps the colour of the paint the skin starts from
        for p, q in zip(before.parts, painted.parts):
            t = q.material.tint
            if not t or t["slot"] != slot:
                assert q.material.color == pytest.approx(p.material.color, abs=1e-6), (slot, q.material.name)


def test_armour_is_coloured_material_by_material(game):
    a, vs, base, paint = _load(game, "armour")
    own = [s for s in _slots(paint(vs[0])) if s.startswith("m:")]
    assert len(own) >= 3, "armour pieces carry their colours in the materials, not in the palette"
    for p in paint(vs[0]).parts:
        t = p.material.tint
        if t and t["slot"].startswith("m:") and p.material.kind == "solid":
            # the colour shown in the Skin Lab (sRGB, gamma 2) gives back the material's own tint
            back = materials.palette_linear(t["own"])
            want = [c / b if b else 0 for c, b in zip(materials.shading(p.material)["albedo"], t["base"])]
            assert back == pytest.approx(want, abs=0.012), p.material.name


@pytest.mark.parametrize("kind", ["ship", "weapon", "armour"])
def test_a_skin_without_changes_looks_like_its_base_paint(game, kind):
    a, vs, base, paint = _load(game, kind)
    for v in vs[:4]:
        same = paint(skins.apply(v, {"name": "t", "palette": {}}, "skin:t"))
        for p, q in zip(paint(v).parts, same.parts):
            assert q.material.color == pytest.approx(p.material.color, abs=1e-6), (v["label"], p.material.name)
            assert q.material.kind == p.material.kind and q.material.diffuse == p.material.diffuse


def test_the_exported_glb_carries_the_skins_colour(game):
    a, vs, base, paint = _load(game, "ship")
    slot = next(s for s in _slots(paint(vs[0])) if not s.startswith("m:"))
    stock = paint(vs[0])
    painted = paint(skins.apply(vs[0], {"name": "t", "palette": {slot: RED}}, "skin:t"))
    names = {p.material.name for p in painted.parts if p.material.tint and p.material.tint["slot"] == slot
             and p.material.kind == "solid"}
    colours = lambda m: {x["name"]: x["pbrMetallicRoughness"]["baseColorFactor"][:3]      # noqa: E731
                         for x in _glb_json(export.to_glb(m, include_hidden=False, textures=None))["materials"]}
    was, now = colours(stock), colours(painted)
    reds = [n for n in now if n in names or (n.split("|")[1:2] or [""])[0] in names]
    assert reds, sorted(now)[:5]
    for n in reds:
        r, g, b = now[n]
        assert g < r * 0.2 and b < r * 0.2, n
    assert any(now[n] != was.get(n) for n in reds)
