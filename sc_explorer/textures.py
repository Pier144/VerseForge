"""Textures: Star Citizen split .dds files (header + mips in .dds.1 … .dds.N, N = largest) -> PIL images."""
import io
import struct
import threading
from collections import OrderedDict

import numpy as np
from PIL import Image

# bytes per 4x4 block for block-compressed formats, bytes per pixel for the few plain ones we accept
_BLOCK = {b"DXT1": 8, b"DXT3": 16, b"DXT5": 16, b"ATI1": 8, b"BC4U": 8, b"ATI2": 16, b"BC5U": 16}
_DXGI_BLOCK = {70: 8, 71: 8, 72: 8, 73: 16, 74: 16, 75: 16, 76: 16, 77: 16, 78: 16, 79: 8, 80: 8, 81: 8,
               82: 16, 83: 16, 84: 16, 94: 16, 95: 16, 96: 16, 97: 16, 98: 16, 99: 16}
_NORMAL_DXGI = {82, 83, 84}           # BC5: two-channel normal maps


def dds_path(path):
    """Materials reference the source .tif/.png; the game ships the compiled .dds next to it."""
    p = path.replace("\\", "/")
    if p.lower().startswith("data/"):
        p = p[5:]
    stem = p.rsplit(".", 1)[0] if "." in p.rsplit("/", 1)[-1] else p
    return stem + ".dds"


def _mip_size(w, h, level, block):
    w, h = max(1, w >> level), max(1, h >> level)
    if block:
        return w, h, max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * block
    return w, h, 0


def _header(h):
    if h[:4] != b"DDS " or len(h) < 128:
        raise ValueError("not a DDS file")
    height, width, _pitch, _depth, mips = struct.unpack_from("<5I", h, 12)
    fourcc = h[84:88]
    dxgi = struct.unpack_from("<I", h, 128)[0] if fourcc == b"DX10" else None
    block = _DXGI_BLOCK.get(dxgi) if dxgi is not None else _BLOCK.get(fourcc)
    return width, height, max(mips, 1), fourcc, dxgi, block, 148 if fourcc == b"DX10" else 128


def _bc4(blocks, signed):
    """Decode BC4 blocks (N, 8 bytes) -> (N, 16) values in -1..1 (signed) or 0..1."""
    e = blocks[:, :2].view(np.int8 if signed else np.uint8).astype(np.float32)
    e0, e1 = e[:, 0], e[:, 1]
    if signed:
        e0, e1 = np.maximum(e0, -127) / 127, np.maximum(e1, -127) / 127
        lo, hi = -1.0, 1.0
    else:
        e0, e1 = e0 / 255, e1 / 255
        lo, hi = 0.0, 1.0
    t = np.arange(8, dtype=np.float32)
    eight = (e0 > e1)[:, None]
    p8 = np.where(t < 2, np.where(t == 0, e0[:, None], e1[:, None]),
                  ((8 - t) * e0[:, None] + (t - 1) * e1[:, None]) / 7)
    p6 = np.where(t < 2, np.where(t == 0, e0[:, None], e1[:, None]),
                  ((6 - t) * e0[:, None] + (t - 1) * e1[:, None]) / 5)
    p6[:, 6], p6[:, 7] = lo, hi
    palette = np.where(eight, p8, p6)
    bits = np.zeros(len(blocks), np.uint64)
    for k in range(6):
        bits |= blocks[:, 2 + k].astype(np.uint64) << np.uint64(8 * k)
    idx = ((bits[:, None] >> (np.arange(16, dtype=np.uint64) * np.uint64(3))) & np.uint64(7)).astype(np.int64)
    return np.take_along_axis(palette, idx, 1)


