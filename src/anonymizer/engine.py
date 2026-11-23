"""Core anonymization: deduce + personal list + extra cleanup passes.

Returns replacements as (start, end, replacement) so they can be applied both to plain
text and to Word documents (preserving formatting).
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz.distance import DamerauLevenshtein

from .settings import Settings

CACHE_DIR = Path.home() / "Library" / "Caches" / "Anonimiseren"
_CACHE_FILE = Path("cache") / "lookup_structs.pickle"


def bundled_cache_dir() -> Path | None:
    """The deduce cache prebuilt into the app bundle by scripts/build_app.sh, if any."""
    resources = os.environ.get("RESOURCEPATH")  # set by py2app inside the .app
    if not resources:
        return None
    path = Path(resources) / "deduce-cache"
    return path if (path / _CACHE_FILE).exists() else None


def _seed_cache(cache_dir: Path) -> None:
    """Copy the prebuilt cache from the app bundle so the first start needs no ~30 s build.

    Copied rather than used in place: if deduce ever decides to rebuild, it must write to
    the user's cache folder, never into the signed app bundle.
    """
    bundled = bundled_cache_dir()
    if bundled is None or cache_is_fresh(cache_dir) or not cache_is_fresh(bundled):
        return
    target = cache_dir / _CACHE_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".partial")
    try:
        shutil.copy2(bundled / _CACHE_FILE, partial)  # copy2 keeps the mtime used by cache_is_fresh
        partial.replace(target)
    except OSError:
        partial.unlink(missing_ok=True)  # e.g. disk full: deduce then builds the cache itself

# Determines which label wins when findings overlap (deduce uses Dutch tags).
_LABEL_PRIORITY = {"patient": 0, "persoon": 1}

# Loose initials directly before/after a name, e.g. "J.P." or "J. P."
_INITIALS_BEFORE = re.compile(r"(?:\b[A-Z]\.\s?)+$")
_INITIALS_AFTER = re.compile(r"^(?:\s?[A-Z]\.)+")
_ENDS_WITH_INITIAL = re.compile(r"(?:^|[\s.])[A-Z]$")

# Dutch salutations, titles and surname prefixes: they say nothing about who someone is.
_TITLES = {
    "dhr", "mevr", "mevrouw", "mw", "heer", "meneer", "de", "dr", "drs", "prof", "ing", "mr",
    "collega", "huisarts", "van", "der", "den", "ter", "ten", "te", "het", "les", "des", "dit",
    "uit", "aan", "bij", "tot", "op", "in",
}
_MALE = {"dhr", "heer", "meneer"}
_FEMALE = {"mevr", "mevrouw", "mw"}

# The date of birth is always removed, even when dates are kept.
# Labels: "geboren", "geb.", "geboortedatum", "geb.datum", "geb. dat.", "geboortedat.", "DOB".
_DATE_OF_BIRTH = re.compile(
    r"(?:geb(?:oorte)?\.?\s*-?\s*dat(?:um|\.)?|geboren|geb\.?|d\.?o\.?b\.?)\s*:?\s*(?:op\s+)?"
    r"(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{1,2}[-\s]+[a-z]{3,}\.?[-\s]+\d{4})",
    re.IGNORECASE,
)

_MONTHS = [
    ("januari", "jan"), ("februari", "feb"), ("maart", "mrt"), ("april", "apr"), ("mei", "mei"),
    ("juni", "jun"), ("juli", "jul"), ("augustus", "aug"), ("september", "sep"),
    ("oktober", "okt"), ("november", "nov"), ("december", "dec"),
]


def _date_pattern(value: str) -> re.Pattern | None:
    """All common Dutch spellings of one date: 12-03-1951, 12/3/51, 12.03.1951, 12 maart 1951,
    12 mrt. 1951. None if `value` is not a day-month-year date."""
    m = re.fullmatch(r"\s*(\d{1,2})\s*[-/. ]\s*(\d{1,2}|[a-z]{3,}\.?)\s*[-/. ]\s*(\d{2}|\d{4})\s*",
                     value, re.IGNORECASE)
    if not m:
        return None
    day, month_text, year_text = m.groups()
    day = int(day)
    if month_text.isdigit():
        month = int(month_text)
    else:
        word = month_text.lower().rstrip(".")
        month = next((i for i, (full, short) in enumerate(_MONTHS, start=1)
                      if word == full or word.startswith(short)), 0)
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return None
    yy = year_text[-2:]
    y = rf"(?:{year_text}|{yy})" if len(year_text) == 4 else rf"(?:(?:19|20)?{yy})"
    d, mo = f"0?{day}", f"0?{month}"
    numeric = rf"{d}\s*[-/.]\s*{mo}\s*[-/.]\s*{y}"
    full, short = _MONTHS[month - 1]
    names = rf"{d}[-\s]+(?:{full}|{short}t?\.?)[-\s]+{y}"
    return re.compile(rf"(?<!\d)(?:{numeric}|{names})(?!\d)", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    start: int
    end: int
    label: str
    text: str
    own: bool = False  # exact match from the personal list -> wins on equal length


@dataclass(frozen=True)
class Replacement:
    start: int
    end: int
    original: str
    replacement: str
    label: str


def _name_pattern(term: str) -> re.Pattern:
    parts = [re.escape(p) for p in term.split()]
    return re.compile(r"(?<!\w)" + r"\s+".join(parts) + r"(?!\w)", re.IGNORECASE)


def _is_common_word_use(term: str, match: str) -> bool:
    """A capitalized name written all-lowercase is an ordinary word, not the name:
    'jan.' (month) for 'Jan', 'de bakker' for 'Bakker'. 'JAN' or 'Jan' still match."""
    return any(c.isupper() for c in term) and match == match.lower()


def cache_is_fresh(cache_dir: Path | None = None) -> bool:
    """True if deduce can load its lookup cache instead of rebuilding it (~30 s).

    Mirrors deduce's own check: the cache is rebuilt when any lookup source file is newer.
    Uses find_spec so deduce itself does not have to be imported (slow).
    """
    import importlib.util

    cache_file = (Path(cache_dir) if cache_dir else CACHE_DIR) / _CACHE_FILE
    spec = importlib.util.find_spec("deduce")
    if not cache_file.exists() or spec is None or spec.origin is None:
        return False
    src = Path(spec.origin).parent / "data" / "lookup" / "src"
    cache_mtime = cache_file.stat().st_mtime
    return all(f.stat().st_mtime <= cache_mtime for f in src.glob("**/*"))


class Anonymizer:
    def __init__(self, settings: Settings | None = None, cache_dir: Path | None = None):
        from deduce import Deduce  # slow to import; only load when needed

        # deduce sets logging to DEBUG on import; we never log document text.
        logging.getLogger().setLevel(logging.WARNING)

        cache = Path(cache_dir) if cache_dir else CACHE_DIR
        cache.mkdir(parents=True, exist_ok=True)
        _seed_cache(cache)
        self._deduce = Deduce(cache_path=cache)
        self.use_settings(settings or Settings())

    def use_settings(self, settings: Settings) -> None:
        """Switch to new personal settings without reloading deduce."""
        self.settings = settings
        self._own_patterns = self._build_own_patterns()
        self._birth_date_pattern = _date_pattern(settings.birth_date) if settings.birth_date else None
        s = self.settings
        self._patient_words = {
            w.lower() for name in [*s.first_names, s.nickname, s.surname] for w in name.split() if len(w) >= 3
        } - _TITLES

    # ---- personal list -------------------------------------------------------------

    def _build_own_patterns(self) -> list[tuple[str, re.Pattern, str]]:
        s = self.settings
        terms: list[tuple[str, str]] = []

        patient_names = set(s.first_names)
        if s.nickname:
            patient_names.add(s.nickname)
        if s.surname:
            patient_names.add(s.surname)
            for first in [*s.first_names, s.nickname]:
                if first:
                    patient_names.add(f"{first} {s.surname}")
            if s.initials:
                patient_names.add(f"{s.initials} {s.surname}")
        terms += [(t, "patient") for t in patient_names]

        for name in s.people:
            terms.append((name, "persoon"))
            parts = name.split()
            if len(parts) >= 2:  # "Marie de Vries" -> also "de Vries"
                terms.append((" ".join(parts[1:]), "persoon"))
        terms += [(a, "locatie") for a in s.addresses]
        terms += [(o, "id") for o in s.other]

        # Longest first so "Jan de Vries" wins over "Jan"
        terms.sort(key=lambda t: len(t[0]), reverse=True)
        return [(t, _name_pattern(t), label) for t, label in terms if len(t) >= 2]

    def _patient_metadata(self):
        from deduce.person import Person

        s = self.settings
        if not (s.first_names or s.nickname or s.surname or s.initials):
            return None
        first_names = list(s.first_names)
        if s.nickname and s.nickname not in first_names:
            first_names.append(s.nickname)
        return {
            "patient": Person(
                first_names=first_names or None,
                initials=s.initials or None,
                surname=s.surname or None,
            )
        }

    # ---- finding -------------------------------------------------------------------

    def find(self, text: str) -> list[Finding]:
        disabled = set()
        if not self.settings.replace_dates:
            disabled.add("dates")
        if not self.settings.replace_ages:
            disabled.add("ages")

        doc = self._deduce.deidentify(text, disabled=disabled or None, metadata=self._patient_metadata())
        findings = [Finding(a.start_char, a.end_char, a.tag, a.text) for a in doc.annotations]

        for term, pattern, label in self._own_patterns:
            for m in pattern.finditer(text):
                if not _is_common_word_use(term, m.group()):
                    findings.append(Finding(m.start(), m.end(), label, m.group(), own=True))

        # The date of birth is always removed, also where it appears without a label.
        birth_patterns = [p for p in (_date_pattern(m.group(1)) for m in _DATE_OF_BIRTH.finditer(text)) if p]
        for m in _DATE_OF_BIRTH.finditer(text):
            findings.append(Finding(m.start(1), m.end(1), "datum", m.group(1)))
        if self._birth_date_pattern:
            birth_patterns.append(self._birth_date_pattern)
        for pattern in birth_patterns:
            for m in pattern.finditer(text):
                findings.append(Finding(m.start(), m.end(), "datum", m.group(), own=True))

        findings = [self._fix_patient_label(f) for f in findings]
        findings = self._extend_initials(text, findings)
        return self._merge(text, findings)

    def _fix_patient_label(self, f: Finding) -> Finding:
        """deduce labels 'dr. P. Jansen' as the patient if 'P' is one of the patient's
        initials. If the finding contains a name that is not the patient's, it is someone else."""
        if f.own or "patient" not in f.label or not self._patient_words:
            return f
        words = {w.lower() for w in re.findall(r"[^\W\d_]{3,}", f.text)} - _TITLES
        if words and not (words & self._patient_words):
            return Finding(f.start, f.end, "persoon", f.text)
        return f

    @staticmethod
    def _is_name(label: str) -> bool:
        return "patient" in label or "persoon" in label

    def _extend_initials(self, text: str, findings: list[Finding]) -> list[Finding]:
        """Include loose initials next to a name ('J.P. de Vries' -> as a whole)."""
        result = []
        for f in findings:
            start, end = f.start, f.end
            if self._is_name(f.label):
                m = _INITIALS_BEFORE.search(text[max(0, start - 20):start])
                if m:
                    start -= len(m.group())
                # 'J' found but not '.P.': include the dot and following initials
                if _ENDS_WITH_INITIAL.search(text[start:end]) and text[end:end + 1] == ".":
                    end += 1
                m = _INITIALS_AFTER.match(text[end:end + 20])
                if m:
                    end += len(m.group())
            result.append(Finding(start, end, f.label, text[start:end], f.own))
        return result

    @staticmethod
    def _label_rank(label: str) -> int:
        for key, rank in _LABEL_PRIORITY.items():
            if key in label:
                return rank
        return 9

    def _strongest(self, a: Finding, b: Finding) -> Finding:
        """Longest finding decides the label; then the personal list; then patient > person > rest."""
        return min((a, b), key=lambda f: (-(f.end - f.start), not f.own, self._label_rank(f.label)))

    def _merge(self, text: str, findings: list[Finding]) -> list[Finding]:
        """Overlapping or adjacent findings become a single finding."""
        findings = sorted(findings, key=lambda f: (f.start, -f.end))
        groups: list[list[Finding]] = []
        for f in findings:
            if groups and f.start <= max(g.end for g in groups[-1]):
                groups[-1].append(f)
            else:
                groups.append([f])
        merged = []
        for group in groups:
            start, end = group[0].start, max(g.end for g in group)
            best = group[0]
            for g in group[1:]:
                best = self._strongest(best, g)
            merged.append(Finding(start, end, best.label, text[start:end], best.own))
        return merged

    # ---- replacing -----------------------------------------------------------------

    @staticmethod
    def _normalize_label(label: str) -> str:
        if "patient" in label:
            return "PATIENT"
        if "persoon" in label:
            return "PERSOON"
        return label.upper()

    @staticmethod
    def _name_parts(text: str) -> tuple[list[str], str]:
        words = [w.lower() for w in re.findall(r"[^\W\d_]{2,}", text)]
        names = [w for w in words if w not in _TITLES]
        gender = "m" if set(words) & _MALE else "f" if set(words) & _FEMALE else ""
        return names, gender

    def _same_entity(self, label: str, a: str, b: str) -> bool:
        norm_a, norm_b = " ".join(a.lower().split()), " ".join(b.lower().split())
        if norm_a == norm_b:
            return True
        # Values with digits (dates, ages, numbers) must match exactly: 1-3-2024 and
        # 1-4-2024 are different dates. Words may differ by one typo (OCR, spelling).
        if any(c.isdigit() for c in norm_a + norm_b):
            return False
        if DamerauLevenshtein.distance(norm_a, norm_b, score_cutoff=1) <= 1:
            return True
        if label != "PERSOON":
            return False
        # 'dhr. drs. P. Jansen' and 'collega Jansen' -> same person,
        # but 'Jan de Vries' and 'Marie de Vries' are not (both have a first name).
        (names_a, gender_a), (names_b, gender_b) = self._name_parts(a), self._name_parts(b)
        if not names_a or not names_b or names_a[-1] != names_b[-1]:
            return False
        if gender_a and gender_b and gender_a != gender_b:
            return False
        # Only a short mention (b, without first name) refers back to an earlier name.
        return len(names_b) == 1

    def replacements(self, text: str) -> list[Replacement]:
        """Numbered like deduce: equal (or nearly equal) text gets the same number."""
        per_label: dict[str, list[tuple[str, str]]] = {}
        result = []
        for f in sorted(self.find(text), key=lambda f: f.start):
            label = self._normalize_label(f.label)
            if label == "PATIENT":
                replacement = "[PATIENT]"
            else:
                group = per_label.setdefault(label, [])
                replacement = next((r for t, r in group if self._same_entity(label, t, f.text)), None)
                if replacement is None:
                    replacement = f"[{label}-{len({r for _, r in group}) + 1}]"
                group.append((f.text, replacement))
            result.append(Replacement(f.start, f.end, f.text, replacement, label))
        return result

    def anonymize(self, text: str) -> str:
        return apply_replacements(text, self.replacements(text))


def apply_replacements(text: str, replacements: list[Replacement]) -> str:
    parts, pos = [], 0
    for r in sorted(replacements, key=lambda r: r.start):
        parts += [text[pos:r.start], r.replacement]
        pos = r.end
    parts.append(text[pos:])
    return "".join(parts)
