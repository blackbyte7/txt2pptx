import json
from typing import Optional, Dict, Any, List
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser, JsonOutputParser, PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_core.retrievers import BaseRetriever
from log_config.logging_config import logger
from app.rag import EnhancedRAG


class BulletPointInput(BaseModel):
    """Input schema for the Bullet_Points_Generator tool."""
    content: str = Field(description="The raw text content to be structured into a presentation.")
    style: str = Field(
        description="The desired conceptual style for the presentation (e.g., Professional, Creative). Influences tone and structure.")
    template_name: str = Field(
        description="The name of the visual template being used (e.g., professional, creative). Should be included in the output.")
    max_slides: Optional[int] = Field(default=15, description="Suggestive maximum number of slides to generate.")
    max_points_per_slide: Optional[int] = Field(default=7,
                                                description="Suggestive maximum number of bullet points per slide.")
    min_points_per_slide: Optional[int] = Field(default=2,
                                                description="Suggestive minimum number of bullet points per slide.")


class QualityCheckInput(BaseModel):
    """Input schema for the Presentation_Quality_Checker tool."""
    presentation_structure: Dict[str, Any] = Field(
        description="The structured presentation JSON outline to be analyzed.")
    target_audience: Optional[str] = Field(default="General Audience",
                                           description="The intended audience for the presentation.")
    time_limit_minutes: Optional[int] = Field(default=None,
                                              description="An optional time limit for the presentation in minutes.")


# --- Output Schemas (for PydanticOutputParser) ---
class SlideDesignElements(BaseModel):
    layout: Optional[str] = Field(default="content",
                                  description="Suggested layout key (e.g., title_content, two_content, comparison, title_only) based on the template and documentation context.")
    visual_elements: Optional[List[str]] = Field(default=None,
                                                 description="Placeholder for future image/chart suggestions.")


class SlideStructure(BaseModel):
    slide_number: int = Field(description="Sequential slide number starting from 1.")
    slide_type: str = Field(default="content",
                            description="Type of slide (e.g., opening, content, closing, section_header).")
    title: str = Field(description="Concise and engaging title for the slide.")
    bullet_points: List[str] = Field(default_factory=list,
                                     description="List of key bullet points for the slide content. Keep points concise.")
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


# --- Prompts ---

BULLET_POINTS_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an expert presentation designer using python-pptx concepts. Your task is to transform the given raw text content into a structured, engaging presentation outline in JSON format.

Adhere strictly to the output JSON schema provided.

Guidelines:
- Analyze the input text and identify key themes, sections, and points.
- Structure the content logically across multiple slides (aim for {min_slides}-{max_slides} slides unless content dictates otherwise).
- Create concise, impactful titles for each slide.
- Generate clear and concise bullet points (aim for {min_points}-{max_points} per slide). Avoid overly long sentences.
- Determine an appropriate `slide_type` for each slide (e.g., 'opening', 'content', 'section_header', 'closing').
- Suggest a suitable `layout` key within `design_elements` based on the slide's content and type (e.g., 'title_slide', 'title_content', 'two_content', 'comparison', 'title_only'). **Use the provided documentation context to inform your layout suggestions where applicable.**
- Optionally add brief `speaker_notes` for context or delivery cues.
- Populate the `metadata` section, including the `presentation_style` and `template_name` provided in the input. Estimate duration based on slide count (approx. 1-2 min/slide).
- Ensure the final output is a single, valid JSON object conforming to the PresentationStructureOutput schema, with no extra text before or after.

Input Details:
- Content Style Guideline: {style}
- Visual Template Name: {template_name}
- Raw Content is provided by the user.

**Consider the following context from python-pptx documentation when deciding on slide structures and suggesting layouts, if relevant:**
<documentation_context>
{context}
</documentation_context>

Output Format Instructions: {format_instructions}
"""),
    ("user", "Raw Content:\n```\n{content}\n```")
])

QUALITY_CHECK_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a presentation quality assurance expert. Analyze the provided presentation structure JSON based on clarity, flow, engagement, and suitability for the target audience and time limit.

Evaluate these aspects:
1.  **Content Clarity & Flow:** Is the information presented logically? Is it easy to understand? Is there a clear narrative arc (opening, body, closing)?
2.  **Slide Structure:** Are titles clear? Are there too many/too few bullet points per slide? Is the content per slide appropriate? Are suggested layouts reasonable?
3.  **Audience Engagement:** Is the structure likely to keep the '{audience}' engaged? Is the complexity appropriate?
4.  **Time Management:** Based on the number of slides and content density, is it feasible within the {time_limit} minute limit (if provided)? Estimate time if no limit given.
5.  **Overall Effectiveness:** Does the structure effectively convey the core message?

Provide your analysis in a JSON format conforming to the QualityAnalysisOutput schema. Be specific and constructive in your feedback.

Output Format Instructions: {format_instructions}
"""),
    ("user", "Presentation Structure JSON:\n```json\n{structure}\n```")
])


# --- Tool Implementation Functions ---

def create_bullet_points_tool(
        input_data: BulletPointInput,
        llm: BaseChatModel,
        retriever: Optional[BaseRetriever],
        config: Optional[Dict] = None
) -> str:
    """
    Creates a structured presentation outline (JSON) from text content using an LLM,
    optionally enhanced with RAG context from python-pptx documentation.
    This function contains the core logic for the 'Bullet_Points_Generator' tool.
    """
    logger.info(
        f"Executing create_bullet_points_tool for style '{input_data.style}', template '{input_data.template_name}'.")
    try:
        # --- RAG Integration ---
        context = "No specific documentation context available."
        if retriever:
            try:
                query = (f"Best practices for python-pptx slide layouts and structuring content for "
                         f"a {input_data.style} presentation covering topics like: {input_data.content[:250]}...")
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

        json_output = response.json(indent=2)
        logger.info("Successfully generated presentation structure JSON.")
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
    Analyzes presentation structure JSON for quality and provides feedback (JSON).
    This function contains the core logic for the 'Presentation_Quality_Checker' tool.
    """
    logger.info(f"Executing create_quality_check_tool for audience '{input_data.target_audience}'.")
    try:
        parser = PydanticOutputParser(pydantic_object=QualityAnalysisOutput)

        try:
            structure_str = json.dumps(input_data.presentation_structure, indent=2)
        except TypeError:
            structure_str = str(input_data.presentation_structure)

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


__all__ = [
    'BulletPointInput',
    'QualityCheckInput',
    'PresentationStructureOutput',
    'QualityAnalysisOutput',
    'create_bullet_points_tool',
    'create_quality_check_tool'
]
