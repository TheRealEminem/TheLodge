"""A prepared roundup as a file: Word (python-docx), PDF (reportlab) or Markdown.

All three are written from the packet alone (roundups.py), in the same order: the title and who it's for, the opening,
everyone at a glance, then a page per person. The overviews and the opening are Markdown, so a small reader here turns
headings, lists, bold, italics and links into each format's own.
"""
import base64
import io
import re
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

INLINE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__|\*(?!\s)(.+?)\*|(?<!\w)_(?!\s)(.+?)_(?!\w)|\[([^\]]+)\]\(([^)\s]+)\)")
LIST = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+(.*)$")
HEADING = re.compile(r"^\s*#{1,6}\s+(.*)$")
LABEL = re.compile(r"^\s*\*\*[^*]+\*\*:?\s*$")


# ── Reading the Markdown ──────────────────────────────────────────────

def blocks(md: str) -> list[tuple[str, str]]:
    """("h" | "p" | "li", text) for each heading, paragraph and list item."""
    out: list[tuple[str, str]] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            out.append(("p", " ".join(para)))
            para.clear()

    for line in (md or "").splitlines():
        if not line.strip():
            flush()
        elif m := HEADING.match(line):
            flush()
            out.append(("h", m.group(1).strip().strip("#").strip()))
        elif LABEL.match(line):
            flush()
            out.append(("p", line.strip()))                    # "**Worth knowing**": a label on its own line
        elif m := LIST.match(line):
            flush()
            out.append(("li", m.group(1).strip()))
        elif out and out[-1][0] == "li" and not para and line.startswith((" ", "\t")):
            out[-1] = ("li", f"{out[-1][1]} {line.strip()}")      # a list item carried onto the next line
        else:
            para.append(line.strip())
    flush()
    return out


def runs(text: str) -> list[tuple[str, bool, bool, str | None]]:
    """(text, bold, italic, link) pieces of one line of Markdown."""
    out, at = [], 0
    for m in INLINE.finditer(text):
        if m.start() > at:
            out.append((text[at:m.start()], False, False, None))
        bold, bold2, it, it2, label, href = m.groups()
        if bold or bold2:
            out.append((bold or bold2, True, False, None))
        elif it or it2:
            out.append((it or it2, False, True, None))
        else:
            out.append((label, False, False, href))
        at = m.end()
    if at < len(text):
        out.append((text[at:], False, False, None))
    return [r for r in out if r[0]]


def plain(text: str) -> str:
    return "".join(r[0] for r in runs(text))


# ── What every format says ────────────────────────────────────────────

def _date(iso: str) -> str:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%-d %B %Y")


def _byline(p: dict) -> str:
    who = f"Prepared for {p['audience']} by {p['owner']}" if p.get("audience") else f"Prepared by {p['owner']}"
    return f"{who} · {_date(p['prepared_at'])} · {len(p['people'])} {'person' if len(p['people']) == 1 else 'people'}"


def _whose(p: dict) -> str:
    first = p["owner"].split()[0] if p["owner"].split() else p["owner"]
    return (f"The summaries come from {first}'s own records and were written for {first}, so where they say "
            f"“you”, that's {first}. The AI was told to use only what's on file. Written by {p['written_by']}.")


def _contact(s: dict) -> list[tuple[str, str | None]]:
    """(label, link) pairs for the line under a person's name."""
    out: list[tuple[str, str | None]] = []
    if s.get("linkedin"):
        url = s["linkedin"] if s["linkedin"].startswith("http") else f"https://{s['linkedin']}"
        out.append(("LinkedIn", url))
    if s.get("email"):
        out.append((s["email"], f"mailto:{s['email']}"))
    if s.get("website"):
        url = s["website"] if s["website"].startswith("http") else f"https://{s['website']}"
        out.append((s["website"].removeprefix("https://").removeprefix("http://").rstrip("/"), url))
    return out


