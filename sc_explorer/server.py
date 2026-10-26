"""Local web server: search API, GLB streaming for the 3D viewer, exports and print jobs."""
import json
import os
import re
import sys
import threading
import time
import traceback
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import APP_NAME, __version__, catalog, export, i18n, model, printing, textures, updates, variants
from .p4k import P4kArchive

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# PyInstaller unpacks resources into sys._MEIPASS; user data never goes next to the program
RES_DIR = getattr(sys, "_MEIPASS", APP_DIR)
WEB_DIR = os.path.join(RES_DIR, "web")
DATA_DIR = os.path.join(os.environ.get("APPDATA", APP_DIR), APP_NAME)
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
CACHE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", APP_DIR), APP_NAME)
DEFAULT_EXPORTS = os.path.join(os.path.expanduser("~"), "Documents", APP_NAME)
DEFAULT_P4K = r"C:\Program Files\Roberts Space Industries\StarCitizen\LIVE\Data.p4k"


def load_config():
    cfg = {"p4k_path": DEFAULT_P4K, "export_dir": DEFAULT_EXPORTS, "blender": "", "language": "english",
           "appearance": "system", "check_updates": True, "skip_version": ""}
    if os.path.exists(CONFIG_FILE):
        try:
            cfg.update(json.load(open(CONFIG_FILE, encoding="utf-8")))
        except (OSError, ValueError):
            pass
    cfg.pop("ui_lang", None)          # setting of older versions (the interface is English only now)
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
        # messages are (i18n key, {args}) tuples, turned into text when the interface asks for them
        self.status = {"ready": False, "message": ("starting",), "progress": 0.0, "error": None}
        self.models = OrderedDict()       # path -> Model (small LRU)
        self.lock = threading.Lock()
        self.jobs = {}
        self.update = None                # last answer from GitHub (checked at most once an hour)
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
            self.status.update(message=("building_catalog",), progress=0.85)
            items = catalog.build(arch, names)
            self.archive, self.items = arch, items
            self.textures = textures.TextureCache(arch)
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
        cache = os.path.join(CACHE_DIR, f"variants_v1_{self.cfg['language']}_{st.st_size}_{int(st.st_mtime)}.json")
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

    def variant_list(self, path):
        return self.variants.get(path.lower().replace("\\", "/"), [])

    def get_model(self, path, variant=None):
        """Model with a paint variant applied (None = the item's default paint, when DataCore has one)."""
        vs = self.variant_list(path)
        v = next((x for x in vs if x["tag"] == variant), vs[0] if vs else None)
        if v is None:
            return self._base_model(path)
        key = (path.lower(), v["tag"])
        with self.lock:
            if key in self.models:
                self.models.move_to_end(key)
                return self.models[key]
        m = model.with_variant(self._base_model(path), self.archive, v["material"], v["palette"])
        with self.lock:
            self.models[key] = m
            while len(self.models) > 8:
                self.models.popitem(last=False)
        return m

    def _base_model(self, path):
        key = path.lower()
        with self.lock:
            if key in self.models:
                self.models.move_to_end(key)
                return self.models[key]
        if not self.archive or not self.archive.exists(path):
            raise HTTPException(404, tr("file_missing", path=path))
        m = model.load_model(self.archive, path)
        with self.lock:
            self.models[key] = m
            while len(self.models) > 8:
                self.models.popitem(last=False)
        return m


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
            "blender": printing.find_blender(state.cfg.get("blender")), "appearance": state.cfg.get("appearance", "system"),
            "check_updates": bool(state.cfg.get("check_updates", True))}


