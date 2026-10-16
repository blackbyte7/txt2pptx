import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader,
    UnstructuredFileLoader,
)
from langchain_core.documents import Document

from app.pptx_generator import PPTXGenerator
from log_config.logging_config import logger

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".html", ".htm", ".docx", ".pptx", ".md"}


def load_supported_documents(file_path: Union[str, Path]) -> List[Document]:
    """Loads documents from a supported file path using appropriate loaders."""
    file_path = Path(file_path)
    logger.info(f"Attempting to load document: {file_path}")

    if not file_path.exists():
        logger.error(f"File not found: {file_path}")
        raise FileNotFoundError(f"Input file not found: {file_path}")

    file_extension = file_path.suffix.lower()

    if file_extension not in ALLOWED_EXTENSIONS:
        logger.error(f"Unsupported file format: {file_extension}")
        raise ValueError(
            f"Unsupported file format: {file_extension}. Supported formats: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    try:
        if file_extension == ".pdf":
            loader = PyPDFLoader(str(file_path))
            documents = loader.load()
        elif file_extension in {".txt", ".md"}:
            try:
                loader = TextLoader(str(file_path), encoding="utf-8")
                documents = loader.load()
                logger.debug("Successfully loaded with UTF-8.")
            except UnicodeDecodeError:
                loader = TextLoader(str(file_path), encoding="latin-1")
                documents = loader.load()
        elif file_extension in {".docx", ".pptx", ".html", ".htm"}:
            loader = UnstructuredFileLoader(str(file_path), mode="elements")
            documents = loader.load()
        else:
            raise ValueError(f"Unsupported extension: {file_extension}")

        return [doc for doc in documents if doc.page_content and doc.page_content.strip()]

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
    output_dir: Union[str, Path] = "exports",
) -> Optional[str]:
    """Generates a .pptx file from the structured JSON using PPTXGenerator."""
    progress = ProgressTracker()
    try:
        progress.update_progress("initializing_generator", "Setting up presentation generator...")
        template_data = presentation_structure_json.get("template_info")
        if not template_data:
            logger.warning("Template info not found in presentation structure. Using default generator settings.")
        generator = PPTXGenerator(template=template_data)

        progress.update_progress("generating_pptx", "Building PowerPoint slides...")
        presentation = generator.create_presentation_from_json(presentation_structure_json)

        if not presentation:
            raise RuntimeError("PPTXGenerator failed to create a presentation object.")

        progress.update_progress("saving", "Saving presentation file...")
        save_dir = Path(output_dir)
        save_dir.mkdir(parents=True, exist_ok=True)

        timestamp = time.strftime("%Y%m%d-%H%M%S")
        safe_base = Path(output_filename_base).stem or "presentation"
        output_path = save_dir / f"{safe_base}_{timestamp}.pptx"

        presentation.save(str(output_path))
        progress.update_progress("complete", "Presentation saved.")
        return str(output_path)

    except Exception as e:
        logger.error(f"Error in generate_presentation utility: {e}", exc_info=True)
        return None


def validate_input_file_path(file_path: Optional[Union[str, Path]]) -> bool:
    """Validates if the input file path has an allowed extension."""
    if not file_path:
        return False
    try:
        return Path(file_path).suffix.lower() in ALLOWED_EXTENSIONS
    except Exception:
        return False


class ProgressTracker:
    """Tracks and logs progress steps."""

    def __init__(self):
        self.steps = {
            "start": "Starting process",
            "loading": "Loading input data",
            "initializing_agent": "Initializing AI Agent",
            "processing": "AI Processing Content",
            "generating_structure": "AI Generating Presentation Structure",
            "analyzing": "Analyzing Content Structure",
            "initializing_generator": "Initializing Presentation Generator",
            "generating_pptx": "Generating PowerPoint File",
            "saving": "Saving Presentation",
            "exporting": "Exporting to other formats",
            "complete": "Process complete",
        }
        self.current_step_key = "start"

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
    "load_supported_documents",
    "generate_presentation",
    "validate_input_file_path",
    "ProgressTracker",
    "ALLOWED_EXTENSIONS",
]
