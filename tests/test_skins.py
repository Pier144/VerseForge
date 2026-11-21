"""Skin files and the paint a skin makes (sc_explorer/skins.py)."""
import io
import json
import os
import zipfile

import pytest

from sc_explorer import skins

MODEL = "objects/spaceships/ships/rsi/perseus/rsi_perseus.cga"


def skin(**over):
    s = {"name": "Night Raid", "target": {"model": MODEL, "label": "Perseus"},
         "base": {"material": "ships/perseus_black.mtl", "palette": "black", "label": "Black"},
         "palette": {"A": [10, 20, 30]}}
    s.update(over)
    return s


PAL = {"name": "black", "A": [1, 2, 3], "B": [40, 50, 60], "C": [200, 210, 220], "glass": [9, 9, 9],
       "spec": {"A": [80, 80, 80], "B": None, "C": [60, 60, 60]}, "gloss": {"A": 200, "B": None, "C": 30},
       "decal": "decals/atlas.dds", "decal_colors": [[1, 1, 1], None, None]}


# ---------------------------------------------------------------- validate

def test_validate_tidies_and_keeps_unknown_fields():
    out = skins.validate(skin(name="  Night   Raid ", future={"x": 1},
                              palette={"A": [10.4, 20, 30], "B": None, "weird": 5, "finish": {"A": {"preset": "matte"}}}))
    assert out["name"] == "Night Raid"
    assert out["palette"]["A"] == [10, 20, 30] and "B" not in out["palette"]
    assert out["palette"]["weird"] == 5 and out["future"] == {"x": 1}
    assert out["palette"]["finish"] == {"A": {"preset": "matte"}}
    assert out["pattern"] is None and out["decals"] == {} and out["format"] == 1


@pytest.mark.parametrize("bad", [
    {"name": ""}, {"name": 5}, {"target": {}}, {"target": None}, {"palette": {"A": [1, 2]}},
    {"palette": {"A": [1, 2, 300]}}, {"palette": {"glass": "red"}}, {"palette": {"finish": {"A": {"preset": "chrome"}}}},
    {"palette": {"finish": {"D": {"preset": "matte"}}}}, {"palette": {"finish": {"A": {"gloss": 900}}}},
    {"id": "nope"}, {"format": "1"}, {"base": {"material": 3}},
])
def test_validate_refuses(bad):
    with pytest.raises(skins.SkinError) as e:
        skins.validate(skin(**bad))
    assert e.value.code == "invalid"


def test_validate_material_colours():
    out = skins.validate(skin(materials={"Props_M": {"color": [1, 2, 3], "finish": {"preset": "gloss"}},
                                         "empty": {}, "Fin": {"finish": {"gloss": 10}}}))
    assert out["materials"] == {"props_m": {"color": [1, 2, 3], "finish": {"preset": "gloss"}},
                                "fin": {"finish": {"preset": "base", "gloss": 10}}}
    assert skins.validate(skin())["materials"] == {}
    for bad in ({"m": {"color": [1]}}, {"m": {"finish": {"preset": "x"}}}, {"m": 3}, [1]):
        with pytest.raises(skins.SkinError):
            skins.validate(skin(materials=bad))


def test_effective_material_colours():
    s = skins.validate(skin(palette={}, materials={
        "Props_M": {"color": [200, 100, 50]}, "Steel": {"color": [200, 100, 50], "finish": {"preset": "metal"}},
        "Fin": {"finish": {"preset": "matte"}}, "Same": {"finish": {"preset": "base"}}}))
    out = skins.effective(PAL, s)["materials"]
    assert out["props_m"] == {"color": [200, 100, 50], "spec": None, "gloss": None}       # the material's own finish
    assert out["steel"] == {"color": [40, 20, 10], "spec": [200, 100, 50], "gloss": skins.PRESETS["metal"]}
    assert out["fin"] == {"color": None, "spec": skins.DIELECTRIC, "gloss": skins.PRESETS["matte"]}
    assert "same" not in out
    assert "materials" not in skins.effective(PAL, skin(palette={}))


def test_validate_refuses_a_newer_format():
    with pytest.raises(skins.SkinError) as e:
        skins.validate(skin(format=skins.FORMAT + 1))
    assert e.value.code == "newer"


# ---------------------------------------------------------------- the paint a skin makes

