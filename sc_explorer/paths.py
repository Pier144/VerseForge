"""Where VerseForge keeps its files and finds the game, on Windows and on Linux.

Windows: settings in %APPDATA%\\VerseForge, caches and log in %LOCALAPPDATA%\\VerseForge.
Linux: the XDG folders (~/.config/VerseForge, ~/.cache/VerseForge). Star Citizen has no Linux client: players run it
through Wine (Lutris, Bottles, Heroic, a plain prefix...), so Data.p4k sits inside a Wine prefix's drive_c."""
import glob
import os
import re
import subprocess
import sys

from . import APP_NAME

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOWS = sys.platform == "win32"
HOME = os.path.expanduser("~")
WINDOWS_P4K = r"C:\Program Files\Roberts Space Industries\StarCitizen\LIVE\Data.p4k"
CHANNELS = ("LIVE", "PTU", "EPTU", "TECH-PREVIEW", "HOTFIX")
WSL_ROOTS = ["/mnt/c/Program Files"]      # the Windows install seen from WSL (Linux on the same PC)


def _xdg(var, fallback):
    value = os.environ.get(var, "")
    return value if os.path.isabs(value) else os.path.join(HOME, fallback)


def data_dir():
    """Settings (config.json)."""
    if WINDOWS:
        return os.path.join(os.environ.get("APPDATA", APP_DIR), APP_NAME)
    return os.path.join(_xdg("XDG_CONFIG_HOME", ".config"), APP_NAME)


def cache_dir():
    """Index, built models and textures, log: everything that can be thrown away."""
    if WINDOWS:
        return os.path.join(os.environ.get("LOCALAPPDATA", APP_DIR), APP_NAME)
    return os.path.join(_xdg("XDG_CACHE_HOME", ".cache"), APP_NAME)


def documents_dir():
    """Default export folder: Documents/VerseForge (the localised XDG documents folder on Linux when it is set)."""
    docs = os.path.join(HOME, "Documents")
    if not WINDOWS:
        try:
            for line in open(os.path.join(_xdg("XDG_CONFIG_HOME", ".config"), "user-dirs.dirs"), encoding="utf-8"):
                if line.startswith("XDG_DOCUMENTS_DIR="):
                    value = line.split("=", 1)[1].strip().strip('"').replace("$HOME", HOME)
                    if os.path.isabs(value) and os.path.normpath(value) != os.path.normpath(HOME):
                        docs = value
        except OSError:
            pass
        if os.path.lexists(docs) and not os.path.isdir(docs):    # e.g. a broken link to a Windows folder (WSL)
            docs = HOME
    return os.path.join(docs, APP_NAME)


def wine_prefixes():
    """Wine prefixes where Star Citizen is usually installed on Linux (existing folders only, most likely first)."""
    patterns = [
        "~/Games/star-citizen",                                   # LUG helper / Lutris installer default
        "~/Games/star_citizen", "~/Games/StarCitizen", "~/Games/*",
        "~/.local/share/lutris/prefixes/*",
        "~/.local/share/bottles/bottles/*",                       # Bottles
        "~/.var/app/com.usebottles.bottles/data/bottles/bottles/*",   # Bottles (flatpak)
        "~/Games/Heroic/Prefixes/*", "~/Games/Heroic/Prefixes/default/*",
        "~/.var/app/net.lutris.Lutris/data/lutris/prefixes/*",
        "~/.wine", "~/.wine*", "~/.local/share/wineprefixes/*",
        "~/.steam/steam/steamapps/compatdata/*/pfx", "~/.local/share/Steam/steamapps/compatdata/*/pfx",
    ]
    seen, out = set(), []
    for p in patterns:
        for d in sorted(glob.glob(os.path.expanduser(p))):
            d = os.path.realpath(d)
            if d not in seen and os.path.isdir(os.path.join(d, "drive_c")):
                seen.add(d)
                out.append(d)
    return out


