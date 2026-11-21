"""Searchable catalogue of the geometry assets inside Data.p4k."""
import re
from collections import defaultdict
from dataclasses import dataclass

from . import i18n

GEOMETRY_EXT = (".cgf", ".cga", ".skin", ".cdf", ".chr")

# category ids in display order (ships and vehicles, personal gear, the rest); labels in i18n.CATEGORIES
CATEGORIES = ["ships", "components", "vehicles", "weapons", "attachments", "armor", "clothing", "tools", "characters",
              "props", "environments", "other"]

CAT_ORDER = {k: i for i, k in enumerate(CATEGORIES)}

# sub-category ids of each category in display order; labels in i18n.SUBCATEGORIES.
# Ships are split by manufacturer instead: their ids are the manufacturer folders (aegs, drak…)
SUBCATEGORIES = {
    "weapons": ["pistols", "smgs", "rifles", "shotguns", "snipers", "lmgs", "launchers", "special", "melee", "grenades",
                "ammo", "mounted", "other"],
    "attachments": ["optics", "magazines", "muzzle", "underbarrel", "stocks", "charms", "other"],
    "tools": ["multitool", "medical", "extinguishers", "gadgets", "usables"],
    "armor": ["helmets", "light", "medium", "heavy", "undersuits", "other"],
    "clothing": ["tops", "bottoms", "outfits", "footwear", "gloves", "headwear", "backpacks", "other"],
    "components": ["weapons", "turrets", "missiles", "thrusters", "power", "coolers", "shields", "quantum", "systems",
                   "interior", "derelicts", "other"],
    "vehicles": ["ground", "exosuits", "derelicts", "other"],
    "characters": ["heads", "bodies", "creatures", "aliens", "other"],
    "props": ["branding", "flair", "missions", "mining", "salvage", "uee", "other"],
    "environments": ["buildings", "hangars", "flora", "caves", "rocks", "space", "racetracks", "other"],
}

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

# manufacturer code -> first code with the same name (ships are grouped by name)
_MANU_IDS = {code: next(c for c, m in MANUFACTURERS.items() if m == manu) for code, manu in MANUFACTURERS.items()}

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
    sub: str = ""      # sub-category id (see SUBCATEGORIES)
    whole: bool = False  # a ship or vehicle of the game (it has a vehicle definition), not one of its pieces


def subtitle(it):
    """Shown beside the name: the maker and, for weapons, the kind. A ship is not called a "hull" there, and the file
    name is left to the tooltip and to the list of every file."""
    return " · ".join(x for x in (it.manu, i18n.weapon_type(it.kind) if it.kind != "hull" else "") if x)


def compact(s):
    """Search key of a text: lowercase letters and digits of any script (names can be Japanese, Korean, Chinese)."""
    return re.sub(r"[\W_]+", "", s.lower())


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


# weapons_v7/<manufacturer>/<type folder>/…, else the type code that starts the file name (bpst, esmg, lrfl…)
_WEAPON_DIRS = {"pistol": "pistols", "toy_pistol": "pistols", "smg": "smgs", "rifle": "rifles", "shotgun": "shotguns",
                "sniper": "snipers", "lmg": "lmgs", "hmg": "lmgs", "launcher": "launchers", "special": "special",
                "crossbow": "special"}
_WEAPON_CODES = {"pst": "pistols", "smg": "smgs", "rfl": "rifles", "sgn": "shotguns", "snp": "snipers", "lmg": "lmgs",
                 "msl": "launchers", "spc": "special", "crb": "special"}
_ATTACHMENT_DIRS = {"sights_scopes": "optics", "ironsights": "optics", "sights_projected": "optics",
                    "magazines": "magazines", "canisters": "magazines", "compensators": "muzzle",
                    "suppressors": "muzzle", "energy_silencers": "muzzle", "flashhiders": "muzzle",
                    "energy_stabilizer": "muzzle", "flashlights": "underbarrel", "laserpointers": "underbarrel",
                    "grips": "underbarrel", "stocks": "stocks", "charms": "charms"}
