"""Reports sent from VerseForge: they become public issues on GitHub through the VerseForge Reports service
(reports-service/ in this repository, hosted on Vercel).

The issue text is built here only (compose): the preview in the app, the real report and the fallback link to
GitHub's own form all use it, so what the user sees is what is sent. Personal data (home folder, user and PC name,
game, export and Blender folders) is removed before that (anonymize)."""

import getpass
import json
import ntpath
import os
import platform
import posixpath
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__
from .updates import REPO

ISSUE_PAGE = f"https://github.com/{REPO}/issues/"
NEW_ISSUE = f"https://github.com/{REPO}/issues/new"
PICTURE = "<!-- screenshot -->"          # replaced by the service with the uploaded picture
KINDS = {"bug": "[Bug] ", "idea": "[Idea] "}
ZWSP = "\u200b"                          # zero-width space: breaks @mentions and ``` fences without showing
MAX_URL = 7000                           # GitHub refuses longer "new issue" links
SERVICE_URL = os.environ.get("VERSEFORGE_REPORTS_URL", "https://verseforge-reports.vercel.app/api/report")
ISSUES_API = f"https://api.github.com/repos/{REPO}/issues/"
KEEP = 50                                # reports remembered in config.json
STATUS_MAX = 20                          # statuses asked to GitHub at a time (public limit: 60 requests/hour)
STATUS_TTL = 300                         # seconds a status stays in memory
_status_cache = {}                       # issue number -> (time, {"state", "comments"})


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


def system_name():
    """Operating system in one line, e.g. "Windows-11-10.0.26300-SP0" or "Ubuntu 24.04.1 LTS (Linux 6.8.0)"."""
    if sys.platform.startswith("linux"):
        try:
            pretty = platform.freedesktop_os_release().get("PRETTY_NAME", "Linux")
        except OSError:
            pretty = "Linux"
        return f"{pretty} (Linux {platform.release()})"
    return platform.platform()


def _log_tail(log_path, n):
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except (OSError, TypeError):
        return []
    return [line[:300] for line in lines[-n:]]


def diagnostics(version=__version__, model=None, variant=None, gpu=None, log_path=None, log_lines=80):
    """Technical details attached to a report. The log is rewritten at every start of the app, so it only holds
    the session in progress; it does not exist when VerseForge runs from source."""
    lines = [f"VerseForge {version}", f"System: {system_name()}"]
    if gpu:
        lines.append(f"GPU: {gpu}")
    if model:
        lines.append(f"Model: {model}" + (f" (variant {variant})" if variant else ""))
    tail = _log_tail(log_path, log_lines)
    if tail:
        lines += ["", f"Last {len(tail)} log lines:", *tail]
    return "\n".join(lines)


class ReportError(Exception):
    """kind: "network" (no connection), "rate" (too many reports from this connection), "invalid" (the service
    refused the content, message says why) or "unavailable" (service off, hourly cap, GitHub down)."""

    def __init__(self, kind, message=""):
        super().__init__(message or kind)
        self.kind, self.message = kind, message


def send(composed, kind, screenshot_b64=None, version=__version__, url=None, timeout=25):
    """Post a composed report to the service; returns {"number", "url"} of the new issue."""
    payload = {"kind": kind, "title": composed["title"], "body": composed["body"], "version": version}
    if screenshot_b64:
        payload["screenshot"] = screenshot_b64
    req = urllib.request.Request(url or SERVICE_URL, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": f"VerseForge/{version}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            number = int(json.load(r)["number"])
    except urllib.error.HTTPError as e:
        try:
            message = str(json.load(e).get("error") or "")
        except (ValueError, AttributeError, OSError):
            message = ""
        raise ReportError({400: "invalid", 413: "invalid", 429: "rate"}.get(e.code, "unavailable"), message) from None
    except (urllib.error.URLError, OSError) as e:
        raise ReportError("network", str(getattr(e, "reason", e))) from None
    except (ValueError, KeyError, TypeError):
        raise ReportError("unavailable", "unexpected answer from the service") from None
    return {"number": number, "url": ISSUE_PAGE + str(number)}


def remember(cfg, number, title, now=None):
    """Keep a sent report in the settings (newest first) so "My reports" can list it."""
    items = [r for r in cfg.get("reports", []) if r.get("number") != number]
    items.insert(0, {"number": int(number), "title": title, "date": time.strftime("%Y-%m-%d", time.localtime(now))})
    cfg["reports"] = items[:KEEP]


def mine(cfg):
    return [dict(r) for r in cfg.get("reports", [])]


def statuses(numbers, api=ISSUES_API, timeout=8):
    """State and number of comments of the most recent reports, from GitHub's public API (no token). Deleted or
    hidden issues (404, 410) are "removed"; once GitHub refuses (public limit used up) the rest is left out.
    A transferred issue answers 301, which urllib follows: the moved issue's state is used."""
    out = {}
    for n in list(numbers)[:STATUS_MAX]:
        hit = _status_cache.get(n)
        if hit and time.time() - hit[0] < STATUS_TTL:
            out[n] = hit[1]
            continue
        req = urllib.request.Request(api + str(int(n)), headers={"Accept": "application/vnd.github+json",
                                                                  "User-Agent": f"VerseForge/{__version__}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                issue = json.load(r)
            info = {"state": "closed" if issue.get("state") == "closed" else "open",
                    "comments": int(issue.get("comments") or 0)}
        except urllib.error.HTTPError as e:
            if e.code not in (404, 410):
                break
            info = {"state": "removed", "comments": 0}
        except (urllib.error.URLError, OSError, ValueError):
            break
        _status_cache[n] = (time.time(), info)
        out[n] = info
    return out
