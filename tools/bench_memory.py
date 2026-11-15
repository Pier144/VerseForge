"""Server memory benchmark (Windows): starts its own server, opens big models one after another the way the viewer
does (info + lite GLB + every game texture) and prints the process memory after each step, then reopens the first
ones to show what the in-memory caches still hold.

    python tools/bench_memory.py --port 8776                 # no disk cache (start.py --no-disk-cache)
    python tools/bench_memory.py --port 8776 --disk-cache    # disk cache on, in a throw-away folder

--disk-cache points LOCALAPPDATA of the server at a temporary folder, so the user's own cache is left alone (the first
start then rebuilds the archive index there, which takes a little longer)."""
import argparse, ctypes, ctypes.wintypes as wt, json, os, shutil, subprocess, sys, tempfile, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B = "http://127.0.0.1:8776"


class PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t), ("PrivateUsage", ctypes.c_size_t)]


def memory(pid):
    """(working set, private bytes, peak private bytes) in MB."""
    k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    h = k32.OpenProcess(0x1000 | 0x0010, False, pid)
    try:
        c = PMC()
        c.cb = ctypes.sizeof(PMC)
        psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb)
        return c.WorkingSetSize / 2 ** 20, c.PrivateUsage / 2 ** 20, c.PeakPagefileUsage / 2 ** 20
    finally:
        k32.CloseHandle(h)


def get(url):
    with urllib.request.urlopen(B + url, timeout=900) as r:
        return r.read()


def open_model(path, interior=False, full=False):
    """What the viewer asks for one model; returns (seconds, GLB MB, number of textures)."""
    q = f"path={urllib.parse.quote(path)}&full={str(full).lower()}&interior={str(interior).lower()}"
    t0 = time.time()
    with ThreadPoolExecutor(2) as ex:
        fi = ex.submit(get, f"/api/model/info?{q}")
        fg = ex.submit(get, f"/api/model/glb?{q}&tex=true&lite=true")
        info, glb = json.loads(fi.result()), fg.result()
    urls = set()
    for sh in info["shading"].values():
        for f, kind in (("color_map", "color"), ("normal_map", "normal"), ("detail_normal", "normal"),
                        ("gloss_map", "gloss"), ("obj_gloss", "gloss"), ("spec_map", "color"), ("hal", "hal"),
                        ("height_map", "mask"), ("stencil_map", "mask")):
            if sh.get(f):
                urls.add(f"/api/texture?path={urllib.parse.quote(sh[f])}&kind={kind}&size=1024")

    def tex(u):
        try:
            return len(get(u))
        except Exception:
            return 0
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(tex, urls))
    return time.time() - t0, len(glb) / 1e6, len(urls)


def main():
    global B
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8776)
    ap.add_argument("--disk-cache", action="store_true")
    ap.add_argument("--label", default="")
    ap.add_argument("--model-mb", type=int, default=0, help="memory budget of the built models (0 = the default)")
    ap.add_argument("--root", default=ROOT, help="source tree to run the server from (e.g. an export of main)")
    a = ap.parse_args()
    B = f"http://127.0.0.1:{a.port}"
    env, tmp = dict(os.environ), None
    cmd = [sys.executable, os.path.join(a.root, "start.py"), "--no-browser", "--port", str(a.port)]
    if a.model_mb:
        env["VERSEFORGE_MODEL_MB"] = str(a.model_mb)
    if a.disk_cache:
        env["LOCALAPPDATA"] = tmp = tempfile.mkdtemp(prefix="vf_bench_cache_")
    else:
        cmd.append("--no-disk-cache")
    proc = subprocess.Popen(cmd, cwd=a.root, env=env)
    try:
        while True:
            time.sleep(1)
            try:
                st = json.loads(get("/api/status"))
            except Exception:
                continue
            if st.get("ready"):
                break
            if st.get("error"):
                raise SystemExit(st["error"])
        polaris = next(it["path"] for it in json.loads(get("/api/search?q=Polaris&limit=50"))["items"]
                       if it["path"].lower().endswith(".cga") and "/exterior/" in it["path"].lower())
        P = {"Polaris int": (polaris, True, False),
             "Perseus int": ("Objects/Spaceships/Ships/RSI/perseus/exterior/rsi_perseus.cga", True, False),
             "Carrack int": ("Objects/Spaceships/Ships/ANVL/Carrack/Exterior/ANVL_Carrack.cga", True, False),
             "Gladius full": ("Objects/Spaceships/Ships/AEGS/Gladius/AEGS_Gladius.cga", False, True),
             "Quartz": ("Objects/fps_weapons/weapons_v7/volt/smg/quartz/esmg_fps_volt_quartz.cdf", False, False)}
        seq = ["Polaris int", "Perseus int", "Carrack int", "Gladius full", "Quartz",
               "Quartz", "Gladius full", "Polaris int", "Perseus int", "Carrack int"]
        ws, pb, _ = memory(proc.pid)
        print(f"# {a.label} disk_cache={a.disk_cache} polaris={polaris}")
        print(f"| step | model | time s | GLB MB | textures | working set MB | private MB | peak private MB | models kept (est. MB) | textures MB |")
        print(f"|---|---|---|---|---|---|---|---|---|---|")
        print(f"| 0 | (ready) | | | | {ws:.0f} | {pb:.0f} | | | |")
        for i, name in enumerate(seq, 1):
            p, interior, full = P[name]
            t, mb, nt = open_model(p, interior, full)
            ws, pb, peak = memory(proc.pid)
            mem = json.loads(get("/api/status")).get("memory")      # only servers with the memory budget report it
            kept = f"{mem['models']} ({mem['models_bytes'] / 2 ** 20:.0f})" if mem else ""
            tex = f"{mem['textures_bytes'] / 2 ** 20:.0f}" if mem else ""
            print(f"| {i} | {name} | {t:.2f} | {mb:.0f} | {nt} | {ws:.0f} | {pb:.0f} | {peak:.0f} | {kept} | {tex} |", flush=True)
    finally:
        proc.terminate()
        proc.wait()
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
