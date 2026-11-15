"""Space backdrops for the viewer, built from the game's sky textures as 360° equirectangular panoramas.

- "pyro": the Pyro system's nebula skybox, six cube faces (Textures/PU/spacescaping/system/Pyro_sys_neb_*). The files
  are named front/right/back/left/up/bot but several are stored rotated: the turns below make all twelve seams of
  the cube meet (checked by comparing the edge pixels of neighbouring faces).
- "stanton": Stanton's sky is made in game of separate 2D layers (nebula cards, the gas giant Crusader on a card,
  stars); here they are laid out on the sphere around generated stars.

Panoramas use three.js' equirectangular convention: column -> longitude atan2(z, x), row 0 = straight up (+Y), so the
viewer shows them as they are with EquirectangularReflectionMapping."""
import math

import numpy as np
from PIL import Image

PYRO_DIR = "Textures/PU/spacescaping/system/"
# face -> (file suffix, numpy rot90 turns) for a cube seen from inside: front = -Z, right = +X, up = +Y
PYRO_FACES = {"front": ("front", 0), "right": ("right", 1), "back": ("back", 2), "left": ("left", 3),
              "up": ("up", 2), "bot": ("bot", 0)}

STANTON_DIR = "Objects/space/2d/skybox/stanton/"
# the default camera looks towards longitude ~48° and down by ~26° (it sees about -46°..-6°): the interesting parts
# are put there
VIEW_LON = 48.0
VIEW_LAT = -24.0

NAMES = ("pyro", "stanton")


def _dirs(width):
    """Unit view directions (x, y, z) of every pixel of a width x width/2 panorama."""
    h = width // 2
    lon = (np.arange(width) + 0.5) / width * 2 * np.pi - np.pi
    lat = np.pi / 2 - (np.arange(h) + 0.5) / h * np.pi
    lon, lat = np.meshgrid(lon, lat)
    c = np.cos(lat)
    return c * np.cos(lon), np.sin(lat), c * np.sin(lon)


def _bilinear(img, u, v):
    """Sample img (H, W, C float) at u, v in 0..1 (u right, v down), clamped at the edges."""
    h, w = img.shape[:2]
    x = np.clip(u * w - 0.5, 0, w - 1)
    y = np.clip(v * h - 0.5, 0, h - 1)
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    x1, y1 = np.minimum(x0 + 1, w - 1), np.minimum(y0 + 1, h - 1)
    fx, fy = (x - x0)[..., None], (y - y0)[..., None]
    top = img[y0, x0] * (1 - fx) + img[y0, x1] * fx
    bot = img[y1, x0] * (1 - fx) + img[y1, x1] * fx
    return top * (1 - fy) + bot * fy


def _yaw(x, z, deg):
    """Turn the directions about +Y (moves the panorama's content by +deg of longitude)."""
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)
    return x * ca + z * sa, -x * sa + z * ca


def pyro(textures, width=4096, face_size=2048):
    faces = {}
    for name, (suffix, turns) in PYRO_FACES.items():
        img = textures.get(f"{PYRO_DIR}Pyro_sys_neb_{suffix}.dds", face_size)
        if img is None:
            return None
        faces[name] = np.rot90(np.asarray(img.convert("RGB"), np.float32), turns)
    x, y, z = _dirs(width)
    # the brightest part of the nebula (the front face) faces the default camera
    x, z = _yaw(x, z, 90.0 + VIEW_LON)
    ax, ay, az = np.abs(x), np.abs(y), np.abs(z)
    out = np.zeros(x.shape + (3,), np.float32)
    with np.errstate(divide="ignore", invalid="ignore"):
        pick = [
            ("front", (az >= ax) & (az >= ay) & (z < 0), x / az, -y / az),
            ("back", (az >= ax) & (az >= ay) & (z >= 0), -x / az, -y / az),
            ("right", (ax > az) & (ax >= ay) & (x >= 0), z / ax, -y / ax),
            ("left", (ax > az) & (ax >= ay) & (x < 0), -z / ax, -y / ax),
            ("up", (ay > ax) & (ay > az) & (y >= 0), x / ay, -z / ay),
            ("bot", (ay > ax) & (ay > az) & (y < 0), x / ay, z / ay),
        ]
        for name, m, s, t in pick:
            if m.any():
                out[m] = _bilinear(faces[name], (s[m] + 1) / 2, (t[m] + 1) / 2)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


def _fade(t, edge):
    """1 inside, smoothly down to 0 over the outer `edge` fraction on both sides."""
    f = np.clip(np.minimum(t, 1 - t) / edge, 0, 1)
    return f * f * (3 - 2 * f)


