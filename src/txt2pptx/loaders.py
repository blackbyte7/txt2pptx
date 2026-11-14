"""Lightweight text extraction for supported input formats (no `unstructured` dependency)."""

from __future__ import annotations

import logging
from html.parser import HTMLParser
from pathlib import Path

from langchain_core.documents import Document

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = (".txt", ".md", ".pdf", ".docx", ".pptx", ".html", ".htm")


class UnsupportedFileError(ValueError):
    pass


def load_documents(path: str | Path, *, max_bytes: int | None = None) -> list[Document]:
    """Extract text from *path* as LangChain documents (one per page/slide where applicable)."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Input file not found: {path}")
    suffix = path.suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileError(
            f"Unsupported file type '{suffix}'. Supported: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    size = path.stat().st_size
    if max_bytes and size > max_bytes:
        raise UnsupportedFileError(
            f"File is too large ({size / 1e6:.1f} MB; limit {max_bytes / 1e6:.0f} MB)."
        )

    loader = {
        ".txt": _load_text,
        ".md": _load_text,
        ".pdf": _load_pdf,
        ".docx": _load_docx,
        ".pptx": _load_pptx,
        ".html": _load_html,
        ".htm": _load_html,
    }[suffix]
    try:
        docs = loader(path)
    except (FileNotFoundError, UnsupportedFileError):
        raise
    except Exception as exc:
        raise UnsupportedFileError(f"Could not read {path.name}: {exc}") from exc
    docs = [d for d in docs if d.page_content.strip()]
    logger.info(
        "Loaded %s: %d section(s), %d chars", path.name, len(docs), sum(len(d.page_content) for d in docs)
    )
    return docs


def load_text(path: str | Path, *, max_bytes: int | None = None) -> str:
    return "\n\n".join(d.page_content.strip() for d in load_documents(path, max_bytes=max_bytes))


# ------------------------------------------------------------------------------------- loaders ----


def _load_text(path: Path) -> list[Document]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    return [Document(page_content=text, metadata={"source": str(path)})]


def _load_pdf(path: Path) -> list[Document]:
    from pypdf import PdfReader

    reader = PdfReader(path)
    return [
        Document(page_content=page.extract_text() or "", metadata={"source": str(path), "page": i + 1})
        for i, page in enumerate(reader.pages)
    ]


def _load_docx(path: Path) -> list[Document]:
    import docx

    document = docx.Document(str(path))
    parts: list[str] = []
    for block in document.iter_inner_content():
        if hasattr(block, "rows"):  # table
            for row in block.rows:
                parts.append(" | ".join(cell.text.strip() for cell in row.cells))
        elif block.text.strip():
            style = (block.style.name or "").lower() if block.style is not None else ""
            prefix = (
                "#" * int(style[-1]) + " " if style.startswith("heading") and style[-1:].isdigit() else ""
            )
            parts.append(prefix + block.text.strip())
    return [Document(page_content="\n".join(parts), metadata={"source": str(path)})]


def _load_pptx(path: Path) -> list[Document]:
    from pptx import Presentation

    prs = Presentation(str(path))
    docs: list[Document] = []
    for number, slide in enumerate(prs.slides, start=1):
        lines: list[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                lines += [p.text for p in shape.text_frame.paragraphs if p.text.strip()]
            elif getattr(shape, "has_table", False) and shape.has_table:
                lines += [" | ".join(c.text for c in row.cells) for row in shape.table.rows]
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                lines.append(f"Notes: {notes}")
        docs.append(Document(page_content="\n".join(lines), metadata={"source": str(path), "slide": number}))
    return docs


class _TextExtractor(HTMLParser):
    _SKIP = frozenset({"script", "style", "noscript", "template", "svg"})
    _BLOCK = frozenset(
        {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "table"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def _load_html(path: Path) -> list[Document]:
    parser = _TextExtractor()
    parser.feed(_load_text(path)[0].page_content)
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    return [Document(page_content="\n".join(line for line in lines if line), metadata={"source": str(path)})]