def _org_line(o: dict) -> str:
    return o["name"] + (f", {o['role']}" if o.get("role") else "") + ("" if o["current"] else " (earlier)")


def _conn_line(c: dict) -> tuple[str, str]:
    name = c["name"] + (f" ({c['headline']})" if c.get("headline") else "")
    return name, c["relation"] + (" · also in this packet" if c["in_packet"] else "")


def _image(s: dict) -> tuple[bytes, str] | None:
    pic = s.get("picture")
    if not pic:
        return None
    data, mime = base64.b64decode(pic["data"]), pic["mime"]
    if mime not in ("image/jpeg", "image/png"):
        from PIL import Image
        out = io.BytesIO()
        Image.open(io.BytesIO(data)).convert("RGB").save(out, "JPEG", quality=90)
        data, mime = out.getvalue(), "image/jpeg"
    return data, mime


# ── Markdown ──────────────────────────────────────────────────────────

def markdown(p: dict) -> str:
    out = [f"# {p['title']}", "", f"*{_byline(p)}*", ""]
    if p.get("event"):
        out += [f"**The event:** {p['event']}", ""]
    out += [p["intro"].strip(), "", "## At a glance", ""]
    for s in p["people"]:
        out.append(f"- **{s['name']}**" + (f", {s['headline']}" if s["headline"] else "") + (f": {s['blurb']}" if s.get("blurb") else ""))
    out += ["", f"*{_whose(p)}*", ""]
    for s in p["people"]:
        out += ["---", "", f"## {s['name']}", ""]
        sub = " · ".join(x for x in (s["headline"], s.get("location")) if x)
        if sub:
            out += [sub, ""]
        if links := _contact(s):
            out += [" · ".join(f"[{label}]({url})" if url else label for label, url in links), ""]
        if s.get("blurb"):
            out += [f"**For this event:** {s['blurb']}", ""]
        if s.get("with_owner"):
            out += [f"*{s['with_owner']}*", ""]
        out += ["### Summary", "", (s["summary"] or "Little is on file about them yet.").strip(), ""]
        if s["organizations"]:
            out += ["### Organizations", "", *[f"- {_org_line(o)}" for o in s["organizations"]], ""]
        if s["connections"]:
            out += ["### Closest connections", "", *[f"- **{n}**: {r}" for n, r in map(_conn_line, s["connections"])], ""]
    return "\n".join(out).rstrip() + "\n"


# ── Word ──────────────────────────────────────────────────────────────

def _hyperlink(paragraph, url: str, text: str, bold: bool = False, italic: bool = False) -> None:
    from docx.opc.constants import RELATIONSHIP_TYPE
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    rid = paragraph.part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), rid)
    run = OxmlElement("w:r")
    props = OxmlElement("w:rPr")
    for tag, val in (("w:color", "1F5C4A"), ("w:u", "single")):
        el = OxmlElement(tag)
        el.set(qn("w:val"), val)
        props.append(el)
    if bold:
        props.append(OxmlElement("w:b"))
    if italic:
        props.append(OxmlElement("w:i"))
    run.append(props)
    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    run.append(t)
    link.append(run)
    paragraph._p.append(link)


def _docx_runs(paragraph, text: str, bold: bool = False, italic: bool = False) -> None:
    for piece, b, i, href in runs(text):
        if href:
            _hyperlink(paragraph, href, piece, bold or b, italic or i)
        else:
            r = paragraph.add_run(piece)
            r.bold, r.italic = bold or b or None, italic or i or None


def _docx_md(doc, md: str, heading_level: int = 3) -> None:
    for kind, text in blocks(md):
        if kind == "h":
            doc.add_heading(plain(text), heading_level)
        elif kind == "li":
            _docx_runs(doc.add_paragraph(style="List Bullet"), text)
        else:
            _docx_runs(doc.add_paragraph(), text)


