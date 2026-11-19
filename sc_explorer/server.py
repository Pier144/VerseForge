"""Local web server: search API, GLB streaming for the 3D viewer, exports and print jobs."""
import io
import json
import os
import re
import sys
import threading
import time
import traceback
import uuid
import zipfile
from contextlib import asynccontextmanager

import numpy as np
import zstandard
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import APP_NAME, __version__, animations, assembly, backdrops, catalog, decalsheet, diskcache, entities, export, i18n, materials, model, modelcache, paints, paths, printing, reports, screens, textures, updates, variants
from .p4k import P4kArchive

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# PyInstaller unpacks resources into sys._MEIPASS; user data never goes next to the program
RES_DIR = getattr(sys, "_MEIPASS", APP_DIR)
WEB_DIR = os.path.join(RES_DIR, "web")
DATA_DIR = paths.data_dir()                 # Windows %APPDATA%\VerseForge, Linux ~/.config/VerseForge
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
CACHE_DIR = paths.cache_dir()               # Windows %LOCALAPPDATA%\VerseForge, Linux ~/.cache/VerseForge
DEFAULT_EXPORTS = paths.documents_dir()


def load_config():
    cfg = {"p4k_path": "", "export_dir": DEFAULT_EXPORTS, "blender": "", "lang": "en", "names": "follow",
           "appearance": "system", "check_updates": True, "skip_version": "", "disk_cache": True}
    if os.path.exists(CONFIG_FILE):
        try:
            cfg.update(json.load(open(CONFIG_FILE, encoding="utf-8")))
        except (OSError, ValueError):
            pass
    cfg.pop("ui_lang", None)          # settings of older versions: the language is "lang" now, and the game's
    cfg.pop("language", None)         # names follow it
    if cfg.get("lang") not in i18n.LANGUAGES:
        cfg["lang"] = "en"
    if cfg.get("names") not in ("follow", "en"):
        cfg["names"] = "follow"
    if not cfg["p4k_path"]:
        cfg["p4k_path"] = paths.find_p4k()   # first start: the usual install folder (Linux: Wine/Lutris prefixes)
    return cfg


def save_config(cfg):
    os.makedirs(DATA_DIR, exist_ok=True)
    json.dump(cfg, open(CONFIG_FILE, "w", encoding="utf-8"), indent=2, ensure_ascii=False)


