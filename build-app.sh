#!/bin/bash
# Builds "PJ Print.app" (GUI launcher + bundled venv) and a drag-to-install DMG.
# Result: dist/PJ-Print-<VERSION>.dmg
set -euo pipefail
cd "$(dirname "$0")"

VERSION=${VERSION:-1.0}
APP="build/PJ Print.app"
RES="$APP/Contents/Resources"

rm -rf build dist
mkdir -p "$APP/Contents/MacOS" "$RES" dist

cp app/pjprint "$APP/Contents/MacOS/pjprint"
chmod +x "$APP/Contents/MacOS/pjprint"
cp app/Info.plist "$APP/Contents/"
printf 'APPL????' > "$APP/Contents/PkgInfo"
cp app/app.icns "$RES/"
cp pj_print.py "$RES/"

# Bundled Python environment (arm64 wheels; the launcher forces arm64 execution)
PYTHON=${PYTHON:-/usr/bin/python3}
if [ "$(sysctl -n hw.optional.arm64 2>/dev/null)" = "1" ]; then
  arch -arm64 "$PYTHON" -m venv "$RES/venv"
else
  "$PYTHON" -m venv "$RES/venv"
fi
"$RES/venv/bin/pip" install -q --upgrade pip
"$RES/venv/bin/pip" install -q pillow pypdfium2

# DMG layout
mkdir -p build/dmg
cp -R "$APP" build/dmg/
cp app/LIESMICH.txt build/dmg/
ln -s /Applications build/dmg/Applications
hdiutil create -volname "PJ Print" -srcfolder build/dmg -ov -format UDZO \
  "dist/PJ-Print-$VERSION.dmg"
echo "-> dist/PJ-Print-$VERSION.dmg"
