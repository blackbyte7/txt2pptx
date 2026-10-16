import ast
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set, Union

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.retrievers import BaseRetriever
from pydantic import BaseModel, Field, field_validator, model_validator

from app.rag import EnhancedRAG
from log_config.logging_config import logger

ALLOWED_CODE_IMPORTS: Set[str] = {
    "pptx",
    "os",
    "pathlib",
    "math",
    "datetime",
    "time",
    "uuid",
    "json",
    "typing",
    "collections",
}

FORBIDDEN_BUILTINS: Set[str] = {
    "eval",
    "exec",
    "compile",
    "open",
    "__import__",
    "input",
    "breakpoint",
    "globals",
    "locals",
    "getattr",
    "setattr",
    "delattr",
}

ALLOWED_OS_ATTRIBUTES: Set[str] = {"makedirs", "path", "sep", "linesep"}


def validate_python_code_ast(code: str) -> List[str]:
    """Statically validates generated Python code using AST to prevent RCE."""
    warnings: List[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as se:
        return [f"SyntaxError in generated code: {se}"]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_pkg = alias.name.split(".")[0]
                if root_pkg not in ALLOWED_CODE_IMPORTS:
                    warnings.append(f"Disallowed import module: '{alias.name}'")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root_pkg = node.module.split(".")[0]
                if root_pkg not in ALLOWED_CODE_IMPORTS:
                    warnings.append(f"Disallowed import from module: '{node.module}'")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in FORBIDDEN_BUILTINS:
                    warnings.append(f"Disallowed builtin function call: '{node.func.id}()'")
            elif isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "os":
                    if node.func.attr not in ALLOWED_OS_ATTRIBUTES:
                        warnings.append(f"Disallowed os call: 'os.{node.func.attr}'")
                if node.func.attr in {
                    "system",
                    "popen",
                    "spawn",
                    "execv",
                    "unlink",
                    "remove",
                    "rmdir",
                }:
                    warnings.append(f"Disallowed system/file operation: '{node.func.attr}'")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                warnings.append(f"Disallowed dunder attribute access: '{node.attr}'")

    return warnings


class BulletPointInput(BaseModel):
    """Input schema for the Bullet_Points_Generator tool."""

    content: str = Field(
        description="The raw text content to be structured into a presentation."
    )
    style: str = Field(
        description="The desired conceptual style for the presentation (e.g., Professional, Creative). Influences tone and structure."
    )
    template_name: str = Field(
        description="The name of the visual template being used (e.g., professional, creative). Should be included in the output."
    )
    max_slides: Optional[int] = Field(
        default=15, description="Suggestive maximum number of slides to generate."
    )
    max_points_per_slide: Optional[int] = Field(
        default=7,
        description="Suggestive maximum number of bullet points per text element.",
    )
    min_points_per_slide: Optional[int] = Field(
        default=2,
        description="Suggestive minimum number of bullet points per text element.",
    )


class QualityCheckInput(BaseModel):
    """Input schema for the Presentation_Quality_Checker tool."""

    presentation_structure: Dict[str, Any] = Field(
        description="The structured presentation JSON outline to be analyzed."
    )
    target_audience: Optional[str] = Field(
        default="General Audience",
        description="The intended audience for the presentation.",
    )
    time_limit_minutes: Optional[int] = Field(
        default=None,
        description="An optional time limit for the presentation in minutes.",
    )


class ElementPosition(BaseModel):
    left_inches: Optional[float] = Field(
        default=None, description="Position from left edge in inches."
    )
    top_inches: Optional[float] = Field(
        default=None, description="Position from top edge in inches."
    )
    width_inches: Optional[float] = Field(
        default=None, description="Width of the element in inches."
    )
    height_inches: Optional[float] = Field(
        default=None, description="Height of the element in inches."
    )


class TextElement(BaseModel):
    element_type: Literal["text"] = Field(
        default="text", description="Type identifier for this element."
    )
    title: Optional[str] = Field(
        default=None, description="Optional title specifically for this text block."
    )
    bullet_points: List[str] = Field(
        default_factory=list,
        description="List of key bullet points for this text element. Keep points concise.",
    )
    level: Optional[int] = Field(
        default=0, description="Indentation level for the text/bullets (0 is base)."
    )
    position: Optional[ElementPosition] = Field(
        default=None,
        description="Optional explicit position and size override for this element (in inches).",
    )


class TableElement(BaseModel):
    element_type: Literal["table"] = Field(
        default="table", description="Type identifier for this element."
    )
    title: Optional[str] = Field(default=None, description="Optional title for the table.")
    headers: List[str] = Field(description="List of header strings for the table columns.")
    rows: List[List[Any]] = Field(
        description="List of rows, where each row is a list of cell values (strings or numbers)."
    )
    position: Optional[ElementPosition] = Field(
        default=None, description="Optional position and size override."
    )


class ChartElement(BaseModel):
    element_type: Literal["chart"] = Field(
        default="chart", description="Type identifier for this element."
    )
    chart_type: str = Field(
        description="Type of chart (e.g., 'BAR_CLUSTERED', 'LINE', 'PIE'). Use python-pptx XL_CHART_TYPE names."
    )
    title: Optional[str] = Field(default=None, description="Title of the chart.")
    categories: List[str] = Field(
        description="List of category labels (X-axis for bar/line, slices for pie)."
    )
    series: Dict[str, List[Union[int, float]]] = Field(
        description="Dictionary where keys are series names and values are lists of data points corresponding to categories."
    )
    position: Optional[ElementPosition] = Field(
        default=None, description="Optional position and size override."
    )


class ImagePlaceholderElement(BaseModel):
    element_type: Literal["image_placeholder"] = Field(
        default="image_placeholder", description="Type identifier for this element."
    )
    description: str = Field(
        description="Description of the image content needed (e.g., 'logo', 'graph showing upward trend')."
    )
    position: Optional[ElementPosition] = Field(
        default=None, description="Optional position and size override."
    )


ContentType = Union[TextElement, TableElement, ChartElement, ImagePlaceholderElement]


class SlideDesignElements(BaseModel):
    layout: Optional[str] = Field(
        default="title_content",
        description="Suggested layout key (e.g., title_slide, title_content, two_content, blank) based on the template and documentation context.",
    )


class SlideStructure(BaseModel):
    slide_number: int = Field(description="Sequential slide number starting from 1.")
    slide_type: str = Field(
        default="content",
        description="Type of slide (e.g., opening, content, closing, section_header).",
    )
    title: str = Field(description="Concise and engaging title for the slide.")
    content_elements: List[ContentType] = Field(
        default_factory=list,
        description="List of content elements (text, tables, charts, image placeholders) for the slide body.",
    )
    design_elements: Optional[SlideDesignElements] = Field(
        default_factory=SlideDesignElements,
        description="Suggestions for layout and visuals, informed by documentation context.",
    )
    speaker_notes: Optional[str] = Field(
        default=None, description="Optional notes for the speaker for this slide."
    )


class PresentationMetadata(BaseModel):
    estimated_duration_minutes: Optional[int] = Field(
        default=None, description="Rough estimate of presentation duration in minutes."
    )
    target_audience: Optional[str] = Field(
        default="General Audience", description="Suggested target audience based on content."
    )
    complexity_level: Optional[str] = Field(
        default="intermediate",
        description="Suggested complexity level (e.g., beginner, intermediate, advanced).",
    )
    presentation_style: Optional[str] = Field(
        default="Professional", description="The conceptual style used (e.g., Professional)."
    )
    template_name: Optional[str] = Field(
        default="professional", description="The visual template name provided in the input."
    )


class PresentationStructureOutput(BaseModel):
    """Output schema for the structured presentation JSON."""

    metadata: PresentationMetadata = Field(description="Metadata about the presentation.")
    slides: List[SlideStructure] = Field(description="List of slide structures.")


class QualityAnalysisOutput(BaseModel):
    """Output schema for the quality analysis JSON."""

    overall_score: int = Field(
        description="Quality score (0-100) based on evaluation criteria."
    )
    clarity_flow_feedback: str = Field(
        description="Feedback on content clarity and logical flow."
    )
    engagement_feedback: str = Field(
        description="Feedback on potential audience engagement."
    )
    visual_suggestions: Optional[List[str]] = Field(
        default=None, description="Suggestions for visual improvements (layouts, elements)."
    )
    timing_feedback: Optional[str] = Field(
        default=None,
        description="Feedback related to the estimated time or provided limit.",
    )
    strengths: List[str] = Field(
        description="Positive aspects of the presentation structure."
    )
    areas_for_improvement: List[str] = Field(
        description="Specific suggestions for improvement."
    )


class GenerateCodeInput(BaseModel):
    """Input schema for the Code_Generator tool."""

    content: str = Field(
        description="The raw text content to be converted into python-pptx code."
    )
    style: str = Field(
        description="The desired conceptual style (e.g., Professional). Influences potential code choices."
    )
    template_name: str = Field(
        description="The name of the visual template (e.g., professional)."
    )
    template_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="The actual template data (colors, fonts, layouts) to be used in the generated code.",
    )


