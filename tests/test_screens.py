"""MFD graphics sets for the ship screens (screens.py) and the monitor flag on screen materials."""
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sc_explorer import materials, screens  # noqa: E402


class Archive:
    def __init__(self, missing=()):
        self.missing = missing

    def exists(self, path):
        return not any(m in path for m in self.missing)


def test_maker_with_its_own_set():
    kit = screens.kit_for(Archive(), "Objects/Spaceships/Ships/AEGS/Gladius/AEGS_Gladius.cga")
    assert kit["name"] == "aegs" and kit["own"] and kit["accent"]
    assert all("/mfd/aegs/" in kit[k] for k in ("bg", "tri_fill", "tri_frame", "panel"))


def test_missing_pieces_come_from_the_generic_set():
    kit = screens.kit_for(Archive(), "objects/spaceships/ships/anvl/hornet/anvl_hornet.cga")
    assert kit["name"] == "anvl" and "/mfd/anvl/" in kit["bg"] and "/pu generic/" in kit["tri_frame"]
    kit = screens.kit_for(Archive(), "objects/spaceships/ships/rsi/perseus/exterior/rsi_perseus.cga")
    assert kit["name"] == "generic" and not kit["own"] and kit["accent"] is None and "/pu generic/" in kit["bg"]


def test_pieces_the_game_files_lack_are_none():
    kit = screens.kit_for(Archive(missing=("triangle",)), "objects/spaceships/ships/drak/cutlass/drak_cutlass.cga")
    assert kit["tri_fill"] is None and kit["tri_frame"] is None and kit["bg"]


def _screen(texture):
    el = ET.fromstring(f'<Material Name="RTT_Screen" Shader="DisplayScreen"><Textures>'
                       f'<Texture Map="TexSlot9" File="{texture}"/></Textures></Material>')
    return materials._material(el)


def test_only_live_drawn_screens_are_monitors():
    assert _screen("$RenderToTexture").rtt
    assert not _screen("textures/vehicles/manufacturer/crus/crus_glasslights_glow.tif").rtt
