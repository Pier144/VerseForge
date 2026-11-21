"""User skins (Skin Lab): a paint of the game with the user's own colours and finishes.

A skin is a `.vfskin` file: a zip holding `skin.json` (and, later, the user's images under `images/`). The library is
a folder of those files, so sharing a skin is copying its file. The server turns a skin into one more paint variant
(`apply`): the material of the paint it starts from and that paint's palette with the user's entries in place, so it
goes through everything a paint goes through (model.with_variant, the instant switch, the exports).

docs/superpowers/specs/2026-11-21-skin-lab-colori-design.md"""
import io
import json
import os
import re
import uuid
import zipfile
from datetime import datetime, timezone

FORMAT = 1
EXT = ".vfskin"
SLOTS = "ABC"
NAME_MAX = 60

# Finishes. A palette entry sets the tint, the reflectance (specColor, sRGB, gamma 2 like the tint) and the
# glossiness (0-255) of the paint layers that use it. Glossiness of each preset; "metal" also moves the colour from
# the tint to the reflectance, the way the game's own metals are a black albedo under a coloured F0.
PRESETS = {"gloss": 225, "satin": 165, "matte": 95, "metal": 205}
DIELECTRIC = [51, 51, 51]      # F0 0.04 (paint, plastic): (51 / 255) ** 2
METAL_TINT = 0.2               # what is left of the colour in a metal's albedo: (0.2) ** 2 = 4 %
NEUTRAL = [128, 128, 128]      # an entry the paint does not define


class SkinError(ValueError):
    """code: bad_file, newer, invalid, missing."""

    def __init__(self, code, text):
        super().__init__(text)
        self.code = code


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rgb(v, what):
    if (not isinstance(v, (list, tuple)) or len(v) != 3
            or not all(isinstance(x, (int, float)) and not isinstance(x, bool) and 0 <= x <= 255 for x in v)):
        raise SkinError("invalid", f"{what}: three numbers from 0 to 255 expected")
    return [int(round(x)) for x in v]


def validate(data):
    """The skin, tidied (a copy). Fields this version does not know are kept as they are. Raises SkinError."""
    if not isinstance(data, dict):
        raise SkinError("invalid", "not a skin")
    fmt = data.get("format", FORMAT)
    if not isinstance(fmt, int) or isinstance(fmt, bool) or fmt < 1:
        raise SkinError("invalid", "format: a whole number expected")
    if fmt > FORMAT:
        raise SkinError("newer", "made with a newer VerseForge")
    out = dict(data)
    out["format"] = fmt
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise SkinError("invalid", "name: missing")
    out["name"] = " ".join(name.split())[:NAME_MAX]
    if "id" in data and data["id"] is not None:
        if not isinstance(data["id"], str) or not re.fullmatch(r"[0-9a-f]{8}", data["id"]):
            raise SkinError("invalid", "id: eight hexadecimal digits expected")
    else:
        out.pop("id", None)
    target = data.get("target")
    if not isinstance(target, dict) or not isinstance(target.get("model"), str) or not target["model"].strip():
        raise SkinError("invalid", "target: the model is missing")
    out["target"] = {**target, "model": target["model"].replace("\\", "/"), "label": str(target.get("label") or "")}
    base = data.get("base") or {}
    if not isinstance(base, dict):
        raise SkinError("invalid", "base: an object expected")
    for k in ("material", "palette"):
        if base.get(k) is not None and not isinstance(base[k], str):
            raise SkinError("invalid", f"base.{k}: text expected")
    out["base"] = {**base, "material": base.get("material") or "", "palette": base.get("palette") or "",
                   "label": str(base.get("label") or "")}
    pal = data.get("palette") or {}
    if not isinstance(pal, dict):
        raise SkinError("invalid", "palette: an object expected")
    clean = dict(pal)
    for k in (*SLOTS, "glass"):
        if pal.get(k) is None:
            clean.pop(k, None)
        else:
            clean[k] = _rgb(pal[k], f"palette.{k}")
    finish = pal.get("finish") or {}
    if not isinstance(finish, dict):
        raise SkinError("invalid", "palette.finish: an object expected")
    fin = {}
    for k, f in finish.items():
        if k not in SLOTS or not isinstance(f, dict):
            raise SkinError("invalid", f"palette.finish.{k}: unknown entry")
        preset = f.get("preset", "base")
        if preset != "base" and preset not in PRESETS:
            raise SkinError("invalid", f"palette.finish.{k}: unknown finish")
        one = {**f, "preset": preset}
        if f.get("gloss") is None:
            one.pop("gloss", None)
        else:
            g = f["gloss"]
            if not isinstance(g, (int, float)) or isinstance(g, bool) or not 0 <= g <= 255:
                raise SkinError("invalid", f"palette.finish.{k}.gloss: a number from 0 to 255 expected")
            one["gloss"] = int(round(g))
        fin[k] = one
    clean["finish"] = fin
    out["palette"] = clean
    out.setdefault("pattern", None)
    out.setdefault("decals", {})
    out["author"] = str(data.get("author") or "")
    return out