class State:
    def __init__(self):
        self.cfg = load_config()
        i18n.set_language(self.cfg["lang"])
        i18n.set_names(self.cfg["names"])
        self.archive = None
        self.textures = None
        self.items = []
        self.by_path = {}
        self.variants = {}               # geometry path (lowercase) -> paint variants from DataCore
        self.entities = {}               # geometry path -> Mannequin animation database (see entities.py)
        # messages are (i18n key, {args}) tuples, turned into text when the interface asks for them
        self.status = {"ready": False, "message": ("starting",), "progress": 0.0, "error": None}
        self.models = modelcache.ModelCache()   # built models, LRU within a memory budget (modelcache.py)
        self.paint_ok = {}               # (path, tag, full, interior) -> paints.check result
        self._paint_locks = {}           # key -> Lock: group_keys / check run once while others wait for the result
        self._paint_locks_guard = threading.Lock()
        self.lock = threading.Lock()
        self.jobs = {}
        self.loc = None                   # the game's texts (global.ini), read when a room name needs them
        self.poses = {}                   # poses sent by the viewer for the still exports (the last few)
        self.update = None                # last answer from GitHub (checked at most once an hour)
        self.disk = diskcache.DiskCache(CACHE_DIR)   # built models and textures kept on disk (diskcache.py)
        # VERSEFORGE_DISK_CACHE=0 (start.py --no-disk-cache): off for this process whatever the setting says, and the
        # shared cache folder is left alone (benchmarks, several dev servers side by side)
        self.disk_forced_off = os.environ.get("VERSEFORGE_DISK_CACHE") == "0"
        self.disk.enabled = bool(self.cfg.get("disk_cache", True)) and not self.disk_forced_off
        self.update_time = 0.0

    def load(self):
        self.status = {"ready": False, "message": ("reading_index",), "progress": 0.05, "error": None}
        try:
            path = self.cfg["p4k_path"]
            if not os.path.isfile(path):
                raise i18n.LocalizedError("p4k_missing", path=path)
            arch = P4kArchive(path, CACHE_DIR)
            arch.load(lambda f: self.status.update(progress=0.05 + 0.4 * f))
            self.status.update(message=("reading_names",), progress=0.5)
            names = self._names(arch)
            self.status.update(message=("reading_paints",), progress=0.7)
            try:
                self.variants = self._variants(arch)
            except Exception:                # colours fall back to neutral grey, the rest keeps working
                traceback.print_exc()
                self.variants = {}
            try:
                self.entities = self._entities(arch)
            except Exception:                # objects still load, animations just keep their file names
                traceback.print_exc()
                self.entities = {}
            self.status.update(message=("building_catalog",), progress=0.85)
            items = catalog.build(arch, names)
            self.archive, self.items = arch, items
            self.textures = textures.TextureCache(arch)
            if not self.disk_forced_off:
                self.disk.bind(__version__, path)
            self.by_path = {it.path.lower(): it for it in items}
            self.loc = None
            self.models.clear()
            self.paint_ok = {}
            self.status = {"ready": True, "message": ("models_ready", {"n": len(items)}), "progress": 1.0, "error": None}
        except Exception as e:
            traceback.print_exc()
            self.status = {"ready": False, "message": ("error",), "progress": 0.0, "error": _err(e)}

    def _names(self, arch):
        st = os.stat(arch.path)
        lang = i18n.game_language()
        cache = os.path.join(CACHE_DIR, f"names3_{lang}_{st.st_size}_{int(st.st_mtime)}.json")
        if os.path.exists(cache):
            return json.load(open(cache, encoding="utf-8"))
        names = catalog.game_names(arch, lang)
        for old in os.listdir(CACHE_DIR):
            if old.startswith(("names_", "names2_", f"names3_{lang}_")):
                try:
                    os.remove(os.path.join(CACHE_DIR, old))
                except OSError:
                    pass
        json.dump(names, open(cache, "w", encoding="utf-8"))
        return names

    def _variants(self, arch):
        st = os.stat(arch.path)
        lang = i18n.game_language()
        cache = os.path.join(CACHE_DIR, f"variants_v6_{lang}_{st.st_size}_{int(st.st_mtime)}.json")
        if os.path.exists(cache):
            return json.load(open(cache, encoding="utf-8"))
        dcb = next(n for n in arch.names if n.lower().endswith(".dcb"))
        out = variants.build(arch.read(dcb), catalog.localization(arch, lang))
        for old in os.listdir(CACHE_DIR):           # one file per language is kept: switching back is quick
            if old.startswith("variants_") and not old.startswith("variants_v6_") or old.startswith(f"variants_v6_{lang}_"):
                try:
                    os.remove(os.path.join(CACHE_DIR, old))
                except OSError:
                    pass
        json.dump(out, open(cache, "w", encoding="utf-8"))
        return out

    def _entities(self, arch):
        st = os.stat(arch.path)
        cache = os.path.join(CACHE_DIR, f"entities_v7_{st.st_size}_{int(st.st_mtime)}.json")
        if os.path.exists(cache):
            return json.load(open(cache, encoding="utf-8"))
        dcb = next(n for n in arch.names if n.lower().endswith(".dcb"))
        out = entities.build(arch.read(dcb), entities.archive_reader(arch))
        for old in os.listdir(CACHE_DIR):
            if old.startswith("entities_"):
                try:
                    os.remove(os.path.join(CACHE_DIR, old))
                except OSError:
                    pass
        json.dump(out, open(cache, "w", encoding="utf-8"))
        return out

    def variant_list(self, path):
        return self.variants.get(path.lower().replace("\\", "/"), [])

    def can_full(self, path):
        return entities.vehicle_for(self.entities, path) is not None

    def can_interior(self, path):
        return bool((entities.vehicle_for(self.entities, path) or {}).get("containers"))

    def ref_tag(self, path):
        vs = self.variant_list(path)
        return vs[0]["tag"] if vs else None

    def tag_of(self, path, variant):
        """The tag get_model() uses for `variant` (None or unknown = the reference paint)."""
        vs = self.variant_list(path)
        return variant if any(v["tag"] == variant for v in vs) else (vs[0]["tag"] if vs else None)

    def keyed(self, path):
        """Models with 2+ paints get the paint-independent GLB layout (paints.py)."""
        return len(self.variant_list(path)) >= 2

    def _paint_lock(self, key):
        with self._paint_locks_guard:
            return self._paint_locks.setdefault(key, threading.Lock())

    def paint_groups(self, path, full, interior):
        # same normalisation as swappable(): the groups are cached on the reference model, which is the same object
        full = bool(full) and self.can_full(path)
        interior = bool(interior) and self.can_interior(path)
        ref = self.get_model(path, None, full, interior)
        # the info and the GLB requests arrive together and group_keys walks ~60k parts: the second waits
        with self._paint_lock(("groups", path.lower(), full, interior)):
            if "paint_groups" not in ref.cache:
                # interior parts come after the hull's and never share a group with them
                fixed_from = len(self.get_model(path, None, full).parts) if interior else None
                # an int32 array: ModelCache's size walk counts one block instead of ~60k Python ints
                ref.cache["paint_groups"] = np.asarray(paints.group_keys(ref, fixed_from), dtype=np.int32)
            return ref.cache["paint_groups"]

    def swappable(self, path, variant, full, interior):
        """Can this paint take the reference paint's place by swapping materials (paints.check)? Kept per request."""
        if not self.keyed(path):
            return False
        full = bool(full) and self.can_full(path)
        interior = bool(interior) and self.can_interior(path)
        key = (path.lower(), self.tag_of(path, variant), full, interior)
        with self._paint_lock(("ok",) + key):
            if key not in self.paint_ok:
                ref = self.get_model(path, None, full, interior)
                self.paint_ok[key] = paints.check(ref, self.get_model(path, variant, full, interior),
                                                  self.paint_groups(path, full, interior))
            return self.paint_ok[key]

    def get_model(self, path, variant=None, full=False, interior=False):
        """Model with a paint variant applied (None or an unknown tag = the reference paint, the first of the list).
        full: ships and vehicles with their factory loadout and landing gear mounted (assembly.load_full).
        interior: the rooms of the ship's object containers placed inside (assembly.load_interior), built once for
        the reference paint and reused by the others (assembly.repaint_interior)."""
        vs = self.variant_list(path)
        v = next((x for x in vs if x["tag"] == variant), vs[0] if vs else None)
        tag = v["tag"] if v else None
        if interior and self.can_interior(path):
            return self.models.get_or_build((path.lower(), "interior", tag, bool(full)),
                                            lambda: self._interior(path, tag, full))
        full = bool(full) and self.can_full(path)
        if v is None:
            return self._base_model(path, full)
        return self.models.get_or_build(
            (path.lower(), v["tag"], full),
            lambda: model.with_variant(self._base_model(path, full), self.archive, v["material"], v["palette"]))

    def _interior(self, path, tag, full):
        hull = self.get_model(path, tag, full)
        vs = self.variant_list(path)
        if vs and tag != vs[0]["tag"]:
            ref_hull = self.get_model(path, vs[0]["tag"], full)
            ref = self.get_model(path, vs[0]["tag"], full, True)
            n = len(ref_hull.parts)
            if len(hull.parts) == n and len(ref.parts) >= n:
                return assembly.repaint_interior(ref, hull, n)
        return assembly.load_interior(self.archive, hull, entities.vehicle_for(self.entities, path),
                                      entities.classes_of(self.entities))

    def _base_model(self, path, full=False):
        def build():
            if not self.archive or not self.archive.exists(path):
                raise HTTPException(404, tr("file_missing", path=path))
            adb = entities.adb_for(self.entities, path)
            if full:
                return assembly.load_full(self.archive, path, entities.vehicle_for(self.entities, path), adb)
            return model.load_model(self.archive, path, adb)
        return self.models.get_or_build((path.lower(), full), build)


