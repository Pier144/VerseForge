#!/usr/bin/env bash
# Linux build: PyInstaller folder (same VerseForge.spec as Windows) -> AppDir -> dist/VerseForge-<version>-x86_64.AppImage
#
#   python3 -m pip install -r requirements-build.txt      # once (Python 3.10+)
#   packaging/linux/build_appimage.sh
#
# WORK_DIR (default build/linux) holds the PyInstaller work files and the AppDir; put it on a native Linux disk when
# the sources sit on a Windows drive (WSL: /mnt/...), it is much faster.
# APPIMAGE_UPDATE_INFO=1 embeds GitHub update information and writes the .zsync file next to the AppImage
# (AppImageUpdate / Gear Lever then update it in place; the GitHub Actions build does this).
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT="$PWD"
PY="${PYTHON:-python3}"
VERSION="$("$PY" -c 'import sc_explorer; print(sc_explorer.__version__)')"
WORK="${WORK_DIR:-$ROOT/build/linux}"
OUT="$ROOT/dist"
APPDIR="$WORK/VerseForge.AppDir"
TOOL_VERSION=1.9.1
TOOL="$WORK/appimagetool-$TOOL_VERSION-x86_64.AppImage"
NAME="VerseForge-$VERSION-x86_64.AppImage"

echo "== PyInstaller ($VERSION)"
"$PY" -m PyInstaller VerseForge.spec --noconfirm --workpath "$WORK/pyinstaller" --distpath "$WORK/dist"

echo "== AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a "$WORK/dist/VerseForge" "$APPDIR/usr/lib/verseforge"
install -m 755 packaging/linux/AppRun "$APPDIR/AppRun"
cp packaging/linux/verseforge.desktop "$APPDIR/verseforge.desktop"
cp packaging/linux/verseforge.desktop "$APPDIR/usr/share/applications/"
"$PY" - "$APPDIR" <<'PY'
import sys
from PIL import Image
appdir = sys.argv[1]
im = Image.open("assets/verseforge.png").convert("RGBA").resize((256, 256), Image.LANCZOS)
im.save(f"{appdir}/verseforge.png")
im.save(f"{appdir}/usr/share/icons/hicolor/256x256/apps/verseforge.png")
PY
ln -sf verseforge.png "$APPDIR/.DirIcon"

echo "== appimagetool"
if [ ! -x "$TOOL" ]; then
  curl -fsSL -o "$TOOL" "https://github.com/AppImage/appimagetool/releases/download/$TOOL_VERSION/appimagetool-x86_64.AppImage"
  chmod +x "$TOOL"
fi
mkdir -p "$OUT"
ARGS=()
if [ "${APPIMAGE_UPDATE_INFO:-0}" = "1" ]; then
  ARGS+=(-u "gh-releases-zsync|Pier144|VerseForge|latest|VerseForge-*-x86_64.AppImage.zsync")
fi
# --appimage-extract-and-run: works without FUSE (containers, CI)
( cd "$OUT" && ARCH=x86_64 "$TOOL" --appimage-extract-and-run "${ARGS[@]}" "$APPDIR" "$OUT/$NAME" )
chmod +x "$OUT/$NAME"
ls -la "$OUT/$NAME"
