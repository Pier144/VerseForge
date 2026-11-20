"""The system's own "choose a file / folder" window, opened by the server for the Browse buttons of the page.

The page cannot ask the system for a path (a browser only hands over file contents), and the server runs on the
user's PC in both versions (windowed app and browser), so the dialog is opened here: Windows through the common
dialogs (ctypes, nothing to install), Linux through zenity or kdialog when one of them is there."""
import os
import shutil
import subprocess
import sys

WINDOWS = sys.platform == "win32"


def available():
    return WINDOWS or bool(shutil.which("zenity") or shutil.which("kdialog"))


def _start_dir(start):
    """The nearest existing folder at or above the path typed so far."""
    d = os.path.expanduser((start or "").strip().strip('"'))
    while d and not os.path.isdir(d):
        up = os.path.dirname(d)
        if up == d:
            return ""
        d = up
    return d


def pick_file(title, patterns, start=""):
    """Path of the file chosen, "" when the user cancels. patterns: [(label, "Data.p4k"), (label, "*.exe")]."""
    start = _start_dir(start)
    if WINDOWS:
        return _windows_file(title, patterns, start)
    if shutil.which("zenity"):
        cmd = ["zenity", "--file-selection", f"--title={title}"]
        cmd += [f"--file-filter={label} | {pattern}" for label, pattern in patterns]
        if start:
            cmd.append(f"--filename={start}{os.sep}")
        return _run(cmd)
    if shutil.which("kdialog"):
        return _run(["kdialog", "--title", title, "--getopenfilename", start or os.path.expanduser("~"),
                     " ".join(pattern for _, pattern in patterns)])
    return ""


def pick_folder(title, start=""):
    start = _start_dir(start)
    if WINDOWS:
        return _windows_folder(title, start)
    if shutil.which("zenity"):
        cmd = ["zenity", "--file-selection", "--directory", f"--title={title}"]
        if start:
            cmd.append(f"--filename={start}{os.sep}")
        return _run(cmd)
    if shutil.which("kdialog"):
        return _run(["kdialog", "--title", title, "--getexistingdirectory", start or os.path.expanduser("~")])
    return ""


def _run(cmd):
    from . import paths
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, env=paths.child_env())
    except OSError:
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


# ------------------------------------------------------------------ Windows
def _windows_file(title, patterns, start):
    import ctypes
    from ctypes import wintypes

    class OPENFILENAMEW(ctypes.Structure):
        _fields_ = [("lStructSize", wintypes.DWORD), ("hwndOwner", wintypes.HWND), ("hInstance", wintypes.HINSTANCE),
                    ("lpstrFilter", wintypes.LPCWSTR), ("lpstrCustomFilter", wintypes.LPWSTR),
                    ("nMaxCustFilter", wintypes.DWORD), ("nFilterIndex", wintypes.DWORD),
                    ("lpstrFile", wintypes.LPWSTR), ("nMaxFile", wintypes.DWORD),
                    ("lpstrFileTitle", wintypes.LPWSTR), ("nMaxFileTitle", wintypes.DWORD),
                    ("lpstrInitialDir", wintypes.LPCWSTR), ("lpstrTitle", wintypes.LPCWSTR),
                    ("Flags", wintypes.DWORD), ("nFileOffset", wintypes.WORD), ("nFileExtension", wintypes.WORD),
                    ("lpstrDefExt", wintypes.LPCWSTR), ("lCustData", wintypes.LPARAM),
                    ("lpfnHook", ctypes.c_void_p), ("lpTemplateName", wintypes.LPCWSTR),
                    ("pvReserved", ctypes.c_void_p), ("dwReserved", wintypes.DWORD), ("FlagsEx", wintypes.DWORD)]

    OFN_EXPLORER, OFN_FILEMUSTEXIST, OFN_PATHMUSTEXIST = 0x80000, 0x1000, 0x800
    OFN_HIDEREADONLY, OFN_NOCHANGEDIR = 0x4, 0x8
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    buf = ctypes.create_unicode_buffer(4096)
    ofn = OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
    ofn.hwndOwner = user32.GetForegroundWindow()       # VerseForge's window: the user has just clicked in it
    ofn.lpstrFilter = "".join(f"{label}\0{pattern}\0" for label, pattern in patterns) + "\0"
    ofn.lpstrFile = ctypes.cast(buf, wintypes.LPWSTR)
    ofn.nMaxFile = len(buf)
    ofn.lpstrInitialDir = start or None
    ofn.lpstrTitle = title
    ofn.Flags = OFN_EXPLORER | OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_HIDEREADONLY | OFN_NOCHANGEDIR
    get = ctypes.windll.comdlg32.GetOpenFileNameW
    get.argtypes, get.restype = [ctypes.POINTER(OPENFILENAMEW)], wintypes.BOOL
    return buf.value if get(ctypes.byref(ofn)) else ""


def _windows_folder(title, start):
    import ctypes
    from ctypes import wintypes

    CALLBACK = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HWND, wintypes.UINT, wintypes.LPARAM, wintypes.LPARAM)

    class BROWSEINFOW(ctypes.Structure):
        _fields_ = [("hwndOwner", wintypes.HWND), ("pidlRoot", ctypes.c_void_p), ("pszDisplayName", wintypes.LPWSTR),
                    ("lpszTitle", wintypes.LPCWSTR), ("ulFlags", wintypes.UINT), ("lpfn", CALLBACK),
                    ("lParam", wintypes.LPARAM), ("iImage", ctypes.c_int)]

    BIF_RETURNONLYFSDIRS, BIF_NEWDIALOGSTYLE, BFFM_INITIALIZED, BFFM_SETSELECTIONW = 0x1, 0x40, 1, 0x467
    user32, shell32, ole32 = ctypes.windll.user32, ctypes.windll.shell32, ctypes.windll.ole32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPCWSTR]
    shell32.SHBrowseForFolderW.argtypes, shell32.SHBrowseForFolderW.restype = [ctypes.POINTER(BROWSEINFOW)], ctypes.c_void_p
    shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]

    def on_message(hwnd, msg, _lp, _data):
        if msg == BFFM_INITIALIZED and start:
            user32.SendMessageW(hwnd, BFFM_SETSELECTIONW, 1, start)
        return 0

    ole32.OleInitialize(None)                          # the new dialog style needs it on this thread
    try:
        name = ctypes.create_unicode_buffer(260)
        info = BROWSEINFOW()
        info.hwndOwner = user32.GetForegroundWindow()
        info.pszDisplayName = ctypes.cast(name, wintypes.LPWSTR)
        info.lpszTitle = title
        info.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE
        info.lpfn = CALLBACK(on_message)
        pidl = shell32.SHBrowseForFolderW(ctypes.byref(info))
        if not pidl:
            return ""
        path = ctypes.create_unicode_buffer(4096)
        ok = shell32.SHGetPathFromIDListW(pidl, path)
        ole32.CoTaskMemFree(pidl)
        return path.value if ok else ""
    finally:
        ole32.OleUninitialize()
