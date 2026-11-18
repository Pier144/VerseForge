"""Decal sheets: the markings of a model (text, numbers, emblems, livery stencils) laid flat at a kit scale, ready to
print on water-slide decal paper.

The game draws its markings as small textured meshes floating on the hull. Here the pieces that belong together (the
letters of a word, the parts of an emblem) are grouped, projected on their own plane as they are seen from outside,
and drawn at their real size divided by the scale. Dirt, glows and relief decals (panel seams, rivets) are left out:
they are not stickers.

Two PDFs come out, both at 600 dpi and true size:
- clear paper: the colours on a transparent sheet, each page followed by its white mask (where a white underprint or
  white toner is needed: home printers cannot print white);
- white paper: every decal on a patch of the hull colour, to be cut flush; white is the paper itself."""
import hashlib
import io
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import export

DPI = 600
PAPERS = {"a4": (210.0, 297.0), "letter": (215.9, 279.4)}
MARGIN_MM = 10.0
GAP_MM = 2.0
HEADER_MM = 9.0
BLEED_MM = 0.6           # hull-colour border around a decal on white paper
MIN_MM = 1.2             # smaller than this at the chosen scale: unreadable, left out
MIN_OPACITY = 0.15       # dirt and stains are fainter than this (0.08); text is 0.3 and up
TEX_SIZE = 4096
MAX_COPIES = 40
NOT_STICKERS = ("glow", "emissive", "dirt", "stitch", "pom", "light", "damage", "grime", "leak", "rust", "scratch")
STICKERS = ("decal", "text", "stencil", "graphic", "logo", "brand", "emblem", "marking", "livery", "sign")


def printable(mat):
    """Is this material a marking one would apply as a sticker?"""
    if mat.kind != "decal" or mat.pom or not mat.diffuse or mat.opacity < MIN_OPACITY:
        return False
    if mat.stencil_colors:
        return True
    n = mat.name.lower()
    if any(w in n for w in NOT_STICKERS):
        return False
    return mat.shader.lower() in ("meshdecal", "decal") or any(w in n for w in STICKERS)


@dataclass
class Decal:
    image: Image.Image       # RGBA at DPI, as seen from outside
    width_mm: float
    height_mm: float
    count: int = 1
    strength: float = 1.0    # the game's opacity: how strongly it covers the paint


