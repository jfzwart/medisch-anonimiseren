"""Creates fake Dutch medical letters to test with. ALL personal data is made up."""

from __future__ import annotations

import random
import subprocess
import sys
from pathlib import Path

from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from PIL import Image, ImageDraw, ImageFilter, ImageFont

LETTER = """Universitair Medisch Centrum Utrecht
Afdeling Cardiologie, Heidelberglaan 100, 3584 CX Utrecht

Aan: dhr. drs. P. Jansen, huisarts
Huisartsenpraktijk De Linde, Dorpsstraat 3, 3701 AA Zeist

Utrecht, 4 november 2024

Betreft: dhr. J.P. (Jan) de Vries, geboren 12-03-1951
BSN 123456782, patiëntnummer 4567890

Geachte collega Jansen,

Hartelijk dank voor het verwijzen van bovengenoemde patiënt. De heer De Vries is een 73-jarige man, bekend met de ziekte van Parkinson en hypertensie. Hij werd vergezeld door zijn echtgenote Marie de Vries.

Anamnese: sinds twee maanden kortademig bij inspanning. Geen pijn op de borst.
Echocardiografie op 28-10-2024: LVEF 45%, matige mitralisinsufficiëntie.

Conclusie: hartfalen met licht verminderde ejectiefractie.
Beleid: start metoprolol 50 mg 1dd en furosemide 40 mg 1dd. Controle over 6 weken.

Met vriendelijke groet,

dr. A.M. Bakker, cardioloog
Tel. 030-2501234, a.bakker@umcutrecht.nl"""


def font(size: int):
    for f in ("/System/Library/Fonts/Supplemental/Times New Roman.ttf",
              "/System/Library/Fonts/Supplemental/Arial.ttf"):
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def make_docx(path: Path) -> None:
    doc = Document()
    doc.core_properties.author = "A.M. Bakker"
    doc.core_properties.title = "Brief J. de Vries"

    section = doc.sections[0]
    section.header.paragraphs[0].text = "UMC Utrecht — Afdeling Cardiologie — Heidelberglaan 100, Utrecht"
    section.footer.paragraphs[0].text = "Secretariaat: 030-2501234 — patiëntnummer 4567890"

    doc.add_paragraph("Utrecht, 4 november 2024")

    # Name split across runs with different formatting (tricky case)
    p = doc.add_paragraph("Betreft: dhr. ")
    r = p.add_run("Jan")
    r.bold = True
    p.add_run(" de ")
    r = p.add_run("Vries")
    r.italic = True
    p.add_run(", geboren 12-03-1951")

    table = doc.add_table(rows=3, cols=2)
    table.style = "Table Grid"
    for i, (k, v) in enumerate([("BSN", "123456782"), ("Adres", "Kerkstraat 14, 3512 AB Utrecht"),
                                 ("Telefoon", "06-12345678")]):
        table.cell(i, 0).text, table.cell(i, 1).text = k, v

    doc.add_paragraph()
    doc.add_paragraph("Geachte collega Jansen,")
    doc.add_paragraph(
        "De heer De Vries (73 jaar) is bekend met de ziekte van Parkinson. Hij werd vergezeld "
        "door zijn echtgenote Marie de Vries. Echocardiografie op 28-10-2024 toonde een LVEF van 45%."
    )
    doc.add_paragraph("Beleid: start metoprolol 50 mg 1dd. Controle over 6 weken. Zie ook 12 maart 1951.")

    # Hyperlink containing an e-mail address
    p = doc.add_paragraph("Vragen? Mail ")
    rid = p.part.relate_to("mailto:a.bakker@umcutrecht.nl", RT.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), rid)
    run = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = "a.bakker@umcutrecht.nl"
    run.append(t)
    link.append(run)
    p._p.append(link)

    doc.add_paragraph("Met vriendelijke groet,\tdr. A.M. Bakker, cardioloog")
    doc.save(str(path))


