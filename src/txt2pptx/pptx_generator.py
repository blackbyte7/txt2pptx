"""Deterministic rendering of a :class:`PresentationOutline` into a ``.pptx`` file."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lxml import etree
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_DATA_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE, PP_PLACEHOLDER
from pptx.enum.text import MSO_AUTO_SIZE, MSO_VERTICAL_ANCHOR, PP_PARAGRAPH_ALIGNMENT
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

from txt2pptx.schemas import (
    ChartElement,
    ElementPosition,
    ImagePlaceholderElement,
    PresentationOutline,
    SlideOutline,
    TableElement,
    TextElement,
)
from txt2pptx.templates import FontSpec, Template

logger = logging.getLogger(__name__)

SLIDE_SIZES = {"16:9": (Inches(13.333), Inches(7.5)), "4:3": (Inches(10), Inches(7.5))}
_DEFAULT_TEMPLATE_WIDTH = Inches(10)  # geometry of python-pptx's built-in layouts

DEFAULT_LAYOUT_INDEX = {
    "title_slide": 0,
    "title_content": 1,
    "section_header": 2,
    "two_content": 3,
    "comparison": 4,
    "title_only": 5,
    "blank": 6,
}

CHART_TYPES = {
    "bar": XL_CHART_TYPE.BAR_CLUSTERED,
    "column": XL_CHART_TYPE.COLUMN_CLUSTERED,
    "stacked_bar": XL_CHART_TYPE.BAR_STACKED,
    "stacked_column": XL_CHART_TYPE.COLUMN_STACKED,
    "line": XL_CHART_TYPE.LINE_MARKERS,
    "pie": XL_CHART_TYPE.PIE,
    "doughnut": XL_CHART_TYPE.DOUGHNUT,
    "area": XL_CHART_TYPE.AREA,
}
_BODY_PLACEHOLDER_TYPES = {PP_PLACEHOLDER.BODY, PP_PLACEHOLDER.OBJECT, PP_PLACEHOLDER.SUBTITLE}
_TITLE_PLACEHOLDER_TYPES = {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE}

MARGIN_X = Inches(0.6)
CONTENT_TOP = Inches(1.75)
MARGIN_BOTTOM = Inches(0.55)
GUTTER = Inches(0.35)


@dataclass
class Box:
    left: int
    top: int
    width: int
    height: int

    @classmethod
    def from_position(cls, pos: ElementPosition) -> Box:
        return cls(
            Inches(pos.left_inches),
            Inches(pos.top_inches),
            Inches(pos.width_inches),
            Inches(pos.height_inches),
        )

    def shrink_top(self, amount: int) -> Box:
        amount = min(amount, self.height // 2)
        return Box(self.left, self.top + amount, self.width, self.height - amount)


@dataclass
class RenderResult:
    presentation: Any
    warnings: list[str] = field(default_factory=list)


def _rgb(hex_color: str) -> RGBColor:
    return RGBColor.from_string(hex_color.lstrip("#").upper())


class PPTXGenerator:
    """Render outlines with a :class:`~txt2pptx.templates.Template`."""

    def __init__(self, template: Template | None = None):
        self.template = template or Template(name="default")
        self.colors = self.template.colors
        self.fonts = self.template.fonts
        self.layout_index = {**DEFAULT_LAYOUT_INDEX, **self.template.layouts}
        self.warnings: list[str] = []

    # ----------------------------------------------------------------------------------- public --
    def build(self, outline: PresentationOutline) -> RenderResult:
        self.warnings = []
        prs = Presentation()
        prs.slide_width, prs.slide_height = SLIDE_SIZES[self.template.aspect_ratio]
        self._x_scale = prs.slide_width / _DEFAULT_TEMPLATE_WIDTH

        meta = outline.metadata
        props = prs.core_properties
        props.title = (meta.title or outline.slides[0].title)[:255]
        props.author = meta.author or "txt2pptx"
        if meta.language:
            props.language = meta.language

        for number, slide in enumerate(outline.slides, start=1):
            try:
                self._add_slide(prs, slide, number, total=len(outline.slides))
            except Exception as exc:  # keep going; report instead of corrupting the deck
                logger.exception("Slide %d failed", number)
                self._warn(number, f"could not be rendered completely ({exc})")
        return RenderResult(prs, list(self.warnings))

    def save(self, outline: PresentationOutline, path: Path) -> RenderResult:
        result = self.build(outline)
        path.parent.mkdir(parents=True, exist_ok=True)
        result.presentation.save(str(path))
        return result

    # ----------------------------------------------------------------------------------- slides --
    def _warn(self, slide_number: int, message: str) -> None:
        text = f"Slide {slide_number}: {message}"
        logger.warning(text)
        self.warnings.append(text)

    def _choose_layout(self, slide: SlideOutline) -> str:
        if slide.layout:
            return slide.layout
        if slide.slide_type == "title":
            return "title_slide"
        if slide.slide_type == "section":
            return "section_header"
        elements = slide.content_elements
        free = [e for e in elements if e.position is None]
        if not elements:
            return "title_only"
        if len(free) == len(elements) and all(isinstance(e, TextElement) for e in elements):
            if len(elements) == 1:
                return "title_content"
            if len(elements) == 2:
                return "two_content"
        return "title_only"

    def _add_slide(self, prs: Any, data: SlideOutline, number: int, total: int) -> None:
        layout_name = self._choose_layout(data)
        index = self.layout_index.get(layout_name, DEFAULT_LAYOUT_INDEX["title_only"])
        if index >= len(prs.slide_layouts):
            self._warn(number, f"layout index {index} unavailable; using 'title_only'")
            index = DEFAULT_LAYOUT_INDEX["title_only"]
        slide = prs.slides.add_slide(prs.slide_layouts[index])
        self._scale_placeholders(slide)
        self._apply_background(slide)

        used: set[int] = set()
        title_ph = next(
            (ph for ph in slide.placeholders if ph.placeholder_format.type in _TITLE_PLACEHOLDER_TYPES), None
        )
        is_cover = layout_name in {"title_slide", "section_header"}
        title_size = self.fonts.heading.size + (8 if layout_name == "title_slide" else 0)
        if title_ph is not None:
            self._fill_title(title_ph, data.title, title_size, center=layout_name == "title_slide")
            used.add(title_ph.placeholder_format.idx)
        else:
            box = Box(MARGIN_X, Inches(0.35), prs.slide_width - 2 * MARGIN_X, Inches(1.2))
            tb = slide.shapes.add_textbox(box.left, box.top, box.width, box.height)
            tb.name = "Title"
            self._fill_title(tb, data.title, title_size, center=False)

        body_phs = [ph for ph in slide.placeholders if ph.placeholder_format.type in _BODY_PLACEHOLDER_TYPES]
        elements = list(data.content_elements)

        if is_cover:
            subtitle = data.subtitle
            if subtitle is None and elements and isinstance(elements[0], TextElement):
                first = elements.pop(0)
                subtitle = "\n".join(filter(None, [first.title, *first.bullet_points]))
            if subtitle and body_phs:
                self._fill_plain(body_phs[0], subtitle)
                used.add(body_phs[0].placeholder_format.idx)
        else:
            if data.subtitle:
                elements.insert(0, TextElement(bullet_points=[data.subtitle]))
            self._add_accent_bar(slide, title_ph)

        if elements:
            all_text_free = all(isinstance(e, TextElement) and e.position is None for e in elements)
            if all_text_free and not is_cover and len(body_phs) >= len(elements):
                for element, ph in zip(elements, body_phs, strict=False):
                    self._fill_text(ph.text_frame, element, Box(ph.left, ph.top, ph.width, ph.height), True)
                    used.add(ph.placeholder_format.idx)
            else:
                self._render_free_form(prs, slide, elements, number, cover=is_cover)

        self._remove_unused_placeholders(slide, used)
        if data.speaker_notes:
            slide.notes_slide.notes_text_frame.text = data.speaker_notes
        if not is_cover:
            self._add_slide_number(prs, slide, number, total)

    # ------------------------------------------------------------------------------- decoration --
    def _scale_placeholders(self, slide: Any) -> None:
        if math.isclose(self._x_scale, 1.0):
            return
        for ph in slide.placeholders:
            # Read all inherited values first: assigning any one of them creates the slide's own <a:xfrm>,
            # after which the remaining properties no longer inherit from the layout (they read as 0).
            left, top, width, height = ph.left, ph.top, ph.width, ph.height
            if None in (left, top, width, height):
                continue
            ph.left, ph.width = int(left * self._x_scale), int(width * self._x_scale)
            ph.top, ph.height = top, height

    def _apply_background(self, slide: Any) -> None:
        fill = slide.background.fill
        fill.solid()
        fill.fore_color.rgb = _rgb(self.colors.background)

    def _add_accent_bar(self, slide: Any, title_ph: Any) -> None:
        left = title_ph.left if title_ph is not None else MARGIN_X
        top = (title_ph.top + title_ph.height) if title_ph is not None else Inches(1.55)
        bar = slide.shapes.add_shape(
            MSO_AUTO_SHAPE_TYPE.RECTANGLE,
            left,
            min(top, CONTENT_TOP - Inches(0.12)),
            Inches(1.1),
            Inches(0.06),
        )
        bar.name = "Accent Bar"
        bar.fill.solid()
        bar.fill.fore_color.rgb = _rgb(self.colors.accent1)
        bar.line.fill.background()

    def _add_slide_number(self, prs: Any, slide: Any, number: int, total: int) -> None:
        width = Inches(1.2)
        tb = slide.shapes.add_textbox(
            prs.slide_width - MARGIN_X - width, prs.slide_height - Inches(0.45), width, Inches(0.3)
        )
        tb.name = "Slide Number"
        p = tb.text_frame.paragraphs[0]
        p.alignment = PP_PARAGRAPH_ALIGNMENT.RIGHT
        run = p.add_run()
        run.text = f"{number} / {total}"
        self._style_run(run, FontSpec(name=self.fonts.body.name, size=10), self.colors.text_light)

    def _remove_unused_placeholders(self, slide: Any, used: set[int]) -> None:
        for ph in list(slide.placeholders):
            if ph.placeholder_format.idx in used:
                continue
            if ph.has_text_frame and ph.text_frame.text.strip():
                continue
            ph._element.getparent().remove(ph._element)

    # -------------------------------------------------------------------------------------- text --
    def _style_run(self, run: Any, font: FontSpec, color: str, *, size: float | None = None) -> None:
        run.font.name = font.name
        run.font.size = Pt(size or font.size)
        run.font.bold = font.bold
        run.font.italic = font.italic
        run.font.color.rgb = _rgb(color)

    def _fill_title(self, shape: Any, text: str, size: float, *, center: bool) -> None:
        tf = shape.text_frame
        tf.word_wrap = True
        tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        tf.text = ""
        p = tf.paragraphs[0]
        if center:
            p.alignment = PP_PARAGRAPH_ALIGNMENT.CENTER
        run = p.add_run()
        run.text = text
        fitted = fit_font_size([(text, 0)], shape.width, shape.height, size, min_pt=20, line_spacing=1.1)
        self._style_run(run, self.fonts.heading, self.colors.title or self.colors.text, size=fitted)

    def _fill_plain(self, shape: Any, text: str) -> None:
        tf = shape.text_frame
        tf.word_wrap = True
        tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        lines = [line for line in text.splitlines() if line.strip()] or [text]
        size = fit_font_size(
            [(line, 0) for line in lines], shape.width, shape.height, self.fonts.body.size + 2, min_pt=12
        )
        tf.text = ""
        for i, line in enumerate(lines):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            _set_bullet(p, None)
            run = p.add_run()
            run.text = line
            self._style_run(run, self.fonts.body, self.colors.text_light, size=size)

    def _fill_text(self, tf: Any, element: TextElement, box: Box, in_placeholder: bool) -> None:
        tf.word_wrap = True
        tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        if not in_placeholder:
            tf.vertical_anchor = MSO_VERTICAL_ANCHOR.TOP
            for side in ("left", "right", "top", "bottom"):
                setattr(tf, f"margin_{side}", Inches(0.08))
        tf.text = ""

        bullets = [b for b in element.bullet_points if b.strip()]
        lines = ([(element.title, 0)] if element.title else []) + [(b, element.level + 1) for b in bullets]
        base = self.fonts.body.size
        size = fit_font_size(lines, box.width, box.height, base, min_pt=11)
        paragraphs = iter([tf.paragraphs[0]])

        def next_paragraph() -> Any:
            return next(paragraphs, None) or tf.add_paragraph()

        if element.title:
            p = next_paragraph()
            _set_bullet(p, None)
            p.space_after = Pt(6)
            run = p.add_run()
            run.text = element.title
            heading = FontSpec(name=self.fonts.body.name, size=size + 2, bold=True)
            self._style_run(run, heading, self.colors.title or self.colors.text)

        for text in bullets:
            p = next_paragraph()
            p.level = min(element.level, 4)
            p.space_before = Pt(4)
            if not in_placeholder:
                _set_bullet(p, self.colors.accent1, level=p.level, size_pt=size)
            run = p.add_run()
            run.text = text
            self._style_run(run, self.fonts.body, self.colors.text, size=max(10, size - 2 * p.level))

    # ------------------------------------------------------------------------------- free form --
    def _content_area(self, prs: Any, cover: bool) -> Box:
        top = Inches(4.6) if cover else CONTENT_TOP
        return Box(MARGIN_X, top, prs.slide_width - 2 * MARGIN_X, prs.slide_height - top - MARGIN_BOTTOM)

    def _render_free_form(
        self, prs: Any, slide: Any, elements: list[Any], number: int, *, cover: bool
    ) -> None:
        area = self._content_area(prs, cover)
        auto = [e for e in elements if e.position is None]
        boxes = iter(grid_boxes(area, auto))
        for element in elements:
            box = Box.from_position(element.position) if element.position else next(boxes)
            try:
                if isinstance(element, TextElement):
                    shape = slide.shapes.add_textbox(box.left, box.top, box.width, box.height)
                    self._fill_text(shape.text_frame, element, box, in_placeholder=False)
                elif isinstance(element, TableElement):
                    self._add_table(slide, element, box, number)
                elif isinstance(element, ChartElement):
                    self._add_chart(slide, element, box, number)
                elif isinstance(element, ImagePlaceholderElement):
                    self._add_image_placeholder(slide, element, box)
            except Exception as exc:
                logger.exception("Element rendering failed on slide %d", number)
                self._warn(number, f"{element.element_type} element skipped ({exc})")

    def _add_caption(self, slide: Any, text: str, box: Box) -> Box:
        height = Inches(0.45)
        tb = slide.shapes.add_textbox(box.left, box.top, box.width, height)
        tb.text_frame.word_wrap = True
        run = tb.text_frame.paragraphs[0].add_run()
        run.text = text
        self._style_run(
            run, FontSpec(name=self.fonts.body.name, size=self.fonts.body.size, bold=True), self.colors.text
        )
        return box.shrink_top(height + Inches(0.05))

    # ------------------------------------------------------------------------------------ tables --
    def _add_table(self, slide: Any, element: TableElement, box: Box, number: int) -> None:
        if element.title:
            box = self._add_caption(slide, element.title, box)
        n_cols = len(element.headers)
        rows = [list(r[:n_cols]) + [None] * (n_cols - len(r)) for r in element.rows]
        if any(len(r) > n_cols for r in element.rows):
            self._warn(number, "table rows longer than the header were truncated")
        max_rows = 14
        if len(rows) > max_rows:
            self._warn(number, f"table truncated to {max_rows} of {len(rows)} rows")
            rows = rows[:max_rows]

        n_rows = len(rows) + 1
        row_height = min(int(box.height / n_rows), Inches(0.55))
        shape = slide.shapes.add_table(n_rows, n_cols, box.left, box.top, box.width, row_height * n_rows)
        table = shape.table
        table.first_row = True
        table.horz_banding = False
        col_width = int(box.width / n_cols)
        for col in table.columns:
            col.width = col_width
        for row in table.rows:
            row.height = row_height

        size = max(10.0, min(self.fonts.body.size - 2, 16 - max(0, n_rows - 6) * 0.6))
        body_font = FontSpec(name=self.fonts.body.name, size=size)
        header_font = FontSpec(name=self.fonts.body.name, size=size, bold=True)

        for c, header in enumerate(element.headers):
            self._style_cell(
                table.cell(0, c), header, header_font, self.colors.on_accent, self.colors.accent1
            )
        for r, row in enumerate(rows, start=1):
            fill = self.colors.surface if r % 2 else self.colors.surface_alt
            for c, value in enumerate(row):
                numeric = isinstance(value, int | float) and not isinstance(value, bool)
                self._style_cell(
                    table.cell(r, c), _format_cell(value), body_font, self.colors.text, fill, right=numeric
                )

    def _style_cell(
        self, cell: Any, text: str, font: FontSpec, color: str, fill: str, *, right: bool = False
    ) -> None:
        cell.fill.solid()
        cell.fill.fore_color.rgb = _rgb(fill)
        cell.vertical_anchor = MSO_VERTICAL_ANCHOR.MIDDLE
        cell.margin_left = cell.margin_right = Inches(0.08)
        tf = cell.text_frame
        tf.word_wrap = True
        tf.text = ""
        p = tf.paragraphs[0]
        p.alignment = PP_PARAGRAPH_ALIGNMENT.RIGHT if right else PP_PARAGRAPH_ALIGNMENT.LEFT
        run = p.add_run()
        run.text = text
        self._style_run(run, font, color)

    # ------------------------------------------------------------------------------------ charts --
    def _add_chart(self, slide: Any, element: ChartElement, box: Box, number: int) -> None:
        kind = element.chart_type
        is_pie = kind in {"pie", "doughnut"}
        series = element.series[:1] if is_pie else element.series
        if is_pie and len(element.series) > 1:
            self._warn(number, f"{kind} charts show one series; extra series dropped")

        n = len(element.categories)
        padded: list[tuple[str, list[float | None]]] = []
        for s in series:
            if len(s.values) != n:
                self._warn(number, f"series '{s.name}' had {len(s.values)} values for {n} categories")
            padded.append((s.name, (list(s.values) + [None] * n)[:n]))
        all_values = [v for _, values in padded for v in values if v is not None]
        integral = all(float(v).is_integer() for v in all_values)
        data = CategoryChartData(number_format="#,##0" if integral else "#,##0.0#")
        data.categories = element.categories
        for name, values in padded:
            data.add_series(name, values)

        graphic = slide.shapes.add_chart(CHART_TYPES[kind], box.left, box.top, box.width, box.height, data)
        chart = graphic.chart
        chart.font.name = self.fonts.body.name
        chart.font.size = Pt(12)
        chart.font.color.rgb = _rgb(self.colors.text)

        if element.title:
            chart.has_title = True
            tf = chart.chart_title.text_frame
            tf.text = element.title
            run = tf.paragraphs[0].runs[0]
            self._style_run(run, FontSpec(name=self.fonts.body.name, size=16, bold=True), self.colors.text)
        else:
            chart.has_title = False

        chart.has_legend = is_pie or len(series) > 1
        if chart.has_legend:
            chart.legend.position = XL_LEGEND_POSITION.BOTTOM
            chart.legend.include_in_layout = False

        palette = self.colors.series_palette()
        plot = chart.plots[0]
        if is_pie:
            for i, point in enumerate(plot.series[0].points):
                point.format.fill.solid()
                point.format.fill.fore_color.rgb = _rgb(palette[i % len(palette)])
            plot.has_data_labels = True
            labels = plot.data_labels
            labels.show_percentage = True
            labels.show_value = False
            labels.number_format = "0%"
            labels.number_format_is_linked = False
            labels.font.size = Pt(12)
            labels.font.color.rgb = _rgb(self.colors.text)
            if kind == "pie":  # outside labels stay readable regardless of slice color
                labels.position = XL_DATA_LABEL_POSITION.OUTSIDE_END
        else:
            for i, s in enumerate(plot.series):
                color = _rgb(palette[i % len(palette)])
                if kind == "line":
                    s.format.line.color.rgb = color
                    s.format.line.width = Pt(2.5)
                    s.smooth = False
                else:
                    s.format.fill.solid()
                    s.format.fill.fore_color.rgb = color
            if kind in {"bar", "column"}:
                plot.gap_width = 80
                if len(series) <= 2 and n <= 8:
                    plot.has_data_labels = True
                    plot.data_labels.font.size = Pt(10)
                    plot.data_labels.number_format = data.number_format
                    plot.data_labels.number_format_is_linked = False
                    plot.data_labels.position = XL_DATA_LABEL_POSITION.OUTSIDE_END
            if kind in {"bar", "stacked_bar"}:
                chart.category_axis.reverse_order = True  # first category on top, as people read
            value_axis = chart.value_axis
            value_axis.has_major_gridlines = True
            value_axis.major_gridlines.format.line.color.rgb = _rgb(self.colors.surface_alt)
            value_axis.format.line.fill.background()
            value_axis.tick_labels.font.color.rgb = _rgb(self.colors.text_light)
            chart.category_axis.tick_labels.font.color.rgb = _rgb(self.colors.text)

    # ------------------------------------------------------------------------------------ images --
    def _add_image_placeholder(self, slide: Any, element: ImagePlaceholderElement, box: Box) -> None:
        shape = slide.shapes.add_shape(
            MSO_AUTO_SHAPE_TYPE.ROUNDED_RECTANGLE, box.left, box.top, box.width, box.height
        )
        shape.name = "Image Placeholder"
        shape.adjustments[0] = 0.04
        shape.fill.solid()
        shape.fill.fore_color.rgb = _rgb(self.colors.surface_alt)
        shape.line.color.rgb = _rgb(self.colors.accent2)
        shape.line.dash_style = MSO_LINE_DASH_STYLE.DASH
        shape.line.width = Pt(1.25)
        tf = shape.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = MSO_VERTICAL_ANCHOR.MIDDLE
        p = tf.paragraphs[0]
        p.alignment = PP_PARAGRAPH_ALIGNMENT.CENTER
        run = p.add_run()
        run.text = f"Image: {element.description}"
        self._style_run(
            run, FontSpec(name=self.fonts.body.name, size=14, italic=True), self.colors.text_light
        )


# --------------------------------------------------------------------------------------- helpers ----


def grid_boxes(area: Box, elements: list[Any]) -> list[Box]:
    """Split *area* into boxes for *elements* (1 = full, 2 = columns, more = 2-column grid)."""
    n = len(elements)
    if n == 0:
        return []
    if n == 1:
        return [area]
    if n == 2:
        first_text = isinstance(elements[0], TextElement) and not isinstance(elements[1], TextElement)
        second_text = isinstance(elements[1], TextElement) and not isinstance(elements[0], TextElement)
        ratio = 0.42 if first_text else 0.58 if second_text else 0.5
        left_w = int((area.width - GUTTER) * ratio)
        right_w = area.width - GUTTER - left_w
        return [
            Box(area.left, area.top, left_w, area.height),
            Box(area.left + left_w + GUTTER, area.top, right_w, area.height),
        ]
    cols = 2
    rows = math.ceil(n / cols)
    w = int((area.width - GUTTER) / cols)
    h = int((area.height - GUTTER * (rows - 1)) / rows)
    return [
        Box(area.left + (i % cols) * (w + GUTTER), area.top + (i // cols) * (h + GUTTER), w, h)
        for i in range(n)
    ]


def fit_font_size(
    lines: list[tuple[str, int]],
    width: int,
    height: int,
    base_pt: float,
    *,
    min_pt: float = 10,
    line_spacing: float = 1.25,
) -> float:
    """Estimate the largest font size (<= *base_pt*) at which *lines* fit into a width x height box."""
    width_pt, height_pt = Emu(width).pt, Emu(height).pt
    size = base_pt
    while size > min_pt:
        needed = 0.0
        for text, level in lines:
            usable = max(width_pt - 18 - level * 22, 40)
            chars_per_line = max(usable / (size * 0.5), 6)
            wrapped = max(1, math.ceil(len(text) / chars_per_line))
            needed += wrapped * size * line_spacing + 4
        if needed <= height_pt * 0.9:
            break
        size -= 1
    return max(size, min_pt)


def _format_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{int(value):,}" if value.is_integer() else f"{value:,.2f}".rstrip("0").rstrip(".")
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    return str(value)


def _set_bullet(paragraph: Any, color: str | None, *, level: int = 0, size_pt: float = 18) -> None:
    """Give *paragraph* a bullet glyph (or explicitly none when *color* is ``None``)."""
    pPr = paragraph._p.get_or_add_pPr()
    for tag in ("a:buClr", "a:buSzPct", "a:buFont", "a:buNone", "a:buChar", "a:buAutoNum"):
        for el in pPr.findall(qn(tag)):
            pPr.remove(el)
    insert_at = _bullet_insert_index(pPr)
    if color is None:
        pPr.set("indent", "0")
        pPr.set("marL", "0")
        pPr.insert(insert_at, etree.Element(qn("a:buNone")))
        return
    indent = int(Pt(size_pt * 0.9))
    pPr.set("marL", str(indent + level * int(Inches(0.3))))
    pPr.set("indent", str(-indent))
    bu_clr = etree.Element(qn("a:buClr"))
    etree.SubElement(bu_clr, qn("a:srgbClr"), val=color.lstrip("#").upper())
    bu_font = etree.Element(qn("a:buFont"), typeface="Arial")
    bu_char = etree.Element(qn("a:buChar"), char="•" if level == 0 else "–")
    for offset, el in enumerate((bu_clr, bu_font, bu_char)):
        pPr.insert(insert_at + offset, el)


def _bullet_insert_index(pPr: Any) -> int:
    """Bullet elements must follow lnSpc/spcBef/spcAft and precede tabLst/defRPr/extLst."""
    preceding = {qn("a:lnSpc"), qn("a:spcBef"), qn("a:spcAft")}
    index = 0
    for i, child in enumerate(pPr):
        if child.tag in preceding:
            index = i + 1
    return index
