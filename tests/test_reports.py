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
    fake["status"], fake["body"] = status, {"error": "The title must be 4 to 130 characters"}
    with pytest.raises(reports.ReportError) as e:
        reports.send(_short(), "bug", url=fake["url"])
    assert e.value.kind == kind
    if status == 400:
        assert e.value.message == "The title must be 4 to 130 characters"


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


def _issue_answers(listed, single):
    """Fake GitHub: the issue list (one request for all reports) and single issues for the ones not listed."""
    def answer(path):
        if "?" in path:
            page = int(urllib.parse.parse_qs(path.split("?", 1)[1]).get("page", ["1"])[0])
            return (200, listed if page == 1 else [])
        return single[int(path.rsplit("/", 1)[1])]
    return answer


def test_statuses_in_one_request(fake):
    fake["status"] = _issue_answers(
        [{"number": 1, "state": "open", "comments": 3}, {"number": 2, "state": "closed", "comments": 0},
         {"number": 9, "state": "open", "comments": 0},                          # someone else's report
         {"number": 5, "state": "open", "comments": 0, "pull_request": {}}],     # not an issue
        {3: (404, {}), 4: (410, {})})
    reports._status_cache.clear()
    api = fake["url"] + "/issues/"
    assert reports.statuses([1, 2, 3, 4], api=api) == {
        1: {"state": "open", "comments": 3}, 2: {"state": "closed", "comments": 0},
        3: {"state": "removed", "comments": 0}, 4: {"state": "removed", "comments": 0}}
    first = fake["seen"][0]["path"]
    assert first.startswith("/issues?") and "labels=from-app" in first and "state=all" in first
    assert len(fake["seen"]) == 3                            # the list, then the two missing ones
    reports.statuses([1, 2], api=api)
    assert len(fake["seen"]) == 3                            # the second time it comes from memory


def test_statuses_stop_when_the_public_limit_is_used_up(fake):
    fake["status"], fake["body"] = 403, {"message": "API rate limit exceeded"}
    reports._status_cache.clear()
    assert reports.statuses([7, 8], api=fake["url"] + "/issues/") == {}
    assert len(fake["seen"]) == 1


def _link_parts(url):
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    return q["title"][0], q["body"][0]


def test_fallback_url_non_ascii_text_keeps_a_body():
    c = reports.compose("bug", "Title here", "漢" * 5000, "", False, "1.0.0")
    u = reports.fallback_url(c)
    assert len(u) <= reports.MAX_URL
    body = _link_parts(u)[1]
    assert body.startswith("漢" * 100) and "did not fit" in body


def test_fallback_url_huge_title_ends():
    out = []
    t = threading.Thread(target=lambda: out.append(reports.fallback_url({"title": "x" * 10000, "body": "y" * 9000})),
                         daemon=True)
    t.start()
    t.join(10)
    assert out, "fallback_url did not end"
    assert len(out[0]) <= reports.MAX_URL
    title, body = _link_parts(out[0])
    assert title == "x" * 130 and body.startswith("y")


def test_fallback_url_drops_details_before_cutting_the_description():
    c = reports.compose("bug", "Title here", "a" * 2000, "log line\n" * 500, False, "1.0.0")
    body = _link_parts(reports.fallback_url(c))[1]
    assert "a" * 2000 in body
    assert "technical details left out" in body and "log line" not in body and "did not fit" not in body


def test_compose_drops_the_oldest_log_lines_when_too_long():
    log = [f"{i:03d} " + "x" * 296 for i in range(80)]
    details = "\n".join(["VerseForge 1.14.0", "System: Windows", "", "Last 80 log lines:", *log])
    body = reports.compose("bug", "Title here", "d" * 8000, details, False, "1.0.0")["body"]
    assert len(body) <= reports.MAX_BODY < 20000
    assert body.startswith("d" * 8000) and "System: Windows" in body
    assert log[-1] in body and log[0] not in body
    kept = sum(1 for line in log if line in body)
    assert f"Last {kept} log lines:" in body                 # the count follows the lines that are left
    assert body.endswith("<sub>Sent from VerseForge 1.0.0</sub>")


def test_compose_cuts_details_without_log_lines_when_too_long():
    body = reports.compose("bug", "Title here", "d" * 8000, "z" * 30000, False, "1.0.0")["body"]
    assert len(body) <= reports.MAX_BODY
    assert body.startswith("d" * 8000) and "zzz" in body and body.endswith("</sub>")


def test_compose_closes_an_unclosed_fence():
    body = reports.compose("bug", "Title here", "look:\n  ```\ncode here", "", False, "1.0.0")["body"]
    assert "code here\n```" in body
    even = reports.compose("bug", "Title here", "```\ncode\n```", "", False, "1.0.0")["body"]
    assert even.startswith("```\ncode\n```\n\n")


def test_compose_neutralises_raw_html_blocks():
    text = "a <pre> b </PRE> c <textarea> d <style> e </script> f <script>"
    body = reports.compose("bug", "Title here", text, "", False, "1.0.0")["body"]
    for tag in ("<pre>", "</PRE>", "<textarea>", "<style>", "</script>", "<script>"):
        assert tag not in body
    assert "&lt;pre>" in body and "&lt;/PRE>" in body and "&lt;/script>" in body


