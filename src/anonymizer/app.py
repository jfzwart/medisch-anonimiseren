"""The Mac app: a window with a large drop zone.

Files can be provided in three ways:
  1. dragging them onto the zone in the window
  2. clicking the zone (or "Kies bestanden…") and selecting them
  3. dragging them onto the app icon in the Dock or in Finder

Processing runs on a background thread so the window never freezes.
All text shown to the user is Dutch.
"""

from __future__ import annotations

import queue
import subprocess
import threading
from pathlib import Path

import objc
from AppKit import (
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyRegular,
    NSApplicationDelegateReplySuccess,
    NSAttributedString,
    NSBackingStoreBuffered,
    NSBezelBorder,
    NSBezierPath,
    NSButton,
    NSColor,
    NSDragOperationCopy,
    NSDragOperationNone,
    NSFont,
    NSFontAttributeName,
    NSFontWeightSemibold,
    NSForegroundColorAttributeName,
    NSImage,
    NSImageSymbolConfiguration,
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSModalResponseOK,
    NSMutableParagraphStyle,
    NSOpenPanel,
    NSParagraphStyleAttributeName,
    NSPasteboardTypeFileURL,
    NSPasteboardURLReadingFileURLsOnlyKey,
    NSScrollView,
    NSTextAlignmentCenter,
    NSTextField,
    NSTextView,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskTitled,
    NSWorkspace,
)
from Foundation import NSURL, NSObject
from PyObjCTools import AppHelper

from . import settings as settings_module
from .pipeline import DEFAULT_OUTPUT_DIR, collect_files, process_file

APP_NAME = "Anonimiseren"
WIDTH, HEIGHT = 580, 560


def _font(size: float, bold: bool = False):
    return NSFont.systemFontOfSize_weight_(size, NSFontWeightSemibold) if bold else NSFont.systemFontOfSize_(size)


def _styled(text: str, size: float, color=None, bold: bool = False, centered: bool = True):
    style = NSMutableParagraphStyle.alloc().init()
    if centered:
        style.setAlignment_(NSTextAlignmentCenter)
    return NSAttributedString.alloc().initWithString_attributes_(text, {
        NSFontAttributeName: _font(size, bold),
        NSForegroundColorAttributeName: color or NSColor.labelColor(),
        NSParagraphStyleAttributeName: style,
    })


def _label(text: str, rect, size: float, color=None, bold: bool = False) -> NSTextField:
    field = NSTextField.wrappingLabelWithString_(text)
    field.setFrame_(rect)
    field.setAlignment_(NSTextAlignmentCenter)
    field.setFont_(_font(size, bold))
    if color is not None:
        field.setTextColor_(color)
    return field


class DropZone(NSView):
    """Large area with a dashed border that accepts dropped files."""

    def initWithFrame_(self, frame):
        self = objc.super(DropZone, self).initWithFrame_(frame)
        if self is None:
            return None
        self.registerForDraggedTypes_([NSPasteboardTypeFileURL])
        self.highlighted = False
        self.enabled = False
        self.on_files = None  # callable(list[str])
        self.on_click = None
        return self

    # ---- drawing ----
    def drawRect_(self, _rect):
        b = self.bounds()
        box = NSMakeRect(b.origin.x + 4, b.origin.y + 4, b.size.width - 8, b.size.height - 8)
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(box, 18, 18)

        accent = NSColor.controlAccentColor()
        if self.highlighted:
            accent.colorWithAlphaComponent_(0.15).setFill()
        else:
            NSColor.quaternaryLabelColor().colorWithAlphaComponent_(0.08).setFill()
        path.fill()

        (accent if self.highlighted else NSColor.tertiaryLabelColor()).setStroke()
        path.setLineWidth_(3 if self.highlighted else 2)
        path.setLineDash_count_phase_([10.0, 6.0], 2, 0.0)
        path.stroke()

        center_x = b.size.width / 2
        icon = self._icon(accent if self.enabled else NSColor.tertiaryLabelColor())
        if icon is not None:
            size = 64
            icon.drawInRect_(NSMakeRect(center_x - size / 2, b.size.height / 2 + 6, size, size))

        if self.enabled:
            title, hint = "Sleep je brieven hierheen", "Word, PDF, scan of foto — of klik om bestanden te kiezen"
        else:
            title, hint = "Even geduld…", "Het programma wordt klaargezet"
        _styled(title, 22, bold=True).drawInRect_(NSMakeRect(10, b.size.height / 2 - 34, b.size.width - 20, 32))
        _styled(hint, 14, NSColor.secondaryLabelColor()).drawInRect_(
            NSMakeRect(10, b.size.height / 2 - 62, b.size.width - 20, 22))

    @staticmethod
    def _icon(color):
        try:
            img = NSImage.imageWithSystemSymbolName_accessibilityDescription_("doc.badge.arrow.up", None)
            config = NSImageSymbolConfiguration.configurationWithPointSize_weight_(48, 0.0)
            config = config.configurationByApplyingConfiguration_(
                NSImageSymbolConfiguration.configurationWithHierarchicalColor_(color))
            return img.imageWithSymbolConfiguration_(config)
        except Exception:  # noqa: BLE001 — the icon is not essential
            return None

    @objc.python_method
    def _set_highlighted(self, value: bool):
        self.highlighted = value
        self.setNeedsDisplay_(True)

    # ---- drag and drop ----
    def draggingEntered_(self, _sender):
        if not self.enabled:
            return NSDragOperationNone
        self._set_highlighted(True)
        return NSDragOperationCopy

    def draggingExited_(self, _sender):
        self._set_highlighted(False)

    def performDragOperation_(self, sender):
        urls = sender.draggingPasteboard().readObjectsForClasses_options_(
            [NSURL], {NSPasteboardURLReadingFileURLsOnlyKey: True}) or []
        self._set_highlighted(False)
        paths = [u.path() for u in urls]
        if paths and self.on_files:
            self.on_files(paths)
        return bool(paths)

    def mouseDown_(self, _event):
        if self.enabled and self.on_click:
            self.on_click()


