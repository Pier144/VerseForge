"""Load time and frame time of big ships in the viewer, driven in a headless Edge/Chrome (same harness as readme_media).

    set VERSEFORGE_URL=http://127.0.0.1:8767        (a running app; otherwise one is started)
    python tools/bench_ships.py out.json [ship ...]

For each ship, as the app opens it (Full ship on) and with Interiors on: seconds until the loading screen goes away,
then 90 frames of a slow orbit drawn one by one: CPU time of renderer.render() and the time until the GPU has drawn it
(a one pixel readPixels), at 1600x900 and at 3840x2160, plus draw calls, triangles, meshes, textures and the JS heap.
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import readme_media as rm

OUT = sys.argv[1]
SHIPS = sys.argv[2:] or ["Perseus", "Carrack", "Polaris", "Idris-M", "Idris-P", "890 Jump", "Reclaimer", "Hammerhead", "Javelin",
                         "Kraken", "Hull C", "Starlancer TAC", "Odyssey", "Liberator", "Ironclad", "Paladin", "Hermes"]

FRAMES = """(async () => {
  const v = __verseforge, r = v.renderer, gl = r.getContext(), c = v.camera, t = v.controls.target;
  const off = c.position.clone().sub(t), R = Math.hypot(off.x, off.z), a0 = Math.atan2(off.x, off.z);
  const cpu = [], all = [], px = new Uint8Array(4);
  for (let i = 0; i < 100; i++) {
    const a = a0 + i * 0.01;
    c.position.set(t.x + R * Math.sin(a), c.position.y, t.z + R * Math.cos(a));
    c.lookAt(t); c.updateMatrixWorld();
    const s = performance.now();
    r.render(v.scene, c);
    const m = performance.now();
    gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);      // waits for the GPU (gl.finish() does not, in Chromium)
    const e = performance.now();
    if (i >= 10) { cpu.push(m - s); all.push(e - s); }
    if (i % 10 === 9) await new Promise((ok) => setTimeout(ok, 0));
  }
  const mean = all.reduce((p, q) => p + q, 0) / all.length;
  const med = (x) => x.sort((p, q) => p - q)[x.length >> 1], p95 = (x) => x[Math.floor(x.length * 0.95)];
  let meshes = 0;
  v.root.traverse((o) => { if (o.isMesh && o.visible) meshes++; });
  c.position.set(t.x + off.x, c.position.y, t.z + off.z); c.lookAt(t); v.controls.update(); v.invalidate(100);
  return { mean, cpu: med(cpu), cpu95: p95(cpu), frame: med(all), frame95: p95(all), calls: r.info.render.calls, tris: r.info.render.triangles,
    meshes, batches: v.batches?.list?.length ?? null, textures: r.info.memory.textures, geometries: r.info.memory.geometries,
    heapMB: performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1048576) : null };
})()"""
GPU = """(() => { const gl = __verseforge.renderer.getContext(), e = gl.getExtension('WEBGL_debug_renderer_info');
  return e ? gl.getParameter(e.UNMASKED_RENDERER_WEBGL) : 'unknown'; })()"""


async def size(p, w, h):
    await p.send("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=False)
    await p.js("window.dispatchEvent(new Event('resize'))")
    await asyncio.sleep(1.0)


async def timed_load(p, item, interior):
    await p.js(f"(() => {{ const s = __verseforge.state(); s.full = true; s.interior = {json.dumps(interior)};"
               f" document.querySelector('#fullOn').checked = true; document.querySelector('#intOn').checked = {json.dumps(interior)}; }})()")
    t = time.time()
    await p.js(f"void __verseforge.load({json.dumps(item)})")
    await asyncio.sleep(0.3)
    for _ in range(6000):
        if await p.js("document.querySelector('#loading').classList.contains('hidden')"):
            break
        await asyncio.sleep(0.05)
    secs = time.time() - t
    await asyncio.sleep(6.0)                                    # progressive textures
    return round(secs, 1)


async def scene(p):
    res = {"gpu": await p.js(GPU), "ships": []}
    print(res["gpu"], flush=True)
    for name in SHIPS:
        try:
            item = await rm.find(p, name)
        except RuntimeError:
            print("not found:", name, flush=True)
            continue
        for interior in (False, True):
            row = {"ship": item["name"], "path": item["path"], "interior": interior}
            try:
                await size(p, 1600, 900)
                row["load_s"] = await timed_load(p, item, interior)
                info = await p.js("(() => { const i = __verseforge.info; return i ? { tri: i.stats.triangles, parts: i.stats.parts, mats: i.stats.materials.length, int: !!i.interior, can: !!i.can_interior } : null; })()")
                row["info"] = info
                if interior and not (info and info["int"]):
                    print(item["name"], "no interior", flush=True)
                    continue
                await rm.reset_view(p)
                row["hd"] = await p.js(FRAMES)
                await size(p, 3840, 2160)
                await rm.reset_view(p)
                row["uhd"] = await p.js(FRAMES)
                row["errors"] = await p.js("(window.__errs || []).length")
            except Exception as e:                              # one ship failing must not lose the others
                row["error"] = str(e)[:300]
            res["ships"].append(row)
            print(json.dumps(row), flush=True)
            json.dump(res, open(OUT, "w"), indent=1)

# extra browser switches, e.g. BENCH_BROWSER_ARGS=--force_high_performance_gpu (headless picks the integrated GPU)
_popen = rm.subprocess.Popen
rm.subprocess.Popen = lambda cmd, **kw: _popen(cmd[:-1] + os.environ.get("BENCH_BROWSER_ARGS", "").split() + cmd[-1:], **kw)
rm.SCENES = {"x": scene}
asyncio.run(rm.main(["x"]))
