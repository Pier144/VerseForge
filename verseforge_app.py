"""VerseForge desktop app: the same interface in its own window, no browser, no console.

Windows: a WebView2 window (the Edge engine that ships with Windows), Qt WebEngine as the fallback.
Linux: Qt WebEngine.

This is the entry point of VerseForge.exe (Windows) and of the Linux AppImage; `python verseforge_app.py` runs it
from source.
"""
import os
import socket
import sys
import threading
import time
import traceback
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from sc_explorer import APP_NAME, __version__, paths  # noqa: E402

LOG_DIR = paths.cache_dir()             # Windows %LOCALAPPDATA%\VerseForge, Linux ~/.cache/VerseForge
RES_DIR = getattr(sys, "_MEIPASS", HERE)


def _linux_gpu_setup():
    """Qt WebEngine on Linux: WebGL needs the GPU process, which Chromium turns off on drivers it does not trust.

    VERSEFORGE_GPU=off forces software drawing (slow, but works on any machine: last resort for broken drivers)."""
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").split()
    if os.environ.get("VERSEFORGE_GPU", "").lower() in ("off", "0", "software"):
        flags += ["--disable-gpu", "--enable-unsafe-swiftshader"]
        os.environ["LIBGL_ALWAYS_SOFTWARE"] = "1"
    else:
        flags += ["--ignore-gpu-blocklist", "--enable-unsafe-swiftshader"]
        if os.path.exists("/dev/dxg") and "GALLIUM_DRIVER" not in os.environ:
            os.environ["GALLIUM_DRIVER"] = "d3d12"    # WSL: Mesa picks the CPU renderer unless told to use the GPU
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(dict.fromkeys(flags))


def _redirect_output():
    """A windowed .exe has no console: sys.stdout/stderr are None and logging would crash."""
    if sys.stdout is None or sys.stderr is None or getattr(sys, "frozen", False):
        os.makedirs(LOG_DIR, exist_ok=True)
        log = open(os.path.join(LOG_DIR, "verseforge.log"), "w", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(port):
    import uvicorn
    from sc_explorer.server import app
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", log_config=None))
    threading.Thread(target=server.run, daemon=True, name="server").start()
    for _ in range(200):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=0.5)
            return server
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("the internal server did not start")


def _cloak_first_frames(win, ms=300):
    """Windows: a new window shows one white frame before Qt paints it. Keep it cloaked (DWM hides it without making
    it a layered window, so the 3D drawing is not slowed down) until the background colour is on screen."""
    import ctypes
    from PySide6.QtCore import QTimer
    DWMWA_CLOAK = 13
    hwnd = int(win.winId())

    def cloak(on):
        try:
            val = ctypes.c_int(1 if on else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_CLOAK, ctypes.byref(val), ctypes.sizeof(val))
        except OSError:
            pass

    cloak(True)
    QTimer.singleShot(ms, lambda: cloak(False))


def _self_test():
    """`VerseForge --self-test`: start the internal server and load Qt WebEngine without opening a window, then quit.
    Used by the Linux build (CI) to check that the packaged app has everything it needs. Exit code 0 = fine."""
    os.environ.setdefault("VERSEFORGE_DISK_CACHE", "0")
    port = _free_port()
    _start_server(port)
    status = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=5).read()
    page = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read()
    from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401  (loads the Chromium libraries)
    from PySide6.QtWidgets import QApplication
    QApplication(sys.argv[:1])
    print(f"self-test ok: {APP_NAME} {__version__}, status {len(status)} bytes, page {len(page)} bytes")
    return 0


def _fail(text):
    """Start-up error shown in a box (the windowed .exe has no console)."""
    traceback.print_exc()
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, 0x10)
    else:
        from PySide6.QtWidgets import QApplication, QMessageBox
        _ = QApplication.instance() or QApplication(sys.argv[:1])
        QMessageBox.critical(None, APP_NAME, text)