W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
W15 = "http://schemas.microsoft.com/office/word/2012/wordml"


def _field_run(paragraph, kind: str, instruction: str | None = None):
    r = OxmlElement("w:r")
    if instruction is None:
        el = OxmlElement("w:fldChar")
        el.set(qn("w:fldCharType"), kind)
    else:
        el = OxmlElement("w:instrText")
        el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        el.text = instruction
    r.append(el)
    paragraph._p.append(r)


def _add_part(docx_path: Path, partname: str, content_type: str, reltype: str, xml: str) -> None:
    """Add an XML part (with a relationship from document.xml) by editing the zip directly."""
    import re
    import zipfile

    with zipfile.ZipFile(docx_path) as z:
        files = {n: z.read(n) for n in z.namelist()}
    rels = files["word/_rels/document.xml.rels"].decode()
    rid = f"rIdTest{len(re.findall('Id=', rels)) + 1}"
    rels = rels.replace("</Relationships>",
                        f'<Relationship Id="{rid}" Type="{reltype}" Target="{partname.removeprefix("word/")}"/>'
                        "</Relationships>")
    types = files["[Content_Types].xml"].decode().replace(
        "</Types>", f'<Override PartName="/{partname}" ContentType="{content_type}"/></Types>')
    files["word/_rels/document.xml.rels"] = rels.encode()
    files["[Content_Types].xml"] = types.encode()
    files[partname] = xml.encode()
    with zipfile.ZipFile(docx_path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)


def make_hidden_data_docx(path: Path) -> None:
    """Personal data in places that are not ordinary visible text."""
    doc = Document()
    p = doc.add_paragraph("Betreft: dhr. Jan de Vries. ")
    comment_run = p.add_run("Bekend met de ziekte van Parkinson, metoprolol 50 mg, LVEF 45%.")
    doc.add_comment(comment_run, text="Graag terugbellen", author="Marie de Vries", initials="MdV")

    # Complex field: the e-mail address only exists in the field code, not in the visible text
    p = doc.add_paragraph("Vragen? ")
    _field_run(p, "begin")
    _field_run(p, "", ' HYPERLINK "mailto:marie.devries@ziggo.nl" ')
    _field_run(p, "separate")
    p.add_run("Mail mijn vrouw")
    _field_run(p, "end")

    # Simple field with a URL containing the patient number
    p = doc.add_paragraph("Zie ")
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), ' HYPERLINK "https://mijnpatient.nl/dossier/4567890" ')
    run = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = "het dossier"
    run.append(t)
    fld.append(run)
    p._p.append(fld)

    # Dates one character apart must get different placeholders; 'jan.' is a month here
    doc.add_paragraph("Echo op 1-3-2024, controle op 1-4-2024. Volgende afspraak in jan. bij de poli.")

    # Document variable in settings.xml
    doc_vars = OxmlElement("w:docVars")
    var = OxmlElement("w:docVar")
    var.set(qn("w:name"), "Patient")
    var.set(qn("w:val"), "Jan de Vries, Kerkstraat 14")
    doc_vars.append(var)
    doc.settings.element.append(doc_vars)
    doc.save(str(path))

    # people.xml: identity of the comment author
    _add_part(
        path, "word/people.xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.people+xml",
        "http://schemas.microsoft.com/office/2011/relationships/people",
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w15:people xmlns:w15="{W15}"><w15:person w15:author="Marie de Vries">'
        f'<w15:presenceInfo w15:providerId="AD" w15:userId="marie.devries@ziggo.nl"/>'
        f'</w15:person></w15:people>',
    )
    # SmartArt data part with a name in it
    _add_part(
        path, "word/diagrams/data1.xml",
        "application/vnd.openxmlformats-officedocument.drawingml.diagramData+xml",
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/diagramData",
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<dgm:dataModel xmlns:dgm="http://schemas.openxmlformats.org/drawingml/2006/diagram" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><dgm:ptLst><dgm:pt modelId="1">'
        '<dgm:t><a:p><a:r><a:t>Huisarts dr. P. Jansen</a:t></a:r></a:p></dgm:t></dgm:pt></dgm:ptLst>'
        '</dgm:dataModel>',
    )


