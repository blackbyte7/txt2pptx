"""Fast, deterministic content checks for outlines (no LLM required)."""

from __future__ import annotations

from txt2pptx.schemas import (
    AnalysisReport,
    ChartElement,
    PresentationOutline,
    TableElement,
    TextElement,
)


class ContentAnalyzer:
    def __init__(
        self,
        max_bullets: int = 6,
        max_words_per_bullet: int = 18,
        max_title_words: int = 10,
        max_elements: int = 3,
        max_table_rows: int = 10,
    ):
        self.max_bullets = max_bullets
        self.max_words_per_bullet = max_words_per_bullet
        self.max_title_words = max_title_words
        self.max_elements = max_elements
        self.max_table_rows = max_table_rows

    def analyze(self, outline: PresentationOutline) -> AnalysisReport:
        report = AnalysisReport()
        slides = outline.slides
        if len(slides) == 1:
            report.suggestions.append("Single-slide deck: consider adding an opening and a closing slide.")
        if len(slides) > 25:
            report.warnings.append(f"{len(slides)} slides is long; consider trimming or splitting the deck.")
        if slides[0].slide_type != "title":
            report.suggestions.append("Slide 1: start with a title slide.")
        if len(slides) > 3 and slides[-1].slide_type != "closing":
            report.suggestions.append(f"Slide {len(slides)}: end with a closing/summary slide.")

        seen_titles: dict[str, int] = {}
        for number, slide in enumerate(slides, start=1):
            prefix = f"Slide {number}"
            title_words = len(slide.title.split())
            if not slide.title:
                report.warnings.append(f"{prefix}: missing title.")
            elif title_words > self.max_title_words:
                report.suggestions.append(f"{prefix}: title has {title_words} words; shorten it.")
            key = slide.title.lower()
            if key and key in seen_titles:
                report.suggestions.append(f"{prefix}: same title as slide {seen_titles[key]}.")
            seen_titles.setdefault(key, number)

            elements = slide.content_elements
            if len(elements) > self.max_elements:
                report.warnings.append(
                    f"{prefix}: {len(elements)} content elements; the slide will be crowded."
                )
            if not elements and slide.slide_type == "content":
                report.suggestions.append(f"{prefix}: content slide without content.")

            bullets = [b for e in elements if isinstance(e, TextElement) for b in e.bullet_points]
            if len(bullets) > self.max_bullets:
                report.warnings.append(
                    f"{prefix}: {len(bullets)} bullets (> {self.max_bullets}); split or summarize."
                )
            for i, bullet in enumerate(bullets, start=1):
                words = len(bullet.split())
                if words > self.max_words_per_bullet:
                    report.suggestions.append(f"{prefix}, bullet {i}: {words} words; tighten the wording.")

            for element in elements:
                if isinstance(element, TableElement) and len(element.rows) > self.max_table_rows:
                    report.warnings.append(
                        f"{prefix}: table has {len(element.rows)} rows; consider a chart or an appendix."
                    )
                if isinstance(element, ChartElement):
                    n = len(element.categories)
                    for series in element.series:
                        if len(series.values) != n:
                            report.warnings.append(
                                f"{prefix}: chart series '{series.name}' has {len(series.values)} values "
                                f"for {n} categories."
                            )
                    if element.chart_type in {"pie", "doughnut"} and n > 7:
                        report.suggestions.append(
                            f"{prefix}: {n} pie slices are hard to read; use a bar chart."
                        )
        return report