state = State()


@asynccontextmanager
async def _lifespan(_app):
    # the catalogue loads in the background: the interface is served at once and shows the progress
    threading.Thread(target=state.load, daemon=True).start()
    yield


app = FastAPI(title=APP_NAME, version=__version__, lifespan=_lifespan)


def tr(key, **kw):
    return i18n.t(key, **kw)


def _msg(m):
    if isinstance(m, tuple) and m and m[0] == "models_ready":
        return tr("models_ready", n=i18n.fmt_int(m[1]["n"]))
    return i18n.msg(m) if m is not None else None


def _err(e):
    """Exception as a message that is turned into text later."""
    return (e.key, e.kw) if isinstance(e, i18n.LocalizedError) else str(e)


def _require_ready():
    if not state.status["ready"]:
        raise HTTPException(503, _msg(state.status.get("error") or state.status["message"]))


def _item_json(it):
    return {"path": it.path, "name": it.name, "subtitle": catalog.subtitle(it), "category": it.category, "ext": it.ext,
            "size": it.size, "main": it.main, "game_name": it.game_name}


def _stem(path):
    return re.sub(r"[^A-Za-z0-9_\-]+", "_", path.rsplit("/", 1)[-1].rsplit(".", 1)[0])


@app.get("/api/status")
def status():
    return {**state.status, "message": _msg(state.status["message"]), "error": _msg(state.status["error"]),
            "app": APP_NAME, "version": __version__, "p4k_path": state.cfg["p4k_path"], "export_dir": state.cfg["export_dir"],
            "blender": printing.find_blender(state.cfg.get("blender")), "blender_setting": state.cfg.get("blender", ""),
            "appearance": state.cfg.get("appearance", "system"), "lang": i18n.language(), "names": i18n.names(),
            "check_updates": bool(state.cfg.get("check_updates", True)),
            "disk_cache": state.disk.enabled, "disk_cache_bytes": state.disk.size, "disk_cache_limit": state.disk.limit,
            "memory": {"models": len(state.models), "models_bytes": state.models.bytes, "models_budget": state.models.budget,
                       "textures_bytes": state.textures.bytes if state.textures else 0,
                       "textures_budget": state.textures.budget if state.textures else 0}}


@app.post("/api/cache/clear")
def clear_cache():
    """Delete the disk cache of models and textures (Settings → Cache)."""
    state.disk.clear()
    return {"ok": True, "bytes": state.disk.size}


@app.get("/api/categories")
def categories():
    counts = {}
    for it in state.items:
        if it.main:
            counts[it.category] = counts.get(it.category, 0) + 1
    subs = catalog.subcategories(state.items)
    return [{"id": k, "label": i18n.category(k), "short": i18n.category_short(k), "count": counts.get(k, 0),
             "subs": [{"id": s, "label": label, "count": n} for s, label, n in subs[k]]} for k in catalog.CATEGORIES]


@app.get("/api/search")
def search(q: str = "", cat: str = "", sub: str = "", main: bool = True, limit: int = 300):
    _require_ready()
    items, total = catalog.search(state.items, q, cat or None, main, min(limit, 2000), sub or None)
    return {"total": total, "items": [_item_json(it) for it in items]}


@app.get("/api/related")
def related(path: str):
    """Other geometry in the same folder (parts, variants, LOD-free)."""
    _require_ready()
    folder = path.lower().rsplit("/", 1)[0] + "/"
    out = [it for it in state.items if it.path.lower().startswith(folder) and "/" not in it.path[len(folder):]]
    out.sort(key=lambda it: (not it.main, it.path))
    return [_item_json(it) for it in out[:200]]


@app.get("/api/model/info")
def model_info(path: str, variant: str = None, full: bool = False, interior: bool = False):
    _require_ready()
    key = (path.lower(), variant, bool(full), bool(interior), i18n.language(), i18n.game_language())   # warnings and names are texts
    cached = state.disk.get("info", key, "json")
    if cached is not None:
        return Response(cached, media_type="application/json")
    # numpy numbers (stats, deck heights) become plain JSON numbers
    data = json.dumps(_model_info(path, variant, full, interior),
                      default=lambda o: o.item() if hasattr(o, "item") else str(o)).encode("utf-8")
    state.disk.put("info", key, "json", data)
    return Response(data, media_type="application/json")


