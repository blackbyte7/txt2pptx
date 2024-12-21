import json
import time
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, List, Union, Literal
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.pydantic_v1 import BaseModel, Field, validator
from langchain_core.retrievers import BaseRetriever
from langchain_experimental.tools import PythonREPLTool

from app.rag import EnhancedRAG
from log_config.logging_config import logger


class BulletPointInput(BaseModel):
    """Input schema for the Bullet_Points_Generator tool."""
    content: str = Field(description="The raw text content to be structured into a presentation.")
    style: str = Field(
        description="The desired conceptual style for the presentation (e.g., Professional, Creative). Influences tone and structure.")
    template_name: str = Field(
        description="The name of the visual template being used (e.g., professional, creative). Should be included in the output.")
    max_slides: Optional[int] = Field(default=15, description="Suggestive maximum number of slides to generate.")
    max_points_per_slide: Optional[int] = Field(default=7,
                                                description="Suggestive maximum number of bullet points per text element.")
    min_points_per_slide: Optional[int] = Field(default=2,
                                                description="Suggestive minimum number of bullet points per text element.")


class QualityCheckInput(BaseModel):
    """Input schema for the Presentation_Quality_Checker tool."""
    presentation_structure: Dict[str, Any] = Field(
        description="The structured presentation JSON outline to be analyzed.")
    target_audience: Optional[str] = Field(default="General Audience",
                                           description="The intended audience for the presentation.")
    time_limit_minutes: Optional[int] = Field(default=None,
                                              description="An optional time limit for the presentation in minutes.")


class ElementPosition(BaseModel):
    left_inches: Optional[float] = Field(default=None, description="Position from left edge in inches.")
    top_inches: Optional[float] = Field(default=None, description="Position from top edge in inches.")
    width_inches: Optional[float] = Field(default=None, description="Width of the element in inches.")
    height_inches: Optional[float] = Field(default=None, description="Height of the element in inches.")


class TextElement(BaseModel):
    element_type: Literal["text"] = Field(default="text", description="Type identifier for this element.")
    # element_type: str = Field(default="text", description="Type identifier for this element.")
    title: Optional[str] = Field(default=None, description="Optional title specifically for this text block.")
    bullet_points: List[str] = Field(default_factory=list,
                                     description="List of key bullet points for this text element. Keep points concise.")
    level: Optional[int] = Field(default=0, description="Indentation level for the text/bullets (0 is base).")
    position: Optional[ElementPosition] = Field(default=None, description="Optional position and size override.")


class TableElement(BaseModel):
    element_type: str = Field(default="table", description="Type identifier for this element.")
    title: Optional[str] = Field(default=None, description="Optional title for the table.")
    headers: List[str] = Field(description="List of header strings for the table columns.")
    rows: List[List[Any]] = Field(
        description="List of rows, where each row is a list of cell values (strings or numbers).")
    position: Optional[ElementPosition] = Field(default=None, description="Optional position and size override.")
    # style_id: Optional[str] = Field(default=None, description="Optional table style ID (from pptx constants).")


class ChartElement(BaseModel):
    element_type: Literal["chart"] = Field(default="chart", description="Type identifier for this element.")
    # element_type: str = Field(default="chart", description="Type identifier for this element.")
    chart_type: str = Field(
        description="Type of chart (e.g., 'BAR_CLUSTERED', 'LINE', 'PIE'). Use python-pptx XL_CHART_TYPE names.")
    title: Optional[str] = Field(default=None, description="Title of the chart.")
    categories: List[str] = Field(description="List of category labels (X-axis for bar/line, slices for pie).")
    series: Dict[str, List[Union[int, float]]] = Field(
        description="Dictionary where keys are series names and values are lists of data points corresponding to categories.")
    position: Optional[ElementPosition] = Field(default=None, description="Optional position and size override.")


class ImagePlaceholderElement(BaseModel):
    element_type: Literal["image_placeholder"] = Field(default="image_placeholder",
                                                       description="Type identifier for this element.")
    # element_type: str = Field(default="image_placeholder", description="Type identifier for this element.")
    description: str = Field(
        description="Description of the image content needed (e.g., 'logo', 'graph showing upward trend').")
    position: Optional[ElementPosition] = Field(default=None, description="Optional position and size override.")


ContentType = Union[TextElement, TableElement, ChartElement, ImagePlaceholderElement]


