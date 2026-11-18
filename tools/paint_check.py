"""Instant paint switching, checked in a headless Edge/Chrome without touching the user's screen (the same way as
readme_media.py). Opens the Perseus with Full ship + Interiors and runs the checks named on the command line:
  frames  draw calls and milliseconds per frame (median of 5 medians, each of 60 frames drawn by hand)
  paint   paint changes: time to the first frame with the new paint (seen and never seen), no loading screen, camera,
          pose and section unchanged, compare with stock and back, resin look on during a change
  menu    picks a livery, then a picture of the panel closed and opened (docs/anteprime/menu-vernici-app.png)
    python tools/paint_check.py frames --save   # before the work: writes the baseline next to the plan
    python tools/paint_check.py frames paint    # after: compares with the baseline
Starts its own server (start.py, port 8791, disk cache off so the shared cache of the installed app is left alone).
Exits with 1 when a target of the spec is missed (docs/superpowers/specs/2026-11-18-vernici-istantanee-design.md)."""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

import websockets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import readme_media as rm  # noqa: E402  (Page, find, load, BROWSERS)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(HERE, "docs", "superpowers", "plans", "2026-11-18-vernici-istantanee.baseline.json")
PORT, DEVTOOLS = 8791, 9245
W, H = 1600, 900
failures = []


def fail(msg):
    failures.append(msg)
    print("  FAIL", msg)


