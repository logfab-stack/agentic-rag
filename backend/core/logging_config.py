"""
Structured Logging Configuration for Agentic RAG System

Feature #321: Implements production-grade structured JSON logging with:
- Request ID generation and propagation
- Contextual logging (request ID in all log entries)
- Log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- Log rotation and retention
- Structured JSON format for log aggregation

Usage:
    from core.logging_config import get_logger, setup_logging

    # At application startup
    setup_logging()

    # In modules
    logger = get_logger(__name__)
    logger.info("Processing document", extra={"document_id": doc_id})
"""

import logging
import logging.handlers
import json
import os
import sys
import uuid
import time
from datetime import datetime
from typing import Optional, Dict, Any
from contextvars import ContextVar
from pathlib import Path

# Context variable for request ID - shared across the entire request lifecycle
request_id_var: ContextVar[Optional[str]] = ContextVar('request_id', default=None)

# Configuration constants
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_FILE = LOG_DIR / "app.log"
ERROR_LOG_FILE = LOG_DIR / "error.log"
MAX_LOG_SIZE = 10 * 1024 * 1024  # 10 MB
BACKUP_COUNT = 5  # Keep 5 rotated files
LOG_RETENTION_DAYS = 30


def get_request_id() -> Optional[str]:
    """Get the current request ID from context."""
    return request_id_var.get()


def set_request_id(request_id: str) -> None:
    """Set the request ID in context."""
    request_id_var.set(request_id)


def generate_request_id() -> str:
    """Generate a unique request ID."""
    # Format: timestamp-short_uuid (e.g., "20260203-a1b2c3d4")
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    short_uuid = uuid.uuid4().hex[:8]
    return f"{timestamp}-{short_uuid}"


class StructuredLogFormatter(logging.Formatter):
    """
    Custom formatter that outputs logs in structured JSON format.

    Each log entry includes:
    - timestamp: ISO 8601 format
    - level: Log level name
    - request_id: Current request ID (if available)
    - logger: Logger name (module path)
    - message: Log message
    - extra: Additional context data
    - exception: Exception info (if applicable)
    """

    def format(self, record: logging.LogRecord) -> str:
        # Build the structured log entry
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add request ID if available
        request_id = get_request_id()
        if request_id:
            log_entry["request_id"] = request_id

        # Add file and line info for debugging
        log_entry["source"] = {
            "file": record.pathname,
            "line": record.lineno,
            "function": record.funcName,
        }

        # Add any extra fields passed to the logger
        # Exclude standard LogRecord attributes
        standard_attrs = {
            'name', 'msg', 'args', 'created', 'filename', 'funcName',
            'levelname', 'levelno', 'lineno', 'module', 'msecs',
            'pathname', 'process', 'processName', 'relativeCreated',
            'stack_info', 'exc_info', 'exc_text', 'thread', 'threadName',
            'taskName', 'message'
        }

        extra_data = {}
        for key, value in record.__dict__.items():
            if key not in standard_attrs and not key.startswith('_'):
                # Try to serialize the value
                try:
                    json.dumps(value)
                    extra_data[key] = value
                except (TypeError, ValueError):
                    extra_data[key] = str(value)

        if extra_data:
            log_entry["extra"] = extra_data

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": self.formatException(record.exc_info) if record.exc_info[2] else None,
            }

        return json.dumps(log_entry, default=str)


class ConsoleLogFormatter(logging.Formatter):
    """
    Human-readable formatter for console output.

    Format: [LEVEL] [REQUEST_ID] [LOGGER] MESSAGE
    """

    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
    }
    RESET = '\033[0m'

    def __init__(self, use_colors: bool = True):
        super().__init__()
        self.use_colors = use_colors

    def format(self, record: logging.LogRecord) -> str:
        # Get request ID
        request_id = get_request_id()
        request_id_part = f"[{request_id[:16]}...]" if request_id and len(request_id) > 16 else f"[{request_id}]" if request_id else ""

        # Format timestamp
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        # Get level with optional color
        level = record.levelname
        if self.use_colors and level in self.COLORS:
            level_str = f"{self.COLORS[level]}{level:8}{self.RESET}"
        else:
            level_str = f"{level:8}"

        # Get short logger name
        logger_name = record.name.split('.')[-1][:15]

        # Build message
        message = record.getMessage()

        # Base format
        log_line = f"{timestamp} {level_str} {request_id_part:20} [{logger_name:15}] {message}"

        # Add exception info if present
        if record.exc_info:
            log_line += f"\n{self.formatException(record.exc_info)}"

        return log_line


