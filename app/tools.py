from langchain.tools import Tool
from langchain.chains import RetrievalQA
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAI
from langchain_anthropic import Anthropic
from langchain.prompts import PromptTemplate
from langchain.text_splitter import RecursiveCharacterTextSplitter
from typing import Dict, List
import hashlib
from pathlib import Path

from templates.templates import PresentationTemplates
from .logging_config import logger
from .rag import EnhancedRAG


# Cache directory for vector stores
CACHE_DIR = Path("cache/vector_stores")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


BULLET_POINTS_PROMPT = PromptTemplate(
    input_variables=["style", "style_params", "user_input"],
    template="""
    Create a professional presentation structure from the following text.
    Style: {style}
    Available style parameters: {style_params}

    Guidelines:
    1. Create clear, concise bullet points
    2. Organize content logically
    3. Include appropriate transitions
    4. Limit to 5-7 bullet points per slide

    Text to process:
    {user_input}

    Return a JSON with the following structure:
    {{
        "pages": [
            {{
                "title": "Clear, engaging title",
                "bullet_points": ["Point 1", "Point 2"],
                "design": "Specific design details",
                "effects": "Transition effects",
                "style_params": ["Selected parameters"]
            }}
        ]
    }}
    """
)

PPTX_CODE_PROMPT = PromptTemplate(
    input_variables=["json_input", "context"],
    template="""
    Using the python-pptx library, generate production-ready Python code for the following presentation structure.

    Relevant documentation context:
    {context}

    Presentation structure:
    {json_input}

    Requirements:
    1. Include proper error handling
    2. Use best practices for python-pptx
    3. Implement all design elements and transitions
    4. Include comments for clarity
    """
)

def create_bullet_points_tool(style_params, llm_provider, api_key):
    def create_bullet_points(user_input, style):
        try:
            logger.info("Creating bullet points with style: %s", style)

            prompt = BULLET_POINTS_PROMPT.format(
                style=style,
                style_params=style_params,
                user_input=user_input
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

    tool = Tool(
        name="Create Bullet Points",
        func=create_bullet_points,
        description="Creates bullet points from the user input, organizes them into pages of a presentation, and"
                    " decides on the design and effects for each slide based on the chosen style."
    )
    return tool


def create_pptx_code_tool(documents, llm_provider, api_key):
    try:
        rag = EnhancedRAG()
        vector_store = rag.create_vector_store(documents, "pptx_docs")
        templates = PresentationTemplates()

        if llm_provider == "OpenAI":
            llm = OpenAI(api_key=api_key)
        elif llm_provider == "Anthropic":
            llm = Anthropic(api_key=api_key)
        else:
            raise ValueError(f"Unsupported LLM provider: {llm_provider}")

        # Create a retrieval QA chain
        qa_chain = RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=vector_store.as_retriever(
                search_kwargs={"k": 3}
            )
        )

        def generate_pptx_code(json_input: Dict) -> str:
            try:
                logger.info("Generating PPTX code")

                # Get template information
                template_name = json_input.get("style", "professional")
                template = templates.get_template(template_name)

                # Get relevant documentation context
                context = rag.get_relevant_context(
                    vector_store,
                    "How to create slides with specific layouts and styling in python-pptx?"
                )

                prompt = PPTX_CODE_PROMPT.format(
                    json_input=json_input,
                    context=context,
                    template=template
                )

                response = llm(prompt)

                # Validate the generated code can be parsed
                compile(response, '<string>', 'exec')
                return response

            except Exception as e:
                logger.error("Error in generate_pptx_code: %s", str(e))
                raise

        return Tool(
            name="Generate PPTX Code",
            func=generate_pptx_code,
            description="Generates Python code for creating PowerPoint presentations"
        )

    except Exception as e:
        logger.error("Error creating PPTX code tool: %s", str(e))
        raise
