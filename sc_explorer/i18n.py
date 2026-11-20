"""Texts of VerseForge, in English, and their translations.

English is the source and lives here (messages the server produces, categories, the texts the page's script builds)
and in web/index.html (the fixed texts of the page, each with a data-t key). A translation is one file,
web/locales/<code>.json, with the same sections as reference(); whatever it leaves out stays English.

Messages are kept as (key, {args}) tuples until they reach the interface, where t() / msg() turn them into text."""
import json
import os
import sys
from html.parser import HTMLParser

_RES = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEB_DIR = os.path.join(_RES, "web")
LOCALES_DIR = os.path.join(WEB_DIR, "locales")

# code -> (name in its own language, folder of the game's texts in Data.p4k: Data/Localization/<folder>/global.ini)
LANGUAGES = {
    "en": ("English", "english"),
    "it": ("Italiano", "italian_(italy)"),
    "fr": ("Français", "french_(france)"),
    "de": ("Deutsch", "german_(germany)"),
    "es": ("Español (España)", "spanish_(spain)"),
    "es-419": ("Español (Latinoamérica)", "spanish_(latin_america)"),
    "pt-BR": ("Português (Brasil)", "portuguese_(brazil)"),
    "ja": ("日本語", "japanese_(japan)"),
    "ko": ("한국어", "korean_(south_korea)"),
    "zh-Hans": ("简体中文", "chinese_(simplified)"),
    "zh-Hant": ("繁體中文", "chinese_(traditional)"),
}

MESSAGES = {
    "starting": "Starting…",
    "reading_index": "Reading the Data.p4k index…",
    "reading_names": "Reading game names (DataCore)…",
    "reading_paints": "Reading paints (DataCore)…",
    "building_catalog": "Building catalog…",
    "models_ready": "{n} models available",
    "error": "Error",
    "p4k_missing": "Data.p4k not found: {path}",
    "p4k_not_there": "Data.p4k is not there. Choose the folder where Star Citizen is installed, or the Data.p4k file "
                     "inside it (…\\StarCitizen\\LIVE).",
    "browse_game": "Select Data.p4k in your Star Citizen folder (…\\StarCitizen\\LIVE)",
    "browse_blender": "Select the Blender program",
    "browse_exports": "Choose the folder for the exports",
    "file_missing": "File not found: {path}",
    "no_geometry": "No geometry",
    "nothing_to_export": "No geometry to export",
    "no_decals": "This model has no markings to print at this scale",
    "no_decals_big": "The markings are larger than the page at this scale: try a smaller model",
    "blender_missing": "Blender not found: install it or set the path to the Blender program in the settings.",
    "queued": "Queued…",
    "done": "Completed",
    "unknown_job": "Unknown job",
    "file_not_ready": "File not ready",
    "print_solidify": "Solidifying in Blender (voxel {voxel} mm)…",
    "print_fill": "Filling the interior…",
    "print_fill_skipped": "Filling skipped: {error}",
    "print_write": "Writing STL…",
    "print_fill_too_big": "Filling skipped: the model is too large to fill at this resolution",
    "blender_no_output": "Blender did not produce the file: {log}",
    "warn_attachment_missing": "missing attachment: {path}",
    "warn_bone_missing": "bone not found: {bone}",
    "warn_part_error": "{path}: {error}",
    "warn_chr_skeleton": "The .chr file only contains the skeleton: open the .cdf or the linked .skin files.",
    "warn_no_geometry": "No geometry found in this file.",
    "warn_anim_error": "animation {clip} skipped: {error}",
    "warn_ports_missing": "{n} loadout item(s) not mounted: their port is not in the model",
    "warn_interior_missing": "{n} interior object(s) could not be loaded",
    "warn_interior_truncated": "Interior shown in part: it stops at {n} pieces",
    "update_source": "This version cannot install updates by itself: download the new one from the release page (from source, use git pull).",
    "update_no_installer": "This release has no installer to download.",
    "update_checksum": "The downloaded installer is damaged (size or checksum mismatch): try again.",
    "update_downloading": "Downloading the update…",
    "update_launching": "Installing: VerseForge will close and start again by itself.",
    "hull": "hull",
}

# category id -> label (ids and display order are in catalog.CATEGORIES)
CATEGORIES = {"weapons": "Weapons", "attachments": "Weapon attachments", "tools": "Tools and gadgets",
              "armor": "Armor", "clothing": "Clothing and backpacks", "ships": "Ships",
              "components": "Ship components", "vehicles": "Vehicles and exosuits",
              "characters": "Characters and creatures", "props": "Props",
              "environments": "Environments and structures", "other": "Other"}
