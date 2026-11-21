"""Custom decals of user skins (sc_explorer/skindecals.py): a text on the name plates, a picture on the livery slots.
On made-up quads; the last test needs Data.p4k (the Liberator)."""
import io
import os
import sys
import xml.etree.ElementTree as ET

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sc_explorer import materials, model, skindecals, skins, textures  # noqa: E402

PLATE = ('<Material Name="RTT_Text_To_Decal" Shader="MeshDecal" Diffuse="1,1,1"><Textures>'
         '<Texture Map="TexSlot1" File="$RenderToTexture"/></Textures></Material>')
LOGO = ('<Material Name="Decal_Branding" Shader="MeshDecal" Diffuse="1,1,1" StringGenMask="%STENCIL_MAP"><Textures>'
        '<Texture Map="TexSlot7" File="textures/logo_stencil.tif"/></Textures></Material>')
HULL = '<Material Name="hull" Shader="Illum" Diffuse="0.5,0.5,0.5"/>'


def _quad(mat, x0, w, h, uv_box):
    """A flat quad w x h metres whose corners take the corners of a UV box."""
    u0, v0, u1, v1 = uv_box
    verts = np.array([[x0, 0, 0], [x0 + w, 0, 0], [x0 + w, 0, -h], [x0, 0, -h]], np.float32)
    uvs = np.array([[u0, v0], [u1, v0], [u1, v1], [u0, v1]], np.float32)
    return model.Part("q", mat, verts, np.array([[0, 1, 2], [0, 2, 3]]), "t", uvs=uvs)


def _model():
    plate = materials._material(ET.fromstring(PLATE), None, None)
    logo = materials._material(ET.fromstring(LOGO), None, None)
    hull = materials._material(ET.fromstring(HULL), None, None)
    parts = [_quad(plate, 0, 6.0, 1.0, (0.0, 0.0, 1.0, 0.0625)), _quad(plate, 10, 6.0, 1.0, (0.0, 0.0, 1.0, 0.0625)),
             _quad(plate, 20, 2.0, 0.5, (0.0, 0.75, 1.0, 1.0)), _quad(logo, 30, 2.0, 2.0, (0.5, 0.5, 1.0, 1.0)),
             _quad(hull, 40, 1.0, 1.0, (0, 0, 1, 1))]
    return model.Model("m.cga", parts=parts)


def _png(color=(255, 0, 0, 255)):
    buf = io.BytesIO()
    Image.new("RGBA", (64, 64), color).save(buf, "PNG")
    return buf.getvalue()


def test_the_game_s_open_slots_are_marked():
    plate = materials._material(ET.fromstring(PLATE), None, None)
    logo = materials._material(ET.fromstring(LOGO), None, None)
    # never drawn as they are (the game fills them at run time), but known as sticker slots
    assert plate.kind == "hidden" and plate.stencil_decal and plate.rtt and skindecals.kind_of(plate) == "text"
    assert logo.kind == "hidden" and logo.stencil_decal and not logo.rtt and skindecals.kind_of(logo) == "image"
    assert skindecals.kind_of(materials._material(ET.fromstring(HULL), None, None)) is None
    assert skindecals.slots(_model()) == {"text": 3, "image": 1}


def test_islands_know_their_region_and_proportions():
    m = _model()
    (u0, v0, u1, v1, aspect), = skindecals._islands(m.parts[0])
    assert (u0, v0, u1, v1) == pytest.approx((0.0, 0.0, 1.0, 0.0625)) and aspect == pytest.approx(6.0, rel=1e-3)
    assert skindecals._islands(m.parts[2])[0][4] == pytest.approx(4.0, rel=1e-3)
    assert skindecals._islands(m.parts[3])[0][4] == pytest.approx(1.0, rel=1e-3)


def test_a_slot_cut_into_quads_is_one_region():
    def at(x0, x1):
        return np.array([x0, 0.0, 0.0]), np.array([x1, 0.0, 2.0])
    # a 4 x 2 m slot made of two quads side by side, another on its own, and a copy of the first (the other side)
    isl = [(0.0, 0.0, 0.25, 0.25, 1.0, *at(0, 2)), (0.25, 0.0, 0.5, 0.25, 1.0, *at(2, 4)),
           (0.6, 0.6, 1.0, 0.8, 3.0, *at(10, 16)), (0.0, 0.0, 0.25, 0.25, 1.0, *at(50, 52))]
    regions = sorted(skindecals._regions(isl))
    assert len(regions) == 2 and [sorted(r[2]) for r in regions] == [[0, 1, 3], [2]]
    assert regions[0][0] == pytest.approx((0.0, 0.0, 0.5, 0.25)) and regions[0][1] == pytest.approx(2.0)
    assert regions[1][0] == pytest.approx((0.6, 0.6, 1.0, 0.8)) and regions[1][1] == pytest.approx(3.0)
    # neighbours in the texture that are far apart on the ship are two slots of the game's atlas
    assert len(skindecals._regions([(0.0, 0.0, 0.25, 0.25, 1.0, *at(0, 2)), (0.25, 0.0, 0.5, 0.25, 1.0, *at(30, 32))])) == 2
    # a small slot inside a wide one (the game's atlas) is not a piece of it, even next to it on the ship
    assert len(skindecals._regions([(0.0, 0.0, 1.0, 0.5, 4.0, *at(0, 4)), (0.1, 0.1, 0.3, 0.3, 1.0, *at(4, 5))])) == 2
    # boxes that only meet at a corner stay apart
    assert len(skindecals._regions([(0.0, 0.0, 0.5, 0.5, 1.0, *at(0, 2)), (0.5, 0.5, 1.0, 1.0, 1.0, *at(2, 4))])) == 2


