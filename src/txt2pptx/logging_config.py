"""Logging setup.

Library modules only call ``logging.getLogger(__name__)``; handlers are installed exclusively by the entry
points (CLI, web UI, MCP server) through :func:`setup_logging`. Console output always goes to **stderr** so
that stdout stays clean for machine protocols such as MCP over stdio.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "txt2pptx"
_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_NOISY_LOGGERS = ("httpx", "httpcore", "openai", "anthropic", "urllib3", "gradio", "uvicorn.access")


def setup_logging(level: str = "INFO", log_dir: Path | None = None) -> logging.Logger:
    """Configure the ``txt2pptx`` logger hierarchy (idempotent)."""
    numeric_level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    app_logger = logging.getLogger(LOGGER_NAME)
    app_logger.setLevel(numeric_level)
    app_logger.propagate = False

    for handler in list(app_logger.handlers):
        app_logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(_FORMAT)
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    app_logger.addHandler(console)

    if log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_dir / "txt2pptx.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            app_logger.addHandler(file_handler)
        except OSError as exc:  # read-only FS, permissions ...
            app_logger.warning("File logging disabled (%s): %s", log_dir, exc)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(max(numeric_level, logging.WARNING))

    return app_logger
