import ast
from langchain.chains import RetrievalQA
from langchain_openai import OpenAI
from langchain_anthropic import Anthropic
from langchain.prompts import PromptTemplate
from langchain.schema import Document
from langchain.tools import StructuredTool
from pydantic import BaseModel
from typing import Optional
from typing import Dict, List, Any
from pathlib import Path
from templates.templates import PresentationTemplates
from logging.logging_config import logger
from .rag import EnhancedRAG

# Cache directory for vector stores
CACHE_DIR = Path("cache/vector_stores")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


class BulletPointInput(BaseModel):
    content: str
    style: str
    max_points_per_slide: Optional[int] = 7
    min_points_per_slide: Optional[int] = 3


class CodeGenerationInput(BaseModel):
    presentation_structure: Dict
    style_requirements: Dict
    include_animations: bool = True


class QualityCheckInput(BaseModel):
    presentation_structure: Dict
    target_audience: str
    time_limit: Optional[int] = None


BULLET_POINTS_PROMPT = PromptTemplate(
    input_variables=["content", "style", "max_points", "min_points"],
    template="""
    As a presentation structure expert, create an engaging presentation outline.

    Content: {content}
    Style: {style}
    Guidelines:
    - Create between {min_points} and {max_points} points per slide
    - Ensure logical flow and progression
    - Include engaging titles and transitions
    - Balance content density

    Consider these aspects:
    1. Opening impact
    2. Information hierarchy
    3. Visual flow
    4. Audience engagement
    5. Key takeaways

    Return a JSON structure with:
    {
        "metadata": {
            "estimated_duration": "minutes",
            "target_audience": "description",
            "complexity_level": "beginner|intermediate|advanced"
        },
        "slides": [
            {
                "slide_number": int,
                "slide_type": "opening|content|closing",
                "title": "string",
                "bullet_points": ["string"],
                "design_elements": {
                    "layout": "string",
                    "visual_elements": ["string"],
                    "transitions": "string"
                },
                "speaker_notes": "string"
            }
        ]
    }
    """
)

PPTX_CODE_PROMPT = PromptTemplate(
    input_variables=["structure", "style", "context", "animations"],
    template="""
    As a python-pptx expert, create professional presentation code.

    Presentation Structure: {structure}
    Style Requirements: {style}
    Include Animations: {animations}

    Python-PPTX Context:
    {context}

    Requirements:
    1. Use object-oriented design patterns
    2. Implement error handling and logging
    3. Create reusable slide templates
    4. Optimize performance for large presentations
    5. Include progress tracking

    Additional Features to Implement:
    1. Smart color scheme management
    2. Dynamic content scaling
    3. Custom shape generation
    4. Master slide templates
    5. Animation sequencing

    Return production-ready Python code with comments and docstrings.
    """
)

QUALITY_CHECK_PROMPT = PromptTemplate(
    input_variables=["structure", "audience", "time_limit"],
    template="""
    As a presentation quality assurance expert, analyze this presentation structure:

    Structure: {structure}
    Target Audience: {audience}
    Time Limit: {time_limit} minutes

    Evaluate these aspects:
    1. Content clarity and flow
    2. Visual balance
    3. Audience engagement
    4. Time management
    5. Message effectiveness

    Return a detailed analysis in JSON format with:
    - Quality score (0-100)
    - Specific improvements
    - Time estimates
    - Engagement predictions
    - Design recommendations
    """
)


def create_bullet_points_tool(style_params, llm_provider, api_key):
    def create_bullet_points(input_data: BulletPointInput) -> Dict:
        try:
            prompt = BULLET_POINTS_PROMPT.format(
                content=input_data.content,
                style=input_data.style,
                max_points=input_data.max_points_per_slide,
                min_points=input_data.min_points_per_slide
            )

            if llm_provider == "OpenAI":
                llm = OpenAI(api_key=api_key)
            elif llm_provider == "Anthropic":
                llm = Anthropic(api_key=api_key)
            else:
                raise ValueError(f"Unsupported LLM provider: {llm_provider}")

            response = llm(prompt)
            return response
        except Exception as e:
            print(f"Error creating bullet points: {str(e)}")
            raise

    return StructuredTool(
        name="Bullet_Points_Generator",
        description="Creates structured presentation outlines with detailed slide specifications",
        func=create_bullet_points,
        args_schema=BulletPointInput
    )


