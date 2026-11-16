"""Automated spot check for the "flashing panels" of the desktop app.

Symptom (15/11/2026): in the Qt window, for 1-55 frames, only the 3D canvas is on screen and the HTML panels (top bar,
side panels, toolbar) are gone. It cannot be seen from inside the page (the DOM is fine), only on screen, so this check:

1. starts the desktop app (Qt WebEngine) with remote debugging, or attaches to one already running (--attach);
2. puts a small magenta square inside every floating panel (same compositing layer as the panel);
3. films the screen at 60 fps (ffmpeg ddagrab, Desktop Duplication) and checks each frame for every square:
   a square that is missing means its panel was not drawn in that frame = one flash;
4. drives a random but repeatable sample of user actions through the DevTools protocol (load ships, full ship,
   interiors, decks, section slider, backdrops, lighting, wireframe, textures, light/dark mode, settings, orbit);
5. writes a report (which step, how many frames, which panels) plus the frames around each flash as PNG.

    python tools/flash_check.py                       # 3 random ships + Perseus, seed 1
    python tools/flash_check.py --ships 6 --seed 7    # bigger sample
    python tools/flash_check.py --only perseus        # just one ship (name search)
    python tools/flash_check.py --attach 9333         # app already running with QTWEBENGINE_REMOTE_DEBUGGING=9333
Exit code 0 = no flash, 1 = flashes found, 2 = the check itself failed, 3 = no flash but interrupted (screen lost).
The window must stay visible on the main screen while it runs (it is filmed): do not cover it.
"""
import argparse
import asyncio
import json
import os
import random
import subprocess
import sys
import threading
import time
import urllib.request
from collections import deque

import cv2
import numpy as np
import websockets

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_ROOT = os.path.join(HERE, "docs", "flash-check")
CAP_W, CAP_H, FPS = 960, 540, 60          # the screen is filmed at this size: enough for 12 px squares


def _screen_width():
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
        return ctypes.windll.user32.GetSystemMetrics(0)
    except Exception:
        return 1920


SCREEN_W = _screen_width()                # physical pixels of the main screen


def _app_in_front():
    """True when the foreground window is VerseForge's (another window in front is not a flash)."""
    try:
        import ctypes
        u = ctypes.windll.user32
        buf = ctypes.create_unicode_buffer(200)
        u.GetWindowTextW(u.GetForegroundWindow(), buf, 200)
        return buf.value.startswith("VerseForge")
    except Exception:
        return True
MARK = 16                                 # CSS px
PANES = [(".topbar", "top bar"), (".sidebar", "left panel"), (".panel", "right panel"),
         (".toolbar", "toolbar"), (".layers", "layers bar")]

