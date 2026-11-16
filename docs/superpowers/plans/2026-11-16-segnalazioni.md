# In-app Reports (GitHub issues) Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** VerseForge users send a bug report or an idea from inside the app; it becomes a public issue on `Pier144/VerseForge` opened by the "VerseForge Reports" GitHub App, and the user follows its status in the app.

**Architecture:** The app's local FastAPI server builds the whole issue text (`sc_explorer/reports.py`, the only owner of the text) after removing personal data, and posts it to a tiny Vercel function (`reports-service/`). The function validates it, uploads the optional screenshot to Vercel Blob, enforces an hourly cap and opens the issue with a GitHub App installation token. Status is read by the app straight from GitHub's public API.

**Tech Stack:** Python 3.12+ / FastAPI / urllib (app), vanilla JS + three.js (UI), Node 20+ with `node:test` and `@vercel/blob` (service), Vercel (hosting, Blob, firewall), GitHub App.

**Spec:** `docs/superpowers/specs/2026-11-16-segnalazioni-design.md`

**Repo conventions (read before starting):**
- Work directly on `main` in `D:\Dev\Progetti Automatici\Star Citizen Workshop\SC-Model-Explorer`. Commit locally after each task with an English message in the style of `git log` (a plain sentence, no `feat:` prefix). **Never push.**
- Python tests: `python -m pytest tests -q` (the whole suite takes about 100 s). Comments and docstrings are plain English, short, and explain *why*. No em dashes in code, UI text or docs.
- The UI is English only. User-facing strings live next to the code that shows them.
- Never write the real `config.json` in `%APPDATA%\VerseForge` from tests.
- No `innerHTML` with data (a security hook refuses it): build elements with `createElement` and `textContent`.

---

## Chunk 1: Commit pending work, then `sc_explorer/reports.py`

### Task 0: Commit the Blender fix and the spec

The working tree already holds a finished, tested fix (Blender found from the installed-programs list and from a folder path) and the spec.

- [ ] **Step 1:** Run `git status --short`. Expected changed/new files: `sc_explorer/printing.py`, `sc_explorer/server.py`, `web/app.js`, `web/index.html`, `web/style.css`, `tests/test_blender.py`, `docs/superpowers/specs/2026-11-16-segnalazioni-design.md`, `docs/superpowers/plans/2026-11-16-segnalazioni.md`. If anything else shows up, stop and report it.
- [ ] **Step 2:** Run `python -m pytest tests/test_blender.py -q`. Expected: `8 passed`.
- [ ] **Step 3: Commit**

```bash
git add sc_explorer/printing.py sc_explorer/server.py web/app.js web/index.html web/style.css tests/test_blender.py
git commit -m "Blender found anywhere: the installed programs list on Windows, the folder or a quoted path in Settings, and a line under the field saying which Blender is used"
git add docs/superpowers/specs/2026-11-16-segnalazioni-design.md docs/superpowers/plans/2026-11-16-segnalazioni.md
git commit -m "Design and plan for reports sent from the app as GitHub issues"
```

### Task 1: Personal data removal (`anonymize`, `local_identity`, `user_folders`)

**Files:** Create `sc_explorer/reports.py`, `tests/test_reports.py`

- [ ] **Step 1: Write the failing tests** in `tests/test_reports.py`:

```python
"""Reports sent from VerseForge (sc_explorer/reports.py): personal data removed, issue text, fallback link, status."""
import json
import os
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sc_explorer import reports  # noqa: E402

WIN = dict(home=r"C:\Users\Mario", user="Mario", machine="DESKTOP-MARIO7")


def test_anonymize_windows_home_any_slash_and_case():
    text = r"opened C:\Users\Mario\Documents\VerseForge\a.glb and c:/users/mario/AppData"
    assert reports.anonymize(text, **WIN) == r"opened <home>\Documents\VerseForge\a.glb and <home>/AppData"


def test_anonymize_linux_home_and_wine_prefix():
    game = "/home/bob/Games/star-citizen/drive_c/Program Files/Roberts Space Industries/StarCitizen"
    text = f"p4k at {game}/LIVE/Data.p4k, cache /home/bob/.cache/VerseForge"
    out = reports.anonymize(text, home="/home/bob", user="bob", machine="arch", folders=[(game, "<game>")])
    assert out == "p4k at <game>/LIVE/Data.p4k, cache <home>/.cache/VerseForge"


def test_anonymize_folders_outside_home():
    text = r"export to D:\Stuff\Exports\x.stl, blender D:\Programmi\Blender 4.4\blender.exe"
    out = reports.anonymize(text, **WIN, folders=[(r"D:\Stuff\Exports", "<exports>"),
                                                  (r"D:\Programmi\Blender 4.4", "<blender>")])
    assert out == r"export to <exports>\x.stl, blender <blender>\blender.exe"


def test_anonymize_home_does_not_eat_longer_folder_names():
    assert reports.anonymize(r"C:\Users\Mariolino\x", **WIN) == r"C:\Users\Mariolino\x"


def test_anonymize_user_and_pc_as_whole_words_only():
    out = reports.anonymize("Mario on DESKTOP-MARIO7 asked; Marione stays", **WIN)
    assert out == "<user> on <pc> asked; Marione stays"


def test_anonymize_ignores_very_short_names():
    assert reports.anonymize("a bo b on pc", home="", user="bo", machine="pc") == "a bo b on pc"


def test_anonymize_empty():
    assert reports.anonymize("", **WIN) == ""
    assert reports.anonymize(None, **WIN) == ""


def test_user_folders():
    cfg = {"p4k_path": r"C:\Games\RSI\StarCitizen\LIVE\Data.p4k", "export_dir": r"D:\Exports"}
    assert reports.user_folders(cfg, r"D:\Programmi\Blender 4.4\blender.exe") == [
        (r"C:\Games\RSI\StarCitizen", "<game>"), (r"D:\Exports", "<exports>"), (r"D:\Programmi\Blender 4.4", "<blender>")]
    assert reports.user_folders({}, "/usr/bin/blender") == []      # a system folder is not personal
```

(`user_folders` uses `ntpath` for paths with a backslash, so this test also passes on the Linux CI.)

- [ ] **Step 2:** Run `python -m pytest tests/test_reports.py -q`. Expected: collection error (`cannot import name 'reports'`).

- [ ] **Step 3: Write** `sc_explorer/reports.py`:

```python
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
```

- [ ] **Step 4:** Run `python -m pytest tests/test_reports.py -q`. Expected: `8 passed`.
- [ ] **Step 5: Commit** `git add sc_explorer/reports.py tests/test_reports.py && git commit -m "Reports: remove home, game, export and Blender folders, user and PC names from report texts"`

### Task 2: Issue text and fallback link (`compose`, `fallback_url`)

**Files:** Modify `sc_explorer/reports.py`, `tests/test_reports.py`

- [ ] **Step 1: Append the failing tests:**

```python
def test_compose_bug_with_picture_and_details():
    c = reports.compose("bug", "  Carrack   textures  ", "It is grey.", "VerseForge 1.14.0", True, "1.14.0")
    assert c["title"] == "[Bug] Carrack textures"
    body = c["body"]
    assert body.startswith("It is grey.")
    assert body.count(reports.PICTURE) == 1
    assert "<details><summary>Technical details</summary>" in body
    assert "```text\nVerseForge 1.14.0\n```" in body
    assert body.endswith("<sub>Sent from VerseForge 1.14.0</sub>")


def test_compose_idea_without_extras():
    c = reports.compose("idea", "More backdrops", "Please add a Pyro station.", "", False, "1.14.0")
    assert c["title"] == "[Idea] More backdrops"
    assert reports.PICTURE not in c["body"] and "<details>" not in c["body"]


def test_compose_neutralises_user_markup():
    c = reports.compose("bug", "@octocat look", "x </details> y <details> z <!-- screenshot --> w @someone",
                        "a ``` b", False, "1.0.0")
    assert c["title"] == "[Bug] @\u200boctocat look"
    body = c["body"]
    assert "</details> y" not in body and "<details> z" not in body
    assert reports.PICTURE not in body
    assert "@\u200bsomeone" in body
    assert "a `\u200b`` b" in body


