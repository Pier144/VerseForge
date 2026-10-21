"""Searchable catalogue of the geometry assets inside Data.p4k."""
import re
from collections import defaultdict
from dataclasses import dataclass

from . import i18n

GEOMETRY_EXT = (".cgf", ".cga", ".skin", ".cdf", ".chr")

# category ids in display order; labels in i18n.CATEGORIES
CATEGORIES = ["weapons", "attachments", "tools", "armor", "clothing", "ships", "components", "vehicles", "characters",
              "props", "environments", "other"]

CAT_ORDER = {k: i for i, k in enumerate(CATEGORIES)}

MANUFACTURERS = {
    "aegs": "Aegis Dynamics", "anvl": "Anvil Aerospace", "argo": "Argo Astronautics", "banu": "Banu",
    "cnou": "Consolidated Outland", "crus": "Crusader Industries", "drak": "Drake Interplanetary",
    "espr": "Esperia", "gama": "Gatac Manufacture", "grin": "Greycat Industrial", "krig": "Kruger Intergalactic",
    "misc": "MISC", "mrai": "Mirai", "orig": "Origin Jumpworks", "rsi": "Roberts Space Industries",
    "tmbl": "Tumbril", "vncl": "Vanduul", "xian": "Aopoa", "xnaa": "Aopoa", "behr": "Behring",
    "ksar": "Kastak Arms", "gmni": "Gemini", "klwe": "Klaus & Werner", "apar": "Apocalypse Arms",
    "volt": "VOLT", "lbco": "Lightning Bolt Co.", "hrst": "Hurston Dynamics", "amrs": "Amon & Reese",
    "sasu": "Sakura Sun", "nova": "Nova Pyrotechnica", "kbar": "KnightBridge Arms", "toag": "Thermyte Concern",
    "clda": "Clark Defense Systems", "rrs": "Roussimoff Rehabilitation Systems", "cds": "Clark Defense Systems",
    "qrt": "Quirinus Tech", "vgl": "Virgil Ltd", "doom": "Doomsday", "grey": "Greycat Industrial",
    "mxox": "MaxOx", "jokr": "Joker Engineering", "wlop": "Wei-Tek", "wetk": "Wei-Tek", "aopo": "Aopoa",
}

# weapon type codes found in file names (brfl, smg, pstl…); their names are in i18n.WEAPON_TYPES
WEAPON_TYPES = set(i18n.WEAPON_TYPES)

JUNK = re.compile(r"(_lod\d|lod\d$|_proxy|proxy_|physics|visarea|_phys$|_dmg|damage|destroyed|debris|"
                  r"decal|_glow|glow_|cinematic|_shadow|occluder|_collision|_ph$|_helper|placeholder)", re.I)


@dataclass
class Item:
    path: str          # Data-relative, forward slashes, original case
    name: str
    manu: str          # manufacturer name or ""
    kind: str          # weapon type code, "hull" or "" (translated by subtitle())
    category: str
    ext: str
    size: int
    main: bool
    key: str           # lowercase alphanumeric search key
    game_name: bool = False
    stem: str = ""     # file name, shown under in-game names


def subtitle(it):
    kind = i18n.t("hull") if it.kind == "hull" else i18n.WEAPON_TYPES.get(it.kind, "")
    return " · ".join(x for x in (it.manu, kind, it.stem) if x)


def compact(s):
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def categorize(p):
    l = p.lower()
    if l.startswith("objects/fps_weapons/attachments"):
        return "attachments"
    if l.startswith("objects/fps_weapons/gadgets") or "/multitool" in l or "/fps_devices" in l or l.startswith("objects/usables"):
        return "tools"
    if l.startswith(("objects/fps_weapons", "objects/weapon/")):
        return "weapons"
    if l.startswith("objects/characters/human/"):
        if "/armor/" in l:
            return "armor"
        if any(k in l for k in ("/clothing/", "/wearables/", "/backpack/")):
            return "clothing"
        return "characters"
    if l.startswith("objects/characters/powersuit") or l.startswith("objects/vehicles"):
        return "vehicles"
    if l.startswith("objects/characters"):
        return "characters"
    if l.startswith("objects/spaceships/ships/"):
        return "ships"
    if l.startswith("objects/spaceships"):
        return "components"
    if l.startswith(("objects/props", "objects/persistent_universe", "objects/gameplay", "objects/salvage")):
        return "props"
    if l.startswith(("objects/buildingsets", "objects/planet", "objects/space", "objects/stations", "objects/landscape",
                     "objects/brush", "objects/organics", "objects/dfm", "objects/facility")):
        return "environments"
    return "other"