def windows_drives():
    return [f"{d}:\\" for d in "CDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.isdir(f"{d}:\\")]


def launcher_game_dirs():
    """"...\\StarCitizen" folders named in the RSI Launcher's log (%APPDATA%\\rsilauncher\\logs\\log.log): where the
    launcher installed or started the game, whatever disk and folder the player chose. Newest first."""
    log = os.path.join(os.environ.get("APPDATA", ""), "rsilauncher", "logs", "log.log")
    try:
        with open(log, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 4_000_000))
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    text = text.replace("\\\\", "\\").replace("/", "\\")
    found = re.findall(r"([A-Za-z]:\\[^\r\n\"<>|*?:]*?\\StarCitizen)\\(?:%s)\b" % "|".join(CHANNELS), text)
    return list(dict.fromkeys(reversed(found)))


def p4k_candidates():
    """Possible Data.p4k locations on this computer, most likely first (they may not exist)."""
    if WINDOWS:
        games = launcher_game_dirs()
        for drive in windows_drives():                  # the usual folders on every disk (C: first)
            for sub in ("Program Files", "", "Games", "Program Files (x86)"):
                games.append(os.path.join(drive, sub, "Roberts Space Industries", "StarCitizen"))
            games += [os.path.join(drive, "StarCitizen"), os.path.join(drive, "Games", "StarCitizen")]
        return [os.path.join(g, c, "Data.p4k") for c in CHANNELS for g in games]
    roots = [os.path.join(prefix, "drive_c", sub) for prefix in wine_prefixes()
             for sub in ("Program Files", "Program Files (x86)", "Games", "")]
    roots += WSL_ROOTS
    out = []
    for c in CHANNELS:                                           # every LIVE before any PTU
        out += [os.path.join(r, "Roberts Space Industries", "StarCitizen", c, "Data.p4k") for r in roots]
    return out


def resolve_p4k(text):
    """Data.p4k from what the user typed or picked: the file itself, or a folder above it (the channel folder
    "LIVE", "StarCitizen", "Roberts Space Industries" or the one that holds it). None when it is not there."""
    p = os.path.expanduser((text or "").strip().strip('"'))
    if os.path.isfile(p):
        return p
    if not os.path.isdir(p):
        return None
    game = [""] + [os.path.join(*parts) for parts in (("StarCitizen",), ("Roberts Space Industries", "StarCitizen"))]
    for c in ("",) + CHANNELS:                                  # the folder itself, then LIVE before PTU
        for g in game:
            f = os.path.join(p, g, c, "Data.p4k")
            if os.path.isfile(f):
                return os.path.normpath(f)
    return None


def find_p4k():
    """First Data.p4k that exists; else the usual location (shown in the settings, the user can change it)."""
    cands = p4k_candidates()
    found = next((c for c in cands if os.path.isfile(c)), None)
    if found:
        return found
    if WINDOWS:
        return WINDOWS_P4K
    return os.path.join(HOME, "Games", "star-citizen", "drive_c", "Program Files", "Roberts Space Industries",
                        "StarCitizen", "LIVE", "Data.p4k")


def child_env():
    """Environment for programs VerseForge starts (file manager, browser, Blender).

    The frozen Linux app (PyInstaller, AppImage) points LD_LIBRARY_PATH and the Qt variables at its own bundled
    libraries: other programs must get the user's original environment back or they may crash."""
    env = dict(os.environ)
    if WINDOWS or not getattr(sys, "frozen", False):
        return env
    orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if orig is not None:
        env["LD_LIBRARY_PATH"] = orig
    else:
        env.pop("LD_LIBRARY_PATH", None)
    for k in ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "QTWEBENGINEPROCESS_PATH", "QTWEBENGINE_RESOURCES_PATH",
              "QTWEBENGINE_LOCALES_PATH", "QTWEBENGINE_CHROMIUM_FLAGS", "QT_QPA_PLATFORM_PLUGIN_PATH"):
        env.pop(k, None)
    return env


def open_path(target):
    """Open a folder in the file manager, or a web address in the browser."""
    if WINDOWS:
        os.startfile(target)
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, target], env=child_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