@app.get("/api/categories")
def categories():
    counts = {}
    for it in state.items:
        if it.main:
            counts[it.category] = counts.get(it.category, 0) + 1
    subs = catalog.subcategories(state.items)
    return [{"id": k, "label": i18n.CATEGORIES[k], "count": counts.get(k, 0),
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
def model_info(path: str, variant: str = None):
    _require_ready()
    m = state.get_model(path, variant)
    s = m.stats()
    it = state.by_path.get(path.lower())
    vs = state.variant_list(path)
    return {"path": path, "name": it.name if it else _stem(path), "stats": s, "warnings": [_msg(w) for w in m.warnings],
            "materials": [{"name": n, "kind": k} for n, k in s["materials"]],
            "variants": [{"tag": v["tag"], "label": v["label"]} for v in vs],
            "variant": variant if any(v["tag"] == variant for v in vs) else (vs[0]["tag"] if vs else None)}


@app.get("/api/model/glb")
def model_glb(path: str, tex: bool = True, variant: str = None):
    _require_ready()
    m = state.get_model(path, variant)
    if not m.parts:
        raise HTTPException(422, "; ".join(_msg(w) for w in m.warnings) or tr("no_geometry"))
    key = ("glb", tex)
    if key not in m.cache:
        m.cache[key] = export.to_glb(m, textures=state.textures if tex else None, tex_size=1024)
    return Response(m.cache[key], media_type="model/gltf-binary")


def _save_export(data, filename):
    os.makedirs(state.cfg["export_dir"], exist_ok=True)
    out = os.path.join(state.cfg["export_dir"], filename)
    with open(out, "wb") as f:
        f.write(data)
    return out


@app.get("/api/export")
def export_model(path: str, fmt: str = Query("glb", pattern="^(glb|obj|stl)$"), decals: bool = False, tex: bool = True,
                 variant: str = None):
    _require_ready()
    m = state.get_model(path, variant)
    if not m.parts:
        raise HTTPException(422, tr("nothing_to_export"))
    stem = _stem(path)
    tex_cache = state.textures if tex else None
    if fmt == "glb":
        data, name = export.to_glb(m, include_hidden=False, textures=tex_cache, tex_size=2048), f"{stem}.glb"
    elif fmt == "obj":
        data, name = export.to_obj_zip(m, stem, include_decals=decals, textures=tex_cache, tex_size=2048), f"{stem}_obj.zip"
    else:
        data, name = export.to_stl(m, include_decals=decals), f"{stem}_{tr('suffix_raw')}.stl"
    saved = _save_export(data, name)
    return Response(data, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Saved-To": saved})


# ------------------------------------------------------------------ print jobs
def _run_print_job(job_id, path, voxel, fill):
    job = state.jobs[job_id]
    try:
        blender = printing.find_blender(state.cfg.get("blender"))
        if not blender:
            raise i18n.LocalizedError("blender_missing")
        m = state.get_model(path)
        stl = export.to_stl(m, include_decals=False)
        data, info = printing.make_printable(stl, blender, voxel, fill,
                                             lambda msg, frac: job.update(message=msg, progress=frac))
        job["file"] = _save_export(data, f"{_stem(path)}_{tr('suffix_print')}.stl")
        job.update(state="done", message=("done",), progress=1.0, info=info)
    except Exception as e:
        traceback.print_exc()
        job.update(state="error", message=_err(e))


@app.post("/api/print")
def start_print(path: str, voxel: float = 0.0, fill: bool = True):
    _require_ready()
    job_id = uuid.uuid4().hex[:10]
    state.jobs[job_id] = {"id": job_id, "path": path, "state": "running", "message": ("queued",), "progress": 0.0,
                          "started": time.time()}
    threading.Thread(target=_run_print_job, args=(job_id, path, voxel or None, fill), daemon=True).start()
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
def set_config(p4k_path: str = "", export_dir: str = "", blender: str = "", appearance: str = "", check_updates: str = ""):
    changed_p4k = p4k_path and p4k_path != state.cfg["p4k_path"]
    if check_updates in ("true", "false"):
        state.cfg["check_updates"] = check_updates == "true"
    if p4k_path:
        state.cfg["p4k_path"] = p4k_path
    if export_dir:
        state.cfg["export_dir"] = export_dir
    if blender:
        state.cfg["blender"] = blender
    if appearance in ("system", "light", "dark"):
        state.cfg["appearance"] = appearance
    save_config(state.cfg)
    if changed_p4k:
        threading.Thread(target=state.load, daemon=True).start()
    return status()


@app.post("/api/open-exports")
def open_exports():
    os.makedirs(state.cfg["export_dir"], exist_ok=True)
    if hasattr(os, "startfile"):
        os.startfile(state.cfg["export_dir"])
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
    import webbrowser
    page = (state.update or {}).get("page") or updates.RELEASES_PAGE
    webbrowser.open(page if page.startswith(updates.RELEASES_PAGE) else updates.RELEASES_PAGE)
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
