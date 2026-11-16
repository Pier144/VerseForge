"""Images and animations (animated WebP) for the README (docs/readme/), made by driving the app in a headless Edge/Chrome.

    python tools/readme_media.py                 # everything
    python tools/readme_media.py hero backdrops  # only some
Scenes: app (screenshot of the interface), hero (orbit around a ship, interface visible), interiors (section
sliding down a ship), animation (a game animation), backdrops (2x2 grid), paints (2x2 grid of liveries).
Starts the browser version (start.py) on port 8790 unless VERSEFORGE_URL points at a running one.
Frames are captured one at a time (the camera is stepped by hand), so the GIFs are smooth whatever the GPU speed.
"""
import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

import cv2
import numpy as np
import websockets

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "docs", "readme")
W, H = 1600, 900
PORT = 8790
BROWSERS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe"]


class Page:
    def __init__(self, ws):
        self.ws, self.n, self.wait = ws, 0, {}
        self.task = asyncio.create_task(self._read())

    async def _read(self):
        async for raw in self.ws:
            m = json.loads(raw)
            f = self.wait.pop(m.get("id"), None)
            if f and not f.done():
                f.set_result(m)

    async def send(self, method, **params):
        self.n += 1
        f = asyncio.get_running_loop().create_future()
        self.wait[self.n] = f
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        m = await asyncio.wait_for(f, 300)
        if "error" in m:
            raise RuntimeError(f"{method}: {m['error']}")
        return m.get("result", {})

    async def js(self, expr):
        r = await self.send("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        if r.get("exceptionDetails"):
            raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description") or r["exceptionDetails"])
        return r.get("result", {}).get("value")

    async def shot(self, clip=None):
        """One frame, drawn after the page has rendered twice."""
        await self.js("__verseforge.invalidate(100); new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
        p = {"format": "png"}
        if clip:
            p["clip"] = {**clip, "scale": 1}
        data = base64.b64decode((await self.send("Page.captureScreenshot", **p))["data"])
        return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)


# ------------------------------------------------------------------ app helpers
async def find(p, q, cat="ships"):
    items = (await p.js(f"fetch('/api/search?cat={cat}&limit=50&q={q}').then(r => r.json())"))["items"]
    exact = [it for it in items if it["name"].lower() == q.lower()]
    if not (exact or items):
        raise RuntimeError(f"model not found: {q}")
    return (exact or items)[0]


async def load(p, item, full=False, interior=False, settle=4.0):
    on = lambda v: json.dumps(v)
    await p.js(f"(() => {{ const s = __verseforge.state(); s.full = {on(full)}; s.interior = {on(interior)};"
               f" document.querySelector('#fullOn').checked = {on(full)}; document.querySelector('#intOn').checked = {on(interior)}; }})()")
    await p.js(f"__verseforge.load({json.dumps(item)})")
    for _ in range(1200):
        await asyncio.sleep(0.1)
        if await p.js("document.querySelector('#loading').classList.contains('hidden')"):
            break
    await asyncio.sleep(settle)                     # progressive textures arrive


async def backdrop(p, kind, settle=2.5):
    await p.js(f"document.querySelector('#bgMenu [data-bg=\"{kind}\"]').click()")
    await asyncio.sleep(settle)


async def light(p, hangar=True):
    if await p.js("__verseforge.state().light") != ("hangar" if hangar else "studio"):
        await p.js("document.querySelector('[data-act=\"light\"]').click()")
        await asyncio.sleep(0.8)


async def ui(p, visible):
    """Hide the panels for clean shots (the camera is re-centred on the whole window)."""
    d = "" if visible else "none"
    await p.js(f"""(() => {{ for (const s of ['.topbar', '.layout > .sidebar', '.layout > .panel', '.floating', '#toasts'])
        document.querySelectorAll(s).forEach(e => e.style.display = '{d}');
        window.dispatchEvent(new Event('resize')); }})()""")
    await asyncio.sleep(0.6)


async def orbit_to(p, yaw_deg, pitch_deg=None, dist_mul=1.0):
    """Place the camera around the controls' target: yaw/pitch in degrees, distance as a multiple of the framed one."""
    await p.js(f"""(() => {{ const v = __verseforge, c = v.camera, t = v.controls.target;
        const off = c.position.clone().sub(t);
        v.__dist = v.__dist || off.length();
        const r = v.__dist * {dist_mul};
        const pitch = {('null' if pitch_deg is None else pitch_deg)};
        const ph = pitch === null ? Math.acos(off.y / off.length()) : (90 - pitch) * Math.PI / 180;
        const th = {yaw_deg} * Math.PI / 180;
        c.position.set(t.x + r * Math.sin(ph) * Math.sin(th), t.y + r * Math.cos(ph), t.z + r * Math.sin(ph) * Math.cos(th));
        c.lookAt(t); v.controls.update(); v.invalidate(100); }})()""")


async def reset_view(p):
    await p.js("__verseforge.frame(); __verseforge.__dist = null;")
    await asyncio.sleep(0.8)


# ------------------------------------------------------------------ output
def save_gif(frames, name, fps=15, width=960, colors=200):
    tmp = tempfile.mkdtemp(prefix="vf_gif_")
    try:
        for i, f in enumerate(frames):
            cv2.imwrite(os.path.join(tmp, f"f{i:04d}.png"), f)
        out = os.path.join(OUT, name)
        src = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-framerate", str(fps), "-i", os.path.join(tmp, "f%04d.png")]
        if name.endswith(".webp"):   # animated WebP: GitHub shows it like a GIF at a fraction of the size
            subprocess.run(src + ["-vf", f"scale={width}:-2:flags=lanczos", "-c:v", "libwebp_anim", "-lossless", "0",
                                  "-q:v", "78", "-compression_level", "6", "-loop", "0", out], check=True)
        else:
            vf = (f"scale={width}:-2:flags=lanczos,split[a][b];[a]palettegen=max_colors={colors}:stats_mode=diff[p];"
                  f"[b][p]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle")
            subprocess.run(src + ["-filter_complex", vf, "-loop", "0", out], check=True)
        print(f"  {name}: {len(frames)} frames, {os.path.getsize(out) / 1e6:.1f} MB")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def save_jpg(img, name, width=None, q=88):
    if width and img.shape[1] != width:
        img = cv2.resize(img, (width, round(img.shape[0] * width / img.shape[1])), interpolation=cv2.INTER_AREA)
    path = os.path.join(OUT, name)
    if name.endswith(".png"):
        cv2.imwrite(path, img, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    else:
        cv2.imwrite(path, img, [cv2.IMWRITE_JPEG_QUALITY, q])
    print(f"  {name}: {img.shape[1]}x{img.shape[0]}, {os.path.getsize(path) / 1e6:.2f} MB")


def label(img, text):
    """Small caption in the bottom-left corner of a tile (Segoe UI Semibold on a dark pill)."""
    from PIL import Image, ImageDraw, ImageFont
    h, w = img.shape[:2]
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\seguisb.ttf", round(h * 0.045))
    except OSError:
        font = ImageFont.load_default()
    im = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)).convert("RGBA")
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = d.textbbox((0, 0), text, font=font)
    pad, m = round(h * 0.022), round(h * 0.03)
    bx, by = m, h - m - (y1 - y0) - 2 * pad
    d.rounded_rectangle((bx, by, bx + (x1 - x0) + 2 * pad, h - m), radius=pad, fill=(10, 12, 18, 170))
    d.text((bx + pad - x0, by + pad - y0), text, font=font, fill=(240, 242, 246, 255))
    im = Image.alpha_composite(im, layer).convert("RGB")
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)


