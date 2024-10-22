import logging
import sys
from pathlib import Path


def setup_logging() -> logging.Logger:
    """Sets up the application logging configuration."""
    # Create logs directory if it doesn't exist
    Path("logs").mkdir(parents=True, exist_ok=True)

    # Configure logging
    logging.basicConfig(  # Use logging.basicConfig, NOT log_config.basicConfig
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/app.log'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)


logger: logging.Logger = setup_logging()
