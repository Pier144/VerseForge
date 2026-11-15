"""Server-side load benchmark: what the viewer asks when it opens a model (info + lite GLB, then every game texture of
its materials, 6 at a time like a browser). Start the server with --no-disk-cache so runs are comparable, e.g.

    python start.py --no-browser --no-disk-cache --port 8771
    python tools/bench_server.py --port 8771 --repeat 2

The first run of a model is "cold" (nothing in memory), later runs show the in-memory cache."""
import argparse, json, sys, time, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor

MODELS = [
    "Objects/fps_weapons/weapons_v7/volt/smg/quartz/esmg_fps_volt_quartz.cdf",
    "Objects/Spaceships/Ships/AEGS/Gladius/AEGS_Gladius.cga",
    "Objects/Spaceships/Ships/RSI/perseus/exterior/rsi_perseus.cga#int",
    "Objects/Spaceships/Ships/ANVL/Carrack/Exterior/ANVL_Carrack.cga#int",
]
B = "http://127.0.0.1:8767"
def get(url):
    with urllib.request.urlopen(B + url, timeout=600) as r:
        return r.read()
def run(path, interior=False, full=False):
    q = f"path={urllib.parse.quote(path)}&full={str(full).lower()}&interior={str(interior).lower()}"
    t0 = time.time()
    with ThreadPoolExecutor(2) as ex:
        fi = ex.submit(get, f"/api/model/info?{q}")
        fg = ex.submit(get, f"/api/model/glb?{q}&tex=true&lite=true")
        info = json.loads(fi.result()); glb = fg.result()
    t1 = time.time()
    urls = set()
    for sh in info["shading"].values():
        for f, kind in (("color_map","color"),("normal_map","normal"),("detail_normal","normal"),("gloss_map","gloss"),("obj_gloss","gloss"),("spec_map","color"),("hal","hal"),("height_map","mask"),("stencil_map","mask")):
            if sh.get(f): urls.add(f"/api/texture?path={urllib.parse.quote(sh[f])}&kind={kind}&size=1024")
    def tex(u):
        try: return len(get(u))
        except Exception: return 0
    with ThreadPoolExecutor(6) as ex:
        sizes = list(ex.map(tex, urls))
    t2 = time.time()
    print(f"{path.rsplit('/',1)[-1]:28s} interior={interior}: model {t1-t0:5.1f}s ({len(glb)/1e6:.0f} MB)  textures {t2-t1:5.1f}s ({len(urls)} files, {sum(sizes)/1e6:.0f} MB)  total {t2-t0:5.1f}s")
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="*", help="geometry paths; add #int for the interior (default: 4 reference models)")
    ap.add_argument("--port", type=int, default=8767)
    ap.add_argument("--repeat", type=int, default=1)
    a = ap.parse_args()
    B = f"http://127.0.0.1:{a.port}"
    for _ in range(a.repeat):
        for spec in a.models or MODELS:
            p, _, flag = spec.partition("#")
            run(p, interior=flag == "int")