def grid(tiles, cols=2, gap=6):
    h, w = tiles[0].shape[:2]
    rows = (len(tiles) + cols - 1) // cols
    out = np.full((rows * h + (rows - 1) * gap, cols * w + (cols - 1) * gap, 3), 13, np.uint8)
    for i, t in enumerate(tiles):
        r, c = divmod(i, cols)
        out[r * (h + gap):r * (h + gap) + h, c * (w + gap):c * (w + gap) + w] = t
    return out


# ------------------------------------------------------------------ scenes
async def scene_app(p):
    """The interface, dark mode, a ship with its full loadout in the hangar."""
    await ui(p, True)
    await light(p, True)
    await backdrop(p, "plain")
    for name in ("Prowler", "Talon", "Mustang"):           # loadouts that mount completely (no warning)
        await load(p, await find(p, name), full=True, settle=6)
        if (await p.js("__fc_ok = !/not mounted/.test(document.querySelector('#info').textContent) &&"
                       " !document.querySelector('#fullPill').classList.contains('hidden')")):
            break
    print(f"  ship: {name}")
    await backdrop(p, "stanton", 4)
    await reset_view(p)
    await orbit_to(p, 40, 16, 0.8)
    save_jpg(await p.shot(), "app.png")
    await backdrop(p, "plain")


