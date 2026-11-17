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
    assert client.get("/api/report/mine").json() == {"news": 1, "reports": [
        {"number": 7, "title": "[Bug] x", "date": "2026-11-16", "state": "closed", "comments": 2, "new": True},
        {"number": 3, "title": "[Idea] y", "date": "2026-11-15", "state": None, "comments": None, "new": False}]}


def test_seen_clears_the_news(client, monkeypatch):
    server.state.cfg["reports"] = [{"number": 7, "title": "[Bug] x", "date": "2026-11-16"}]
    monkeypatch.setattr(reports, "statuses", lambda numbers: {7: {"state": "open", "comments": 4}})
    assert client.get("/api/report/mine").json()["news"] == 1
    assert client.post("/api/report/seen").status_code == 200
    assert client.get("/api/report/mine").json()["news"] == 0
    assert server.state.cfg["reports"][0]["seen_comments"] == 4


def test_open_only_builds_github_addresses(client, monkeypatch):
    opened = []
    monkeypatch.setattr(server.paths, "open_path", opened.append)
    assert client.post("/api/report/open", json={"number": 7}).status_code == 200
    assert client.post("/api/report/open", json={"fallback": FIELDS}).status_code == 200
    assert opened[0] == "https://github.com/Pier144/VerseForge/issues/7"
    assert opened[1].startswith("https://github.com/Pier144/VerseForge/issues/new?")
    assert client.post("/api/report/open", json={}).status_code == 400
    assert client.post("/api/report/open", json={"number": -1}).status_code == 400


def test_posts_from_other_pages_are_refused(client):
    url = "/api/report/preview"
    assert client.post(url, json=FIELDS, headers={"Origin": "https://evil.example"}).status_code == 403
    # DNS rebinding: a foreign name that points at 127.0.0.1 sends a matching Origin and Host
    assert client.post(url, json=FIELDS, headers={"Origin": "http://evil.example:8767",
                                                  "Host": "evil.example:8767"}).status_code == 403
    assert client.post(url, json=FIELDS, headers={"Origin": "http://127.0.0.1:8767",
                                                  "Host": "127.0.0.1:8767"}).status_code == 200
    assert client.post(url, json=FIELDS).status_code == 200          # no Origin: not a web page


def test_issue_number_kept_even_if_settings_cannot_be_saved(client, monkeypatch):
    def broken(cfg):
        raise PermissionError("config.json is read-only")

    monkeypatch.setattr(server, "save_config", broken)
    monkeypatch.setattr(reports, "send", lambda composed, kind, shot=None, **kw: {"number": 9, "url": reports.ISSUE_PAGE + "9"})
    assert client.post("/api/report", json=FIELDS).json()["number"] == 9
