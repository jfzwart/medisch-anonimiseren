#!/bin/zsh
# Builds dist/Anonimiseren.app — fully offline, only from wheels/ and build-wheels/.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=/opt/homebrew/bin/python3.12
BUILD_VENV=.venv-build

echo "==> Clean build environment"
rm -rf "$BUILD_VENV" build dist
$PY -m venv "$BUILD_VENV"
"$BUILD_VENV/bin/pip" install -q --no-index --find-links wheels --require-hashes -r requirements.lock
"$BUILD_VENV/bin/pip" install -q --no-index --find-links build-wheels --require-hashes -r build-requirements.lock

echo "==> Icon"
"$BUILD_VENV/bin/python" -I scripts/make_icon.py resources/Anonimiseren.icns

echo "==> Build app (py2app)"
mkdir -p build
"$BUILD_VENV/bin/python" setup.py py2app > build/py2app.log 2>&1 || { tail -40 build/py2app.log; exit 1; }

APP=dist/Anonimiseren.app
echo "==> Ad-hoc signing (required on Apple Silicon)"
codesign --force --deep --sign - "$APP"
codesign --verify --deep "$APP"
echo "==> Done: $APP ($(du -sh "$APP" | cut -f1))"

echo "==> Zip for transfer (ditto preserves the signature)"
ditto -c -k --keepParent "$APP" dist/Anonimiseren.zip
echo "==> Done: dist/Anonimiseren.zip ($(du -sh dist/Anonimiseren.zip | cut -f1))"