def test_compose_breaks_html_comments_in_details():
    body = reports.compose("bug", "Title here", "Some text here", "log <!-- screenshot --> end", True, "1.0.0")["body"]
    assert body.count(reports.PICTURE) == 1
    assert body.index(reports.PICTURE) < body.index("<details>")
    assert "<!\u200b-- screenshot -->" in body


def test_anonymize_url_encoded_paths_and_names():
    text = "file:///C%3A%5CUsers%5CMario%20Rossi%5Cx.glb c%3a%5cusers%5cmario%20rossi by Mario%20Rossi"
    out = reports.anonymize(text, home=r"C:\Users\Mario Rossi", user="Mario Rossi", machine="")
    assert out == "file:///<home>%5Cx.glb <home> by <user>"


def test_anonymize_onedrive_for_business():
    text = r"saved <home>\OneDrive - Contoso Ltd\Documents\a.glb and /OneDrive - Acme S.p.A./b and OneDrive - Org"
    assert reports.anonymize(text) == r"saved <home>\OneDrive\Documents\a.glb and /OneDrive/b and OneDrive"


def test_system_folders_elsewhere(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert reports.system_folders() == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_system_folders_on_windows():
    out = reports.system_folders()
    assert isinstance(out, list)
    for folder, tag in out:
        assert isinstance(folder, str) and folder and tag in ("<home>", "<temp>")
        assert folder != os.path.expanduser("~")


def test_user_folders_game_at_the_drive_root():
    assert reports.user_folders({"p4k_path": r"D:\Mario\Data.p4k"}) == [(r"D:\Mario", "<game>")]
    assert reports.user_folders({"p4k_path": "/games/Data.p4k"}) == [("/games", "<game>")]
    assert reports.user_folders({"p4k_path": r"D:\Data.p4k"}) == []


def test_send_broken_answer_is_network(monkeypatch):
    import http.client

    def broken(*a, **k):
        raise http.client.IncompleteRead(b"")
    monkeypatch.setattr(reports.urllib.request, "urlopen", broken)
    with pytest.raises(reports.ReportError) as e:
        reports.send(_short(), "bug", url="http://127.0.0.1:9/")
    assert e.value.kind == "network"


@pytest.mark.parametrize("status", [400, 413])
def test_send_refused_without_reason(fake, status):
    fake["status"], fake["body"] = status, {}
    with pytest.raises(reports.ReportError) as e:
        reports.send(_short(), "bug", url=fake["url"])
    assert e.value.kind == "invalid" and e.value.message == "The report was not accepted"


def test_hand_edited_reports_in_config(fake):
    cfg = {"reports": [{"number": None}, "junk", {"number": 3, "title": "x", "date": "2026-11-16"}]}
    assert reports.mine(cfg) == [{"number": 3, "title": "x", "date": "2026-11-16"}]
    reports.remember(cfg, 4, "y")
    assert [r["number"] for r in cfg["reports"]] == [4, 3]
    fake["status"] = _issue_answers([{"number": 3, "state": "open", "comments": 0}, {"state": "open"}, "junk"], {})
    reports._status_cache.clear()
    out = reports.statuses([None, "junk", -1, 0, True, 3], api=fake["url"] + "/issues/")
    assert out == {3: {"state": "open", "comments": 0}}
    assert len(fake["seen"]) == 1


def test_with_news_flags_changes_since_last_look():
    items = [{"number": 1, "title": "a"},                                             # never looked: open, 0 comments
             {"number": 2, "title": "b", "seen_state": "open", "seen_comments": 2},
             {"number": 3, "title": "c", "seen_state": "closed", "seen_comments": 1},
             {"number": 4, "title": "d"}]
    known = {1: {"state": "open", "comments": 1}, 2: {"state": "open", "comments": 2},
             3: {"state": "closed", "comments": 1}}                                    # 4: status unknown
    out = {r["number"]: r for r in reports.with_news(items, known)}
    assert out[1]["new"] and not out[2]["new"] and not out[3]["new"] and not out[4]["new"]
    assert [out[n]["news"] for n in (1, 2, 3, 4)] == [1, 0, 0, 0]
    assert out[4]["state"] is None and out[1]["comments"] == 1
    assert reports.with_news([{"number": 5, "title": "e"}], {5: {"state": "closed", "comments": 0}})[0]["new"]


def test_mark_seen_keeps_the_status_in_the_settings():
    cfg = {"reports": [{"number": 1, "title": "a"}, {"number": 2, "title": "b"}, "junk"]}
    reports.mark_seen(cfg, {1: {"state": "closed", "comments": 3}})
    assert cfg["reports"][0] == {"number": 1, "title": "a", "seen_state": "closed", "seen_comments": 3}
    assert cfg["reports"][1] == {"number": 2, "title": "b"}                           # unknown status: untouched
    assert not reports.with_news(reports.mine(cfg), {1: {"state": "closed", "comments": 3}})[0]["new"]


def test_news_counts_each_new_comment_and_the_change_of_state():
    items = [{"number": 1, "title": "a", "seen_state": "open", "seen_comments": 1}]
    out = reports.with_news(items, {1: {"state": "closed", "comments": 4}})[0]
    assert out["new"] and out["news"] == 4                  # 3 new comments + closed
    assert reports.with_news(items, {1: {"state": "open", "comments": 0}})[0]["news"] == 0   # a comment was deleted
