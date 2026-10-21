"""Paint variants (skins) from DataCore: geometry path -> [{tag, label, material, palette colours}]."""
from collections import defaultdict

from .datacore import DataCore


def _norm(path):
    p = (path or "").replace("\\", "/").lower()
    return p[5:] if p.startswith("data/") else p


def _rgb(v):
    return [int(v["r"]), int(v["g"]), int(v["b"])] if v is not None else None


def _palette(dc, ref, child_path=""):
    """TintPaletteRef -> {"name", "A", "B", "C", "glass"} (sRGB 0-255) or None."""
    ri = ref
    if ri is None:
        return None
    node = dc.record_view(ri)["root"]
    for part in [p for p in (child_path or "").split(".") if p]:
        nxt = next((c for c in node["children"] if c is not None and c["name"].lower() == part.lower()), None)
        if nxt is None:
            break
        node = nxt
    return {"name": node["name"] or dc.record_name(ri).split(".", 1)[-1],
            "A": _rgb(node["entryA"]["tintColor"]), "B": _rgb(node["entryB"]["tintColor"]),
            "C": _rgb(node["entryC"]["tintColor"]), "glass": _rgb(node["glassColor"])}


def _node(dc, node):
    g = node["Geometry"]
    pal = g["Palette"]
    return _norm(g["Geometry"]["path"]), _norm(g["Material"]["path"]), _palette(dc, pal["RootRecord"], pal["ChildPath"])


def build(data: bytes, loc: dict):
    """Scan every entity with geometry. Returns {geometry path: {"default": tag, "variants": [...]}}."""
    dc = DataCore(data)
    entities, paint_labels = [], {}
    for ri in dc.records_of("EntityClassDefinition"):
        geo, tag, name = None, "", ""
        for c in dc.record_view(ri)["Components"]:
            if c is None:
                continue
            t = c.type
            if t == "SGeometryResourceParams":
                root = c["Geometry"]
                path, mtl, pal = _node(dc, root)
                if not path:
                    continue
                subs = {}
                for s in root["SubGeometry"]:
                    st = s["Tags"]
                    if not st:
                        continue
                    spath, smtl, spal = _node(dc, s)
                    if spath and spath != path:
                        continue
                    subs[st.lower()] = (smtl or mtl, spal or pal)
                geo = (path, mtl, pal, subs)
            elif t == "SAttachableComponentParams":
                ad = c["AttachDef"]
                name = ad["Localization"]["Name"]
                if ad["Type"] == "Paints":       # ship liveries: "@<geometry tag>" in the item tags
                    for tok in (ad["Tags"] or "").split():
                        if tok.startswith("@"):
                            paint_labels.setdefault(tok[1:].lower(), name)
            if c.has("geometryTags") and c["geometryTags"]:
                tag = c["geometryTags"].lower()
        if geo:
            entities.append((dc.record_name(ri).split(".", 1)[-1], geo, tag, name))

    def label(key, fallback):
        text = loc.get((key or "").lstrip("@").lower(), "")
        return text if text and not text.startswith("@") else fallback

    tag_labels = {(e[1][0], e[2]): label(e[3], e[0]) for e in entities if e[2]}

    def tag_label(path, tag):
        if (path, tag) in tag_labels:
            return tag_labels[(path, tag)]
        return label(paint_labels.get(tag), tag.replace("_", " ").strip().capitalize())
    by_path = defaultdict(list)
    for e in sorted(entities, key=lambda e: (len(e[0]), e[0])):
        by_path[e[1][0]].append(e)

    def usable(v):
        return "invis" not in (v["material"] or "") and "placeholder" not in v["label"].lower()

    result = {}
    for path, ents in by_path.items():
        plain, tagged = [], []
        for ent_name, (_, mtl, pal, subs), tag, name in ents:
            if tag and tag in subs:
                smtl, spal = subs[tag]
                tagged.append({"label": label(name, ent_name), "material": smtl, "palette": spal})
            elif not tag:
                plain.append({"label": label(name, ent_name), "material": mtl, "palette": pal})
            for stag, (smtl, spal) in subs.items():
                tagged.append({"label": tag_label(path, stag), "material": smtl, "palette": spal})
        plain = [v for v in plain if usable(v)]
        default = plain[:1]
        rest = sorted([v for v in tagged + plain[1:] if usable(v)], key=lambda v: v["label"].lower())
        variants, seen = [], set()
        for v in default + rest:
            key = (v["material"], (v["palette"] or {}).get("name"))
            if key in seen or v["label"].lower() in seen:
                continue
            seen.update((key, v["label"].lower()))
            variants.append(v)
        if not any(v["material"] or v["palette"] for v in variants):
            continue
        for i, v in enumerate(variants):
            v["tag"] = str(i)
        result[path] = variants
    return result
