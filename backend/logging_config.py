"""
Logging configuration module for the Shopify Automation application.
Provides centralized logging setup with environment-based debug control.
"""
import os
import logging
import sys

DEBUG_LOGGING = os.getenv("DEBUG_LOGGING", "false").lower() == "true"


def setup_logging():
    """Configure logging for the application."""
    log_level = logging.DEBUG if DEBUG_LOGGING else logging.INFO
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("celery").setLevel(logging.INFO)
    logging.getLogger("kombu").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name."""
    return logging.getLogger(name)


def debug_log(logger: logging.Logger, message: str, *args, **kwargs):
    """Only log debug messages if DEBUG_LOGGING is enabled."""
    if DEBUG_LOGGING:
        logger.debug(message, *args, **kwargs)
