"""Reports sent from VerseForge: they become public issues on GitHub through the VerseForge Reports service
(reports-service/ in this repository, hosted on Vercel).

The issue text is built here only (compose): the preview in the app, the real report and the fallback link to
GitHub's own form all use it, so what the user sees is what is sent. Personal data (home folder, user and PC name,
game, export and Blender folders) is removed before that (anonymize)."""

import getpass
import ntpath
import os
import platform
import posixpath
import re


def _dirname(path):
    """Folder of a path written with either kind of slash (Windows paths are also handled on Linux)."""
    return (ntpath if "\\" in path else posixpath).dirname(path)


def local_identity():
    """Home folder, user name and PC name of this computer: what anonymize() removes."""
    try:
        user = getpass.getuser()
    except Exception:  # no user name in the environment (rare, e.g. some service accounts)
        user = ""
    return {"home": os.path.expanduser("~"), "user": user, "machine": platform.node()}


def user_folders(cfg, blender=None):
    """Folders from the settings that may hold personal names, with the tag that replaces them."""
    out = []
    p4k = cfg.get("p4k_path") or ""
    if p4k:
        out.append((_dirname(_dirname(p4k)), "<game>"))            # ...\StarCitizen, above LIVE / PTU
    if cfg.get("export_dir"):
        out.append((cfg["export_dir"], "<exports>"))
    folder = _dirname(blender or "")
    if "blender" in folder.lower():                                 # not /usr/bin and the like
        out.append((folder, "<blender>"))
    return out


def _folder_pattern(folder):
    """A folder as a regex that accepts \\ and / as separators and does not match a longer folder name."""
    tokens = re.split(r"([\\/]+)", folder)
    body = "".join(r"[\\/]+" if re.fullmatch(r"[\\/]+", t) else re.escape(t) for t in tokens if t)
    return re.compile(body + r"(?![A-Za-z0-9_.-])", re.IGNORECASE)


def _word_pattern(word):
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])", re.IGNORECASE)


def anonymize(text, *, home="", user="", machine="", folders=()):
    """Remove personal data from a text: folders first (longest first, so the game folder inside the home folder
    keeps its own tag), then the PC name, then the user name. Names shorter than 3 letters are left alone."""
    if not text:
        return ""
    pairs = [(f.rstrip("\\/"), tag) for f, tag in [*folders, (home, "<home>")] if f]
    for folder, tag in sorted(pairs, key=lambda p: -len(p[0])):
        if len(folder) >= 3:
            text = _folder_pattern(folder).sub(tag, text)
    for word, tag in ((machine, "<pc>"), (user, "<user>")):
        if word and len(word) >= 3:
            text = _word_pattern(word).sub(tag, text)
    return text