_COMPONENT_DIRS = {"weapons": "weapons", "weapons_bespoke": "weapons", "weapon_mounts": "weapons",
                   "rocket_pods": "weapons", "turrets": "turrets", "missile_racks": "missiles", "bomb_racks": "missiles",
                   "torpedo_racks": "missiles", "ammo": "missiles", "emp_pods": "missiles", "thrusters": "thrusters",
                   "intakes": "thrusters", "blades": "thrusters", "power_plants": "power", "coolers": "coolers",
                   "shields": "shields", "quantum_drives": "quantum", "avionics": "systems", "radar": "systems",
                   "relay": "systems", "fuel_tanks": "systems", "life_support": "systems", "batteries": "systems",
                   "jump_modules": "systems", "components": "systems", "utilities": "systems", "seats": "interior",
                   "seataccess": "interior", "screens": "interior", "doors": "interior", "switches": "interior",
                   "lighting": "interior", "usables": "interior", "escape_pods": "interior", "cargo": "interior",
                   "derelicts": "derelicts"}
_CLOTHING_WORDS = [("headwear", {"hat", "cap", "helmet", "mask", "glasses", "goggles", "beanie", "bandana", "hood",
                                 "headphones", "headset", "beret"}),
                   ("footwear", {"shoes", "boots", "sneakers", "sandals", "slippers", "heels"}),
                   ("gloves", {"gloves", "glove"}),
                   ("bottoms", {"pants", "shorts", "skirt", "trousers", "leggings"}),
                   ("tops", {"jacket", "shirt", "tshirt", "vest", "coat", "sweater", "hoodie", "top", "blouse",
                             "tanktop", "sweatshirt", "poncho", "shirts", "longsleeve", "trenchcoat"}),
                   ("outfits", {"jumpsuit", "uniform", "suit", "dress", "gown", "apron", "coveralls", "robe",
                                "flightsuit", "bodysuit", "outfit", "scrubs"})]


def subcategorize(p, cat, name=""):
    """Sub-category id of a geometry path, from its folders, the words in its file name and its in-game name."""
    l = p.lower()
    segs = l.split("/")
    dirs, stem = segs[1:-1], segs[-1].rsplit(".", 1)[0]
    words = set(re.split(r"[_\-]+", stem))
    if cat == "weapons":
        if l.startswith("objects/weapon/"):
            return "mounted"
        if l.startswith("objects/fps_weapons/ammo"):
            return "ammo"
        if l.startswith(("objects/fps_weapons/grenades", "objects/fps_weapons/deployables")):
            return "grenades"
        if any(d.startswith(("knife", "melee")) or d == "fsk8" for d in dirs) or words & {"knife", "combatknife"}:
            return "melee"
        typ = next((_WEAPON_DIRS[d] for d in dirs[3:] if d in _WEAPON_DIRS), None)
        m = re.match(r"([a-z]?)(pst|smg|rfl|sgn|snp|lmg|msl|spc|crb)_", stem)
        if m and m.groups() == ("m", "spc"):
            return "melee"            # mspc_…: melee "special" items
        return typ or (_WEAPON_CODES[m.group(2)] if m else "other")
    if cat == "attachments":
        return _ATTACHMENT_DIRS.get(segs[3] if len(segs) > 4 else "", "other")
    if cat == "tools":
        if l.startswith("objects/usables"):
            return "usables"
        if any(k in l for k in ("multitool", "/salvage", "/tractor", "/mining")):
            return "multitool"
        if "/crlf" in l or "medical" in l:
            return "medical"
        return "extinguishers" if "extinguisher" in l else "gadgets"
    if cat == "armor":
        if "helmet" in l or "visor" in words or "helmet" in name.lower():
            return "helmets"
        if words & {"heavy", "superheavy", "heavyarmor"}:
            return "heavy"
        if words & {"medium", "med", "mediumarmor"}:
            return "medium"
        if words & {"light", "lightarmor"}:
            return "light"
        if words & {"undersuit", "flightsuit", "suit", "necksock"} or "flightsuit" in l:
            return "undersuits"
        return "other"
    if cat == "clothing":
        if "backpack" in l:
            return "backpacks"
        return next((sub for sub, keys in _CLOTHING_WORDS if words & keys), "other")
    if cat == "ships":
        # one id per manufacturer name (xian and xnaa are both Aopoa)
        return _MANU_IDS.get(segs[3], segs[3]) if len(segs) > 4 else "other"
    if cat == "components":
        return _COMPONENT_DIRS.get(segs[2] if len(segs) > 3 else "", "other")
    if cat == "vehicles":
        if l.startswith("objects/characters/powersuit"):
            return "exosuits"
        if l.startswith("objects/vehicles/derelicts"):
            return "derelicts"
        if len(segs) > 3 and segs[2] in ("seats", "turrets", "weapons", "repair"):
            return "other"
        return "ground"
    if cat == "characters":
        if "/heads/" in l:
            return "heads"
        if l.startswith("objects/characters/creatures"):
            return "creatures"
        if l.startswith(("objects/characters/vanduul", "objects/characters/banu")):
            return "aliens"
        return "bodies" if l.startswith("objects/characters/human") else "other"
    if cat == "props":
        top = "/".join(segs[1:3])
        if top in ("props/branding", "props/flair"):
            return segs[2]
        if top in ("props/mission", "props/reward", "props/loot"):
            return "missions"
        if top == "gameplay/mining":
            return "mining"
        if segs[1] == "salvage":
            return "salvage"
        return "uee" if segs[1] == "persistent_universe" else "other"
    if cat == "environments":
        top = segs[1]
        if top == "buildingsets" or top == "facility":
            return "hangars" if len(segs) > 3 and segs[2] in ("hangar", "garage") else "buildings"
        if top == "dfm":
            return "racetracks"
        if top in ("space", "spacescape", "stations") or "/asteroids" in l:
            return "space"
        if "/flora" in l or "/botanical" in l:
            return "flora"
        if "/cave" in l:
            return "caves"
        if top in ("planet", "planets", "landscape", "brush", "organics"):
            return "rocks" if any(k in l for k in ("geology", "/rock", "terrain", "brush/", "/ice")) else "other"
        return "other"
    return ""


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