def test_compose_breaks_mentions_once():
    body = reports.compose("bug", "Title", "hi @bob", "", False, "1.0.0")["body"]
    assert "@\u200bbob" in body and "\u200b\u200b" not in body


def test_compose_unknown_kind_is_a_bug():
    assert reports.compose("spam", "Title", "Some text here", "", False, "1.0.0")["title"].startswith("[Bug] ")


def test_fallback_url_short():
    c = reports.compose("bug", "Title here", "Some text here", "", True, "1.0.0")
    u = reports.fallback_url(c)
    assert u.startswith("https://github.com/Pier144/VerseForge/issues/new?")
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(u).query)
    assert q["title"] == ["[Bug] Title here"]
    assert reports.PICTURE not in q["body"][0] and "attach a screenshot" in q["body"][0]


def test_fallback_url_long_text_is_cut():
    c = reports.compose("bug", "Title here", "è" * 9000, "log line\n" * 500, False, "1.0.0")
    u = reports.fallback_url(c)
    assert len(u) <= reports.MAX_URL
    assert "did not fit" in urllib.parse.parse_qs(urllib.parse.urlsplit(u).query)["body"][0]
```

- [ ] **Step 2:** Run the tests. Expected: the 7 new tests FAIL (`no attribute 'compose'` / `'PICTURE'`).

- [ ] **Step 3: Add to `reports.py`.** Imports: add `import urllib.parse`, then after the stdlib imports `from . import __version__` and `from .updates import REPO`. Constants after the imports:

```python
ISSUE_PAGE = f"https://github.com/{REPO}/issues/"
NEW_ISSUE = f"https://github.com/{REPO}/issues/new"
PICTURE = "<!-- screenshot -->"          # replaced by the service with the uploaded picture
KINDS = {"bug": "[Bug] ", "idea": "[Idea] "}
ZWSP = "\u200b"                          # zero-width space: breaks @mentions and ``` fences without showing
MAX_URL = 7000                           # GitHub refuses longer "new issue" links
```

Functions:

```python
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
```

- [ ] **Step 4:** Run `python -m pytest tests/test_reports.py -q`. Expected: `15 passed`.
- [ ] **Step 5: Commit** `git add sc_explorer/reports.py tests/test_reports.py && git commit -m "Reports: issue title and body built in one place, user markup neutralised, fallback link to GitHub's form"`

### Task 3: Technical details (`diagnostics`)

**Files:** Modify `sc_explorer/reports.py`, `tests/test_reports.py`

- [ ] **Step 1: Append the failing tests:**

```python
def test_diagnostics_with_log(tmp_path):
    log = tmp_path / "verseforge.log"
    log.write_text("\n".join(f"line {i}" for i in range(200)), encoding="utf-8")
    d = reports.diagnostics("1.14.0", model="Data/Objects/ships/carrack.cgf", variant="pirate", gpu="RTX 4080",
                            log_path=str(log), log_lines=5)
    lines = d.splitlines()
    assert lines[0] == "VerseForge 1.14.0"
    assert lines[1].startswith("System: ")
    assert "GPU: RTX 4080" in lines and "Model: Data/Objects/ships/carrack.cgf (variant pirate)" in lines
    assert lines[-5:] == [f"line {i}" for i in range(195, 200)]


def test_diagnostics_without_log(tmp_path):
    d = reports.diagnostics("1.14.0", log_path=str(tmp_path / "missing.log"))
    assert "log lines" not in d and "Model:" not in d and "GPU:" not in d
```

- [ ] **Step 2:** Run the tests. Expected: the 2 new tests FAIL (`no attribute 'diagnostics'`).

- [ ] **Step 3: Add to `reports.py`** (add `import sys` to the imports):

```python
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
```

- [ ] **Step 4:** Run `python -m pytest tests/test_reports.py -q`. Expected: `17 passed`.
- [ ] **Step 5: Commit** `git add sc_explorer/reports.py tests/test_reports.py && git commit -m "Reports: technical details (version, system, graphics card, open model, last log lines)"`

### Task 4: Sending, the list of sent reports and their status

**Files:** Modify `sc_explorer/reports.py`, `tests/test_reports.py`

- [ ] **Step 1: Append the failing tests** (the fixture runs a real local HTTP server):

```python
@pytest.fixture
def fake():
    """Local HTTP server answering with the status and JSON set by the test; it records every request."""
    box = {"status": 201, "body": {"number": 42, "url": "x"}, "seen": []}

    class Handler(BaseHTTPRequestHandler):
        def _answer(self):
            n = int(self.headers.get("Content-Length") or 0)
            box["seen"].append({"path": self.path, "headers": dict(self.headers), "body": self.rfile.read(n)})
            status, body = box["status"], box["body"]
            if callable(status):
                status, body = status(self.path)
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = _answer

        def log_message(self, *args):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    box["url"] = f"http://127.0.0.1:{srv.server_address[1]}"
    yield box
    srv.shutdown()


def _short():
    return reports.compose("bug", "Title here", "Some text here", "", False, "1.0.0")


def test_send_ok(fake):
    c = reports.compose("bug", "Title here", "Some text here", "", True, "1.14.0")
    out = reports.send(c, "bug", "/9j/AAAA", version="1.14.0", url=fake["url"] + "/api/report")
    assert out == {"number": 42, "url": "https://github.com/Pier144/VerseForge/issues/42"}
    req = fake["seen"][0]
    assert req["path"] == "/api/report" and req["headers"]["User-Agent"] == "VerseForge/1.14.0"
    assert json.loads(req["body"]) == {"kind": "bug", "title": c["title"], "body": c["body"], "version": "1.14.0",
                                       "screenshot": "/9j/AAAA"}


@pytest.mark.parametrize("status,kind", [(400, "invalid"), (403, "unavailable"), (429, "rate"), (503, "unavailable"),
                                         (500, "unavailable")])
def test_send_errors(fake, status, kind):
    fake["status"], fake["body"] = status, {"error": "Title must be 5 to 130 characters"}
    with pytest.raises(reports.ReportError) as e:
        reports.send(_short(), "bug", url=fake["url"])
    assert e.value.kind == kind
    if status == 400:
        assert e.value.message == "Title must be 5 to 130 characters"


def test_send_network_down():
    with pytest.raises(reports.ReportError) as e:
        reports.send(_short(), "bug", url="http://127.0.0.1:9/", timeout=3)
    assert e.value.kind == "network"


def test_remember_newest_first_and_capped():
    cfg = {}
    for n in range(1, 60):
        reports.remember(cfg, n, f"t{n}")
    reports.remember(cfg, 5, "again")
    items = reports.mine(cfg)
    assert len(items) == reports.KEEP
    assert items[0]["number"] == 5 and items[0]["title"] == "again" and items[1]["number"] == 59
    assert len(items[0]["date"]) == 10                       # YYYY-MM-DD


def test_statuses(fake):
    answers = {1: (200, {"state": "open", "comments": 3}), 2: (200, {"state": "closed", "comments": 0}),
               3: (404, {}), 4: (410, {})}
    fake["status"] = lambda path: answers[int(path.rsplit("/", 1)[1])]
    reports._status_cache.clear()
    api = fake["url"] + "/issues/"
    assert reports.statuses([1, 2, 3, 4], api=api) == {
        1: {"state": "open", "comments": 3}, 2: {"state": "closed", "comments": 0},
        3: {"state": "removed", "comments": 0}, 4: {"state": "removed", "comments": 0}}
    reports.statuses([1], api=api)
    assert len(fake["seen"]) == 4                            # the second time it comes from memory


def test_statuses_stop_when_the_public_limit_is_used_up(fake):
    fake["status"], fake["body"] = 403, {"message": "API rate limit exceeded"}
    reports._status_cache.clear()
    assert reports.statuses([7, 8], api=fake["url"] + "/issues/") == {}
    assert len(fake["seen"]) == 1