def _model_info(path, variant, full, interior):
    m = state.get_model(path, variant, full, interior)
    s = m.stats()
    it = state.by_path.get(path.lower())
    vs = state.variant_list(path)
    return {"path": path, "name": it.name if it else _stem(path), "stats": s, "warnings": [_msg(w) for w in m.warnings],
            "materials": [{"name": n, "kind": k} for n, k in s["materials"]],
            "variants": [{"tag": v["tag"], "label": v["label"], "colors": paints.swatches(v.get("palette")),
                          "stock": bool(v.get("stock"))} for v in vs],
            "keyed": state.keyed(path),
            "keyed_glb": state.swappable(path, variant, full, interior),
            "variant": variant if any(v["tag"] == variant for v in vs) else (vs[0]["tag"] if vs else None),
            "can_full": state.can_full(path), "full": bool(full) and state.can_full(path),
            "can_interior": state.can_interior(path), "interior": bool(interior) and state.can_interior(path),
            "ground_vehicle": "/vehicles/" in path.lower().replace("\\", "/"),
            "ammo": entities.ammo_for(state.entities, path),
            "stickers": any(decalsheet.printable(p.material) for p in m.parts),
            "screen": _screen_info(m, it),
            "shading": _shading(m),
            "decks": assembly.decks(m) if bool(interior) and state.can_interior(path) else [],
            "rooms": _rooms(m) if bool(interior) and state.can_interior(path) else [],
            "animations": [{"id": a.id, "label": a.label, "group": a.group, "clip": a.clip, "duration": a.duration,
                            "speed": a.speed, "pose": a.pose} for a in m.animations]}


def _room_label(r):
    """The name the game shows for a room when it has one (global.ini), else its entity name tidied up:
    Room_RN_habs_bunks_closet in the habs container -> "Bunks closet"."""
    key = (r.get("key") or "").lstrip("@").lower()
    if key:
        if state.loc is None:
            try:
                state.loc = catalog.localization(state.archive, i18n.game_language())
            except Exception:
                state.loc = {}
        text = state.loc.get(key)
        if text:
            return text, text
    n = re.sub(r"(?i)room_?rn|_rn\b|\broom\b", " ", r.get("name") or "")
    n = re.sub(r"([a-z])([A-Z])", r"\1 \2", n)
    words = [w for w in re.split(r"[\s_\-]+", n) if w and not w.isdigit()]
    skip = {w.lower() for w in re.split(r"[\s_\-]+", r.get("container") or "")} | {"int", "rsi", "base", "main"}
    kept = [w for w in words if w.lower() not in skip] or words
    # (short name, full name): the full one keeps the container's words, to tell "Top corridor" from "Habs corridor"
    return " ".join(kept).capitalize() or "Room", " ".join(words).capitalize() or "Room"


def _rooms(m):
    """The rooms of an interior that hold something, for the viewer's room list: id (the number in the mesh names,
    "|R<id>"), name, height of the middle (metres, viewer Y)."""
    out, seen = [], {}
    for i, r in enumerate(m.rooms):
        if not r["parts"]:
            continue
        name, full = _room_label(r)
        seen[name] = seen.get(name, 0) + 1
        out.append({"id": i, "name": name, "full": full, "y": round(r["centre"][2], 2)})
    for o in out:                       # same short name twice: the full names tell them apart
        full = o.pop("full")
        if seen[o["name"]] > 1:
            o["name"] = full
    count, nth = {}, {}
    for o in out:
        count[o["name"]] = count.get(o["name"], 0) + 1
    for o in out:                       # still the same (two "Docking Bay"): number them
        if count[o["name"]] > 1:
            nth[o["name"]] = nth.get(o["name"], 0) + 1
            o["name"] = f"{o['name']} {nth[o['name']]}"
    return out


def _shading(m):
    """Game-look shading of every textured material, keyed by the id the GLB carries in its material names."""
    out = {}
    for p in m.parts:
        sh = materials.shading(p.material)
        if sh:
            out[materials.shading_id(sh)] = sh
    return out


DDS_MEDIA = "image/vnd-ms.dds"


def _dds_response(request, data):
    """Raw blocks are about twice the size of the JPEGs: zstd level 1 halves them for ~2 ms a texture (the browser
    unpacks it natively)."""
    headers = {"Cache-Control": "max-age=86400", "Vary": "Accept-Encoding"}
    if "zstd" in request.headers.get("accept-encoding", ""):
        data = zstandard.ZstdCompressor(level=1).compress(data)
        headers["Content-Encoding"] = "zstd"
    return Response(data, media_type=DDS_MEDIA, headers=headers)


@app.get("/api/texture")
def texture(request: Request, path: str, kind: str = Query("color", pattern="^(color|normal|gloss|hal|mask)$"),
            size: int = 1024, gpu: str = ""):
    """One game texture for the viewer's game-look materials: colour, normal (RGB), gloss (grey), HAL or a stencil
    mask (RGB data, sent lossless). gpu=s3tc,rgtc,bptc (the compressed formats the viewer's GPU takes): the game's
    own blocks as a DDS file when the map can be used as it is stored (textures.gpu_blocks), else the image."""
    _require_ready()
    size = max(64, min(int(size), 2048))
    key = (path.lower(), kind, size)
    accept = {f for f in gpu.lower().split(",") if f in ("s3tc", "rgtc", "bptc")}
    if accept:
        cached = state.disk.get("tex", key, "dds")
        if cached is not None and textures.gpu_dds(cached[:148])[1] in accept:
            return _dds_response(request, cached)
        data = state.textures.gpu(path, kind, size, tuple(sorted(accept)))
        if data is not None:
            state.disk.put("tex", key, "dds", data)
            return _dds_response(request, data)
    for ext, media in (("png", "image/png"), ("jpg", "image/jpeg")):
        cached = state.disk.get("tex", key, ext)
        if cached is not None:
            return Response(cached, media_type=media, headers={"Cache-Control": "max-age=86400"})
    tc = state.textures
    if kind == "gloss":
        img = tc.gloss(path, size)
    else:
        img = tc.get(path, size, normal=kind == "normal")
    if img is None:
        raise HTTPException(404, "texture not found")
    buf = io.BytesIO()
    if kind in ("gloss", "hal", "mask") or img.mode == "RGBA":
        img.save(buf, "PNG", compress_level=1)
        media = "image/png"
    else:
        img.convert("RGB").save(buf, "JPEG", quality=92)
        media = "image/jpeg"
    state.disk.put("tex", key, "png" if media == "image/png" else "jpg", buf.getvalue())
    return Response(buf.getvalue(), media_type=media, headers={"Cache-Control": "max-age=86400"})


