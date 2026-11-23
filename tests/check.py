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
    "Heidelberglaan", "3584", "Dorpsstraat", "3701", "De Linde",
    "marie.devries@ziggo.nl", "mijnpatient.nl", "MdV",
]
# Dates in the letters (not the date of birth): replaced only with `data_vervangen = true`.
LETTER_DATES = ["28-10-2024", "4 november 2024"]
# Medical content that MUST remain.
MUST_REMAIN = ["Parkinson", "metoprolol", "LVEF", "45%"]


def check_docx(path: Path, must_remain: list[str] = MUST_REMAIN, dates_kept: bool = False) -> list[str]:
    """Search every part of the .docx (all XML and relationships, not just visible text)."""
    problems = []
    with zipfile.ZipFile(path) as z:
        parts = {n: z.read(n).decode("utf-8", "ignore") for n in z.namelist()}
    for s in SENSITIVE + ([] if dates_kept else LETTER_DATES):
        for name, content in parts.items():
            if s in content:
                problems.append(f"found: {s!r} in {name}")
    body = parts.get("word/document.xml", "")
    for m in must_remain:
        if m not in body:
            problems.append(f"medical content lost: {m!r}")

    if path.name.startswith("verborgen gegevens"):
        if "in jan." not in body:
            problems.append("ordinary word 'jan.' (month) was replaced")
        if dates_kept:
            if "Echo op 1-3-2024, controle op 1-4-2024" not in body:
                problems.append("dates were replaced although data_vervangen is off")
        else:
            dates = re.findall(r"Echo op (\[DATUM-\d+\]), controle op (\[DATUM-\d+\])", body)
            if not dates or dates[0][0] == dates[0][1]:
                problems.append(f"different dates got the same placeholder: {dates}")
    elif dates_kept and not any(d in body for d in LETTER_DATES):
        problems.append(f"letter dates were replaced although data_vervangen is off")
    return problems


def unit_checks() -> list[str]:
    problems = []
    a = Anonymizer(settings.load(ROOT / "tests" / "sample-settings.toml"))

    out = a.anonymize("Echo op 1-3-2024, controle op 1-4-2024.")
    if len(set(re.findall(r"\[DATUM-\d+\]", out))) != 2:
        problems.append(f"near-identical dates share a placeholder: {out}")
    out = Anonymizer(settings.Settings()).anonymize(
        "Dhr. Pietersen, geboren 12-03-1951. Echo op 28-10-2024, controle 4 november 2024."
    )
    if "12-03-1951" in out or "28-10-2024" not in out or "4 november 2024" not in out:
        problems.append(f"default must keep dates but remove the date of birth: {out}")
    default = Anonymizer(settings.Settings())
    for text in ["Geb.datum: 12-03-1951", "Geb. dat.: 12-03-1951", "DOB: 12-03-1951",
                 "geb. 12 mrt. 1951, controle op 12-3-1951"]:
        out = default.anonymize(text)
        if "1951" in out:
            problems.append(f"date of birth left behind: {out}")
    keep_dates = settings.load(ROOT / "tests" / "sample-settings.toml")
    keep_dates.replace_dates = False
    out = Anonymizer(keep_dates).anonymize("Pat. J. de Vries (12-03-1951), echo 28-10-2024. Zie 12 maart 1951.")
    if "1951" in out or "28-10-2024" not in out:
        problems.append(f"geboortedatum from the settings not removed in every spelling: {out}")
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


class _NeuralEngineFails:
    """Wraps a Vision handler; fails like the e5rt error unless the request runs on the CPU."""

    def __init__(self, handler):
        self.handler, self.calls = handler, 0

    def performRequests_error_(self, requests, error):
        import Vision

        self.calls += 1
        device = requests[0].computeDeviceForComputeStage_(Vision.VNComputeStageMain)
        if device is None or "CPU" not in type(device).__name__:
            return False, "e5rt_execution_stream_operation_create_precompiled_compute_operation_with_options call failed"
        return self.handler.performRequests_error_(requests, error)


