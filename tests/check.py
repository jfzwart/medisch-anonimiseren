"""End-to-end check: create samples, process them, search the output for leftover data.

Run:  .venv/bin/python -I tests/check.py
The results are written to tests/output/ for manual inspection.
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import make_samples  # noqa: E402

from anonymizer import settings  # noqa: E402
from anonymizer.engine import Anonymizer  # noqa: E402
from anonymizer.pipeline import collect_files, process_file  # noqa: E402

# Everything in the sample letters that must NOT appear anywhere in the output.
SENSITIVE = [
    "Vries", "Jan ", "J.P.", "Marie", "Bakker", "A.M.", "Jansen", "123456782", "4567890",
    "12-03-1951", "Kerkstraat", "3512", "06-12345678", "030-2501234", "umcutrecht.nl",
    "Heidelberglaan", "3584", "Dorpsstraat", "3701", "De Linde", "28-10-2024", "4 november 2024",
    "marie.devries@ziggo.nl", "mijnpatient.nl", "MdV",
]
# Medical content that MUST remain.
MUST_REMAIN = ["Parkinson", "metoprolol", "LVEF", "45%"]


def check_docx(path: Path) -> list[str]:
    """Search every part of the .docx (all XML and relationships, not just visible text)."""
    problems = []
    with zipfile.ZipFile(path) as z:
        parts = {n: z.read(n).decode("utf-8", "ignore") for n in z.namelist()}
    for s in SENSITIVE:
        for name, content in parts.items():
            if s in content:
                problems.append(f"found: {s!r} in {name}")
    body = parts.get("word/document.xml", "")
    for m in MUST_REMAIN:
        if m not in body:
            problems.append(f"medical content lost: {m!r}")

    if path.name.startswith("verborgen gegevens"):
        if "in jan." not in body:
            problems.append("ordinary word 'jan.' (month) was replaced")
        dates = re.findall(r"Echo op (\[DATUM-\d+\]), controle op (\[DATUM-\d+\])", body)
        if not dates or dates[0][0] == dates[0][1]:
            problems.append(f"different dates got the same placeholder: {dates}")
    return problems


def unit_checks() -> list[str]:
    problems = []
    a = Anonymizer(settings.load(ROOT / "tests" / "sample-settings.toml"))

    out = a.anonymize("Echo op 1-3-2024, controle op 1-4-2024.")
    if len(set(re.findall(r"\[DATUM-\d+\]", out))) != 2:
        problems.append(f"near-identical dates share a placeholder: {out}")
    out = a.anonymize("Volgende afspraak in jan. bij de poli. Groet aan JAN DE VRIES.")
    if "in jan." not in out or "VRIES" in out:
        problems.append(f"case handling of personal names wrong: {out}")

    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "mijn-gegevens.toml"
        bad.write_text('[patient]\nroepnaam = Jan\n', encoding="utf-8")  # missing quotes
        try:
            settings.load(bad)
            problems.append("invalid settings file did not raise SettingsError")
        except settings.SettingsError:
            pass
        if settings.ensure_exists(bad) != bad:
            problems.append("ensure_exists must not touch an existing file")

        locked = Path(tmp) / "map" / "geen toegang"
        locked.mkdir(parents=True)
        (Path(tmp) / "map" / "brief.pdf").write_bytes(b"")
        locked.chmod(0)
        try:
            found = collect_files([Path(tmp) / "map"])
            if [f.name for f in found] != ["brief.pdf"]:
                problems.append(f"collect_files returned {found}")
        except PermissionError as e:
            problems.append(f"collect_files crashed on an unreadable folder: {e}")
        finally:
            locked.chmod(0o755)
    return problems


def main() -> int:
    samples, output = ROOT / "tests" / "samples", ROOT / "tests" / "output"
    shutil.rmtree(output, ignore_errors=True)
    make_samples.main(samples)

    failures = 0
    print("\n== unit checks")
    for p in unit_checks():
        print("  FAIL  " + p)
        failures += 1
    if not failures:
        print("  OK")

    for name, config in [("with-settings", ROOT / "tests" / "sample-settings.toml"), ("without-settings", None)]:
        s = settings.load(config) if config else settings.Settings()
        anonymizer = Anonymizer(s)
        print(f"\n== {name}")
        for f in collect_files([samples]):
            r = process_file(f, output / name, anonymizer)
            problems = [r.message] if not r.ok else check_docx(r.target)
            print(("  OK    " if not problems else "  FAIL  ") + f.name)
            for p in problems:
                print("        - " + p)
            failures += bool(problems)

    print(f"\n{'All good.' if not failures else f'{failures} problem(s).'}  Output: {output}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