def test_effective_without_changes_is_the_base_paint_made_complete():
    out = skins.effective(PAL, skin(palette={}))
    assert (out["A"], out["B"], out["C"], out["glass"]) == ([1, 2, 3], [40, 50, 60], [200, 210, 220], [9, 9, 9])
    assert out["spec"]["A"] == [80, 80, 80] and out["gloss"]["A"] == 200
    # an entry the paint leaves open gets a plain satin paint, so every entry is complete
    assert out["spec"]["B"] == skins.DIELECTRIC and out["gloss"]["B"] == skins.PRESETS["satin"]
    assert out["decal"] == "decals/atlas.dds" and out["decal_colors"] == PAL["decal_colors"] and out["name"] == "black"


def test_effective_presets():
    fin = {"A": {"preset": "gloss"}, "B": {"preset": "matte", "gloss": 77}, "C": {"preset": "metal"}}
    out = skins.effective(PAL, skin(palette={"A": [100, 0, 0], "C": [200, 100, 50], "glass": [5, 6, 7], "finish": fin}))
    assert out["A"] == [100, 0, 0] and out["spec"]["A"] == skins.DIELECTRIC and out["gloss"]["A"] == skins.PRESETS["gloss"]
    assert out["B"] == [40, 50, 60] and out["gloss"]["B"] == 77                    # the fine slider wins
    # metal: the colour goes to the reflectance, the albedo is nearly black
    assert out["spec"]["C"] == [200, 100, 50] and out["C"] == [40, 20, 10] and out["gloss"]["C"] == skins.PRESETS["metal"]
    assert out["glass"] == [5, 6, 7]


def test_effective_base_finish_keeps_the_paints_own_with_a_new_colour():
    out = skins.effective(PAL, skin(palette={"C": [1, 1, 1], "finish": {"C": {"preset": "base"}}}))
    assert out["C"] == [1, 1, 1] and out["spec"]["C"] == [60, 60, 60] and out["gloss"]["C"] == 30


def test_effective_without_a_base_palette():
    out = skins.effective(None, skin(palette={"A": [10, 20, 30]}))
    assert out["A"] == [10, 20, 30] and out["spec"]["A"] == skins.DIELECTRIC and out["gloss"]["A"] is not None
    # an entry nobody colours stays empty: its layers keep the game's dark grey, as under the paint itself
    assert out["B"] is None and out["spec"]["B"] is None and out["gloss"]["B"] is None and out["glass"] is None


def test_find_base_by_material_and_palette_not_by_position():
    vs = [{"tag": "0", "label": "Stock", "material": "a.mtl", "palette": {"name": "grey"}, "stock": True},
          {"tag": "1", "label": "Black", "material": "ships/perseus_black.mtl", "palette": {"name": "black"}, "stock": False},
          {"tag": "2", "label": "Blue", "material": "ships/perseus_black.mtl", "palette": {"name": "blue"}, "stock": False}]
    assert skins.find_base(vs, skin()) == (vs[1], True)
    assert skins.find_base(list(reversed(vs)), skin()) == (vs[1], True)          # the list was sorted another way
    gone = skin(base={"material": "old.mtl", "palette": "x"})
    assert skins.find_base(vs, gone) == (vs[0], False)                           # the paint is gone: stock, flagged
    assert skins.find_base([], skin(base={})) == (None, True)                    # a model without paints
    assert skins.find_base([], skin()) == (None, False)


def test_base_ref_round_trip():
    v = {"tag": "7", "label": "Black", "material": "ships/perseus_black.mtl", "palette": {"name": "black"}}
    assert skins.find_base([v], skin(base=skins.base_ref(v))) == (v, True)
    assert skins.base_ref(None) == {"material": "", "palette": "", "label": ""}


def test_apply_is_a_paint_variant():
    base = {"tag": "1", "label": "Black", "material": "m.mtl", "palette": PAL, "stock": True}
    v = skins.apply(base, skins.validate(skin()), "skin:abc")
    assert v["tag"] == "skin:abc" and v["label"] == "Night Raid" and v["material"] == "m.mtl"
    assert v["stock"] is False and v["custom"] is True and v["palette"]["A"] == [10, 20, 30]
    assert skins.apply(None, skins.validate(skin()), "skin:x")["material"] is None


# ---------------------------------------------------------------- the library

