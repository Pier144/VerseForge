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