async def scene_hero(p):
    await ui(p, False)
    await light(p, True)
    await load(p, await find(p, "Perseus"), full=True, settle=6)
    await backdrop(p, "stanton", 4)
    await reset_view(p)
    frames = []
    for i in range(120):                             # one turn in 8 s at 15 fps
        await orbit_to(p, 200 + i * 3, 12, 0.52)
        frames.append((await p.shot())[90:810])     # 1600x720: a wide strip
    save_gif(frames, "hero.webp", fps=15, width=1000)


async def scene_interiors(p):
    await ui(p, False)
    await light(p, True)
    await backdrop(p, "plain")
    await load(p, await find(p, "Perseus"), interior=True, settle=6)
    await reset_view(p)
    frames = []
    cuts = [1.0] * 6 + [1.0 - 0.55 * i / 44 for i in range(45)] + [0.45] * 12 + [0.45 + 0.55 * i / 20 for i in range(21)]
    for i, cut in enumerate(cuts):
        await p.js(f"(() => {{ const c = document.querySelector('#cut'); c.value = {round(cut * 1000)};"
                   " c.dispatchEvent(new Event('input')); })()")
        await orbit_to(p, 150 + i * 0.6, 50, 0.5)
        frames.append((await p.shot())[60:840, 210:1390])
    save_gif(frames, "interiors.webp", fps=15, width=800)


async def scene_animation(p):
    """A ship's moving parts: the first canopy / ramp / door / landing gear animation found."""
    await ui(p, False)
    await light(p, True)
    await backdrop(p, "plain")
    for name in ("Gladius", "Hornet", "Arrow", "Constellation"):
        await load(p, await find(p, name), full=True)
        acts = await p.js("__verseforge.anim.list.map(a => ({ id: a.id, group: a.group, label: a.label, d: a.duration }))")
        pick = next((a for g in ("canopy", "ramp", "door", "land") for a in acts
                     if g in a["group"].lower() and a["label"].lower() in ("open", "deploy", "extend", "lower")), None)
        if pick:
            break
    else:
        raise RuntimeError("no ship with a canopy/ramp/door animation found")
    print(f"  animation: {name} {pick['group']} · {pick['label']} ({pick['d']:.1f} s)")
    await reset_view(p)
    # aim at the parts the clip moves (their centre), a little closer than the framed view
    await p.js(f"""(() => {{ const v = __verseforge, a = v.anim.list.find(x => x.id === {json.dumps(pick['id'])});
        const clip = v.anim.clips.get(a.clip), box = new v.camera.position.constructor(), n = {{ c: 0 }};
        const names = new Set(clip.tracks.map(t => t.name.slice(0, t.name.lastIndexOf('.'))));
        const sum = box.set(0, 0, 0).clone();
        v.root.traverse(o => {{ if (names.has(o.name) || names.has(o.uuid)) {{ sum.add(o.getWorldPosition(box.clone())); n.c++; }} }});
        if (n.c) v.controls.target.copy(sum.divideScalar(n.c));
        v.__dist = null; v.controls.update(); }})()""")
    await orbit_to(p, 235, 24, 0.55)
    await p.js(f"document.querySelector('#animGroups [data-id=\"{pick['id']}\"]').click()")
    await asyncio.sleep(0.3)
    # scrub the timeline by hand: open, hold, close again (a smooth loop whatever the capture speed)
    n = round(pick["d"] * 15)
    ts = [0] * 8 + [k / n for k in range(n + 1)] + [1] * 12 + [1 - k / n for k in range(n + 1)] + [0] * 4
    frames = []
    for t in ts:
        await p.js(f"(() => {{ const e = document.querySelector('#animTime'); e.value = {round(t * 1000)};"
                   " e.dispatchEvent(new Event('input')); })()")
        frames.append(await p.shot())
    await p.js("document.querySelector('#animTime').dispatchEvent(new Event('change'))")
    frames = [f[90:810, 160:1440] for f in frames]
    save_gif(frames, "animation.webp", fps=15, width=800)