class GeneratedCodeOutput(BaseModel):
    """Output schema for the generated python-pptx code."""

    python_code: str = Field(
        description="The generated Python code using the python-pptx library."
    )
    output_filename: str = Field(
        description="The suggested filename (including .pptx extension) where the code will save the presentation."
    )

    @field_validator("output_filename")
    @classmethod
    def filename_must_end_with_pptx(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("output_filename must be a string")
        if not v.endswith(".pptx"):
            raise ValueError("output_filename must end with .pptx")
        return v


class CodeQualityCheckInput(BaseModel):
    """Input schema for the Code_Quality_Checker tool."""

    python_code: str = Field(
        description="The python-pptx code generated by the Code_Generator tool to be checked for safety and relevance."
    )


class CodeQualityAnalysisOutput(BaseModel):
    """Output schema for the code quality analysis."""

    is_safe: bool = Field(
        description="True if the code seems safe and relevant for pptx generation, False otherwise."
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="List of warnings or reasons why the code might be unsafe or irrelevant.",
    )
    assessment: str = Field(
        description="A brief overall assessment of the code quality check."
    )

    @model_validator(mode="after")
    def check_warnings_if_unsafe(self) -> "CodeQualityAnalysisOutput":
        """Adds a default warning if the code is marked unsafe but no specific warnings were provided."""
        if not isinstance(self.warnings, list):
            self.warnings = []
        if not self.is_safe and not self.warnings:
            self.warnings.append("Code marked as unsafe; no specific reasons provided.")
            logger.debug(
                "Added default unsafe warning to CodeQualityAnalysisOutput via model_validator."
            )
        return self


# --- Prompts ---

BULLET_POINTS_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are an expert presentation designer using python-pptx concepts. 
    Your task is to transform the given raw text content into a detailed, structured presentation outline in JSON format.

Adhere strictly to the output JSON schema provided (`PresentationStructureOutput` containing `SlideStructure` with `content_elements` list).

Guidelines:
- Analyze the input text to identify key themes, sections, data points, and potential visuals.
- Structure the content logically across multiple slides (aim for {min_slides}-{max_slides} slides).
- Create concise, impactful titles for each slide (`SlideStructure.title`).
- For each slide, populate the `content_elements` list. Decide the best element type(s) for the information:
    - Use `TextElement` for explanatory text, key takeaways, or lists. Generate clear bullet points (`bullet_points`, aim for {min_points}-{max_points} points).
    - Use `TableElement` if the text contains structured data suitable for a table. Extract `headers` and `rows`.
    - Use `ChartElement` if the text describes trends, comparisons, or proportions that can be visualized. 
      Choose an appropriate `chart_type` (e.g., 'BAR_CLUSTERED', 'LINE', 'PIE' from python-pptx XL_CHART_TYPE), define `categories` and `series` data.
    - Use `ImagePlaceholderElement` to indicate where a visual (like a logo, photo, or diagram) would be beneficial, providing a `description`.
- Assign an appropriate `slide_type` (e.g., 'opening', 'content', 'closing').
- Suggest a suitable `layout` key in `design_elements` (e.g., 'title_slide', 'title_content', 'two_content', 'blank'). 
**Use the provided documentation context to understand layout capabilities and how to best structure elements like tables or charts within standard layouts.** If a standard layout seems insufficient, suggest 'blank' and provide position hints in the element's `position` field if necessary.
- Optionally add brief `speaker_notes`.
- Populate the `metadata` section, including the `presentation_style` and `template_name` from input. Estimate duration (1-2 min/slide).
- Ensure the final output is a single, valid JSON object conforming to the PresentationStructureOutput schema. No extra text or markdown.

Input Details:
- Content Style Guideline: {style}
- Visual Template Name: {template_name}
- Raw Content is provided by the user.

**Leverage the following context from python-pptx documentation to inform your decisions on structuring content elements (especially tables and charts) and suggesting appropriate slide layouts:**
<documentation_context>
{context}
</documentation_context>

Output Format Instructions: {format_instructions}
""",
        ),
        ("user", "Raw Content:\n```\n{content}\n```"),
    ]
)

QUALITY_CHECK_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a presentation quality assurance expert. Analyze the provided presentation structure JSON based 
    on clarity, flow, engagement, appropriate use of elements (text, tables, charts), and suitability for the target audience and time limit.

Evaluate these aspects:
1.  **Content Clarity & Flow:** Is the information presented logically? Is there a clear narrative arc?
2.  **Slide Structure & Element Choice:** Are titles clear? Is the choice of text, tables, charts appropriate for the content on each slide? Is the complexity of elements suitable? Are suggested layouts reasonable?
3.  **Audience Engagement:** Is the structure likely to keep the '{audience}' engaged? Is the mix of elements effective?
4.  **Time Management:** Based on the number and complexity of slides/elements, is it feasible within the {time_limit} minute limit (if provided)? Estimate time if no limit given.
5.  **Overall Effectiveness:** Does the structure effectively convey the core message using the chosen elements?

Provide your analysis in a JSON format conforming to the QualityAnalysisOutput schema. Be specific and constructive.

Output Format Instructions: {format_instructions}
""",
        ),
        ("user", "Presentation Structure JSON:\n```json\n{structure}\n```"),
    ]
)

