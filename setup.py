"""Builds Anonimiseren.app with py2app. Usage: scripts/build_app.sh"""

import sys

from setuptools import setup

sys.path.insert(0, "src")
sys.setrecursionlimit(5000)  # modulegraph needs this for numpy

VERSION = "0.2.0"

# Files that may be dropped on the app icon. Rank "Alternate": the app does NOT become
# the default app for Word/PDF, it only shows up under "Open With".
DOCUMENT_TYPES = [
    ("Word document", ["docx"], ["org.openxmlformats.wordprocessingml.document"]),
    ("Legacy Word document", ["doc"], ["com.microsoft.word.doc"]),
    ("RTF/ODT document", ["rtf", "odt"], ["public.rtf", "org.oasis-open.opendocument.text"]),
    ("PDF", ["pdf"], ["com.adobe.pdf"]),
    ("Photo or scan", ["jpg", "jpeg", "png", "heic", "heif", "tif", "tiff"], ["public.image"]),
    ("Folder", [], ["public.folder"]),
]

OPTIONS = {
    "iconfile": "resources/Anonimiseren.icns",
    "arch": "arm64",
    # Shipped as directories (not zipped): deduce reads its lookup lists from disk.
    "packages": [
        "anonymizer", "deduce", "docdeid", "docx", "pypdfium2", "pypdfium2_raw",
        "PIL", "rapidfuzz", "regex", "frozendict", "numpy", "lxml",
    ],
    "includes": ["Vision", "Quartz", "AppKit", "Foundation", "objc"],
    "excludes": ["tkinter", "setuptools", "pip", "wheel", "py2app", "pkg_resources"],
    "plist": {
        "CFBundleName": "Anonimiseren",
        "CFBundleDisplayName": "Anonimiseren",
        "CFBundleIdentifier": "nl.jfzwart.anonimiseren",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "14.0",
        "LSApplicationCategoryType": "public.app-category.productivity",
        "NSHumanReadableCopyright": "Werkt volledig offline. Gebouwd met deduce (LGPL-3.0).",
        "NSHighResolutionCapable": True,
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": name,
                "CFBundleTypeRole": "Viewer",
                "LSHandlerRank": "Alternate",
                "CFBundleTypeExtensions": extensions,
                "LSItemContentTypes": utis,
            }
            for name, extensions, utis in DOCUMENT_TYPES
        ],
    },
}

setup(
    name="Anonimiseren",
    version=VERSION,
    app=["app_main.py"],
    options={"py2app": OPTIONS},
)