def test_text_and_picture_go_on_their_slots():
    m = _model()
    out = skindecals.decorate(m, {"text": {"value": "r/StarCitizen", "color": [255, 255, 255]}, "image": {"file": "images/a.png"}},
                              None, lambda name: _png())
    plate, logo, hull = out.parts[0].material, out.parts[3].material, out.parts[4].material
    assert plate.kind == "decal" and plate.diffuse.startswith("skinimg:") and plate.stencil_decal
    assert out.parts[1].material.diffuse == plate.diffuse == out.parts[2].material.diffuse      # one picture per material
    assert logo.kind == "decal" and logo.diffuse.startswith("skinimg:") and logo.diffuse != plate.diffuse
    assert hull == m.parts[4].material and m.parts[0].material.kind == "hidden"                 # the model given is untouched
    # the sheet is the skin's own: one cell per slot (two kinds of plate: a row each), the quads moved onto them
    sheet = np.asarray(textures.TextureCache(None).get(plate.diffuse, 2048))
    assert sheet.shape == (2048, 2048, 4)
    alpha = sheet[..., 3]
    assert alpha[:1024].any() and alpha[1024:].any()
    long, short = out.parts[0].uvs, out.parts[2].uvs
    assert long.min() > 0 and long[:, 0].max() > 0.99 and long[:, 1].max() < 0.5 and np.allclose(long, out.parts[1].uvs)
    assert short[:, 1].min() > 0.5 and short.max() < 1
    assert np.allclose(m.parts[0].uvs[:, 1].max(), 0.0625)                                      # not the model's own
    # the picture, whole and in proportion, fills the logo's cell (the only one of its sheet)
    pic = np.asarray(textures.TextureCache(None).get(logo.diffuse, 2048))
    ys, xs = np.nonzero(pic[..., 3])
    assert (xs.min() + xs.max()) / 2 == pytest.approx(1024, abs=4) and (xs.max() - xs.min()) == pytest.approx(ys.max() - ys.min(), abs=4)
    assert tuple(pic[1024, 1024]) == (255, 0, 0, 255)
    assert out.parts[3].uvs.min() > 0 and out.parts[3].uvs.max() < 1
    # smaller on request, like any texture
    assert textures.TextureCache(None).get(plate.diffuse, 512).size == (512, 512)


def test_several_pictures_share_the_slots():
    # the shape decides: a long plate on the long slots, a square on the square ones
    assert skindecals._assign([5.7, 0.66, 5.7, 0.66], [1.0, 4.0]) == [1, 0, 1, 0]
    # two pictures that suit a slot about as well take turns
    assert skindecals._assign([1.0, 1.0, 1.0, 1.0], [1.0, 1.1]) == [0, 1, 0, 1]
    # none is left out while a slot can be spared: the wide stamp takes one of the two squares' slots
    got = skindecals._assign([5.7, 0.66, 5.7, 0.66], [1.75, 1.0, 4.0])
    assert sorted(set(got)) == [0, 1, 2] and got[0] == got[2] == 2
    assert skindecals._assign([1.0, 2.0], [1.0]) == [0, 0]
    # the empty border of a picture does not count
    img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    img.paste((255, 0, 0, 255), (10, 40, 90, 60))
    assert skindecals._trimmed(img).size == (80, 20)
    # two logo slots, one on each side with the same piece of the atlas: one picture each
    logo = materials._material(ET.fromstring(LOGO), None, None)
    m = model.Model("m.cga", parts=[_quad(logo, 0, 2.0, 2.0, (0.5, 0.5, 1.0, 1.0)), _quad(logo, 30, 2.0, 2.0, (0.5, 0.5, 1.0, 1.0))])
    pics = {"images/a.png": _png((255, 0, 0, 255)), "images/b.png": _png((0, 0, 255, 255))}
    out = skindecals.decorate(m, {"image": {"file": "images/a.png"}, "images": [{"file": "images/b.png"}]}, None, pics.get)
    sheet = np.asarray(textures.TextureCache(None).get(out.parts[0].material.diffuse, 2048))
    seen = {tuple(sheet[y, x]) for x, y in ((512, 1024), (1536, 1024))}
    assert seen == {(255, 0, 0, 255), (0, 0, 255, 255)}
    assert not np.allclose(out.parts[0].uvs, out.parts[1].uvs)
    ok = skins.validate({"name": "s", "target": {"model": "m.cga"}, "decals": {"images": [{"file": "images/b.png"}]}})
    assert ok["decals"] == {"images": [{"file": "images/b.png"}]}
    with pytest.raises(skins.SkinError):
        skins.validate({"name": "s", "target": {"model": "m.cga"}, "decals": {"images": [{"file": "../b.png"}]}})