def _bc5_normal(payload, w, h, signed):
    """BC5 (two BC4 channels) -> RGB normal map image, Z rebuilt from X/Y."""
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    blocks = np.frombuffer(payload, np.uint8, bw * bh * 16).reshape(-1, 16)
    xy = []
    for ch in (blocks[:, :8], blocks[:, 8:]):
        v = _bc4(np.ascontiguousarray(ch), signed)
        v = v if signed else v * 2 - 1
        xy.append(v.reshape(bh, bw, 4, 4).transpose(0, 2, 1, 3).reshape(bh * 4, bw * 4)[:h, :w])
    x, y = xy
    z = np.sqrt(np.clip(1 - x * x - y * y, 0, 1))
    out = np.stack([x, y, z], -1) * 0.5 + 0.5
    return Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")


def _single_mip_dds(head, hsize, w, h, payload):
    """Copy of the original header describing one mip level only (so Pillow can decode it)."""
    out = bytearray(head[:hsize])
    struct.pack_into("<II", out, 12, h, w)
    struct.pack_into("<I", out, 28, 1)
    return bytes(out) + payload


def _decode(archive, path, max_size, alpha=False):
    """alpha=True: the separate alpha image of a _ddna map (gloss), stored as <name>.dds.a + <name>.dds.<n>a with a
    DDS header that lacks the 'DDS ' magic."""
    base = dds_path(path)
    sfx = "a" if alpha else ""
    hname = base + ".a" if alpha else base
    if not archive.exists(hname):
        return None, False
    head = archive.read(hname)
    if alpha and head[:4] != b"DDS ":
        head = b"DDS " + head
    w, h, mips, fourcc, dxgi, block, hsize = _header(head)
    if not block:
        return _decode_plain(archive, base, head, w, h, mips, dxgi, hsize, max_size)
    split = 0
    while archive.exists(f"{base}.{split + 1}{sfx}"):
        split += 1
    # smallest level whose size still reaches max_size (or the largest one available)
    level = 0
    while level + 1 < mips and max(w >> (level + 1), h >> (level + 1)) >= max_size:
        level += 1
    mw, mh, size = _mip_size(w, h, level, block)
    if level < split:
        payload = archive.read(f"{base}.{split - level}{sfx}")[:size]
    else:
        # remaining (smaller) mips are stored in the header file after the header, largest first
        off = hsize + sum(_mip_size(w, h, lv, block)[2] for lv in range(split, level))
        payload = head[off:off + size]
    if len(payload) < size:
        return None, False
    if dxgi in _NORMAL_DXGI or fourcc in (b"ATI2", b"BC5U", b"BC5S"):
        # Pillow flattens signed BC5 to grey: decode it here (already a 3-channel normal map)
        return _bc5_normal(payload, mw, mh, signed=dxgi == 84 or fourcc == b"BC5S"), True
    img = Image.open(io.BytesIO(_single_mip_dds(head, hsize, mw, mh, payload)))
    img.load()
    return img, False


_PLAIN_DXGI = {49: 2, 28: 4, 29: 4, 87: 4, 61: 1}   # R8G8, R8G8B8A8 (+sRGB), B8G8R8A8, R8: stencil atlases


