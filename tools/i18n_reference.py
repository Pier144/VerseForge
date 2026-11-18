"""Write web/locales/en.json: every text of VerseForge in English, the file to copy and translate for a new language.

English itself is read from the code (sc_explorer/i18n.py) and from web/index.html, never from this file: run this
after changing a text, so translators see it.  python tools/i18n_reference.py"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sc_explorer import i18n  # noqa: E402

path = os.path.join(i18n.LOCALES_DIR, "en.json")
with open(path, "w", encoding="utf-8", newline="\n") as f:
    json.dump(i18n.reference(), f, indent=2, ensure_ascii=False)
    f.write("\n")
print(path)
