"""New versions: GitHub releases of VerseForge, download of the installer and hand-over to it.

Only the Windows app (VerseForge.exe) installs updates; the source version just links to the release page."""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request

REPO = "Pier144/VerseForge"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"   # installers are only ever taken from here


def parse_version(text):
    """"v1.3.0" -> (1, 3, 0); None if the text has no version number."""
    m = re.match(r"^[vV]?(\d+(?:\.\d+)*)", (text or "").strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def is_newer(latest, current):
    a, b = parse_version(latest), parse_version(current)
    if a is None or b is None:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def can_install():
    return bool(getattr(sys, "frozen", False)) and sys.platform == "win32"


def check(current, timeout=8):
    """Latest release on GitHub compared with the running version."""
    req = urllib.request.Request(LATEST_API, headers={"Accept": "application/vnd.github+json",
                                                      "User-Agent": f"VerseForge/{current}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        rel = json.load(r)
    latest = (rel.get("tag_name") or "").lstrip("vV")
    setup = next((a for a in rel.get("assets", [])
                  if a.get("name", "").lower().endswith("-setup.exe")
                  and a.get("browser_download_url", "").startswith(DOWNLOAD_PREFIX)), None)
    page = rel.get("html_url") or ""
    return {
        "current": current,
        "latest": latest,
        "available": is_newer(latest, current),
        "page": page if page.startswith(RELEASES_PAGE) else RELEASES_PAGE,
        "notes": (rel.get("body") or "")[:6000],
        "installer": {"name": setup["name"], "url": setup["browser_download_url"], "size": setup.get("size", 0),
                      "digest": setup.get("digest") or ""} if setup else None,
    }


def download(installer, progress=None, timeout=30):
    """Download the installer into %TEMP%\\VerseForge-update and check its size and SHA-256 (when GitHub gives it)."""
    url = installer["url"]
    if not url.startswith(DOWNLOAD_PREFIX):
        raise ValueError(f"unexpected download address: {url}")
    folder = os.path.join(tempfile.gettempdir(), "VerseForge-update")
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, re.sub(r"[^\w.\-]+", "_", os.path.basename(installer["name"])))
    part = dest + ".part"
    total, done, sha = int(installer.get("size") or 0), 0, hashlib.sha256()
    req = urllib.request.Request(url, headers={"User-Agent": "VerseForge-updater"})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(part, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
            sha.update(chunk)
            done += len(chunk)
            if progress and total:
                progress(min(done / total, 1.0))
    digest = installer.get("digest", "")
    if (total and done != total) or (digest.startswith("sha256:") and sha.hexdigest() != digest[7:].lower()):
        os.remove(part)
        raise ValueError("checksum")
    os.replace(part, dest)
    return dest


def launch(installer_path):
    """Start the installer detached: /SILENT shows only its progress window; it waits for VerseForge to quit (closing it
    if needed) and starts it again when done (see installer/VerseForge.iss)."""
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    subprocess.Popen([installer_path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                     creationflags=flags, close_fds=True)
