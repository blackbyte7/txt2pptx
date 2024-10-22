import ast
from pathlib import Path
from typing import Optional, Dict, List, Any

from langchain_anthropic import ChatAnthropic
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from langchain_core.runnables import RunnableConfig, RunnablePassthrough
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from log_config.logging_config import logger
from templates.templates import PresentationTemplates
from .rag import EnhancedRAG

# Cache directory for vector stores (make sure this directory exists)
CACHE_DIR = Path("cache/vector_stores")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


class BulletPointInput(BaseModel):
    content: str = Field(description="The content to be converted into bullet points.")
    style: str = Field(description="The desired style for the presentation.")
    max_points_per_slide: Optional[int] = Field(default=7, description="Maximum number of bullet points per slide.")
    min_points_per_slide: Optional[int] = Field(default=3, description="Minimum number of bullet points per slide.")


class CodeGenerationInput(BaseModel):
    presentation_structure: Dict = Field(description="The structured outline of the presentation.")
    style_requirements: Dict = Field(description="Specific style guidelines for the presentation.")
    include_animations: bool = Field(default=True, description="Whether to include animations in the presentation.")


class QualityCheckInput(BaseModel):
    presentation_structure: Dict = Field(description="The structured outline of the presentation.")
    target_audience: str = Field(description="The intended audience for the presentation.")
    time_limit: Optional[int] = Field(default=None, description="The time limit for the presentation in minutes.")


BULLET_POINTS_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """As a presentation structure expert, create an engaging presentation outline.

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
    {{
        "metadata": {{
            "estimated_duration": "minutes",
            "target_audience": "description",
            "complexity_level": "beginner|intermediate|advanced"
        }},
        "slides": [
            {{
                "slide_number": int,
                "slide_type": "opening|content|closing",
                "title": "string",
                "bullet_points": ["string"],
                "design_elements": {{
                    "layout": "string",
                    "visual_elements": ["string"],
                    "transitions": "string"
                }},
                "speaker_notes": "string"
            }}
        ]
    }}
    """),
    ("user", "Content: {content}\nStyle: {style}")
])

PPTX_CODE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """As a python-pptx expert, create professional presentation code.

    Requirements:
    1. Use object-oriented design patterns
    2. Implement error handling and log_config
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
    """),
    ("user",
     """Presentation Structure: {structure}\nStyle Requirements: {style}\nInclude Animations: {animations}\n\nPython-PPTX Context: {context}""")
])

QUALITY_CHECK_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """As a presentation quality assurance expert, analyze this presentation structure.

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
    """),
    ("user", "Structure: {structure}\nTarget Audience: {audience}\nTime Limit: {time_limit} minutes")
])


def get_llm(llm_provider: str, api_key: str):
    """Helper function to select and initialize LLM."""
    if llm_provider == "OpenAI":
        return ChatOpenAI(api_key=api_key, model="gpt-3.5-turbo-0125")
    elif llm_provider == "Anthropic":
        return ChatAnthropic(api_key=api_key, model_name="claude-3-opus-20240229")
    else:
        raise ValueError(f"Unsupported LLM provider: {llm_provider}")


def create_retrieval_chain(llm, retriever):
    """Create a retrieval-augmented generation chain."""
    return (
            {"context": retriever, "question": RunnablePassthrough()}
            | RunnablePassthrough.assign(context=lambda x: x["context"])
            | PPTX_CODE_PROMPT
            | llm
            | StrOutputParser()
    )


@tool("Bullet_Points_Generator", args_schema=BulletPointInput, return_direct=True)
def create_bullet_points_tool(
        input_data: BulletPointInput,
        llm_provider: str,
        api_key: str,
        config: Optional[RunnableConfig] = None
) -> Dict:
    """Creates structured presentation outlines with detailed slide specifications."""
    try:
        llm = get_llm(llm_provider, api_key)

        prompt = BULLET_POINTS_PROMPT.format(
            content=input_data.content,
            style=input_data.style,
            max_points=input_data.max_points_per_slide,
            min_points=input_data.min_points_per_slide
        )

        response = llm.invoke(prompt, config=config)
        return response.content
    except Exception as e:
        logger.error(f"Error creating bullet points: {str(e)}")
        raise


