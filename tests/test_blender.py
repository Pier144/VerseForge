"""Finding Blender: the path typed in the settings (program or its folder) and the installed programs list on Windows."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sc_explorer import printing  # noqa: E402

EXE = printing.BLENDER_EXE


def _install(folder):
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / EXE
    exe.write_bytes(b"")
    return str(exe)


def test_setting_with_the_program(tmp_path):
    exe = _install(tmp_path / "Blender 4.4")
    assert printing.from_setting(exe) == exe


def test_setting_with_the_folder(tmp_path):
    exe = _install(tmp_path / "Blender 4.4")
    assert printing.from_setting(str(tmp_path / "Blender 4.4")) == exe
    assert printing.from_setting(str(tmp_path / "Blender 4.4") + os.sep) == exe


def test_setting_with_the_parent_folder_takes_the_newest(tmp_path):
    _install(tmp_path / "Blender Foundation" / "Blender 3.6")
    newest = _install(tmp_path / "Blender Foundation" / "Blender 4.4")
    assert printing.from_setting(str(tmp_path / "Blender Foundation")) == newest


def test_setting_pasted_with_quotes_and_spaces(tmp_path):
    exe = _install(tmp_path / "Blender 4.4")
    assert printing.from_setting(f'  "{exe}"  ') == exe      # Windows "Copy as path" adds the quotes


def test_setting_that_points_nowhere(tmp_path):
    assert printing.from_setting(str(tmp_path / "missing")) is None
    assert printing.from_setting("") is None
    assert printing.from_setting(None) is None


def test_installed_programs_pick_the_newest_blender(tmp_path):
    old = str(tmp_path / "old")
    new = str(tmp_path / "Programmi" / "Blender 4.4")
    _install(tmp_path / "old")
    _install(tmp_path / "Programmi" / "Blender 4.4")
    entries = [("Blender", "3.6.2", old + os.sep), ("Blender", "4.4.0", new + os.sep),
               ("Blender Launcher", "2.0", str(tmp_path / "nothing-here")), ("GIMP", "2.10", new)]
    assert printing.pick_installed(entries) == os.path.join(new, EXE)


def test_installed_programs_without_blender(tmp_path):
    assert printing.pick_installed([("GIMP", "2.10", str(tmp_path))]) is None
    assert printing.pick_installed([("Blender", "4.4", "")]) is None


def test_find_blender_prefers_the_setting(tmp_path, monkeypatch):
    exe = _install(tmp_path / "Blender 4.4")
    monkeypatch.setattr(printing, "_installed_programs", lambda: [])
    assert printing.find_blender(str(tmp_path / "Blender 4.4")) == exe