# ------------------------------------------------------------------ grouping
class _Sets:
    def __init__(self, n):
        self.p = np.arange(n)

    def find(self, i):
        p = self.p
        while p[i] != i:
            p[i] = p[p[i]]
            i = p[i]
        return i

    def join(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.p[b] = a

    def labels(self):
        return np.array([self.find(i) for i in range(len(self.p))])


def _islands(tris):
    """Label per triangle: triangles sharing a corner (welded at 0.1 mm) are one island."""
    corners = np.round(tris.reshape(-1, 3) * 1e4).astype(np.int64)
    _, vid = np.unique(corners, axis=0, return_inverse=True)
    vid = vid.reshape(-1, 3)
    sets = _Sets(int(vid.max()) + 1)
    for a, b, c in vid:
        sets.join(a, b)
        sets.join(a, c)
    return np.array([sets.find(v) for v in vid[:, 0]])


def _clusters(tris, normals, areas):
    """Label per triangle: islands that lie on the same plane, close to each other (the letters of a word, the
    pieces of an emblem), become one decal."""
    isl = _islands(tris)
    ids, inv = np.unique(isl, return_inverse=True)
    n = len(ids)
    if n == 1 or n > 6000:
        return inv
    lo = np.full((n, 3), np.inf)
    hi = np.full((n, 3), -np.inf)
    np.minimum.at(lo, inv, tris.min(1))
    np.maximum.at(hi, inv, tris.max(1))
    nrm = np.zeros((n, 3))
    np.add.at(nrm, inv, normals * areas[:, None])
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12
    cen = (lo + hi) / 2
    size = (hi - lo).max(1)
    sets = _Sets(n)
    for i in range(n - 1):
        j = slice(i + 1, n)
        gap = np.linalg.norm(np.maximum(0, np.maximum(lo[j] - hi[i], lo[i] - hi[j])), axis=1)
        near = gap < 0.8 * np.minimum(size[i], size[j])
        flat = (nrm[j] @ nrm[i]) > 0.9
        level = np.abs((cen[j] - cen[i]) @ nrm[i]) < 0.3 * np.maximum(size[i], size[j]) + 1e-3
        for k in np.nonzero(near & flat & level)[0]:
            sets.join(i, i + 1 + int(k))
    return sets.labels()[inv]


# ------------------------------------------------------------------ drawing
def _texture(mat, cache):
    """RGBA float array (0..1) of a decal's picture: stencil masks take the paint's colours, the others their own
    colour times the material's."""
    img = cache.get(mat.diffuse, TEX_SIZE)
    if img is None:
        return None
    if mat.stencil_colors:
        img = export._stencil(img, mat.stencil_colors)
        tint = (1.0, 1.0, 1.0)
    else:
        tint = tuple(float(x) for x in export._srgb(np.clip(np.asarray(mat.color, np.float64), 0, 1)))
    a = np.asarray(img.convert("RGBA"), np.float32) / 255.0
    a[..., :3] *= tint
    return a


def _sample(tex, u, v):
    """Bilinear, repeating."""
    h, w = tex.shape[:2]
    x = (u % 1.0) * w - 0.5
    y = (v % 1.0) * h - 0.5
    x0, y0 = np.floor(x).astype(np.int64), np.floor(y).astype(np.int64)
    fx, fy = (x - x0)[:, None], (y - y0)[:, None]
    x1, y1 = (x0 + 1) % w, (y0 + 1) % h
    x0, y0 = x0 % w, y0 % h
    return ((tex[y0, x0] * (1 - fx) + tex[y0, x1] * fx) * (1 - fy)
            + (tex[y1, x0] * (1 - fx) + tex[y1, x1] * fx) * fy)


def _draw(tris, uvs, normal, tex, px_per_m):
    """One decal seen from outside (against `normal`), upright along its texture -> RGBA float image, or None."""
    e1, e2 = tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]
    d1, d2 = uvs[:, 1] - uvs[:, 0], uvs[:, 2] - uvs[:, 0]
    det = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
    ok = np.abs(det) > 1e-12
    if not ok.any():
        return None
    w = np.linalg.norm(np.cross(e1, e2), axis=1)[ok, None]
    dpdu = ((e1[ok] * d2[ok, 1:2] - e2[ok] * d1[ok, 1:2]) / det[ok, None] * w).sum(0)
    dpdv = ((e2[ok] * d1[ok, 0:1] - e1[ok] * d2[ok, 0:1]) / det[ok, None] * w).sum(0)
    right = dpdu - normal * (dpdu @ normal)
    if np.linalg.norm(right) < 1e-9:
        return None
    right /= np.linalg.norm(right)
    down = np.cross(right, normal)             # seen from outside: right x up points at the viewer
    if dpdv @ down < 0:                        # mirrored mapping: keep the picture upright, mirrored as on the hull
        right, down = -right, -down
    xy = np.stack([tris @ right, tris @ down], axis=-1) * px_per_m
    lo = xy.reshape(-1, 2).min(0)
    xy = xy - lo + 1.0
    size = np.ceil(xy.reshape(-1, 2).max(0) + 1.0).astype(int)
    if size.min() < 2 or size.max() > 20000:
        return None
    out = np.zeros((size[1], size[0], 4), np.float32)
    for t, uv in zip(xy, uvs):
        x0, y0 = np.floor(t.min(0)).astype(int)
        x1, y1 = np.ceil(t.max(0)).astype(int) + 1
        m = np.array([[t[1, 0] - t[0, 0], t[2, 0] - t[0, 0]], [t[1, 1] - t[0, 1], t[2, 1] - t[0, 1]]])
        d = m[0, 0] * m[1, 1] - m[0, 1] * m[1, 0]
        if abs(d) < 1e-9:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1) + 0.5 - t[0, 0], np.arange(y0, y1) + 0.5 - t[0, 1])
        b = (gx * m[1, 1] - gy * m[0, 1]) / d
        c = (gy * m[0, 0] - gx * m[1, 0]) / d
        a = 1.0 - b - c
        inside = (a >= -0.02) & (b >= -0.02) & (c >= -0.02)
        if not inside.any():
            continue
        a, b, c = a[inside], b[inside], c[inside]
        col = _sample(tex, a * uv[0, 0] + b * uv[1, 0] + c * uv[2, 0], a * uv[0, 1] + b * uv[1, 1] + c * uv[2, 1])
        view = out[y0:y1, x0:x1]
        keep = col[:, 3] >= view[inside][:, 3]         # where pieces overlap, the more opaque one shows
        idx = np.nonzero(inside)
        view[idx[0][keep], idx[1][keep]] = col[keep]
    return out


