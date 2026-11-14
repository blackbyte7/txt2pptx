"""Pydantic models shared by the LLM chains, the PPTX generator, the web UI and the MCP server.

The :class:`PresentationOutline` is the central contract: an LLM (server-side, or the MCP client itself)
produces it and :class:`~txt2pptx.pptx_generator.PPTXGenerator` renders it deterministically.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ChartType = Literal["bar", "column", "stacked_bar", "stacked_column", "line", "pie", "doughnut", "area"]
SlideType = Literal["title", "section", "content", "closing"]
LayoutName = Literal[
    "title_slide",
    "title_content",
    "section_header",
    "two_content",
    "comparison",
    "title_only",
    "blank",
]

# Legacy / python-pptx enum names the LLM (or older outlines) may still produce.
_CHART_TYPE_ALIASES: dict[str, str] = {
    "bar_clustered": "bar",
    "bar_stacked": "stacked_bar",
    "column_clustered": "column",
    "column_stacked": "stacked_column",
    "line_markers": "line",
    "pie_exploded": "pie",
    "doughnut_exploded": "doughnut",
    "area_stacked": "area",
    "clustered_bar": "bar",
    "clustered_column": "column",
}
_SLIDE_TYPE_ALIASES: dict[str, str] = {
    "opening": "title",
    "intro": "title",
    "title_slide": "title",
    "section_header": "section",
    "conclusion": "closing",
    "summary": "closing",
}


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class ElementPosition(_Model):
    """Explicit placement in inches, measured from the slide's top-left corner."""

    left_inches: float = Field(ge=0, le=20)
    top_inches: float = Field(ge=0, le=20)
    width_inches: float = Field(gt=0, le=20)
    height_inches: float = Field(gt=0, le=20)


class TextElement(_Model):
    element_type: Literal["text"] = "text"
    title: str | None = Field(None, description="Optional bold heading above the bullets.")
    bullet_points: list[str] = Field(
        default_factory=list, description="Concise bullet points (max ~15 words)."
    )
    level: int = Field(0, ge=0, le=4, description="Indentation level of the bullets (0 = top level).")
    position: ElementPosition | None = None


Cell = str | int | float | None


class TableElement(_Model):
    element_type: Literal["table"] = "table"
    title: str | None = None
    headers: list[str] = Field(min_length=1, description="Column headers.")
    rows: list[list[Cell]] = Field(min_length=1, description="Data rows; one value per header.")
    position: ElementPosition | None = None


class ChartSeries(_Model):
    name: str
    values: list[float | None] = Field(description="One value per category.")

    @field_validator("values", mode="before")
    @classmethod
    def _coerce_numbers(cls, values: Any) -> Any:
        if not isinstance(values, list):
            return values
        return [_to_number(v) for v in values]


class ChartElement(_Model):
    element_type: Literal["chart"] = "chart"
    chart_type: ChartType = "column"
    title: str | None = None
    categories: list[str] = Field(min_length=1, description="Category labels (x-axis or pie slices).")
    series: list[ChartSeries] = Field(
        min_length=1, description="Data series; pie/doughnut use only the first."
    )
    position: ElementPosition | None = None

    @field_validator("chart_type", mode="before")
    @classmethod
    def _normalise_chart_type(cls, value: Any) -> Any:
        if isinstance(value, str):
            key = value.strip().lower().replace(" ", "_").replace("-", "_")
            return _CHART_TYPE_ALIASES.get(key, key)
        return value

    @field_validator("categories", mode="before")
    @classmethod
    def _stringify_categories(cls, value: Any) -> Any:
        return [str(v) for v in value] if isinstance(value, list) else value

    @field_validator("series", mode="before")
    @classmethod
    def _accept_mapping_series(cls, value: Any) -> Any:
        # Legacy format: {"Series A": [1, 2], "Series B": [3, 4]}
        if isinstance(value, dict):
            return [{"name": str(k), "values": v} for k, v in value.items()]
        return value


class ImagePlaceholderElement(_Model):
    element_type: Literal["image_placeholder"] = "image_placeholder"
    description: str = Field(
        description="What image belongs here, e.g. 'team photo' or 'product screenshot'."
    )
    position: ElementPosition | None = None