```

- [ ] **Step 2:** Run the tests. Expected: the new tests FAIL (`no attribute 'send'` / `'remember'` / `'_status_cache'`).

- [ ] **Step 3: Add to `reports.py`** (imports: `import json`, `import time`, `import urllib.error`, `import urllib.request`):

```python
SERVICE_URL = os.environ.get("VERSEFORGE_REPORTS_URL", "https://verseforge-reports.vercel.app/api/report")
ISSUES_API = f"https://api.github.com/repos/{REPO}/issues/"
KEEP = 50                                # reports remembered in config.json
STATUS_MAX = 20                          # statuses asked to GitHub at a time (public limit: 60 requests/hour)
STATUS_TTL = 300                         # seconds a status stays in memory
_status_cache = {}                       # issue number -> (time, {"state", "comments"})


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
```

- [ ] **Step 4:** Run `python -m pytest tests/test_reports.py -q`. Expected: all pass (28 tests).
- [ ] **Step 5: Commit** `git add sc_explorer/reports.py tests/test_reports.py && git commit -m "Reports: send to the service, remember sent reports, read their status from GitHub"`

---

## Chunk 2: Server endpoints

### Task 5: `/api/report/*` in `server.py`

**Files:** Modify `sc_explorer/server.py` (imports; new section just before `@app.exception_handler(Exception)`); create `tests/test_reports_api.py`

- [ ] **Step 1: Write the failing tests** `tests/test_reports_api.py`:

```python
"""Report endpoints of the local server: the real config is never written (save_config replaced, cfg copied)."""
import os
import sys

import pytest

pytest.importorskip("httpx")                       # FastAPI's TestClient needs it (not in requirements.txt)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi.testclient import TestClient  # noqa: E402

from sc_explorer import reports, server  # noqa: E402

FIELDS = {"kind": "bug", "title": "Carrack textures", "description": "Interior is grey everywhere.",
          "picture": True, "details": False}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "save_config", lambda cfg: None)
    monkeypatch.setattr(server.state, "cfg", {**server.state.cfg, "reports": []})
    return TestClient(server.app)                  # no `with`: the game catalogue is not loaded


def test_preview(client):
    out = client.post("/api/report/preview", json=FIELDS).json()
    assert out["title"] == "[Bug] Carrack textures" and reports.PICTURE in out["body"]
    assert "Technical details" not in out["body"]
    with_details = client.post("/api/report/preview", json={**FIELDS, "details": True, "gpu": "RTX 4080"}).json()
    assert "GPU: RTX 4080" in with_details["body"]


def test_send_remembers_the_issue(client, monkeypatch):
    got = {}

    def fake_send(composed, kind, screenshot_b64=None, **kw):
        got.update(composed=composed, kind=kind, shot=screenshot_b64)
        return {"number": 7, "url": reports.ISSUE_PAGE + "7"}

    monkeypatch.setattr(reports, "send", fake_send)
    r = client.post("/api/report", json={**FIELDS, "screenshot": "/9j/AA"})
    assert r.json() == {"number": 7, "url": "https://github.com/Pier144/VerseForge/issues/7"}
    assert got["shot"] == "/9j/AA" and got["kind"] == "bug" and reports.PICTURE in got["composed"]["body"]
    assert server.state.cfg["reports"][0]["number"] == 7


def test_send_without_screenshot_has_no_placeholder(client, monkeypatch):
    got = {}

    def fake_send(composed, kind, screenshot_b64=None, **kw):
        got["composed"] = composed
        return {"number": 8, "url": reports.ISSUE_PAGE + "8"}

    monkeypatch.setattr(reports, "send", fake_send)
    client.post("/api/report", json=FIELDS)
    assert reports.PICTURE not in got["composed"]["body"]


def test_send_error_kind(client, monkeypatch):
    def boom(*args, **kwargs):
        raise reports.ReportError("rate", "")

    monkeypatch.setattr(reports, "send", boom)
    r = client.post("/api/report", json=FIELDS)
    assert r.status_code == 502 and r.json()["kind"] == "rate"
    assert server.state.cfg["reports"] == []


def test_mine_with_status(client, monkeypatch):
    server.state.cfg["reports"] = [{"number": 7, "title": "[Bug] x", "date": "2026-11-16"},
                                   {"number": 3, "title": "[Idea] y", "date": "2026-11-15"}]
    monkeypatch.setattr(reports, "statuses", lambda numbers: {7: {"state": "closed", "comments": 2}})
    assert client.get("/api/report/mine").json() == {"reports": [
        {"number": 7, "title": "[Bug] x", "date": "2026-11-16", "state": "closed", "comments": 2},
        {"number": 3, "title": "[Idea] y", "date": "2026-11-15", "state": None, "comments": None}]}


def test_open_only_builds_github_addresses(client, monkeypatch):
    opened = []
    monkeypatch.setattr(server.paths, "open_path", opened.append)
    assert client.post("/api/report/open", json={"number": 7}).status_code == 200
    assert client.post("/api/report/open", json={"fallback": FIELDS}).status_code == 200
    assert opened[0] == "https://github.com/Pier144/VerseForge/issues/7"
    assert opened[1].startswith("https://github.com/Pier144/VerseForge/issues/new?")
    assert client.post("/api/report/open", json={}).status_code == 400
    assert client.post("/api/report/open", json={"number": -1}).status_code == 400
```

- [ ] **Step 2:** Run `python -m pytest tests/test_reports_api.py -q`. Expected: FAIL (the new endpoints answer 404 or 405).

- [ ] **Step 3: Implement.** In `server.py`: add `reports` to the `from . import ...` line (alphabetical: `..., printing, reports, textures, ...`) and `from pydantic import BaseModel` after the fastapi imports. Insert this section right before `@app.exception_handler(Exception)`:

```python
# ------------------------------------------------------------------ reports (public GitHub issues, see reports.py)
LOG_FILE = os.path.join(CACHE_DIR, "verseforge.log")     # written by verseforge_app.py in the packaged app only


class ReportIn(BaseModel):
    kind: str = "bug"
    title: str = ""
    description: str = ""
    picture: bool = True
    details: bool = True
    model: str | None = None
    variant: str | None = None
    gpu: str | None = None
    screenshot: str | None = None          # JPEG in base64 (only for sending)


class OpenIn(BaseModel):
    number: int | None = None
    fallback: ReportIn | None = None


def _compose_report(r, with_picture):
    """Anonymized issue text for a report from the interface: the same text for the preview, the real report and
    the fallback link."""
    folders = reports.user_folders(state.cfg, printing.find_blender(state.cfg.get("blender")))
    ident = reports.local_identity()

    def clean(text):
        return reports.anonymize(text, folders=folders, **ident)

    details = ""
    if r.details:
        log = LOG_FILE if getattr(sys, "frozen", False) else None
        details = clean(reports.diagnostics(__version__, model=r.model, variant=r.variant, gpu=r.gpu, log_path=log))
    kind = r.kind if r.kind in reports.KINDS else "bug"
    return kind, reports.compose(kind, clean(r.title), clean(r.description), details, with_picture, __version__)


@app.post("/api/report/preview")
def report_preview(r: ReportIn):
    return _compose_report(r, r.picture)[1]


@app.post("/api/report")
def report_send(r: ReportIn):
    shot = r.screenshot if r.picture and r.screenshot else None
    kind, composed = _compose_report(r, bool(shot))
    try:
        out = reports.send(composed, kind, shot)
    except reports.ReportError as e:
        return JSONResponse({"kind": e.kind, "detail": e.message}, status_code=502)
    reports.remember(state.cfg, out["number"], composed["title"])
    save_config(state.cfg)
    return out


@app.get("/api/report/mine")
def report_mine():
    items = reports.mine(state.cfg)
    known = reports.statuses([it["number"] for it in items])
    return {"reports": [{**it, **known.get(it["number"], {"state": None, "comments": None})} for it in items]}


@app.post("/api/report/open")
def report_open(o: OpenIn):
    """Open a sent report, or GitHub's own form filled in. The address is always built here."""
    if o.number is not None and o.number > 0:
        paths.open_path(reports.ISSUE_PAGE + str(int(o.number)))
    elif o.fallback is not None:
        paths.open_path(reports.fallback_url(_compose_report(o.fallback, o.fallback.picture)[1]))
    else:
        raise HTTPException(400, "Nothing to open")
    return {"ok": True}
```

- [ ] **Step 4:** Run `python -m pytest tests/test_reports_api.py tests/test_reports.py -q` (all pass), then the full suite `python -m pytest tests -q` (all pass).
- [ ] **Step 5: Commit** `git add sc_explorer/server.py tests/test_reports_api.py && git commit -m "Report endpoints: preview, send, my reports with status, open on GitHub"`

---

## Chunk 3: The service (`reports-service/`)

All commands in this chunk run from `reports-service/`. Node is installed (v24).

### Task 6: Project skeleton and validation

**Files:** Create `reports-service/package.json`, `reports-service/vercel.json`, `reports-service/.gitignore`, `reports-service/lib/validate.js`, `reports-service/test/validate.test.js`

- [ ] **Step 1: Skeleton files.**

`reports-service/package.json`:
```json
{
  "name": "verseforge-reports",
  "private": true,
  "type": "module",
  "description": "Receives reports from VerseForge and opens them as GitHub issues (VerseForge Reports app).",
  "engines": { "node": ">=20" },
  "scripts": { "test": "node --test" },
  "dependencies": { "@vercel/blob": "^2.9.0" }
}
```

`reports-service/vercel.json` (only rebuild when this folder changes):
```json
{ "ignoreCommand": "git diff --quiet HEAD^ HEAD -- ." }
```

`reports-service/.gitignore`:
```
node_modules/
.vercel/
```

- [ ] **Step 2: Write the failing test** `reports-service/test/validate.test.js`:

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { validate, breakMentions, placePicture, PICTURE } from "../lib/validate.js";

const JPEG = Buffer.from([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3]).toString("base64");
const good = { kind: "bug", title: "[Bug] Carrack", body: "It is grey everywhere", version: "1.14.0" };

test("accepts a good report with a picture", () => {
  const { report, error } = validate({ ...good, screenshot: JPEG });
  assert.equal(error, undefined);
  assert.equal(report.kind, "bug");
  assert.equal(report.picture.length, 7);
});

test("accepts a report without a picture", () => {
  assert.equal(validate(good).report.picture, null);
});

test("rejects bad fields", () => {
  const bad = [null, "text", { ...good, kind: "spam" }, { ...good, title: "abc" }, { ...good, title: "x".repeat(131) },
    { ...good, body: "short" }, { ...good, body: "x".repeat(20001) }, { ...good, version: "" },
    { ...good, version: "1.14" }, { ...good, screenshot: "not base64!" },
    { ...good, screenshot: Buffer.from("GIF89a").toString("base64") }];
  for (const b of bad) assert.ok(validate(b).error, JSON.stringify(b)?.slice(0, 80));
});

test("rejects pictures over 2 MB", () => {
  const big = Buffer.alloc(2 * 1024 * 1024 + 1);
  big[0] = 0xff; big[1] = 0xd8; big[2] = 0xff;
  assert.match(validate({ ...good, screenshot: big.toString("base64") }).error, /2 MB/);
});

test("mentions are broken once", () => {
  const once = breakMentions("hi @bob and a@b");
  assert.equal(once, "hi @\u200bbob and a@\u200bb");
  assert.equal(breakMentions(once), once);
  assert.equal(validate({ ...good, body: "ping @octocat please" }).report.body, "ping @\u200boctocat please");
});

test("the picture goes in the last placeholder only", () => {
  assert.equal(placePicture(`a ${PICTURE} b ${PICTURE} c`, "IMG"), `a ${PICTURE} b IMG c`);
  assert.equal(placePicture("no marker", "IMG"), "no marker");
});
```

- [ ] **Step 3:** Run `node --test`. Expected: FAIL (cannot find `../lib/validate.js`).

- [ ] **Step 4: Implement** `reports-service/lib/validate.js`:

```js
// Checks a report sent by VerseForge. The app builds the whole issue text (sc_explorer/reports.py): here it is only
// checked, never rewritten, apart from @mentions, which are broken again in case the request did not come from the app.
export const PICTURE = "<!-- screenshot -->";
const LIMITS = { title: [5, 130], body: [10, 20000], picture: 2 * 1024 * 1024 };
const VERSION = /^\d+\.\d+\.\d+$/;
const BASE64 = /^[A-Za-z0-9+/]+={0,2}$/;

export function breakMentions(text) {
  return text.replace(/@(?=[A-Za-z0-9])/g, "@\u200b");   // zero-width space: GitHub does not notify anyone
}

const length = (s, [min, max]) => typeof s === "string" && s.trim().length >= min && s.length <= max;

export function validate(input) {
  if (!input || typeof input !== "object") return { error: "The report is empty" };
  const { kind, title, body, version, screenshot } = input;
  if (kind !== "bug" && kind !== "idea") return { error: "Unknown report type" };
  if (!length(title, LIMITS.title)) return { error: "The title must be 5 to 130 characters" };
  if (!length(body, LIMITS.body)) return { error: "The text must be 10 to 20000 characters" };
  if (typeof version !== "string" || !VERSION.test(version)) return { error: "Missing VerseForge version" };
  let picture = null;
  if (screenshot != null) {
    if (typeof screenshot !== "string" || !BASE64.test(screenshot)) return { error: "The picture is not valid" };
    picture = Buffer.from(screenshot, "base64");
    if (picture.length > LIMITS.picture) return { error: "The picture is larger than 2 MB" };
    if (picture.length < 3 || picture[0] !== 0xff || picture[1] !== 0xd8 || picture[2] !== 0xff) {
      return { error: "The picture must be a JPEG" };
    }
  }
  return { report: { kind, title: breakMentions(title.trim()), body: breakMentions(body), version, picture } };
}

export function placePicture(body, markdown) {
  const i = body.lastIndexOf(PICTURE);
  return i < 0 ? body : body.slice(0, i) + markdown + body.slice(i + PICTURE.length);
}
```

- [ ] **Step 5:** Run `node --test`. Expected: 6 pass, 0 fail.
- [ ] **Step 6: Commit** `git add reports-service && git commit -m "Reports service: project and validation of incoming reports"`

### Task 7: GitHub App client

**Files:** Create `reports-service/lib/github.js`, `reports-service/test/github.test.js`

- [ ] **Step 1: Write the failing test** `reports-service/test/github.test.js`:

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { generateKeyPairSync, createVerify } from "node:crypto";
import { appJwt, GitHub } from "../lib/github.js";

const { privateKey, publicKey } = generateKeyPairSync("rsa", {
  modulusLength: 2048,
  privateKeyEncoding: { type: "pkcs8", format: "pem" },
  publicKeyEncoding: { type: "spki", format: "pem" },
});
const NOW = Date.UTC(2026, 10, 16, 12, 0, 0);
const REPO = "Pier144/VerseForge";

// fetch stand-in: routes are "METHOD /path" -> [status, json] or (nth call of that route) => [status, json]
function fakeFetch(routes) {
  const calls = [];
  const fn = async (url, opts = {}) => {
    const key = `${opts.method || "GET"} ${new URL(url).pathname}`;
    calls.push({ url, key, ...opts });
    const route = routes[key];
    if (!route) throw new Error(`unexpected ${key}`);
    const [status, body] = typeof route === "function" ? route(calls.filter((c) => c.key === key).length) : route;
    return { ok: status < 300, status, statusText: String(status), json: async () => body };
  };
  fn.calls = calls;
  return fn;
}
const INSTALL = { [`GET /repos/${REPO}/installation`]: [200, { id: 99 }] };
const token = (t = "t1") => [201, { token: t, expires_at: "2026-11-16T13:00:00Z" }];
const client = (fetch) => new GitHub({ appId: 123, privateKey, repo: REPO, fetch, now: () => NOW });

test("app JWT is signed, short-lived and accepts a key pasted on one line", () => {
  const jwt = appJwt(123, privateKey.replace(/\n/g, "\\n"), NOW);
  const [h, c, s] = jwt.split(".");
  assert.deepEqual(JSON.parse(Buffer.from(c, "base64url")), { iat: NOW / 1000 - 60, exp: NOW / 1000 + 540, iss: "123" });
  const v = createVerify("RSA-SHA256");
  v.update(`${h}.${c}`);
  assert.ok(v.verify(publicKey, s, "base64url"));
});

test("finds the installation, keeps the token and creates issues", async () => {
  const f = fakeFetch({ ...INSTALL, "POST /app/installations/99/access_tokens": token(),
    [`POST /repos/${REPO}/issues`]: [201, { number: 5, html_url: "u" }] });
  const g = client(f);
  assert.equal((await g.createIssue({ title: "t", body: "b", labels: ["from-app"] })).number, 5);
  await g.createIssue({ title: "t2", body: "b2", labels: [] });
  assert.equal(f.calls.filter((c) => c.key.endsWith("access_tokens")).length, 1);
  assert.equal(f.calls.at(-1).headers.Authorization, "Bearer t1");
  assert.deepEqual(JSON.parse(f.calls.at(-1).body), { title: "t2", body: "b2", labels: [] });
});

test("a 401 renews the token once and retries", async () => {
  let n = 0;
  const f = fakeFetch({ ...INSTALL, "POST /app/installations/99/access_tokens": () => token(`t${++n}`),
    [`POST /repos/${REPO}/issues`]: (k) => (k === 1 ? [401, { message: "Bad credentials" }] : [201, { number: 6 }]) });
  assert.equal((await client(f).createIssue({ title: "t", body: "b", labels: [] })).number, 6);
  assert.equal(f.calls.at(-1).headers.Authorization, "Bearer t2");
});

test("other errors carry the status", async () => {
  const f = fakeFetch({ ...INSTALL, "POST /app/installations/99/access_tokens": token(),
    [`POST /repos/${REPO}/issues`]: [422, { message: "Validation Failed" }] });
  await assert.rejects(client(f).createIssue({ title: "t", body: "b", labels: [] }), { status: 422 });
});

test("counts recent reports with search", async () => {
  const f = fakeFetch({ ...INSTALL, "POST /app/installations/99/access_tokens": token(),
    "GET /search/issues": [200, { total_count: 3 }] });
  assert.equal(await client(f).recentReports("2026-11-16T11:00:00Z"), 3);
  assert.equal(new URL(f.calls.at(-1).url).searchParams.get("q"),
    `repo:${REPO} is:issue label:from-app created:>=2026-11-16T11:00:00Z`);
});
```

- [ ] **Step 2:** Run `node --test`. Expected: FAIL (cannot find `../lib/github.js`).

- [ ] **Step 3: Implement** `reports-service/lib/github.js`:

```js
// GitHub REST calls as the "VerseForge Reports" GitHub App: a JWT signed with the app's private key buys an
// installation token (valid 1 hour), kept in memory while the function instance stays warm.
import { createSign } from "node:crypto";

const API = "https://api.github.com";
const b64url = (x) => Buffer.from(x).toString("base64url");

export class GitHubError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

export function appJwt(appId, privateKey, now = Date.now()) {
  const t = Math.floor(now / 1000);
  const head = b64url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  // issued a minute in the past and valid 9 minutes: GitHub allows 10, and clocks drift
  const claims = b64url(JSON.stringify({ iat: t - 60, exp: t + 540, iss: String(appId) }));
  const sign = createSign("RSA-SHA256");
  sign.update(`${head}.${claims}`);
  return `${head}.${claims}.${sign.sign(privateKey.replace(/\\n/g, "\n"), "base64url")}`;
}

export class GitHub {
  constructor({ appId, privateKey, installationId, repo, fetch = globalThis.fetch, now = Date.now }) {
    Object.assign(this, { appId, privateKey, installationId, repo, fetch, now });
    this.token = null;
    this.tokenExp = 0;
  }

  async call(method, path, { token, body } = {}) {
    const headers = { Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "verseforge-reports", Authorization: `Bearer ${token}` };
    if (body) headers["Content-Type"] = "application/json";
    const r = await this.fetch(API + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new GitHubError(r.status, data.message || r.statusText);
    return data;
  }

  async installationToken(force = false) {
    if (!force && this.token && this.now() < this.tokenExp - 5 * 60_000) return this.token;
    const jwt = appJwt(this.appId, this.privateKey, this.now());
    if (!this.installationId) {
      this.installationId = (await this.call("GET", `/repos/${this.repo}/installation`, { token: jwt })).id;
    }
    const t = await this.call("POST", `/app/installations/${this.installationId}/access_tokens`, { token: jwt });
    this.token = t.token;
    this.tokenExp = Date.parse(t.expires_at) || this.now() + 3_600_000;
    return this.token;
  }

  // with the installation token; a 401 (token revoked or expired early) renews it once
  async request(method, path, body) {
    try {
      return await this.call(method, path, { token: await this.installationToken(), body });
    } catch (e) {
      if (e.status !== 401) throw e;
      return this.call(method, path, { token: await this.installationToken(true), body });
    }
  }

  async recentReports(sinceIso) {
    const q = encodeURIComponent(`repo:${this.repo} is:issue label:from-app created:>=${sinceIso}`);
    return (await this.request("GET", `/search/issues?q=${q}&per_page=1`)).total_count;
  }

  createIssue({ title, body, labels }) {
    return this.request("POST", `/repos/${this.repo}/issues`, { title, body, labels });
  }
}
```

- [ ] **Step 4:** Run `node --test`. Expected: all pass (11 tests).
- [ ] **Step 5: Commit** `git add reports-service && git commit -m "Reports service: GitHub App token and issue calls"`

### Task 8: Request handling and the Vercel entry point

**Files:** Create `reports-service/lib/handle.js`, `reports-service/api/report.js`, `reports-service/README.md`, `reports-service/test/handle.test.js`

- [ ] **Step 1: Write the failing test** `reports-service/test/handle.test.js`:

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { handle } from "../lib/handle.js";

const JPEG = Buffer.from([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3]).toString("base64");
const report = { kind: "bug", title: "[Bug] Carrack", version: "1.14.0", screenshot: JPEG,
  body: "Grey everywhere\n\n<!-- screenshot -->\n\n<sub>Sent from VerseForge 1.14.0</sub>" };
const req = (body, ua = "VerseForge/1.14.0", method = "POST") => ({ method, headers: { "user-agent": ua }, body });
const ISSUE = { number: 42, html_url: "https://github.com/Pier144/VerseForge/issues/42" };

function deps({ count = 0, issue = ISSUE, put = async (name) => `https://blob.example/${name}`, env = {} } = {}) {
  const made = [], logs = [];
  return {
    made, logs, log: (m) => logs.push(m), now: () => Date.UTC(2026, 10, 16, 12),
    env: { REPORTS_ENABLED: "1", REPORTS_PER_HOUR: "20", ...env },
    putPicture: put,
    github: {
      recentReports: async () => { if (count instanceof Error) throw count; return count; },
      createIssue: async (i) => { if (issue instanceof Error) throw issue; made.push(i); return issue; },
    },
  };
}

test("creates the issue with the picture and the labels", async () => {
  const d = deps();
  assert.deepEqual(await handle(req(report), d), { status: 201, json: { number: 42, url: ISSUE.html_url } });
  assert.deepEqual(d.made[0].labels, ["from-app", "bug"]);
  assert.equal(d.made[0].title, "[Bug] Carrack");
  assert.match(d.made[0].body, /!\[3D view\]\(https:\/\/blob\.example\/reports\/2026-11\/[0-9a-f-]{36}\.jpg\)/);
  assert.ok(d.logs.some((l) => /^issue #42 picture reports\/2026-11\//.test(l)));
});

test("an idea gets the enhancement label", async () => {
  const d = deps();
  await handle(req({ ...report, kind: "idea", screenshot: undefined }), d);
  assert.deepEqual(d.made[0].labels, ["from-app", "enhancement"]);
  assert.ok(!d.made[0].body.includes("<!-- screenshot -->"));
});

test("the issue still goes out when the picture upload fails", async () => {
  const d = deps({ put: async () => { throw new Error("blob down"); } });
  assert.equal((await handle(req(report), d)).status, 201);
  assert.match(d.made[0].body, /the picture could not be uploaded/);
});

test("switched off", async () => {
  assert.equal((await handle(req(report), deps({ env: { REPORTS_ENABLED: "0" } }))).status, 503);
});

test("only POST from VerseForge", async () => {
  assert.equal((await handle(req(report, "curl/8"), deps())).status, 403);
  assert.equal((await handle(req(report, undefined, "GET"), deps())).status, 405);
});

test("invalid content gets the reason", async () => {
  const out = await handle(req({ ...report, title: "abc" }), deps());
  assert.equal(out.status, 400);
  assert.match(out.json.error, /title/i);
});

test("hourly cap", async () => {
  const d = deps({ count: 20 });
  assert.equal((await handle(req(report), d)).status, 503);
  assert.equal(d.made.length, 0);
});

test("a failed count lets the report through", async () => {
  const d = deps({ count: Object.assign(new Error("search down"), { status: 500 }) });
  assert.equal((await handle(req(report), d)).status, 201);
  assert.ok(d.logs.some((l) => l.includes("search down")));
});

test("GitHub refusing the issue gives 503", async () => {
  const d = deps({ issue: Object.assign(new Error("Validation Failed"), { status: 422 }) });
  assert.equal((await handle(req(report), d)).status, 503);
});
```

- [ ] **Step 2:** Run `node --test`. Expected: FAIL (cannot find `../lib/handle.js`).

- [ ] **Step 3: Implement** `reports-service/lib/handle.js`:

```js
// One report from VerseForge -> one GitHub issue. Pure function of the request and its dependencies (GitHub
// client, picture upload, environment, clock, log), so it is tested without the network.
import { randomUUID } from "node:crypto";
import { validate, placePicture } from "./validate.js";

const reply = (status, json) => ({ status, json });

export async function handle(req, { env, github, putPicture, log = console.log, now = Date.now }) {
  if (req.method !== "POST") return reply(405, { error: "Use POST" });
  if (env.REPORTS_ENABLED !== "1") return reply(503, { error: "Reports are switched off for now" });
  if (!String(req.headers?.["user-agent"] || "").startsWith("VerseForge/")) {
    return reply(403, { error: "Reports are sent from VerseForge" });
  }
  const { error, report } = validate(req.body);
  if (error) return reply(400, { error });

  try {
    // hourly cap over all senders (approximate: GitHub's search index can lag a few minutes)
    try {
      const since = new Date(now() - 3_600_000).toISOString().replace(/\.\d+Z$/, "Z");
      if ((await github.recentReports(since)) >= Number(env.REPORTS_PER_HOUR || 20)) {
        log("hourly cap reached");
        return reply(503, { error: "Too many reports right now, try again later" });
      }
    } catch (e) {
      log(`count failed, report let through: ${e.message}`);   // the per-IP firewall limit still applies
    }

    let markdown = "", pictureName = "";
    if (report.picture) {
      pictureName = `reports/${new Date(now()).toISOString().slice(0, 7)}/${randomUUID()}.jpg`;
      try {
        markdown = `![3D view](${await putPicture(pictureName, report.picture)})`;
      } catch (e) {
        log(`picture upload failed: ${e.message}`);
        markdown = "_(the picture could not be uploaded)_";
        pictureName = "";
      }
    }
    const issue = await github.createIssue({
      title: report.title,
      body: placePicture(report.body, markdown),
      labels: ["from-app", report.kind === "bug" ? "bug" : "enhancement"],
    });
    log(`issue #${issue.number}${pictureName ? ` picture ${pictureName}` : ""}`);
    return reply(201, { number: issue.number, url: issue.html_url });
  } catch (e) {
    log(`GitHub refused the report (${e.status || "no status"}): ${e.message}`);
    return reply(503, { error: "GitHub did not accept the report, try again later" });
  }
}
```

`reports-service/api/report.js` (Vercel Node function; it only wires the real dependencies, so it has no unit test):

```js
import { put } from "@vercel/blob";
import { GitHub } from "../lib/github.js";
import { handle } from "../lib/handle.js";

let github;   // kept between requests while the instance is warm (the installation token is cached inside)

export default async function handler(req, res) {
  github ??= new GitHub({
    appId: process.env.GH_APP_ID,
    privateKey: process.env.GH_APP_PRIVATE_KEY || "",
    installationId: process.env.GH_APP_INSTALLATION_ID || undefined,
    repo: process.env.REPORTS_REPO || "Pier144/VerseForge",
  });
  let body;
  try {
    body = req.body;   // parsed by Vercel for application/json; reading it throws on broken JSON
  } catch {
    body = null;
  }
  const out = await handle({ method: req.method, headers: req.headers, body }, {
    env: process.env,
    github,
    putPicture: async (name, data) => (await put(name, data, { access: "public", contentType: "image/jpeg" })).url,
  });
  res.status(out.status).json(out.json);
}
```

`reports-service/README.md`:

````markdown
# VerseForge Reports service

Receives the reports sent from VerseForge (Feedback button) and opens them as public issues on
[Pier144/VerseForge](https://github.com/Pier144/VerseForge/issues?q=label%3Afrom-app) through the
**VerseForge Reports** GitHub App. Screenshots go to Vercel Blob. Hosted on Vercel (project `verseforge-reports`,
root directory `reports-service`).

The issue text is built by the app (`sc_explorer/reports.py`); this service only checks it, uploads the picture,
applies the limits and creates the issue.

## Environment variables

| name | value |
|---|---|
| `GH_APP_ID` | App ID of the VerseForge Reports GitHub App |
| `GH_APP_PRIVATE_KEY` | the app's private key (.pem content; one line with `\n` also works) |
| `GH_APP_INSTALLATION_ID` | optional: found automatically from the repository |
| `REPORTS_REPO` | `Pier144/VerseForge` |
| `REPORTS_ENABLED` | `1` to accept reports, anything else to switch them off |
| `REPORTS_PER_HOUR` | cap on reports per hour from everyone (default 20) |
| `BLOB_READ_WRITE_TOKEN` | set by Vercel when the Blob store is connected |

Firewall: rate limit rule on `/api/report`, 5 requests per 10 minutes per IP, action deny.

## Tests

```bash
node --test
```

## Emergency (spam or abuse)

1. Vercel, project settings, Environment Variables: `REPORTS_ENABLED=0`, then redeploy. The app then offers
   GitHub's own form instead.
2. Close the bad issues in bulk:
   `gh issue list -R Pier144/VerseForge -l from-app --search "created:>=YYYY-MM-DD" --json number -q ".[].number" | xargs -n1 gh issue close -R Pier144/VerseForge`
   (delete them from the GitHub page if their content must go).
3. Pictures: Vercel, Storage, the Blob store, delete the files. The function log has a line
   `issue #N picture reports/YYYY-MM/<id>.jpg` for each report with a picture.
````

- [ ] **Step 4:** Run `node --test`. Expected: all pass (20 tests).
- [ ] **Step 5:** Run `npm install` in `reports-service/` to create `package-lock.json` (`node_modules` stays ignored). `git status` shows only `package-lock.json` and the new files.
- [ ] **Step 6: Commit** `git add reports-service && git commit -m "Reports service: request handling with hourly cap, picture upload and the Vercel entry point; README with setup and emergency steps"`

---

## Chunk 4: The interface

### Task 9: Feedback dialog markup and styles

**Files:** Modify `web/index.html` (symbols block near line 28, top bar near line 66, new dialog right after the `#updateDlg` dialog), `web/style.css` (after `.version-line.missing`)

- [ ] **Step 1: Icon.** In the `<svg>` symbols block add after `i-download`:

```html
      <symbol id="i-chat" viewBox="0 0 24 24"><path d="M4.5 6.5A2 2 0 0 1 6.5 4.5h11a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H11l-4.5 3.5v-3.5h0a2 2 0 0 1-2-2z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M8.5 9.5h7M8.5 12.5h4.5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></symbol>
```

- [ ] **Step 2: Button.** In `<header class="topbar">` insert before `#btnMode`:

```html
      <button id="btnReport" class="icon-btn" title="Report a problem or suggest an idea" aria-label="Report a problem or suggest an idea"><svg class="i"><use href="#i-chat"/></svg></button>
```

- [ ] **Step 3: Dialog.** Insert after the closing `</dialog>` of `#updateDlg`:

```html
  <dialog id="reportDlg">
    <form method="dialog" class="settings report">
      <div class="report-head">
        <h2>Feedback</h2>
        <div class="tabs">
          <button type="button" class="tab is-on" data-tab="new">New report</button>
          <button type="button" class="tab" data-tab="mine">My reports</button>
        </div>
      </div>
      <div id="repNew" class="rep-pane">
        <div class="kind-row">
          <button type="button" class="kind is-on" data-kind="bug">Bug</button>
          <button type="button" class="kind" data-kind="idea">Idea</button>
        </div>
        <label class="field-col"><span>Title</span><input id="repTitle" type="text" maxlength="120" spellcheck="true" placeholder="Short summary, e.g. Carrack interior has no textures"></label>
        <label class="field-col"><span>Details <em>what happened, or what you would like</em></span><textarea id="repText" rows="6" maxlength="8000" placeholder="Steps to reproduce, what you expected, what you saw…"></textarea></label>
        <label class="switch"><input id="repPicture" type="checkbox" checked><span class="track"></span><span>Attach a picture of the 3D view</span></label>
        <label class="switch"><input id="repDetails" type="checkbox" checked><span class="track"></span><span>Attach technical details (version, system, graphics card, log)</span></label>
        <details id="repPreviewBox" class="rep-preview"><summary>What will be sent</summary><pre id="repPreview"></pre></details>
        <p class="hint">Reports and pictures are public on GitHub. Personal folders and names are removed.</p>
        <p id="repError" class="rep-error hidden"></p>
        <div class="dialog-actions">
          <button id="repFallback" type="button" class="link-btn skip hidden">Open on GitHub instead</button>
          <button value="cancel" class="ghost">Cancel</button>
          <button id="repSend" type="button" class="primary" disabled>Send</button>
        </div>
      </div>
      <div id="repMine" class="rep-pane hidden">
        <ul id="repList" class="rep-list"></ul>
        <p id="repMineNote" class="hint"></p>
        <div class="dialog-actions"><button value="close" class="ghost">Close</button></div>
      </div>
    </form>
  </dialog>
```

The dialog must be in the HTML at load time: the switch sync code at the top of `app.js` only wires switches that exist then.

- [ ] **Step 4: Styles.** Append after `.version-line.missing { ... }` (the textarea copies `input[type=text]`, line 105):

```css
/* feedback (reports) */
textarea {
  width: 100%; min-height: 110px; resize: vertical; padding: 8px 10px; font: inherit; font-size: 13px; color: var(--text);
  background: var(--input-bg); border: 1px solid var(--input-border); border-radius: 11px; outline: none;
  transition: border-color .15s, box-shadow .15s;
}
textarea:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--focus-ring); }
textarea::placeholder { color: var(--faint); }
.report-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.report-head h2 { margin: 0; }
.tabs, .kind-row { display: flex; gap: 4px; }
.tab, .kind {
  padding: 5px 12px; border: 0; border-radius: 10px; background: transparent; color: var(--muted); font-size: 12.5px;
  transition: background .15s, color .15s;
}
.tab:hover, .kind:hover { color: var(--text); }
.tab.is-on, .kind.is-on { background: var(--accent-soft); color: var(--accent-text); }
.rep-pane { display: flex; flex-direction: column; gap: 14px; }
.rep-preview summary { cursor: pointer; font-size: 12px; color: var(--muted); }
.rep-preview pre {
  max-height: 220px; overflow: auto; margin: 8px 0 0; padding: 10px; border-radius: 10px; white-space: pre-wrap;
  word-break: break-word; font: 11px/1.45 var(--mono); color: var(--text-2); background: color-mix(in srgb, var(--text) 5%, transparent);
}
.rep-error { margin: 0; font-size: 12px; color: var(--err); }
.rep-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; max-height: 320px; overflow-y: auto; }
.rep-item {
  display: grid; grid-template-columns: auto 1fr auto; gap: 2px 10px; width: 100%; padding: 8px 10px; border: 0; border-radius: 12px;
  background: transparent; color: var(--text); text-align: left;
}
.rep-item:hover { background: color-mix(in srgb, var(--text) 6%, transparent); }
.rep-num { font-variant-numeric: tabular-nums; color: var(--muted); }
.rep-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rep-state { font-size: 11.5px; font-weight: 600; color: var(--muted); }
.rep-state.open { color: var(--ok); }
.rep-state.closed { color: var(--accent-text); }
.rep-meta { grid-column: 2 / 4; font-size: 11.5px; color: var(--faint); }
```

- [ ] **Step 5: Commit** `git add web/index.html web/style.css && git commit -m "Feedback dialog: button in the top bar, new report and my reports tabs"`

### Task 10: Feedback dialog behaviour

**Files:** Modify `web/app.js` (new section right after the Settings code: after the `$("#cfgSave").addEventListener(...)` block and the `showBlender` function)

- [ ] **Step 1: Add the code:**

```js
// ---------------------------------------------------------------- feedback: reports become public GitHub issues
// The server builds the text (and removes personal data); here: the form, the picture of the view, the list.
const rep = { kind: "bug", timer: 0 };
const JSON_POST = (body) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function gpuName() {
  try {
    const gl = renderer.getContext();
    const ext = gl.getExtension("WEBGL_debug_renderer_info");
    return String(gl.getParameter(ext ? ext.UNMASKED_RENDERER_WEBGL : gl.RENDERER));
  } catch { return ""; }
}

