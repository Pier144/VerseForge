"""The Values tab's answers (/api/values…) on the made-up DataCore of test_gamestats (no game needed)."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_gamestats as made_up  # noqa: E402

from sc_explorer import entities, gamestats, i18n, server  # noqa: E402


class _Archive:
    names = ["Data\\Game2.dcb"]

    def __init__(self, data):
        self.data = data

    def read(self, _name):
        return self.data


@pytest.fixture
def game(monkeypatch, tmp_path):
    data = made_up._datacore()
    st = server.state
    monkeypatch.setattr(st, "status", {"ready": True, "message": ("starting",), "progress": 1.0, "error": None})
    monkeypatch.setattr(st, "archive", _Archive(data))
    monkeypatch.setattr(st, "gamestats", gamestats.build(entities.open_index(data, made_up._read), made_up._read))
    monkeypatch.setattr(st, "loc", {"vehicle_nameanvl_hornet": "Anvil F7C Hornet", "item_namerifle": "P4-AR Rifle",
                                    "vehicle_focus_fighter": "Medium Fighter", "manufacturer_namebehr": "Behring"})
    monkeypatch.setitem(st.cfg, "export_dir", str(tmp_path))
    yield tmp_path
    i18n.set_language("en")


def _rows(record):
    return {r["id"]: r for g in record["groups"] for r in g["rows"]}


def test_values_of_a_model(game):
    got = server.values(made_up.HORNET)["records"]
    assert [(r["record"], r["name"], r["kind_label"]) for r in got] == [
        ("ANVL_Hornet", "Anvil F7C Hornet", "Ships"), ("ANVL_Hornet_Tracker", "Anvil F7C Hornet", "Ships")]
    assert [g["label"] for g in got[0]["groups"]] == ["Hull", "Flight", "Factory loadout"]
    rows = _rows(got[0])
    assert rows["scm_speed"] == {"id": "scm_speed", "label": "SCM speed", "value": 230, "unit": "m/s"}
    assert rows["role"]["value"] == "Medium Fighter"                # the game's text for "@vehicle_focus_fighter"
    assert rows["career"]["value"] == "Combat"                      # no text in the game: what the key says
    assert server.values("objects/nothing.cgf") == {"records": []}


def test_values_speak_the_interface_language(game):
    i18n.set_language("it")
    rifle = server.values(made_up.RIFLE)["records"][0]
    rows = _rows(rifle)
    assert rifle["kind_label"] == "Armi personali" and rows["fire_mode"]["value"] == "Colpo singolo"
    assert rows["magazine"]["label"] == "Caricatore" and rows["other_modes"]["value"] == "Raffica 900 rpm"
    assert rows["manufacturer"]["value"] == "Behring"


def test_table_of_a_kind(game):
    r = server.values_table("weapon")
    lines = r.body.decode("utf-8-sig").splitlines()
    assert lines[0].startswith("Record,Name,Type,Size,Grade,Manufacturer,Mass (kg),Fire mode,Fire rate (rpm),")
    assert lines[1].startswith("behr_rifle,P4-AR Rifle,WeaponPersonal / Medium,2,1,Behring,3.5,Single,600,")
    assert len(lines) == 3 and (game / "values_weapon.csv").read_bytes() == r.body
    assert 'filename="values_weapon.csv"' in r.headers["content-disposition"]
    ships = json.loads(server.values_table("ship", "json").body)
    assert [s["record"] for s in ships] == ["ANVL_Hornet", "ANVL_Hornet_Tracker"] and ships[0]["cargo"] == 8
    with pytest.raises(server.HTTPException) as e:
        server.values_table("nothing")
    assert e.value.status_code == 404


def test_everything_on_one_record(game):
    r = server.values_raw("behr_rifle_mag")
    got = json.loads(r.body)
    ammo = next(c for c in got["Components"] if c["_type"] == "SAmmoContainerComponentParams")
    assert ammo["ammoParamsRecord"]["projectileParams"]["damage"]["DamagePhysical"] == 20.0
    assert (game / "behr_rifle_mag_raw.json").exists()
    with pytest.raises(server.HTTPException) as e:
        server.values_raw("nothing")
    assert e.value.status_code == 404
