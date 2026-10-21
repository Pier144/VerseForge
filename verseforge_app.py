"""VerseForge desktop app: the same interface in its own window (Qt WebEngine), no browser, no console.

This is the entry point of VerseForge.exe; `python verseforge_app.py` runs it from source.
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

from sc_explorer import APP_NAME, __version__  # noqa: E402

LOG_DIR = os.path.join(os.environ.get("LOCALAPPDATA", HERE), APP_NAME)
RES_DIR = getattr(sys, "_MEIPASS", HERE)


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


def main():
    _redirect_output()
    # Windows: own taskbar icon instead of python's
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"VerseForge.App.{__version__}")

    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QIcon
    from PySide6.QtWebEngineCore import QWebEngineDownloadRequest, QWebEngineProfile, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox

    qt = QApplication(sys.argv)
    qt.setApplicationName(APP_NAME)
    qt.setApplicationVersion(__version__)
    icon = QIcon(os.path.join(RES_DIR, "assets", "verseforge.ico"))
    qt.setWindowIcon(icon)

    try:
        port = _free_port()
        server = _start_server(port)
    except Exception as e:
        traceback.print_exc()
        QMessageBox.critical(None, APP_NAME, f"Could not start {APP_NAME} / Impossibile avviare {APP_NAME}:\n{e}")
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
        title = "Salva file" if state.cfg.get("ui_lang") == "it" else "Save file"
        path, _ = QFileDialog.getSaveFileName(win, title, os.path.join(folder, req.downloadFileName()))
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
