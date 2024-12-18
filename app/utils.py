import time
from pathlib import Path
from typing import Any, List, Optional, Dict, Union
from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader,
    UnstructuredFileLoader
    # UnstructuredHTMLLoader,
    # UnstructuredWordDocumentLoader,
    # UnstructuredPowerPointLoader
)
from langchain_core.documents import Document
from app.pptx_generator import PPTXGenerator
from log_config.logging_config import logger

ALLOWED_EXTENSIONS = {'.pdf', '.txt', '.html', '.htm', '.docx', '.pptx', '.md'}


def load_supported_documents(file_path: Union[str, Path]) -> List[Document]:
    """
    Load documents from a supported file path using appropriate loaders.

    Args:
        file_path (Union[str, Path]): Path to the input file.

    Returns:
        List[Document]: Loaded documents.

    Raises:
        ValueError: If the file type is unsupported.
        FileNotFoundError: If the file does not exist.
        Exception: For other loading errors.
    """
    file_path = Path(file_path)
    logger.info(f"Attempting to load document: {file_path}")

    if not file_path.exists():
        logger.error(f"File not found: {file_path}")
        raise FileNotFoundError(f"Input file not found: {file_path}")

    file_extension = file_path.suffix.lower()

    if file_extension not in ALLOWED_EXTENSIONS:
        logger.error(f"Unsupported file format: {file_extension}")
        raise ValueError(
            f"Unsupported file format: {file_extension}. Supported formats: {', '.join(ALLOWED_EXTENSIONS)}")

    loader: Any = None
    documents: List[Document] = []

    try:
        if file_extension == '.pdf':
            loader = PyPDFLoader(str(file_path))
            documents = loader.load()
        elif file_extension == '.txt' or file_extension == '.md':
            try:
                logger.debug(f"Attempting to load {file_path} with UTF-8 encoding.")
                loader = TextLoader(str(file_path), encoding='utf-8')
                documents = loader.load()
                logger.debug("Successfully loaded with UTF-8.")
            except UnicodeDecodeError:
                logger.warning("UTF-8 decoding failed, trying 'latin-1' encoding for .txt/.md file.")
                loader = TextLoader(str(file_path), encoding='latin-1')
                documents = loader.load()
                logger.debug("Successfully loaded with Latin-1 fallback.")

        elif file_extension in ['.docx', '.pptx', '.html', '.htm']:
            loader = UnstructuredFileLoader(str(file_path), mode="elements")
            documents = loader.load()
        else:
            raise ValueError(f"Loader logic error: Unsupported extension {file_extension} passed checks.")

        logger.info(f"Successfully loaded {len(documents)} document parts from {file_path}")

        documents = [doc for doc in documents if doc.page_content and doc.page_content.strip()]
        if not documents and file_path.stat().st_size > 0:
            logger.warning(
                f"No content could be extracted from {file_path} after loading and filtering, although file has size > 0.")
        elif not documents:
            logger.info(f"File {file_path} resulted in no extracted content (likely empty or filtered).")

        return documents

    except ImportError as ie:
        logger.error(
            f"ImportError loading {file_path}: {ie}. Ensure all dependencies in requirements.txt are installed.")
        raise ImportError(f"Missing library required for {file_extension} files: {ie}") from ie
    except FileNotFoundError:
        raise
    except Exception as e:
        logger.error(f"Failed to load or parse {file_path}: {e}", exc_info=True)
        raise RuntimeError(f"Could not process input file {file_path}: {e}") from e


def generate_presentation(
        presentation_structure_json: Dict[str, Any],
        output_filename_base: str = "generated_presentation",
        output_dir: Union[str, Path] = "exports"
) -> Optional[str]:
    """
    Generates a .pptx file from the structured JSON using the safe PPTXGenerator.

    Args:
        presentation_structure_json (Dict[str, Any]): The structured JSON output from the agent.
        output_filename_base (str): The base name for the output file (without extension).
        output_dir (Union[str, Path]): The directory to save the output file.

    Returns:
        Optional[str]: Path to the generated presentation file, or None on failure.
    """
    progress = ProgressTracker()  # Track progress internally

    try:
        progress.update_progress('initializing_generator', "Setting up presentation generator...")
        template_data = presentation_structure_json.get("template_info")
        if not template_data:
            logger.warning("Template info not found in presentation structure. Using default generator settings.")
        generator = PPTXGenerator(template=template_data)

        progress.update_progress('generating_pptx', "Building PowerPoint slides...")
        presentation = generator.create_presentation_from_json(presentation_structure_json)

        if not presentation:
            raise RuntimeError("PPTXGenerator failed to create a presentation object.")

        progress.update_progress('saving', "Saving presentation file...")
        save_dir = Path(output_dir)
        save_dir.mkdir(parents=True, exist_ok=True)

        timestamp = time.strftime("%Y%m%d-%H%M%S")
        output_filename = f"{output_filename_base}_{timestamp}.pptx"
        output_path = save_dir / output_filename

        try:
            presentation.save(str(output_path))
            logger.info(f"Successfully generated and saved presentation: {output_path}")
            progress.update_progress('complete', "Presentation saved.")
            return str(output_path)
        except Exception as save_err:
            logger.error(f"Failed to save presentation to {output_path}: {save_err}", exc_info=True)
            raise RuntimeError(f"Failed to save presentation: {save_err}") from save_err

    except Exception as e:
        logger.error(f"Error in generate_presentation utility: {e}", exc_info=True)
        return None


def validate_input_file_path(file_path: Optional[Union[str, Path]]) -> bool:
    """
    Validates if the input file path string is not None and the file extension is allowed.
    Does NOT check if the file exists.
    """
    if not file_path:
        return False
    try:
        p = Path(file_path)
        return p.suffix.lower() in ALLOWED_EXTENSIONS
    except Exception:
        return False


class ProgressTracker:
    """A simple class to track and log progress steps."""

    def __init__(self):
        self.steps = {
            'start': 'Starting process',
            'loading': 'Loading input data',
            'initializing_agent': 'Initializing AI Agent',
            'processing': 'AI Processing Content',
            'generating_structure': 'AI Generating Presentation Structure',
            'analyzing': 'Analyzing Content Structure',
            'initializing_generator': 'Initializing Presentation Generator',
            'generating_pptx': 'Generating PowerPoint File',
            'saving': 'Saving Presentation',
            'exporting': 'Exporting to other formats',
            'complete': 'Process complete'
        }
        self.current_step_key = 'start'
        logger.debug("ProgressTracker initialized.")

    def update_progress(self, step_key: str, message: Optional[str] = None):
        """Update and log the current progress step."""
        if step_key not in self.steps:
            logger.warning(f"Unknown progress step key: {step_key}")
            return

        self.current_step_key = step_key
        log_message = self.steps[step_key]
        if message:
            log_message = f"{log_message}: {message}"

        logger.info(f"Progress: {log_message}")


__all__ = [
    'load_supported_documents',
    'generate_presentation',
    'validate_input_file_path',
    'ProgressTracker',
    'ALLOWED_EXTENSIONS'
]