_backdrop_lock = threading.Lock()


@app.get("/api/backdrop/{name}")
def backdrop(name: str):
    """360° space panorama made from the game's sky textures (see backdrops.py), cached on disk per game version."""
    _require_ready()
    if name not in backdrops.NAMES:
        raise HTTPException(404, "unknown backdrop")
    st = os.stat(state.archive.path)
    path = os.path.join(CACHE_DIR, f"backdrop_v4_{name}_{st.st_size}_{int(st.st_mtime)}.jpg")
    with _backdrop_lock:
        if not os.path.exists(path):
            img = backdrops.build(name, state.textures)
            if img is None:
                raise HTTPException(404, "backdrop textures not found")
            for old in os.listdir(CACHE_DIR):
                if old.startswith(f"backdrop_v4_{name}_") or (old.startswith("backdrop_") and not old.startswith("backdrop_v4_")):
                    try:
                        os.remove(os.path.join(CACHE_DIR, old))
                    except OSError:
                        pass
            img.save(path, "JPEG", quality=92)
    with open(path, "rb") as f:
        # kept on disk by the server: the browser asks again each session, so a new version of the panorama shows
        return Response(f.read(), media_type="image/jpeg", headers={"Cache-Control": "no-cache"})


def _screen_info(m, it):
    """What the viewer needs to light the screens: their accent colour (from the paint) and the maker's name."""
    screens_ = [p.material for p in m.parts if p.material.kind == "screen"]
    if not screens_:
        return None
    e = screens_[0].emissive or (0.2, 0.6, 0.8)
    kit = screens.kit_for(state.archive, m.path) if any(s.rtt for s in screens_) else None
    return {"accent": "#%02x%02x%02x" % tuple(int(round(min(1, max(0, c)) ** (1 / 2.2) * 255)) for c in e),
            "maker": (it.manu if it else "") or "", "kit": kit}


def _sources(m):
    """Decoded clips of a model's animations, once per model (warnings go to the model the first time)."""
    if "sources" not in m.cache:
        src, warns = animations.sources(state.archive, m) if m.anim_sets else ([], [])
        m.warnings += warns
        m.cache["sources"] = src
    return m.cache["sources"]


@app.get("/api/model/glb")
def model_glb(path: str, tex: bool = True, variant: str = None, anim: bool = True, full: bool = False,
              interior: bool = False, lite: bool = False):
    _require_ready()
    dkey = (path.lower(), variant, bool(full), bool(interior), bool(tex), bool(anim), bool(lite))
    cached = state.disk.get("glb", dkey, "glb")
    if cached is not None:
        return Response(cached, media_type="model/gltf-binary")
    m = state.get_model(path, variant, full, interior)
    if not m.parts:
        raise HTTPException(422, "; ".join(_msg(w) for w in m.warnings) or tr("no_geometry"))
    key = ("glb", tex, anim, lite)
    data = m.cache.get(key)
    if data is None:
        groups = (state.paint_groups(path, full, interior)
                  if lite and state.swappable(path, variant, full, interior) else None)
        data = export.to_glb(m, textures=state.textures if tex else None, tex_size=1024,
                             sources=_sources(m) if anim else None, lite=lite, groups=groups)
        # once on disk the file is read from there (above): a second copy in memory would only take room
        if not state.disk.put("glb", dkey, "glb", data):
            m.cache[key] = data
        state.models.trim()
    return Response(data, media_type="model/gltf-binary")


def _hull_parts(path, variant, full, interior):
    """How many parts of the model are the hull's (or full ship's): the interior's come after them."""
    if bool(interior) and state.can_interior(path):
        return len(state.get_model(path, variant, full).parts)
    return None


def _paint_stamp():
    """Names the game build and this program's grouping (paints.group_keys) for the texture URLs: group numbers can
    change after a game patch or a program update, and the browser keeps those images for 24 hours."""
    d = state.disk.dir
    if d:
        return os.path.basename(d)               # program version + format + p4k size and mtime (DiskCache.bind)
    try:
        st = os.stat(state.cfg["p4k_path"])
        return f"{__version__}_{st.st_size}_{int(st.st_mtime)}"
    except (OSError, KeyError, TypeError):
        return str(__version__)


@app.get("/api/model/paint")
def model_paint(path: str, variant: str = None, full: bool = False, interior: bool = False):
    """One paint's materials for the viewer's instant switch (web/paint.js), or {swappable: false}: reload instead.
    An unknown path answers {swappable: false} too: the client reloads and shows the GLB route's error."""
    _require_ready()
    tag = state.tag_of(path, variant)
    if not state.swappable(path, variant, full, interior):
        return {"variant": tag, "swappable": False}
    m = state.get_model(path, variant, full, interior)
    table = paints.paint_table(m, state.paint_groups(path, full, interior), state.textures,
                               fixed_from=_hull_parts(path, variant, full, interior))
    it = state.by_path.get(path.lower())
    data = {"variant": tag, "swappable": True, "stamp": _paint_stamp(), "groups": table["groups"], "shading": table["shading"],
            "stickers": any(decalsheet.printable(p.material) for p in m.parts), "screen": _screen_info(m, it)}
    return Response(json.dumps(data, default=lambda o: o.item() if hasattr(o, "item") else str(o)),
                    media_type="application/json")