# ---------------------------------------------------------------- the paint a skin makes

def effective(base_palette, skin):
    """The palette (variants._palette shape) of `skin` over the palette of the paint it starts from (or None).
    Entries A, B and C always come out with a colour, a reflectance and a glossiness, so the paint layers never fall
    back to the layer's own reflectance map while a skin is on: changing a finish only changes numbers."""
    base = base_palette or {}
    pal = skin.get("palette") or {}
    finish = pal.get("finish") or {}
    out = {"name": base.get("name") or "", "glass": pal.get("glass") or base.get("glass"),
           "decal": base.get("decal"), "decal_colors": base.get("decal_colors") or [None, None, None],
           "spec": {}, "gloss": {}}
    for k in SLOTS:
        colour = list(pal.get(k) or base.get(k) or NEUTRAL)
        f = finish.get(k) or {}
        preset = f.get("preset", "base")
        if preset == "base":
            spec = (base.get("spec") or {}).get(k) or DIELECTRIC
            gloss = (base.get("gloss") or {}).get(k)
            gloss = PRESETS["satin"] if gloss is None else gloss
        elif preset == "metal":
            spec, gloss = colour, PRESETS["metal"]
            colour = [int(round(c * METAL_TINT)) for c in colour]
        else:
            spec, gloss = DIELECTRIC, PRESETS[preset]
        if f.get("gloss") is not None:
            gloss = f["gloss"]
        out[k], out["spec"][k], out["gloss"][k] = colour, list(spec), int(gloss)
    return out


def base_ref(variant):
    """What a skin remembers of the paint it starts from. Not its tag: tags are positions in a list sorted by the
    paint's name in the game's language, so they move with a patch or a change of language."""
    v = variant or {}
    return {"material": v.get("material") or "", "palette": (v.get("palette") or {}).get("name") or "",
            "label": v.get("label") or ""}


def find_base(variants, skin):
    """(the paint `skin` starts from among a model's variants, whether it is the one the skin names). A paint that is
    gone gives the stock one; a model with no paints gives (None, True) when the skin names none either."""
    want = skin.get("base") or {}
    key = (want.get("material") or "", want.get("palette") or "")
    for v in variants:
        if (v.get("material") or "", (v.get("palette") or {}).get("name") or "") == key:
            return v, True
    if not variants:
        return None, key == ("", "")
    return next((v for v in variants if v.get("stock")), variants[0]), False


def apply(base, skin, tag):
    """The paint variant of `skin` over `base` (a variant of the model, or None for a model without paints)."""
    b = base or {}
    return {"tag": tag, "label": skin.get("name") or "", "material": b.get("material"),
            "palette": effective(b.get("palette"), skin), "stock": False, "custom": True}


# ---------------------------------------------------------------- files

