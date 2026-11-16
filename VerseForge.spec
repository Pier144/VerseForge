# PyInstaller spec for VerseForge.exe  ->  python -m PyInstaller VerseForge.spec --noconfirm
# Output: dist/VerseForge/VerseForge.exe (one folder: starts fast, Qt WebEngine needs its resource files next to it)
# Linux: same spec, run by packaging/linux/build_appimage.sh (folder in build/linux, then dist/VerseForge-<v>-x86_64.AppImage)
import glob
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

WINDOWS = sys.platform == "win32"
datas = [("web", "web"), ("assets", "assets")]
datas += collect_data_files("trimesh")            # trimesh/resources (templates, schemas)
binaries = collect_dynamic_libs("embreex") + collect_dynamic_libs("manifold3d")
hiddenimports = (collect_submodules("uvicorn") + collect_submodules("embreex") +
                 ["manifold3d", "skimage.measure", "scipy.ndimage", "zstandard", "Crypto.Cipher.AES"])
if not WINDOWS:
    # Qt WebEngine needs NSS; NSS opens its crypto modules by name at run time (no link PyInstaller can follow):
    # ship them next to libnss3 so the AppImage also starts on systems without NSS installed
    for d in [p for p in os.environ.get("LD_LIBRARY_PATH", "").split(":") if p] + ["/usr/lib/x86_64-linux-gnu",
                                                                                 "/usr/lib64", "/usr/lib"]:
        mods = [f for n in ("libsoftokn3.so", "libfreebl3.so", "libfreeblpriv3.so", "libnssckbi.so", "libnssdbm3.so")
                for f in glob.glob(os.path.join(d, n)) + glob.glob(os.path.join(d, "nss", n))]
        if mods and os.path.exists(os.path.join(d, "libnss3.so")):
            binaries += [(f, ".") for f in mods]
            break

# big packages installed on this PC that VerseForge never uses
excludes = ["torch", "torchvision", "transformers", "tokenizers", "safetensors", "timm", "onnxruntime", "cv2",
            "kivy", "kivy_deps", "matplotlib", "IPython", "numba", "llvmlite", "tkinter", "PyQt5", "PyQt6",
            "sympy", "pandas", "networkx", "albumentations", "albucore", "kornia", "rembg", "pymupdf", "fitz",
            "transparent_background", "huggingface_hub", "anthropic", "openpyxl", "reportlab", "colour",
            "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtMultimedia", "PySide6.QtCharts",
            "PySide6.QtDataVisualization", "PySide6.QtQuick3D", "PySide6.QtBluetooth", "PySide6.QtSql",
            "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtPdf", "PySide6.QtLocation", "PySide6.QtSensors",
            "PySide6.QtSerialPort", "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech", "PySide6.QtGraphs"]

a = Analysis(["verseforge_app.py"], pathex=["."], binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=excludes, noarchive=False)


def _keep(dest):
    """Drop Qt files VerseForge never uses (~170 MB): debug paks, devtools, QML, translations (English only)."""
    d = dest.replace("\\", "/").lower()
    if "pyside6/" not in d:
        return True
    name = d.rsplit("/", 1)[-1]
    if ".debug." in name or "devtools_resources" in name:
        return False
    if "/qml/" in d or "/plugins/qmltooling/" in d:
        return False
    if "/translations/qtwebengine_locales/" in d:
        return name == "en-us.pak"
    if "/translations/" in d:
        return False                  # Qt is English by default: no .qm files needed
    return True


a.datas = [x for x in a.datas if _keep(x[0])]
a.binaries = [x for x in a.binaries if _keep(x[0])]
pyz = PYZ(a.pure)
if WINDOWS:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="VerseForge", icon="assets/verseforge.ico",
              console=False, upx=False, version="version_info.txt")
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="VerseForge", console=False, upx=False, strip=False)
coll = COLLECT(exe, a.binaries, a.datas, name="VerseForge", upx=False)