@tool("PPTX_Code_Generator", args_schema=CodeGenerationInput, return_direct=True)
def create_pptx_code_tool(
        input_data: CodeGenerationInput,
        llm_provider: str,
        api_key: str,
        documents: List,
        config: Optional[RunnableConfig] = None
) -> str:
    """Generates optimized python-pptx code with advanced features and RAG integration."""
    try:
        # Initialize RAG system
        rag = EnhancedRAG()
        vector_store = rag.create_vector_store(documents, "pptx_docs")
        templates = PresentationTemplates()

        # Initialize LLM
        llm = get_llm(llm_provider, api_key)

        # Create retrieval chain
        retriever = vector_store.as_retriever(search_kwargs={"k": 3})
        retrieval_chain = create_retrieval_chain(llm, retriever)

        # Get template information
        template_name = input_data.style_requirements.get("template", "professional")
        template = templates.get_template(template_name)

        # Generate specific queries
        queries = [
            f"How to create {input_data.style_requirements['layout']} slides in python-pptx?",
            f"How to implement {input_data.style_requirements.get('effects', 'basic')} animations in python-pptx?",
            f"How to set custom {input_data.style_requirements.get('design', 'default')} styles in python-pptx?"
        ]

        # Gather relevant documentation context using RAG
        contexts = [retrieval_chain.invoke(query) for query in queries]
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

        code = llm.invoke(prompt, config=config).content

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


@tool("Presentation_Quality_Checker", args_schema=QualityCheckInput, return_direct=True)
def create_quality_check_tool(
        input_data: QualityCheckInput,
        llm_provider: str,
        api_key: str,
        config: Optional[RunnableConfig] = None
) -> Dict:
    """Analyzes and provides improvements for presentation quality."""
    try:
        llm = get_llm(llm_provider, api_key)

        prompt = QUALITY_CHECK_PROMPT.format(
            structure=input_data.presentation_structure,
            audience=input_data.target_audience,
            time_limit=input_data.time_limit
        )

        response = llm.invoke(prompt, config=config)
        return response.content
    except Exception as e:
        logger.error(f"Error in quality check: {str(e)}")
        raise


def optimize_and_validate_code(code: str) -> str:
    """Validates and optimizes the generated Python code."""
    try:
        # Basic syntax check
        ast.parse(code)

        # Add standard imports (check if already present to avoid duplicates)
        imports = [
            "from pptx import Presentation",
            "from pptx.util import Inches, Pt",
            "from pptx.enum.shapes import MSO_SHAPE",
            "from pptx.dml.color import RGBColor",
            "import log_config"
        ]
        existing_imports = set()
        for node in ast.walk(ast.parse(code)):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for n in node.names:
                    existing_imports.add(n.name)

        new_imports = [imp for imp in imports if imp.split(" ")[[1]](
            "https://python.langchain.com/docs/integrations/chat/writer/") not in existing_imports]
        optimized_code = "\n".join(new_imports) + "\n"

        # Add log_config configuration (if not already present)
        if "log_config.basicConfig" not in code:
            optimized_code += "\nlog_config.basicConfig(level=log_config.INFO)\n"

        # Wrap in a function and add basic error handling
        optimized_code += "\ndef create_presentation():\n"
        for line in code.split('\n'):
            optimized_code += f"    {line}\n"  # Indent the code

        optimized_code += "\n    try:\n"
        optimized_code += "        prs = Presentation()  # Ensure a presentation is created\n"
        optimized_code += "        # Add your slide generation logic here\n"
        optimized_code += "        prs.save('output.pptx')  # Save the presentation\n"
        optimized_code += "        log_config.info('Presentation created successfully')\n"
        optimized_code += "        return prs\n"
        optimized_code += "    except Exception as e:\n"
        optimized_code += "        log_config.error(f'Error creating presentation: {str(e)}')\n"
        optimized_code += "        raise\n"

        return optimized_code

    except SyntaxError as e:
        logger.error(f"Syntax error in generated code: {e}")
        raise
    except Exception as e:
        logger.error(f"Error validating/optimizing code: {e}")
        raise


def test_generated_code(code: str) -> Dict[str, Any]:
    """Tests the generated code with sample data."""
    try:
        # Create a temporary environment for testing
        namespace = {}
        exec(code, namespace)

        # Test with minimal sample data
        if "create_presentation" in namespace:
            # Call create_presentation with no arguments
            presentation = namespace["create_presentation"]()

            if presentation:
                return {
                    "success": True,
                    "message": "Presentation created successfully"
                }
            else:
                return {
                    "success": False,
                    "error": "create_presentation function did not return a presentation object."
                }
        else:
            return {
                "success": False,
                "error": "create_presentation function not found in generated code."
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# Export the tools for easy import
__all__ = [
    'create_bullet_points_tool',
    'create_pptx_code_tool',
    'create_quality_check_tool',
    'BulletPointInput',
    'CodeGenerationInput',
    'QualityCheckInput'
]
