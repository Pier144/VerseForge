"""Messages the server produces: status, categories, warnings, jobs.

Messages are kept as (key, {args}) tuples until they reach the interface, where t() / msg() turn them into text."""

MESSAGES = {
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
}

# category id -> label (ids and display order are in catalog.CATEGORIES)
CATEGORIES = {"weapons": "Weapons", "attachments": "Weapon attachments", "tools": "Tools and gadgets",
              "armor": "Armor", "clothing": "Clothing and backpacks", "ships": "Ships",
              "components": "Ship components", "vehicles": "Vehicles and exosuits",
              "characters": "Characters and creatures", "props": "Props",
              "environments": "Environments and structures", "other": "Other"}

# weapon type code found in file names -> readable name
WEAPON_TYPES = {"brfl": "rifle", "rfl": "rifle", "smg": "SMG", "lmg": "LMG", "sgun": "shotgun", "shtg": "shotgun",
                "snpr": "sniper rifle", "pstl": "pistol", "glau": "grenade launcher", "rlau": "rocket launcher",
                "melee": "melee weapon", "knif": "knife", "gdgt": "gadget", "optc": "optic", "mgzn": "magazine",
                "cmpn": "compensator", "brrl": "barrel", "undr": "underbarrel"}


def t(key, **kw):
    text = MESSAGES.get(key) or key
    return text.format(**kw) if kw else text


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
