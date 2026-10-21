"""Update check: version comparison and release parsing (no network, no installed game needed)."""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sc_explorer import updates  # noqa: E402


def test_parse_version():
    assert updates.parse_version("v1.3.0") == (1, 3, 0)
    assert updates.parse_version("1.10") == (1, 10)
    assert updates.parse_version("V2.0.1-beta") == (2, 0, 1)
    assert updates.parse_version("latest") is None
    assert updates.parse_version("") is None


def test_is_newer():
    assert updates.is_newer("1.4.0", "1.3.1")
    assert updates.is_newer("v1.10.0", "1.9.9")        # numeric, not alphabetical
    assert updates.is_newer("1.3.1", "1.3")
    assert not updates.is_newer("1.3.0", "1.3.0")
    assert not updates.is_newer("1.3", "1.3.0")
    assert not updates.is_newer("1.2.9", "1.3.0")
    assert not updates.is_newer("nightly", "1.3.0")


def _fake_release(monkeypatch, release):
    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(updates.urllib.request, "urlopen", lambda req, timeout=0: Resp(json.dumps(release).encode()))


def test_check_picks_the_installer(monkeypatch):
    dl = updates.DOWNLOAD_PREFIX + "v1.4.0/"
    _fake_release(monkeypatch, {
        "tag_name": "v1.4.0", "html_url": updates.RELEASES_PAGE + "/tag/v1.4.0", "body": "## What's new",
        "assets": [{"name": "01_search_and_view.mp4", "browser_download_url": dl + "01_search_and_view.mp4", "size": 1},
                   {"name": "VerseForge-1.4.0-Setup.exe", "browser_download_url": dl + "VerseForge-1.4.0-Setup.exe",
                    "size": 123, "digest": "sha256:abc"}]})
    u = updates.check("1.3.1")
    assert u["available"] and u["latest"] == "1.4.0"
    assert u["installer"] == {"name": "VerseForge-1.4.0-Setup.exe", "url": dl + "VerseForge-1.4.0-Setup.exe",
                              "size": 123, "digest": "sha256:abc"}


def test_check_ignores_foreign_downloads(monkeypatch):
    _fake_release(monkeypatch, {
        "tag_name": "v9.0.0", "html_url": "https://example.com/evil",
        "assets": [{"name": "VerseForge-9.0.0-Setup.exe", "browser_download_url": "https://example.com/x-Setup.exe"}]})
    u = updates.check("1.3.1")
    assert u["installer"] is None                       # never downloads from outside the project's releases
    assert u["page"] == updates.RELEASES_PAGE


def test_check_same_version(monkeypatch):
    _fake_release(monkeypatch, {"tag_name": "v1.3.1", "assets": []})
    assert not updates.check("1.3.1")["available"]
