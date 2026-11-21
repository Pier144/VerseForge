"""The game values VerseForge reads from DataCore (DPS, magazine, speeds, health…), without opening the app.

    python tools/game_values.py                     one CSV per kind (ships, weapons…) and all.json, in the exports folder
    python tools/game_values.py --check             how many objects of each kind have each value, and the values
                                                    that nothing has any more (after a patch renamed a field)
    python tools/game_values.py --raw ANVL_Hornet_F7C      everything the game holds on one entity, as JSON
    python tools/game_values.py --schema IFCS       the structs of the database whose name or properties hold a text

--p4k takes another Data.p4k than the one in the settings, --out another folder, --lang the language of the names."""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sc_explorer import catalog, entities, gamestats, i18n  # noqa: E402
from sc_explorer.p4k import P4kArchive  # noqa: E402
from sc_explorer.server import CACHE_DIR, load_config  # noqa: E402


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--p4k", default=cfg["p4k_path"])
    ap.add_argument("--out", default=os.path.join(cfg["export_dir"], "values"))
    ap.add_argument("--lang", default=cfg["lang"], choices=list(i18n.LANGUAGES))
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--raw", metavar="RECORD")
    ap.add_argument("--schema", metavar="TEXT")
    args = ap.parse_args()
    if not os.path.isfile(args.p4k):
        sys.exit(f"Data.p4k not found: {args.p4k}")
    i18n.set_language(args.lang)
    arch = P4kArchive(args.p4k, CACHE_DIR)
    arch.load()
    read = entities.archive_reader(arch)
    idx = entities.open_index(arch.read(next(n for n in arch.names if n.lower().endswith(".dcb"))), read)
    if args.schema:
        for name, props in sorted(gamestats.schema(idx.dc, args.schema).items()):
            print(f"{name}: {', '.join(props)}")
        return
    if args.raw:
        ri = gamestats.find_record(idx.dc, args.raw)
        if ri is None:
            sys.exit(f"No entity named {args.raw}")
        print(json.dumps(gamestats.raw(idx.dc, ri), indent=1, ensure_ascii=False,
                         default=lambda o: o.item() if hasattr(o, "item") else str(o)))
        return
    index = gamestats.build(idx, read)
    if args.check:
        for kind, c in gamestats.coverage(index).items():
            print(f"{kind}: {c['records']}")
            for stat, n in c["stats"].items():
                print(f"    {stat:<22}{n}")
        gone = gamestats.missing(index)
        print("values that nothing has: " + (", ".join(gone) if gone else "none"))
        return
    loc = catalog.localization(arch, i18n.game_language())

    def text(stat, value):
        return loc.get(value.lstrip("@").lower(), value) if isinstance(value, str) and value.startswith("@") else value
    os.makedirs(args.out, exist_ok=True)
    for kind in gamestats.KINDS:
        entries = gamestats.of_kind(index, kind)
        if entries:
            lines = gamestats.table(entries, i18n.stat, text, lambda e: loc.get(e["name"]) or e["record"])
            with open(os.path.join(args.out, f"values_{kind}.csv"), "wb") as f:
                f.write(gamestats.csv_bytes(lines))
            print(f"{kind}: {len(entries)}")
    with open(os.path.join(args.out, "all.json"), "w", encoding="utf-8") as f:
        json.dump(index["records"], f, indent=1, ensure_ascii=False)
    print(args.out)


if __name__ == "__main__":
    main()