def docx(p: dict) -> bytes:
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.shared import Inches, Pt, RGBColor

    doc = Document()
    for section in doc.sections:
        section.left_margin = section.right_margin = Inches(0.9)
        section.top_margin = section.bottom_margin = Inches(0.8)
    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = "Calibri", Pt(10.5)
    soft = RGBColor(0x5B, 0x63, 0x5F)
    for style in ("Title", "Heading 1", "Heading 2", "Heading 3"):
        doc.styles[style].font.name, doc.styles[style].font.color.rgb = "Calibri", RGBColor(0x1D, 0x24, 0x20)

    doc.add_heading(p["title"], 0)
    by = doc.add_paragraph()
    run = by.add_run(_byline(p))
    run.italic, run.font.color.rgb = True, soft
    if p.get("event"):
        para = doc.add_paragraph()
        para.add_run("The event: ").bold = True
        para.add_run(p["event"])
    _docx_md(doc, p["intro"], 2)

    doc.add_heading("At a glance", 1)
    for s in p["people"]:
        para = doc.add_paragraph(style="List Bullet")
        para.add_run(s["name"]).bold = True
        if s["headline"]:
            para.add_run(f", {s['headline']}")
        if s.get("blurb"):
            para.add_run(f": {s['blurb']}")
    note = doc.add_paragraph()
    run = note.add_run(_whose(p))
    run.italic, run.font.size, run.font.color.rgb = True, Pt(9), soft

    for s in p["people"]:
        doc.add_page_break()
        table = doc.add_table(rows=1, cols=2)
        table.alignment = WD_TABLE_ALIGNMENT.LEFT
        pic_cell, head = table.rows[0].cells
        pic_cell.width, head.width = Inches(1.4), Inches(5.3)
        if (img := _image(s)) is not None:
            pic_cell.paragraphs[0].add_run().add_picture(io.BytesIO(img[0]), width=Inches(1.25))
        else:
            pic_cell.width, head.width = Inches(0.1), Inches(6.6)
        name = head.paragraphs[0]
        r = name.add_run(s["name"])
        r.bold, r.font.size = True, Pt(18)
        sub = " · ".join(x for x in (s["headline"], s.get("location")) if x)
        if sub:
            r = head.add_paragraph().add_run(sub)
            r.font.color.rgb = soft
        if links := _contact(s):
            para = head.add_paragraph()
            for n, (label, url) in enumerate(links):
                if n:
                    para.add_run(" · ")
                _hyperlink(para, url, label) if url else para.add_run(label)
        if s.get("blurb"):
            para = doc.add_paragraph()
            para.paragraph_format.space_before = Pt(10)
            para.add_run("For this event: ").bold = True
            para.add_run(s["blurb"])
        if s.get("with_owner"):
            r = doc.add_paragraph().add_run(s["with_owner"])
            r.italic, r.font.color.rgb = True, soft
        doc.add_heading("Summary", 2)
        _docx_md(doc, s["summary"] or "Little is on file about them yet.")
        if s["organizations"]:
            doc.add_heading("Organizations", 2)
            for o in s["organizations"]:
                doc.add_paragraph(_org_line(o), style="List Bullet")
        if s["connections"]:
            doc.add_heading("Closest connections", 2)
            for n, rel in map(_conn_line, s["connections"]):
                para = doc.add_paragraph(style="List Bullet")
                para.add_run(n).bold = True
                para.add_run(f": {rel}")
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


# ── PDF ───────────────────────────────────────────────────────────────

FONTS = Path("/System/Library/Fonts/Supplemental")


def _fonts() -> tuple[str, str, str]:
    """Arial from macOS, which covers accents, Greek and Cyrillic; reportlab's own Helvetica elsewhere (Docker)."""
    from reportlab.lib.fonts import addMapping
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    files = {"Packet": "Arial.ttf", "Packet-Bold": "Arial Bold.ttf", "Packet-Italic": "Arial Italic.ttf", "Packet-BoldItalic": "Arial Bold Italic.ttf"}
    if "Packet" in pdfmetrics.getRegisteredFontNames():
        return "Packet", "Packet-Bold", "Packet-Italic"
    if all((FONTS / f).is_file() for f in files.values()):
        for name, f in files.items():
            pdfmetrics.registerFont(TTFont(name, str(FONTS / f)))
        addMapping("Packet", 0, 0, "Packet")
        addMapping("Packet", 1, 0, "Packet-Bold")
        addMapping("Packet", 0, 1, "Packet-Italic")
        addMapping("Packet", 1, 1, "Packet-BoldItalic")
        return "Packet", "Packet-Bold", "Packet-Italic"
    return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"


