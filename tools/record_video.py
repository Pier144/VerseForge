"""Record scripted demo videos of VerseForge.

Drives a headless Edge/Chrome through the DevTools protocol, captures the page with Page.startScreencast,
draws a visible cursor + captions inside the page, and encodes an H.264 MP4 with OpenCV (Windows Media Foundation).

    python tools/record_video.py                   # the two tutorial videos (search, export) into docs/video
    python tools/record_video.py search            # only one
    python tools/record_video.py demo_en           # short presentation of the program
    python tools/record_video.py demo_en_notext    # the same without captions, only opening and closing titles
Requires the app running on http://127.0.0.1:8765 (start.py); another address with VERSEFORGE_URL.
The scenes rely on element ids and data attributes (#q, #results li, [data-exp], [data-act], #btnPrint, #btnSettings…),
never on interface text.
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

APP = os.environ.get("VERSEFORGE_URL", "http://127.0.0.1:8765/").rstrip("/") + "/"
W, H, FPS = 1600, 900, 30
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(HERE, "docs", "video")
# the print job is done when its download link appears (independent of the interface text)
PRINT_DONE = "!!document.querySelector('#printStatus a[href]')"
BROWSERS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe"]

OVERLAY_JS = r"""
(() => {
  if (window.__demo) return;
  window.__demo = true;
  const st = document.createElement('style');
  st.textContent = `
    #demoCursor{position:fixed;left:0;top:0;width:26px;height:26px;z-index:99999;pointer-events:none;transform:translate(-3px,-2px);
      filter:drop-shadow(0 2px 3px #000a);transition:none}
    .demoRipple{position:fixed;width:44px;height:44px;margin:-22px 0 0 -22px;border-radius:50%;border:3px solid #40c4ff;
      z-index:99998;pointer-events:none;animation:demoR .55s ease-out forwards}
    @keyframes demoR{from{transform:scale(.3);opacity:1}to{transform:scale(1.4);opacity:0}}
    #demoCap{position:fixed;left:50%;bottom:64px;transform:translateX(-50%);z-index:99997;pointer-events:none;
      background:rgba(8,14,20,.88);border:1px solid #40c4ff;color:#fff;font:600 22px "Segoe UI",sans-serif;
      padding:12px 22px;border-radius:10px;box-shadow:0 10px 40px #000c;max-width:80vw;text-align:center;
      opacity:0;transition:opacity .35s}
    #demoCap.on{opacity:1}
    #demoCap small{display:block;font-weight:400;font-size:15px;color:#9fb6c8;margin-top:4px}
    #demoTitle{position:fixed;inset:0;z-index:99996;display:flex;flex-direction:column;align-items:center;justify-content:center;
      background:radial-gradient(ellipse at center,#14212d 0%,#06090c 80%);color:#fff;font-family:"Segoe UI",sans-serif;
      transition:opacity .6s;pointer-events:none}
    #demoTitle h1{font-size:54px;margin:0 0 10px}#demoTitle h1 span{color:#40c4ff}
    #demoTitle p{font-size:24px;color:#9fb6c8;margin:0}`;
  document.head.appendChild(st);
  const c = document.createElement('div');
  c.id = 'demoCursor';
  c.innerHTML = '<svg viewBox="0 0 24 24" width="26" height="26"><path d="M3 2l7.5 19 2.6-7.6L21 10.8z" fill="#fff" stroke="#000" stroke-width="1.4" stroke-linejoin="round"/></svg>';
  document.body.appendChild(c);
  const cap = document.createElement('div'); cap.id = 'demoCap'; document.body.appendChild(cap);
  const mv = (e) => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; };
  window.addEventListener('pointermove', mv, true);
  window.addEventListener('mousemove', mv, true);
  window.addEventListener('pointerdown', (e) => {
    const r = document.createElement('div'); r.className = 'demoRipple';
    r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
    document.body.appendChild(r); setTimeout(() => r.remove(), 700);
  }, true);
  window.__cap = (t, s) => {
    if (!t) { cap.classList.remove('on'); return; }
    cap.innerHTML = t + (s ? `<small>${s}</small>` : ''); cap.classList.add('on');
  };
  window.__title = (t, s) => {
    let d = document.getElementById('demoTitle');
    if (!t) { if (d) { d.style.opacity = 0; setTimeout(() => d.remove(), 700); } return; }
    if (!d) { d = document.createElement('div'); d.id = 'demoTitle'; document.body.appendChild(d); }
    d.innerHTML = `<h1>${t}</h1><p>${s || ''}</p>`; d.style.opacity = 1;
  };
})();
"""


class Page:
    def __init__(self, ws):
        self.ws = ws
        self.seq = 0
        self.pending = {}
        self.frames = []             # (wall time, jpeg bytes)
        self.warps = [(0.0, 1.0)]    # (wall time, playback speed factor)
        self.mouse = (W / 2, H / 2)
        self.reader = asyncio.create_task(self._read())

    async def _read(self):
        async for raw in self.ws:
            msg = json.loads(raw)
            if "id" in msg and msg["id"] in self.pending:
                self.pending.pop(msg["id"]).set_result(msg)
            elif msg.get("method") == "Page.screencastFrame":
                p = msg["params"]
                self.frames.append((time.time(), base64.b64decode(p["data"])))
                asyncio.create_task(self.send("Page.screencastFrameAck", sessionId=p["sessionId"]))

    async def send(self, method, **params):
        self.seq += 1
        fut = asyncio.get_running_loop().create_future()
        self.pending[self.seq] = fut
        await self.ws.send(json.dumps({"id": self.seq, "method": method, "params": params}))
        msg = await fut
        if "error" in msg:
            raise RuntimeError(f"{method}: {msg['error']}")
        return msg.get("result", {})

    async def js(self, expr):
        r = await self.send("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"])
        return r.get("result", {}).get("value")

    # ------------------------------------------------------------ helpers
    async def wait(self, s):
        await asyncio.sleep(s)

    def speed(self, factor):
        self.warps.append((time.time(), factor))

    async def caption(self, text=None, sub=None):
        await self.js(f"window.__cap({json.dumps(text)}, {json.dumps(sub)})")

    async def title(self, text=None, sub=None):
        await self.js(f"window.__title({json.dumps(text)}, {json.dumps(sub)})")

    async def center(self, selector, index=0):
        r = await self.js(f"""(() => {{ const els = [...document.querySelectorAll({json.dumps(selector)})];
            const e = els[{index}]; if (!e) return null; e.scrollIntoView({{block:'nearest'}});
            const b = e.getBoundingClientRect(); return [b.left + b.width/2, b.top + b.height/2]; }})()""")
        if r is None:
            raise RuntimeError(f"element not found: {selector}")
        return r

    async def move(self, x, y, duration=0.6, buttons=0):
        x0, y0 = self.mouse
        steps = max(2, int(duration * 60))
        for i in range(1, steps + 1):
            t = i / steps
            e = t * t * (3 - 2 * t)                      # ease in/out
            px, py = x0 + (x - x0) * e, y0 + (y - y0) * e
            await self.send("Input.dispatchMouseEvent", type="mouseMoved", x=px, y=py,
                            button="left" if buttons else "none", buttons=buttons)
            await asyncio.sleep(duration / steps)
        self.mouse = (x, y)

    async def click(self, selector=None, index=0, xy=None, pause=0.25):
        x, y = xy or await self.center(selector, index)
        await self.move(x, y)
        await asyncio.sleep(pause)
        await self.send("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", buttons=1, clickCount=1)
        await asyncio.sleep(0.08)
        await self.send("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button="left", buttons=0, clickCount=1)

    async def click_text(self, selector, text):
        idx = await self.js(f"[...document.querySelectorAll({json.dumps(selector)})].findIndex(e => e.textContent.includes({json.dumps(text)}))")
        if idx is None or idx < 0:
            raise RuntimeError(f"text not found: {text}")
        await self.click(selector, idx)

    async def drag(self, dx, dy, duration=1.2, start=None, button="left"):
        x, y = start or self.mouse
        await self.move(x, y, 0.4)
        bmask = 1 if button == "left" else 2
        await self.send("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button=button, buttons=bmask, clickCount=1)
        steps = int(duration * 60)
        for i in range(1, steps + 1):
            await self.send("Input.dispatchMouseEvent", type="mouseMoved", x=x + dx * i / steps, y=y + dy * i / steps,
                            button=button, buttons=bmask)
            await asyncio.sleep(duration / steps)
        await self.send("Input.dispatchMouseEvent", type="mouseReleased", x=x + dx, y=y + dy, button=button, buttons=0, clickCount=1)
        self.mouse = (x + dx, y + dy)

    async def wheel(self, delta, times=6):
        x, y = self.mouse
        for _ in range(times):
            await self.send("Input.dispatchMouseEvent", type="mouseWheel", x=x, y=y, deltaX=0, deltaY=delta)
            await asyncio.sleep(0.07)

    async def type(self, text, delay=0.09):
        for ch in text:
            await self.send("Input.insertText", text=ch)
            await asyncio.sleep(delay)

    async def clear_field(self, selector):
        await self.js(f"(() => {{ const e = document.querySelector({json.dumps(selector)}); e.value=''; e.dispatchEvent(new Event('input')); }})()")

    async def close_dialog(self):
        """Close the open settings dialog (like pressing Esc)."""
        await self.js("(() => { const d = document.querySelector('dialog[open]'); if (d) d.close(); })()")

    async def until(self, expr, timeout=120):
        t = time.time()
        while time.time() - t < timeout:
            if await self.js(expr):
                return
            await asyncio.sleep(0.25)
        raise TimeoutError(expr)

    async def model_loaded(self, timeout=60):
        await asyncio.sleep(0.3)
        await self.until("document.getElementById('loading').classList.contains('hidden')", timeout)
        await asyncio.sleep(0.6)

    # ------------------------------------------------------------ encoding
    def encode(self, path, t_start, t_end):
        frames = [(t, f) for t, f in self.frames if t <= t_end]
        if not frames:
            raise RuntimeError("no frames captured")
        warps = sorted(self.warps)

        def warp(t):  # wall time -> playback time
            out, prev_t, prev_f = 0.0, t_start, 1.0
            for wt, f in warps:
                if wt <= t_start:
                    prev_f = f
                    continue
                if wt >= t:
                    break
                out += (wt - prev_t) / prev_f
                prev_t, prev_f = wt, f
            return out + (t - prev_t) / prev_f

        times = np.array([warp(max(t, t_start)) for t, _ in frames])
        total = warp(t_end)
        writer = cv2.VideoWriter(path, cv2.CAP_MSMF, cv2.VideoWriter_fourcc(*"H264"), FPS, (W, H))
        if not writer.isOpened():
            writer = cv2.VideoWriter(path, cv2.CAP_ANY, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
        last_i, img = -1, None
        for k in range(int(total * FPS)):
            i = int(np.searchsorted(times, k / FPS, "right")) - 1
            i = max(i, 0)
            if i != last_i:
                img = cv2.imdecode(np.frombuffer(frames[i][1], np.uint8), cv2.IMREAD_COLOR)
                if img.shape[1] != W or img.shape[0] != H:
                    img = cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA)
                last_i = i
            writer.write(img)
        writer.release()
        return total


# ---------------------------------------------------------------------- scenes
async def scene_search(p):
    await p.title("VerseForge", "Search, view in 3D and export Star Citizen models")
    await p.wait(2.8)
    await p.title(None)
    await p.wait(0.8)

    await p.caption("1 · Search for an item", "in-game names, ship names and file names all work")
    await p.click("#q")
    await p.type("P4-AR")
    await p.wait(1.4)
    await p.caption("2 · Click a result to open it in 3D")
    await p.click("#results li", 0)
    await p.model_loaded()
    await p.wait(1.2)

    await p.caption("3 · Drag to rotate, wheel to zoom", "right button to pan the view")
    await p.drag(260, 40, 1.6, start=(800, 420))
    await p.drag(-120, -70, 1.2)
    await p.wheel(-120, 7)
    await p.wait(0.6)
    await p.wheel(120, 5)
    await p.wait(0.6)
    await p.drag(90, 0, 0.9, button="right")
    await p.wait(0.4)

    await p.caption("Frame, wireframe, auto-rotate, grid…", "on the right: real dimensions, triangles and materials")
    await p.click('[data-act="reset"]')
    await p.wait(0.8)
    await p.click('[data-act="wire"]')
    await p.wait(1.8)
    await p.click('[data-act="wire"]')
    await p.wait(0.5)
    await p.click('[data-act="rotate"]')
    await p.wait(3.5)
    await p.click('[data-act="rotate"]')
    await p.wait(0.6)

    await p.caption("4 · Filter by category", "e.g. Ships: the hull is assembled with all its parts")
    await p.clear_field("#q")
    await p.click('#cats [data-id="ships"]')
    await p.wait(1.2)
    await p.click("#q")
    await p.type("gladius")
    await p.wait(1.2)
    await p.click("#results li", 0)
    await p.model_loaded()
    await p.wait(0.8)
    await p.drag(-300, 30, 2.0, start=(820, 400))
    await p.wheel(-120, 5)
    await p.wait(0.8)

    await p.caption("5 · Show or hide decals, glass and single materials")
    await p.click('[data-kind="decal"]')
    await p.wait(1.0)
    await p.click('[data-kind="decal"]')
    await p.click('[data-kind="glass"]')
    await p.wait(1.2)
    await p.click("#mats li", 0)
    await p.wait(0.5)
    await p.click("#mats li", 2)
    await p.wait(1.5)
    await p.click("#mats li", 0)
    await p.click("#mats li", 2)
    await p.click('[data-kind="glass"]')
    await p.wait(0.8)

    await p.caption("On the right: the other files in the same folder", "parts, variants, interiors")
    await p.click_text("#related li", "_Int.cga")
    await p.model_loaded()
    await p.drag(-200, 40, 1.4, start=(820, 400))
    await p.wheel(-120, 4)
    await p.wait(1.5)
    await p.caption(None)
    await p.title("Happy exploring!", "VerseForge.exe")
    await p.wait(2.5)


async def scene_export(p):
    await p.title("Export and 3D print", "GLB · OBJ · STL · solid STL for printing")
    await p.wait(2.6)
    await p.title(None)
    await p.wait(0.8)

    await p.caption("Open a model", "here the P4-AR magazine")
    await p.click("#q")
    await p.type("p4-ar magazine")
    await p.wait(1.2)
    await p.click("#results li", 0)
    await p.model_loaded()
    await p.drag(200, 20, 1.2, start=(800, 420))
    await p.wait(0.6)

    await p.caption("Export with one click: GLB, OBJ or STL", "the file is downloaded and a copy goes to the exports folder")
    await p.click('[data-exp="glb"]')
    await p.wait(2.2)
    await p.click('[data-exp="obj"]')
    await p.wait(2.2)
    await p.click('[data-exp="stl"]')
    await p.wait(2.4)

    await p.caption("3D printing: make a printable STL", "Blender turns the model into a closed, filled solid, in millimetres")
    await p.click("#btnPrint")
    await p.wait(2.5)
    await p.caption("Processing…", "video sped up ×8")
    p.speed(8.0)
    await p.until(PRINT_DONE, 600)
    p.speed(1.0)
    await p.caption("Ready: closed STL, with dimensions and volume", "download it from the link or from the exports folder")
    await p.move(*await p.center("#printStatus"), 0.8)
    await p.wait(3.5)

    await p.caption("Settings: game path, exports folder, Blender")
    await p.click("#btnSettings")
    await p.wait(3.0)
    await p.close_dialog()
    await p.wait(0.8)
    await p.caption(None)
    await p.title("Ready for the slicer", "STL in millimetres, Z axis up")
    await p.wait(2.5)


async def pick_variant(p, label):
    """Choose a paint from the variant menu (a native <select> cannot be driven with mouse events in headless mode)."""
    await p.move(*await p.center("#variantSel"), 0.6)
    await p.wait(0.4)
    await p.js(f"""(() => {{ const s = document.getElementById('variantSel');
        s.value = [...s.options].find(o => o.text.includes({json.dumps(label)})).value;
        s.dispatchEvent(new Event('change')); }})()""")
    await p.model_loaded()


async def scene_demo_en(p, captions=True):
    """Short English presentation of the program (about a minute), e.g. to show it to CIG.

    captions=False keeps only the opening and closing titles."""
    if not captions:
        async def no_caption(text=None, sub=None):
            pass
        p.caption = no_caption
    await p.title("VerseForge", "A free fan tool to view Star Citizen 3D models from your own game installation")
    await p.wait(3.2)
    await p.title(None)
    await p.wait(0.8)

    await p.caption("1 · Search by in-game name", "weapons, armor, clothing, ships, vehicles, items…")
    await p.click("#q")
    await p.type("quartz")
    await p.wait(1.2)
    await p.click_text("#results li", "Quartz Energy SMG")
    await p.model_loaded()
    await p.wait(0.8)

    await p.caption("2 · Inspect the model in 3D", "drag to rotate · wheel to zoom")
    await p.drag(240, 30, 1.6, start=(800, 430))
    await p.wheel(-120, 5)
    await p.wait(0.5)
    await p.wheel(120, 4)
    await p.wait(0.6)

    await p.caption("Real dimensions, materials and in-game paints", "read from the game's own database")
    await pick_variant(p, "Jungle Camo")
    await p.wait(1.6)
    await pick_variant(p, "microTech")
    await p.wait(1.6)

    await p.caption("Wireframe, auto-rotate, grid…")
    await p.click('[data-act="wire"]')
    await p.wait(1.6)
    await p.click('[data-act="wire"]')
    await p.click('[data-act="rotate"]')
    await p.wait(3.0)
    await p.click('[data-act="rotate"]')
    await p.wait(0.4)

    await p.caption("3 · Ships too", "the hull is assembled with all its parts")
    await p.clear_field("#q")
    await p.click("#q")
    await p.type("gladius")
    await p.wait(1.2)
    await p.click_text("#results li", "Gladius")
    await p.model_loaded()
    await p.drag(-300, 30, 2.0, start=(820, 420))
    await p.wheel(-120, 4)
    await p.wait(1.0)

    await p.caption("4 · Export a single model for renders or personal cosplay", "GLB · OBJ · STL, plus a solid STL for 3D printing")
    await p.move(*await p.center('[data-exp="glb"]'), 0.8)
    await p.wait(0.6)
    await p.move(*await p.center('[data-exp="stl"]'), 0.6)
    await p.wait(0.6)
    await p.move(*await p.center("#btnPrint"), 0.6)
    await p.wait(2.0)

    await p.caption("Read-only · works offline · never modifies or redistributes game files")
    await p.move(800, 430, 0.8)
    await p.wait(3.0)
    await p.move(W - 20, H - 20, 0.6)   # keep the cursor off the closing title
    await p.caption(None)
    await p.title("VerseForge", "Free and non-commercial · not affiliated with or endorsed by Cloud Imperium Games / RSI")
    await p.wait(3.5)


# name -> (output file, scene, bitrate in kbit/s)
SCENES = {"search": ("01_search_and_view.mp4", scene_search, 3000),
          "export": ("02_export_and_print.mp4", scene_export, 3000),
          "demo_en": ("verseforge_demo_en.mp4", scene_demo_en, 2000),   # small enough to attach to a support ticket
          "demo_en_notext": ("verseforge_demo_en_notext.mp4", lambda p: scene_demo_en(p, captions=False), 2000)}
TUTORIALS = ("search", "export")


# ---------------------------------------------------------------------- runner
async def record(name, browser):
    filename, scene, kbps = SCENES[name]
    profile = tempfile.mkdtemp(prefix="scme_rec_")
    downloads = tempfile.mkdtemp(prefix="scme_dl_")
    port = 9333
    proc = subprocess.Popen([browser, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
                             f"--window-size={W},{H}", "--hide-scrollbars", "--mute-audio", "--no-first-run",
                             "--disable-extensions", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1))
                page_t = next(t for t in targets if t["type"] == "page")
                break
            except Exception:
                await asyncio.sleep(0.2)
        async with websockets.connect(page_t["webSocketDebuggerUrl"], max_size=None) as ws:
            p = Page(ws)
            await p.send("Page.enable")
            await p.send("Runtime.enable")
            await p.send("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=1, mobile=False)
            await p.send("Browser.setDownloadBehavior", behavior="allow", downloadPath=downloads)
            await p.send("Page.addScriptToEvaluateOnNewDocument", source=f"window.addEventListener('DOMContentLoaded', () => {{ {OVERLAY_JS} }});")
            await p.send("Page.navigate", url=APP)
            await p.until("document.readyState === 'complete' && !!window.__demo", 30)
            await p.until("document.querySelectorAll('#cats [data-id]').length > 3", 120)   # catalogue ready
            await p.title("VerseForge", "")
            await p.wait(0.5)
            await p.send("Page.startScreencast", format="jpeg", quality=88, maxWidth=W, maxHeight=H, everyNthFrame=1)
            await p.wait(0.5)
            t0 = time.time()
            await scene(p)
            t1 = time.time()
            await p.send("Page.stopScreencast")
            out = os.path.join(OUT_DIR, filename)
            raw = os.path.join(OUT_DIR, "_raw_" + filename)
            os.makedirs(OUT_DIR, exist_ok=True)
            dur = p.encode(raw, t0, t1)
            compress(raw, out, kbps)
            print(f"{filename}: {dur:.1f} s, {len(p.frames)} frames captured, {os.path.getsize(out) / 1e6:.1f} MB")
            p.reader.cancel()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
        shutil.rmtree(downloads, ignore_errors=True)


def compress(raw, out, kbps=3000):
    """OpenCV's Media Foundation writer ignores quality settings (~40 Mbit/s): re-encode with Windows' transcoder."""
    script = os.path.join(HERE, "tools", "compress_video.ps1")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, "-In", raw, "-Out", out,
                        "-Kbps", str(kbps)], capture_output=True, text=True)
    if r.returncode == 0 and os.path.exists(out):
        os.remove(raw)
    else:
        print("Compression failed, keeping the raw file:", r.stdout[-300:], r.stderr[-300:])
        os.replace(raw, out)


def main():
    browser = next((b for b in BROWSERS if os.path.isfile(b)), None)
    if not browser:
        sys.exit("Edge or Chrome not found")
    try:
        urllib.request.urlopen(APP + "api/status", timeout=2)
    except OSError:
        sys.exit("Start the app first (start.py)")
    for name in (sys.argv[1:] or TUTORIALS):
        asyncio.run(record(name, browser))


if __name__ == "__main__":
    main()
