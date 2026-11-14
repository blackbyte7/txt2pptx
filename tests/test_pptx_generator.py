"""Generator tests against real python-pptx output (re-opened from disk)."""

import pytest
from pptx import Presentation
from pptx.enum.chart import XL_CHART_TYPE
from pptx.oxml.ns import qn
from pptx.util import Inches

from txt2pptx.pptx_generator import Box, PPTXGenerator, fit_font_size, grid_boxes
from txt2pptx.schemas import ChartElement, PresentationOutline, TextElement
from txt2pptx.templates import TemplateManager


@pytest.fixture
def render(tmp_path):
    def _render(outline_dict, template="professional", **overrides):
        manager = TemplateManager()
        tpl = manager.customize(template, overrides or None)
        path = tmp_path / "deck.pptx"
        result = PPTXGenerator(tpl).save(PresentationOutline.model_validate(outline_dict), path)
        return Presentation(str(path)), result

    return _render


def _shapes_by_kind(slide):
    return {
        "charts": [s for s in slide.shapes if s.has_chart],
        "tables": [s for s in slide.shapes if s.has_table],
        "text": [s for s in slide.shapes if s.has_text_frame],
    }


def test_deck_structure(render, sample_outline):
    prs, result = render(sample_outline)
    assert result.warnings == []
    assert len(prs.slides) == 5
    assert prs.slide_width == Inches(13.333)
    assert prs.core_properties.title == "AI Testing 2026"
    assert prs.core_properties.author == "QA Team"

    title_slide = prs.slides[0]
    assert title_slide.shapes.title.text == "AI Testing in Practice"
    assert any("Reliability" in s.text_frame.text for s in title_slide.shapes if s.has_text_frame)

    assert prs.slides[1].notes_slide.notes_text_frame.text == "Set the stage."


def test_no_empty_placeholders_left(render, sample_outline):
    prs, _ = render(sample_outline)
    for slide in prs.slides:
        for ph in slide.placeholders:
            assert ph.has_text_frame and ph.text_frame.text.strip(), f"empty placeholder on {slide.slide_id}"


def test_placeholders_scaled_to_widescreen(render, sample_outline):
    prs, _ = render(sample_outline)
    for slide in prs.slides:
        for shape in slide.shapes:
            assert shape.left + shape.width <= prs.slide_width + Inches(0.01)


def test_background_color_applied(render, sample_outline):
    prs, _ = render(sample_outline, template="dark")
    fill = prs.slides[1].background.fill
    assert str(fill.fore_color.rgb) == "111827"


def test_chart_and_text_side_by_side(render, sample_outline):
    prs, _ = render(sample_outline)
    kinds = _shapes_by_kind(prs.slides[2])
    assert len(kinds["charts"]) == 1
    chart_shape = kinds["charts"][0]
    chart = chart_shape.chart
    assert chart.chart_type == XL_CHART_TYPE.COLUMN_CLUSTERED
    assert chart.has_legend  # two series
    assert [s.name for s in chart.plots[0].series] == ["Product A", "Product B"]
    bullet_box = next(s for s in kinds["text"] if "East leads A" in s.text_frame.text)
    assert bullet_box.left < chart_shape.left


def test_free_textbox_bullets_have_glyphs(render, sample_outline):
    prs, _ = render(sample_outline)
    box = next(s for s in prs.slides[2].shapes if s.has_text_frame and "East leads A" in s.text_frame.text)
    paragraphs = [p for p in box.text_frame.paragraphs if p.text in {"East leads A", "South leads B"}]
    assert paragraphs
    for p in paragraphs:
        assert p._p.pPr.find(qn("a:buChar")) is not None
    heading = next(p for p in box.text_frame.paragraphs if p.text == "Highlights")
    assert heading._p.pPr.find(qn("a:buNone")) is not None
    assert box.text_frame.paragraphs[0].text == "Highlights"  # no leading empty paragraph


def test_single_text_uses_body_placeholder(render, sample_outline):
    prs, _ = render(sample_outline)
    slide = prs.slides[1]
    bodies = [ph for ph in slide.placeholders if ph.placeholder_format.idx == 1]
    assert bodies and "non-deterministic" in bodies[0].text_frame.text
    assert bodies[0].text_frame.paragraphs[0].level == 0


