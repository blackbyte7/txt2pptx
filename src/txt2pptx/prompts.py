"""Prompt templates."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

OUTLINE_GUIDELINES = """\
Design rules for a professional slide deck:
- Start with a `title` slide (deck title + one-line subtitle) and end with a `closing` slide
  (key takeaways or call to action). Use `section` slides only to separate major parts of long decks.
- One idea per slide. Slide titles are short and specific (max ~8 words), ideally stating the insight.
- Bullets are concise phrases (max ~15 words), 3-6 per text element. Never paste paragraphs.
- Prefer at most two content elements per slide. Good pairings: text + chart, text + table, text + image.
- Use a `table` element when the source has structured, comparable data (max ~8 rows, ~5 columns).
- Use a `chart` element for trends (line), comparisons (column/bar), or shares of a whole (pie/doughnut).
  Every series must have exactly one numeric value per category. Never invent numbers that are not
  supported by the source text.
- Use an `image_placeholder` only where a real visual would clearly help (describe it precisely).
- Put supporting detail and talking points into `speaker_notes`, not on the slide.
- Write in the same language as the source content.
"""

OUTLINE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are an expert presentation designer. Turn the user's source material into a structured, "
            "render-ready slide deck outline.\n\n"
            + OUTLINE_GUIDELINES
            + "\nTarget: {min_slides}-{max_slides} slides. Tone/style: {style}. "
            "Audience: {audience}.\n\n"
            "Optional reference material about the rendering library (may be empty):\n"
            "<reference>\n{context}\n</reference>",
        ),
        ("human", "Source material:\n<source>\n{content}\n</source>"),
    ]
)

REVIEW_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a presentation coach. Review the slide deck outline (JSON) for clarity, narrative flow, "
            "audience engagement, appropriate choice of tables/charts, and timing. Audience: {audience}. "
            "Time limit: {time_limit}. Be specific and constructive; reference slide numbers.",
        ),
        ("human", "Outline:\n```json\n{outline}\n```"),
    ]
)

CODE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are an expert Python developer using the python-pptx library (v1.0).\n"
            "Write a self-contained script that builds a presentation for the user's content.\n\n"
            "Hard requirements:\n"
            "1. Only import from: pptx, math, datetime, json, typing, collections, enum. No other modules, "
            "no file or network access, no dunder attributes, no eval/exec/open/getattr.\n"
            "2. Create the deck as `prs = Presentation()` and set a 16:9 size "
            "(`prs.slide_width = Inches(13.333)`, `prs.slide_height = Inches(7.5)`).\n"
            "3. Do NOT call `prs.save()` - the runtime saves `prs` for you.\n"
            "4. Apply the template colors (hex strings -> `RGBColor.from_string('RRGGBB')`) and fonts.\n"
            "5. Use tables (`shapes.add_table`) and charts (`shapes.add_chart` with `CategoryChartData`) "
            "where the content has data.\n\n"
            + OUTLINE_GUIDELINES
            + "\nStyle: {style}\nTemplate (JSON): {template_json}\n\n"
            "Reference documentation (may be empty):\n<reference>\n{context}\n</reference>",
        ),
        ("human", "Content:\n<source>\n{content}\n</source>"),
    ]
)

CODE_REVIEW_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a security auditor. Decide whether this Python script ONLY builds a PowerPoint deck "
            "with python-pptx. Mark it unsafe if it touches the file system, network, environment, "
            "subprocesses, introspection/dunder tricks, or does anything unrelated to building slides.",
        ),
        ("human", "```python\n{code}\n```"),
    ]
)