CODE_GENERATION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are an expert Python programmer specializing in the `python-pptx` library.
Your task is to generate Python code that creates a PowerPoint presentation based on the provided text content, style, and template data.

**Strict Requirements:**
1.  **Import Necessary Libraries:** Start the code with necessary imports (`from pptx import Presentation`, `from pptx.util import Inches, Pt`, `from pptx.dml.color import RGBColor`, `from pptx.enum.chart import XL_CHART_TYPE`, etc.). Only import from `pptx`, `os`, `pathlib`, `math`, `datetime`, `time`, `uuid`, `json`. Use `RGBColor.from_string` for hex colors.
2.  **Use Template Data:** Directly use the provided `template_data` dictionary (colors, fonts, layouts) to style the presentation elements. Note that `template_data['font']` values may be either strings or dictionaries with `'name'` and `'size'`.
3.  **Instantiate Presentation:** Create a `Presentation()` object.
4.  **Add Slides:** Iterate through logical sections of the input content and add slides using `prs.slides.add_slide(prs.slide_layouts[index])`. Choose the layout index based on `template_data['layouts']`.
5.  **Populate Slides:** Add titles, text (using bullet points in text frames), tables (`shapes.add_table`), charts (`shapes.add_chart`), or image placeholders (`shapes.add_shape` with text description) based on the content.
6.  **Apply Styling:** Apply fonts and colors from `template_data` to text runs, table cells, chart elements, etc. Handle potential errors if template keys are missing.
7.  **Saving:** The *last* line of your generated code MUST be `prs.save('{output_filename}')`.
8.  **Error Handling (Optional but Recommended):** Include basic error handling (e.g., try-except blocks around file operations or complex element additions).
9.  **Standalone Code:** The generated code must be runnable independently using `python-pptx`.
10. **Output Format:** Respond ONLY with the valid JSON object conforming to the `GeneratedCodeOutput` schema. Do NOT include any explanatory text or markdown formatting outside the JSON structure.