def _global_ini(archive, language):
    ini = next((n for n in archive.names if n.lower() == f"data\\localization\\{language}\\global.ini"), None)
    loc = {}
    if ini:
        for line in archive.read(ini).decode("utf-8-sig", "replace").splitlines():
            k, sep, v = line.partition("=")
            # texts the game has not translated yet hold a note instead ("! ITALIAN_(ITALY) TRANSLATION NOT FOUND
            # FOR LOCID: ... !"): left out, so the English text is used
            if sep and "TRANSLATION NOT FOUND" not in v:
                loc[k.split(",")[0].strip().lower()] = v.strip()
    return loc


def localization(archive, language="english"):
    """global.ini as {lowercase key: text}. Another language is laid over the English texts, so what the game has
    not translated stays English."""
    loc = _global_ini(archive, "english")
    if language != "english":
        loc.update({k: v for k, v in _global_ini(archive, language).items() if v})
    return loc


_NO_NAME = re.compile(r"placeholder|test string|^unknown$|^<|^\s*$", re.I)


def _exact_names(guessed, index, label):
    """The names the game's entities give their geometry replace the guessed ones (see game_names).
    index: entities.build()'s answer; label(key) -> text or None.
    - a ship or vehicle is called by its vehicle name ("Aegis Redeemer"), first;
    - geometry whose entities have a name takes those names, the entity named like the file first;
    - geometry whose entities have no name loses its guess (a seat access is not a "Camo Livery"): the catalogue
      then shows the file name. The same for the pieces of ships and vehicles whose name is one word ("Access",
      "Seat") or has nothing of the file name in it ("TRGT. STATUS" for every seat): the file name says more."""
    vehicles = index.get("vehicles", {})
    names = index.get("names", {})
    for path in {**names, **vehicles}:
        keys = names.get(path, [])
        labels = []
        veh = (vehicles.get(path) or {}).get("name")
        for k in ([veh] if veh else []) + list(keys):
            text = (label(k) or "").replace("\\n", " ").strip()
            if text and not text.startswith("@") and not _NO_NAME.search(text) and text not in labels:
                labels.append(text)
        if labels and not veh and categorize(path) in ("ships", "vehicles"):
            # pieces of a ship: seats, doors and dashboards are all called "TRGT. STATUS" or "Door Control"
            stem = compact(path.rsplit("/", 1)[-1].rsplit(".", 1)[0])
            words = [compact(w) for w in labels[0].split()]
            if len(words) < 2 or not any(len(w) >= 3 and w in stem for w in words):
                labels = []
        if labels:
            guessed[path] = labels
        else:
            guessed.pop(path, None)
    return guessed


