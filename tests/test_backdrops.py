"""Space backdrops made from the game's sky textures. Needs Data.p4k."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sc_explorer import backdrops, textures  # noqa: E402
from sc_explorer.p4k import P4kArchive  # noqa: E402
from sc_explorer.server import CACHE_DIR, load_config  # noqa: E402

P4K = load_config()["p4k_path"]
pytestmark = pytest.mark.skipif(not os.path.isfile(P4K), reason="Data.p4k not found")


@pytest.fixture(scope="module")
def tex():
    a = P4kArchive(P4K, CACHE_DIR)
    a.load()
    return textures.TextureCache(a)


def _face(tex, name, size=256):
    suffix, turns = backdrops.PYRO_FACES[name]
    img = tex.get(f"{backdrops.PYRO_DIR}Pyro_sys_neb_{suffix}.dds", size)
    return np.rot90(np.asarray(img.convert("RGB"), np.float32), turns)


def test_pyro_cube_seams_meet(tex):
    # the faces are stored with different turns: once turned, every edge continues into its neighbour
    f = {n: _face(tex, n) for n in backdrops.PYRO_FACES}
    err = lambda a, b: float(np.abs(a - b).mean())  # noqa: E731
    ring = ["front", "right", "back", "left"]
    seams = [err(f[ring[i]][:, -1], f[ring[(i + 1) % 4]][:, 0]) for i in range(4)]
    up, bot = f["up"], f["bot"]
    seams += [err(up[-1], f["front"][0]), err(up[:, -1][::-1], f["right"][0]), err(up[0][::-1], f["back"][0]),
              err(up[:, 0], f["left"][0]), err(bot[0], f["front"][-1]), err(bot[:, -1], f["right"][-1]),
              err(bot[-1][::-1], f["back"][-1]), err(bot[:, 0][::-1], f["left"][-1])]
    wrong = err(f["front"][:, -1], f["up"][:, 0])        # two edges that do not touch
    assert max(seams) < 3.0 < wrong


def test_panoramas(tex):
    for name in backdrops.NAMES:
        img = backdrops.build(name, tex, width=1024)
        assert img is not None and img.size == (1024, 512) and img.mode == "RGB"
        a = np.asarray(img, np.float32)
        assert a.mean() > 3 and a.max() > 150         # not an empty black sky
