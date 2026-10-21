"""Interface language (English / Italian) for the messages the server produces: status, categories, warnings, jobs.

The web interface has its own table in web/app.js; the language is shared through config.json ("ui_lang")."""
import locale

LANGS = ("en", "it")

MESSAGES = {
    "en": {
        "starting": "Starting…",
        "reading_index": "Reading the Data.p4k index…",
        "reading_names": "Reading game names (DataCore)…",
        "reading_paints": "Reading paints (DataCore)…",
        "building_catalog": "Building catalog…",
        "models_ready": "{n} models available",
        "error": "Error",
        "p4k_missing": "Data.p4k not found: {path}",
        "file_missing": "File not found: {path}",
        "no_geometry": "No geometry",
        "nothing_to_export": "No geometry to export",
        "blender_missing": "Blender not found: install it or set the path to blender.exe in the settings.",
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
        "hull": "hull",
        "suffix_raw": "raw_mm",
        "suffix_print": "print3d_mm",
    },
    "it": {
        "starting": "Avvio…",
        "reading_index": "Lettura indice di Data.p4k…",
        "reading_names": "Lettura dei nomi del gioco (DataCore)…",
        "reading_paints": "Lettura delle verniciature (DataCore)…",
        "building_catalog": "Costruzione catalogo…",
        "models_ready": "{n} modelli disponibili",
        "error": "Errore",
        "p4k_missing": "Data.p4k non trovato: {path}",
        "file_missing": "File non trovato: {path}",
        "no_geometry": "Nessuna geometria",
        "nothing_to_export": "Nessuna geometria da esportare",
        "blender_missing": "Blender non trovato: installalo o indica il percorso di blender.exe nelle impostazioni.",
        "queued": "In coda…",
        "done": "Completato",
        "unknown_job": "Lavoro sconosciuto",
        "file_not_ready": "File non pronto",
        "print_solidify": "Solidificazione in Blender (voxel {voxel} mm)…",
        "print_fill": "Riempimento dell'interno…",
        "print_fill_skipped": "Riempimento saltato: {error}",
        "print_write": "Scrittura STL…",
        "print_fill_too_big": "Riempimento saltato: modello troppo grande per il riempimento a questa risoluzione",
        "blender_no_output": "Blender non ha prodotto il file: {log}",
        "warn_attachment_missing": "attacco mancante: {path}",
        "warn_bone_missing": "osso non trovato: {bone}",
        "warn_part_error": "{path}: {error}",
        "warn_chr_skeleton": "Il file .chr contiene solo lo scheletro: apri il .cdf o i .skin collegati.",
        "warn_no_geometry": "Nessuna geometria trovata in questo file.",
        "hull": "scafo",
        "suffix_raw": "grezzo_mm",
        "suffix_print": "stampa3d_mm",
    },
}

CATEGORIES = {
    "en": {"armi": "Weapons", "accessori": "Weapon attachments", "strumenti": "Tools and gadgets", "armature": "Armor",
           "abiti": "Clothing and backpacks", "navi": "Ships", "componenti": "Ship components",
           "veicoli": "Vehicles and exosuits", "personaggi": "Characters and creatures", "oggetti": "Props",
           "ambienti": "Environments and structures", "altro": "Other"},
    "it": {"armi": "Armi", "accessori": "Accessori armi", "strumenti": "Strumenti e gadget", "armature": "Armature",
           "abiti": "Abiti e zaini", "navi": "Navi", "componenti": "Componenti navi",
           "veicoli": "Veicoli ed esoscheletri", "personaggi": "Personaggi e creature", "oggetti": "Oggetti",
           "ambienti": "Ambienti e strutture", "altro": "Altro"},
}

WEAPON_TYPES = {
    "en": {"brfl": "rifle", "rfl": "rifle", "smg": "SMG", "lmg": "LMG", "sgun": "shotgun", "shtg": "shotgun",
           "snpr": "sniper rifle", "pstl": "pistol", "glau": "grenade launcher", "rlau": "rocket launcher",
           "melee": "melee weapon", "knif": "knife", "gdgt": "gadget", "optc": "optic", "mgzn": "magazine",
           "cmpn": "compensator", "brrl": "barrel", "undr": "underbarrel"},
    "it": {"brfl": "fucile", "rfl": "fucile", "smg": "mitraglietta", "lmg": "mitragliatrice", "sgun": "fucile a pompa",
           "shtg": "fucile a pompa", "snpr": "fucile di precisione", "pstl": "pistola", "glau": "lanciagranate",
           "rlau": "lanciarazzi", "melee": "arma bianca", "knif": "coltello", "gdgt": "gadget", "optc": "ottica",
           "mgzn": "caricatore", "cmpn": "compensatore", "brrl": "canna", "undr": "sottocanna"},
}


def system_lang():
    """Italian on an Italian Windows, English everywhere else."""
    try:
        name = locale.getlocale()[0] or ""
    except ValueError:
        name = ""
    return "it" if name.lower().startswith(("it", "italian")) else "en"


def norm(lang):
    return lang if lang in LANGS else "en"


def t(lang, key, **kw):
    text = MESSAGES[norm(lang)].get(key) or MESSAGES["en"].get(key) or key
    return text.format(**kw) if kw else text


def msg(m, lang):
    """Translate a message kept as (key, kwargs) or a plain string (e.g. an exception text)."""
    if isinstance(m, (tuple, list)):
        return t(lang, m[0], **(m[1] if len(m) > 1 else {}))
    return m


class LocalizedError(Exception):
    """An error whose text is translated when it reaches the interface."""

    def __init__(self, key, **kw):
        super().__init__(t("en", key, **kw))
        self.key, self.kw = key, kw

    def text(self, lang):
        return t(lang, self.key, **self.kw)


def error_text(e, lang):
    return e.text(lang) if isinstance(e, LocalizedError) else str(e)


def fmt_int(n, lang):
    return f"{n:,}".replace(",", "." if norm(lang) == "it" else ",")
