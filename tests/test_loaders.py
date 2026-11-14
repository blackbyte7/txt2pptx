import docx
import pytest
from pptx import Presentation

from tests.helpers import write_text_pdf
from txt2pptx.loaders import UnsupportedFileError, load_documents, load_text


def test_txt_with_legacy_encoding(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_bytes("Café prices – up 5%".encode("cp1252"))
    assert load_text(path) == "Café prices – up 5%"


def test_markdown_with_bom(tmp_path):
    path = tmp_path / "a.md"
    path.write_bytes("﻿# Title\n\nBody".encode())
    assert load_text(path).startswith("# Title")


def test_html_strips_scripts_and_styles(tmp_path):
    path = tmp_path / "page.html"
    path.write_text(
        "<html><head><style>p{color:red}</style><script>alert('x')</script></head>"
        "<body><h1>Heading</h1><p>First &amp; second</p><ul><li>One</li><li>Two</li></ul></body></html>",
        encoding="utf-8",
    )
    text = load_text(path)
    assert "alert" not in text and "color" not in text
    assert text.splitlines() == ["Heading", "First & second", "One", "Two"]


def test_docx_paragraphs_headings_and_tables(tmp_path):
    document = docx.Document()
    document.add_heading("Quarterly report", level=1)
    document.add_paragraph("Revenue grew.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "Region", "Sales"
    table.cell(1, 0).text, table.cell(1, 1).text = "North", "100"
    path = tmp_path / "report.docx"
    document.save(path)
    text = load_text(path)
    assert "# Quarterly report" in text
    assert "Revenue grew." in text
    assert "North | 100" in text


def test_pptx_slides_and_notes(tmp_path):
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Agenda"
    slide.placeholders[1].text_frame.text = "Point one"
    slide.notes_slide.notes_text_frame.text = "Say hello"
    path = tmp_path / "deck.pptx"
    prs.save(path)
    docs = load_documents(path)
    assert docs[0].metadata["slide"] == 1
    assert "Agenda" in docs[0].page_content and "Notes: Say hello" in docs[0].page_content


def test_pdf_pages(tmp_path):
    path = write_text_pdf(tmp_path / "doc.pdf", ["Hello PDF", "Second line"])
    docs = load_documents(path)
    assert docs[0].metadata["page"] == 1
    assert "Hello PDF" in docs[0].page_content


def test_unsupported_extension(tmp_path):
    path = tmp_path / "x.exe"
    path.write_bytes(b"MZ")
    with pytest.raises(UnsupportedFileError, match="Unsupported"):
        load_text(path)


def test_size_limit(tmp_path):
    path = tmp_path / "big.txt"
    path.write_text("x" * 2000)
    with pytest.raises(UnsupportedFileError, match="too large"):
        load_text(path, max_bytes=1000)


def test_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_text(tmp_path / "nope.txt")


def test_corrupt_file_wrapped(tmp_path):
    path = tmp_path / "bad.docx"
    path.write_bytes(b"not a zip")
    with pytest.raises(UnsupportedFileError, match="Could not read"):
        load_text(path)