class SlideDesignElements(BaseModel):
    layout: Optional[str] = Field(default="title_content",
                                  description="Suggested layout key (e.g., title_slide, title_content, two_content, blank) "
                                              "based on the template and documentation context.")
    # visual_elements: Optional[List[str]] = Field(default=None, description="Placeholder for future explicit visual suggestions.")


class SlideStructure(BaseModel):
    slide_number: int = Field(description="Sequential slide number starting from 1.")
    slide_type: str = Field(default="content",
                            description="Type of slide (e.g., opening, content, closing, section_header).")
    title: str = Field(description="Concise and engaging title for the slide.")
    content_elements: List[ContentType] = Field(
        description="List of content elements (text, tables, charts, image placeholders) for the slide body.")
    design_elements: Optional[SlideDesignElements] = Field(default_factory=SlideDesignElements,
                                                           description="Suggestions for layout and visuals, informed by documentation context.")
    speaker_notes: Optional[str] = Field(default=None, description="Optional notes for the speaker for this slide.")


class PresentationMetadata(BaseModel):
    estimated_duration_minutes: Optional[int] = Field(default=None,
                                                      description="Rough estimate of presentation duration in minutes.")
    target_audience: Optional[str] = Field(default="General Audience",
                                           description="Suggested target audience based on content.")
    complexity_level: Optional[str] = Field(default="intermediate",
                                            description="Suggested complexity level (e.g., beginner, intermediate, advanced).")
    presentation_style: Optional[str] = Field(description="The conceptual style used (e.g., Professional).")
    template_name: Optional[str] = Field(description="The visual template name provided in the input.")


class PresentationStructureOutput(BaseModel):
    """Output schema for the structured presentation JSON."""
    metadata: PresentationMetadata = Field(description="Metadata about the presentation.")
    slides: List[SlideStructure] = Field(description="List of slide structures.")


class QualityAnalysisOutput(BaseModel):
    """Output schema for the quality analysis JSON."""
    overall_score: int = Field(description="Quality score (0-100) based on evaluation criteria.")
    clarity_flow_feedback: str = Field(description="Feedback on content clarity and logical flow.")
    engagement_feedback: str = Field(description="Feedback on potential audience engagement.")
    visual_suggestions: Optional[List[str]] = Field(default=None,
                                                    description="Suggestions for visual improvements (layouts, elements).")
    timing_feedback: Optional[str] = Field(default=None,
                                           description="Feedback related to the estimated time or provided limit.")
    strengths: List[str] = Field(description="Positive aspects of the presentation structure.")
    areas_for_improvement: List[str] = Field(description="Specific suggestions for improvement.")


class GenerateCodeInput(BaseModel):
    """Input schema for the Code_Generator tool."""
    content: str = Field(description="The raw text content to be converted into python-pptx code.")
    style: str = Field(
        description="The desired conceptual style (e.g., Professional). Influences potential code choices.")
    template_name: str = Field(description="The name of the visual template (e.g., professional).")
    template_data: Dict[str, Any] = Field(
        description="The actual template data (colors, fonts, layouts) to be used in the generated code.")