def test_nothing_asked_nothing_changed():
    m = _model()
    assert skindecals.decorate(m, {}, None, None) is m
    assert skindecals.decorate(m, {"image": {"file": "images/a.png"}}, None, lambda name: None) is m     # picture missing
    only_text = skindecals.decorate(m, {"text": {"value": "X"}}, None, None)
    assert only_text.parts[0].material.kind == "decal" and only_text.parts[3].material.kind == "hidden"
    # a text in capitals and one with small letters both draw something
    for text in ("ABC", "abc"):
        tile = skindecals._text_tile(None, text, [255, 255, 255], 6.0)
        assert tile.size == (1536, 256) and np.asarray(tile)[..., 3].any()


def test_a_skin_s_decals_are_validated():
    base = {"name": "s", "target": {"model": "m.cga"}}
    ok = skins.validate({**base, "decals": {"text": {"value": "  r/StarCitizen  "}, "image": {"file": "images/logo.png"}, "x": 1}})
    assert ok["decals"] == {"text": {"value": "r/StarCitizen", "color": [235, 235, 235]}, "image": {"file": "images/logo.png"}, "x": 1}
    assert skins.validate({**base, "decals": {"text": {"value": "   "}}})["decals"] == {}
    assert len(skins.validate({**base, "decals": {"text": {"value": "a" * 99}}})["decals"]["text"]["value"]) == skins.TEXT_MAX
    for bad in ({"image": {"file": "../x.png"}}, {"image": {"file": "images/x.exe"}}, {"text": "hi"},
                {"text": {"value": "a", "color": [1]}}, []):
        with pytest.raises(skins.SkinError):
            skins.validate({**base, "decals": bad})
    assert skins.apply(None, ok, "skin:x")["decals"] == ok["decals"]


def test_pictures_live_in_the_skin_file(tmp_path):
    lib = str(tmp_path)
    s = skins.save(lib, {"name": "s", "target": {"model": "m.cga"}})
    assert skins.set_image(lib, s["id"], "images/logo.png", _png()) == "images/logo.png"
    assert skins.read_image(lib, s["id"], "images/logo.png") == _png()
    assert skins.read_image(lib, s["id"], "images/none.png") is None and skins.read_image(lib, s["id"], "skin.json") is None
    skins.set_image(lib, s["id"], "images/logo.png", _png((0, 255, 0, 255)))                      # replaced, not doubled
    assert skins.read_image(lib, s["id"], "images/logo.png") == _png((0, 255, 0, 255))
    again = skins.save(lib, {**s, "decals": {"image": {"file": "images/logo.png"}}})              # saving keeps it
    assert skins.read_image(lib, again["id"], "images/logo.png") == _png((0, 255, 0, 255))
    with pytest.raises(skins.SkinError):
        skins.set_image(lib, "00000000", "images/logo.png", _png())
    with pytest.raises(skins.SkinError):
        skins.set_image(lib, s["id"], "images/../x.png", _png())


def test_the_liberator_has_plates_and_logo_slots():
    from sc_explorer.p4k import P4kArchive
    from sc_explorer.server import CACHE_DIR, load_config
    p4k = load_config()["p4k_path"]
    if not os.path.isfile(p4k):
        pytest.skip("Data.p4k not found")
    a = P4kArchive(p4k, CACHE_DIR)
    a.load()
    want = "objects/spaceships/ships/anvl/liberator/exterior/anvl_liberator.cga"
    path = next(n.replace("\\", "/")[5:] for n in a.names if n.replace("\\", "/").lower().endswith(want))
    base = model.load_model(a, path, None)
    assert skindecals.slots(base) == {"text": 5, "image": 4}
    out = skindecals.decorate(base, {"text": {"value": "r/StarCitizen"}}, a, None)
    plates = [p for p in out.parts if (p.material.diffuse or "").startswith("skinimg:")]
    assert len(plates) == 3 and all(p.material.name == "RTT_Text_To_Decal" for p in plates)
    assert np.asarray(textures.custom_image(plates[0].material.diffuse, 2048))[..., 3].any()
    assert all(0 < p.uvs.min() and p.uvs.max() < 1 for p in plates)