class AppDelegate(NSObject):
    def init(self):
        self = objc.super(AppDelegate, self).init()
        if self is None:
            return None
        self.jobs: queue.Queue = queue.Queue()
        self.anonymizer = None
        self.window = None
        return self

    # ---- startup ----
    def applicationDidFinishLaunching_(self, _notification):
        self._build_menu()
        self._build_window()
        threading.Thread(target=self._worker, daemon=True).start()

    def application_openFiles_(self, app, filenames):
        """Files dropped on the app icon (also when that is what launches the app)."""
        self.enqueue(list(filenames))
        app.replyToOpenOrPrint_(NSApplicationDelegateReplySuccess)

    def applicationShouldTerminateAfterLastWindowClosed_(self, _app):
        return True

    @objc.python_method
    def _build_menu(self):
        main_menu = NSMenu.alloc().init()
        app_item = NSMenuItem.alloc().init()
        main_menu.addItem_(app_item)
        menu = NSMenu.alloc().initWithTitle_(APP_NAME)
        for title, action, key in [
            (f"Over {APP_NAME}", "orderFrontStandardAboutPanel:", ""),
            (None, None, None),
            ("Mijn gegevens bewerken…", "editSettings:", ","),
            ("Open map met resultaten", "openResults:", "r"),
            (None, None, None),
            (f"Verberg {APP_NAME}", "hide:", "h"),
            (f"Stop {APP_NAME}", "terminate:", "q"),
        ]:
            if title is None:
                menu.addItem_(NSMenuItem.separatorItem())
            else:
                item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)
                if action in ("editSettings:", "openResults:"):
                    item.setTarget_(self)
                menu.addItem_(item)
        app_item.setSubmenu_(menu)
        NSApp.setMainMenu_(main_menu)

    @objc.python_method
    def _build_window(self):
        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable
        w = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, WIDTH, HEIGHT), style, NSBackingStoreBuffered, False)
        w.setTitle_(APP_NAME)
        w.setReleasedWhenClosed_(False)
        content = w.contentView()

        content.addSubview_(_label("Brieven anonimiseren", NSMakeRect(24, HEIGHT - 60, WIDTH - 48, 34), 26, bold=True))
        content.addSubview_(_label(
            "Namen, adressen, geboortedatum en andere persoonlijke gegevens worden eruit gehaald. "
            "Alles blijft op deze computer.",
            NSMakeRect(40, HEIGHT - 108, WIDTH - 80, 40), 14, NSColor.secondaryLabelColor()))

        self.drop_zone = DropZone.alloc().initWithFrame_(NSMakeRect(24, 210, WIDTH - 48, HEIGHT - 330))
        self.drop_zone.on_files = self.enqueue
        self.drop_zone.on_click = lambda: self.chooseFiles_(None)
        content.addSubview_(self.drop_zone)

        self.status = _label("", NSMakeRect(24, 172, WIDTH - 48, 26), 16, bold=True)
        content.addSubview_(self.status)

        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(24, 62, WIDTH - 48, 104))
        scroll.setHasVerticalScroller_(True)
        scroll.setBorderType_(NSBezelBorder)
        self.log_view = NSTextView.alloc().initWithFrame_(scroll.contentView().bounds())
        self.log_view.setEditable_(False)
        self.log_view.setAutoresizingMask_(2)  # follow width
        self.log_view.setTextContainerInset_((6, 6))
        scroll.setDocumentView_(self.log_view)
        content.addSubview_(scroll)

        choose = NSButton.buttonWithTitle_target_action_("Kies bestanden…", self, "chooseFiles:")
        choose.setFrame_(NSMakeRect(20, 16, 200, 34))
        choose.setFont_(_font(14))
        choose.setEnabled_(False)
        content.addSubview_(choose)
        self.choose_button = choose

        open_results = NSButton.buttonWithTitle_target_action_("Open map met resultaten", self, "openResults:")
        open_results.setFrame_(NSMakeRect(WIDTH - 260, 16, 240, 34))
        open_results.setFont_(_font(14))
        content.addSubview_(open_results)

        w.center()
        w.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)
        self.window = w

    # ---- buttons and menu ----
    def chooseFiles_(self, _sender):
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(True)
        panel.setCanChooseDirectories_(True)
        panel.setAllowsMultipleSelection_(True)
        panel.setPrompt_("Anonimiseer")
        panel.setMessage_("Kies de brieven die je wilt anonimiseren")
        if panel.runModal() == NSModalResponseOK:
            self.enqueue([u.path() for u in panel.URLs()])

    def openResults_(self, _sender):
        DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        NSWorkspace.sharedWorkspace().openURL_(NSURL.fileURLWithPath_(str(DEFAULT_OUTPUT_DIR)))

    def editSettings_(self, _sender):
        # Do not parse here: the file must open even when it contains a mistake.
        path = settings_module.ensure_exists()
        subprocess.run(["/usr/bin/open", "-e", str(path)], check=False)

    # ---- processing ----
    @objc.python_method
    def enqueue(self, paths: list[str]):
        self.jobs.put(paths)

    @objc.python_method
    def _on_main_thread(self, func, *args):
        AppHelper.callAfter(func, *args)

    @objc.python_method
    def _set_status(self, text: str):
        self._on_main_thread(self.status.setStringValue_, text)

    @objc.python_method
    def _log(self, text: str, color=None):
        def write():
            storage = self.log_view.textStorage()
            storage.appendAttributedString_(_styled(text + "\n", 13, color, centered=False))
            self.log_view.scrollRangeToVisible_((storage.length(), 0))
        self._on_main_thread(write)

    @objc.python_method
    def _enable(self):
        def do():
            self.drop_zone.enabled = True
            self.drop_zone.setNeedsDisplay_(True)
            self.choose_button.setEnabled_(True)
        self._on_main_thread(do)

    @objc.python_method
    def _load_settings(self) -> settings_module.Settings:
        """Never fails: a mistake in the file is reported and processing continues without it."""
        try:
            return settings_module.load()
        except Exception as e:  # noqa: BLE001
            self._log(f"Let op: 'mijn gegevens' kon niet gelezen worden: {e}. Er wordt verder "
                      f"gewerkt zonder. Herstel het via het menu → Mijn gegevens bewerken…",
                      NSColor.systemOrangeColor())
            return settings_module.Settings()

    @objc.python_method
    def _worker(self):
        with objc.autorelease_pool():
            from .engine import Anonymizer, cache_is_fresh

            if cache_is_fresh():
                self._set_status("Even geduld…")
            else:  # first start, or the first start after an update
                self._set_status("Klaarzetten… dit duurt ongeveer een halve minuut")
            try:
                self.anonymizer = Anonymizer(self._load_settings())
            except Exception as e:  # noqa: BLE001
                self._set_status("Het programma kon niet starten.")
                self._log(f"Fout bij opstarten: {type(e).__name__}: {e}", NSColor.systemRedColor())
                return
            self._set_status("Klaar voor gebruik")
            self._enable()

        while True:
            paths = self.jobs.get()
            with objc.autorelease_pool():
                try:
                    self._process(paths)
                except Exception as e:  # noqa: BLE001 — the worker must survive any error
                    self._set_status("Er ging iets mis")
                    self._log(f"✗  Er ging iets mis: {type(e).__name__}: {e}", NSColor.systemRedColor())

    @objc.python_method
    def _process(self, paths: list[str]):
        files = collect_files([Path(p) for p in paths])
        if not files:
            self._set_status("Geen bruikbare bestanden gevonden")
            self._log("Sleep Word-bestanden, PDF's, scans of foto's hierheen.", NSColor.systemOrangeColor())
            return

        self.anonymizer.use_settings(self._load_settings())  # use edited settings right away

        done = []
        for i, f in enumerate(files, start=1):
            self._set_status(f"Bezig met {f.name} ({i} van {len(files)})…")
            r = process_file(f, DEFAULT_OUTPUT_DIR, self.anonymizer)
            if r.ok:
                done.append(r.target)
                self._log(f"✓  {f.name}  →  klaar ({len(r.replacements)} gegevens vervangen)",
                          NSColor.systemGreenColor())
            else:
                self._log(f"✗  {f.name}: {r.message}", NSColor.systemRedColor())
            for w in r.warnings:
                self._log(f"    !  {w}", NSColor.systemOrangeColor())

        if done:
            self._set_status("Klaar! De nieuwe bestanden staan in Finder geselecteerd.")
            urls = [NSURL.fileURLWithPath_(str(p)) for p in done]
            self._on_main_thread(NSWorkspace.sharedWorkspace().activateFileViewerSelectingURLs_, urls)
        else:
            self._set_status("Er is niets verwerkt")


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    AppHelper.runEventLoop()
