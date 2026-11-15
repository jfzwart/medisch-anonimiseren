"""Process a single file or a whole folder.

Messages in `Result` are shown to the end user, so they are in Dutch.
"""

from __future__ import annotations

import os
import re
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import readers, word
from .engine import Anonymizer, Replacement, apply_replacements

DEFAULT_OUTPUT_DIR = Path.home() / "Documents" / "Anonimiseren" / "Geanonimiseerd"
_PAGE_BREAK = "\n\n\f\n\n"


@dataclass
class Result:
    source: Path
    target: Path | None = None
    ok: bool = False
    message: str = ""
    counts: Counter = field(default_factory=Counter)
    warnings: list[str] = field(default_factory=list)
    replacements: list[Replacement] = field(default_factory=list)


def _safe_name(stem: str, anonymizer: Anonymizer) -> str:
    """The file name may contain a name too ('Brief Jan de Vries')."""
    readable = re.sub(r"_+", " ", stem)
    clean = anonymizer.anonymize(readable)
    clean = re.sub(r'[\\/:*?"<>|]', "", clean).strip() or "document"
    return clean[:120]


def _free_path(directory: Path, name: str) -> Path:
    target = directory / f"{name} (geanonimiseerd).docx"
    n = 2
    while target.exists():
        target = directory / f"{name} (geanonimiseerd {n}).docx"
        n += 1
    return target


def process_file(path: Path, output_dir: Path, anonymizer: Anonymizer) -> Result:
    path = Path(path)
    result = Result(source=path)
    ext = path.suffix.lower()

    if ext not in readers.SUPPORTED:
        result.message = f"Dit soort bestand ({ext or 'zonder extensie'}) wordt niet ondersteund."
        return result

    output_dir.mkdir(parents=True, exist_ok=True)
    target = _free_path(output_dir, _safe_name(path.stem, anonymizer))

    try:
        if ext in readers.WORD or ext in readers.CONVERTIBLE:
            with tempfile.TemporaryDirectory() as tmp:
                source = path
                if ext in readers.CONVERTIBLE:
                    source = readers.convert_to_docx(path, Path(tmp) / "converted.docx")
                result.replacements, result.warnings = word.anonymize_docx(source, target, anonymizer)
        else:
            extracted = readers.read_pdf(path) if ext in readers.PDF else readers.read_image(path)
            if not "".join(extracted.pages).strip():
                result.message = "Er kon geen tekst uit dit bestand gehaald worden."
                return result
            full_text = _PAGE_BREAK.join(extracted.pages)
            result.replacements = anonymizer.replacements(full_text)
            clean = apply_replacements(full_text, result.replacements)
            pages = [p.strip("\n") for p in clean.split("\f")]

            kind = "PDF" if ext in readers.PDF else "foto/scan"
            note = f"Geanonimiseerde versie van een {kind}"
            if extracted.ocr_pages:
                note += " (tekst herkend uit een scan; kleine leesfouten zijn mogelijk)"
                result.warnings.append(
                    "Tekst is herkend uit een scan. Controleer of handgeschreven namen "
                    "of slecht leesbare stukken goed zijn verwijderd."
                )
            word.write_text_as_docx(pages, target, note + ".")
    except Exception as e:  # noqa: BLE001 — one broken file must not stop the rest
        if target.exists():
            target.unlink()
        result.message = f"Er ging iets mis: {type(e).__name__}: {e}"
        return result

    result.target, result.ok = target, True
    result.counts = Counter(r.label for r in result.replacements)
    result.message = f"{len(result.replacements)} gegevens vervangen."
    return result


def collect_files(paths: list[Path]) -> list[Path]:
    """Expand folders into the supported files they contain."""
    files = []
    for p in map(Path, paths):
        if p.is_dir():
            found = []
            # os.walk skips folders we may not read instead of raising (Path.rglob raises).
            for folder, _dirs, names in os.walk(p, onerror=lambda _e: None):
                found += [
                    Path(folder) / n for n in names
                    if Path(n).suffix.lower() in readers.SUPPORTED and not n.startswith(("~$", "."))
                ]
            files += sorted(found)
        elif p.is_file():
            files.append(p)
    return files