# Injected once: markers, a frame-gap recorder and the helpers the steps use.
PAGE_JS = r"""
(() => {
  if (window.__fc) return true;
  const $ = (s) => document.querySelector(s);
  const panes = %PANES%;
  const fc = window.__fc = { gaps: [], laf: [], marks: [] };
  // a marker inside each panel: the panel draws it, so it disappears together with the panel
  fc.placeMarks = () => {
    fc.marks = [];
    for (const [sel, name] of panes) {
      const el = $(sel);
      if (!el || el.offsetParent === null) continue;
      let m = el.querySelector(":scope > .fc-mark");
      if (!m) {
        m = document.createElement("div");
        m.className = "fc-mark";
        m.style.cssText = "position:absolute;width:%MARK%px;height:%MARK%px;background:#ff00ff;pointer-events:none;" +
          "z-index:99;border-radius:0;left:26px;top:" + (el.clientHeight > 80 ? "12px" : "calc(50% - %HALF%px)");
        if (sel === ".toolbar") m.style.left = "6px";
        if (sel === ".layers") { m.style.left = "auto"; m.style.right = "6px"; }   // the bar grows to the left
        el.appendChild(m);
      }
      const r = m.getBoundingClientRect();
      fc.marks.push({ name, x: r.left + r.width / 2, y: r.top + r.height / 2 });
    }
    return { marks: fc.marks, dpr: devicePixelRatio, w: innerWidth, h: innerHeight };
  };
  // gaps between animation frames (wall clock, same clock as the recorder) and long animation frames
  let last = Date.now();
  const loop = () => { const now = Date.now(); if (now - last > 40) fc.gaps.push([last, now - last]); last = now; requestAnimationFrame(loop); };
  requestAnimationFrame(loop);
  try {
    new PerformanceObserver((l) => { for (const e of l.getEntries())
      fc.laf.push([performance.timeOrigin + e.startTime, e.duration, e.blockingDuration]); })
      .observe({ type: "long-animation-frame", buffered: false });
  } catch { /* not supported */ }
  fc.busy = () => !$("#loading").classList.contains("hidden");
  fc.idle = async (extra = 800, max = 120000) => {
    const t0 = Date.now();
    await new Promise((r) => setTimeout(r, 250));
    while (fc.busy() && Date.now() - t0 < max) await new Promise((r) => setTimeout(r, 100));
    await new Promise((r) => setTimeout(r, extra));
    return !fc.busy();
  };
  fc.setBox = (id, on) => { const c = $(id); if (!c || c.closest(".hidden") || c.checked === on) return false; c.click(); return true; };
  fc.visible = (sel) => { const e = $(sel); return !!e && e.offsetParent !== null && !e.closest(".hidden"); };
  return true;
})()
"""


