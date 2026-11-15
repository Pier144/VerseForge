"""Server-side load benchmark: what the viewer asks when it opens a model (info + lite GLB, then every game texture of
its materials, 6 at a time like a browser). Start the server with --no-disk-cache so runs are comparable, e.g.

    python start.py --no-browser --no-disk-cache --port 8771
    python tools/bench_server.py --port 8771 --repeat 2
    python tools/bench_server.py --port 8771 --gpu s3tc,rgtc,bptc     # textures as GPU blocks where possible

The first run of a model is "cold" (nothing in memory), later runs show the in-memory cache.
--textures also prints per-texture times, the formats received and the estimated GPU memory (VRAM) of the textures:
JPEG/PNG become RGBA8 with a full mip chain (x 4/3), DDS keeps its blocks and the mips it carries."""
import argparse, io, json, statistics, struct, sys, time, urllib.request, urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

MODELS = [
    "Objects/fps_weapons/weapons_v7/volt/smg/quartz/esmg_fps_volt_quartz.cdf",
    "Objects/Spaceships/Ships/AEGS/Gladius/AEGS_Gladius.cga",
    "Objects/Spaceships/Ships/RSI/perseus/exterior/rsi_perseus.cga#int",
    "Objects/Spaceships/Ships/ANVL/Carrack/Exterior/ANVL_Carrack.cga#int",
]
B = "http://127.0.0.1:8767"
DXGI_NAMES = {71: "BC1", 72: "BC1", 74: "BC2", 75: "BC2", 77: "BC3", 78: "BC3", 80: "BC4", 81: "BC4s", 83: "BC5",
              84: "BC5s", 98: "BC7", 99: "BC7"}


def get(url, zstd=False):
    """Body (unpacked) and content type; with zstd=True also accepts zstd like a browser (wire bytes in WIRE)."""
    req = urllib.request.Request(B + url, headers={"Accept-Encoding": "zstd"} if zstd else {})
    with urllib.request.urlopen(req, timeout=600) as r:
        data = r.read()
        WIRE.append(len(data))
        if r.headers.get("Content-Encoding") == "zstd":
            import zstandard
            data = zstandard.ZstdDecompressor().decompressobj().decompress(data)
        return data, r.headers.get("Content-Type", "")


WIRE = []


def image_info(data, ctype):
    """(label, VRAM bytes) of one texture answer."""
    if data[:4] == b"DDS ":
        h, w, _p, _d, mips = struct.unpack_from("<5I", data, 12)
        dxgi = struct.unpack_from("<I", data, 128)[0]
        return DXGI_NAMES.get(dxgi, f"dxgi{dxgi}"), len(data) - 148     # payload = all mips as on the GPU
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    return ("png" if "png" in ctype else "jpg"), im.width * im.height * 4 * 4 // 3


def run(path, interior=False, full=False, gpu="", detail=False):
    q = f"path={urllib.parse.quote(path)}&full={str(full).lower()}&interior={str(interior).lower()}"
    t0 = time.time()
    with ThreadPoolExecutor(2) as ex:
        fi = ex.submit(get, f"/api/model/info?{q}")
        fg = ex.submit(get, f"/api/model/glb?{q}&tex=true&lite=true")
        info = json.loads(fi.result()[0]); glb = fg.result()[0]
    t1 = time.time()
    urls = set()
    extra = f"&gpu={gpu}" if gpu else ""
    for sh in info["shading"].values():
        for f, kind in (("color_map","color"),("normal_map","normal"),("detail_normal","normal"),("gloss_map","gloss"),("obj_gloss","gloss"),("spec_map","color"),("hal","hal"),("height_map","mask"),("stencil_map","mask")):
            if sh.get(f): urls.add(f"/api/texture?path={urllib.parse.quote(sh[f])}&kind={kind}&size=1024{extra}")

    def tex(u):
        s = time.time()
        try:
            data, ctype = get(u, zstd=bool(gpu))
        except Exception:
            return 0, time.time() - s, None, 0, u
        label, vram = image_info(data, ctype) if detail else ("", 0)
        return len(data), time.time() - s, label, vram, u
    WIRE.clear()
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(tex, sorted(urls)))
    t2 = time.time()
    sizes = [r[0] for r in res]
    wire = sum(WIRE)
    print(f"{path.rsplit('/',1)[-1]:28s} interior={interior}: model {t1-t0:5.1f}s ({len(glb)/1e6:.0f} MB)  textures {t2-t1:5.1f}s ({len(urls)} files, {sum(sizes)/1e6:.0f} MB, {wire/1e6:.0f} MB sent)  total {t2-t0:5.1f}s")
    if detail:
        times = [r[1] for r in res if r[2]]
        kinds = Counter()
        for r in res:
            if r[2]:
                kinds[(r[4].split("kind=")[1].split("&")[0], r[2])] += 1
        print(f"    per texture: mean {statistics.mean(times)*1000:.0f} ms, median {statistics.median(times)*1000:.0f} ms,"
              f" max {max(times)*1000:.0f} ms   missing {sum(1 for r in res if not r[2])}")
        print(f"    VRAM estimate {sum(r[3] for r in res)/2**20:.0f} MiB   formats: "
              + ", ".join(f"{k}/{f} {n}" for (k, f), n in sorted(kinds.items())))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="*", help="geometry paths; add #int for the interior (default: 4 reference models)")
    ap.add_argument("--port", type=int, default=8767)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--gpu", default="", help="compressed formats the client accepts, e.g. s3tc,rgtc,bptc")
    ap.add_argument("--textures", action="store_true", help="per-texture times, formats and VRAM estimate")
    a = ap.parse_args()
    B = f"http://127.0.0.1:{a.port}"
    for _ in range(a.repeat):
        for spec in a.models or MODELS:
            p, _, flag = spec.partition("#")
            run(p, interior=flag == "int", gpu=a.gpu, detail=a.textures)
