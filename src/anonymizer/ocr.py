"""Text recognition (OCR) with Apple Vision, built into macOS. Fully offline."""

from __future__ import annotations

import io
from pathlib import Path

import Vision
from Foundation import NSURL, NSData

LANGUAGES = ["nl-NL", "en-US"]


def _make_request():
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setRecognitionLanguages_(LANGUAGES)
    request.setUsesLanguageCorrection_(True)
    return request


def _perform(handler) -> str:
    request = _make_request()
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise RuntimeError(f"Text recognition failed: {error}")
    return _reading_order(request.results() or [])


def _reading_order(observations) -> str:
    """Put recognized lines in reading order and start a paragraph at large gaps."""
    lines = []
    for obs in observations:
        candidates = obs.topCandidates_(1)
        if not candidates:
            continue
        box = obs.boundingBox()  # normalized, origin bottom-left
        center = box.origin.y + box.size.height / 2
        lines.append((center, box.origin.x, box.size.height, candidates[0].string()))
    if not lines:
        return ""

    lines.sort(key=lambda line: -line[0])  # top to bottom

    # Merge lines at roughly the same height (e.g. "Datum:  12-03-2024")
    rows: list[list] = []
    for line in lines:
        if rows and abs(rows[-1][0][0] - line[0]) < line[2] * 0.5:
            rows[-1].append(line)
        else:
            rows.append([line])

    out, prev_y, prev_h = [], None, None
    for row in rows:
        row.sort(key=lambda line: line[1])
        y, h = row[0][0], max(line[2] for line in row)
        if prev_y is not None and (prev_y - y) > 1.8 * max(h, prev_h):
            out.append("")  # blank line = new paragraph
        out.append("   ".join(line[3] for line in row))
        prev_y, prev_h = y, h
    return "\n".join(out)


def recognize_image(image) -> str:
    """OCR a PIL image."""
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="PNG")
    data = buf.getvalue()
    nsdata = NSData.dataWithBytes_length_(data, len(data))
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(nsdata, None)
    return _perform(handler)


def recognize_file(path: Path) -> str:
    """OCR an image file (jpg, png, heic, tiff)."""
    path = Path(path)
    if path.suffix.lower() in {".heic", ".heif"}:
        url = NSURL.fileURLWithPath_(str(path))
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)
        return _perform(handler)

    from PIL import Image, ImageOps

    with Image.open(path) as img:
        return recognize_image(ImageOps.exif_transpose(img))