# ------------------------------------------------------------------ DevTools protocol
class CDP:
    def __init__(self, ws):
        self.ws, self.n, self.wait = ws, 0, {}
        self.handlers = {}         # event name -> function(params)
        self.task = asyncio.create_task(self._reader())

    @classmethod
    async def connect(cls, port):
        pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2))
        page = next(p for p in pages if p.get("type") == "page" and "127.0.0.1" in p.get("url", ""))
        return cls(await websockets.connect(page["webSocketDebuggerUrl"], max_size=None))

    async def _reader(self):
        async for msg in self.ws:
            m = json.loads(msg)
            if "method" in m:
                h = self.handlers.get(m["method"])
                if h:
                    h(m.get("params", {}))
                continue
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

    async def js(self, expr, timeout=300):
        r = await asyncio.wait_for(self.send("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True), timeout)
        if r.get("exceptionDetails"):
            raise RuntimeError(f"page error: {r['exceptionDetails'].get('exception', {}).get('description') or r['exceptionDetails']}")
        return r.get("result", {}).get("value")

    async def drag(self, x0, y0, dx, dy, steps=30, button="left"):
        await self.send("Input.dispatchMouseEvent", type="mouseMoved", x=x0, y=y0)
        await self.send("Input.dispatchMouseEvent", type="mousePressed", x=x0, y=y0, button=button, clickCount=1)
        for i in range(1, steps + 1):
            await self.send("Input.dispatchMouseEvent", type="mouseMoved", x=x0 + dx * i / steps, y=y0 + dy * i / steps,
                            button=button, buttons=1 if button == "left" else 2)
            await asyncio.sleep(1 / 60)
        await self.send("Input.dispatchMouseEvent", type="mouseReleased", x=x0 + dx, y=y0 + dy, button=button, clickCount=1)

    async def close(self):
        self.task.cancel()
        await self.ws.close()


# ------------------------------------------------------------------ screen recorder
class Recorder:
    """Checks the panel markers in every frame. Two sources:
    screen      ffmpeg ddagrab -> BGRA frames on a pipe (what is really on the monitor; needs an unlocked, visible desktop)
    screencast  the frames Chromium itself composes (DevTools Page.startScreencast, JPEG): works with the PC locked or
                remote desktop minimised, but misses anything that goes wrong after Chromium (Qt drawing the window)."""

    def __init__(self, out_dir, source="screen", cdp=None):
        self.out_dir = out_dir
        self.source = source
        self.scale = None          # capture pixels per CSS pixel
        self.cdp = cdp
        self.frames = 0
        self.t0 = None
        self.boxes = []            # (name, x0, y0, x1, y1) in capture pixels
        self.missing = []          # (frame, wall time, [names])
        self.ring = deque(maxlen=6)
        self.after = 0
        self.saved = 0
        self.ref = None
        self.paused = False
        self.covered = 0           # frames with another window in front of the app
        self.moves = []            # (wall time, name): a panel's marker moved (frames near it are not judged for it)
        self.lock = threading.Lock()
        self.proc = self.thread = None
        if source == "screen":
            self.proc = subprocess.Popen(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"ddagrab=framerate={FPS}:output_idx=0",
                 "-vf", f"hwdownload,format=bgra,scale={CAP_W}:{CAP_H}:flags=neighbor", "-f", "rawvideo", "-"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=CAP_W * CAP_H * 4 * 2)
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    async def start_screencast(self):
        def on_frame(p):
            asyncio.ensure_future(self.cdp.send("Page.screencastFrameAck", sessionId=p["sessionId"]))
            img = cv2.imdecode(np.frombuffer(__import__("base64").b64decode(p["data"]), np.uint8), cv2.IMREAD_COLOR)
            if self.scale is None:
                self.scale = img.shape[1] / p["metadata"]["deviceWidth"]
            self.feed(img, time.time())
        self.cdp.handlers["Page.screencastFrame"] = on_frame
        await self.cdp.send("Page.startScreencast", format="jpeg", quality=90, maxWidth=CAP_W, maxHeight=CAP_H, everyNthFrame=1)

    def alive(self):
        return self.proc is None or self.proc.poll() is None

    def _run(self):
        size = CAP_W * CAP_H * 4
        while True:
            buf = self.proc.stdout.read(size)
            if len(buf) < size:
                return
            self.feed(np.frombuffer(buf, np.uint8).reshape(CAP_H, CAP_W, 4), time.time())

    def feed(self, img, now):
        if True:
            with self.lock:
                if self.t0 is None:
                    self.t0 = now
                self.frames += 1
                self.ref = img
                gone = [name for name, x0, y0, x1, y1 in self.boxes if not _is_mark(img[y0:y1, x0:x1])]
                if gone and self.source == "screen" and not _app_in_front():
                    self.covered += 1                 # another window is in front: not judged
                    gone = []
                if gone:
                    self.missing.append((self.frames, now, gone))
                    if self.saved < 300:
                        for i, (fn, frame) in enumerate(self.ring):
                            self._save(fn, frame, "before")
                        self.ring.clear()
                        self._save(self.frames, img, "FLASH")
                    self.after = 2
                elif self.after:
                    self.after -= 1
                    self._save(self.frames, img, "after")
                else:
                    self.ring.append((self.frames, img.copy()))
                    if len(self.ring) > 2:
                        self.ring.popleft()

    def _save(self, fn, img, tag):
        self.saved += 1
        cv2.imwrite(os.path.join(self.out_dir, f"f{fn:06d}_{tag}.png"), img[:, :, :3])

    def snapshot(self):
        with self.lock:
            return None if self.ref is None else self.ref.copy()

    def find_boxes(self, layout):
        """Match the page's markers to the magenta squares on screen (the window origin is not known in advance)."""
        img = self.snapshot()
        mask = ((img[:, :, 2] > 220) & (img[:, :, 1] < 40) & (img[:, :, 0] > 220)).astype(np.uint8)
        n, _, st, cen = cv2.connectedComponentsWithStats(mask)
        if self.source == "screen":
            self.scale = CAP_W / SCREEN_W * layout["dpr"]
        sx = self.scale
        side = MARK * sx * 0.4
        blobs = [(cen[i], st[i]) for i in range(1, n) if st[i][2] >= side and st[i][3] >= side]
        exp = [(m["name"], m["x"] * sx, m["y"] * sx) for m in layout["marks"]]
        best = None
        for c, _ in blobs:                       # try each blob as the first marker: the offset that matches most wins
            ox, oy = c[0] - exp[0][1], c[1] - exp[0][2]
            match = []
            for name, ex, ey in exp:
                d = [(abs(b[0][0] - ex - ox) + abs(b[0][1] - ey - oy), b) for b in blobs]
                dist, b = min(d, key=lambda t: t[0])
                if dist < 4:
                    match.append((name, b))
            if not best or len(match) > len(best):
                best = match
        if not best or len(best) < len(exp):
            cv2.imwrite(os.path.join(self.out_dir, "markers_not_found.png"), img[:, :, :3])
            print("expected", exp, "blobs", [(tuple(map(int, c)), tuple(map(int, st_[2:4]))) for c, st_ in blobs])
            raise RuntimeError(f"found {len(best or [])} of {len(exp)} panel markers on screen: is the window visible and in front?")
        # where the page's (0, 0) is on the captured frame: later moves of the panels are followed from the page alone
        name0, b0 = best[0]
        self.origin = (b0[0][0] - exp[0][1], b0[0][1] - exp[0][2])
        self.half = max(1, int(MARK * sx / 2) - 1)
        return self.update_boxes(layout)

    def update_boxes(self, layout):
        """Boxes of the markers from the page coordinates (panels that move or appear, e.g. the layers bar)."""
        sx = self.scale
        ox, oy = self.origin
        h = self.half
        boxes = [(m["name"], int(round(ox + m["x"] * sx)) - h, int(round(oy + m["y"] * sx)) - h,
                  int(round(ox + m["x"] * sx)) + h, int(round(oy + m["y"] * sx)) + h) for m in layout["marks"]]
        with self.lock:
            self.paused = False
            old = {b[0]: b[1:] for b in self.boxes}
            now = time.time()
            self.moves += [(now, b[0]) for b in boxes if b[0] in old and old[b[0]] != b[1:]]
            self.boxes = boxes
        return boxes

    def pause(self):
        """Stop judging frames (a modal dialog covers the panels on purpose) until the next update_boxes."""
        with self.lock:
            self.boxes = []
            self.paused = True

    def stop(self):
        if self.source == "screencast":
            self.cdp.handlers.pop("Page.screencastFrame", None)
            return
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.thread.join(5)


def _is_mark(px):
    if px.size == 0:
        return True
    ok = (px[:, :, 2] > 200) & (px[:, :, 1] < 70) & (px[:, :, 0] > 200)
    return ok.mean() > 0.5


# ------------------------------------------------------------------ app
def start_app(port, exe, extra=()):
    env = dict(os.environ, QTWEBENGINE_REMOTE_DEBUGGING=str(port))
    env.update(kv.split("=", 1) for kv in extra)
    cmd = [exe] if exe else [sys.executable, os.path.join(HERE, "verseforge_app.py")]
    proc = subprocess.Popen(cmd, cwd=HERE, env=env)
    for _ in range(600):
        try:
            pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1))
            if any(p.get("type") == "page" and "127.0.0.1" in p.get("url", "") for p in pages):
                return proc
        except OSError:
            pass
        if proc.poll() is not None:
            raise RuntimeError("the app exited while starting")
        time.sleep(0.2)
    raise RuntimeError("the app did not open its page")


