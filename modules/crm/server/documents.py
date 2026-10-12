"""Turn uploaded files into plain text (documents) or rows (spreadsheets)."""

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath

DOCUMENT_EXTS = {".docx", ".pdf", ".pptx", ".txt", ".md", ".markdown"}
SPREADSHEET_EXTS = {".xlsx", ".xlsm", ".csv"}
MAX_TEXT_CHARS = 600_000  # ~150k tokens; anything larger is truncated with a warning


class UnsupportedFile(ValueError):
    pass


@dataclass
class ParsedDocument:
    text: str
    created: datetime | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def words(self) -> int:
        return len(self.text.split())


@dataclass
class ParsedSheet:
    name: str
    rows: list[list[str]]


def kind_of(filename: str) -> str:
    ext = PurePosixPath(filename.lower()).suffix
    if ext in DOCUMENT_EXTS:
        return "document"
    if ext in SPREADSHEET_EXTS:
        return "spreadsheet"
    return "unsupported"


def text_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha256(normalized.encode()).hexdigest()


def _docx(data: bytes) -> ParsedDocument:
    import docx  # python-docx

    d = docx.Document(io.BytesIO(data))
    parts = [p.text for p in d.paragraphs]
    for table in d.tables:
        for row in table.rows:
            cells = []
            for c in row.cells:
                t = c.text.strip()
                if t and (not cells or cells[-1] != t):  # merged cells repeat
                    cells.append(t)
            if cells:
                parts.append(" | ".join(cells))
    created = d.core_properties.created
    return ParsedDocument("\n".join(parts), created)


def _pdf(data: bytes) -> ParsedDocument:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
    doc = ParsedDocument(text)
    if len(text.strip()) < 20 and len(reader.pages) > 0:
        doc.warnings.append("PDF has no extractable text (probably scanned); OCR isn't supported yet.")
    return doc


def _pptx(data: bytes) -> ParsedDocument:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    slides = []
    for i, slide in enumerate(prs.slides, 1):
        texts = [shape.text_frame.text for shape in slide.shapes if shape.has_text_frame and shape.text_frame.text.strip()]
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
            texts.append("Speaker notes: " + slide.notes_slide.notes_text_frame.text)
        if texts:
            slides.append(f"[Slide {i}]\n" + "\n".join(texts))
    return ParsedDocument("\n\n".join(slides), prs.core_properties.created)


def parse_document(filename: str, data: bytes) -> ParsedDocument:
    ext = PurePosixPath(filename.lower()).suffix
    if ext == ".docx":
        doc = _docx(data)
    elif ext == ".pdf":
        doc = _pdf(data)
    elif ext == ".pptx":
        doc = _pptx(data)
    elif ext in (".txt", ".md", ".markdown"):
        doc = ParsedDocument(data.decode("utf-8", errors="replace"))
    else:
        raise UnsupportedFile(f"Unsupported document type: {ext or filename}")
    doc.text = re.sub(r"\n{3,}", "\n\n", doc.text).strip()
    if len(doc.text) > MAX_TEXT_CHARS:
        doc.text = doc.text[:MAX_TEXT_CHARS]
        doc.warnings.append("Very long file: only the first ~150k tokens were read.")
    return doc


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat() if v.time() == datetime.min.time() else v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def parse_spreadsheet(filename: str, data: bytes) -> list[ParsedSheet]:
    ext = PurePosixPath(filename.lower()).suffix
    if ext == ".csv":
        text = data.decode("utf-8-sig", errors="replace")
        rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text))]
        return [ParsedSheet(PurePosixPath(filename).stem, [r for r in rows if any(r)])]
    if ext in (".xlsx", ".xlsm"):
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        sheets = []
        for ws in wb.worksheets:
            rows = [[_cell(v) for v in r] for r in ws.iter_rows(values_only=True)]
            rows = [r for r in rows if any(r)]
            if rows:
                width = max(i + 1 for r in rows for i, v in enumerate(r) if v)
                sheets.append(ParsedSheet(ws.title, [r[:width] + [""] * (width - len(r[:width])) for r in rows]))
        return sheets
    raise UnsupportedFile(f"Unsupported spreadsheet type: {ext or filename}")
