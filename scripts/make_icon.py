"""Draws the app icon (a document with black redaction bars) and turns it into an .icns."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw


def draw(size: int = 1024) -> Image.Image:
    s = size / 1024
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # Background: rounded tile with a gradient (macOS-style margin)
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gradient = Image.new("RGBA", (size, size))
    gd = ImageDraw.Draw(gradient)
    for y in range(size):
        t = y / size
        gd.line([(0, y), (size, y)], fill=(int(40 + 20 * t), int(130 - 40 * t), int(200 - 40 * t), 255))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([100 * s, 100 * s, 924 * s, 924 * s], radius=185 * s, fill=255)
    tile.paste(gradient, (0, 0), mask)
    img = Image.alpha_composite(img, tile)

    d = ImageDraw.Draw(img)
    # White document with folded corner
    x0, y0, x1, y1, corner = 300 * s, 210 * s, 724 * s, 814 * s, 120 * s
    d.polygon([(x0, y0), (x1 - corner, y0), (x1, y0 + corner), (x1, y1), (x0, y1)], fill=(255, 255, 255, 255))
    d.polygon([(x1 - corner, y0), (x1 - corner, y0 + corner), (x1, y0 + corner)], fill=(205, 220, 235, 255))

    # Text lines, some of them redacted
    lines = [(0.55, False), (0.85, True), (0.75, False), (0.6, False), (0.8, True), (0.7, False), (0.5, False)]
    y = 360 * s
    for length, redacted in lines:
        w = (x1 - x0 - 120 * s) * length
        if redacted:
            d.rounded_rectangle([x0 + 60 * s, y - 14 * s, x0 + 60 * s + w, y + 30 * s], radius=8 * s, fill=(25, 25, 30, 255))
        else:
            d.rounded_rectangle([x0 + 60 * s, y, x0 + 60 * s + w, y + 16 * s], radius=8 * s, fill=(175, 190, 205, 255))
        y += 62 * s
    return img


def main(out: Path) -> None:
    iconset = out.with_suffix(".iconset")
    shutil.rmtree(iconset, ignore_errors=True)
    iconset.mkdir(parents=True)
    large = draw(1024)
    for base in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            px = base * scale
            name = f"icon_{base}x{base}{'@2x' if scale == 2 else ''}.png"
            large.resize((px, px), Image.LANCZOS).save(iconset / name)
    subprocess.run(["/usr/bin/iconutil", "-c", "icns", str(iconset), "-o", str(out)], check=True)
    large.save(out.with_suffix(".png"))
    shutil.rmtree(iconset)
    print("Icon created:", out)


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "resources/Anonimiseren.icns"))