@app.get("/api/model/paint/texture")
def model_paint_texture(path: str, group: int, variant: str = None, full: bool = False,
                        map: str = Query("base", pattern="^(base|normal)$"), v: str = ""):
    """The image _glb_mesh would embed for one group in one paint (a livery sticker coloured by the palette).
    Hull groups have the same numbers with and without the interior (hull parts come first), so no `interior`."""
    _require_ready()
    full = bool(full) and state.can_full(path)
    # `v` (the stamp of /api/model/paint) only changes the URL, so the browser's 24 h copy is dropped when the game
    # or the group numbering changes; it is not part of the key here
    key = (path.lower(), state.tag_of(path, variant), full, int(group), map)
    for ext, media in (("png", "image/png"), ("jpg", "image/jpeg")):
        cached = state.disk.get("painttex", key, ext)
        if cached is not None:
            return Response(cached, media_type=media, headers={"Cache-Control": "max-age=86400"})
    m = state.get_model(path, variant, full)
    groups = state.paint_groups(path, full, False)
    p = next((p for g, p in zip(groups, m.parts) if g == group), None)
    if p is None:
        raise HTTPException(404, "no such paint group")
    mat, off = export.keyed_form(p.material)
    has_uv = any(q.uvs is not None for g, q in zip(groups, m.parts) if g == group)
    _, base, normal, _, _ = export.glb_material(mat, has_uv, state.textures, 1024, lite=True, group=group, off=off)
    img = base if map == "base" else normal
    if img is None:
        raise HTTPException(404, "no texture")
    buf = io.BytesIO()
    if img.format == "PNG":
        img.save(buf, "PNG", compress_level=1)
        ext, media = "png", "image/png"
    else:
        img.convert("RGB").save(buf, "JPEG", quality=92)
        ext, media = "jpg", "image/jpeg"
    state.disk.put("painttex", key, ext, buf.getvalue())
    return Response(buf.getvalue(), media_type=media, headers={"Cache-Control": "max-age=86400"})


def _save_export(data, filename):
    os.makedirs(state.cfg["export_dir"], exist_ok=True)
    out = os.path.join(state.cfg["export_dir"], filename)
    with open(out, "wb") as f:
        f.write(data)
    return out


class PoseIn(BaseModel):
    nodes: dict[str, list[float]]


@app.post("/api/pose")
def store_pose(p: PoseIn):
    """The pose the viewer shows (see export.posed); the exports that follow name it by the id returned here."""
    pose_id = uuid.uuid4().hex[:10]
    state.poses[pose_id] = p.nodes
    while len(state.poses) > 8:
        state.poses.pop(next(iter(state.poses)))
    return {"id": pose_id}


def _posed(m, pose):
    """(model in the stored pose, whether anything moved). An unknown or empty pose leaves the model as it is."""
    nodes = state.poses.get(pose) if pose else None
    if not nodes:
        return m, False
    out = export.posed(m, _sources(m), nodes)
    return out, out is not m


@app.get("/api/export")
def export_model(path: str, fmt: str = Query("glb", pattern="^(glb|obj|stl)$"), decals: bool = False, tex: bool = True,
                 variant: str = None, anim: bool = True, full: bool = False, interior: bool = False, pose: str = None):
    _require_ready()
    m = state.get_model(path, variant, full, interior)
    if not m.parts:
        raise HTTPException(422, tr("nothing_to_export"))
    stem = (_stem(path) + ("_full" if full and state.can_full(path) else "")
            + ("_interior" if interior and state.can_interior(path) else ""))
    # a GLB with its animations keeps the rest pose (the clips move it); the still files take the pose shown
    if pose and not (fmt == "glb" and anim and m.animations):
        m, moved = _posed(m, pose)
        stem += "_pose" if moved else ""
        anim = anim and not moved
    tex_cache = state.textures if tex else None
    if fmt == "glb":
        data, name = export.to_glb(m, include_hidden=False, textures=tex_cache, tex_size=2048,
                                   sources=_sources(m) if anim else None), f"{stem}.glb"
    elif fmt == "obj":
        data, name = export.to_obj_zip(m, stem, include_decals=decals, textures=tex_cache, tex_size=2048), f"{stem}_obj.zip"
    else:
        data, name = export.to_stl(m, include_decals=decals), f"{stem}_raw_mm.stl"
    saved = _save_export(data, name)
    return Response(data, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Saved-To": saved})


@app.get("/api/decals")
def decal_sheets(path: str, scale: float = Query(72.0, ge=1.0, le=5000.0), paper: str = Query("a4", pattern="^(a4|letter)$"),
                 variant: str = None, full: bool = False):
    """Zip with the two decal sheets of a model at a kit scale (see decalsheet.py)."""
    _require_ready()
    m = state.get_model(path, variant, full)
    it = state.by_path.get(path.lower())
    decals, small = decalsheet.collect(m, state.textures, scale)
    clear, white, info = decalsheet.sheets(decals, paper, decalsheet.hull_colour(m), it.name if it else _stem(path), scale)
    if not clear:
        raise HTTPException(422, tr("no_decals_big" if info["too_big"] else "no_decals"))
    stem = f"{_stem(path)}_decals_1-{scale:g}"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.writestr(f"{stem}_clear_paper.pdf", clear)
        z.writestr(f"{stem}_white_paper.pdf", white)
    data, name = buf.getvalue(), f"{stem}.zip"
    saved = _save_export(data, name)
    info["too_small"] = small
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Saved-To": saved,
                             "X-Decals": json.dumps(info)})