def ocr_failure_checks(samples: Path, output: Path) -> list[str]:
    """OCR that fails on the Neural Engine must retry on the CPU; a PDF page with a text layer
    must fall back to it when OCR fails completely."""
    import Vision
    from Foundation import NSURL

    from anonymizer import ocr

    problems = []
    scan = next(samples.glob("*.jpg"))
    wrappers = []

    def make_handler():
        url = NSURL.fileURLWithPath_(str(scan))
        wrappers.append(_NeuralEngineFails(Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)))
        return wrappers[-1]

    ocr._first_attempt = 0
    try:
        text = ocr._perform(make_handler)
        if "metoprolol" not in text:
            problems.append(f"CPU retry recognized no usable text: {text[:80]!r}")
        first_calls = len(wrappers)
        ocr._perform(make_handler)
        if len(wrappers) - first_calls != 1:
            problems.append("OCR tried the failing Neural Engine again instead of remembering the CPU")
    except RuntimeError as e:
        problems.append(f"no CPU retry after a Neural Engine failure: {e}")
    finally:
        ocr._first_attempt = 0

    class _OnlyFastWorks(_NeuralEngineFails):
        def performRequests_error_(self, requests, error):
            if requests[0].recognitionLevel() != Vision.VNRequestTextRecognitionLevelFast:
                return False, "simulated failure on one odd image"
            return self.handler.performRequests_error_(requests, error)

    try:
        ocr._perform(lambda: _OnlyFastWorks(make_handler().handler))
        if ocr._first_attempt != 1:
            problems.append("one image that only worked in fast mode downgraded OCR for later pages")
    except RuntimeError as e:
        problems.append(f"fast-mode fallback did not work: {e}")
    finally:
        ocr._first_attempt = 0

    def broken(_image):
        raise RuntimeError("Text recognition failed: simulated")

    anonymizer = Anonymizer(settings.load(ROOT / "tests" / "sample-settings.toml"))
    original, ocr.recognize_image = ocr.recognize_image, broken
    try:
        r = process_file(samples / "portaal met scan.pdf", output / "ocr-broken", anonymizer)
        if not r.ok:
            problems.append(f"mixed PDF failed instead of using its text layer: {r.message}")
        else:
            if not any("Tekstherkenning lukte niet" in w for w in r.warnings):
                problems.append("no warning when the text layer was used instead of OCR")
            problems += check_docx(r.target, must_remain=[])
        r = process_file(samples / "gescande brief.pdf", output / "ocr-broken", anonymizer)
        if r.ok:
            problems.append("scanned PDF without text layer reported success while OCR failed")
    finally:
        ocr.recognize_image = original
    return problems


def speed_checks(samples: Path, output: Path) -> list[str]:
    """Progress is reported per page, and a prebuilt cache in the app bundle is used."""
    import os

    from anonymizer import engine

    problems = []
    anonymizer = Anonymizer(settings.load(ROOT / "tests" / "sample-settings.toml"))
    messages: list[str] = []
    r = process_file(samples / "gescande brief.pdf", output / "progress", anonymizer, progress=messages.append)
    if not r.ok or "pagina 1 van 1 wordt gelezen…" not in messages:
        problems.append(f"no page progress reported: {messages}")

    if not engine.cache_is_fresh():
        return problems + ["no fresh deduce cache to test the bundled-cache copy with"]
    with tempfile.TemporaryDirectory() as tmp:
        bundled = Path(tmp) / "Resources" / "deduce-cache" / "cache"
        bundled.mkdir(parents=True)
        shutil.copy2(engine.CACHE_DIR / "cache" / "lookup_structs.pickle", bundled)
        old = os.environ.get("RESOURCEPATH")
        os.environ["RESOURCEPATH"] = str(Path(tmp) / "Resources")
        try:
            user_cache = Path(tmp) / "user-cache"
            engine._seed_cache(user_cache)
            if not engine.cache_is_fresh(user_cache):
                problems.append("prebuilt cache from the app bundle was not copied to the user cache")

            def disk_full(*_args, **_kwargs):
                raise OSError(28, "No space left on device")

            broken_cache = Path(tmp) / "broken-cache"
            original, engine.shutil.copy2 = engine.shutil.copy2, disk_full
            try:
                engine._seed_cache(broken_cache)
            except OSError:
                problems.append("a failed cache copy stops the app from starting")
            finally:
                engine.shutil.copy2 = original
            if list(broken_cache.rglob("*.partial")):
                problems.append("a failed cache copy left a .partial file behind")
        finally:
            if old is None:
                os.environ.pop("RESOURCEPATH")
            else:
                os.environ["RESOURCEPATH"] = old
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

    print("\n== OCR failure handling")
    ocr_problems = ocr_failure_checks(samples, output)
    for p in ocr_problems:
        print("  FAIL  " + p)
    failures += len(ocr_problems)
    if not ocr_problems:
        print("  OK")

    print("\n== progress and prebuilt cache")
    speed_problems = speed_checks(samples, output)
    for p in speed_problems:
        print("  FAIL  " + p)
    failures += len(speed_problems)
    if not speed_problems:
        print("  OK")

    for name, config in [("with-settings", ROOT / "tests" / "sample-settings.toml"), ("without-settings", None)]:
        s = settings.load(config) if config else settings.Settings()
        anonymizer = Anonymizer(s)
        print(f"\n== {name}")
        for f in collect_files([samples]):
            r = process_file(f, output / name, anonymizer)
            problems = [r.message] if not r.ok else check_docx(r.target, dates_kept=not s.replace_dates)
            print(("  OK    " if not problems else "  FAIL  ") + f.name)
            for p in problems:
                print("        - " + p)
            failures += bool(problems)

    print(f"\n{'All good.' if not failures else f'{failures} problem(s).'}  Output: {output}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