**Input Details:**
- Content Style Guideline: {style}
- Visual Template Name: {template_name}
- Template Data (JSON): {template_data_json}
- Raw Content: Provided by the user.

**Leverage the following context from python-pptx documentation to write accurate and effective code:**
<documentation_context>
{context}
</documentation_context>

Output Format Instructions: {format_instructions}
""",
        ),
        ("user", "Raw Content:\n```\n{content}\n```"),
    ]
)

CODE_QUALITY_CHECK_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a code security and relevance auditor specializing in `python-pptx`.
    Your task is to analyze the provided Python code snippet, intended for generating a PowerPoint presentation,
    and determine if it is safe and relevant for that specific purpose.

**Safety Checks:**
1.  **Imports:** Does it import suspicious libraries unrelated to presentation generation (e.g., `requests`, `subprocess`, `socket`, `os` beyond basic path manipulation)? Allow `pptx`, `uuid`, `json`, `time`, `pathlib`, `os` (for `makedirs`).
2.  **File Access:** Does it attempt to read/write files outside a designated 'exports' directory or access system files?
3.  **Network Access:** Does it try to make network connections?
4.  **External Execution:** Does it attempt to run shell commands or other external processes?
5.  **Data Handling:** Does it seem to exfiltrate data or perform unusually complex computations unrelated to placing content on slides?

**Relevance Checks:**
1.  **Core Purpose:** Is the code primarily focused on using `python-pptx` functions (`Presentation`, `add_slide`, `shapes.add_...`, styling, `prs.save`)?
2.  **Simplicity:** Is the code reasonably direct for presentation generation, or does it contain unnecessary complexity or obfuscation?

**Output:**
- Respond ONLY with a valid JSON object conforming to the `CodeQualityAnalysisOutput` schema.
- Set `is_safe` to `True` only if ALL safety and relevance checks pass. Otherwise, set it to `False`.
- If `is_safe` is `False`, provide specific reasons in the `warnings` list.
- Provide a brief `assessment` summarizing your findings.

Output Format Instructions: {format_instructions}
""",
        ),
        ("user", "Python Code to Analyze:\n```python\n{python_code}\n```"),
    ]
)


