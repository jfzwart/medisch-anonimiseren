"""Renders the app window to a PNG (no screen-recording permission needed). For development.

Usage: .venv/bin/python -I tests/render_window.py out.png [dark] [loading]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from AppKit import NSAppearance, NSApplication, NSBitmapImageFileTypePNG, NSColor  # noqa: E402

from anonymizer.app import AppDelegate, _styled  # noqa: E402


def render(out: str, dark: bool, ready: bool):
    app = NSApplication.sharedApplication()
    if dark:
        app.setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua"))
    d = AppDelegate.alloc().init()
    d._build_window()
    d.drop_zone.enabled = ready
    if ready:
        d.status.setStringValue_("Klaar! De nieuwe bestanden staan in Finder geselecteerd.")
        for text, color in [
            ("✓  Brief cardiologie.docx  →  klaar (20 gegevens vervangen)", NSColor.systemGreenColor()),
            ("✓  gescande brief.pdf  →  klaar (23 gegevens vervangen)", NSColor.systemGreenColor()),
            ("    !  Tekst is herkend uit een scan. Controleer of handgeschreven namen goed zijn verwijderd.",
             NSColor.systemOrangeColor()),
        ]:
            d.log_view.textStorage().appendAttributedString_(_styled(text + "\n", 13, color, centered=False))
    else:
        d.status.setStringValue_("Klaarzetten… dit duurt ongeveer een halve minuut")
    view = d.window.contentView()
    view.layoutSubtreeIfNeeded()
    rep = view.bitmapImageRepForCachingDisplayInRect_(view.bounds())
    view.cacheDisplayInRect_toBitmapImageRep_(view.bounds(), rep)
    rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, None).writeToFile_atomically_(out, True)
    d.window.orderOut_(None)


if __name__ == "__main__":
    args = sys.argv[1:]
    render(args[0], dark="dark" in args[1:], ready="loading" not in args[1:])