class GeneratedCodeOutput(BaseModel):
    """Output schema for the generated python-pptx code."""
    python_code: str = Field(description="The generated Python code using the python-pptx library.")
    output_filename: str = Field(
        description="The suggested filename (including .pptx extension) where the code will save the presentation.")

    @validator('output_filename')
    def filename_must_end_with_pptx(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError('output_filename must be a string')
        if not v.endswith('.pptx'):
            raise ValueError('output_filename must end with .pptx')
        return v


# --- Prompts ---

BULLET_POINTS_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an expert presentation designer using python-pptx concepts. 
    Your task is to transform the given raw text content into a detailed, structured presentation outline in JSON format.

Adhere strictly to the output JSON schema provided (`PresentationStructureOutput` containing `SlideStructure` with `content_elements` list).

Guidelines:
- Analyze the input text to identify key themes, sections, data points, and potential visuals.
- Structure the content logically across multiple slides (aim for {min_slides}-{max_slides} slides).
- Create concise, impactful titles for each slide (`SlideStructure.title`).
- For each slide, populate the `content_elements` list. Decide the best element type(s) for the information:
    - Use `TextElement` for explanatory text, key takeaways, or lists. Generate clear bullet points (`bullet_points`).
    - Use `TableElement` if the text contains structured data suitable for a table. Extract `headers` and `rows`.
    - Use `ChartElement` if the text describes trends, comparisons, or proportions that can be visualized. 
      Choose an appropriate `chart_type` (e.g., 'BAR_CLUSTERED', 'LINE', 'PIE' from python-pptx XL_CHART_TYPE), define `categories` and `series` data.
    - Use `ImagePlaceholderElement` to indicate where a visual (like a logo, photo, or diagram) would be beneficial, providing a `description`.
- Assign an appropriate `slide_type` (e.g., 'opening', 'content', 'closing').
- Suggest a suitable `layout` key in `design_elements` (e.g., 'title_slide', 'title_content', 'two_content', 'blank'). 
**Use the provided documentation context to understand layout capabilities and how to best structure elements like tables or charts within standard layouts.
** If a standard layout seems insufficient, suggest 'blank' and provide position hints in the element's `position` field if necessary.
- Optionally add brief `speaker_notes`.
- Populate the `metadata` section, including the `presentation_style` and `template_name` from input. Estimate duration (1-2 min/slide).
- Ensure the final output is a single, valid JSON object conforming to the PresentationStructureOutput schema. No extra text or markdown.

Input Details:
- Content Style Guideline: {style}
- Visual Template Name: {template_name}
- Raw Content is provided by the user.

**Leverage the following context from python-pptx documentation to inform your decisions on structuring content elements 
(especially tables and charts) and suggesting appropriate slide layouts:**
<documentation_context>
{context}
</documentation_context>

Output Format Instructions: {format_instructions}
"""),
    ("user", "Raw Content:\n```\n{content}\n```")
])

QUALITY_CHECK_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a presentation quality assurance expert. Analyze the provided presentation structure JSON based 
    on clarity, flow, engagement, appropriate use of elements (text, tables, charts), and suitability for the target audience and time limit.

Evaluate these aspects:
1.  **Content Clarity & Flow:** Is the information presented logically? Is there a clear narrative arc?
2.  **Slide Structure & Element Choice:** Are titles clear? Is the choice of text, tables, charts appropriate for 
the content on each slide? Is the complexity of elements suitable? Are suggested layouts reasonable?
3.  **Audience Engagement:** Is the structure likely to keep the '{audience}' engaged? Is the mix of elements effective?
4.  **Time Management:** Based on the number and complexity of slides/elements, is it feasible within the {time_limit} 
minute limit (if provided)? Estimate time if no limit given.
5.  **Overall Effectiveness:** Does the structure effectively convey the core message using the chosen elements?

Provide your analysis in a JSON format conforming to the QualityAnalysisOutput schema. Be specific and constructive.

Output Format Instructions: {format_instructions}
"""),
    ("user", "Presentation Structure JSON:\n```json\n{structure}\n```")
])

CODE_GENERATION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an expert Python programmer specializing in the `python-pptx` library.
Your task is to generate Python code that creates a PowerPoint presentation based on the provided text content, style, and template data.

