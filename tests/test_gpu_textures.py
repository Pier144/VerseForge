"""Game textures sent to the viewer as their compressed blocks (DDS) instead of decoded JPEG/PNG. Needs Data.p4k."""
import io
import os
import struct
import sys

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sc_explorer import textures  # noqa: E402
from sc_explorer.p4k import P4kArchive  # noqa: E402
from sc_explorer.server import CACHE_DIR, load_config  # noqa: E402

P4K = load_config()["p4k_path"]
pytestmark = pytest.mark.skipif(not os.path.isfile(P4K), reason="Data.p4k not found")

ALL = {"s3tc", "rgtc", "bptc"}
TEX = "objects/fps_weapons/weapons_v7/volt/smg/quartz/textures/"
BC1_COLOR = TEX + "esmg_fps_volt_quartz_trim_diff.tif"
BC7_COLOR = "objects/fps_weapons/weapons_v7/volt/textures/volt_decals_1_diff.tif"
BC5S_NORMAL = TEX + "esmg_fps_volt_quartz_ddna.tif"
CAMO_MASK = "objects/spaceships/textures/stencils/camo_digi_stencil_01_mask.dds"


@pytest.fixture(scope="module")
def archive():
    a = P4kArchive(P4K, CACHE_DIR)
    a.load()
    return a


def _dds(data):
    h, w = struct.unpack_from("<2I", data, 12)
    mips = struct.unpack_from("<I", data, 28)[0]
    dxgi = struct.unpack_from("<I", data, 128)[0]
    return w, h, mips, dxgi


def _chain_bytes(w, h, mips, block):
    return sum(max(1, (max(1, w >> i) + 3) // 4) * max(1, (max(1, h >> i) + 3) // 4) * block for i in range(mips))


def test_colour_map_blocks_match_decoded_image(archive):
    for path, dxgi, block in ((BC1_COLOR, 71, 8), (BC7_COLOR, 98, 16)):
        data = textures.gpu_blocks(archive, path, "color", 256, ALL)
        w, h, mips, fmt = _dds(data)
        assert (w, h, fmt) == (256, 256, dxgi) and mips >= 6
        assert len(data) == 148 + _chain_bytes(w, h, mips, block)
        # the first mip is exactly what the decoded path shows (Pillow reads the DX10 DDS's first level)
        sent = np.asarray(Image.open(io.BytesIO(data)).convert("RGBA"))
        ref = np.asarray(textures.TextureCache(archive).get(path, 256).convert("RGBA"))
        assert np.abs(sent.astype(int) - ref.astype(int)).max() <= 1


def test_signed_bc5_normal_blocks(archive):
    data = textures.gpu_blocks(archive, BC5S_NORMAL, "normal", 256, ALL)
    w, h, mips, fmt = _dds(data)
    assert (w, h, fmt) == (256, 256, 84)
    # decoding the blocks sent gives the normal map of the decoded path
    sent = np.asarray(textures._bc5_normal(data[148:148 + 256 * 256], 256, 256, signed=True))
    ref = np.asarray(textures.TextureCache(archive).get(BC5S_NORMAL, 256, normal=True))
    assert np.abs(sent.astype(int) - ref.astype(int)).max() <= 1


def test_gloss_from_alpha_file_is_bc4(archive):
    data = textures.gpu_blocks(archive, BC5S_NORMAL, "gloss", 256, ALL)
    w, h, mips, fmt = _dds(data)
    assert (w, h, fmt) == (256, 256, 80)
    sent = textures._bc4(np.frombuffer(data, np.uint8, 64 * 64 * 8, 148).reshape(-1, 8), False)
    sent = sent.reshape(64, 64, 4, 4).transpose(0, 2, 1, 3).reshape(256, 256) * 255
    ref = np.asarray(textures.TextureCache(archive).gloss(BC5S_NORMAL, 256)).astype(float)
    assert np.abs(sent - ref).mean() < 1


def test_maps_that_need_processing_keep_the_decoded_path(archive):
    assert textures.gpu_blocks(archive, CAMO_MASK, "mask", 256, ALL) is None          # uncompressed RGB mask
    assert textures.gpu_blocks(archive, BC5S_NORMAL, "color", 256, ALL) is None       # BC5 would show red/green
    assert textures.gpu_blocks(archive, BC7_COLOR, "color", 256, {"s3tc", "rgtc"}) is None   # GPU without BPTC
    assert textures.gpu_blocks(archive, BC1_COLOR, "gloss", 256, ALL) is None         # no separate gloss file


class _Req:
    def __init__(self, enc):
        self.headers = {"accept-encoding": enc}


def test_texture_endpoint_sends_dds_only_when_asked():
    import zstandard
    from sc_explorer import server
    if not server.state.status["ready"]:
        server.state.load()
    r = server.texture(_Req("gzip, zstd"), BC1_COLOR, "color", 256, "s3tc,rgtc,bptc")
    assert r.media_type == server.DDS_MEDIA and r.headers["content-encoding"] == "zstd"
    assert _dds(zstandard.ZstdDecompressor().decompressobj().decompress(r.body))[3] == 71
    r = server.texture(_Req(""), BC1_COLOR, "color", 256, "s3tc")
    assert r.media_type == server.DDS_MEDIA and "content-encoding" not in r.headers and r.body[:4] == b"DDS "
    r = server.texture(_Req("zstd"), BC1_COLOR, "color", 256, "")
    assert r.media_type in ("image/png", "image/jpeg")
    r = server.texture(_Req("zstd"), CAMO_MASK, "mask", 256, "s3tc,rgtc,bptc")
    assert r.media_type == "image/png"
