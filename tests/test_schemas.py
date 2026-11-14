import pytest
from pydantic import ValidationError

from txt2pptx.schemas import (
    ChartElement,
    CodeSafetyReview,
    ImagePlaceholderElement,
    PresentationOutline,
    SlideOutline,
    TableElement,
    TextElement,
)


def test_valid_outline(sample_outline):
    outline = PresentationOutline.model_validate(sample_outline)
    assert len(outline.slides) == 5
    assert isinstance(outline.slides[2].content_elements[1], ChartElement)
    assert isinstance(outline.slides[3].content_elements[0], TableElement)


def test_legacy_outline_format_is_accepted():
    legacy = {
        "metadata": {"presentation_style": "Professional"},
        "slides": [
            {
                "slide_number": 1,
                "slide_type": "opening",
                "title": "Intro",
                "design_elements": {"layout": "title_slide"},
                "content_elements": [{"element_type": "text", "bullet_points": ["a"]}],
            },
            {
                "slide_number": 2,
                "slide_type": "section_header",
                "title": "Data",
                "design_elements": {"layout": "something_unknown"},
                "content_elements": [
                    {
                        "element_type": "chart",
                        "chart_type": "BAR_CLUSTERED",
                        "categories": ["x", "y"],
                        "series": {"S1": [1, "2,500"], "S2": ["3.5", None]},
                    },
                    {"headers": ["h"], "rows": [["v"]]},
                    {"description": "logo"},
                ],
            },
        ],
    }
    outline = PresentationOutline.model_validate(legacy)
    first, second = outline.slides
    assert first.slide_type == "title"
    assert first.layout == "title_slide"
    assert second.slide_type == "section"
    assert second.layout is None  # unknown layouts fall back to automatic choice
    chart, table, image = second.content_elements
    assert chart.chart_type == "bar"
    assert [s.name for s in chart.series] == ["S1", "S2"]
    assert chart.series[0].values == [1.0, 2500.0]
    assert chart.series[1].values == [3.5, None]
    assert isinstance(table, TableElement)
    assert isinstance(image, ImagePlaceholderElement)


def test_element_type_defaults_to_text():
    slide = SlideOutline.model_validate({"title": "t", "content_elements": [{"bullet_points": ["x"]}]})
    assert isinstance(slide.content_elements[0], TextElement)


@pytest.mark.parametrize(
    "bad",
    [
        {"slides": []},
        {"slides": [{"content_elements": []}]},  # missing title
        {"slides": [{"title": "t", "content_elements": [{"element_type": "chart", "categories": [], "series": []}]}]},
        {"slides": [{"title": "t", "content_elements": [{"element_type": "chart", "chart_type": "radar",
                                                          "categories": ["a"], "series": [{"name": "s", "values": [1]}]}]}]},
        {"slides": [{"title": "t", "content_elements": [{"element_type": "table", "headers": [], "rows": []}]}]},
    ],
)  # fmt: skip
def test_invalid_outlines_rejected(bad):
    with pytest.raises(ValidationError):
        PresentationOutline.model_validate(bad)


def test_unsafe_review_gets_default_warning():
    review = CodeSafetyReview(is_safe=False, assessment="nope")
    assert review.warnings


def test_outline_json_schema_is_generated():
    schema = PresentationOutline.model_json_schema()
    assert "slides" in schema["properties"]