function reportFields() {
  return { kind: rep.kind, title: $("#repTitle").value.trim(), description: $("#repText").value.trim(),
    picture: $("#repPicture").checked, details: $("#repDetails").checked,
    model: state.current?.path || null, variant: state.variant ?? null, gpu: gpuName() };
}

// the 3D view as a JPEG in base64 (no "data:" prefix), at most 2 MB; transparent parts get the page background
function viewPicture() {
  const src = renderer.domElement;
  const bg = getComputedStyle(document.body).backgroundColor || "#10141b";
  for (const [side, quality] of [[1600, 0.85], [1200, 0.75], [900, 0.7]]) {
    const k = Math.min(1, side / Math.max(src.width, src.height));
    const c = document.createElement("canvas");
    c.width = Math.max(1, Math.round(src.width * k));
    c.height = Math.max(1, Math.round(src.height * k));
    const g = c.getContext("2d");
    g.fillStyle = bg;
    g.fillRect(0, 0, c.width, c.height);
    g.drawImage(src, 0, 0, c.width, c.height);
    const b64 = c.toDataURL("image/jpeg", quality).split(",")[1];
    if (b64.length * 0.75 <= 2_000_000) return b64;
  }
  return null;
}

function reportReady() {
  const f = reportFields();
  $("#repSend").disabled = f.title.length < 4 || f.description.length < 10;
}