def make_mixed_pdf(path: Path, scan_jpg: Path) -> None:
    """A digital header stamped over a scanned letter (as hospital portals do)."""
    import Quartz
    from AppKit import NSAttributedString, NSFont, NSFontAttributeName, NSGraphicsContext
    from Foundation import NSURL

    width, height = 595, 842
    ctx = Quartz.CGPDFContextCreateWithURL(
        NSURL.fileURLWithPath_(str(path)), Quartz.CGRectMake(0, 0, width, height), None)
    Quartz.CGPDFContextBeginPage(ctx, None)
    source = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(str(scan_jpg)), None)
    image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
    Quartz.CGContextDrawImage(ctx, Quartz.CGRectMake(0, 0, width, height - 40), image)

    ns_ctx = NSGraphicsContext.graphicsContextWithCGContext_flipped_(ctx, False)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(ns_ctx)
    header = "Uitdraai patiëntportaal — dhr. J.P. de Vries — BSN 123456782 — afgedrukt 12-11-2024"
    NSAttributedString.alloc().initWithString_attributes_(
        header, {NSFontAttributeName: NSFont.systemFontOfSize_(9)}).drawAtPoint_((30, height - 25))
    NSGraphicsContext.restoreGraphicsState()
    Quartz.CGPDFContextEndPage(ctx)
    Quartz.CGPDFContextClose(ctx)


def make_scan(pdf_path: Path, jpg_path: Path) -> None:
    width, height = 1654, 2339  # A4 at 200 dpi
    img = Image.new("L", (width, height), 250)
    d = ImageDraw.Draw(img)
    f = font(30)
    y = 140
    for line in LETTER.split("\n"):
        # wrap long lines
        current = ""
        for word in line.split(" "):
            if d.textlength(current + " " + word, font=f) > width - 260:
                d.text((130, y), current.strip(), fill=20, font=f)
                y += 44
                current = ""
            current += " " + word
        d.text((130, y), current.strip(), fill=20, font=f)
        y += 44
    # Scan effects: slight rotation, noise, blur
    random.seed(1)
    img = img.rotate(0.8, fillcolor=250, resample=Image.BICUBIC)
    px = img.load()
    for _ in range(40000):
        px[random.randrange(width), random.randrange(height)] = random.randrange(150, 255)
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    img.save(str(pdf_path), "PDF", resolution=200)
    img.save(str(jpg_path), "JPEG", quality=80)


def make_text_pdf(path: Path, tmp: Path) -> None:
    """Text PDF via the built-in macOS tool cupsfilter."""
    txt = tmp / "letter.txt"
    txt.write_text(LETTER, encoding="utf-8")
    with open(path, "wb") as out:
        subprocess.run(["/usr/sbin/cupsfilter", "-m", "application/pdf", str(txt)],
                       stdout=out, stderr=subprocess.DEVNULL, check=True)
    txt.unlink()


def main(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    make_docx(directory / "Brief cardiologie Jan de Vries.docx")
    subprocess.run(["/usr/bin/textutil", "-convert", "doc", "-output", str(directory / "oude brief.doc"),
                    str(directory / "Brief cardiologie Jan de Vries.docx")], check=True)
    make_text_pdf(directory / "ontslagbrief digitaal.pdf", directory)
    make_scan(directory / "gescande brief.pdf", directory / "foto van brief.jpg")
    make_hidden_data_docx(directory / "verborgen gegevens.docx")
    make_mixed_pdf(directory / "portaal met scan.pdf", directory / "foto van brief.jpg")
    print("Samples created in", directory)


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "tests/samples"))
