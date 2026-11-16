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
import urllib.parse

from . import __version__
from .updates import REPO

ISSUE_PAGE = f"https://github.com/{REPO}/issues/"
NEW_ISSUE = f"https://github.com/{REPO}/issues/new"
PICTURE = "<!-- screenshot -->"          # replaced by the service with the uploaded picture
KINDS = {"bug": "[Bug] ", "idea": "[Idea] "}
ZWSP = "\u200b"                          # zero-width space: breaks @mentions and ``` fences without showing
MAX_URL = 7000                           # GitHub refuses longer "new issue" links


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


def _neutral(text):
    """User text that cannot break the issue layout or ping people: no <details> tags, no picture marker,
    no HTML comments, @mentions broken (once: an already broken mention is left as it is)."""
    text = (text or "").replace("\r\n", "\n").strip()
    text = re.sub(r"<(/?)details", r"&lt;\1details", text, flags=re.IGNORECASE)
    text = text.replace("<!--", "&lt;!--")
    return re.sub(r"@(?=[A-Za-z0-9])", "@" + ZWSP, text)


def compose(kind, title, description, details="", has_picture=False, version=__version__):
    """Title and Markdown body of the issue. The texts must already be anonymized."""
    title = KINDS.get(kind, KINDS["bug"]) + " ".join(_neutral(title).split())
    parts = [_neutral(description)]
    if has_picture:
        parts.append(PICTURE)
    if details:
        fenced = details.strip().replace("```", "`" + ZWSP + "``")
        parts.append(f"<details><summary>Technical details</summary>\n\n```text\n{fenced}\n```\n\n</details>")
    parts.append(f"<sub>Sent from VerseForge {version}</sub>")
    return {"title": title[:130], "body": "\n\n".join(parts)}


def fallback_url(composed):
    """GitHub's own "new issue" form, filled in (used when the service cannot be reached). No picture: the user
    can paste one there. Labels in the link are ignored by GitHub for people without rights on the repository."""
    body = composed["body"].replace(PICTURE, "_(please attach a screenshot here)_")

    def link(text):
        return NEW_ISSUE + "?" + urllib.parse.urlencode({"title": composed["title"], "body": text})

    note = "\n\n_(cut: the full text did not fit in the link)_"
    text, url = body, link(body)
    while len(url) > MAX_URL:
        text = text[: max(0, len(text) - max(100, (len(url) - MAX_URL) // 3))]
        url = link(text + note)
    return url