def create_bullet_points_tool(
    input_data: BulletPointInput,
    llm: BaseChatModel,
    retriever: Optional[BaseRetriever],
    config: Optional[Dict] = None,
) -> str:
    """
    Creates a detailed, structured presentation outline (JSON) from text content,
    including various element types (text, tables, charts), using an LLM and optional RAG context.
    This function contains the core logic for the 'Bullet_Points_Generator' tool.
    """
    logger.info(
        f"Executing create_bullet_points_tool for style '{input_data.style}', template '{input_data.template_name}'."
    )
    try:
        context = "No specific documentation context available."
        if retriever:
            try:
                query = (
                    f"How to structure python-pptx elements like text, tables (add_table), "
                    f"and charts (add_chart, XL_CHART_TYPE) within slide layouts for a {input_data.style} presentation. "
                    f"Content involves topics like: {input_data.content[:250]}..."
                )
                logger.debug(f"RAG Query for structuring: {query}")

                retrieved_docs = retriever.invoke(query)
                if retrieved_docs:
                    context = EnhancedRAG._format_docs(retrieved_docs)
                    logger.info(
                        f"Retrieved {len(retrieved_docs)} context chunks from documentation for structuring."
                    )
                    logger.debug(f"Retrieved Context Preview: {context[:300]}...")
                else:
                    logger.info("RAG retriever returned no documents for the query.")
                    context = "No relevant documentation context found for the query."
            except Exception as rag_err:
                logger.warning(
                    f"Failed to retrieve or format RAG context: {rag_err}", exc_info=True
                )
                context = "Error retrieving documentation context."
        else:
            logger.info("No retriever provided. Skipping RAG context retrieval.")

        parser = PydanticOutputParser(pydantic_object=PresentationStructureOutput)
        max_slides = input_data.max_slides or 15

        chain = (
            BULLET_POINTS_PROMPT.partial(
                format_instructions=parser.get_format_instructions(),
                min_slides=max(1, max_slides // 3),
                max_slides=max_slides,
                min_points=input_data.min_points_per_slide or 2,
                max_points=input_data.max_points_per_slide or 7,
                style=input_data.style,
                template_name=input_data.template_name,
                context=context,
            )
            | llm
            | parser
        )

        response: PresentationStructureOutput = chain.invoke(
            {"content": input_data.content}, config=config
        )

        for slide in response.slides:
            for i, element in enumerate(slide.content_elements):
                if not getattr(element, "element_type", None):
                    element_type_mapping = {
                        "TextElement": "text",
                        "TableElement": "table",
                        "ChartElement": "chart",
                        "ImagePlaceholderElement": "image_placeholder",
                    }
                    class_name = element.__class__.__name__
                    inferred_type = element_type_mapping.get(class_name)
                    if inferred_type:
                        logger.warning(
                            f"Slide {slide.slide_number}, Element {i}: Missing element_type, "
                            f"inferred as '{inferred_type}' from class {class_name}"
                        )
                        element.element_type = inferred_type  # type: ignore
                    else:
                        logger.error(
                            f"Slide {slide.slide_number}, Element {i}: Missing element_type "
                            f"and cannot infer from unknown class {class_name}"
                        )

        json_output = response.model_dump_json(indent=2)
        logger.info("Successfully generated detailed presentation structure JSON.")
        logger.debug(f"Generated Structure JSON (preview): {json_output[:500]}...")
        return json_output

    except Exception as e:
        logger.error(f"Error in create_bullet_points_tool: {e}", exc_info=True)
        raise ValueError(f"Failed to generate presentation structure: {e}") from e


def create_quality_check_tool(
    input_data: QualityCheckInput,
    llm: BaseChatModel,
    config: Optional[Dict] = None,
) -> str:
    """Analyzes detailed presentation structure JSON for quality and provides feedback (JSON)."""
    logger.info(f"Executing create_quality_check_tool for audience '{input_data.target_audience}'.")
    try:
        structure_str = json.dumps(input_data.presentation_structure, indent=2)
    except TypeError as te:
        logger.error(f"Input presentation_structure is not JSON serializable: {te}")
        raise ValueError(f"Invalid presentation structure received for quality check: {te}") from te

    try:
        parser = PydanticOutputParser(pydantic_object=QualityAnalysisOutput)
        chain = (
            QUALITY_CHECK_PROMPT.partial(
                format_instructions=parser.get_format_instructions(),
                audience=input_data.target_audience,
                time_limit=(
                    input_data.time_limit_minutes
                    if input_data.time_limit_minutes
                    else "Not specified"
                ),
            )
            | llm
            | parser
        )

        response: QualityAnalysisOutput = chain.invoke({"structure": structure_str}, config=config)
        return response.model_dump_json(indent=2)

    except Exception as e:
        logger.error(f"Error in create_quality_check_tool: {e}", exc_info=True)
        raise ValueError(f"Failed to perform quality analysis: {e}") from e


def create_code_generation_tool(
    input_data: GenerateCodeInput,
    llm: BaseChatModel,
    retriever: Optional[BaseRetriever],
    config: Optional[Dict] = None,
) -> str:
    """Generates python-pptx code to create a presentation based on text content and template data."""
    logger.info(
        f"Executing create_code_generation_tool for style '{input_data.style}', template '{input_data.template_name}'."
    )
    try:
        context = "No specific documentation context available."
        if retriever:
            try:
                query = (
                    f"python-pptx code examples for slides, text, tables, charts, RGBColor.from_string: "
                    f"{input_data.content[:250]}"
                )
                retrieved_docs = retriever.invoke(query)
                if retrieved_docs:
                    context = EnhancedRAG._format_docs(retrieved_docs)
            except Exception as rag_err:
                logger.warning(f"Failed to retrieve RAG context for code gen: {rag_err}")
                context = "Error retrieving documentation context."

        parser = PydanticOutputParser(pydantic_object=GeneratedCodeOutput)
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        suggested_filename = f"generated_code_{timestamp}_{unique_id}.pptx"

        try:
            template_data_json_str = json.dumps(input_data.template_data, indent=2)
        except TypeError:
            template_data_json_str = json.dumps({"name": input_data.template_name})

        chain = (
            CODE_GENERATION_PROMPT.partial(
                format_instructions=parser.get_format_instructions(),
                style=input_data.style,
                template_name=input_data.template_name,
                template_data_json=template_data_json_str,
                context=context,
                output_filename=suggested_filename,
            )
            | llm
            | parser
        )

        response: GeneratedCodeOutput = chain.invoke(
            {"content": input_data.content}, config=config
        )

        safe_filename = Path(response.output_filename).name
        save_dir = Path("exports")
        output_path_in_code = save_dir / safe_filename
        replacement_stmt = (
            f"import os; os.makedirs('exports', exist_ok=True); "
            f"prs.save(r'{output_path_in_code}')"
        )

        if re.search(r"\.save\s*\([^)]+\)", response.python_code):
            response.python_code = re.sub(
                r"[a-zA-Z_][a-zA-Z0-9_]*\.save\s*\([^)]+\)",
                replacement_stmt,
                response.python_code,
                count=1,
            )
        else:
            response.python_code = f"{response.python_code.rstrip()}\n{replacement_stmt}\n"

        response.output_filename = str(output_path_in_code)
        return response.model_dump_json(indent=2)

    except Exception as e:
        logger.error(f"Error in create_code_generation_tool: {e}", exc_info=True)
        raise ValueError(f"Failed to generate python-pptx code: {e}") from e


def create_code_quality_check_tool(
    input_data: CodeQualityCheckInput,
    llm: BaseChatModel,
    config: Optional[Dict] = None,
) -> str:
    """Analyzes generated python-pptx code for safety using static AST checks and LLM verification."""
    logger.info("Executing create_code_quality_check_tool.")
    ast_warnings = validate_python_code_ast(input_data.python_code)
    if ast_warnings:
        logger.warning(f"Static AST security check rejected generated code: {ast_warnings}")
        return CodeQualityAnalysisOutput(
            is_safe=False,
            warnings=ast_warnings,
            assessment="Code failed static AST security validation.",
        ).model_dump_json(indent=2)

    try:
        parser = PydanticOutputParser(pydantic_object=CodeQualityAnalysisOutput)
        chain = (
            CODE_QUALITY_CHECK_PROMPT.partial(
                format_instructions=parser.get_format_instructions()
            )
            | llm
            | parser
        )

        response: CodeQualityAnalysisOutput = chain.invoke(
            {"python_code": input_data.python_code}, config=config
        )
        return response.model_dump_json(indent=2)

    except Exception as e:
        logger.error(f"Error in create_code_quality_check_tool: {e}", exc_info=True)
        return CodeQualityAnalysisOutput(
            is_safe=False,
            warnings=[f"Failed to perform code quality analysis: {e}"],
            assessment="Error during analysis.",
        ).model_dump_json(indent=2)


__all__ = [
    "BulletPointInput",
    "QualityCheckInput",
    "PresentationStructureOutput",
    "QualityAnalysisOutput",
    "TextElement",
    "TableElement",
    "ChartElement",
    "ImagePlaceholderElement",
    "GenerateCodeInput",
    "GeneratedCodeOutput",
    "CodeQualityCheckInput",
    "CodeQualityAnalysisOutput",
    "validate_python_code_ast",
    "create_bullet_points_tool",
    "create_quality_check_tool",
    "create_code_generation_tool",
    "create_code_quality_check_tool",
]
