"""VerseForge desktop app: the same interface in its own window (Qt WebEngine), no browser, no console.

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

    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QIcon
    from PySide6.QtWebEngineCore import QWebEngineDownloadRequest, QWebEngineProfile, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox

    qt = QApplication(sys.argv)
    qt.setApplicationName(APP_NAME)
    qt.setApplicationVersion(__version__)
    if sys.platform != "win32":
        qt.setDesktopFileName("verseforge")      # Wayland/GNOME/KDE: window icon and name from verseforge.desktop
    icon = QIcon(os.path.join(RES_DIR, "assets", "verseforge.ico" if sys.platform == "win32" else "verseforge.png"))
    qt.setWindowIcon(icon)

    try:
        port = _free_port()
        server = _start_server(port)
    except Exception as e:
        traceback.print_exc()
        QMessageBox.critical(None, APP_NAME, f"Could not start {APP_NAME}:\n{e}")
        return 1

    from sc_explorer.server import state

    win = QMainWindow()
    win.setWindowTitle(f"{APP_NAME} {__version__}")
    win.resize(1500, 920)
    view = QWebEngineView(win)
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
    view.setUrl(QUrl(f"http://127.0.0.1:{port}/"))
    win.showMaximized()
    code = qt.exec()
    server.should_exit = True
    return code


if __name__ == "__main__":
    sys.exit(main())
