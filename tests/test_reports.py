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