async def wait_ready(cdp):
    for _ in range(600):
        ok = await cdp.js("fetch('/api/search?q=perseus&cat=ships&limit=1').then(r => r.ok && !!window.__verseforge).catch(() => false)")
        if ok:
            return
        await asyncio.sleep(0.5)
    raise RuntimeError("the catalogue did not load (is the Data.p4k path set?)")


# ------------------------------------------------------------------ the sample of actions
class ScreenLost(Exception):
    """The screen recorder stopped (PC locked, remote desktop minimised): the run ends with what it has."""


class Run:
    def __init__(self, cdp, rng, layout, rec):
        self.cdp, self.rng, self.layout, self.rec = cdp, rng, layout, rec
        self.steps = []           # (label, t0, t1)
        self.lost = None          # label of the step after which the screen was lost

    async def step(self, label, coro):
        t0 = time.time()
        print(f"  {label}", flush=True)
        try:
            await coro
        except Exception as e:  # a step that fails is reported, the run goes on
            label += f"  [step failed: {e}]"
            print(f"    failed: {e}")
        self.steps.append((label, t0, time.time()))
        if not self.rec.alive():
            raise ScreenLost(label)

    async def idle(self, extra=800):
        await self.cdp.js(f"__fc.idle({extra})")

    async def click(self, sel, extra=800):
        await self.cdp.js(f"document.querySelector({json.dumps(sel)}).click()")
        await self.idle(extra)

    async def box(self, sel, on, extra=1000):
        if await self.cdp.js(f"__fc.setBox({json.dumps(sel)}, {json.dumps(on)})"):
            await self.idle(extra)

    async def orbit(self):
        cx = (self.layout["w"]) / 2
        cy = self.layout["h"] / 2
        await self.cdp.drag(cx, cy, self.rng.choice([-1, 1]) * 260, self.rng.uniform(-60, 60))
        await self.idle(600)

    async def load(self, item, everything=False):
        """Load a ship plain, or with interiors + full ship + decals already on (the heavy case)."""
        on = json.dumps(everything)
        await self.cdp.js(f"(() => {{ const s = __verseforge.state(), on = {on}; s.full = on; s.interior = on; s.kinds.decal = on;"
                          " document.querySelector('#fullOn').checked = on; document.querySelector('#intOn').checked = on;"
                          " document.querySelector('[data-kind=decal]').checked = on;"
                          " try { sessionStorage.setItem('vf.full', on ? '1' : '0'); sessionStorage.setItem('vf.int', on ? '1' : '0'); } catch {} })()")
        await self.cdp.js(f"__verseforge.load({json.dumps(item)})")
        await self.idle(1500)

    async def all_on_quickly(self):
        """Interiors, full ship and decals switched on one after the other while the first reload is still running."""
        for sel in ("#intOn", "#fullOn", "[data-kind=decal]"):
            await self.cdp.js(f"__fc.setBox({json.dumps(sel)}, true)")
            await asyncio.sleep(self.rng.uniform(0.1, 0.6))
        await self.idle(2000)

    async def decks(self):
        n = await self.cdp.js("document.querySelectorAll('#decks button').length")
        if not n or await self.cdp.js("document.querySelector('#decks').hidden"):
            return
        order = list(range(n))
        self.rng.shuffle(order)
        for i in order[: min(n, 5)] + [n - 1]:      # a few decks in random order, then "All"
            await self.cdp.js(f"document.querySelectorAll('#decks button')[{i}].click()")
            await self.idle(500)

    async def slider(self):
        if not await self.cdp.js("__fc.visible('#cutBox')"):
            return
        for v in (700, 450, 820, 1000):
            await self.cdp.js(f"(() => {{ const c = document.querySelector('#cut'); c.value = {v}; c.dispatchEvent(new Event('input')); }})()")
            await asyncio.sleep(0.25)
        await self.idle(500)

    async def backdrop(self, kind):
        await self.cdp.js(f"document.querySelector('#bgMenu [data-bg=\"{kind}\"]').click()")
        await self.idle(1500)

    async def ship(self, item):
        r = self.rng
        name = item["name"]
        # A: everything on from the start
        await self.step(f"{name}: load with interiors + full ship + decals", self.load(item, True))
        await self.step(f"{name}: orbit", self.orbit())
        await self.step(f"{name}: decks", self.decks())
        await self.step(f"{name}: section slider", self.slider())
        for kind in r.sample(["workbench", "pyro", "stanton", "studio"], 2):
            await self.step(f"{name}: backdrop {kind} (everything on)", self.backdrop(kind))
            await self.step(f"{name}: orbit", self.orbit())
        await self.step(f"{name}: backdrop plain", self.backdrop("plain"))
        # B: plain, then the switches one by one or all together
        await self.step(f"{name}: load", self.load(item))
        await self.step(f"{name}: orbit", self.orbit())
        extras = [
            ("wireframe on/off", self._twice(lambda: self.click('[data-act="wire"]', 400))),
            ("hangar/studio light", self._twice(lambda: self.click('[data-act="light"]', 600))),
            ("light/dark mode", self._twice(lambda: self.click("#btnMode", 700))),
            ("settings open/close", self._settings()),
            ("textures off/on", self._seq(lambda: self.box("#texOn", False, 1000), lambda: self.box("#texOn", True, 1500))),
        ]
        for label, coro in r.sample(extras, 2):
            await self.step(f"{name}: {label}", coro)
        for label, coro in extras:
            coro.close()  # the ones not picked (closing a finished one does nothing)
        if r.random() < 0.5:
            await self.step(f"{name}: interiors + full ship + decals in quick succession", self.all_on_quickly())
        else:
            for sel, label in (("#fullOn", "full ship on"), ("#intOn", "interiors on"), ("[data-kind=decal]", "decals on")):
                await self.step(f"{name}: {label}", self.box(sel, True, 1500))
        await self.step(f"{name}: orbit", self.orbit())
        await self.step(f"{name}: decks", self.decks())
        kind = r.choice(["workbench", "pyro", "stanton", "studio", "inverted"])
        await self.step(f"{name}: backdrop {kind}", self.backdrop(kind))
        await self.step(f"{name}: backdrop plain", self.backdrop("plain"))

    async def _twice(self, f):
        await f()
        await f()

    async def _seq(self, *steps):
        for f in steps:
            await f()

    async def _settings(self):
        # the modal dialog blurs the whole window on purpose: frames are not judged while it is open
        self.rec.pause()
        try:
            await self.click("#btnSettings", 700)
            await self.cdp.js("document.querySelector('dialog[open]')?.close()")
            await self.idle(700)
        finally:
            self.rec.update_boxes(await self.cdp.js("__fc.placeMarks()"))


