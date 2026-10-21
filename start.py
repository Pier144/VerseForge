"""Start VerseForge in the browser: local server on http://127.0.0.1:8765 (the .exe uses verseforge_app.py)."""
import argparse
import os
import sys
import threading
import time
import urllib.request
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def main():
    ap = argparse.ArgumentParser(description="VerseForge")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="do not open the browser")
    args = ap.parse_args()
    url = f"http://127.0.0.1:{args.port}/"

    try:
        import uvicorn
        from sc_explorer.server import app
    except ImportError as e:
        print(f"Missing dependency: {e.name}. Run:  python -m pip install -r requirements.txt")
        input("Press Enter to close…")
        return

    if not args.no_browser:
        def open_when_ready():
            for _ in range(100):
                try:
                    urllib.request.urlopen(url + "api/status", timeout=1)
                    webbrowser.open(url)
                    return
                except OSError:
                    time.sleep(0.2)
        threading.Thread(target=open_when_ready, daemon=True).start()

    print(f"VerseForge running at {url}  (close this window to stop it)")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