def _trim(img):
    a = img[..., 3] > 0.03
    if not a.any():
        return None
    ys, xs = np.nonzero(a.any(1))[0], np.nonzero(a.any(0))[0]
    return img[ys[0]:ys[-1] + 1, xs[0]:xs[-1] + 1]


def collect(model, textures, scale):
    """-> (decals sorted tall to short, number left out as too small). Equal decals are one entry with a count."""
    px_per_m = DPI / 25.4 * 1000.0 / scale
    px_per_mm = DPI / 25.4
    groups = {}
    for p in model.parts:
        if p.uvs is None or not len(p.faces) or not printable(p.material):
            continue
        m = p.material
        key = (m.diffuse.lower(), m.stencil_colors, tuple(np.round(m.color, 3)), round(m.opacity, 2))
        groups.setdefault(key, (m, [], []))
        groups[key][1].append(p.vertices[p.faces])
        groups[key][2].append(p.uvs[p.faces])
    found, small = {}, 0
    for mat, tl, ul in groups.values():
        tris, uvs = np.vstack(tl).astype(np.float64), np.vstack(ul).astype(np.float64)
        cross = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
        areas = np.linalg.norm(cross, axis=1) / 2
        good = areas > 1e-10
        if not good.any():
            continue
        tris, uvs, cross, areas = tris[good], uvs[good], cross[good], areas[good]
        normals = cross / (2 * areas[:, None])
        tex = None
        labels = _clusters(tris, normals, areas)
        for lab in np.unique(labels):
            sel = labels == lab
            t, uv = tris[sel], uvs[sel]
            extent = (t.reshape(-1, 3).max(0) - t.reshape(-1, 3).min(0)).max() * 1000.0 / scale
            if extent < MIN_MM:
                small += 1
                continue
            uspan = uv.reshape(-1, 2).max(0) - uv.reshape(-1, 2).min(0)
            if uspan.max() > 1.5:                       # a repeating strip (hazard tape, trims), not a sticker
                continue
            if tex is None:
                tex = _texture(mat, textures)
                if tex is None:
                    break
            n = (normals[sel] * areas[sel, None]).sum(0)
            n /= np.linalg.norm(n) + 1e-12
            img = _draw(t, uv, n, tex, px_per_m)
            img = _trim(img) if img is not None else None
            if img is None:
                continue
            h, w = img.shape[:2]
            if max(w, h) / px_per_mm < MIN_MM:
                small += 1
                continue
            pil = Image.fromarray((img.clip(0, 1) * 255).astype(np.uint8), "RGBA")
            # the same sticker placed twice differs by a pixel of rounding: compare a coarse thumbnail and the size
            thumb = np.asarray(pil.resize((8, 8), Image.BOX), np.uint8) // 40
            sig = hashlib.md5(thumb.tobytes()).hexdigest()
            k = (sig, round(w / px_per_mm * 2), round(h / px_per_mm * 2))
            if k in found:
                found[k].count += 1
            else:
                found[k] = Decal(pil, w / px_per_mm, h / px_per_mm, 1, float(mat.opacity))
    out = sorted(found.values(), key=lambda d: (-d.height_mm, -d.width_mm))
    return out, small


def hull_colour(model):
    """sRGB 0..255 of the paint that covers most of the model."""
    area = {}
    for p in model.parts:
        if p.material.kind != "solid" or not len(p.faces):
            continue
        t = p.vertices[p.faces]
        a = float(np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum())
        k = tuple(np.round(p.material.color, 3))
        area[k] = area.get(k, 0.0) + a
    if not area:
        return (128, 128, 128)
    c = np.clip(np.asarray(max(area, key=area.get), np.float64), 0, 1)
    return tuple(int(round(float(x) * 255)) for x in export._srgb(c))