def create_pptx_code_tool(llm_provider: str, api_key: str, documents: List[Document]) -> StructuredTool:
    """Creates an enhanced structured tool for PPTX code generation with RAG integration."""

    try:
        # Initialize RAG system
        rag = EnhancedRAG()
        vector_store = rag.create_vector_store(documents, "pptx_docs")
        templates = PresentationTemplates()

        # Initialize LLM
        if llm_provider == "OpenAI":
            llm = OpenAI(api_key=api_key)
        elif llm_provider == "Anthropic":
            llm = Anthropic(api_key=api_key)
        else:
            raise ValueError(f"Unsupported LLM provider: {llm_provider}")

        # Create retrieval QA chain
        qa_chain = RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=vector_store.as_retriever(
                search_kwargs={"k": 3}
            )
        )

        def generate_pptx_code(input_data: CodeGenerationInput) -> str:
            try:
                # Get template information
                template_name = input_data.style_requirements.get("template", "professional")
                template = templates.get_template(template_name)

                # Generate specific queries based on the presentation requirements
                queries = [
                    f"How to create {input_data.style_requirements['layout']} slides in python-pptx?",
                    f"How to implement {input_data.style_requirements.get('effects', 'basic')} animations in python-pptx?",
                    f"How to set custom {input_data.style_requirements.get('design', 'default')} styles in python-pptx?"
                ]

                # Gather relevant documentation context using RAG
                contexts = []
                for query in queries:
                    context = qa_chain.run(query)
                    contexts.append(context)

                # Combine contexts with weightings based on relevance
                combined_context = "\n\n".join([
                    f"Context for {query}:\n{context}"
                    for query, context in zip(queries, contexts)
                ])

                # Generate code using enhanced prompt
                prompt = PPTX_CODE_PROMPT.format(
                    structure=input_data.presentation_structure,
                    style=input_data.style_requirements,
                    animations=input_data.include_animations,
                    context=combined_context,
                    template=template
                )

                code = llm(prompt)

                # Validate and optimize the generated code
                optimized_code = optimize_and_validate_code(code)

                # Test code generation with sample data
                test_result = test_generated_code(optimized_code)
                if not test_result["success"]:
                    raise ValueError(f"Code validation failed: {test_result['error']}")

                return optimized_code

            except Exception as e:
                logger.error(f"Error in generate_pptx_code: {str(e)}")
                raise

        return StructuredTool(
            name="Enhanced_PPTX_Code_Generator",
            description="Generates optimized python-pptx code with advanced features and RAG integration",
            func=generate_pptx_code,
            args_schema=CodeGenerationInput
        )

    except Exception as e:
        logger.error(f"Error creating PPTX code tool: {str(e)}")
        raise


def create_quality_check_tool(llm):
    """Creates a tool for presentation quality assurance."""

    def check_presentation_quality(input_data: QualityCheckInput) -> Dict:
        prompt = QUALITY_CHECK_PROMPT.format(
            structure=input_data.presentation_structure,
            audience=input_data.target_audience,
            time_limit=input_data.time_limit
        )

        response = llm(prompt)
        return response

    return StructuredTool(
        name="Presentation_Quality_Checker",
        description="Analyzes and provides improvements for presentation quality",
        func=check_presentation_quality,
        args_schema=QualityCheckInput
    )


def optimize_and_validate_code(code: str) -> str:
    """Validates and optimizes the generated Python code."""
    try:
        # Parse the code to check for syntax errors
        ast.parse(code)

        # Add performance optimizations
        optimized_code = []

        # Add imports
        optimized_code.append("from pptx import Presentation")
        optimized_code.append("from pptx.util import Inches, Pt")
        optimized_code.append("from pptx.enum.shapes import MSO_SHAPE")
        optimized_code.append("from pptx.dml.color import RGBColor")
        optimized_code.append("import logging")

        # Add logging configuration
        optimized_code.append("\nlogging.basicConfig(level=logging.INFO)")

        # Add the main code with progress tracking
        optimized_code.append("\ndef create_presentation():")
        optimized_code.append("    logging.info('Starting presentation creation')")
        optimized_code.append("    prs = Presentation()")

        # Add the original code with indentation
        for line in code.split('\n'):
            optimized_code.append(f"    {line}")

        # Add error handling and cleanup
        optimized_code.append("\ntry:")
        optimized_code.append("    presentation = create_presentation()")
        optimized_code.append("    logging.info('Presentation created successfully')")
        optimized_code.append("    return presentation")
        optimized_code.append("except Exception as e:")
        optimized_code.append("    logging.error(f'Error creating presentation: {str(e)}')")
        optimized_code.append("    raise")

        return "\n".join(optimized_code)

    except Exception as e:
        raise ValueError(f"Code validation failed: {str(e)}")


def test_generated_code(code: str) -> Dict[str, Any]:
    """Tests the generated code with sample data."""
    try:
        # Create a temporary environment for testing
        namespace = {}
        exec(code, namespace)

        # Test with minimal sample data
        sample_data = {
            "title": "Test Presentation",
            "slides": [
                {
                    "title": "Test Slide",
                    "content": ["Test bullet point"]
                }
            ]
        }

        # Try to create a sample presentation
        result = namespace["create_presentation"](sample_data)

        return {
            "success": True,
            "result": result
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