def read_bytes(data):
    """The skin inside the bytes of a .vfskin file, validated. Raises SkinError."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if "skin.json" not in z.namelist():
                raise SkinError("bad_file", "not a VerseForge skin: no skin.json inside")
            raw = z.read("skin.json")
    except zipfile.BadZipFile:
        raise SkinError("bad_file", "not a VerseForge skin file") from None
    try:
        skin = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise SkinError("bad_file", "not a VerseForge skin: skin.json cannot be read") from None
    return validate(skin)


def _read(path):
    with open(path, "rb") as f:
        return read_bytes(f.read())


def _files(folder):
    try:
        names = sorted(os.listdir(folder), key=str.lower)
    except OSError:
        return []
    return [os.path.join(folder, n) for n in names if n.lower().endswith(EXT)]


_cache = {}     # path -> (mtime_ns, size, skin or None): the library is read again only when a file changed


def _entry(path):
    try:
        st = os.stat(path)
    except OSError:
        _cache.pop(path, None)
        return None
    hit = _cache.get(path)
    if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        skin = hit[2]
    else:
        try:
            skin = _read(path)
        except (SkinError, OSError):
            skin = None                              # not a skin, or one a newer version made: not listed
        _cache[path] = (st.st_mtime_ns, st.st_size, skin)
    return (skin, st.st_mtime_ns) if skin and skin.get("id") else None


def _same_model(a, b):
    return a.replace("\\", "/").lower() == b.replace("\\", "/").lower()


def list_skins(folder, model=None):
    """[(skin, file path, stamp)] of the library, by name; `model`: only the skins of that model. The stamp changes
    whenever the file does: it keys the caches of what was built from the skin."""
    out, seen = [], set()
    for path in _files(folder):
        e = _entry(path)
        if not e or e[0]["id"] in seen:               # a copied file: the first one (by file name) is the skin
            continue
        seen.add(e[0]["id"])
        if model is None or _same_model(e[0]["target"]["model"], model):
            out.append((e[0], path, e[1]))
    return sorted(out, key=lambda t: t[0]["name"].lower())


def find(folder, skin_id):
    """(skin, file path, stamp) or None."""
    return next((t for t in list_skins(folder) if t[0]["id"] == skin_id), None)


def _numbered(name, taken):
    """`name`, or `name 2`, `name 3`… when taken (compared whatever the case)."""
    low = {t.lower() for t in taken}
    if name.lower() not in low:
        return name
    stem = re.sub(r" \d+$", "", name)
    n = 2
    while f"{stem} {n}".lower() in low:
        n += 1
    return f"{stem[:NAME_MAX - len(str(n)) - 1]} {n}"


def _file_stem(name):
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return stem or "skin"


def save(folder, data):
    """Write a skin into the library (new without an id, else in place of the one with that id) and return it.
    A name another skin of the same model already has gets a number. Images already in the file are kept."""
    skin = validate(data)
    os.makedirs(folder, exist_ok=True)
    everything = list_skins(folder)
    old = next((t for t in everything if t[0]["id"] == skin.get("id")), None) if skin.get("id") else None
    if not skin.get("id"):
        skin["id"] = uuid.uuid4().hex[:8]
    others = [t for t in everything if t[0]["id"] != skin["id"]]
    skin["name"] = _numbered(skin["name"], [t[0]["name"] for t in others
                                            if _same_model(t[0]["target"]["model"], skin["target"]["model"])])
    now = _now()
    skin["created"] = (old[0].get("created") if old else None) or skin.get("created") or now
    skin["modified"] = now
    used = {os.path.basename(t[1])[:-len(EXT)] for t in others}
    used |= {os.path.basename(p)[:-len(EXT)] for p in _files(folder) if not old or p != old[1]}
    path = os.path.join(folder, _numbered(_file_stem(skin["name"]), used) + EXT)
    extra = {}
    if old:
        try:
            with zipfile.ZipFile(old[1]) as z:
                extra = {n: z.read(n) for n in z.namelist() if n != "skin.json"}
        except (OSError, zipfile.BadZipFile):
            extra = {}
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("skin.json", json.dumps(skin, indent=2, ensure_ascii=False))
        for n, blob in extra.items():
            z.writestr(n, blob)
    os.replace(tmp, path)
    if old and os.path.normcase(old[1]) != os.path.normcase(path):
        try:
            os.remove(old[1])                         # renamed: the file follows the name
        except OSError:
            pass
    return skin


def delete(folder, skin_id):
    """Take a skin out of the library. The file is not destroyed: it moves to the `Deleted` folder inside the
    library (a later one of the same name replaces it). True when there was one."""
    hit = find(folder, skin_id)
    if not hit:
        return False
    bin_dir = os.path.join(folder, "Deleted")
    os.makedirs(bin_dir, exist_ok=True)
    os.replace(hit[1], os.path.join(bin_dir, os.path.basename(hit[1])))
    return True


def import_bytes(folder, data):
    """Add the skin of a .vfskin file (its bytes) to the library; returns it. A skin already there under the same id
    is not replaced: the imported one becomes a new skin. Raises SkinError."""
    skin = read_bytes(data)
    if not skin.get("id") or find(folder, skin["id"]):
        skin.pop("id", None)
    saved = save(folder, skin)
    try:                                              # the images of the file come along
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            extra = {n: z.read(n) for n in z.namelist() if n != "skin.json" and not n.endswith("/")}
    except zipfile.BadZipFile:
        extra = {}
    if extra:
        hit = find(folder, saved["id"])
        with zipfile.ZipFile(hit[1], "a", zipfile.ZIP_DEFLATED) as z:
            for n, blob in extra.items():
                z.writestr(n, blob)
    return saved