def pretty(path):
    parts = path.split("/")
    stem = parts[-1].rsplit(".", 1)[0]
    tokens = stem.split("_")
    manu = next((MANUFACTURERS[t.lower()] for t in tokens if t.lower() in MANUFACTURERS), None)
    if manu is None:
        manu = next((MANUFACTURERS[d.lower()] for d in parts[1:-1] if d.lower() in MANUFACTURERS), None)
    kind = next((t.lower() for t in tokens if t.lower() in WEAPON_TYPES), None)
    skip = {"fps", "s01", "s02", "s03", "s04", "s05"} | WEAPON_TYPES | set(MANUFACTURERS)
    words = [t for t in tokens if t.lower() not in skip] or tokens
    name = " ".join(w.upper() if len(w) <= 4 and any(c.isdigit() for c in w) else w.capitalize() for w in words)
    return name, manu or "", kind or ""


_DCB_PATTERN = re.compile(rb"@(item_Name[A-Za-z0-9_\-]+)\x00|([A-Za-z0-9_/\.\-]+\.(?:cdf|cga|cgf|skin))\x00")


def localization(archive, language="english"):
    """global.ini as {lowercase key: text}."""
    ini = next((n for n in archive.names if n.lower() == f"data\\localization\\{language}\\global.ini"), None)
    loc = {}
    if ini:
        for line in archive.read(ini).decode("utf-8-sig", "replace").splitlines():
            k, sep, v = line.partition("=")
            if sep:
                loc[k.split(",")[0].strip().lower()] = v.strip()
    return loc


def game_names(archive, language="english"):
    """Map geometry path (lowercase) -> in-game names, using the order of strings in DataCore.

    DataCore stores strings in first-use order, so an item's '@item_Name<class>' key is followed closely by the
    geometry it references. Not a full DataCore parse, but it names most weapons, armour, tools and vehicles."""
    dcb = next((n for n in archive.names if n.lower().endswith(".dcb")), None)
    loc = localization(archive, language)
    if not dcb or not loc:
        return {}
    data = archive.read(dcb)
    names, last_key, last_pos = {}, None, -10 ** 9
    for m in _DCB_PATTERN.finditer(data):
        if m.group(1):
            key = m.group(1).decode().lower()
            if not key.endswith(("_short", "_desc")) and key in loc:
                last_key, last_pos = key, m.start()
        elif last_key and m.start() - last_pos < 6000:
            path = m.group(2).decode().lower()
            label = loc[last_key]
            if label and not label.startswith("@") and label not in names.setdefault(path, []):
                names[path].append(label)
    return names


def build(archive, names=None):
    names = names or {}
    items = []
    ship_folders = defaultdict(list)
    for i, raw in enumerate(archive.names):
        low = raw.lower()
        if not low.endswith(GEOMETRY_EXT) or not low.startswith("data\\objects\\"):
            continue
        path = raw.replace("\\", "/")[5:]
        stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if re.search(r"_lod\d+$", stem, re.I):
            continue
        cat = categorize(path)
        name, manu, kind = pretty(path)
        ext = path.rsplit(".", 1)[-1].lower()
        main = not JUNK.search(stem) and ext != "chr"
        labels = names.get(path.lower(), []) if cat not in ("environments", "other") else []
        key = compact(path) + compact(manu) + compact(labels[0] if labels else name) + "".join(compact(x) for x in labels)
        it = Item(path, labels[0] if labels else name, manu, kind, cat, ext, int(archive.usize[i]), main, key)
        if labels:
            it.game_name, it.stem = True, stem
        if cat == "ships":
            segs = path.split("/")
            if len(segs) >= 5:
                ship_folders["/".join(segs[:5])].append(it)
            it.main = False
        items.append(it)
    # ships: the hull is the .cga named like the folder (AEGS/Gladius -> AEGS_Gladius.cga), else the largest .cga
    for folder, its in ship_folders.items():
        manu, ship = folder.split("/")[3:5]
        want = {f"{manu}_{ship}".lower(), ship.lower()}
        hull = [it for it in its if it.ext == "cga" and it.path.rsplit("/", 1)[-1][:-4].lower() in want]
        if not hull:
            cga = [it for it in its if it.ext == "cga" and it.path.count("/") == 4 and not JUNK.search(it.path)]
            hull = sorted(cga, key=lambda it: -it.size)[:1]
        for it in hull:
            it.main = True
            if not it.game_name:
                it.name = f"{ship.replace('_', ' ')}"
            it.manu, it.kind, it.stem = MANUFACTURERS.get(manu.lower(), manu), "hull", ""
    return items


def search(items, query="", category=None, main_only=True, limit=300):
    tokens = [compact(t) for t in query.split() if compact(t)]
    out = []
    for it in items:
        if category and it.category != category:
            continue
        if main_only and not it.main:
            continue
        if tokens and not all(t in it.key for t in tokens):
            continue
        out.append(it)
    # better matches first: name hits, main assets, shorter paths
    def rank(it):
        name_key = compact(it.name)
        return (0 if tokens and all(t in name_key for t in tokens) else 1, 0 if it.main else 1,
                CAT_ORDER.get(it.category, 99), 0 if it.game_name else 1, len(it.path))
    out.sort(key=rank)
    return out[:limit], len(out)
