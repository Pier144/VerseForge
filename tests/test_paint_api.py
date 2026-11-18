"""Paint endpoints of the local server, on fake models (no game files): the catalogue is never loaded."""
import os
import sys

import pytest

pytest.importorskip("httpx")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi.testclient import TestClient  # noqa: E402

from sc_explorer import export, materials, model, server  # noqa: E402
from test_paints import _glb_json, _mat, _paint, _part  # noqa: E402

PATH = "Objects/ship.cga"
PAINTS = {"0": [(0.5, 0.5, 0.5), (0.2, 0.2, 0.2), (0.8, 0.8, 0.8)],
          "1": [(0.9, 0.1, 0.1), (0.1, 0.9, 0.1), (0.3, 0.3, 0.3)]}


@pytest.fixture
def client(monkeypatch):
    built = {t: _paint(c, livery=t == "1") for t, c in PAINTS.items()}
    broken = model.Model(PATH, parts=built["1"].parts[:-1])
    vs = [{"tag": "0", "label": "Stock", "material": "", "palette": None, "stock": True},
          {"tag": "1", "label": "Red", "material": "", "palette": {"A": [200, 0, 0], "B": [0, 200, 0], "C": [9, 9, 9]},
           "stock": False},
          {"tag": "2", "label": "Odd", "material": "", "palette": None, "stock": False}]
    st = server.state
    monkeypatch.setattr(st, "status", {"ready": True, "message": ("models_ready", {"n": 1}), "progress": 1.0, "error": None})
    monkeypatch.setattr(st, "variants", {PATH.lower(): vs})
    monkeypatch.setattr(st, "can_full", lambda p: False)
    monkeypatch.setattr(st, "can_interior", lambda p: False)
    monkeypatch.setattr(st, "get_model", lambda p, variant=None, full=False, interior=False:
                        broken if variant == "2" else built.get(variant or "0", built["0"]))
    monkeypatch.setattr(st, "paint_ok", {})
    monkeypatch.setattr(st.disk, "enabled", False)
    monkeypatch.setattr(server, "_sources", lambda m: [])
    return TestClient(server.app)


def test_info_lists_swatches_and_stock(client):
    info = client.get("/api/model/info", params={"path": PATH, "variant": "1"}).json()
    assert info["keyed"] and info["keyed_glb"]
    assert [v["colors"] for v in info["variants"]] == [None, [[200, 0, 0], [0, 200, 0], [9, 9, 9]], None]
    assert [v["stock"] for v in info["variants"]] == [True, False, False]


def test_keyed_glb_only_for_swappable_paints(client):
    good = _glb_json(client.get("/api/model/glb", params={"path": PATH, "variant": "1", "lite": True}).content)
    odd = _glb_json(client.get("/api/model/glb", params={"path": PATH, "variant": "2", "lite": True}).content)
    assert all("|g" in m["name"] for m in good["materials"])
    assert not any("|g" in m["name"] for m in odd["materials"])
    assert not client.get("/api/model/info", params={"path": PATH, "variant": "2"}).json()["keyed_glb"]


def test_paint_table(client):
    out = client.get("/api/model/paint", params={"path": PATH, "variant": "1"}).json()
    assert out["swappable"] and out["variant"] == "1" and len(out["groups"]) == 4
    assert out["groups"][3]["visible"] and out["groups"][0]["name"].endswith("|g0")
    assert set(out["shading"]) == {g["name"].split("|")[2] for g in out["groups"] if g and g["name"].split("|")[2]}
    assert client.get("/api/model/paint", params={"path": PATH, "variant": "2"}).json() == \
        {"variant": "2", "swappable": False}


def test_paint_texture_route(client, monkeypatch):
    from PIL import Image
    p = {"path": PATH, "variant": "1"}
    assert client.get("/api/model/paint/texture", params={**p, "group": 99}).status_code == 404
    assert client.get("/api/model/paint/texture", params={**p, "group": 0}).status_code == 404   # plain colour
    sticker = materials.Material("livery", "MeshDecal", "decal", (1, 1, 1), diffuse="x.dds", stencil_decal=True,
                                 stencil_colors=[[1, 0, 0], None, None])
    image = {"png": Image.new("RGBA", (4, 4), (255, 0, 0, 128)), "jpg": Image.new("RGB", (4, 4), (255, 0, 0))}
    image["png"].format, image["jpg"].format = "PNG", "JPEG"
    kind = ["png"]
    monkeypatch.setattr(export, "material_textures", lambda mat, cache, size: (image[kind[0]], None, 1.0))
    built = server.state.get_model(PATH, "1")
    built.parts[4].material = sticker
    group = server.state.paint_groups(PATH, False, False)[4]
    r = client.get("/api/model/paint/texture", params={**p, "group": group})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    kind[0] = "jpg"
    r = client.get("/api/model/paint/texture", params={**p, "group": group})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"


@pytest.fixture
def interior_client(monkeypatch):
    """Interior on: get_model(interior=True) is the hull plus one room part, as State._interior builds it, with the
    same room part in every paint."""
    built = {t: _paint(c, livery=t == "1") for t, c in PAINTS.items()}
    room = _part(_mat("floor"), "int.mtl", 0, seed=9, room=0)
    vs = [{"tag": "0", "label": "Stock", "material": "", "palette": None, "stock": True},
          {"tag": "1", "label": "Red", "material": "", "palette": None, "stock": False}]

    def get_model(p, variant=None, full=False, interior=False):
        hull = built.get(variant or "0", built["0"])
        if not interior:
            return hull
        key = ("int", variant or "0")
        if key not in cache:
            cache[key] = model.Model(PATH, parts=list(hull.parts) + [room], rooms=[{"name": "bridge", "parts": 1, "centre": [0, 0, 1.5]}])
        return cache[key]

    cache = {}
    st = server.state
    monkeypatch.setattr(st, "status", {"ready": True, "message": ("models_ready", {"n": 1}), "progress": 1.0, "error": None})
    monkeypatch.setattr(st, "variants", {PATH.lower(): vs})
    monkeypatch.setattr(st, "can_full", lambda p: False)
    monkeypatch.setattr(st, "can_interior", lambda p: True)
    monkeypatch.setattr(st, "get_model", get_model)
    monkeypatch.setattr(st, "paint_ok", {})
    monkeypatch.setattr(st, "_paint_locks", {})
    monkeypatch.setattr(st.disk, "enabled", False)
    monkeypatch.setattr(server, "_sources", lambda m: [])
    return TestClient(server.app)


def test_paint_table_with_the_interior(interior_client):
    p = {"path": PATH, "variant": "1", "interior": True}
    out = interior_client.get("/api/model/paint", params=p).json()
    assert out["swappable"] and len(out["groups"]) == 5
    assert all(g is not None for g in out["groups"][:4])      # every hull group has its material
    assert out["groups"][4] is None                           # the room never changes with the paint
    assert interior_client.get("/api/model/info", params=p).json()["keyed_glb"]