# short labels for the category grid (the full label is its tooltip)
CATEGORIES_SHORT = {"weapons": "Weapons", "attachments": "Attachments", "tools": "Tools", "armor": "Armor",
                    "clothing": "Clothing", "ships": "Ships", "components": "Components", "vehicles": "Vehicles",
                    "characters": "Characters", "props": "Props", "environments": "Environments", "other": "Other"}

# category id -> {sub-category id -> label} (ids and display order are in catalog.SUBCATEGORIES; ships use manufacturers)
SUBCATEGORIES = {
    "weapons": {"pistols": "Pistols", "smgs": "SMGs", "rifles": "Rifles", "shotguns": "Shotguns",
                "snipers": "Sniper rifles", "lmgs": "LMGs and HMGs", "launchers": "Launchers",
                "special": "Special weapons", "melee": "Knives and melee",
                "grenades": "Grenades and deployables", "ammo": "Ammo", "mounted": "Turrets and mounted guns",
                "other": "Other"},
    "attachments": {"optics": "Optics and sights", "magazines": "Magazines", "muzzle": "Muzzle",
                    "underbarrel": "Underbarrel", "stocks": "Stocks", "charms": "Charms", "other": "Other"},
    "tools": {"multitool": "Multi-tools and modules", "medical": "Medical", "extinguishers": "Fire extinguishers",
              "gadgets": "Gadgets", "usables": "Usables and nav nodes"},
    "armor": {"helmets": "Helmets", "light": "Light armor", "medium": "Medium armor", "heavy": "Heavy armor",
              "undersuits": "Undersuits and flight suits", "other": "Other"},
    "clothing": {"tops": "Jackets and shirts", "bottoms": "Pants", "outfits": "Jumpsuits and uniforms",
                 "footwear": "Shoes and boots", "gloves": "Gloves", "headwear": "Hats, masks and glasses",
                 "backpacks": "Backpacks", "other": "Other"},
    "components": {"weapons": "Weapons", "turrets": "Turrets", "missiles": "Missiles, bombs and racks",
                   "thrusters": "Thrusters and intakes", "power": "Power plants", "coolers": "Coolers",
                   "shields": "Shields", "quantum": "Quantum drives", "systems": "Avionics and other systems",
                   "interior": "Seats and interior", "derelicts": "Derelicts and wrecks", "other": "Other"},
    "vehicles": {"ground": "Ground vehicles", "exosuits": "Exosuits", "derelicts": "Derelicts", "other": "Other"},
    "characters": {"heads": "Heads", "bodies": "Bodies", "creatures": "Creatures", "aliens": "Vanduul and Banu",
                   "other": "Other"},
    "props": {"branding": "Branding", "flair": "Flair and decorations", "missions": "Mission items and loot",
              "mining": "Mining", "salvage": "Salvage", "uee": "UEE", "other": "Other"},
    "environments": {"buildings": "Buildings", "hangars": "Hangars and garages", "flora": "Plants",
                     "caves": "Caves", "rocks": "Rocks and terrain", "space": "Space and stations",
                     "racetracks": "Race tracks and arenas", "other": "Other"},
}

# weapon type code found in file names -> readable name
WEAPON_TYPES = {"brfl": "rifle", "rfl": "rifle", "smg": "SMG", "lmg": "LMG", "sgun": "shotgun", "shtg": "shotgun",
                "snpr": "sniper rifle", "pstl": "pistol", "glau": "grenade launcher", "rlau": "rocket launcher",
                "melee": "melee weapon", "knif": "knife", "gdgt": "gadget", "optc": "optic", "mgzn": "magazine",
                "cmpn": "compensator", "brrl": "barrel", "undr": "underbarrel"}


