"""Icon files from the vector logo assets/verseforge.svg:

    python tools/make_icons.py

  assets/verseforge.png   1024 px (README, Linux window and AppImage, installer images)
  assets/verseforge.ico   16-256 px (VerseForge.exe, the window, the installer)

The SVG is drawn by a headless Edge/Chrome (exact rendering, transparent corners); every icon size is rendered from
the vector, not shrunk from the big PNG, so the small ones stay sharp. Windows only (it looks for Edge or Chrome).
"""
import asyncio
import base64
import io
import json
import os
import subprocess
import tempfile
import time
import urllib.request

import websockets
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SVG = os.path.join(HERE, "assets", "verseforge.svg")
BROWSERS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe"]
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]
PORT = 9431


async def render(sizes):
    browser = next(b for b in BROWSERS if os.path.exists(b))
    profile = tempfile.mkdtemp(prefix="vf-icons-")
    proc = subprocess.Popen([browser, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}",
                             "--remote-allow-origins=*", "--hide-scrollbars", "about:blank"])
    try:
        for _ in range(60):
            try:
                page = next(p for p in json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=2))
                            if p["type"] == "page")
                break
            except Exception:
                time.sleep(0.5)
        ws = await websockets.connect(page["webSocketDebuggerUrl"], max_size=None)
        n = 0

        async def send(method, **params):
            nonlocal n
            n += 1
            await ws.send(json.dumps({"id": n, "method": method, "params": params}))
            while True:
                m = json.loads(await ws.recv())
                if m.get("id") == n:
                    return m.get("result", {})

        svg = open(SVG, encoding="utf-8").read()
        out = {}
        for size in sizes:
            await send("Emulation.setDeviceMetricsOverride", width=size, height=size, deviceScaleFactor=1, mobile=False)
            await send("Emulation.setDefaultBackgroundColorOverride", color={"r": 0, "g": 0, "b": 0, "a": 0})
            html = ("<html><body style='margin:0;background:transparent'>"
                    + svg.replace("<svg ", f"<svg width='{size}' height='{size}' ", 1) + "</body></html>")
            await send("Page.navigate", url="data:text/html;base64," + base64.b64encode(html.encode()).decode())
            await asyncio.sleep(0.4)
            shot = await send("Page.captureScreenshot", format="png",
                              clip={"x": 0, "y": 0, "width": size, "height": size, "scale": 1})
            out[size] = Image.open(io.BytesIO(base64.b64decode(shot["data"]))).convert("RGBA")
        await ws.close()
        return out
    finally:
        proc.terminate()


def main():
    images = asyncio.run(render(ICO_SIZES + [1024]))
    images[1024].save(os.path.join(HERE, "assets", "verseforge.png"))
    ico = [images[s] for s in ICO_SIZES]
    ico[-1].save(os.path.join(HERE, "assets", "verseforge.ico"), sizes=[(s, s) for s in ICO_SIZES],
                 append_images=ico[:-1])
    print("assets/verseforge.png and assets/verseforge.ico written")


if __name__ == "__main__":
    main()