async function refreshPreview() {
  if (!$("#repPreviewBox").open) return;
  try {
    const c = await (await api("/api/report/preview", JSON_POST(reportFields()))).json();
    $("#repPreview").textContent = `${c.title}\n\n${c.body.replace("<!-- screenshot -->", "[picture of the 3D view]")}`;
  } catch (e) { $("#repPreview").textContent = e.message; }
}

function reportChanged() {
  reportReady();
  clearTimeout(rep.timer);
  rep.timer = setTimeout(refreshPreview, 400);
}

function showReportError(text, offerGitHub = false) {
  $("#repError").textContent = text;
  $("#repError").classList.toggle("hidden", !text);
  $("#repFallback").classList.toggle("hidden", !offerGitHub);
}

const REPORT_ERRORS = {
  rate: () => "Too many reports from this connection, try again in a few minutes.",
  invalid: (detail) => detail || "The report was not accepted.",
  unavailable: () => "The report service is not available right now.",
  network: () => "No connection to the report service.",
};

async function loadMyReports() {
  const list = $("#repList");
  list.replaceChildren();
  $("#repMineNote").textContent = "Loading…";
  try {
    const { reports } = await (await api("/api/report/mine")).json();
    const STATES = { open: "Open", closed: "Closed", removed: "Removed" };
    for (const r of reports) {
      const comments = r.comments ? `${r.comments} comment${r.comments === 1 ? "" : "s"} · ` : "";
      const btn = el("button", "rep-item");
      btn.type = "button";
      btn.append(el("span", "rep-num", `#${r.number}`), el("span", "rep-title", r.title),
        el("span", `rep-state ${r.state || ""}`, STATES[r.state] || ""), el("span", "rep-meta", comments + r.date));
      btn.addEventListener("click", () => api("/api/report/open", JSON_POST({ number: r.number })).catch((e) => toast(e.message, true)));
      const li = el("li");
      li.append(btn);
      list.append(li);
    }
    $("#repMineNote").textContent = !reports.length ? "No reports sent from this computer yet."
      : reports.some((r) => r.state == null) ? "Status unavailable right now: GitHub limits how often it can be checked."
        : "Click a report to open it on GitHub.";
  } catch (e) { $("#repMineNote").textContent = e.message; }
}

