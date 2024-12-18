import logging
import os
import sys
from pathlib import Path


def setup_logging(log_level: str = 'INFO') -> logging.Logger:
    """Sets up the application logging configuration."""
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / 'app.log'

    level = getattr(logging, log_level.upper(), logging.INFO)

    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ],
        force=True
    )

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    return logging.getLogger("txt2pptx")


logger: logging.Logger = setup_logging(os.getenv('LOG_LEVEL', 'INFO'))