def _decode_plain(archive, base, head, w, h, mips, dxgi, hsize, max_size):
    """Uncompressed DDS (palette stencil atlases are R8G8; camo stencil masks are legacy 24/32-bit RGB without a
    FourCC): same mip layout as the block formats."""
    legacy = None
    if dxgi is None:
        # legacy pixel format: bit count + channel masks (camo masks: 24-bit, R=0xff0000 -> bytes stored B, G, R)
        pf_flags, = struct.unpack_from("<I", head, 80)
        bits, rm, gm, bm, am = struct.unpack_from("<5I", head, 88)
        if not pf_flags & 0x40 or bits not in (24, 32):
            return None, False
        shifts = [(m.bit_length() - 8) // 8 if m else None for m in (rm, gm, bm, am)]
        legacy = shifts
        bpp = bits // 8
    else:
        bpp = _PLAIN_DXGI.get(dxgi)
    if not bpp:
        return None, False
    split = 0
    while archive.exists(f"{base}.{split + 1}"):
        split += 1
    level = 0
    while level + 1 < mips and max(w >> (level + 1), h >> (level + 1)) >= max_size:
        level += 1

    def size(lv):
        return max(1, w >> lv) * max(1, h >> lv) * bpp
    mw, mh = max(1, w >> level), max(1, h >> level)
    if level < split:
        payload = archive.read(f"{base}.{split - level}")[:size(level)]
    else:
        off = hsize + sum(size(lv) for lv in range(split, level))
        payload = head[off:off + size(level)]
    if len(payload) < size(level):
        return None, False
    a = np.frombuffer(payload, np.uint8, size(level)).reshape(mh, mw, bpp)
    if legacy is not None:
        r, g, b, al = legacy
        rgb = np.stack([a[..., r], a[..., g], a[..., b]], -1)
        if al is not None:
            return Image.fromarray(np.ascontiguousarray(np.dstack([rgb, a[..., al]])), "RGBA"), False
        return Image.fromarray(np.ascontiguousarray(rgb), "RGB"), False
    if bpp == 4:
        rgba = a[..., [2, 1, 0, 3]] if dxgi == 87 else a
        return Image.fromarray(np.ascontiguousarray(rgba), "RGBA"), False
    rgb = np.zeros((mh, mw, 3), np.uint8)
    rgb[..., :bpp] = a
    return Image.fromarray(rgb, "RGB"), False


class TextureCache:
    """Decoded textures by (path, size): LRU with a memory budget, shared by viewer and exports."""

    def __init__(self, archive, budget_mb=400):
        self.archive = archive
        self.budget = budget_mb * 2 ** 20
        self._items = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()

    @staticmethod
    def _cost(value):
        imgs = value if isinstance(value, tuple) else (value,)
        return sum(i.width * i.height * len(i.getbands()) for i in imgs if isinstance(i, Image.Image)) + 64

    def get(self, path, max_size=1024, normal=False):
        """RGB(A) PIL image or None. normal=True returns a 3-channel tangent-space normal map."""
        if not path:
            return None
        key = (dds_path(path).lower(), max_size, normal)
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]
        try:
            img, is_bc5 = _decode(self.archive, path, max_size)
        except Exception:
            img, is_bc5 = None, False
        if img is not None:
            if max(img.size) > max_size:
                img.thumbnail((max_size, max_size), Image.LANCZOS)
            if normal and not is_bc5:
                img = img.convert("RGB")
            elif img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if "A" in img.mode else "RGB")
        return self.memo(key, img, store=True)

    def gloss(self, path, max_size=1024):
        """Gloss (smoothness 0..1 as an 'L' image) of a _ddna normal map: its separate alpha image, or the alpha
        channel of older single-file maps. None when the map carries no gloss."""
        if not path:
            return None
        key = ("gloss", dds_path(path).lower(), max_size)
        hit = self.memo(key)
        if hit is not None:
            return hit or None
        img = None
        try:
            img, _ = _decode(self.archive, path, max_size, alpha=True)
            if img is None:
                full, _ = _decode(self.archive, path, max_size)
                if full is not None and full.mode == "RGBA":
                    img = full.getchannel("A")
        except Exception:
            img = None
        if img is not None:
            img = img.getchannel(0) if img.mode != "L" else img
            if max(img.size) > max_size:
                img = img.resize((max_size, max_size), Image.LANCZOS)
        self.memo(key, img if img is not None else False, store=True)
        return img

    def memo(self, key, value=None, store=False):
        """Generic LRU slot (also used for per-material images): get when value is None, else store."""
        with self._lock:
            if value is None and not store:
                if key in self._items:
                    self._items.move_to_end(key)
                    return self._items[key]
                return None
            if key in self._items:
                self._bytes -= self._cost(self._items.pop(key))
            self._items[key] = value
            self._bytes += self._cost(value)
            while self._bytes > self.budget and len(self._items) > 1:
                self._bytes -= self._cost(self._items.popitem(last=False)[1])
            return value