# texts built by the page's script (web/app.js: T("key", {vars})); the fixed texts of the page are in web/index.html
UI = {
    "loading": "Loading…", "loadingOf": "Loading {name}…", "width": "Width", "length": "Length", "height": "Height",
    "triangles": "Triangles", "parts": "Parts", "materials": "Materials", "variant": "Variant / paint",
    "compareStock": "Compare with stock paint", "showingStock": "Showing stock paint · click to go back",
    "loadFailed": "Could not load the model: {error}", "exported": "Exported {name} (copy saved to {dir})",
    "exportsDir": "exports", "exportFailed": "Export failed: {error}", "print3d": "3D print: {error}",
    "loadPrepare": "Preparing the model on the server…", "loadDownload": "Downloading {done} / {total} MB",
    "loadDownloadNoSize": "Downloading {done} MB", "loadTextures": "Game textures {done} / {total}",
    "loadScene": "Building the scene…", "loadShaders": "Preparing shaders…",
    "printReady": "Ready: {size} mm, {volume} cm³, {closed}.", "closedYes": "watertight ✓",
    "closedNo": "not fully closed", "downloadStl": "Download STL", "printDone": "Printable STL of {name} ready",
    "results": "{n} results", "resultsOf": "{n} results · showing {shown}", "all": "All",
    "openSettings": "open Settings to fix the path",
    "browseFailed": "Could not open the file window: {error}",
    "decalSize": "The model is {size} long at this scale.", "decalWorking": "Drawing the markings…",
    "decalReady": "Ready: {pieces} decals on {pages} page(s) per sheet.",
    "decalSmall": "{n} too small to read at this scale were left out.",
    "decalBig": "{n} larger than the page were left out.",
    "rooms": "Rooms", "roomsN": "{n} rooms", "roomsAll": "Whole ship", "deckN": "Deck {n}",
    "deckTitle": "Deck {n}: remove everything above it",
    "serverDown": "Server not reachable…", "saved": "Settings saved",
    "kindDecal": "decal", "kindGlass": "glass", "kindProxy": "proxy", "kindScreen": "screen",
    "fullShip": "Full ship", "fullVehicle": "Full vehicle", "animReversed": "reversed",
    "resinLife": "Printed life size (1:1), {layer} mm layers.",
    "resinScaled": "Printed at 1:{scale} ({plate} mm long), {layer} mm layers.",
    "modeToLight": "Switch to light", "modeToDark": "Switch to dark",
    "updateTo": "Update to {version}", "updateText": "VerseForge {latest} is available. You have {current}.",
    "updateNoNotes": "No release notes.", "updateNow": "Update now", "updateOpenPage": "Open download page",
    "updateCheckFailed": "Could not check for updates: {error}", "githubUnreachable": "Could not reach GitHub: {error}",
    "upToDate": "VerseForge {version} is the latest version", "updateFailed": "Update failed: {error}",
    "versionLine": "You are using VerseForge {version}",
    "blenderAuto": "Detected automatically", "blenderPath": "Path to blender.exe or its folder",
    "blenderUsing": "Using {path}",
    "blenderNotThere": "Blender not found there: choose blender.exe or the folder that holds it",
    "blenderNotFound": "Blender not found: type where blender.exe is (the program or its folder)",
    "cacheUse": "Using {size} of {limit} · older files are removed beyond that", "cacheUseNoLimit": "Using {size}",
    "cacheCleared": "Cache cleared",
    "reportTitle": "Report a problem or suggest an idea",
    "repRate": "Too many reports from this connection, try again in a few minutes.",
    "repInvalid": "The report was not accepted.",
    "repUnavailable": "The report service is not available right now.",
    "repNetwork": "No connection to the report service.",
    "repLocal": "VerseForge could not prepare the report: {detail}",
    "repLocalNoDetail": "VerseForge could not prepare the report.",
    "repOpen": "Open", "repClosed": "Closed", "repRemoved": "Removed",
    "repCommentsOne": "{n} comment", "repCommentsMany": "{n} comments",
    "repNewSince": "{n} new since you last looked",
    "repNone": "No reports sent from this computer yet.",
    "repStatusUnavailable": "Status unavailable right now: GitHub limits how often it can be checked.",
    "repClickOpen": "Click a report to open it on GitHub.",
    "repNewsOne": "{n} new notification on your reports", "repNewsMany": "{n} new notifications on your reports",
    "repSend": "Send", "repSending": "Sending…", "repSent": "Report #{n} sent, thank you",
    "repSentUnsaved": "Report #{n} sent, but VerseForge could not save its settings: it will be missing from My reports after a restart",
}

_lang = "en"
_names = "follow"           # the game's names: "follow" the interface language, or "en" (always English)
_tables = {}                # language code -> its file's content
_html = None                # English texts of web/index.html, by key


def language():
    return _lang


