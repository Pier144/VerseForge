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


def _windows(monkeypatch, tmp_path):
    """A made-up Windows PC: two "disks" (folders) and its own %APPDATA%."""
    monkeypatch.setattr(paths, "WINDOWS", True)
    c, d = tmp_path / "C", tmp_path / "D"
    c.mkdir(), d.mkdir()
    monkeypatch.setattr(paths, "windows_drives", lambda: [str(c), str(d)])
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    return c, d


def _windows_game(root, channel="LIVE"):
    folder = root / "StarCitizen" / channel
    folder.mkdir(parents=True)
    (folder / "Data.p4k").write_bytes(b"")
    return str(folder / "Data.p4k")


def test_windows_game_found_on_another_disk(monkeypatch, tmp_path):
    c, d = _windows(monkeypatch, tmp_path)
    assert paths.find_p4k() == paths.WINDOWS_P4K                     # nothing anywhere: the usual place is shown
    ptu = _windows_game(c / "Program Files" / "Roberts Space Industries", "PTU")
    assert paths.find_p4k() == ptu
    live = _windows_game(d / "Games")                                # D:\Games\StarCitizen\LIVE: LIVE before any PTU
    assert paths.find_p4k() == live


def test_windows_game_found_from_the_launcher_log(monkeypatch, tmp_path):
    _windows(monkeypatch, tmp_path)
    game = _windows_game(tmp_path / "anywhere" / "My Games" / "RSI")
    logs = tmp_path / "appdata" / "rsilauncher" / "logs"
    logs.mkdir(parents=True)
    folder = os.path.dirname(game).replace("\\", "\\\\")             # the log is JSON: backslashes are doubled
    (logs / "log.log").write_text('{ "t":"1", "[main][info] ": "Launching Star Citizen LIVE from (%s)" }\n' % folder,
                                  encoding="utf-8")
    if os.name == "nt":                                               # the log holds drive paths: Windows only
        assert paths.find_p4k() == game


def test_resolve_p4k_takes_the_file_or_a_folder_above_it(tmp_path):
    game = _windows_game(tmp_path / "Roberts Space Industries")
    _windows_game(tmp_path / "Roberts Space Industries", "PTU")
    for typed in (game, os.path.dirname(game), str(tmp_path / "Roberts Space Industries" / "StarCitizen"),
                  str(tmp_path / "Roberts Space Industries"), str(tmp_path), f'"{game}"', f"  {game} "):
        assert paths.resolve_p4k(typed) == game, typed
    assert paths.resolve_p4k(str(tmp_path / "nowhere")) is None
    assert paths.resolve_p4k("") is None
    empty = tmp_path / "empty"
    empty.mkdir()
    assert paths.resolve_p4k(str(empty)) is None