async def pick_ships(cdp, rng, n, only):
    if only:
        q = await cdp.js(f"fetch('/api/search?cat=ships&limit=20&q={only}').then(r => r.json())")
        return q["items"][:1]
    items = (await cdp.js("fetch('/api/search?cat=ships&limit=2000').then(r => r.json())"))["items"]
    perseus = [it for it in items if "perseus" in it["name"].lower()][:1]
    rest = [it for it in items if it not in perseus]
    return perseus + rng.sample(rest, min(n, len(rest)))


# ------------------------------------------------------------------ report
def report(out_dir, rec, run, page, args, ships):
    events = []                                   # consecutive missing frames grouped into one flash
    noise = 0
    for fn, t, gone in rec.missing:
        # a panel that had just moved (layers bar growing, ...): the box was still on its old place
        real = [g for g in gone if not any(n == g and abs(t - tm) < 0.4 for tm, n in rec.moves)]
        if len(real) < len(gone):
            noise += 1
        gone = real
        if not gone:
            continue
        if events and fn - events[-1]["last"] <= 2:
            e = events[-1]
            e["last"], e["frames"], e["t1"] = fn, e["frames"] + 1, t
            e["panels"] |= set(gone)
        else:
            events.append({"first": fn, "last": fn, "frames": 1, "t0": t, "t1": t, "panels": set(gone)})

    def step_at(t):
        for label, t0, t1 in run.steps:
            if t0 - 0.05 <= t <= t1 + 0.05:
                return label
        return "(between steps)"

    def near(series, t0, t1, pad=0.25):
        return [s for s in series if t0 - pad <= s[0] / 1000 <= t1 + pad]

    lines = [f"# Flash check {time.strftime('%Y-%m-%d %H:%M')}", "",
             f"Seed {args.seed}, source {args.source}, ships: {', '.join(s['name'] for s in ships)}.",
             f"Frames filmed: {rec.frames} ({rec.frames / FPS:.0f} s at {FPS} fps), panels watched: "
             f"{', '.join(b[0] for b in rec.boxes)}.", "",
             f"**Flashes: {len(events)}** (frames without panels: {sum(e['frames'] for e in events)}; "
             f"with every panel gone: {sum(len(e['panels']) == len(rec.boxes) for e in events)})",
             f"Frames ignored because a panel was moving: {noise}, because another window was in front: {rec.covered}.",
             *([f"**INTERRUPTED**: the screen could not be filmed any more after \"{run.lost}\"; "
                "the results cover only the steps before it.", ""] if run.lost else []),
             f"Environment: {' '.join(args.env) or '(default)'}{', continuous drawing' if args.continuous else ''}"
             f"{f', {args.rounds} rounds' if args.rounds > 1 else ''}.", ""]
    if events:
        lines += ["| # | step | frames | panels gone | rAF gap near | long frame near |", "|---|---|---|---|---|---|"]
    for i, e in enumerate(events, 1):
        gaps = near(page["gaps"], e["t0"], e["t1"])
        laf = near(page["laf"], e["t0"], e["t1"])
        g = f"{max(x[1] for x in gaps):.0f} ms" if gaps else "-"
        lf = f"{max(x[1] for x in laf):.0f} ms" if laf else "-"
        lines.append(f"| {i} | {step_at(e['t0'])} | {e['frames']} (f{e['first']}) | {', '.join(sorted(e['panels']))} | {g} | {lf} |")
        e["panels"] = sorted(e["panels"])
        e["step"] = step_at(e["t0"])
    by_step = {}
    for e in events:
        k = e["step"].split(": ", 1)[-1]
        by_step[k] = by_step.get(k, 0) + 1
    if by_step:
        lines += ["", "By action: " + ", ".join(f"{k} {v}" for k, v in sorted(by_step.items(), key=lambda kv: -kv[1]))]
    lines += ["", "## Steps", ""] + [f"- {time.strftime('%H:%M:%S', time.localtime(t0))} {label} ({t1 - t0:.1f} s)"
                                     for label, t0, t1 in run.steps]
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump({"seed": args.seed, "ships": ships, "frames": rec.frames, "boxes": rec.boxes, "events": events,
                   "steps": run.steps, "gaps": page["gaps"], "laf": page["laf"]}, f, indent=1)
    return events


