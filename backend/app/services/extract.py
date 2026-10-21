"""Turn an uploaded file into text, page by page.

Supported: PDF (text layer only), DOCX, Markdown and plain text. The file type is decided by the
extension and then checked against the file's first bytes, so a renamed file is not misread.
Everything here is pure Python, so it installs from any package index without a compiler.
"""

import io
import re
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree  # noqa: S405 (input size is capped; expat stops entity bombs)

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from app.errors import ApiError

SUPPORTED = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".md": "text/markdown",
    ".txt": "text/plain",
}
MAX_DOCX_XML_BYTES = 60 * 1024 * 1024
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass(frozen=True)
class Page:
    number: int | None  # None for formats without pages
    text: str


@dataclass(frozen=True)
class Extracted:
    mime: str
    pages: list[Page]
    page_count: int | None


def _unsupported(name: str) -> ApiError:
    kinds = ", ".join(sorted(SUPPORTED))
    return ApiError("unsupported_file", f"'{name}' is not a supported file type ({kinds}).", 415)


def _clean(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _pdf(data: bytes, name: str, max_pages: int) -> Extracted:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ApiError("unreadable_file", f"'{name}' is password-protected.", 422)
        total = len(reader.pages)
        if total > max_pages:
            raise ApiError(
                "document_too_large", f"'{name}' has {total} pages; the limit is {max_pages}.", 413
            )
        pages = [Page(i + 1, _clean(p.extract_text() or "")) for i, p in enumerate(reader.pages)]
    except ApiError:
        raise
    except (PyPdfError, ValueError, KeyError, RecursionError, OSError) as exc:
        raise ApiError("unreadable_file", f"'{name}' could not be read as a PDF.", 422) from exc
    return Extracted(SUPPORTED[".pdf"], pages, total)


def _docx(data: bytes, name: str) -> Extracted:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > MAX_DOCX_XML_BYTES:
                raise ApiError("document_too_large", f"'{name}' is too large to read.", 413)
            root = ElementTree.fromstring(archive.read(info))  # noqa: S314
    except ApiError:
        raise
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, ValueError, OSError) as exc:
        raise ApiError("unreadable_file", f"'{name}' could not be read as a DOCX.", 422) from exc
    paragraphs = []
    for para in root.iter(f"{_W}p"):
        parts = []
        for node in para.iter():
            if node.tag == f"{_W}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{_W}tab":
                parts.append("\t")
            elif node.tag in (f"{_W}br", f"{_W}cr"):
                parts.append("\n")
        paragraphs.append("".join(parts))
    return Extracted(SUPPORTED[".docx"], [Page(None, _clean("\n\n".join(paragraphs)))], None)


def extract(filename: str, data: bytes, *, max_pdf_pages: int = 500) -> Extracted:
    """Read the text of a file. Raises ApiError with a readable message when it cannot be used."""
    name = filename.strip() or "file"
    suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if suffix not in SUPPORTED:
        raise _unsupported(name)
    if suffix == ".pdf":
        if not data.lstrip()[:5].startswith(b"%PDF"):
            raise ApiError("unreadable_file", f"'{name}' is not a PDF file.", 422)
        result = _pdf(data, name, max_pdf_pages)
    elif suffix == ".docx":
        if not data.startswith(b"PK"):
            raise ApiError("unreadable_file", f"'{name}' is not a DOCX file.", 422)
        result = _docx(data, name)
    else:
        if b"\x00" in data[:4096]:
            raise ApiError("unreadable_file", f"'{name}' is not a text file.", 422)
        result = Extracted(SUPPORTED[suffix], [Page(None, _clean(_decode(data)))], None)
    if not any(p.text for p in result.pages):
        hint = " It may be a scan; text in images is not read." if suffix == ".pdf" else ""
        raise ApiError("no_text", f"'{name}' contains no text.{hint}", 422)
    return result
