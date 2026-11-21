"""User skins on the local server: the library calls, a skin as one more paint, the draft (no game files)."""
import os
import sys
import time
import xml.etree.ElementTree as ET

import pytest

pytest.importorskip("httpx")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from sc_explorer import materials, server, skins  # noqa: E402

PATH = "Objects/ship.cga"
PAL = {"name": "red", "A": [200, 0, 0], "B": [0, 200, 0], "C": [9, 9, 9], "glass": None,
       "spec": {"A": None, "B": None, "C": None}, "gloss": {"A": 100, "B": None, "C": None},
       "decal": None, "decal_colors": [None, None, None]}


def body(**over):
    s = {"name": "Mine", "target": {"model": PATH, "label": "Ship"},
         "base": {"material": "red.mtl", "palette": "red", "label": "Red"}, "palette": {"B": [1, 2, 3]}}
    s.update(over)
    return s


@pytest.fixture
def client(monkeypatch, tmp_path):
    vs = [{"tag": "0", "label": "Stock", "material": "", "palette": None, "stock": True},
          {"tag": "1", "label": "Red", "material": "red.mtl", "palette": PAL, "stock": False}]
    st = server.state
    monkeypatch.setattr(server, "SKINS_DIR", str(tmp_path / "Skins"))
    monkeypatch.setattr(st, "status", {"ready": True, "message": ("models_ready", {"n": 1}), "progress": 1.0, "error": None})
    monkeypatch.setattr(st, "variants", {PATH.lower(): vs, "objects/gun.cgf": vs[:1]})
    monkeypatch.setattr(st, "by_path", {PATH.lower(): object()})
    monkeypatch.setattr(st, "cfg", {**st.cfg, "export_dir": str(tmp_path / "out")})
    monkeypatch.setattr(st, "paint_ok", {})
    monkeypatch.setattr(st, "draft", None)
    monkeypatch.setattr(st.disk, "enabled", False)
    return TestClient(server.app)


def test_save_list_get_delete(client):
    r = client.post("/api/skins", json=body())
    assert r.status_code == 200
    meta = r.json()["skin"]
    assert meta["tag"] == f"skin:{meta['id']}" and meta["label"] == "Mine" and meta["custom"]
    assert meta["colors"] == [[200, 0, 0], [1, 2, 3], [9, 9, 9]]            # the base paint's colours with the skin's B
    assert meta["base_tag"] == "1" and meta["base_found"] and meta["openable"]
    listed = client.get("/api/skins", params={"path": PATH}).json()
    assert [s["id"] for s in listed["skins"]] == [meta["id"]] and listed["folder"].endswith("Skins")
    assert client.get("/api/skins", params={"path": "Objects/gun.cgf"}).json()["skins"] == []
    assert len(client.get("/api/skins").json()["skins"]) == 1
    got = client.get(f"/api/skins/{meta['id']}").json()
    assert got["data"]["palette"]["B"] == [1, 2, 3] and got["skin"]["stamp"]
    assert client.delete(f"/api/skins/{meta['id']}").json() == {"ok": True}
    assert client.get(f"/api/skins/{meta['id']}").status_code == 404
    assert client.delete(f"/api/skins/{meta['id']}").status_code == 404


def test_a_skin_is_one_more_paint(client):
    sid = client.post("/api/skins", json=body()).json()["skin"]["id"]
    st = server.state
    v = st.variant(PATH, f"skin:{sid}")
    assert v["tag"] == f"skin:{sid}" and v["material"] == "red.mtl" and v["custom"]
    assert v["palette"]["A"] == [200, 0, 0] and v["palette"]["B"] == [1, 2, 3]
    assert v["palette"]["gloss"] == {"A": 100, "B": skins.PRESETS["satin"], "C": skins.PRESETS["satin"]}
    assert st.shown_tag(PATH, f"skin:{sid}") == f"skin:{sid}"
    key = st.tag_of(PATH, f"skin:{sid}")
    assert key.startswith(f"skin:{sid}:") and key == st.tag_of(PATH, f"skin:{sid}")
    # saving again changes the key, so nothing built from the old colours is found again
    time.sleep(0.02)
    client.post("/api/skins", json={**body(palette={"B": [4, 5, 6]}), "id": sid})
    assert st.tag_of(PATH, f"skin:{sid}") != key
    assert st.variant(PATH, f"skin:{sid}")["palette"]["B"] == [4, 5, 6]


def test_game_paints_resolve_as_before(client):
    st = server.state
    assert st.variant(PATH, "1")["label"] == "Red" and st.tag_of(PATH, "1") == "1"
    assert st.tag_of(PATH, "nope") == "0" and st.tag_of(PATH, None) == "0" and st.shown_tag(PATH, "nope") == "0"
    assert st.variant("Objects/none.cgf", None) is None and st.tag_of("Objects/none.cgf", "x") is None