def start_server():
    env = {**os.environ, "VERSEFORGE_DISK_CACHE": "0"}
    proc = subprocess.Popen([sys.executable, os.path.join(HERE, "start.py"), "--port", str(PORT), "--no-browser"],
                            cwd=HERE, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(600):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/search?limit=1", timeout=1)
            return proc
        except OSError:
            time.sleep(0.5)
    proc.kill()
    raise RuntimeError("the server did not start")


FRAMES_JS = """(async () => { const v = __verseforge, r = v.renderer, meds = [];
  for (let k = 0; k < 5; k++) {                     // headless GPU timings wobble: median of 5 medians
    const t = [];
    for (let i = 0; i < 60; i++) { const a = performance.now(); r.render(v.scene, v.camera); r.getContext().finish();
      t.push(performance.now() - a); }
    t.sort((a, b) => a - b); meds.push(t[30]); }
  meds.sort((a, b) => a - b); return { calls: r.info.render.calls, ms: meds[2] }; })()"""


async def frames(p, save):
    got = await p.js(FRAMES_JS)
    print(f"  draw calls {got['calls']}, {got['ms']:.2f} ms per frame")
    if save:
        with open(BASELINE, "w", encoding="utf-8") as f:
            json.dump(got, f, indent=2)
        print(f"  saved {BASELINE}")
        return
    if not os.path.exists(BASELINE):
        fail("no baseline: run `frames --save` before the work")
        return
    base = json.load(open(BASELINE, encoding="utf-8"))
    print(f"  baseline: {base['calls']} calls, {base['ms']:.2f} ms")
    # +15 %: accepted on 19/11/2026, hull and interior pieces with the same material stay in separate batches because
    # only the hull changes with the paint (spec, "Rischi")
    if got["calls"] > base["calls"] * 1.15:
        fail(f"draw calls {got['calls']} > baseline {base['calls']} + 15 %")
    if got["ms"] > base["ms"] * 1.10 + 0.3:          # 0.3 ms of slack: medians of a headless GPU still wobble
        fail(f"{got['ms']:.2f} ms per frame > baseline {base['ms']:.2f} + 10 %")


async def menu(p):
    """The panel with a livery chosen (so Compare with stock shows), closed and with the menu open, side by side."""
    import cv2
    import numpy as np
    before = await p.js("__verseforge.stats.paints || 0")
    await p.js("document.querySelector('#info .dd-btn').click()")
    await asyncio.sleep(0.4)
    await p.js("(() => { const v = __verseforge.info.variants, i = v.findIndex(x => /adamantine/i.test(x.label));"
               " document.querySelectorAll('#info .dd-list li')[i >= 0 ? i : v.findIndex(x => !x.stock)].click(); })()")
    for _ in range(300):                              # the swap, or a reload when the model cannot swap
        if (await p.js("(__verseforge.stats.paints || 0) > " + str(before) +
                       " || !document.querySelector('#loading').classList.contains('hidden')")):
            break
        await asyncio.sleep(0.1)
    for _ in range(600):
        if await p.js("document.querySelector('#loading').classList.contains('hidden')"):
            break
        await asyncio.sleep(0.1)
    await asyncio.sleep(1.0)
    box = await p.js("(() => { const r = document.querySelector('.layout > .panel').getBoundingClientRect();"
                     " return { x: r.x, y: r.y, width: r.width, height: Math.min(r.height, 640) }; })()")
    closed = await p.shot(box)
    await p.js("document.querySelector('#info .dd-btn').click()")
    await asyncio.sleep(0.4)
    opened = await p.shot(box)
    await p.js("document.querySelector('#info .dd-btn').click()")
    gap = np.full((closed.shape[0], 24, 3), closed[0, 0], np.uint8)
    out = os.path.join(HERE, "docs", "anteprime", "menu-vernici-app.png")
    cv2.imwrite(out, np.hstack([closed, gap, opened]))
    if not await p.js("!!document.querySelector('#cmpStock')"):
        fail("no Compare with stock button under the paint menu")
    print(f"  saved {out}")


STATE_JS = """(() => { const v = __verseforge, c = v.camera.position, t = v.controls.target;
  return { cam: [c.x, c.y, c.z, t.x, t.y, t.z].map(x => +x.toFixed(4)), cut: v.state().cut,
           pose: [...v.anim.actions.values()].map(a => +a.time.toFixed(3)) }; })()"""

SWAP_JS = """(async (tag, keep) => { const v = __verseforge, n = v.stats.paints || 0, t = performance.now();
  await v.changePaint(tag, { keepChoice: keep });
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  return { ms: performance.now() - t, swapped: (v.stats.paints || 0) > n }; })"""

WRONG_JS = """(() => { const v = __verseforge, ps = v.paint, built = ps.paints.get(ps.current); let bad = 0;
  for (const [g, m] of built.mats) {
    for (const o of ps.meshes.get(g) || []) if ((o.userData.gameMaterial || o.material) !== m) bad++;
    for (const b of v.batches.byGroup(g)) if ((b.userData.gameMaterial || b.material) !== m) bad++; }
  return bad; })()"""


async def paint(p):
    await p.js("""(() => { const L = document.querySelector('#loading'); window.__sawLoading = false;
      new MutationObserver(() => { if (!L.classList.contains('hidden')) window.__sawLoading = true; })
        .observe(L, { attributes: true, attributeFilter: ['class'] }); })()""")
    if not await p.js("!!__verseforge.paint"):
        fail("the Perseus is not swappable (no PaintSwap): check keyed_glb in /api/model/info")
        return
    tags = await p.js("[...document.querySelectorAll('#variantSel option')].map(o => o.value)")
    first = await p.js("__verseforge.state().variant")
    stock = await p.js("(__verseforge.info.variants.find(v => v.stock) || {}).tag || null")
    others = [t for t in tags if t not in (first, stock)]
    if len(others) < 5:
        fail(f"the Perseus has too few paints for this check: {tags}")
        return
    a, b = others[0], others[4]                   # two paints never shown yet
    before = await p.js(STATE_JS)

    async def swap(tag, target, label, keep=False):
        r = await p.js(f"({SWAP_JS})({json.dumps(tag)}, {json.dumps(keep)})")
        print(f"  {label}: {r['ms']:.0f} ms" + ("" if r["swapped"] else " (NOT swapped)"))
        if not r["swapped"]:
            fail(f"{label}: reloaded instead of swapping")
        elif r["ms"] > target:
            fail(f"{label}: {r['ms']:.0f} ms > {target} ms")

    await swap(a, 1500, "never seen paint")
    await swap(b, 1500, "another never seen paint")
    await swap(a, 300, "back to a seen paint")
    await swap(first, 300, "back to the paint loaded first")
    if await p.js("window.__sawLoading"):
        fail("the loading screen showed during paint changes")
    after = await p.js(STATE_JS)
    for k in ("cam", "cut", "pose"):
        if before[k] != after[k]:
            fail(f"{k} changed: {before[k]} -> {after[k]}")
    if await p.js(WRONG_JS):
        fail("some pieces do not show the current paint's material")
    # Compare with stock: the chosen paint stays chosen
    await p.js(f"(() => {{ const s = document.querySelector('#variantSel'); s.value = {json.dumps(b)};"
               " s.dispatchEvent(new Event('change')); })()")
    for _ in range(100):
        if await p.js(f"__verseforge.paint.current === {json.dumps(b)}"):
            break
        await asyncio.sleep(0.05)
    if await p.js("!!document.querySelector('#cmpStock')"):
        n = await p.js("__verseforge.stats.paints")
        await p.js("document.querySelector('#cmpStock').click()")
        for _ in range(100):
            if await p.js(f"__verseforge.stats.paints > {n}"):
                break
            await asyncio.sleep(0.05)
        if await p.js("__verseforge.state().variant") != b or await p.js("__verseforge.paint.current") != stock:
            fail("Compare with stock changed the chosen paint, or did not show the stock one")
        await p.js("document.querySelector('#cmpStock').click()")
        await asyncio.sleep(0.5)
        if await p.js("__verseforge.paint.current") != b:
            fail("Compare with stock did not come back to the chosen paint")
    else:
        fail("no Compare with stock button on the Perseus")
    # resin look on during a change: switching it off must show the new paint (`a` was shown a moment ago: kept)
    await p.js("document.querySelector('#resinMenu [data-resin=\"grey\"]').click()")
    await asyncio.sleep(0.5)
    await swap(stock or a, 300, "paint change with the resin look on")
    await p.js("document.querySelector('#resinMenu [data-resin=\"off\"]').click()")
    await asyncio.sleep(0.5)
    if await p.js(WRONG_JS):
        fail("after the resin look the pieces do not show the current paint")


CHECKS = {"frames": frames, "menu": menu, "paint": paint}


async def main(names, save):
    server = start_server()
    browser = next(b for b in rm.BROWSERS if os.path.exists(b))
    profile = tempfile.mkdtemp(prefix="vf_paint_")
    proc = subprocess.Popen([browser, "--headless=new", f"--remote-debugging-port={DEVTOOLS}", f"--user-data-dir={profile}",
                             f"--window-size={W},{H}", "--hide-scrollbars", "--mute-audio", "--no-first-run",
                             "--disable-extensions", "--ignore-gpu-blocklist", "--force-device-scale-factor=1",
                             "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        pages = []
        for _ in range(100):
            try:
                pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{DEVTOOLS}/json", timeout=1))
                if pages:
                    break
            except OSError:
                time.sleep(0.2)
        page = next(t for t in pages if t["type"] == "page")
        p = rm.Page(await websockets.connect(page["webSocketDebuggerUrl"], max_size=None))
        await p.send("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=1, mobile=False)
        await p.send("Page.navigate", url=f"http://127.0.0.1:{PORT}/")
        for _ in range(600):
            await asyncio.sleep(0.2)
            try:
                if await p.js("!!window.__verseforge && document.readyState === 'complete'"):
                    break
            except RuntimeError:
                pass
        for _ in range(900):                          # the catalogue loads in the background
            if (await p.js("fetch('/api/status').then(r => r.json())"))["ready"]:
                break
            await asyncio.sleep(1)
        if not await p.js("(() => { const s = __verseforge.state(); return s.tex && s.look; })()"):
            fail("the game look is off in this browser profile: the targets assume it on")
        item = await rm.find(p, "perseus")
        print("loading the Perseus with Full ship + Interiors")
        await rm.load(p, item, full=True, interior=True, settle=6.0)
        for n in names:
            print(n)
            await CHECKS[n](p, save) if n == "frames" else await CHECKS[n](p)
    finally:
        proc.kill()
        server.kill()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    names = args or ["frames"]
    bad = [n for n in names if n not in CHECKS]
    if bad:
        sys.exit(f"unknown checks: {bad}; choose from {list(CHECKS)}")
    asyncio.run(main(names, "--save" in sys.argv))
    print("FAILED" if failures else "OK")
    sys.exit(1 if failures else 0)