def _webview2_version():
    """Version of the installed WebView2 runtime (part of Windows 11, on nearly every Windows 10), or None."""
    import winreg
    key = r"Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    for root, path in ((winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\{key}"),
                       (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\{key}"), (winreg.HKEY_CURRENT_USER, rf"SOFTWARE\{key}")):
        try:
            with winreg.OpenKey(root, path) as k:
                pv = winreg.QueryValueEx(k, "pv")[0]
            if pv and pv != "0.0.0.0":
                return pv
        except OSError:
            pass
    return None


def _pick_shell():
    """Which window hosts the page: "webview2" (Windows: the system's Edge engine) or "qt" (Qt WebEngine).

    Qt WebEngine on Windows hands frames to the window before Chromium has finished composing them (QTBUG-123181,
    QTBUG-129721): with heavy 3D scenes the panels vanished for a frame or more ("flashing"). The same page in a real
    Chromium window never does (tools/flash_check.py: 134 flashes against 0), so Windows uses WebView2 when it is
    there. VERSEFORGE_SHELL=qt forces the Qt window; Linux always uses it."""
    if sys.platform != "win32" or os.environ.get("VERSEFORGE_SHELL", "").lower() == "qt":
        return "qt"
    if not _webview2_version():
        print("WebView2 runtime not found: using the Qt window")
        return "qt"
    try:
        import webview  # noqa: F401
    except Exception:  # not installed (running from source without it) or .NET missing
        traceback.print_exc()
        return "qt"
    return "webview2"


def _dark(pref, system_dark):
    return pref == "dark" or (pref != "light" and system_dark)


def _windows_dark():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return True


def _debug_port():
    """DevTools port for the automated checks (tools/flash_check.py); the Qt name is accepted by both windows."""
    port = os.environ.get("VERSEFORGE_REMOTE_DEBUGGING") or os.environ.get("QTWEBENGINE_REMOTE_DEBUGGING")
    return int(port) if port and port.isdigit() else None


def _run_webview2(url, state):
    """The page in a WebView2 window (pywebview). Downloads ask where to save, like the Qt window does."""
    import webview
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = False
    if _debug_port():
        webview.settings["REMOTE_DEBUGGING_PORT"] = _debug_port()
    bg = "#06070b" if _dark(state.cfg.get("appearance", "system"), _windows_dark()) else "#eef1f6"
    webview.create_window(f"{APP_NAME} {__version__}", url, width=1500, height=920, maximized=True,
                          background_color=bg, text_select=True)
    # a profile of its own, kept between runs (Chromium's shader cache makes later starts faster); the page itself is
    # always revalidated (server: Cache-Control no-cache)
    webview.start(private_mode=False, storage_path=os.path.join(LOG_DIR, "webview2"),
                  icon=os.path.join(RES_DIR, "assets", "verseforge.ico"))
    return 0


def main():
    if "--self-test" in sys.argv:
        return _self_test()
    _redirect_output()
    # Windows: own taskbar icon instead of python's
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"VerseForge.App.{__version__}")
    else:
        _linux_gpu_setup()

    try:
        port = _free_port()
        server = _start_server(port)
    except Exception as e:
        _fail(f"Could not start {APP_NAME}:\n{e}")
        return 1

    from sc_explorer.server import state
    url = f"http://127.0.0.1:{port}/"
    shell = _pick_shell()
    print(f"window: {shell}")
    try:
        return _run_webview2(url, state) if shell == "webview2" else _run_qt(url, state)
    finally:
        server.should_exit = True


def _run_qt(url, state):
    from PySide6.QtCore import Qt, QUrl
    from PySide6.QtGui import QColor, QIcon
    from PySide6.QtWebEngineCore import QWebEngineDownloadRequest, QWebEngineProfile, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow

    qt = QApplication(sys.argv)
    qt.setApplicationName(APP_NAME)
    qt.setApplicationVersion(__version__)
    if sys.platform != "win32":
        qt.setDesktopFileName("verseforge")      # Wayland/GNOME/KDE: window icon and name from verseforge.desktop
    icon = QIcon(os.path.join(RES_DIR, "assets", "verseforge.ico" if sys.platform == "win32" else "verseforge.png"))
    qt.setWindowIcon(icon)

    # until the page paints, Qt WebEngine shows white: use the app's own background (--app-bg in web/style.css),
    # dark or light as saved in the settings ("system" follows Windows / the desktop)
    dark = _dark(state.cfg.get("appearance", "system"), qt.styleHints().colorScheme() != Qt.ColorScheme.Light)
    bg = QColor("#06070b" if dark else "#eef1f6")

    win = QMainWindow()
    win.setWindowTitle(f"{APP_NAME} {__version__}")
    win.setStyleSheet(f"QMainWindow {{ background: {bg.name()}; }}")
    win.resize(1500, 920)
    view = QWebEngineView(win)
    view.page().setBackgroundColor(bg)
    win.setCentralWidget(view)

    profile = QWebEngineProfile.defaultProfile()
    profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.NoCache)
    view.settings().setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)

    def on_download(req: QWebEngineDownloadRequest):
        # exports are already saved in the export folder; this dialog lets the user keep an extra copy elsewhere
        folder = state.cfg.get("export_dir") or os.path.expanduser("~")
        os.makedirs(folder, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(win, "Save file",os.path.join(folder, req.downloadFileName()))
        if not path:
            req.cancel()
            return
        req.setDownloadDirectory(os.path.dirname(path))
        req.setDownloadFileName(os.path.basename(path))
        req.accept()

    profile.downloadRequested.connect(on_download)
    view.setUrl(QUrl(url))
    if sys.platform == "win32":
        _cloak_first_frames(win)
    win.showMaximized()
    code = qt.exec()
    return code


if __name__ == "__main__":
    sys.exit(main())