ContentElement = Annotated[
    TextElement | TableElement | ChartElement | ImagePlaceholderElement,
    Field(discriminator="element_type"),
]


class SlideOutline(_Model):
    title: str = Field(description="Short, specific slide title (max ~10 words).")
    subtitle: str | None = Field(None, description="Subtitle for title/section slides.")
    slide_type: SlideType = "content"
    layout: LayoutName | None = Field(
        None, description="Override the layout derived from slide_type/content."
    )
    content_elements: list[ContentElement] = Field(
        default_factory=list, description="At most 2 elements per slide renders best."
    )
    speaker_notes: str | None = Field(None, description="What the presenter should say.")

    @model_validator(mode="before")
    @classmethod
    def _legacy_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        design = data.pop("design_elements", None)
        if isinstance(design, dict) and design.get("layout") and not data.get("layout"):
            data["layout"] = design["layout"]
        if data.get("layout") not in (None, *LayoutName.__args__):
            data["layout"] = None  # unknown layout keys fall back to automatic selection
        slide_type = data.get("slide_type")
        if isinstance(slide_type, str):
            normalised = slide_type.strip().lower()
            normalised = _SLIDE_TYPE_ALIASES.get(normalised, normalised)
            data["slide_type"] = normalised if normalised in SlideType.__args__ else "content"
        # Elements without a discriminator default to text.
        elements = data.get("content_elements")
        if isinstance(elements, list):
            data["content_elements"] = [
                {**e, "element_type": e.get("element_type") or _guess_element_type(e)}
                if isinstance(e, dict)
                else e
                for e in elements
            ]
        return data


class PresentationMetadata(_Model):
    title: str | None = Field(None, description="Deck title (used for file properties).")
    author: str | None = None
    target_audience: str | None = None
    estimated_duration_minutes: int | None = Field(None, ge=0)
    language: str | None = Field(None, description="Language of the slide text, e.g. 'en'.")


class PresentationOutline(_Model):
    """A complete, render-ready description of a slide deck."""

    metadata: PresentationMetadata = Field(default_factory=PresentationMetadata)
    slides: list[SlideOutline] = Field(min_length=1)


# ---------------------------------------------------------------------------------------- reviews ----


class QualityReview(_Model):
    """LLM-generated review of an outline."""

    overall_score: int = Field(ge=0, le=100)
    strengths: list[str] = Field(default_factory=list)
    areas_for_improvement: list[str] = Field(default_factory=list)
    clarity_flow_feedback: str = ""
    engagement_feedback: str = ""
    visual_suggestions: list[str] = Field(default_factory=list)
    timing_feedback: str | None = None


class AnalysisReport(_Model):
    """Heuristic (non-LLM) content analysis."""

    warnings: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)

    def to_markdown(self) -> str:
        if not self.warnings and not self.suggestions:
            return "No issues found."
        parts: list[str] = []
        if self.warnings:
            parts.append("**Warnings**\n" + "\n".join(f"- {w}" for w in self.warnings))
        if self.suggestions:
            parts.append("**Suggestions**\n" + "\n".join(f"- {s}" for s in self.suggestions))
        return "\n\n".join(parts)


# ----------------------------------------------------------------------------- code generation ----


class GeneratedCode(_Model):
    python_code: str = Field(
        description="python-pptx code that builds the deck in a variable named `prs`. Do NOT call prs.save()."
    )


class CodeSafetyReview(_Model):
    is_safe: bool
    warnings: list[str] = Field(default_factory=list)
    assessment: str = ""

    @model_validator(mode="after")
    def _explain_unsafe(self) -> CodeSafetyReview:
        if not self.is_safe and not self.warnings:
            self.warnings.append("Code marked as unsafe; no specific reasons provided.")
        return self


# ------------------------------------------------------------------------------------- helpers ----


def _to_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None if value is None else float(value)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "").replace("%", "").replace("$", "").replace("€", "")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _guess_element_type(element: dict[str, Any]) -> str:
    if "headers" in element or "rows" in element:
        return "table"
    if "series" in element or "categories" in element:
        return "chart"
    if "description" in element and "bullet_points" not in element:
        return "image_placeholder"
    return "text"