def _markup(text: str) -> str:
    """One line of Markdown as reportlab's paragraph markup."""
    out = []
    for piece, bold, italic, href in runs(text):
        piece = escape(piece)
        if href:
            piece = f'<a href="{escape(href, {chr(34): "&quot;"})}" color="#1F5C4A"><u>{piece}</u></a>'
        if bold:
            piece = f"<b>{piece}</b>"
        if italic:
            piece = f"<i>{piece}</i>"
        out.append(piece)
    return "".join(out)


def pdf(p: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import Image, KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    regular, bold, italic = _fonts()
    ink, soft, rule = colors.HexColor("#1D2420"), colors.HexColor("#5B635F"), colors.HexColor("#D9DED8")
    body = ParagraphStyle("body", fontName=regular, fontSize=10.5, leading=15, textColor=ink, spaceAfter=6)
    small = ParagraphStyle("small", parent=body, fontSize=9, leading=12.5, textColor=soft)
    meta = ParagraphStyle("meta", parent=body, textColor=soft, spaceAfter=2)
    title = ParagraphStyle("title", parent=body, fontName=bold, fontSize=24, leading=29, spaceAfter=6)
    name = ParagraphStyle("name", parent=body, fontName=bold, fontSize=19, leading=23, spaceAfter=3)
    h1 = ParagraphStyle("h1", parent=body, fontName=bold, fontSize=14, leading=18, spaceBefore=12, spaceAfter=6)
    h2 = ParagraphStyle("h2", parent=body, fontName=bold, fontSize=11.5, leading=15, spaceBefore=10, spaceAfter=4)

    def bullets(items: list[str]):
        return ListFlowable([ListItem(Paragraph(i, body), leftIndent=12, value="•") for i in items],
                            bulletType="bullet", start="•", leftIndent=12, bulletFontName=regular, bulletColor=soft)

    def md(text: str, heading=h2) -> list:
        flow, items = [], []
        for kind, line in blocks(text):
            if kind == "li":
                items.append(_markup(line))
                continue
            if items:
                flow.append(bullets(items))
                items = []
            flow.append(Paragraph(_markup(line), heading if kind == "h" else body))
        if items:
            flow.append(bullets(items))
        return flow

    story: list = [Paragraph(escape(p["title"]), title), Paragraph(escape(_byline(p)), meta), Spacer(1, 10)]
    if p.get("event"):
        story.append(Paragraph(f"<b>The event:</b> {escape(p['event'])}", body))
    story += md(p["intro"])
    story.append(Paragraph("At a glance", h1))
    story.append(bullets([f"<b>{escape(s['name'])}</b>" + (f", {escape(s['headline'])}" if s["headline"] else "")
                          + (f": {escape(s['blurb'])}" if s.get("blurb") else "") for s in p["people"]]))
    story += [Spacer(1, 8), Paragraph(escape(_whose(p)), small)]

    for s in p["people"]:
        story.append(PageBreak())
        head = [Paragraph(escape(s["name"]), name)]
        sub = " · ".join(x for x in (s["headline"], s.get("location")) if x)
        if sub:
            head.append(Paragraph(escape(sub), meta))
        if links := _contact(s):
            head.append(Paragraph(" · ".join(_markup(f"[{label}]({url})") if url else escape(label) for label, url in links), meta))
        img = _image(s)
        if img is not None:
            pic = Image(io.BytesIO(img[0]), width=1.15 * inch, height=1.15 * inch, kind="proportional")
            table = Table([[pic, head]], colWidths=[1.35 * inch, None])
        else:
            table = Table([[head]])
        table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (0, 0), 0),
                                   ("LINEBELOW", (0, 0), (-1, -1), 0.6, rule), ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]))
        story += [table, Spacer(1, 10)]
        if s.get("blurb"):
            story.append(Paragraph(f"<b>For this event:</b> {escape(s['blurb'])}", body))
        if s.get("with_owner"):
            story.append(Paragraph(f"<i>{escape(s['with_owner'])}</i>", meta))
        story.append(Paragraph("Summary", h2))
        story += md(s["summary"] or "Little is on file about them yet.", h2)
        if s["organizations"]:
            story.append(KeepTogether([Paragraph("Organizations", h2), bullets([escape(_org_line(o)) for o in s["organizations"]])]))
        if s["connections"]:
            lines = [f"<b>{escape(n)}</b>: {escape(r)}" for n, r in map(_conn_line, s["connections"])]
            story.append(KeepTogether([Paragraph("Closest connections", h2), bullets(lines)]))

    def footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(regular, 8)
        canvas.setFillColor(soft)
        canvas.drawString(0.9 * inch, 0.55 * inch, p["title"])
        canvas.drawRightString(LETTER[0] - 0.9 * inch, 0.55 * inch, str(doc.page))
        canvas.restoreState()

    out = io.BytesIO()
    SimpleDocTemplate(out, pagesize=LETTER, leftMargin=0.9 * inch, rightMargin=0.9 * inch, topMargin=0.8 * inch,
                      bottomMargin=0.9 * inch, title=p["title"], author=p["owner"]).build(story, onFirstPage=footer, onLaterPages=footer)
    return out.getvalue()