def test_a_skin_tag_that_leads_nowhere_is_an_error(client):
    st = server.state
    with pytest.raises(HTTPException) as e:
        st.variant(PATH, "skin:00000000")
    assert e.value.status_code == 404
    assert client.get("/api/model/paint", params={"path": PATH, "variant": "skin:00000000"}).status_code == 404
    assert client.get("/api/model/info", params={"path": PATH, "variant": "skin:draft"}).status_code == 404   # no draft yet
    # a skin of another model is not a paint of this one
    sid = client.post("/api/skins", json=body(target={"model": "Objects/gun.cgf"})).json()["skin"]["id"]
    with pytest.raises(HTTPException):
        st.variant(PATH, f"skin:{sid}")
    assert st.variant("objects\\GUN.cgf", f"skin:{sid}")["label"] == "Mine"


def test_a_base_paint_that_is_gone_falls_back_to_stock(client):
    meta = client.post("/api/skins", json=body(base={"material": "old.mtl", "palette": "old", "label": "Old"})).json()["skin"]
    assert meta["base_tag"] == "0" and not meta["base_found"]
    assert server.state.variant(PATH, meta["tag"])["material"] == ""


def test_the_draft_lives_in_memory_only(client, tmp_path):
    st = server.state
    r = client.post("/api/skins/draft", json=body(palette={"A": [7, 7, 7]}))
    assert r.json() == {"tag": f"skin:draft:{st.draft_rev}"}
    first = st.tag_of(PATH, r.json()["tag"])
    assert st.variant(PATH, "skin:draft")["palette"]["A"] == [7, 7, 7]
    st.paint_ok[(PATH.lower(), first, False, False)] = True
    again = client.post("/api/skins/draft", json=body(palette={"A": [8, 8, 8]})).json()["tag"]
    assert st.tag_of(PATH, again) != first and st.variant(PATH, r.json()["tag"])["palette"]["A"] == [8, 8, 8]
    assert st.paint_ok == {}                                    # the checks of older drafts are dropped
    assert not os.path.exists(tmp_path / "Skins")               # nothing written
    assert client.post("/api/skins/draft", json=body(name="")).status_code == 422


def test_bad_skins_are_refused_with_a_reason(client):
    r = client.post("/api/skins", json=body(palette={"A": [1, 2]}))
    assert r.status_code == 422 and "palette.A" in r.json()["detail"]
    r = client.post("/api/skins", json=body(format=99))
    assert r.status_code == 422 and "newer" in r.json()["detail"].lower()
    r = client.post("/api/skins/import", content=b"junk", headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 422


def test_export_and_import_round_trip(client, tmp_path):
    sid = client.post("/api/skins", json=body()).json()["skin"]["id"]
    saved = client.post(f"/api/skins/{sid}/export").json()["saved"]
    assert saved == str(tmp_path / "out" / "Mine.vfskin") and os.path.isfile(saved)
    assert client.post("/api/skins/nope/export").status_code == 404
    data = open(saved, "rb").read()
    r = client.post("/api/skins/import", content=data, headers={"Content-Type": "application/octet-stream"})
    twin = r.json()["skin"]
    assert twin["id"] != sid and twin["label"] == "Mine 2" and twin["colors"][1] == [1, 2, 3]
    assert len(client.get("/api/skins", params={"path": PATH}).json()["skins"]) == 2


def test_keyed_layout_on_request(client):
    st = server.state
    assert st.keyed(PATH) and not st.keyed("Objects/gun.cgf") and st.keyed("Objects/gun.cgf", True)
    assert not st.swappable("Objects/gun.cgf", None, False, False)


# ---------------------------------------------------------------- tint in the materials

LAYER = ('<Material Name="paint" Shader="HardSurface" Diffuse="1,1,1"><MatLayers>'
         '<Layer Path="" TintColor="1,1,1" PaletteTint="{slot}"/></MatLayers></Material>')


def test_materials_name_the_palette_entry_they_use():
    m = materials._material(ET.fromstring(LAYER.format(slot=2)), None, PAL)
    assert m.tint == {"slot": "B", "base": [1.0, 1.0, 1.0]}
    sh = materials.shading(m)
    assert sh["tint"] == m.tint
    # base x the palette colour (gamma 2) is the albedo the server sends: what the viewer's retint computes
    want = [b * c for b, c in zip(sh["tint"]["base"], materials.palette_linear(PAL["B"]))]
    assert sh["albedo"] == pytest.approx(want, abs=1e-4)
    # entry known even when the palette does not fill it; none for a layer with its own colour
    assert materials._material(ET.fromstring(LAYER.format(slot=3)), None, None).tint["slot"] == "C"
    assert materials._material(ET.fromstring(LAYER.format(slot=0)), None, PAL).tint is None


def test_a_skin_without_changes_colours_like_its_base_paint():
    el = ET.fromstring(LAYER.format(slot=1))
    base = materials._material(el, None, PAL)
    same = materials._material(el, None, skins.effective(PAL, {"palette": {}}))
    assert same.color == base.color and same.gloss == base.gloss
    red = materials._material(el, None, skins.effective(PAL, {"palette": {"A": [0, 0, 255], "finish": {"A": {"preset": "metal"}}}}))
    assert red.spec == pytest.approx(materials.palette_linear([0, 0, 255])) and max(red.color) < 0.05
    assert red.gloss == pytest.approx(skins.PRESETS["metal"] / 255)
