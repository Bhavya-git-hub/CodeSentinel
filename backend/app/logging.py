"""Structured logging setup.

Analyser failures must be recorded with their reason (constraint C3, anti-pattern #9).
Structured events make that reason queryable instead of buried in a formatted string.
"""

from __future__ import annotations

import logging
import sys

import structlog

from app.config import Settings


def configure_logging(settings: Settings) -> None:
    """Configure structlog once at application start."""
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=settings.log_level)

    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer()
        if settings.environment == "production"
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level)
        ),
        cache_logger_on_first_use=True,
    )