def screen_ok():
    """Desktop Duplication works only on an unlocked desktop that is being drawn (remote desktop not minimised)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "ddagrab=framerate=10",
                        "-frames:v", "1", "-f", "null", "-"], capture_output=True, text=True, timeout=20)
    return r.returncode == 0, r.stderr.strip().splitlines()[:1]


async def main_async(args):
    ok, err = screen_ok() if args.source == "screen" else (True, [])
    t_wait = time.time() + args.wait_screen * 60
    while not ok and time.time() < t_wait:        # wait for the user to come back / unlock
        await asyncio.sleep(15)
        ok, err = screen_ok()
    if not ok:
        raise RuntimeError(f"the screen cannot be filmed ({' '.join(err)}): unlock the PC and keep the window visible "
                           "(with remote desktop: the window open, not minimised)")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = os.path.join(OUT_ROOT, stamp + (f"-{args.label}" if args.label else ""))
    os.makedirs(out_dir, exist_ok=True)
    port = args.attach or args.port
    app = None if args.attach else start_app(port, args.exe, args.env)
    rec = None
    try:
        cdp = await CDP.connect(port)
        await wait_ready(cdp)
        js = (PAGE_JS.replace("%PANES%", json.dumps(PANES)).replace("%MARK%", str(MARK)).replace("%HALF%", str(MARK // 2)))
        await cdp.js(js)
        await cdp.js("document.querySelector('#bgMenu [data-bg=\"plain\"]').click()")
        await asyncio.sleep(2.5)                  # window fully drawn
        layout = await cdp.js("__fc.placeMarks()")
        rec = Recorder(out_dir, args.source, cdp)
        if args.source == "screencast":
            await rec.start_screencast()
            await cdp.js("__verseforge.invalidate(500)")
        for _ in range(100):                      # first frames (ddagrab sends one only when the screen changes)
            await asyncio.sleep(0.1)
            if rec.frames > 5:
                break
        else:
            raise RuntimeError("no frames from the recorder" + (
                f": {rec.proc.stderr.read1(2000).decode(errors='replace')}" if rec.proc else ""))
        rec.find_boxes(layout)
        print(f"watching {len(rec.boxes)} panels; frames go to {out_dir}")
        rng = random.Random(args.seed)
        ships = await pick_ships(cdp, rng, args.ships, args.only)
        run = Run(cdp, rng, layout, rec)

        async def follow():                       # panels that move or resize: keep the boxes on their markers
            last = layout["marks"]
            while True:
                await asyncio.sleep(0.12)
                lay = await cdp.js("__fc.placeMarks()")
                if lay["marks"] != last and not rec.paused:
                    rec.update_boxes(lay)
                    last = lay["marks"]
        follower = asyncio.create_task(follow())
        try:
            for item in ships * args.rounds:
                if args.continuous:               # draw every frame instead of on demand (comparison)
                    await cdp.js("__verseforge.invalidate(1e9)")
                await run.ship(item)
        except ScreenLost as e:
            run.lost = str(e)
            print(f"screen lost after: {e} (PC locked or remote desktop minimised?); partial report")
        finally:
            follower.cancel()
        await asyncio.sleep(0.5)
        page = await cdp.js("({ gaps: __fc.gaps, laf: __fc.laf })")
        rec.stop()
        events = report(out_dir, rec, run, page, args, ships)
        await cdp.close()
        print(open(os.path.join(out_dir, "report.md"), encoding="utf-8").read())
        return 1 if events else (3 if run.lost else 0)
    finally:
        if rec:
            rec.stop()
        if app:
            app.terminate()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ships", type=int, default=3, help="random ships besides the Perseus (default 3)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--only", help="test only the first ship matching this search")
    ap.add_argument("--attach", type=int, help="DevTools port of an app already running")
    ap.add_argument("--port", type=int, default=9333)
    ap.add_argument("--exe", help="run this VerseForge.exe instead of the sources")
    ap.add_argument("--label", default="", help="suffix of the report folder")
    ap.add_argument("--wait-screen", type=float, default=0, metavar="MIN",
                    help="wait up to MIN minutes for the screen to become filmable (PC unlocked)")
    ap.add_argument("--rounds", type=int, default=1, help="repeat the whole sample this many times")
    ap.add_argument("--continuous", action="store_true", help="draw every frame (turns off render on demand)")
    ap.add_argument("--env", action="append", default=[], metavar="KEY=VALUE",
                    help="environment variable for the app (repeatable), e.g. QSG_RHI_BACKEND=opengl")
    ap.add_argument("--source", choices=["screen", "screencast"], default="screen",
                    help="screen = film the monitor (default, what you really see); screencast = Chromium's own frames")
    args = ap.parse_args()
    try:
        sys.exit(asyncio.run(main_async(args)))
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"flash check failed: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