def _card(out, x, y, z, img, lon, lat, width, height, gain=1.0, mode="add"):
    """Lay a flat 2D layer on the sky, centred on (lon, lat) and spanning width x height degrees of longitude and
    latitude (good for the wide nebula cards, which wrap round a good part of the sky)."""
    a = np.asarray(img.convert("RGBA"), np.float32) / 255.0
    plon = np.degrees(np.arctan2(z, x))
    plat = np.degrees(np.arcsin(np.clip(y, -1, 1)))
    dlon = (plon - lon + 180.0) % 360.0 - 180.0
    u = dlon / width + 0.5
    v = 0.5 - (plat - lat) / height
    m = (u >= 0) & (u <= 1) & (v >= 0) & (v <= 1)
    s = _bilinear(a, u[m], v[m])
    # the cards carry a faint glow up to their edges: fade them out so no rectangle shows on the sky
    s = s * (_fade(u[m], 0.22) * _fade(v[m], 0.3))[:, None]
    if mode == "add":
        out[m] += s[:, :3] * 255.0 * gain
    else:
        out[m] = out[m] * (1 - s[:, 3:4]) + s[:, :3] * 255.0 * s[:, 3:4] * gain


def _disc(out, x, y, z, img, lon, lat, size, gain=1.0):
    """A round object (a planet card) seen in perspective: gnomonic projection around its direction, `size` degrees
    across, blended with its alpha."""
    a = np.asarray(img.convert("RGBA"), np.float32) / 255.0
    lo, la = math.radians(lon), math.radians(lat)
    c = np.array([math.cos(la) * math.cos(lo), math.sin(la), math.cos(la) * math.sin(lo)])
    e1 = np.cross([0.0, 1.0, 0.0], c)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(c, e1)
    d = x * c[0] + y * c[1] + z * c[2]
    half = math.tan(math.radians(size) / 2)
    with np.errstate(divide="ignore", invalid="ignore"):
        px = (x * e1[0] + y * e1[1] + z * e1[2]) / d
        py = (x * e2[0] + y * e2[1] + z * e2[2]) / d
    u = -px / half / 2 + 0.5        # e1 points west of the planet as seen from inside the sphere
    v = 0.5 - py / half / 2
    m = (d > 0) & (u >= 0) & (u <= 1) & (v >= 0) & (v <= 1)
    s = _bilinear(a, u[m], v[m])
    out[m] = out[m] * (1 - s[:, 3:4]) + s[:, :3] * 255.0 * s[:, 3:4] * gain


def _stars(out, width, seed=7, count=26000):
    """Generated stars: uniform on the sphere, few bright ones, white to pale blue/amber."""
    rng = np.random.default_rng(seed)
    h = width // 2
    zs = rng.uniform(-1, 1, count)
    lon = rng.uniform(-np.pi, np.pi, count)
    lat = np.arcsin(zs)
    col = ((lon + np.pi) / (2 * np.pi) * width).astype(int) % width
    row = np.clip(((np.pi / 2 - lat) / np.pi * h).astype(int), 0, h - 1)
    b = rng.pareto(2.2, count) * 22 + 10
    b = np.minimum(b, 255)
    tint = rng.choice([[1.0, 1.0, 1.0], [0.8, 0.88, 1.0], [1.0, 0.9, 0.75]], count, p=[0.6, 0.28, 0.12])
    for (r, c, br, t) in zip(row, col, b, tint):
        out[r, c] += t * br
        if br > 120:            # bright stars: a small soft halo
            for dr, dc, f in ((-1, 0, .35), (1, 0, .35), (0, -1, .35), (0, 1, .35)):
                out[(r + dr) % h, (c + dc) % width] += t * br * f


def stanton(textures, width=4096):
    x, y, z = _dirs(width)
    out = np.zeros(x.shape + (3,), np.float32)
    _stars(out, width)
    layers = [
        # (file, lon, lat, width°, height°, gain): the teal nebula fields Stanton is known for, a faint dusty band
        ("Nebula/stanton_nebula_b.dds", VIEW_LON - 8, VIEW_LAT + 4, 200, 100, 2.2),
        ("Nebula/stanton_nebula_c.dds", VIEW_LON + 170, 8, 190, 95, 1.8),
        ("Crusader/2d_skybox_stanton_Nebula_diff.dds", VIEW_LON + 95, 28, 150, 60, 0.9),
    ]
    for f, lon, lat, w, h, g in layers:
        img = textures.get(STANTON_DIR + f, 2048)
        if img is not None:
            _card(out, x, y, z, img, lon, lat, w, h, g)
    crusader = textures.get(STANTON_DIR + "Crusader/2d_skybox_stanton_crusader.dds", 2048)
    if crusader is not None:
        _disc(out, x, y, z, crusader, VIEW_LON + 14, VIEW_LAT + 10, 19, 1.0)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


def build(name, textures, width=4096):
    """Panorama `name` (see NAMES) as a PIL image, or None when the game files are missing."""
    if name == "pyro":
        return pyro(textures, width)
    if name == "stanton":
        return stanton(textures, width)
    raise ValueError(name)