def test_table_styling(render, sample_outline):
    prs, _ = render(sample_outline)
    table = _shapes_by_kind(prs.slides[3])["tables"][0].table
    header = table.cell(0, 0)
    assert header.text == "Region"
    assert str(header.fill.fore_color.rgb) == "2E86DE"  # accent1
    assert str(header.text_frame.paragraphs[0].runs[0].font.color.rgb) == "FFFFFF"
    assert table.cell(1, 1).text == "1,500"
    assert table.cell(2, 2).text == "950.5"


@pytest.mark.parametrize(
    "chart_type", ["bar", "column", "stacked_bar", "stacked_column", "line", "pie", "doughnut", "area"]
)
def test_every_chart_type_renders(render, chart_type):
    outline = {
        "slides": [{
            "title": "Chart",
            "content_elements": [{
                "element_type": "chart", "chart_type": chart_type, "categories": ["a", "b", "c"],
                "series": [{"name": "s1", "values": [1, 2.5, 3]}, {"name": "s2", "values": [3, 2, 1]}],
            }],
        }]
    }  # fmt: skip
    prs, result = render(outline)
    charts = _shapes_by_kind(prs.slides[0])["charts"]
    assert len(charts) == 1
    if chart_type in {"pie", "doughnut"}:
        assert len(charts[0].chart.plots[0].series) == 1
        assert any("one series" in w for w in result.warnings)
    else:
        assert not result.warnings


def test_mismatched_series_is_padded_with_warning(render):
    outline = {"slides": [{"title": "x", "content_elements": [{
        "element_type": "chart", "categories": ["a", "b", "c"], "series": [{"name": "s", "values": [1]}]}]}]}  # fmt: skip
    prs, result = render(outline)
    assert any("had 1 values for 3 categories" in w for w in result.warnings)
    assert _shapes_by_kind(prs.slides[0])["charts"]


def test_long_table_truncated(render):
    rows = [[str(i), i] for i in range(30)]
    outline = {"slides": [{"title": "x", "content_elements": [{
        "element_type": "table", "headers": ["k", "v"], "rows": rows}]}]}  # fmt: skip
    prs, result = render(outline)
    assert len(_shapes_by_kind(prs.slides[0])["tables"][0].table.rows) == 15
    assert any("truncated" in w for w in result.warnings)


def test_explicit_position_and_image_placeholder(render):
    outline = {"slides": [{"title": "x", "layout": "blank", "content_elements": [{
        "element_type": "image_placeholder", "description": "logo",
        "position": {"left_inches": 1, "top_inches": 2, "width_inches": 3, "height_inches": 1.5}}]}]}  # fmt: skip
    prs, _ = render(outline)
    slide = prs.slides[0]
    image = next(s for s in slide.shapes if s.name == "Image Placeholder")
    assert (image.left, image.top, image.width) == (Inches(1), Inches(2), Inches(3))
    assert any(
        s.name == "Title" and s.text_frame.text == "x" for s in slide.shapes
    )  # blank layout => manual title


def test_four_by_three_template(render, sample_outline):
    prs, _ = render(sample_outline, aspect_ratio="4:3")
    assert prs.slide_width == Inches(10)


def test_every_template_renders(render, sample_outline):
    for name in TemplateManager().names():
        _, result = render(sample_outline, template=name)
        assert result.warnings == []


def test_fit_font_size_shrinks_long_text():
    short = fit_font_size([("Hello", 0)], Inches(6), Inches(3), 24)
    long = fit_font_size([("word " * 60, 0)] * 6, Inches(6), Inches(3), 24, min_pt=10)
    assert short == 24
    assert 10 <= long < 24


def test_grid_boxes():
    area = Box(0, 0, Inches(12), Inches(5))
    assert grid_boxes(area, []) == []
    assert grid_boxes(area, [TextElement()]) == [area]
    text_chart = grid_boxes(
        area, [TextElement(), ChartElement(categories=["a"], series=[{"name": "s", "values": [1]}])]
    )
    assert text_chart[0].width < text_chart[1].width
    assert len(grid_boxes(area, [TextElement()] * 3)) == 3


def test_widescreen_placeholders_keep_their_height(render, sample_outline):
    """Regression: scaling must not collapse inherited placeholder geometry to zero height."""
    prs, _ = render(sample_outline)
    for slide in prs.slides:
        for ph in slide.placeholders:
            assert ph.height > Inches(0.5), f"placeholder {ph.name} collapsed"
            assert ph.top > 0 or ph.placeholder_format.idx == 0
