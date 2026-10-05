"""Parse bytes locally; never execute documents, fetch links or open user paths."""

from io import BytesIO
from zipfile import ZipFile

from backend.app.files.contracts import (
    CHUNK_CHARS, MAX_UPLOAD_BYTES, MAX_TEXT_CHARS, MAX_PDF_PAGES,
    FileImportError, validate_filename,
)

SUPPORTED_TYPES = frozenset({"txt", "pdf", "docx"})


def _normalize(text):
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")).strip()


def _pdf_units(data):
    from pypdf import PdfReader
    reader = PdfReader(BytesIO(data), strict=True)
    if reader.is_encrypted:
        raise FileImportError("Password-protected PDFs are not supported.")
    if len(reader.pages) > MAX_PDF_PAGES:
        raise FileImportError("Import a PDF of at most 100 pages.")
    for number, page in enumerate(reader.pages, 1):
        yield {"text": page.extract_text() or "", "page": number, "section": None}


def _docx_units(data):
    from docx import Document
    from docx.table import Table
    # Inspect the ZIP without extracting it. Bound expanded XML/media size.
    with ZipFile(BytesIO(data)) as archive:
        entries = archive.infolist()
        if (len(entries) > 1000 or sum(item.file_size for item in entries) > 20 * 1024 * 1024
                or "word/document.xml" not in archive.namelist()):
            raise FileImportError("The Word document is invalid or too large when expanded.")
    document = Document(BytesIO(data))
    blocks = []
    for block in document.iter_inner_content():
        if isinstance(block, Table):
            blocks.extend(" | ".join(cell.text for cell in row.cells) for row in block.rows)
        else:
            blocks.append(block.text)
    # DOCX pagination is not known without rendering; do not invent page numbers.
    yield {"text": "\n".join(blocks), "page": None, "section": None}


def _chunks(text):
    """Deterministic non-overlapping chunks, preferably split at a text boundary."""
    start = 0
    while start < len(text):
        end = min(start + CHUNK_CHARS, len(text))
        if end < len(text):
            boundary = max(text.rfind("\n", start + CHUNK_CHARS // 2, end),
                           text.rfind(" ", start + CHUNK_CHARS // 2, end))
            if boundary > start:
                end = boundary + 1
        yield text[start:end]
        start = end


def parse_file(filename, data):
    """Return normalized text/chunks only. No storage, model or network calls."""
    validate_filename(filename)
    file_type = filename.rsplit(".", 1)[-1].casefold()
    if file_type not in SUPPORTED_TYPES:
        raise FileImportError("Supported files are UTF-8 .txt, text-based .pdf and .docx.")
    if not isinstance(data, bytes) or not data:
        raise FileImportError("The imported file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise FileImportError("Import a file of at most 5 MB.")
    try:
        if file_type == "txt":
            units = [{"text": data.decode("utf-8-sig"), "page": None, "section": None}]
        else:
            units = _pdf_units(data) if file_type == "pdf" else _docx_units(data)
        chunks, texts, total = [], [], 0
        for unit in units:
            text = _normalize(unit["text"])
            if not text:
                continue
            total += len(text)
            if total > MAX_TEXT_CHARS:
                raise FileImportError("Extracted text exceeds 250,000 characters; import a smaller document.")
            texts.append(text)
            chunks.extend({"text": part, "page": unit["page"], "section": unit["section"]}
                          for part in _chunks(text))
        if not texts:
            raise FileImportError("No readable text was found. Scanned PDFs need OCR, which is not supported yet.")
        return {"filename": filename, "file_type": file_type, "text": "\n\n".join(texts), "chunks": chunks}
    except FileImportError:
        raise
    except UnicodeDecodeError:
        raise FileImportError("Save text files as UTF-8 before importing.") from None
    except Exception:
        # Parser exceptions may contain document text or paths; expose neither.
        raise FileImportError("The document could not be parsed. Check its format and try a smaller file.") from None