def game_names(archive, language="english", index=None):
    """Map geometry path (lowercase) -> in-game names.

    With index (entities.build()'s answer) the names are the ones the game's entities give their geometry. What no
    entity uses directly (armour and clothing pieces, mostly) is named from the order of strings in DataCore:
    DataCore stores strings in first-use order, so an item's '@item_Name<class>' key is followed closely by the
    geometry it references. Not a full DataCore parse, but it names most weapons, armour, tools and vehicles.
    For another language the answer is {"names": {path: [names]}, "english": {path: [English names]}}: the catalogue
    shows the first and still finds (and sorts into sub-categories) by the second."""
    dcb = next((n for n in archive.names if n.lower().endswith(".dcb")), None)
    english = _global_ini(archive, "english")
    if not dcb or not english:
        return {}
    data = archive.read(dcb)
    keys, last_key, last_pos = {}, None, -10 ** 9
    for m in _DCB_PATTERN.finditer(data):
        if m.group(1):
            key = m.group(1).decode().lower()
            if not key.endswith(("_short", "_desc")) and key in english:
                last_key, last_pos = key, m.start()
        elif last_key and m.start() - last_pos < 6000:
            path = m.group(2).decode().lower()
            if last_key not in keys.setdefault(path, []):
                keys[path].append(last_key)

    def named(loc):
        out = {}
        for path, ks in keys.items():
            labels = []
            for k in ks:
                label = loc.get(k) or english[k]
                if label and not label.startswith("@") and label not in labels:
                    labels.append(label)
            out[path] = labels
        if index:
            _exact_names(out, index, lambda k: loc.get(k) or english.get(k))
        return out

    if language == "english":
        return named(english)
    return {"names": named(_global_ini(archive, language)), "english": named(english)}


# first word of every manufacturer's name, and the short forms the game writes in front of a vehicle name
_MAKER_WORDS = {m.split()[0].lower() for m in MANUFACTURERS.values()} | {"rsi", "c.o.", "grey's"} - {"nova"}


def _drop_maker(label, code, manu):
    """"Drake Cutlass Black" -> "Cutlass Black": the manufacturer is shown beside the name."""
    words = label.split()
    if len(words) > 1 and words[0].lower() in {code.lower(), manu.split()[0].lower() if manu else ""} | _MAKER_WORDS:
        words = words[1:]
    return " ".join(words)


def build(archive, names=None, vehicles=()):
    """vehicles: geometry paths (lower case) that have a vehicle definition in the game: the ships and ground
    vehicles themselves, shown first and as main models whatever their file is called. A dict gives each one a
    weight (how many of the game's vehicles use it, the size of its loadout) that picks between two files of the
    same name."""
    names = names or {}
    english = names.get("english") if isinstance(names.get("english"), dict) else None
    if english is not None:
        names = names.get("names") or {}
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
        named = cat not in ("environments", "other")
        labels = names.get(path.lower(), []) if named else []
        # another language: the English names still find the model, and sort it into its sub-category
        en = english.get(path.lower(), []) if english is not None and named else labels
        key = compact(path) + compact(manu) + compact(labels[0] if labels else name) + \
            "".join(compact(x) for x in labels + [x for x in en if x not in labels])
        it = Item(path, labels[0] if labels else name, manu, kind, cat, ext, int(archive.usize[i]), main, key,
                  sub=subcategorize(path, cat, en[0] if en else ""))
        if labels:
            it.game_name, it.stem = True, stem
        if cat == "ships":
            segs = path.split("/")
            if len(segs) >= 5:
                ship_folders["/".join(segs[:5])].append(it)
            it.main = False
        if cat in ("ships", "vehicles") and path.lower() in vehicles:
            segs = path.split("/")
            code = segs[3] if cat == "ships" and len(segs) >= 5 else ""
            it.whole = it.main = True
            it.stem = ""
            if code:
                it.manu, it.kind = MANUFACTURERS.get(code.lower(), it.manu or code), "hull"
            if labels:
                it.name = _drop_maker(labels[0], code, it.manu)
        items.append(it)
    # ships without a vehicle definition (not flyable any more, or never): the hull is the .cga named like the
    # folder (AEGS/Gladius -> AEGS_Gladius.cga), else the largest .cga
    # two files of the same ship (Constellation Phoenix: the old hull and the reworked one): the one with the
    # bigger loadout stays, the other goes back among the pieces
    flown = {folder for folder, its in ship_folders.items() if any(it.whole for it in its)}
    # ground vehicles: like the ships, the list shows the vehicle, not its doors, racks and wheels (the Ground list
    # held 444 files for 20 vehicles, forty of them under names such as "Door Control" or "Personal Storage"). The
    # pieces stay one switch away (Main models off). Folders without a vehicle of the game keep all their files
    driven = {"/".join(it.path.lower().split("/")[:4]) for it in items if it.whole and it.category == "vehicles"}
    for it in items:
        if it.category == "vehicles" and not it.whole and "/".join(it.path.lower().split("/")[:4]) in driven:
            it.main = False
    best = {}
    for it in items:
        if it.whole:
            k = (it.category, it.name.lower())
            weight = (vehicles.get(it.path.lower(), 0) if isinstance(vehicles, dict) else 0, it.size)   # see build()
            if k not in best or weight > best[k][0]:
                best[k] = (weight, it)
    for it in items:
        if it.whole and best[it.category, it.name.lower()][1] is not it:
            it.whole = it.main = False
    for folder, its in ship_folders.items():
        if folder in flown:
            continue
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


