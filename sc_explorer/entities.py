"""Index of DataCore entities by geometry: which Mannequin animation database (.adb) gives an object's clips meaning."""
from .datacore import DataCore

ADB_ROOT = "Animations/Mannequin/ADB/"


def _norm(path):
    p = (path or "").replace("\\", "/").lower()
    return p[5:] if p.startswith("data/") else p


def build(data: bytes):
    """{"adb": {geometry path (lowercase, "/"): .adb path (Data-relative)}}"""
    dc = DataCore(data)
    found = {}                      # geometry -> [(record name, adb)]
    for ri in dc.records_of("EntityClassDefinition"):
        geo = adb = None
        for c in dc.record_view(ri)["Components"]:
            if c is None:
                continue
            t = c.type
            if t == "SGeometryResourceParams":
                geo = _norm(c["Geometry"]["Geometry"]["Geometry"]["path"])
            elif t == "SAnimationControllerParams":
                adb = (c["AnimationDatabase"] or "").replace("\\", "/")
        if geo and adb:
            found.setdefault(geo, []).append((dc.record_name(ri).split(".", 1)[-1], adb))
    out = {}
    for geo, recs in found.items():
        stem = geo.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        recs.sort()
        name, adb = next((r for r in recs if r[0].lower().endswith(stem)), recs[0])
        out[geo] = adb if adb.lower().startswith("animations/") else ADB_ROOT + adb
    return {"adb": out}


def adb_for(index, path):
    return (index or {}).get("adb", {}).get(_norm(path))