# ------------------------------------------------------------------ print jobs
def _run_print_job(job_id, path, voxel, fill, full=False, pose=None):
    job = state.jobs[job_id]
    try:
        blender = printing.find_blender(state.cfg.get("blender"))
        if not blender:
            raise i18n.LocalizedError("blender_missing")
        m, moved = _posed(state.get_model(path, full=full), pose)
        stl = export.to_stl(m, include_decals=False)
        data, info = printing.make_printable(stl, blender, voxel, fill,
                                             lambda msg, frac: job.update(message=msg, progress=frac))
        job["file"] = _save_export(data, f"{_stem(path)}{'_pose' if moved else ''}_print3d_mm.stl")
        job.update(state="done", message=("done",), progress=1.0, info=info)
    except Exception as e:
        traceback.print_exc()
        job.update(state="error", message=_err(e))


@app.post("/api/print")
def start_print(path: str, voxel: float = 0.0, fill: bool = True, full: bool = False, pose: str = None):
    _require_ready()
    job_id = uuid.uuid4().hex[:10]
    state.jobs[job_id] = {"id": job_id, "path": path, "state": "running", "message": ("queued",), "progress": 0.0,
                          "started": time.time()}
    threading.Thread(target=_run_print_job, args=(job_id, path, voxel or None, fill, full, pose), daemon=True).start()
    return print_status(job_id)


@app.get("/api/print/{job_id}")
def print_status(job_id: str):
    job = state.jobs.get(job_id)
    if not job:
        raise HTTPException(404, tr("unknown_job"))
    return {k: v for k, v in job.items() if k != "file"} | {"message": _msg(job["message"]), "has_file": "file" in job}


@app.get("/api/print/{job_id}/file")
def print_file(job_id: str):
    job = state.jobs.get(job_id)
    if not job or "file" not in job:
        raise HTTPException(404, tr("file_not_ready"))
    return FileResponse(job["file"], filename=os.path.basename(job["file"]), media_type="application/octet-stream")


# ------------------------------------------------------------------ settings
@app.post("/api/config")
def set_config(p4k_path: str = "", export_dir: str = "", blender: str = None, appearance: str = "", check_updates: str = "",
               disk_cache: str = "", lang: str = "", names: str = ""):
    changed_p4k = p4k_path and p4k_path != state.cfg["p4k_path"]
    changed_lang = lang in i18n.LANGUAGES and lang != state.cfg["lang"]
    if changed_lang:
        state.cfg["lang"] = i18n.set_language(lang)
    game_before = i18n.game_language()
    if names in ("follow", "en"):
        state.cfg["names"] = i18n.set_names(names)
    changed_names = i18n.game_language() != game_before or (changed_lang and names == "")
    if check_updates in ("true", "false"):
        state.cfg["check_updates"] = check_updates == "true"
    if disk_cache in ("true", "false"):
        state.cfg["disk_cache"] = disk_cache == "true"
        state.disk.enabled = state.cfg["disk_cache"] and not state.disk_forced_off
    if p4k_path:
        state.cfg["p4k_path"] = p4k_path
    if export_dir:
        state.cfg["export_dir"] = export_dir
    if blender is not None:                 # empty = find it automatically again
        state.cfg["blender"] = blender.strip()
    if appearance in ("system", "light", "dark"):
        state.cfg["appearance"] = appearance
    save_config(state.cfg)
    # another language: the categories and, unless they are kept in English, the game's names of models, paints
    # and rooms change, so the catalogue is built again
    if changed_p4k or changed_lang or changed_names:
        state.status = {"ready": False, "message": ("reading_index",), "progress": 0.05, "error": None}
        threading.Thread(target=state.load, daemon=True).start()
    return status()


@app.get("/api/i18n")
def page_language():
    """The language and every text of the page (web/i18n.js)."""
    return i18n.page_strings()


@app.post("/api/open-exports")
def open_exports():
    os.makedirs(state.cfg["export_dir"], exist_ok=True)
    paths.open_path(state.cfg["export_dir"])
    return {"ok": True, "dir": state.cfg["export_dir"]}


# ------------------------------------------------------------------ updates
@app.get("/api/update/check")
def update_check(force: bool = False):
    """New release on GitHub? Without force it respects the "check at startup" setting and asks GitHub once an hour."""
    enabled = bool(state.cfg.get("check_updates", True))
    if not (enabled or force):
        return {"enabled": False, "available": False, "current": __version__}
    if force or not state.update or time.time() - state.update_time > 3600:
        try:
            state.update = updates.check(__version__)
        except Exception as e:                       # offline, GitHub down, rate limit: try again next time
            return {"enabled": enabled, "available": False, "current": __version__, "error": str(e)}
        state.update_time = time.time()
    u = state.update
    return {**u, "enabled": enabled, "skipped": u["latest"] == state.cfg.get("skip_version"),
            "can_install": updates.can_install() and bool(u["installer"])}


@app.post("/api/update/skip")
def update_skip(version: str):
    state.cfg["skip_version"] = version
    save_config(state.cfg)
    return {"ok": True}


def _run_update(job):
    try:
        path = updates.download(state.update["installer"], lambda f: job.update(progress=f))
        job.update(state="launching", message=("update_launching",), progress=1.0)
        updates.launch(path)
        # leave the files free for the installer at once (it also waits for VerseForge, and closes it if needed)
        threading.Timer(0.3, lambda: os._exit(0)).start()
    except Exception as e:
        traceback.print_exc()
        job.update(state="error", message=("update_checksum",) if str(e) == "checksum" else str(e))


