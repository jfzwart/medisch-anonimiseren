"""Extract text from PDFs and images; convert legacy Word formats to .docx."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

WORD = {".docx"}
CONVERTIBLE = {".doc", ".rtf", ".odt"}  # converted to .docx with macOS textutil
PDF = {".pdf"}
IMAGE = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff"}
SUPPORTED = WORD | CONVERTIBLE | PDF | IMAGE

# A page with less text than this is probably a scan.
_MIN_CHARS_PER_PAGE = 40
# A page where images cover at least this share is (partly) a scan, even if it also has a
# digital text layer, e.g. a printed letterhead stamped over a scanned letter.
_MIN_IMAGE_COVERAGE = 0.3
_OCR_DPI = 300


def _image_coverage(page) -> float:
    """Share of the page area covered by image objects (overlaps counted double, capped at 1)."""
    import pypdfium2.raw as pdfium_c

    width, height = page.get_size()
    if width <= 0 or height <= 0:
        return 0.0
    covered = 0.0
    for obj in page.get_objects(filter=(pdfium_c.FPDF_PAGEOBJ_IMAGE,)):
        left, bottom, right, top = obj.get_bounds()
        covered += max(0.0, min(right, width) - max(left, 0)) * max(0.0, min(top, height) - max(bottom, 0))
    return min(1.0, covered / (width * height))


@dataclass
class ExtractedText:
    pages: list[str]
    ocr_pages: list[int] = field(default_factory=list)  # 1-based
    # Pages where OCR failed and the digital text layer was used instead (1-based).
    text_layer_fallback: list[int] = field(default_factory=list)


def read_pdf(path: Path, progress: Callable[[str], None] | None = None) -> ExtractedText:
    import pypdfium2 as pdfium

    from . import ocr

    progress = progress or (lambda _text: None)
    pdf = pdfium.PdfDocument(str(path))
    total = len(pdf)
    pages, ocr_pages, fallback = [], [], []
    try:
        for number, page in enumerate(pdf, start=1):
            progress(f"pagina {number} van {total} wordt gelezen…")
            textpage = page.get_textpage()
            text = textpage.get_text_bounded().replace("\r\n", "\n").replace("\r", "\n")
            textpage.close()
            if len(text.strip()) < _MIN_CHARS_PER_PAGE or _image_coverage(page) >= _MIN_IMAGE_COVERAGE:
                # OCR the rendered page: that includes both the digital text and the scan.
                image = page.render(scale=_OCR_DPI / 72).to_pil()
                try:
                    text = ocr.recognize_image(image)
                    ocr_pages.append(number)
                except RuntimeError:
                    if len(text.strip()) < _MIN_CHARS_PER_PAGE:
                        raise  # nothing to fall back on
                    fallback.append(number)
            pages.append(text)
            page.close()
    finally:
        pdf.close()
    return ExtractedText(pages, ocr_pages, fallback)


def read_image(path: Path, progress: Callable[[str], None] | None = None) -> ExtractedText:
    from . import ocr

    if progress:
        progress("tekst wordt herkend…")
    return ExtractedText([ocr.recognize_file(path)], [1])


def convert_to_docx(path: Path, target: Path) -> Path:
    """Uses the built-in macOS tool textutil (no network, nothing extra installed)."""
    subprocess.run(
        ["/usr/bin/textutil", "-convert", "docx", "-output", str(target), str(path)],
        check=True, capture_output=True, timeout=120,
    )
    return target
