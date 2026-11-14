import pytest

from tests.helpers import write_text_pdf
from txt2pptx import exporters
from txt2pptx.analyzers import ContentAnalyzer
from txt2pptx.exporters import PresentationExporter
from txt2pptx.schemas import PresentationOutline


def test_analyzer_clean_outline(sample_outline):
    report = ContentAnalyzer().analyze(PresentationOutline.model_validate(sample_outline))
    assert report.warnings == []
    assert report.to_markdown() == "No issues found." or report.suggestions


def test_analyzer_flags_problems():
    outline = PresentationOutline.model_validate(
        {
            "slides": [
                {"title": "A very long title that goes on and on and on forever and ever", "content_elements": []},
                {
                    "title": "Dense",
                    "content_elements": [
                        {"element_type": "text", "bullet_points": [f"point {i}" for i in range(9)]},
                        {"element_type": "text", "bullet_points": ["word " * 30]},
                        {"element_type": "chart", "chart_type": "pie", "categories": list("abcdefgh"),
                         "series": [{"name": "s", "values": [1, 2]}]},
                        {"element_type": "table", "headers": ["h"], "rows": [[i] for i in range(12)]},
                    ],
                },
                {"title": "Dense", "content_elements": []},
                {"title": "End", "content_elements": []},
            ]
        }
    )  # fmt: skip
    report = ContentAnalyzer().analyze(outline)
    text = report.to_markdown()
    assert "start with a title slide" in text
    assert "end with a closing" in text
    assert "9 bullets" in text or "10 bullets" in text
    assert "4 content elements" in text
    assert "pie slices" in text
    assert "2 values for 8 categories" in text
    assert "12 rows" in text
    assert "same title as slide 2" in text
    assert "title has" in text


@pytest.fixture
def no_pdf_tools(monkeypatch):
    monkeypatch.setattr(exporters, "find_soffice", lambda: None)
    monkeypatch.setattr(exporters, "powerpoint_available", lambda: False)


def test_export_without_pdf_tools_reports_errors(no_pdf_tools, service, sample_outline):
    deck = service.build(sample_outline).pptx_path
    exporter = PresentationExporter(service.output_dir)
    assert exporter.capabilities() == {"pdf": False, "images": False, "html": True}
    result = exporter.export(deck, ["pdf", "images", "html", "gif"])
    assert set(result.errors) == {"pdf", "images", "gif"}
    assert "LibreOffice" in result.errors["pdf"]
    assert result.files["html"][0].exists()


def test_images_rendered_from_pdf_without_poppler(tmp_path):
    pdf = write_text_pdf(tmp_path / "deck.pdf", ["Slide one"])
    paths = PresentationExporter(tmp_path).to_images(pdf, "deck")
    assert [p.name for p in paths] == ["slide_001.png"]
    from PIL import Image

    with Image.open(paths[0]) as img:
        assert img.width > 1000


def test_html_export_escapes_and_includes_notes(service):
    deck = service.build(
        {"slides": [{"title": "<script>x</script>", "speaker_notes": "say <b>hi</b>",
                     "content_elements": [{"element_type": "text", "bullet_points": ["a & b"]}]}]}
    ).pptx_path  # fmt: skip
    html = PresentationExporter(service.output_dir).to_html(deck).read_text(encoding="utf-8")
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html
    assert "a &amp; b" in html
    assert 'class="notes"' in html
