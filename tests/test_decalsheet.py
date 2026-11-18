"""Decal sheets (decalsheet.py): what counts as a sticker, grouping, true size, pages."""
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sc_explorer import decalsheet, materials, model  # noqa: E402


class Textures:
    """Left half red and opaque, right half clear."""
    def get(self, path, max_size=1024, normal=False):
        a = np.zeros((64, 64, 4), np.uint8)
        a[:, :32] = (255, 0, 0, 255)
        return Image.fromarray(a, "RGBA")


def _mat(name="Decal_Text", shader="MeshDecal", **kw):
    m = materials.Material(name, shader, "decal", (1.0, 1.0, 1.0), diffuse="t.dds")
    for k, v in kw.items():
        setattr(m, k, v)
    return m


def _quad(x, y, w, h, mat, z=0.0, u=(0.0, 0.5)):
    """A w x h metre quad facing +Z, picture upright when seen from above with +X to the right and -Y down."""
    v = np.array([[x, y, z], [x + w, y, z], [x + w, y - h, z], [x, y - h, z]], np.float64)
    uv = np.array([[u[0], 0], [u[1], 0], [u[1], 1], [u[0], 1]], np.float32)
    return model.Part("q", mat, v, np.array([[0, 2, 1], [0, 3, 2]]), "x", uvs=uv)


def test_what_is_a_sticker():
    assert decalsheet.printable(_mat())
    assert decalsheet.printable(_mat("text_decals", "Illum"))
    assert not decalsheet.printable(_mat("Decal_Dirt", opacity=0.08))
    assert not decalsheet.printable(_mat("Decal_POM_A", pom=True))
    assert not decalsheet.printable(_mat("Decal_Glow_Linked", "Illum"))
    assert not decalsheet.printable(_mat("Paint", "HardSurface"))
    solid = _mat()
    solid.kind = "solid"
    assert not decalsheet.printable(solid)


def test_true_size_and_copies():
    mat = _mat()
    m = model.Model("s.cga", parts=[_quad(0, 0, 1.44, 0.72, mat), _quad(10, 5, 1.44, 0.72, mat)])
    decals, small = decalsheet.collect(m, Textures(), 72)
    assert small == 0 and len(decals) == 1 and decals[0].count == 2
    d = decals[0]
    assert abs(d.width_mm - 20.0) < 0.3 and abs(d.height_mm - 10.0) < 0.3
    px = np.asarray(d.image)
    assert px[px.shape[0] // 2, px.shape[1] // 2].tolist() == [255, 0, 0, 255]


def test_letters_close_together_stay_one_decal_and_tiny_ones_are_dropped():
    mat = _mat()
    letters = [_quad(i * 0.25, 0, 0.2, 0.3, mat) for i in range(4)]          # 5 cm apart, 30 cm tall
    far = _quad(50, 0, 0.2, 0.3, mat)
    tiny = _quad(80, 0, 0.02, 0.02, mat)
    decals, small = decalsheet.collect(model.Model("s.cga", parts=letters + [far, tiny]), Textures(), 72)
    assert small == 1
    assert sorted(round(d.width_mm, 0) for d in decals) == [3.0, 13.0]


def test_sheets_are_true_size_pdfs():
    mat = _mat()
    m = model.Model("s.cga", parts=[_quad(0, 0, 1.44, 0.72, mat)])
    decals, _ = decalsheet.collect(m, Textures(), 72)
    clear, white, info = decalsheet.sheets(decals, "a4", (40, 60, 80), "Test", 72)
    assert info == {"decals": 1, "pieces": 1, "pages": 1, "too_big": 0}
    assert clear[:4] == b"%PDF" and white[:4] == b"%PDF"
    pages, size, big = decalsheet._layout(decals, "a4")
    assert size == (4961, 7016) and big == 0


def test_nothing_to_print():
    clear, white, info = decalsheet.sheets([], "letter", (0, 0, 0), "Test", 72)
    assert clear is None and info["pages"] == 0