# ------------------------------------------------------------------ pages
def _font(mm):
    px = max(8, int(round(mm * DPI / 25.4)))
    for name in ("bahnschrift.ttf", "segoeui.ttf", "DejaVuSans.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default(px)


def _layout(decals, paper):
    """Shelf packing -> list of pages, each a list of (decal, x px, y px). Decals larger than the page are left out
    and counted."""
    mm = DPI / 25.4
    pw, ph = (int(round(x * mm)) for x in PAPERS[paper])
    x0, y0 = int(MARGIN_MM * mm), int((MARGIN_MM + HEADER_MM) * mm)
    x1, y1 = pw - int(MARGIN_MM * mm), ph - int(MARGIN_MM * mm)
    gap = int((GAP_MM + 2 * BLEED_MM) * mm)
    pages, page, x, y, row, big = [], [], x0, y0, 0, 0
    for d in decals:
        w, h = d.image.size
        if w > x1 - x0 or h > y1 - y0:
            big += 1
            continue
        for _ in range(min(d.count, MAX_COPIES)):
            if x + w > x1:
                x, y, row = x0, y + row + gap, 0
            if y + h > y1:
                pages.append(page)
                page, x, y, row = [], x0, y0, 0
            page.append((d, x, y))
            x += w + gap
            row = max(row, h)
    if page:
        pages.append(page)
    return pages, (pw, ph), big


def _header(img, text, ink=0):
    """Title line and a 10 mm ruler (five 2 mm steps) to check the print came out at 100%."""
    mm = DPI / 25.4
    d = ImageDraw.Draw(img)
    x, y = int(MARGIN_MM * mm), int(MARGIN_MM * mm)
    d.text((x, y), text, font=_font(2.6), fill=ink)
    rx = img.width - int(MARGIN_MM * mm) - int(10 * mm)
    for i in range(5):
        if i % 2 == 0:
            d.rectangle([rx + int(i * 2 * mm), y, rx + int((i + 1) * 2 * mm) - 1, y + int(1.2 * mm)], fill=ink)
    d.rectangle([rx, y, rx + int(10 * mm) - 1, y + int(1.2 * mm)], outline=ink, width=2)
    d.text((rx, y + int(1.6 * mm)), "10 mm", font=_font(2.0), fill=ink)


def _pdf(pages):
    buf = io.BytesIO()
    pages[0].save(buf, "PDF", resolution=DPI, save_all=True, append_images=pages[1:], quality=95)
    return buf.getvalue()


def sheets(decals, paper, hull, title, scale):
    """-> (clear-paper PDF, white-paper PDF, info dict). hull: sRGB 0..255 of the paint under the decals."""
    pages, size, big = _layout(decals, paper)
    if not pages:
        return None, None, {"decals": 0, "pieces": 0, "pages": 0, "too_big": big}
    mm = DPI / 25.4
    bleed = int(round(BLEED_MM * mm))
    clear, white = [], []
    for n, page in enumerate(pages, 1):
        head = f"{title}   1:{scale:g}   {n}/{len(pages)}"
        colour = Image.new("RGB", size, (255, 255, 255))
        mask = Image.new("L", size, 255)
        patch = Image.new("RGB", size, (255, 255, 255))
        for d, x, y in page:
            colour.paste(d.image.convert("RGB"), (x, y), d.image.getchannel("A"))
            mask.paste(0, (x, y), d.image.getchannel("A"))
            w, h = d.image.size
            patch.paste(hull, (x - bleed, y - bleed, x + w + bleed, y + h + bleed))
            alpha = d.image.getchannel("A").point(lambda a, s=d.strength: int(a * s))
            patch.paste(d.image.convert("RGB"), (x, y), alpha)
        _header(colour, head + "   clear paper: colours   print at 100%", (0, 0, 0))
        _header(mask, head + "   clear paper: white mask (black = white ink)   print at 100%", 0)
        _header(patch, head + "   white paper: cut flush to each patch   print at 100%", (0, 0, 0))
        clear += [colour, mask]
        white.append(patch)
    info = {"decals": len(decals), "pieces": sum(len(p) for p in pages), "pages": len(pages), "too_big": big}
    return _pdf(clear), _pdf(white), info