function showReportTab(tab) {
  document.querySelectorAll("#reportDlg .tab").forEach((b) => b.classList.toggle("is-on", b.dataset.tab === tab));
  $("#repNew").classList.toggle("hidden", tab !== "new");
  $("#repMine").classList.toggle("hidden", tab !== "mine");
  if (tab === "mine") loadMyReports();
}

$("#btnReport").addEventListener("click", () => {
  showReportTab("new");
  reportReady();
  $("#reportDlg").showModal();
});
document.querySelectorAll("#reportDlg .tab").forEach((b) => b.addEventListener("click", () => showReportTab(b.dataset.tab)));
document.querySelectorAll("#reportDlg .kind").forEach((b) => b.addEventListener("click", () => {
  rep.kind = b.dataset.kind;
  document.querySelectorAll("#reportDlg .kind").forEach((k) => k.classList.toggle("is-on", k === b));
  reportChanged();
}));
for (const id of ["#repTitle", "#repText"]) $(id).addEventListener("input", reportChanged);
for (const id of ["#repPicture", "#repDetails"]) $(id).addEventListener("change", reportChanged);
$("#repPreviewBox").addEventListener("toggle", refreshPreview);
// Enter in the title would submit the dialog's form and close it
$("#repTitle").addEventListener("keydown", (e) => { if (e.key === "Enter") e.preventDefault(); });

