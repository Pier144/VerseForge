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
from contextlib import asynccontextmanager

import zstandard
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import APP_NAME, __version__, animations, assembly, backdrops, catalog, diskcache, entities, export, i18n, materials, model, modelcache, paths, printing, reports, textures, updates, variants
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
    cfg = {"p4k_path": "", "export_dir": DEFAULT_EXPORTS, "blender": "", "language": "english",
           "appearance": "system", "check_updates": True, "skip_version": "", "disk_cache": True}
    if os.path.exists(CONFIG_FILE):
        try:
            cfg.update(json.load(open(CONFIG_FILE, encoding="utf-8")))
        except (OSError, ValueError):
            pass
    cfg.pop("ui_lang", None)          # setting of older versions (the interface is English only now)
    if not cfg["p4k_path"]:
        cfg["p4k_path"] = paths.find_p4k()   # first start: the usual install folder (Linux: Wine/Lutris prefixes)
    return cfg


def save_config(cfg):
    os.makedirs(DATA_DIR, exist_ok=True)
    json.dump(cfg, open(CONFIG_FILE, "w", encoding="utf-8"), indent=2, ensure_ascii=False)


class State:
    def __init__(self):
        self.cfg = load_config()
        self.archive = None
        self.textures = None
        self.items = []
        self.by_path = {}
        self.variants = {}               # geometry path (lowercase) -> paint variants from DataCore
        self.entities = {}               # geometry path -> Mannequin animation database (see entities.py)
        # messages are (i18n key, {args}) tuples, turned into text when the interface asks for them
        self.status = {"ready": False, "message": ("starting",), "progress": 0.0, "error": None}
        self.models = modelcache.ModelCache()   # built models, LRU within a memory budget (modelcache.py)
        self.lock = threading.Lock()
        self.jobs = {}
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
            self.models.clear()
            self.status = {"ready": True, "message": ("models_ready", {"n": len(items)}), "progress": 1.0, "error": None}
        except Exception as e:
            traceback.print_exc()
            self.status = {"ready": False, "message": ("error",), "progress": 0.0, "error": _err(e)}

    def _names(self, arch):
        st = os.stat(arch.path)
        cache = os.path.join(CACHE_DIR, f"names_{self.cfg['language']}_{st.st_size}_{int(st.st_mtime)}.json")
        if os.path.exists(cache):
            return json.load(open(cache, encoding="utf-8"))
        names = catalog.game_names(arch, self.cfg["language"])
        for old in os.listdir(CACHE_DIR):
            if old.startswith("names_"):
                try:
                    os.remove(os.path.join(CACHE_DIR, old))
                except OSError:
                    pass
        json.dump(names, open(cache, "w", encoding="utf-8"))
        return names

    def _variants(self, arch):
        st = os.stat(arch.path)
        cache = os.path.join(CACHE_DIR, f"variants_v3_{self.cfg['language']}_{st.st_size}_{int(st.st_mtime)}.json")
        if os.path.exists(cache):
            return json.load(open(cache, encoding="utf-8"))
        dcb = next(n for n in arch.names if n.lower().endswith(".dcb"))
        out = variants.build(arch.read(dcb), catalog.localization(arch, self.cfg["language"]))
        for old in os.listdir(CACHE_DIR):
            if old.startswith("variants_"):
                try:
                    os.remove(os.path.join(CACHE_DIR, old))
                except OSError:
                    pass
        json.dump(out, open(cache, "w", encoding="utf-8"))
        return out

    def _entities(self, arch):
        st = os.stat(arch.path)
        cache = os.path.join(CACHE_DIR, f"entities_v5_{st.st_size}_{int(st.st_mtime)}.json")
        if os.path.exists(cache):
            return json.load(open(cache, encoding="utf-8"))
        dcb = next(n for n in arch.names if n.lower().endswith(".dcb"))
        out = entities.build(arch.read(dcb))
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

    def get_model(self, path, variant=None, full=False, interior=False):
        """Model with a paint variant applied (None = the item's default paint, when DataCore has one).
        full: ships and vehicles with their factory loadout and landing gear mounted (assembly.load_full).
        interior: the rooms of the ship's object containers placed inside (assembly.load_interior)."""
        if interior and self.can_interior(path):
            return self.models.get_or_build(
                (path.lower(), "interior", variant, bool(full)),
                lambda: assembly.load_interior(self.archive, self.get_model(path, variant, full),
                                               entities.vehicle_for(self.entities, path),
                                               entities.classes_of(self.entities)))
        full = bool(full) and self.can_full(path)
        vs = self.variant_list(path)
        v = next((x for x in vs if x["tag"] == variant), vs[0] if vs else None)
        if v is None:
            return self._base_model(path, full)
        return self.models.get_or_build(
            (path.lower(), v["tag"], full),
            lambda: model.with_variant(self._base_model(path, full), self.archive, v["material"], v["palette"]))

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
            "appearance": state.cfg.get("appearance", "system"),
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
    return [{"id": k, "label": i18n.CATEGORIES[k], "short": i18n.CATEGORIES_SHORT[k], "count": counts.get(k, 0),
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
    key = (path.lower(), variant, bool(full), bool(interior))
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
            "variants": [{"tag": v["tag"], "label": v["label"]} for v in vs],
            "variant": variant if any(v["tag"] == variant for v in vs) else (vs[0]["tag"] if vs else None),
            "can_full": state.can_full(path), "full": bool(full) and state.can_full(path),
            "can_interior": state.can_interior(path), "interior": bool(interior) and state.can_interior(path),
            "ground_vehicle": "/vehicles/" in path.lower().replace("\\", "/"),
            "ammo": entities.ammo_for(state.entities, path),
            "screen": _screen_info(m, it),
            "shading": _shading(m),
            "decks": assembly.decks(m) if bool(interior) and state.can_interior(path) else [],
            "animations": [{"id": a.id, "label": a.label, "group": a.group, "clip": a.clip, "duration": a.duration,
                            "speed": a.speed, "pose": a.pose} for a in m.animations]}


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
    screens = [p.material for p in m.parts if p.material.kind == "screen"]
    if not screens:
        return None
    e = screens[0].emissive or (0.2, 0.6, 0.8)
    return {"accent": "#%02x%02x%02x" % tuple(int(round(min(1, max(0, c)) ** (1 / 2.2) * 255)) for c in e),
            "maker": (it.manu if it else "") or ""}


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
        data = export.to_glb(m, textures=state.textures if tex else None, tex_size=1024,
                             sources=_sources(m) if anim else None, lite=lite)
        # once on disk the file is read from there (above): a second copy in memory would only take room
        if not state.disk.put("glb", dkey, "glb", data):
            m.cache[key] = data
        state.models.trim()
    return Response(data, media_type="model/gltf-binary")


def _save_export(data, filename):
    os.makedirs(state.cfg["export_dir"], exist_ok=True)
    out = os.path.join(state.cfg["export_dir"], filename)
    with open(out, "wb") as f:
        f.write(data)
    return out


@app.get("/api/export")
def export_model(path: str, fmt: str = Query("glb", pattern="^(glb|obj|stl)$"), decals: bool = False, tex: bool = True,
                 variant: str = None, anim: bool = True, full: bool = False, interior: bool = False):
    _require_ready()
    m = state.get_model(path, variant, full, interior)
    if not m.parts:
        raise HTTPException(422, tr("nothing_to_export"))
    stem = (_stem(path) + ("_full" if full and state.can_full(path) else "")
            + ("_interior" if interior and state.can_interior(path) else ""))
    tex_cache = state.textures if tex else None
    if fmt == "glb":
        data, name = export.to_glb(m, include_hidden=False, textures=tex_cache, tex_size=2048,
                                   sources=_sources(m) if anim else None), f"{stem}.glb"
    elif fmt == "obj":
        data, name = export.to_obj_zip(m, stem, include_decals=decals, textures=tex_cache, tex_size=2048), f"{stem}_obj.zip"
    else:
        data, name = export.to_stl(m, include_decals=decals), f"{stem}_{tr('suffix_raw')}.stl"
    saved = _save_export(data, name)
    return Response(data, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Saved-To": saved})


# ------------------------------------------------------------------ print jobs
def _run_print_job(job_id, path, voxel, fill, full=False):
    job = state.jobs[job_id]
    try:
        blender = printing.find_blender(state.cfg.get("blender"))
        if not blender:
            raise i18n.LocalizedError("blender_missing")
        m = state.get_model(path, full=full)
        stl = export.to_stl(m, include_decals=False)
        data, info = printing.make_printable(stl, blender, voxel, fill,
                                             lambda msg, frac: job.update(message=msg, progress=frac))
        job["file"] = _save_export(data, f"{_stem(path)}_{tr('suffix_print')}.stl")
        job.update(state="done", message=("done",), progress=1.0, info=info)
    except Exception as e:
        traceback.print_exc()
        job.update(state="error", message=_err(e))


@app.post("/api/print")
def start_print(path: str, voxel: float = 0.0, fill: bool = True, full: bool = False):
    _require_ready()
    job_id = uuid.uuid4().hex[:10]
    state.jobs[job_id] = {"id": job_id, "path": path, "state": "running", "message": ("queued",), "progress": 0.0,
                          "started": time.time()}
    threading.Thread(target=_run_print_job, args=(job_id, path, voxel or None, fill, full), daemon=True).start()
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
               disk_cache: str = ""):
    changed_p4k = p4k_path and p4k_path != state.cfg["p4k_path"]
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
    if changed_p4k:
        threading.Thread(target=state.load, daemon=True).start()
    return status()


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
    folders = reports.user_folders(state.cfg, printing.find_blender(state.cfg.get("blender")))
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
    save_config(state.cfg)
    return out


@app.get("/api/report/mine")
def report_mine():
    items = reports.mine(state.cfg)
    known = reports.statuses([it["number"] for it in items])
    return {"reports": [{**it, **known.get(it["number"], {"state": None, "comments": None})} for it in items]}


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


@app.middleware("http")
async def _no_stale_ui(request, call_next):
    # the UI changes with every update: make the browser / Qt WebEngine revalidate instead of using a cached copy
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