def test_save_load_list_delete(tmp_path):
    lib = str(tmp_path / "Skins")
    a = skins.save(lib, skin())
    assert len(a["id"]) == 8 and a["created"] and a["modified"]
    assert os.path.isfile(os.path.join(lib, "Night Raid.vfskin"))
    got, path, stamp = skins.find(lib, a["id"])
    assert got == a and path.endswith("Night Raid.vfskin") and stamp
    skins.save(lib, skin(name="Other", target={"model": "weapons/gun.cgf", "label": "Gun"}))
    assert [s["name"] for s, _, _ in skins.list_skins(lib)] == ["Night Raid", "Other"]
    assert [s["name"] for s, _, _ in skins.list_skins(lib, MODEL.upper().replace("/", "\\"))] == ["Night Raid"]
    assert skins.delete(lib, a["id"]) and not skins.find(lib, a["id"])
    assert os.path.isfile(os.path.join(lib, "Deleted", "Night Raid.vfskin"))      # recoverable
    assert not skins.delete(lib, a["id"])


def test_save_again_keeps_the_id_and_follows_a_new_name(tmp_path):
    lib = str(tmp_path)
    a = skins.save(lib, skin())
    b = skins.save(lib, {**a, "name": "Day Raid", "palette": {"A": [9, 9, 9]}})
    assert b["id"] == a["id"] and b["created"] == a["created"]
    assert sorted(os.listdir(lib)) == ["Day Raid.vfskin"]
    assert skins.find(lib, a["id"])[0]["palette"]["A"] == [9, 9, 9]


def test_a_name_already_used_gets_a_number(tmp_path):
    lib = str(tmp_path)
    a = skins.save(lib, skin())
    b = skins.save(lib, skin())
    c = skins.save(lib, skin())
    assert [a["name"], b["name"], c["name"]] == ["Night Raid", "Night Raid 2", "Night Raid 3"]
    # same name on another model: the name stays, only the file gets a number
    d = skins.save(lib, skin(target={"model": "weapons/gun.cgf", "label": "Gun"}))
    assert d["name"] == "Night Raid" and len(os.listdir(lib)) == 4


def test_names_that_are_not_file_names(tmp_path):
    a = skins.save(str(tmp_path), skin(name='Red / "Blue" ?'))
    assert a["name"] == 'Red / "Blue" ?' and os.listdir(tmp_path) == ["Red _ _Blue_ _.vfskin"]


def test_broken_files_are_refused_and_not_listed(tmp_path):
    lib = str(tmp_path)
    (tmp_path / "junk.vfskin").write_bytes(b"not a zip")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("other.txt", "x")
    (tmp_path / "empty.vfskin").write_bytes(buf.getvalue())
    assert skins.list_skins(lib) == []
    for data in (b"not a zip", buf.getvalue()):
        with pytest.raises(skins.SkinError) as e:
            skins.read_bytes(data)
        assert e.value.code == "bad_file"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("skin.json", "{broken")
    with pytest.raises(skins.SkinError):
        skins.read_bytes(buf.getvalue())


def test_import_keeps_both_when_the_id_is_taken_and_carries_images(tmp_path):
    lib, other = str(tmp_path / "a"), str(tmp_path / "b")
    a = skins.save(other, skin())
    path = skins.find(other, a["id"])[1]
    with zipfile.ZipFile(path, "a") as z:
        z.writestr("images/logo.png", b"PNG")
    data = open(path, "rb").read()
    first = skins.import_bytes(lib, data)
    assert first["id"] == a["id"] and first["name"] == "Night Raid"
    second = skins.import_bytes(lib, data)
    assert second["id"] != a["id"] and second["name"] == "Night Raid 2"
    with zipfile.ZipFile(skins.find(lib, first["id"])[1]) as z:
        assert z.read("images/logo.png") == b"PNG"
    # saving again keeps the images
    skins.save(lib, {**first, "palette": {"B": [1, 1, 1]}})
    with zipfile.ZipFile(skins.find(lib, first["id"])[1]) as z:
        assert z.read("images/logo.png") == b"PNG" and json.loads(z.read("skin.json"))["palette"]["B"] == [1, 1, 1]


def test_a_file_changed_by_hand_is_read_again(tmp_path):
    lib = str(tmp_path)
    a = skins.save(lib, skin())
    _, path, stamp = skins.find(lib, a["id"])
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("skin.json", json.dumps({**a, "palette": {"A": [7, 7, 7]}}))
    os.utime(path, ns=(stamp + 10**9, stamp + 10**9))
    got, _, stamp2 = skins.find(lib, a["id"])
    assert got["palette"]["A"] == [7, 7, 7] and stamp2 != stamp
