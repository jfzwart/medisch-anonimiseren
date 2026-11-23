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
RES="$APP/Contents/Resources"
echo "==> Precompile Python files (the app never writes into its own bundle)"
# Same Python version as the one inside the app, so the .pyc files match.
"$BUILD_VENV/bin/python" -I -m compileall -q -j 0 "$RES/lib/python3.12"

echo "==> Prebuild the deduce cache into the app (saves ~30 s on the first start)"
# deduce rebuilds its cache when a lookup source file is newer than the cache. Give the source
# files a fixed old date so time zones or clock differences on the target Mac never trigger that.
# (.py files keep their date so the precompiled .pyc files stay valid.)
find "$RES/lib/python3.12/deduce/data/lookup/src" -not -name '*.py' -exec touch -t 202001010000 {} +
sandbox-exec -p '(version 1)(allow default)(deny network*)' \
  env PYTHONHOME="$RES" "$APP/Contents/MacOS/python" -I -c "
import logging, sys
sys.dont_write_bytecode = True
from pathlib import Path
sys.path[:0] = ['$RES/lib/python312.zip', '$RES/lib/python3.12', '$RES/lib/python3.12/lib-dynload']
from deduce import Deduce
logging.getLogger().setLevel(logging.WARNING)
Deduce(cache_path=Path('$RES/deduce-cache'))
"
test -f "$RES/deduce-cache/cache/lookup_structs.pickle"

echo "==> Ad-hoc signing (required on Apple Silicon)"
codesign --force --deep --sign - "$APP"
codesign --verify --deep "$APP"
echo "==> Done: $APP ($(du -sh "$APP" | cut -f1))"

echo "==> Zip for transfer (ditto preserves the signature)"
ditto -c -k --keepParent "$APP" dist/Anonimiseren.zip
echo "==> Done: dist/Anonimiseren.zip ($(du -sh dist/Anonimiseren.zip | cut -f1))"