def name_hulls(items, stock_label, flyable):
    """Ship hulls named after their folder ("hammerhead gs", "railen", "890Jump") take the name of their stock paint
    in game ("Aegis Hammerhead" -> "Hammerhead"), the manufacturer left out. Then a hull the game no longer flies (no
    vehicle definition) gives way to a flyable one of the same name: "Hammerhead" opened the old AEGS_Hammerhead.cga,
    grey, with no landing gear and no loadout, while the ship of the game is hammerhead_gs.
    stock_label(path) -> the stock paint's label or None; flyable(path) -> bool."""
    hulls = [it for it in items if it.kind == "hull" and it.main]
    for it in hulls:
        label = (stock_label(it.path) or "").strip()
        if it.game_name or not label:
            continue
        code = it.path.split("/")[3] if it.path.count("/") >= 4 else ""
        it.name = _drop_maker(label, code, it.manu)
        it.key += compact(it.name)
    fly = {it.name.lower() for it in hulls if flyable(it.path)}
    for it in hulls:
        if it.name.lower() in fly and not flyable(it.path):
            it.main = False


def subcategory_label(cat, sub):
    if cat == "ships":
        return MANUFACTURERS.get(sub, sub.upper())
    return i18n.subcategory(cat, sub)


def subcategories(items):
    """{category: [(id, label, main models)]} in display order; empty sub-categories are left out."""
    total, main = defaultdict(int), defaultdict(int)
    for it in items:
        total[it.category, it.sub] += 1
        main[it.category, it.sub] += it.main
    out = {}
    for cat in CATEGORIES:
        if cat == "ships":
            subs = {s for c, s in total if c == cat and s != "other"}
            order = sorted(subs, key=lambda s: subcategory_label(cat, s).lower()) + ["other"]
        else:
            order = SUBCATEGORIES.get(cat, [])
        out[cat] = [(s, subcategory_label(cat, s), main[cat, s]) for s in order if total.get((cat, s))]
    return out


def search(items, query="", category=None, main_only=True, limit=300, sub=None, offset=0):
    tokens = [compact(t) for t in query.split() if compact(t)]
    out = []
    for it in items:
        if category and it.category != category:
            continue
        if sub and it.sub != sub:
            continue
        if main_only and not it.main:
            continue
        if tokens and not all(t in it.key for t in tokens):
            continue
        out.append(it)
    # better matches first: name hits, main assets, whole ships and vehicles (by name), shorter paths
    def rank(it):
        name_key = compact(it.name)
        return (0 if tokens and all(t in name_key for t in tokens) else 1, 0 if it.main else 1, 0 if it.whole else 1,
                CAT_ORDER.get(it.category, 99), it.name.lower() if it.whole else "", 0 if it.game_name else 1,
                len(it.path))
    out.sort(key=rank)
    return out[offset:offset + limit], len(out)
