"""Logging configuration for the project."""

import logging
import sys


def setup_logger(
    name: str,
    level: int = logging.INFO,
) -> logging.Logger:
    """Set up a named logger with a stdout handler. Datei-Logging erfolgt über die Container-Infrastruktur."""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger
