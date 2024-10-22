import json
import time
from pathlib import Path
from typing import Any, List, Optional
from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader,
    UnstructuredHTMLLoader,
    UnstructuredWordDocumentLoader,
    UnstructuredPowerPointLoader
)
from langchain_core.documents import Document
from langchain_core.runnables import RunnableConfig

from app.tools import create_pptx_code_tool
from log_config.logging_config import logger


def load_documentation(file_path: str) -> List[Document]:
    """
    Load documentation from a file path.

    Args:
        file_path (str): Path to the documentation file

    Returns:
        List[Document]: Loaded documents
    """
    try:
        loader = PyPDFLoader(file_path)
        documents = loader.load()
        return documents
    except Exception as e:
        logger.error(f"Error loading documentation: {str(e)}")
        raise


def generate_presentation(
        input_file: str,
        style: str,
        agent: Any,
        llm_provider: str,
        api_key: str,
        rag_system: Any,
        config: Optional[RunnableConfig] = None
) -> str:
    """
    Generate a presentation from an input file.

    Args:
        input_file (str): Path to the input file
        style (str): Presentation style
        agent (Any): Agent for processing content
        llm_provider (str): Language model provider
        api_key (str): API key for the language model
        rag_system (Any): Retrieval-augmented generation system
        config (Optional[RunnableConfig]): Runnable configuration

    Returns:
        str: Path to the generated presentation file
    """
    progress = ProgressTracker()

    try:
        if not validate_input_file(input_file):
            raise ValueError("Unsupported file format")

        progress.update_progress('loading')
        # Load the input file based on its format
        loader = get_document_loader(input_file)
        user_input = loader.load_and_split()[0].page_content

        # Run the agent with the user input and selected style
        progress.update_progress('processing')
        output = agent.run(user_input, style)

        # Generate the Python code
        progress.update_progress('generating')
        json_output = json.loads(output)

        # Use the code generation tool directly
        code_generation_input = {
            "presentation_structure": json_output,
            "style_requirements": {
                "template": style,
                "layout": "two_content",
                "effects": "basic",
                "design": "default"
            },
            "include_animations": True
        }

        python_code = create_pptx_code_tool(
            code_generation_input,
            llm_provider,
            api_key,
            rag_system,
            config
        )

        # Run the generated Python code
        progress.update_progress('saving')

        # Execute the generated code and save the presentation
        namespace = {}
        exec(python_code, namespace)
        presentation = namespace['create_presentation']()

        # Save the generated PowerPoint presentation
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        output_file = f"generated_presentation_{timestamp}.pptx"
        presentation.save(output_file)

        logger.info(f"Successfully generated presentation: {output_file}")
        return output_file

    except Exception as e:
        logger.error(f"Error in generate_presentation: {str(e)}")
        raise


def get_document_loader(file_path: str):
    """
    Select the appropriate document loader based on file extension.

    Args:
        file_path (str): Path to the document

    Returns:
        Document loader
    """
    file_extension = Path(file_path).suffix.lower()
    loaders = {
        '.pdf': PyPDFLoader,
        '.txt': TextLoader,
        '.html': UnstructuredHTMLLoader,
        '.htm': UnstructuredHTMLLoader,
        '.docx': UnstructuredWordDocumentLoader,
        '.pptx': UnstructuredPowerPointLoader
    }

    loader_class = loaders.get(file_extension)
    if not loader_class:
        raise ValueError(f"Unsupported file format: {file_extension}")

    return loader_class(file_path)


class ProgressTracker:
    """
    A class to track and log progress of presentation generation.
    """

    def __init__(self):
        """
        Initialize the progress tracker with predefined steps.
        """
        self.steps = {
            'loading': 'Loading input file',
            'processing': 'Processing content',
            'generating': 'Generating presentation',
            'saving': 'Saving presentation'
        }
        self.current_step = None

    def update_progress(self, step: str, message: Optional[str] = None):
        """
        Update and log the current progress step.

        Args:
            step (str): The current step in the process
            message (Optional[str]): Additional message to log
        """
        self.current_step = step
        if message:
            logger.info(f"{self.steps[step]}: {message}")
        else:
            logger.info(self.steps[step])


def validate_input_file(file_path: str) -> bool:
    """
    Validate the input file based on its extension.

    Args:
        file_path (str): Path to the input file

    Returns:
        bool: Whether the file extension is allowed
    """
    allowed_extensions = {'.pdf', '.txt', '.html', '.htm', '.docx', '.pptx'}
    return Path(file_path).suffix.lower() in allowed_extensions


# Export key functions and classes
__all__ = [
    'load_documentation',
    'generate_presentation',
    'validate_input_file',
    'ProgressTracker',
    'get_document_loader'
]


