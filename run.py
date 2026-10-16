import logging
import os
import sys
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from langchain_core.documents import Document

from app.utils import load_supported_documents
from log_config.logging_config import logger, setup_logging
from templates.templates import PresentationTemplates
from view.gradio_ui import launch_interface

PLACEHOLDER_KEYS = {"01010101", "your_secret_key", "your_anthropic_api_key", "key", ""}


def _clean_api_key(raw_key: Optional[str]) -> Optional[str]:
    if not raw_key:
        return None
    stripped = raw_key.strip()
    return None if stripped in PLACEHOLDER_KEYS else stripped


def main():
    """Main function to configure and launch the application."""

    try:
        env_path = Path(__file__).parent / "environment.env"
        if env_path.exists():
            logger.info(f"Loading environment variables from {env_path}")
            load_dotenv(dotenv_path=env_path)
        else:
            logger.info(f"'environment.env' file not found at {env_path}. Using system environment variables.")
            load_dotenv()

        log_level_from_env = os.getenv("LOG_LEVEL", "INFO")
        setup_logging(log_level_from_env)
        logger.info(f"Logger configured to level: {logging.getLevelName(logger.level)}")

        openai_api_key = _clean_api_key(os.getenv("OPENAI_API_KEY"))
        anthropic_api_key = _clean_api_key(os.getenv("ANTHROPIC_API_KEY"))

        if not openai_api_key and not anthropic_api_key:
            logger.warning(
                "No valid API key found in environment. Users must enter an API key in the Gradio UI."
            )

        template_manager = PresentationTemplates()
        available_templates = template_manager.list_templates()
        if not available_templates:
            logger.warning("No presentation templates found or loaded. UI might lack template choices.")
        else:
            logger.info(f"Loaded {len(available_templates)} presentation templates.")

        docs_path_str = os.getenv("DOCS_PATH")
        loaded_docs: Optional[List[Document]] = None
        if docs_path_str:
            docs_path = Path(docs_path_str)
            if docs_path.exists():
                try:
                    loaded_docs = load_supported_documents(docs_path)
                    logger.info(f"Loaded {len(loaded_docs)} document chunks from {docs_path}")
                except Exception as e:
                    logger.error(f"Error loading documentation from {docs_path}: {e}", exc_info=True)
            else:
                logger.warning(f"Documentation file not found at DOCS_PATH: {docs_path}")

        logger.info("Preparing to launch Gradio interface...")
        launch_interface(
            available_templates=available_templates,
            loaded_docs_for_rag=loaded_docs,
            default_openai_key=openai_api_key,
            default_anthropic_key=anthropic_api_key,
        )

    except Exception as e:
        logger.critical(f"Unhandled error during application startup: {e}", exc_info=True)
        print(f"\nFATAL STARTUP ERROR: {e}\n", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
