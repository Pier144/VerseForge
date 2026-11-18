"""Languages: the English source (code + index.html), the translation files, and the game's names in another
language (needs Data.p4k)."""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sc_explorer import catalog, i18n  # noqa: E402
from sc_explorer.p4k import P4kArchive  # noqa: E402
from sc_explorer.server import CACHE_DIR, load_config  # noqa: E402

P4K = load_config()["p4k_path"]
needs_game = pytest.mark.skipif(not os.path.isfile(P4K), reason="Data.p4k not found")
OTHERS = [c for c in i18n.LANGUAGES if c != "en"]
WEB = i18n.WEB_DIR


def _flat(d, prefix=""):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(_flat(v, f"{prefix}{k}."))
        else:
            out[prefix + k] = v
    return out


def _holes(text):
    return sorted(re.findall(r"\{(\w*)\}", text))


def _file(code):
    with open(os.path.join(i18n.LOCALES_DIR, f"{code}.json"), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(autouse=True)
def english_again():
    yield
    i18n.set_language("en")


def test_page_texts_have_keys_and_agree_with_the_script():
    page = i18n.page_texts()
    assert len(page) > 100 and all(page.values())
    assert page["settings"] == "Settings" and page["searchPh"].startswith("Search")
    # a key used both by the page and by the script means the same text
    assert not {k for k in page if k in i18n.UI and page[k] != i18n.UI[k]}


def test_script_keys_exist():
    """Every T("key") / plural(.., "key", "key") in app.js is a known text."""
    src = open(os.path.join(WEB, "app.js"), encoding="utf-8").read()
    used = set(re.findall(r'\bT\(\s*"(\w+)"', src))
    used |= {k for pair in re.findall(r'\bT\([^"()]*\?\s*"(\w+)"\s*:\s*"(\w+)"', src) for k in pair}
    used |= {k for pair in re.findall(r'plural\([^,]+,\s*"(\w+)",\s*"(\w+)"\)', src) for k in pair}
    known = {**i18n.page_texts(), **i18n.UI}
    assert len(used) > 60 and not used - set(known)
    # and no text of the script's table is left unused
    assert not [k for k in i18n.UI if f'"{k}"' not in src]


def test_reference_file_is_up_to_date():
    """web/locales/en.json is what translators copy: tools/i18n_reference.py rewrites it."""
    assert _file("en") == i18n.reference()


@pytest.mark.parametrize("code", OTHERS)
def test_translation_is_complete(code):
    ref, got = _flat(i18n.reference()), _flat(_file(code))
    assert set(got) == set(ref)
    assert not [k for k, v in got.items() if not isinstance(v, str) or not v.strip()]
    assert not {k: (ref[k], got[k]) for k in ref if _holes(ref[k]) != _holes(got[k])}
    assert not [k for k, v in got.items() if "<" in v and ">" in v]


def test_language_switch_and_fallback():
    assert i18n.t("queued") == "Queued…" and i18n.category("ships") == "Ships"
    i18n.set_language("it")
    assert i18n.language() == "it" and i18n.game_language() == "italian_(italy)"
    assert i18n.t("queued") != "Queued…" and i18n.category("ships") != "Ships"
    assert i18n.subcategory("weapons", "pistols") != "Pistols" and i18n.weapon_type("pstl") != "pistol"
    assert "12" in i18n.t("models_ready", n=12)
    strings = i18n.page_strings()
    assert strings["lang"] == "it" and strings["strings"]["settings"] != "Settings"
    assert set(strings["strings"]) == set(i18n.reference()["ui"])
    assert i18n.t("no_such_key") == "no_such_key"
    # an unknown language is English
    assert i18n.set_language("xx") == "en" and i18n.t("queued") == "Queued…"


def test_broken_translation_falls_back(monkeypatch):
    monkeypatch.setitem(i18n._tables, "it", {"messages": {"models_ready": "{quanti} modelli", "queued": ""}, "ui": {"save": ""}})
    i18n.set_language("it")
    assert i18n.t("models_ready", n=5) == "5 models available"       # wrong placeholder
    assert i18n.t("queued") == "Queued…"                              # empty
    assert i18n.page_strings()["strings"]["save"] == "Save"


def test_search_key_keeps_other_scripts():
    assert catalog.compact("Gladius 日本語_x-1") == "gladius日本語x1"
    assert catalog.compact("Ñandú Über") == "ñandúüber"


class _Archive:
    """Just enough of a P4kArchive for catalog.build / localization."""

    def __init__(self, files):
        self.files = files
        self.names = list(files)
        self.usize = [len(v) for v in files.values()]

    def read(self, name):
        return self.files[name]


def _archive():
    return _Archive({
        "Data\\Localization\\english\\global.ini": "item_Namegun=Arclight Pistol\nitem_Nameknife=Combat Knife\n".encode(),
        "Data\\Localization\\italian_(italy)\\global.ini": ("item_Namegun=Pistola Arclight\n"   # the game's note for a text it has not translated: English is used
                                                            "item_Nameknife=! ITALIAN_(ITALY) TRANSLATION NOT FOUND FOR LOCID: item_Nameknife !\n").encode(),
        "Data\\Game.dcb": b"@item_Namegun\x00objects/fps_weapons/weapons_v7/klwe/pistol/klwe_pistol.cgf\x00"
                           b"@item_Nameknife\x00objects/fps_weapons/weapons_v7/knife/knife.cgf\x00",
        "Data\\Objects\\fps_weapons\\weapons_v7\\klwe\\pistol\\klwe_pistol.cgf": b"x",
        "Data\\Objects\\fps_weapons\\weapons_v7\\knife\\knife.cgf": b"x",
    })


def test_names_in_another_language_still_found_in_english():
    arch = _archive()
    english = catalog.build(arch, catalog.game_names(arch, "english"))
    names = catalog.game_names(arch, "italian_(italy)")
    assert names["names"]["objects/fps_weapons/weapons_v7/klwe/pistol/klwe_pistol.cgf"] == ["Pistola Arclight"]
    items = catalog.build(arch, names)
    gun = next(it for it in items if it.path.endswith("klwe_pistol.cgf"))
    knife = next(it for it in items if it.path.endswith("knife.cgf"))
    assert gun.name == "Pistola Arclight" and knife.name == "Combat Knife"      # not translated by the game: English
    assert catalog.search(items, "pistola")[0] == [gun] and catalog.search(items, "arclight pistol")[0] == [gun]
    # sub-categories are worked out from the English name, so they do not move with the language
    assert {it.path: it.sub for it in items} == {it.path: it.sub for it in english}
    assert catalog.localization(arch, "italian_(italy)") == {"item_namegun": "Pistola Arclight", "item_nameknife": "Combat Knife"}


@needs_game
def test_game_has_every_language():
    a = P4kArchive(P4K, CACHE_DIR)
    a.load()
    have = {n.lower() for n in a.names if n.lower().endswith("global.ini")}
    for code, (_, folder) in i18n.LANGUAGES.items():
        assert f"data\\localization\\{folder}\\global.ini" in have, code