$("#repSend").addEventListener("click", async () => {
  const f = reportFields();
  if (f.picture) f.screenshot = viewPicture();
  const btn = $("#repSend");
  showReportError("");
  btn.disabled = true;
  btn.textContent = "Sending…";
  try {
    const r = await fetch("/api/report", JSON_POST(f));
    const out = await r.json().catch(() => ({ kind: "unavailable" }));
    if (!r.ok) throw out;
    toast(`Report #${out.number} sent, thank you`);
    $("#repTitle").value = "";
    $("#repText").value = "";
    showReportTab("mine");
  } catch (e) {
    const kind = REPORT_ERRORS[e?.kind] ? e.kind : "network";
    showReportError(REPORT_ERRORS[kind](e?.detail), kind === "network" || kind === "unavailable");
  } finally {
    btn.textContent = "Send";
    reportReady();
  }
});

$("#repFallback").addEventListener("click", () =>
  api("/api/report/open", JSON_POST({ fallback: reportFields() })).catch((e) => toast(e.message, true)));
```

This code reuses helpers already in `app.js`: `el(tag, cls, text)` (near line 804, creates an element with class and text), `toast` (line 135), `renderer` (line 146), `state`, `api`. Do not define `el` again (a second declaration is a syntax error in a module).

- [ ] **Step 2: Check it in the dev preview** (`verseforge-dev`, port 8767, configuration in `Star Citizen Workshop/.claude/launch.json`). The service is not online yet, so sending fails, which is expected here. Check:
  - the chat button is in the top bar; clicking it opens the dialog on "New report";
  - Send stays disabled until the title has 4 characters and the details 10;
  - "What will be sent" shows `[Bug] <title>`, the text, `[picture of the 3D view]` and the technical details with `<home>` in place of the user folder (open a model first: the "Model:" line appears);
  - Send shows "No connection..." or "not available" and the "Open on GitHub instead" button; the typed text stays;
  - "My reports" shows "No reports sent from this computer yet.";
  - light and dark appearance both readable; no errors in the console.
  The dev server uses the real `config.json`: do not send against a working service in this step.
- [ ] **Step 3:** Run `python -m pytest tests -q`: all pass.
- [ ] **Step 4: Commit** `git add web/app.js && git commit -m "Feedback dialog: preview of what is sent, picture of the 3D view, errors with GitHub's form as fallback, list of my reports"`

---

## Chunk 5: Going online (main session with the user, not a subagent)

These steps touch the user's GitHub and Vercel accounts. Each one that creates or changes something outside this repo is confirmed with the user first. The assistant never sees or types the private key.

### Task 11: GitHub App and label

- [ ] **Step 1:** Create the label (ask first): `gh label create from-app -R Pier144/VerseForge --color 0a84ff --description "Sent from the VerseForge app"`.
- [ ] **Step 2:** Give the user the prefilled registration link (GitHub reads these parameters); they press "Create GitHub App":
  `https://github.com/settings/apps/new?name=VerseForge%20Reports&description=Opens%20the%20reports%20sent%20from%20the%20VerseForge%20app&url=https%3A%2F%2Fgithub.com%2FPier144%2FVerseForge&public=false&webhook_active=false&issues=write&metadata=read`
  If the name is taken they choose another (e.g. "VerseForge Reports Bot").