def set_language(code):
    """Language of everything t() and the label functions return from now on; unknown codes mean English."""
    global _lang
    _lang = code if code in LANGUAGES else "en"
    return _lang


def set_names(mode):
    """The game's names (ships, items, paints, rooms): "follow" the interface language, or "en" for English
    whatever the interface speaks."""
    global _names
    _names = "en" if mode == "en" else "follow"
    return _names


def names():
    return _names


def game_language(code=None):
    """Folder of the game's own texts for a language (the names of ships, items, paints and rooms)."""
    if code is None and _names == "en":
        return LANGUAGES["en"][1]
    return LANGUAGES.get(code or _lang, LANGUAGES["en"])[1]


def _table(code=None):
    code = code or _lang
    if code == "en":
        return {}
    if code not in _tables:
        try:
            with open(os.path.join(LOCALES_DIR, f"{code}.json"), encoding="utf-8") as f:
                _tables[code] = json.load(f)
        except (OSError, ValueError):
            _tables[code] = {}
    return _tables[code]


def _section(name):
    sec = _table().get(name)
    return sec if isinstance(sec, dict) else {}


class _PageTexts(HTMLParser):
    """Texts of the page that carry a key: data-t (the element's text), data-t-title, data-t-ph (placeholder),
    data-t-aria (aria-label)."""
    ATTRS = {"data-t-title": "title", "data-t-ph": "placeholder", "data-t-aria": "aria-label"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.open = {}, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.open = None
        for key_attr, attr in self.ATTRS.items():
            if a.get(key_attr):
                self.out[a[key_attr]] = a.get(attr) or ""
        if a.get("data-t"):
            self.open = a["data-t"]
            self.out[self.open] = ""

    def handle_data(self, data):
        if self.open:
            self.out[self.open] += data

    def handle_endtag(self, tag):
        self.open = None


def page_texts():
    """{key: English text} of the fixed texts in web/index.html."""
    global _html
    if _html is None:
        try:
            parser = _PageTexts()
            with open(os.path.join(WEB_DIR, "index.html"), encoding="utf-8") as f:
                parser.feed(f.read())
            _html = {k: " ".join(v.split()) for k, v in parser.out.items()}
        except OSError:
            _html = {}
    return _html


def reference():
    """Everything a translation can hold, in English: the content of web/locales/en.json, the file to copy for a
    new language."""
    return {"messages": dict(MESSAGES), "categories": dict(CATEGORIES), "categories_short": dict(CATEGORIES_SHORT),
            "subcategories": {c: dict(s) for c, s in SUBCATEGORIES.items()}, "weapon_types": dict(WEAPON_TYPES),
            "ui": {**page_texts(), **UI}}


def page_strings():
    """What the page needs: the language, the choices, and every text of the page and its script."""
    return {"lang": _lang, "languages": [{"code": c, "name": n} for c, (n, _) in LANGUAGES.items()],
            "strings": {**page_texts(), **UI, **{k: v for k, v in _section("ui").items() if v}}}


def category(cat):
    return _section("categories").get(cat) or CATEGORIES.get(cat, cat)


def category_short(cat):
    return _section("categories_short").get(cat) or CATEGORIES_SHORT.get(cat, cat)


def subcategory(cat, sub):
    sec = _section("subcategories").get(cat)
    return (sec.get(sub) if isinstance(sec, dict) else None) or SUBCATEGORIES.get(cat, {}).get(sub, sub)


def weapon_type(code):
    return _section("weapon_types").get(code) or WEAPON_TYPES.get(code, "")


def t(key, **kw):
    text = _section("messages").get(key) or MESSAGES.get(key) or key
    if not kw:
        return text
    try:
        return text.format(**kw)
    except (KeyError, IndexError, ValueError):      # a translation with a wrong placeholder: the English text
        return (MESSAGES.get(key) or key).format(**kw)


def msg(m):
    """Text of a message kept as (key, kwargs) or a plain string (e.g. an exception text)."""
    if isinstance(m, (tuple, list)):
        return t(m[0], **(m[1] if len(m) > 1 else {}))
    return m


class LocalizedError(Exception):
    """An error raised with a message key, so the interface gets the same text as the other messages."""

    def __init__(self, key, **kw):
        super().__init__(t(key, **kw))
        self.key, self.kw = key, kw

    def text(self):
        return t(self.key, **self.kw)


def error_text(e):
    return e.text() if isinstance(e, LocalizedError) else str(e)


def fmt_int(n):
    return f"{n:,}"