@app.post("/api/update/install")
def update_install():
    if not updates.can_install():
        raise HTTPException(400, tr("update_source"))
    if not state.update or not state.update.get("available") or not state.update.get("installer"):
        raise HTTPException(400, tr("update_no_installer"))
    job = state.jobs.get("update")
    if not job or job["state"] == "error":
        job = state.jobs["update"] = {"id": "update", "state": "running", "message": ("update_downloading",), "progress": 0.0}
        threading.Thread(target=_run_update, args=(job,), daemon=True).start()
    return update_progress()


@app.get("/api/update/progress")
def update_progress():
    job = state.jobs.get("update")
    if not job:
        raise HTTPException(404, tr("unknown_job"))
    return {**job, "message": _msg(job["message"])}


@app.post("/api/open-release")
def open_release():
    """Open the release page in the default browser (only GitHub pages of this project)."""
    page = (state.update or {}).get("page") or updates.RELEASES_PAGE
    paths.open_path(page if page.startswith(updates.RELEASES_PAGE) else updates.RELEASES_PAGE)
    return {"ok": True}


# ------------------------------------------------------------------ reports (public GitHub issues, see reports.py)
LOG_FILE = os.path.join(CACHE_DIR, "verseforge.log")     # written by verseforge_app.py in the packaged app only


class ReportIn(BaseModel):
    kind: str = "bug"
    title: str = ""
    description: str = ""
    picture: bool = True
    details: bool = True
    model: str | None = None
    variant: str | None = None
    gpu: str | None = None
    screenshot: str | None = None          # JPEG in base64 (only for sending)


class OpenIn(BaseModel):
    number: int | None = None
    fallback: ReportIn | None = None


def _compose_report(r, with_picture):
    """Anonymized issue text for a report from the interface: the same text for the preview, the real report and
    the fallback link."""
    folders = reports.user_folders(state.cfg, printing.find_blender(state.cfg.get("blender"))) + reports.system_folders()
    ident = reports.local_identity()

    def clean(text):
        return reports.anonymize(text, folders=folders, **ident)

    details = ""
    if r.details:
        log = LOG_FILE if getattr(sys, "frozen", False) else None
        details = clean(reports.diagnostics(__version__, model=r.model, variant=r.variant, gpu=r.gpu, log_path=log))
    kind = r.kind if r.kind in reports.KINDS else "bug"
    return kind, reports.compose(kind, clean(r.title), clean(r.description), details, with_picture, __version__)


@app.post("/api/report/preview")
def report_preview(r: ReportIn):
    return _compose_report(r, r.picture)[1]


@app.post("/api/report")
def report_send(r: ReportIn):
    shot = r.screenshot if r.picture and r.screenshot else None
    kind, composed = _compose_report(r, bool(shot))
    try:
        out = reports.send(composed, kind, shot)
    except reports.ReportError as e:
        return JSONResponse({"kind": e.kind, "detail": e.message}, status_code=502)
    reports.remember(state.cfg, out["number"], composed["title"])
    try:
        save_config(state.cfg)
        saved = True
    except Exception:                       # the issue exists anyway: say so, or the user would send it twice
        traceback.print_exc()
        saved = False                       # the interface warns that My reports will forget it after a restart
    return {**out, "saved": saved}


@app.get("/api/report/mine")
def report_mine():
    items = reports.mine(state.cfg)
    listed = reports.with_news(items, reports.statuses([it["number"] for it in items]))
    return {"news": sum(r["news"] for r in listed), "reports": listed}


@app.post("/api/report/seen")
def report_seen():
    """The user opened "My reports": what it shows is no longer news (statuses come from the 5-minute cache)."""
    reports.mark_seen(state.cfg, reports.statuses([it["number"] for it in reports.mine(state.cfg)]))
    try:
        save_config(state.cfg)
    except OSError:
        traceback.print_exc()
    return {"ok": True}


@app.post("/api/report/open")
def report_open(o: OpenIn):
    """Open a sent report, or GitHub's own form filled in. The address is always built here."""
    if o.number is not None and o.number > 0:
        paths.open_path(reports.ISSUE_PAGE + str(int(o.number)))
    elif o.fallback is not None:
        paths.open_path(reports.fallback_url(_compose_report(o.fallback, o.fallback.picture)[1]))
    else:
        raise HTTPException(400, "Nothing to open")
    return {"ok": True}


@app.exception_handler(Exception)
def _errors(_request, exc):
    traceback.print_exc()
    return JSONResponse({"detail": i18n.error_text(exc)}, status_code=500)


LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")


@app.middleware("http")
async def _same_page_only(request, call_next):
    """POSTs to the API only from VerseForge's own page. A web page open in the user's browser could otherwise
    reach the local server (it only has to guess the port) and, e.g., send a public report with their details.
    Browsers always add Origin to such requests; DNS rebinding is stopped by requiring a local Host."""
    origin = request.headers.get("origin")
    if request.method == "POST" and request.url.path.startswith("/api/") and origin is not None:
        host = request.headers.get("host", "")
        if origin != f"http://{host}" or host.rsplit(":", 1)[0] not in LOCAL_HOSTS:
            return JSONResponse({"detail": "Requests from other pages are not allowed"}, status_code=403)
    return await call_next(request)


@app.middleware("http")
async def _no_stale_ui(request, call_next):
    # the UI changes with every update: make the browser / Qt WebEngine revalidate instead of using a cached copy
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
