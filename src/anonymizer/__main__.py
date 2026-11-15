"""Command line (for development and testing): python -m anonymizer <files/folders>"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import settings
from .engine import Anonymizer
from .pipeline import DEFAULT_OUTPUT_DIR, collect_files, process_file


def main() -> int:
    ap = argparse.ArgumentParser(prog="anonymizer", description="Anonymize Dutch medical documents (offline).")
    ap.add_argument("paths", nargs="+", type=Path, help="files or folders")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_DIR, help="output folder")
    ap.add_argument("--settings", type=Path, default=None, help="path to mijn-gegevens.toml")
    ap.add_argument("--cache", type=Path, default=None, help="folder for the deduce cache")
    ap.add_argument("--show", action="store_true",
                    help="show what was replaced (WARNING: prints the confidential data)")
    args = ap.parse_args()

    files = collect_files(args.paths)
    if not files:
        print("No supported files found.")
        return 1

    anonymizer = Anonymizer(settings.load(args.settings), cache_dir=args.cache)
    failures = 0
    for f in files:
        r = process_file(f, args.out, anonymizer)
        print(f"{'✓' if r.ok else '✗'} {f.name}: {r.message}")
        if r.ok:
            print(f"   → {r.target}")
            print("   " + ", ".join(f"{k.lower()}: {v}" for k, v in sorted(r.counts.items())))
        for w in r.warnings:
            print(f"   ! {w}")
        if args.show:
            for rep in r.replacements:
                print(f"     {rep.replacement:<22} ← {rep.original!r}")
        failures += not r.ok
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
