import os
import sys
from pathlib import Path
from typing import Optional, List
from dotenv import load_dotenv
from log_config.logging_config import logger, setup_logging
from view.gradio_ui import launch_interface
from app.utils import load_supported_documents
from templates.templates import PresentationTemplates
from langchain_core.documents import Document


# PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
# if PROJECT_ROOT not in sys.path:
#     sys.path.append(PROJECT_ROOT)

def main():
    """Main function to configure and launch the application."""
    global logger

    try:
        env_path = Path('.') / 'environment.env'
        if env_path.exists():
            load_dotenv(dotenv_path=env_path)
            logger.info(f"Loaded environment variables from {env_path}")
        else:
            logger.info("'.env' file not found. Using system environment variables.")
            load_dotenv()

        logger = setup_logging(os.getenv('LOG_LEVEL', 'INFO'))
        logger.info("Logger re-configured based on environment settings.")

        openai_api_key = os.getenv("OPENAI_API_KEY")
        anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")

        if not openai_api_key and not anthropic_api_key:
            logger.error(
                "Missing API Key: Set either OPENAI_API_KEY or ANTHROPIC_API_KEY in your environment or .env file.")
            print("\nERROR: Missing API Key. Please set OPENAI_API_KEY or ANTHROPIC_API_KEY.\n", file=sys.stderr)
            sys.exit(1)
        else:
            logger.info(
                f"Found API keys: OpenAI={'Yes' if openai_api_key else 'No'}, Anthropic={'Yes' if anthropic_api_key else 'No'}")

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
            logger.info(f"Attempting to load documentation for RAG from: {docs_path}")
            if not docs_path.exists():
                logger.warning(f"Documentation file not found at specified DOCS_PATH: {docs_path}")
            else:
                try:
                    loaded_docs = load_supported_documents(docs_path)
                    logger.info(f"Successfully loaded {len(loaded_docs)} document parts from {docs_path}")
                except Exception as e:
                    logger.error(f"Error loading documentation from {docs_path}: {e}", exc_info=True)
        else:
            logger.info("DOCS_PATH not set in environment. Skipping documentation loading for RAG.")

        logger.info("Preparing to launch Gradio interface...")
        launch_interface(
            available_templates=available_templates,
            loaded_docs_for_rag=loaded_docs,
            default_openai_key=openai_api_key,
            default_anthropic_key=anthropic_api_key,
        )

    except Exception as e:
        logger.critical(f"An unhandled error occurred during application startup: {e}", exc_info=True)
        print(f"\nFATAL STARTUP ERROR: {e}\n", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
