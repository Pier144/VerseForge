"""Custom decals of user skins (Skin Lab): a text and a picture on the decal slots the game itself leaves open.

Ships carry two kinds of sticker slot that the game fills at run time, so their materials have no picture of their
own and the viewer leaves them out:
  - name plates: MeshDecal with the texture "$RenderToTexture" (the game writes the ship's name there);
  - livery slots: MeshDecal + %STENCIL_MAP (the paint's logo or number, from the palette's stencil atlas).
materials.py marks both `stencil_decal` (the name plates also `rtt`). A skin's `decals` put a text on the first
kind and a picture on the second:  {"text": {"value", "color"}, "image": {"file": "images/<name>"}}.

Each slot is a few quads laid out on a region of a texture the game would draw. decorate() finds those regions
(islands of the mesh and their UV boxes), draws the text or the picture into each one with the proportions the
quad has in the world, and gives the material that picture: textures.TextureCache serves it under a "skinimg:"
path, so the viewer, the exports and the decal sheets treat it like any decal of the game."""
import hashlib
import io
from dataclasses import replace

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import textures

SIZE = 2048                    # the picture made for a slot material (its quads use regions of it)
TEXT_MAX = 40
# the game's own hull lettering: capitals only, so it is used for a text written in capitals
GAME_FONTS = ("objects/spaceships/ships/orig/textures/decals/font/variations/gunshipbold.ttf",
              "objects/spaceships/ships/orig/textures/decals/font/gunship.ttf")
# a bold sans of the system for a text with small letters (Windows, then the usual Linux ones)
SYSTEM_FONTS = ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf")


def kind_of(mat):
    """"text", "image" or None: which custom decal a material can take."""
    if not getattr(mat, "stencil_decal", False):
        return None
    return "text" if mat.rtt else "image"


def _islands(part):
    """The quads of a part as separate patches: [(u0, v0, u1, v1, world width / world height)]. Vertices at the
    same place are one (the mesh splits them along UV seams)."""
    if part.uvs is None or not len(part.faces):
        return []
    v, uv, f = np.asarray(part.vertices, np.float64), np.asarray(part.uvs, np.float64), np.asarray(part.faces)
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    place = {}
    for i in np.unique(f):
        k = tuple(np.round(v[i], 4))
        parent[find(int(i))] = find(place.setdefault(k, int(i)))
    for a, b, c in f:
        parent[find(int(a))] = find(int(b))
        parent[find(int(b))] = find(int(c))
    groups = {}
    for i in np.unique(f):
        groups.setdefault(find(int(i)), []).append(int(i))
    out = []
    for idx in groups.values():
        idx = np.asarray(idx)
        u0, v0 = uv[idx].min(0)
        u1, v1 = uv[idx].max(0)
        if u1 - u0 < 1e-5 or v1 - v0 < 1e-5:
            continue
        # how far a step in U and a step in V move on the surface: position ~ A @ (u, v) + b
        a_mat = np.column_stack([uv[idx] - uv[idx].mean(0), np.ones(len(idx))])
        sol = np.linalg.lstsq(a_mat, v[idx] - v[idx].mean(0), rcond=None)[0]
        w, h = np.linalg.norm(sol[0]) * (u1 - u0), np.linalg.norm(sol[1]) * (v1 - v0)
        aspect = float(w / h) if h > 1e-6 and w > 1e-6 else float((u1 - u0) / (v1 - v0))
        out.append((float(u0), float(v0), float(u1), float(v1), min(40.0, max(0.025, aspect))))
    return out


def slots(model):
    """{"text": n, "image": n}: how many patches of each kind the model has."""
    out = {"text": 0, "image": 0}
    for p in model.parts:
        k = kind_of(p.material)
        if k:
            out[k] += len(_islands(p))
    return out


_font_files = {}       # the game's font files, read once


def _font(archive, px, text=""):
    if text and text == text.upper():
        for path in GAME_FONTS:
            try:
                if path not in _font_files:
                    _font_files[path] = archive.read(path) if archive is not None and archive.exists(path) else None
                if _font_files[path]:
                    return ImageFont.truetype(io.BytesIO(_font_files[path]), px)
            except Exception:
                _font_files[path] = None
    for name in SYSTEM_FONTS:
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            pass
    return ImageFont.load_default(px)