class RequestIdFilter(logging.Filter):
    """
    Logging filter that adds request_id to all log records.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "no-request"
        return True


def setup_logging(
    log_level: str = "INFO",
    log_to_file: bool = True,
    log_to_console: bool = True,
    json_format: bool = True,
    console_colors: bool = True,
) -> None:
    """
    Configure application-wide logging.

    Args:
        log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_to_file: Whether to log to rotating files
        log_to_console: Whether to log to console
        json_format: Use JSON format for file logs (recommended for production)
        console_colors: Use colors in console output
    """
    # Create logs directory
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Get the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Remove existing handlers
    root_logger.handlers = []

    # Create request ID filter
    request_filter = RequestIdFilter()

    # File handler with rotation (JSON format)
    if log_to_file:
        # Main log file (all levels)
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE,
            maxBytes=MAX_LOG_SIZE,
            backupCount=BACKUP_COUNT,
            encoding='utf-8',
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(StructuredLogFormatter() if json_format else ConsoleLogFormatter(use_colors=False))
        file_handler.addFilter(request_filter)
        root_logger.addHandler(file_handler)

        # Error log file (ERROR and above only)
        error_handler = logging.handlers.RotatingFileHandler(
            ERROR_LOG_FILE,
            maxBytes=MAX_LOG_SIZE,
            backupCount=BACKUP_COUNT,
            encoding='utf-8',
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(StructuredLogFormatter() if json_format else ConsoleLogFormatter(use_colors=False))
        error_handler.addFilter(request_filter)
        root_logger.addHandler(error_handler)

    # Console handler (human-readable)
    if log_to_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
        console_handler.setFormatter(ConsoleLogFormatter(use_colors=console_colors))
        console_handler.addFilter(request_filter)
        root_logger.addHandler(console_handler)

    # Suppress noisy loggers
    logging.getLogger('uvicorn.access').setLevel(logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)

    # Log startup
    logger = logging.getLogger(__name__)
    logger.info(
        "Logging configured",
        extra={
            "log_level": log_level,
            "log_to_file": log_to_file,
            "log_to_console": log_to_console,
            "json_format": json_format,
            "log_dir": str(LOG_DIR),
        }
    )


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with the specified name.

    Usage:
        logger = get_logger(__name__)
        logger.info("Processing document", extra={"document_id": "123"})

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)


class LoggingContextManager:
    """
    Context manager for adding extra context to all logs within a block.

    Usage:
        with LoggingContextManager(user_id="123", operation="upload"):
            logger.info("Starting upload")  # Will include user_id and operation
    """

    def __init__(self, **context):
        self.context = context
        self.old_factory = None

    def __enter__(self):
        self.old_factory = logging.getLogRecordFactory()
        context = self.context

        def record_factory(*args, **kwargs):
            record = self.old_factory(*args, **kwargs)
            for key, value in context.items():
                setattr(record, key, value)
            return record

        logging.setLogRecordFactory(record_factory)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        logging.setLogRecordFactory(self.old_factory)
        return False


def log_function_call(logger: logging.Logger):
    """
    Decorator to log function entry and exit with timing.

    Usage:
        @log_function_call(logger)
        async def process_document(doc_id: str):
            ...
    """
    import functools
    import asyncio

    def decorator(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            func_name = func.__name__
            start_time = time.time()

            # Log entry
            logger.debug(
                f"Entering {func_name}",
                extra={"function": func_name, "args_count": len(args), "kwargs_keys": list(kwargs.keys())}
            )

            try:
                result = await func(*args, **kwargs)
                duration_ms = (time.time() - start_time) * 1000

                # Log successful exit
                logger.debug(
                    f"Exiting {func_name}",
                    extra={"function": func_name, "duration_ms": round(duration_ms, 2), "success": True}
                )

                return result
            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000

                # Log error exit
                logger.error(
                    f"Error in {func_name}: {str(e)}",
                    extra={"function": func_name, "duration_ms": round(duration_ms, 2), "success": False},
                    exc_info=True
                )
                raise

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            func_name = func.__name__
            start_time = time.time()

            # Log entry
            logger.debug(
                f"Entering {func_name}",
                extra={"function": func_name, "args_count": len(args), "kwargs_keys": list(kwargs.keys())}
            )

            try:
                result = func(*args, **kwargs)
                duration_ms = (time.time() - start_time) * 1000

                # Log successful exit
                logger.debug(
                    f"Exiting {func_name}",
                    extra={"function": func_name, "duration_ms": round(duration_ms, 2), "success": True}
                )

                return result
            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000

                # Log error exit
                logger.error(
                    f"Error in {func_name}: {str(e)}",
                    extra={"function": func_name, "duration_ms": round(duration_ms, 2), "success": False},
                    exc_info=True
                )
                raise

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