def markdown_pdf(title: str, md: str, author: str = "") -> bytes:
    """Any Markdown (headings, paragraphs, lists, bold, italics, links) as a plain PDF in the packets' type, for quick
    export (quick_export.py). The first heading is the title; the rest are section headings."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate

    regular, bold, _ = _fonts()
    ink, soft = colors.HexColor("#1D2420"), colors.HexColor("#5B635F")
    body = ParagraphStyle("body", fontName=regular, fontSize=10.5, leading=15, textColor=ink, spaceAfter=6)
    big = ParagraphStyle("title", parent=body, fontName=bold, fontSize=22, leading=27, spaceAfter=4)
    h1 = ParagraphStyle("h1", parent=body, fontName=bold, fontSize=13.5, leading=17, spaceBefore=12, spaceAfter=5)

    story: list = []
    items: list[str] = []

    def bullets() -> None:
        if items:
            story.append(ListFlowable([ListItem(Paragraph(i, body), leftIndent=12, value="•") for i in items],
                                      bulletType="bullet", start="•", leftIndent=12, bulletFontName=regular, bulletColor=soft))
            items.clear()

    for kind, line in blocks(md):
        if kind == "li":
            items.append(_markup(line))
            continue
        bullets()
        style = (big if not story else h1) if kind == "h" else body
        story.append(Paragraph(_markup(line), style))
    bullets()

    def footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(regular, 8)
        canvas.setFillColor(soft)
        canvas.drawString(0.9 * inch, 0.55 * inch, title)
        canvas.drawRightString(LETTER[0] - 0.9 * inch, 0.55 * inch, str(doc.page))
        canvas.restoreState()

    out = io.BytesIO()
    SimpleDocTemplate(out, pagesize=LETTER, leftMargin=0.9 * inch, rightMargin=0.9 * inch, topMargin=0.8 * inch,
                      bottomMargin=0.9 * inch, title=title, author=author).build(story, onFirstPage=footer, onLaterPages=footer)
    return out.getvalue()


def render(packet: dict, fmt: str) -> bytes:
    if fmt == "md":
        return markdown(packet).encode()
    return docx(packet) if fmt == "docx" else pdf(packet)