def _text_tile(archive, text, color, aspect):
    """The text on a transparent tile with the proportions of the quad it goes on, fitted with a margin."""
    h = 256
    w = max(32, min(8192, int(round(h * aspect))))
    tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)
    px = int(h * 0.62)
    while px > 8:
        font = _font(archive, px, text)
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= w * 0.92 and box[3] - box[1] <= h * 0.74:
            break
        px = int(px * 0.92)
    draw.text(((w - (box[2] - box[0])) / 2 - box[0], (h - (box[3] - box[1])) / 2 - box[1]), text, font=font,
              fill=(*[int(c) for c in color], 255))
    return tile


def _image_tile(picture, aspect):
    """The picture, whole and centred, on a transparent tile with the proportions of the quad."""
    h = 512
    w = max(32, min(8192, int(round(h * aspect))))
    tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pic = picture.copy()
    pic.thumbnail((int(w * 0.92), int(h * 0.92)), Image.LANCZOS)
    tile.paste(pic, ((w - pic.width) // 2, (h - pic.height) // 2), pic)
    return tile


def _sheet(tiles):
    """One SIZE x SIZE picture with each tile stretched onto its UV box (the quad stretches it back)."""
    sheet = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    for (u0, v0, u1, v1), tile in tiles:
        x0, y0 = int(round(max(0.0, u0) * SIZE)), int(round(max(0.0, v0) * SIZE))
        x1, y1 = int(round(min(1.0, u1) * SIZE)), int(round(min(1.0, v1) * SIZE))
        if x1 - x0 < 2 or y1 - y0 < 2:
            continue
        sheet.paste(tile.resize((x1 - x0, y1 - y0), Image.LANCZOS), (x0, y0))
    return sheet


def _register(img):
    buf = io.BytesIO()
    img.save(buf, "PNG", compress_level=3)
    data = buf.getvalue()
    key = hashlib.sha1(data).hexdigest()[:16]
    return textures.register_custom(key, data)


def decorate(model, decals, archive=None, images=None):
    """Copy of `model` with the skin's decals on its open slots (see the module text). `images`: name -> bytes of a
    picture kept in the skin's file. Slots the skin says nothing for stay as they are (not drawn)."""
    decals = decals or {}
    text = (decals.get("text") or {}).get("value") or ""
    color = (decals.get("text") or {}).get("color") or [235, 235, 235]
    picture = None
    name = (decals.get("image") or {}).get("file")
    if name and images:
        try:
            data = images(name)
            picture = Image.open(io.BytesIO(data)).convert("RGBA") if data else None
        except Exception:
            picture = None
    if not text and picture is None:
        return model
    # every part of a slot material shares one picture: gather its patches first
    patches = {}
    for p in model.parts:
        k = kind_of(p.material)
        if (k == "text" and text) or (k == "image" and picture is not None):
            patches.setdefault((k, p.material.name), []).extend(_islands(p))
    made, tiles = {}, {}
    for (k, mat_name), isl in patches.items():
        placed = []
        for u0, v0, u1, v1, aspect in isl:
            box = tuple(round(x, 4) for x in (u0, v0, u1, v1))
            if any(b == box for b, _ in placed):
                continue                                  # the same region on both sides of the ship
            tkey = (k, round(aspect, 2))
            if tkey not in tiles:
                tiles[tkey] = _text_tile(archive, text, color, aspect) if k == "text" else _image_tile(picture, aspect)
            placed.append((box, tiles[tkey]))
        if placed:
            made[(k, mat_name)] = _register(_sheet(placed))
    if not made:
        return model
    parts = []
    for p in model.parts:
        path = made.get((kind_of(p.material), p.material.name))
        if path:
            mat = replace(p.material, kind="decal", diffuse=path, normal=None, stencil_colors=None, opacity=1.0,
                          color=(1.0, 1.0, 1.0), pom=False)
            p = replace(p, material=mat)
        parts.append(p)
    return replace(model, parts=parts, warnings=list(model.warnings), cache={})
