"""Personal settings: details that must always be removed.

The file is plain TOML so it can be edited without programming knowledge. It is
user-facing, so its keys and comments are in Dutch.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DIR = Path.home() / "Documents" / "Anonimiseren"
DEFAULT_FILE = DEFAULT_DIR / "mijn-gegevens.toml"

TEMPLATE = """\
# Mijn gegevens — deze worden ALTIJD uit documenten verwijderd.
# Vul in wat je weet, laat leeg wat je niet weet. Tekst altijd tussen "aanhalingstekens".

[patient]
voornamen = []            # bijvoorbeeld ["Johannes", "Petrus"]
roepnaam = ""             # bijvoorbeeld "Jan"
initialen = ""            # bijvoorbeeld "J.P."
achternaam = ""           # bijvoorbeeld "de Vries"

[extra]
# Namen van familie, mantelzorgers, vaste artsen, enz. (elke naam apart)
personen = []             # bijvoorbeeld ["Marie de Vries", "A. Bakker"]
# Adressen en woonplaats
adressen = []             # bijvoorbeeld ["Kerkstraat 14", "3512 AB"]
# Overige vaste gegevens: patiëntnummers, verzekeringsnummer, enz.
overig = []               # bijvoorbeeld ["4567890"]

[opties]
# Data (zoals 12-03-2024) vervangen door [DATUM-1]? Standaard blijven data staan, zodat de
# tijdlijn te volgen is. De geboortedatum wordt altijd verwijderd. Zet op true om ook alle
# andere data te vervangen.
data_vervangen = false
# Leeftijden (zoals "73 jaar") vervangen?
leeftijd_vervangen = true
"""


@dataclass
class Settings:
    first_names: list[str] = field(default_factory=list)
    nickname: str = ""
    initials: str = ""
    surname: str = ""
    people: list[str] = field(default_factory=list)
    addresses: list[str] = field(default_factory=list)
    other: list[str] = field(default_factory=list)
    replace_dates: bool = False  # keep dates for the timeline; date of birth is always removed
    replace_ages: bool = True


def _as_list(value) -> list[str]:
    if isinstance(value, str):
        value = [value]
    return [str(v).strip() for v in (value or []) if str(v).strip()]


class SettingsError(Exception):
    """The settings file exists but cannot be read. The message is Dutch (shown to the user)."""


def ensure_exists(path: Path | None = None) -> Path:
    """Create the settings file from the template if needed, without parsing it."""
    path = Path(path) if path else DEFAULT_FILE
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(TEMPLATE, encoding="utf-8")
    return path


def load(path: Path | None = None, create: bool = True) -> Settings:
    """Read the settings file; create it from the template if it does not exist yet.

    Raises SettingsError when the file contains a mistake (e.g. a missing quote).
    """
    path = Path(path) if path else DEFAULT_FILE
    if not path.exists():
        if create:
            ensure_exists(path)
        return Settings()

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        raise SettingsError(f"er staat een fout in {path.name} ({e})") from e
    patient, extra, options = data.get("patient", {}), data.get("extra", {}), data.get("opties", {})
    return Settings(
        first_names=_as_list(patient.get("voornamen")),
        nickname=str(patient.get("roepnaam", "")).strip(),
        initials=str(patient.get("initialen", "")).strip(),
        surname=str(patient.get("achternaam", "")).strip(),
        people=_as_list(extra.get("personen")),
        addresses=_as_list(extra.get("adressen")),
        other=_as_list(extra.get("overig")),
        replace_dates=bool(options.get("data_vervangen", False)),
        replace_ages=bool(options.get("leeftijd_vervangen", True)),
    )
