#!/usr/bin/env bash
# Build the Linux AppImage from the PyInstaller folder.
#
#   packaging/linux/build_appimage.sh <version> [pyinstaller dist folder]
#
# The dist folder defaults to packaging/dist (it must contain opticore-studio/). appimagetool must be on PATH or in
# $APPIMAGETOOL. The result is packaging/dist/OptiCore-Studio-<version>-x86_64.AppImage.
set -euo pipefail

VERSION="$1"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIST="${2:-$ROOT/packaging/dist}"
APPDIR="$(mktemp -d)/OptiCore-Studio.AppDir"
OUT="$ROOT/packaging/dist/OptiCore-Studio-$VERSION-x86_64.AppImage"

mkdir -p "$APPDIR/usr/lib" "$(dirname "$OUT")"
cp -a "$DIST/opticore-studio" "$APPDIR/usr/lib/"
install -m 755 "$ROOT/packaging/linux/AppRun" "$APPDIR/AppRun"
cp "$ROOT/packaging/linux/opticore-studio.desktop" "$APPDIR/"
cp "$ROOT/packaging/assets/opticore-studio.png" "$APPDIR/opticore-studio.png"
ln -sf opticore-studio.png "$APPDIR/.DirIcon"

ARCH=x86_64 "${APPIMAGETOOL:-appimagetool}" --no-appstream "$APPDIR" "$OUT"
rm -rf "$(dirname "$APPDIR")"
echo "Built $OUT"