**Strict Requirements:**
1.  **Import Necessary Libraries:** Start the code with necessary imports (`from pptx import Presentation`, `from pptx.util import Inches, Pt`, `from pptx.dml.color import RGBColor`, `from pptx.enum.chart import XL_CHART_TYPE`, etc.). Use `RGBColor.from_string` for hex colors.
2.  **Use Template Data:** Directly use the provided `template_data` dictionary (colors, fonts, layouts) to style the presentation elements. Extract colors (`template_data['colors']`) and font names/sizes (`template_data['font']`) from it. Use `template_data['layouts']` to select slide layouts.
3.  **Instantiate Presentation:** Create a `Presentation()` object.
4.  **Add Slides:** Iterate through logical sections of the input content and add slides using `prs.slides.add_slide(prs.slide_layouts[index])`. Choose the layout index based on `template_data['layouts']`.
5.  **Populate Slides:** Add titles, text (using bullet points in text frames), tables (`shapes.add_table`), charts (`shapes.add_chart`), or image placeholders (`shapes.add_shape` with text description) based on the content. Use helper functions if needed for complex element creation.
6.  **Apply Styling:** Apply fonts and colors from `template_data` to text runs, table cells, chart elements, etc. Handle potential errors if template keys are missing.
7.  **Saving:** The *last* line of your generated code MUST be `prs.save('{output_filename}')`. You will determine a suitable filename based on the context.
8.  **Error Handling (Optional but Recommended):** Include basic error handling (e.g., try-except blocks around file operations or complex element additions).
9.  **Standalone Code:** The generated code must be runnable independently using `python-pptx`.
10. **Output Format:** Respond ONLY with the valid JSON object conforming to the `GeneratedCodeOutput` schema. Do NOT include any explanatory text, markdown formatting (like ```python), or comments outside the JSON structure or the Python code string itself.

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
"""),
    ("user", "Raw Content:\n```\n{content}\n```")
])


def create_bullet_points_tool(
        input_data: BulletPointInput,
        llm: BaseChatModel,
        retriever: Optional[BaseRetriever],
        config: Optional[Dict] = None
) -> str:
    """
    Creates a detailed, structured presentation outline (JSON) from text content,
    including various element types (text, tables, charts), using an LLM and optional RAG context.
    This function contains the core logic for the 'Bullet_Points_Generator' tool.
    """
    logger.info(
        f"Executing create_bullet_points_tool for style '{input_data.style}', template '{input_data.template_name}'.")
    try:
        context = "No specific documentation context available."
        if retriever:
            try:
                query = (f"How to structure python-pptx elements like text, tables (add_table), "
                         f"and charts (add_chart, XL_CHART_TYPE) within slide layouts for a {input_data.style} presentation. "
                         f"Content involves topics like: {input_data.content[:250]}...")
                logger.debug(f"RAG Query for structuring: {query}")

                retrieved_docs = retriever.invoke(query)
                if retrieved_docs:
                    context = EnhancedRAG._format_docs(retrieved_docs)
                    logger.info(f"Retrieved {len(retrieved_docs)} context chunks from documentation for structuring.")
                    logger.debug(f"Retrieved Context Preview: {context[:300]}...")
                else:
                    logger.info("RAG retriever returned no documents for the query.")
                    context = "No relevant documentation context found for the query."
            except Exception as rag_err:
                logger.warning(f"Failed to retrieve or format RAG context: {rag_err}", exc_info=True)
                context = "Error retrieving documentation context."
        else:
            logger.info("No retriever provided. Skipping RAG context retrieval.")

        parser = PydanticOutputParser(pydantic_object=PresentationStructureOutput)

        chain = (
                BULLET_POINTS_PROMPT.partial(
                    format_instructions=parser.get_format_instructions(),
                    min_slides=max(1, input_data.max_slides // 3),
                    max_slides=input_data.max_slides,
                    min_points=input_data.min_points_per_slide,
                    max_points=input_data.max_points_per_slide,
                    style=input_data.style,
                    template_name=input_data.template_name,
                    context=context
                )
                | llm
                | parser
        )

        response: PresentationStructureOutput = chain.invoke(
            {"content": input_data.content},
            config=config
        )

        for slide in response.slides:
            for i, element in enumerate(slide.content_elements):
                if not getattr(element, 'element_type', None):
                    element_type_mapping = {
                        "TextElement": "text",
                        "TableElement": "table",
                        "ChartElement": "chart",
                        "ImagePlaceholderElement": "image_placeholder"
                    }
                    class_name = element.__class__.__name__
                    inferred_type = element_type_mapping.get(class_name)
                    if inferred_type:
                        logger.warning(
                            f"Slide {slide.slide_number}, Element {i}: Missing element_type, inferred as '{inferred_type}' from class {class_name}")
                        element.element_type = inferred_type
                    else:
                        logger.error(
                            f"Slide {slide.slide_number}, Element {i}: Missing element_type and cannot infer from unknown class {class_name}")
                        # slide.content_elements[i] = TextElement(element_type="text", bullet_points=["Error: Invalid element type"])

        json_output = response.json(indent=2)
        logger.info("Successfully generated detailed presentation structure JSON.")
        logger.debug(f"Generated Structure JSON (preview): {json_output[:500]}...")
        return json_output

    except Exception as e:
        logger.error(f"Error in create_bullet_points_tool: {e}", exc_info=True)
        raise ValueError(f"Failed to generate presentation structure: {e}")


def create_quality_check_tool(
        input_data: QualityCheckInput,
        llm: BaseChatModel,
        config: Optional[Dict] = None
) -> str:
    """
    Analyzes detailed presentation structure JSON for quality and provides feedback (JSON).
    This function contains the core logic for the 'Presentation_Quality_Checker' tool.
    """
    logger.info(f"Executing create_quality_check_tool for audience '{input_data.target_audience}'.")
    try:
        parser = PydanticOutputParser(pydantic_object=QualityAnalysisOutput)

        try:
            structure_str = json.dumps(input_data.presentation_structure, indent=2)
        except TypeError as te:
            logger.error(f"Input presentation_structure is not JSON serializable: {te}")
            raise ValueError(f"Invalid presentation structure received for quality check: {te}")

        chain = (
                QUALITY_CHECK_PROMPT.partial(
                    format_instructions=parser.get_format_instructions(),
                    audience=input_data.target_audience,
                    time_limit=input_data.time_limit_minutes if input_data.time_limit_minutes else "Not specified"
                )
                | llm
                | parser
        )

        response: QualityAnalysisOutput = chain.invoke(
            {"structure": structure_str},
            config=config
        )

        json_output = response.json(indent=2)
        logger.info("Successfully generated quality analysis JSON.")
        logger.debug(f"Generated Analysis JSON (preview): {json_output[:500]}...")
        return json_output

    except Exception as e:
        logger.error(f"Error in create_quality_check_tool: {e}", exc_info=True)
        raise ValueError(f"Failed to perform quality analysis: {e}")


def create_code_generation_tool(
        input_data: GenerateCodeInput,
        llm: BaseChatModel,
        retriever: Optional[BaseRetriever],
        config: Optional[Dict] = None
) -> str:
    """
    Generates python-pptx code to create a presentation based on text content,
    style, template data, and optional RAG context.
    This function contains the core logic for the 'Code_Generator' tool.
    """
    logger.info(
        f"Executing create_code_generation_tool for style '{input_data.style}', template '{input_data.template_name}'.")
    try:
        context = "No specific documentation context available."
        if retriever:
            try:
                query = (
                    f"Generate python-pptx code examples for creating slides with text, tables, charts (like {input_data.style} style). "
                    f"Focus on using Presentation(), add_slide(), slide_layouts, shapes.add_textbox(), shapes.add_table(), "
                    f"shapes.add_chart(), font properties, RGBColor.from_string, and saving the presentation. "
                    f"Content summary: {input_data.content[:250]}...")
                logger.debug(f"RAG Query for code generation: {query}")

                retrieved_docs = retriever.invoke(query)
                if retrieved_docs:
                    context = EnhancedRAG._format_docs(retrieved_docs)
                    logger.info(
                        f"Retrieved {len(retrieved_docs)} context chunks from documentation for code generation.")
                    logger.debug(f"Retrieved Context Preview: {context[:300]}...")
                else:
                    logger.info("RAG retriever returned no documents for the code generation query.")
                    context = "No relevant documentation context found for the query."
            except Exception as rag_err:
                logger.warning(f"Failed to retrieve or format RAG context for code gen: {rag_err}", exc_info=True)
                context = "Error retrieving documentation context."
        else:
            logger.info("No retriever provided. Skipping RAG context retrieval for code gen.")

        parser = PydanticOutputParser(pydantic_object=GeneratedCodeOutput)

        timestamp = time.strftime("%Y%m%d-%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        suggested_filename = f"generated_code_{timestamp}_{unique_id}.pptx"

        try:
            template_data_json_str = json.dumps(input_data.template_data, indent=2)
        except TypeError as e:
            logger.error(f"Template data is not JSON serializable: {e}. Using basic representation.")
            template_data_json_str = json.dumps(
                {"name": input_data.template_name, "error": "Data not fully serializable"})

        chain = (
                CODE_GENERATION_PROMPT.partial(
                    format_instructions=parser.get_format_instructions(),
                    style=input_data.style,
                    template_name=input_data.template_name,
                    template_data_json=template_data_json_str,
                    context=context,
                    output_filename=suggested_filename
                )
                | llm
                | parser
        )

        response: GeneratedCodeOutput = chain.invoke(
            {"content": input_data.content},
            config=config
        )

        safe_filename = Path(response.output_filename).name
        save_dir = "exports"
        output_path_in_code = Path(save_dir) / safe_filename
        response.python_code = response.python_code.replace(
            f"prs.save('{response.output_filename}')",
            f"import os; os.makedirs('{save_dir}', exist_ok=True); prs.save(r'{str(output_path_in_code)}')",
            1
        )
        response.output_filename = str(output_path_in_code)

        json_output = response.json(indent=2)
        logger.info(f"Successfully generated python-pptx code. Expected output file: {response.output_filename}")
        logger.debug(f"Generated Code JSON: {json_output}")
        return json_output

    except Exception as e:
        logger.error(f"Error in create_code_generation_tool: {e}", exc_info=True)
        raise ValueError(f"Failed to generate python-pptx code: {e}")


__all__ = [
    'BulletPointInput',
    'QualityCheckInput',
    'PresentationStructureOutput',
    'QualityAnalysisOutput',
    'TextElement',
    'TableElement',
    'ChartElement',
    'ImagePlaceholderElement',
    'create_bullet_points_tool',
    'create_quality_check_tool',
    'create_code_generation_tool'
]