- [ ] **Step 3:** The user generates a private key (a .pem file downloads) and installs the app only on `Pier144/VerseForge`, then tells the assistant the App ID (a number on the app page, not secret).

### Task 12: Vercel project, Blob, variables, firewall

- [ ] **Step 1:** With the Vercel connector (team `pier144s-projects`), check whether Vercel can see `Pier144/VerseForge` through its GitHub integration. If yes, create project `verseforge-reports` linked to the repo, root directory `reports-service`, framework "Other". If not, ask the user to connect GitHub in Vercel, or deploy from `reports-service/` with `npx vercel deploy --prod` after the user logs in.
- [ ] **Step 2:** Create a Blob store `verseforge-reports` and connect it to the project (sets `BLOB_READ_WRITE_TOKEN`).
- [ ] **Step 3:** Set the Production variables `GH_APP_ID=<id>`, `REPORTS_REPO=Pier144/VerseForge`, `REPORTS_ENABLED=1`, `REPORTS_PER_HOUR=20`. The user pastes `GH_APP_PRIVATE_KEY` (the whole .pem content) in Vercel, Project, Settings, Environment Variables.
- [ ] **Step 4:** Firewall rule on the project: path starts with `/api/report`, rate limit 5 requests per 600 s per IP, action deny. If the Hobby plan does not accept it, write that in `reports-service/README.md` and rely on the hourly cap.
- [ ] **Step 5:** Deploy to production. If the address is not `https://verseforge-reports.vercel.app/api/report`, change `SERVICE_URL` in `sc_explorer/reports.py`, run the tests and commit.
- [ ] **Step 6: Smoke test without creating an issue:** a POST with `{}` and a curl user agent answers 403; with `-A "VerseForge/1.14.0"` it answers 400 "Unknown report type"; a GET answers 405.

### Task 13: Real end-to-end report (with the user's permission)

- [ ] **Step 1:** Ask the user: a test report will be sent from the dev app and will be **public** on VerseForge (title "Test report from the VerseForge app, please ignore"). Wait for a yes.
- [ ] **Step 2:** In the dev preview, with a model open: fill in the form with picture and details on, Send. Expected: toast "Report #N sent", "My reports" lists it as Open.
- [ ] **Step 3:** Check the issue (`gh issue view N -R Pier144/VerseForge --json author,labels,body`): author is the app bot, labels `from-app` and `bug`, picture visible, technical details folded, no Windows user name or PC name anywhere in the body.
- [ ] **Step 4:** Close it with a comment and delete its picture from the Blob store (ask first): `gh issue close N -R Pier144/VerseForge -c "Test of the in-app reports, closed."`.
- [ ] **Step 5:** Final checks: `python -m pytest tests -q` and `node --test` in `reports-service/` both pass. Update the memory note `verseforge-segnalazioni.md` (App ID, not the key; Vercel project name and address). Releasing 1.14.0 waits for the user's request.
