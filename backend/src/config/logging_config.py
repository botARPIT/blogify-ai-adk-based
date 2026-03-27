"""Logging configuration with structured JSON logging."""

import logging
import re
import sys
from typing import Any

import structlog


SENSITIVE_FIELD_PATTERN = re.compile(
    r"(secret|token|api[_-]?key|password|authorization|database_url)", re.IGNORECASE
)
DATABASE_CREDENTIALS_PATTERN = re.compile(r"(://)([^:@/]+):([^@/]+)@")


def _mask_sensitive_values(_logger, _method_name, event_dict):
    def mask(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: ("***" if SENSITIVE_FIELD_PATTERN.search(str(key)) else mask(val))
                for key, val in value.items()
            }
        if isinstance(value, list):
            return [mask(item) for item in value]
        if isinstance(value, tuple):
            return tuple(mask(item) for item in value)
        if isinstance(value, str):
            return DATABASE_CREDENTIALS_PATTERN.sub(r"\1***:***@", value)
        return value

    return mask(event_dict)


def setup_logging(
    log_level: str = "INFO",
    *,
    log_format: str = "json",
    mask_secrets: bool = True,
) -> None:
    """Configure structured logging with structlog."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper()),
    )

    renderer = (
        structlog.dev.ConsoleRenderer()
        if str(log_format).lower() == "console"
        else structlog.processors.JSONRenderer()
    )
    processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]
    if mask_secrets:
        processors.append(_mask_sensitive_values)
    processors.append(renderer)

    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    """Get a structured logger instance."""
    return structlog.get_logger(name)
