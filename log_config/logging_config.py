import logging
import sys
from pathlib import Path
import os


def setup_logging(log_level: str = 'INFO') -> logging.Logger:
    """Sets up the application logging configuration."""
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / 'app.log'

    # Determine the effective log level
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Configure logging
    # Remove existing handlers associated with the root logger
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ],
        force=True # Force re-configuration if already configured
    )
    # Set higher level for noisy libraries if needed
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    # Return a logger instance for the application
    return logging.getLogger("txt2pptx")


# Initialize logger instance when the module is imported
logger: logging.Logger = setup_logging(os.getenv('LOG_LEVEL', 'INFO'))

# Add __init__.py files to relevant directories if they don't exist
for dir_path in ["app", "log_config", "templates", "view"]:
    init_file = Path(dir_path) / "__init__.py"
    init_file.touch(exist_ok=True)