"""Where VerseForge looks for Data.p4k and keeps its files on Linux (fake home folder: runs on any system)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sc_explorer import paths  # noqa: E402


def _linux_home(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "WINDOWS", False)
    monkeypatch.setattr(paths, "HOME", str(tmp_path))
    monkeypatch.setattr(paths, "WSL_ROOTS", [])          # the real game may be installed on this PC
    for var in ("HOME", "USERPROFILE"):                   # expanduser reads USERPROFILE on Windows
        monkeypatch.setenv(var, str(tmp_path))
    for var in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def _game(prefix, channel="LIVE", sub="Program Files"):
    d = prefix / "drive_c" / sub / "Roberts Space Industries" / "StarCitizen" / channel
    d.mkdir(parents=True)
    (d / "Data.p4k").write_bytes(b"")
    return str(d / "Data.p4k")


def test_xdg_folders(monkeypatch, tmp_path):
    home = _linux_home(monkeypatch, tmp_path)
    assert paths.data_dir() == os.path.join(str(home), ".config", "VerseForge")
    assert paths.cache_dir() == os.path.join(str(home), ".cache", "VerseForge")
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / "c"))
    assert paths.cache_dir() == os.path.join(str(home / "c"), "VerseForge")
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/ignored")          # the XDG spec: relative paths are invalid
    assert paths.data_dir() == os.path.join(str(home), ".config", "VerseForge")


def test_documents_folder_follows_user_dirs(monkeypatch, tmp_path):
    home = _linux_home(monkeypatch, tmp_path)
    assert paths.documents_dir() == os.path.join(str(home), "Documents", "VerseForge")
    (home / ".config").mkdir()
    (home / ".config" / "user-dirs.dirs").write_text('XDG_DOCUMENTS_DIR="$HOME/Documenti"\n', encoding="utf-8")
    assert os.path.normpath(paths.documents_dir()) == os.path.normpath(os.path.join(str(home), "Documenti", "VerseForge"))


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need extra rights on Windows")
def test_broken_documents_link(monkeypatch, tmp_path):
    home = _linux_home(monkeypatch, tmp_path)
    os.symlink(str(home / "missing" / "Documents"), str(home / "Documents"))
    assert paths.documents_dir() == os.path.join(str(home), "VerseForge")


def test_finds_the_game_in_a_lutris_prefix(monkeypatch, tmp_path):
    home = _linux_home(monkeypatch, tmp_path)
    assert paths.find_p4k().endswith(os.path.join("star-citizen", "drive_c", "Program Files", "Roberts Space Industries",
                                                  "StarCitizen", "LIVE", "Data.p4k"))       # nothing installed: usual place
    p4k = _game(home / "Games" / "star-citizen")
    assert os.path.realpath(paths.find_p4k()) == os.path.realpath(p4k)


def test_bottles_and_live_before_ptu(monkeypatch, tmp_path):
    home = _linux_home(monkeypatch, tmp_path)
    bottle = home / ".local" / "share" / "bottles" / "bottles" / "StarCitizen"
    _game(bottle, "PTU")
    live = _game(home / ".wine", "LIVE", sub="Games")     # another prefix and folder, but the LIVE channel wins
    assert os.path.realpath(paths.find_p4k()) == os.path.realpath(live)


def test_child_env_restores_the_system_libraries(monkeypatch):
    monkeypatch.setattr(paths, "WINDOWS", False)
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEIxyz")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/local/lib")
    monkeypatch.setenv("QTWEBENGINE_CHROMIUM_FLAGS", "--ignore-gpu-blocklist")
    env = paths.child_env()
    assert env["LD_LIBRARY_PATH"] == "/usr/local/lib" and "LD_LIBRARY_PATH_ORIG" not in env
    assert "QTWEBENGINE_CHROMIUM_FLAGS" not in env
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG")
    assert "LD_LIBRARY_PATH" not in paths.child_env()
