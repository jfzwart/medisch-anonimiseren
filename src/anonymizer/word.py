"""Anonymize Word documents while preserving formatting, and write text to Word.

A .docx is a zip of XML parts. Text can hide in many of them, so we:
  1. collect text from *every* XML part into one string (visible paragraphs, field codes,
     text-bearing attributes, SmartArt, charts, ...) so one analysis gives consistent numbering;
  2. write the replacements back into the exact elements/attributes they came from;
  3. clean metadata (authors, people.xml, alt text, hyperlink targets, properties);
  4. run a safety net: every original value found is searched again in all text, attribute
     values and external link targets of the whole package, and replaced there too.
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.shared import Pt
from lxml import etree

from .engine import Anonymizer, Replacement

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
VML = "urn:schemas-microsoft-com:vml"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

# Parts whose paragraphs are the visible document text.
_MAIN_PARTS = re.compile(r"^/word/(document|header\d*|footer\d*|footnotes|endnotes|comments)\.xml$")
# Parts without user text (formatting only), and properties handled separately.
_SKIP_PARTS = re.compile(
    r"^/(docProps/.*|word/(styles|stylesWithEffects|fontTable|numbering|webSettings|theme/[^/]*))\.xml$"
)
# Attributes that can hold text typed by a person: (element) -> attribute.
_TEXT_ATTRIBUTES = {
    f"{{{W}}}fldSimple": f"{{{W}}}instr",      # simple field, e.g. HYPERLINK "mailto:..."
    f"{{{W}}}docVar": f"{{{W}}}val",           # document variables (settings.xml)
    f"{{{W}}}alias": f"{{{W}}}val",            # content control title
    f"{{{W}}}tag": f"{{{W}}}val",              # content control tag
    f"{{{W}}}default": f"{{{W}}}val",          # form field default text
    f"{{{W}}}helpText": f"{{{W}}}val",         # form field help text
    f"{{{W}}}statusText": f"{{{W}}}val",       # form field status bar text
    f"{{{VML}}}textpath": "string",            # legacy WordArt
}
_MIN_SAFETY_NET_LENGTH = 3


class _Segment:
    """A piece of text in the package that may be rewritten.

    el=None marks read-only filler (tab, line break). attr=None means the element's text.
    """

    __slots__ = ("el", "attr", "text", "start")

    def __init__(self, el, text: str, start: int, attr: str | None = None):
        self.el, self.attr, self.text, self.start = el, attr, text, start

    @property
    def end(self) -> int:
        return self.start + len(self.text)

    def write(self) -> None:
        if self.el is None:
            return
        if self.attr:
            if self.el.get(self.attr) != self.text:
                self.el.set(self.attr, self.text)
        elif self.el.text != self.text:
            self.el.text = self.text
            if self.el.tag == f"{{{W}}}t":
                self.el.set(XML_SPACE, "preserve")


class _Collector:
    def __init__(self):
        self.segments: list[_Segment] = []
        self.chunks: list[str] = []
        self.pos = 0

    def add(self, el, text: str, attr: str | None = None) -> None:
        seg = _Segment(el, text, self.pos, attr)
        self.segments.append(seg)
        self.chunks.append(text)
        self.pos += len(text)

    def separator(self) -> None:
        self.chunks.append("\n")
        self.pos += 1

    @property
    def text(self) -> str:
        return "".join(self.chunks)


def _roots(doc):
    """All XML parts that may contain user text, as (part, root, kind)."""
    for part in doc.part.package.iter_parts():
        name = str(part.partname)
        if not name.endswith(".xml") or _SKIP_PARTS.match(name):
            continue
        kind = "main" if _MAIN_PARTS.match(name) else "other"
        if hasattr(part, "_element"):
            yield part, part._element, kind, False
        else:  # not parsed by python-docx: parse ourselves and write back later
            try:
                yield part, etree.fromstring(part.blob), kind, True
            except etree.XMLSyntaxError:
                continue


def _own_paragraph(el, p) -> bool:
    parent = el.getparent()
    while parent is not None and parent.tag != f"{{{W}}}p":
        parent = parent.getparent()
    return parent is p


def _collect(roots) -> tuple[str, list[_Segment]]:
    c = _Collector()
    P, T, TAB, BR, CR, DEL, INSTR = (
        f"{{{W}}}{n}" for n in ("p", "t", "tab", "br", "cr", "delText", "instrText"))

    for _part, root, kind, _ in roots:
        if kind == "main":
            for p in root.iter(P):
                instructions = []
                for el in p.iter(T, TAB, BR, CR, DEL, INSTR):
                    if not _own_paragraph(el, p):  # belongs to a nested paragraph (text box)
                        continue
                    if el.tag == DEL:
                        el.text = ""  # deleted text (track changes) is dropped
                    elif el.tag == INSTR:
                        instructions.append(el)
                    elif el.tag == T:
                        c.add(el, el.text or "")
                    else:
                        c.add(None, "\t" if el.tag == TAB else "\n")
                c.separator()
                # Field codes (e.g. HYPERLINK "mailto:...") are invisible but stored as text;
                # analysed as their own line, since one instruction may span several runs.
                if instructions:
                    for el in instructions:
                        c.add(el, el.text or "")
                    c.separator()
        else:
            # SmartArt, charts, custom XML, ...: every text node is a separate line.
            for el in root.iter():
                if isinstance(el.tag, str) and el.text and el.text.strip() and len(el) == 0:
                    c.add(el, el.text)
                    c.separator()

        for el in root.iter(*_TEXT_ATTRIBUTES):
            attr = _TEXT_ATTRIBUTES[el.tag]
            value = el.get(attr)
            if value and value.strip():
                c.add(el, value, attr)
                c.separator()
        c.separator()
    return c.text, c.segments


def _apply(segments: list[_Segment], replacements: list[Replacement]) -> None:
    # Work from the end so earlier positions stay valid.
    for r in sorted(replacements, key=lambda r: r.start, reverse=True):
        placed = False
        for s in segments:
            if s.el is None or not (s.start < r.end and s.end > r.start):
                continue
            a = max(r.start, s.start) - s.start
            b = min(r.end, s.end) - s.start
            s.text = s.text[:a] + (r.replacement if not placed else "") + s.text[b:]
            placed = True
    for s in segments:
        s.write()


def _clean_metadata(doc, roots) -> list[str]:
    warnings = []

    props = doc.core_properties
    for name in ("author", "last_modified_by", "title", "subject", "keywords", "comments",
                 "category", "identifier", "content_status"):
        setattr(props, name, "")

    images = 0
    for part, root, _kind, _ in roots:
        for el in list(root.iter()):
            if not isinstance(el.tag, str):
                continue
            local = etree.QName(el).localname
            # people.xml: identity of comment authors (name, e-mail, account id)
            if local == "presenceInfo":
                el.getparent().remove(el)
                continue
            for attr in list(el.attrib):
                attr_local = etree.QName(attr).localname
                if attr_local == "author":  # comments, tracked changes, people.xml
                    el.set(attr, "Anoniem")
                elif attr_local == "initials" and etree.QName(attr).namespace == W:
                    el.set(attr, "")
            # image alt text
            if el.tag == f"{{{WP}}}docPr":
                images += 1
                for attr in ("descr", "title"):
                    if attr in el.attrib:
                        el.set(attr, "")
        # hyperlinks: the text is replaced already, but not the target (mailto:...)
        for link in list(root.iter(f"{{{W}}}hyperlink")):
            rid = link.get(f"{{{R}}}id")
            parent = link.getparent()
            idx = parent.index(link)
            for child in list(link):
                parent.insert(idx, child)
                idx += 1
            parent.remove(link)
            if rid and rid in part.rels:
                part.rels.pop(rid)

    package = doc.part.package
    for rid, rel in list(package.rels.items()):
        if rel.is_external:
            continue
        name = str(rel.target_part.partname)
        if name == "/docProps/custom.xml":
            package.rels.pop(rid)
        elif name == "/docProps/app.xml":
            part = rel.target_part
            root = etree.fromstring(part.blob)
            for el in root.iter():
                if isinstance(el.tag, str) and etree.QName(el).localname in ("Company", "Manager"):
                    el.text = ""
            part._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)

    if images:
        warnings.append(
            f"Het document bevat {images} afbeelding(en). Tekst ín afbeeldingen "
            f"(bijv. een gescande handtekening of briefhoofd) wordt niet gecontroleerd."
        )
    if any(str(p.partname).startswith("/word/embeddings/") for p in package.iter_parts()):
        warnings.append(
            "Het document bevat ingesloten objecten (bijv. een Excel-tabel). "
            "De inhoud daarvan wordt niet gecontroleerd."
        )
    return warnings


def _safety_net(doc, roots, replacements: list[Replacement]) -> None:
    """Replace every original value wherever else it still occurs in the package."""
    # Case-sensitive on purpose: 'Jan' must not turn the month 'jan.' into a placeholder.
    mapping: dict[str, str] = {}
    for r in replacements:
        original = " ".join(r.original.split())
        if len(original) >= _MIN_SAFETY_NET_LENGTH:
            mapping.setdefault(original, r.replacement)
    if not mapping:
        return
    pattern = re.compile(
        r"(?<!\w)(" + "|".join(re.escape(o).replace(r"\ ", r"\s+")
                               for o in sorted(mapping, key=len, reverse=True)) + r")(?!\w)"
    )

    def scrub(value: str) -> str:
        return pattern.sub(lambda m: mapping.get(" ".join(m.group().split()), m.group()), value)

    for _part, root, _kind, _ in roots:
        for el in root.iter():
            if not isinstance(el.tag, str):
                continue
            if el.text:
                new = scrub(el.text)
                if new != el.text:
                    el.text = new
            if el.tail:
                new = scrub(el.tail)
                if new != el.tail:
                    el.tail = new
            for attr, value in el.attrib.items():
                new = scrub(value)
                if new != value:
                    el.set(attr, new)

    for part in doc.part.package.iter_parts():
        for rel in part.rels.values():
            if rel.is_external and pattern.search(rel.target_ref):
                rel._target = "#"


def anonymize_docx(source: Path, target: Path, anonymizer: Anonymizer) -> tuple[list[Replacement], list[str]]:
    doc = Document(str(source))
    roots = list(_roots(doc))
    text, segments = _collect(roots)
    replacements = anonymizer.replacements(text)
    _apply(segments, replacements)
    warnings = _clean_metadata(doc, roots)
    _safety_net(doc, roots, replacements)

    for part, root, _kind, from_blob in roots:
        if from_blob:
            part._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)

    doc.save(str(target))
    return replacements, warnings


def write_text_as_docx(pages: list[str], target: Path, note: str) -> None:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    intro = doc.add_paragraph()
    run = intro.add_run(note)
    run.italic = True
    run.font.size = Pt(9)

    for number, page in enumerate(pages, start=1):
        if len(pages) > 1:
            doc.add_heading(f"Pagina {number}", level=2)
        for block in re.split(r"\n\s*\n", page.strip()):
            lines = [line.rstrip() for line in block.split("\n") if line.strip()]
            if not lines:
                continue
            p = doc.add_paragraph()
            for i, line in enumerate(lines):
                r = p.add_run(line)
                if i < len(lines) - 1:
                    r.add_break()

    props = doc.core_properties
    props.author = props.last_modified_by = ""
    doc.save(str(target))