async def scene_backdrops(p):
    await ui(p, False)
    await light(p, True)
    await load(p, await find(p, "Hornet"), full=True)
    tiles = []
    for kind, text in (("pyro", "Pyro nebula"), ("stanton", "Stanton · Crusader"),
                       ("workbench", "Modelling workshop"), ("studio", "Photo studio")):
        await backdrop(p, kind, 4)
        await reset_view(p)
        await orbit_to(p, 225, 14, 0.85 if kind != "workbench" else 1.0)
        img = await p.shot()
        tiles.append(label(cv2.resize(img, (800, 450), interpolation=cv2.INTER_AREA), text.replace("·", "-")))
    await backdrop(p, "plain")
    save_jpg(grid(tiles), "backdrops.jpg", q=86)


async def scene_paints(p):
    await ui(p, False)
    await light(p, True)
    await backdrop(p, "plain")
    item = await find(p, "Gladius")
    await load(p, item)
    opts = await p.js("[...document.querySelectorAll('#variantSel option')].map(o => [o.value, o.textContent])")
    if not opts:
        raise RuntimeError("no paints for this model")
    step = max(1, len(opts) // 4)
    chosen = opts[::step][:4]
    tiles = []
    for value, text in chosen:
        await p.js(f"(() => {{ const s = document.querySelector('#variantSel'); s.value = {json.dumps(value)};"
                   " s.dispatchEvent(new Event('change')); })()")
        await asyncio.sleep(1.0)
        for _ in range(600):
            await asyncio.sleep(0.1)
            if await p.js("document.querySelector('#loading').classList.contains('hidden')"):
                break
        await asyncio.sleep(3.5)
        await reset_view(p)
        await orbit_to(p, 230, 20, 0.8)
        img = await p.shot()
        tiles.append(label(cv2.resize(img, (800, 450), interpolation=cv2.INTER_AREA), text.strip()[:40]))
    save_jpg(grid(tiles), "paints.jpg", q=86)


SCENES = {"app": scene_app, "hero": scene_hero, "interiors": scene_interiors, "animation": scene_animation,
          "backdrops": scene_backdrops, "paints": scene_paints}


# ------------------------------------------------------------------ main
def start_server():
    url = os.environ.get("VERSEFORGE_URL")
    try:                                              # already running on our port
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/search?limit=1", timeout=1)
        return f"http://127.0.0.1:{PORT}/", None
    except OSError:
        pass
    if url:
        return url.rstrip("/") + "/", None
    proc = subprocess.Popen([sys.executable, os.path.join(HERE, "start.py"), "--port", str(PORT), "--no-browser"],
                            cwd=HERE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(600):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/search?limit=1", timeout=1)
            return f"http://127.0.0.1:{PORT}/", proc
        except OSError:
            time.sleep(0.5)
    proc.kill()
    raise RuntimeError("the server did not start")


async def main(names):
    os.makedirs(OUT, exist_ok=True)
    url, server = start_server()
    browser = next(b for b in BROWSERS if os.path.exists(b))
    profile = tempfile.mkdtemp(prefix="vf_readme_")
    port = 9244
    proc = subprocess.Popen([browser, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
                             f"--window-size={W},{H}", "--hide-scrollbars", "--mute-audio", "--no-first-run",
                             "--disable-extensions", "--ignore-gpu-blocklist", "--force-device-scale-factor=1",
                             "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1))
                if pages:
                    break
            except OSError:
                time.sleep(0.2)
        page = next(t for t in pages if t["type"] == "page")
        p = Page(await websockets.connect(page["webSocketDebuggerUrl"], max_size=None))
        await p.send("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=1, mobile=False)
        # dark mode, game textures on, plain grid
        await p.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])
        await p.send("Page.navigate", url=url)
        for _ in range(600):
            await asyncio.sleep(0.2)
            try:
                if await p.js("!!window.__verseforge && document.readyState === 'complete'"):
                    break
            except RuntimeError:
                pass
        await asyncio.sleep(2)
        await p.js("document.querySelectorAll('.update-pill').forEach(e => e.remove())")
        for n in names:
            print(n)
            await SCENES[n](p)
    finally:
        proc.kill()
        if server:
            server.kill()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    names = sys.argv[1:] or list(SCENES)
    bad = [n for n in names if n not in SCENES]
    if bad:
        sys.exit(f"unknown scenes: {bad}; choose from {list(SCENES)}")
    asyncio.run(main(names))
