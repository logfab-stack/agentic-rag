"""
Standardized Error Handling Module for the Agentic RAG System.

Feature #327: Error handling and user-friendly error messages

This module provides:
- Standardized error response format with error codes
- User-friendly error messages that hide technical details
- Server-side logging of full stack traces
- Custom exception classes for different error types

Usage:
    from core.errors import (
        AppError, NotFoundError, ValidationError, raise_api_error,
        handle_exception, ErrorCode, error_response
    )

    # Using custom exceptions
    raise NotFoundError("Document", document_id)

    # Using raise_api_error helper
    raise_api_error(ErrorCode.DOCUMENT_NOT_FOUND, document_id=doc_id)

    # Wrapping unknown exceptions
    except Exception as e:
        raise handle_exception(e, context="uploading document")

Error Response Format:
    {
        "error": true,
        "code": "ERR_DOC_NOT_FOUND",
        "message": "The requested document could not be found.",
        "detail": "Document with ID 'abc123' does not exist.",
        "request_id": "req-xyz-789"
    }
"""

import logging
import traceback
from enum import Enum
from typing import Optional, Dict, Any, Union
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.logging_config import get_logger

logger = get_logger(__name__)


class ErrorCode(str, Enum):
    """
    Standardized error codes for the application.

    Format: ERR_<CATEGORY>_<SPECIFIC_ERROR>

    Categories:
    - GEN: General errors
    - DOC: Document-related errors
    - COL: Collection-related errors
    - CHT: Chat-related errors
    - CFG: Configuration/Settings errors
    - AUT: Authentication/Authorization errors
    - VAL: Validation errors
    - SVC: Service/External service errors
    - DB: Database errors
    """
    # General errors
    INTERNAL_ERROR = "ERR_GEN_INTERNAL"
    RATE_LIMITED = "ERR_GEN_RATE_LIMITED"
    SERVICE_UNAVAILABLE = "ERR_GEN_SERVICE_UNAVAILABLE"
    REQUEST_TIMEOUT = "ERR_GEN_TIMEOUT"

    # Document errors
    DOCUMENT_NOT_FOUND = "ERR_DOC_NOT_FOUND"
    DOCUMENT_FILE_MISSING = "ERR_DOC_FILE_MISSING"
    DOCUMENT_UPLOAD_FAILED = "ERR_DOC_UPLOAD_FAILED"
    DOCUMENT_DUPLICATE = "ERR_DOC_DUPLICATE"
    DOCUMENT_TOO_LARGE = "ERR_DOC_TOO_LARGE"
    DOCUMENT_UNSUPPORTED_TYPE = "ERR_DOC_UNSUPPORTED_TYPE"
    DOCUMENT_PARSE_ERROR = "ERR_DOC_PARSE_ERROR"
    DOCUMENT_EMBEDDING_FAILED = "ERR_DOC_EMBEDDING_FAILED"

    # Collection errors
    COLLECTION_NOT_FOUND = "ERR_COL_NOT_FOUND"
    COLLECTION_DELETE_FAILED = "ERR_COL_DELETE_FAILED"
    COLLECTION_DUPLICATE = "ERR_COL_DUPLICATE"

    # Chat errors
    CHAT_CONVERSATION_NOT_FOUND = "ERR_CHT_CONV_NOT_FOUND"
    CHAT_MESSAGE_EMPTY = "ERR_CHT_MSG_EMPTY"
    CHAT_PROCESSING_FAILED = "ERR_CHT_PROCESSING_FAILED"
    CHAT_BLOCKED = "ERR_CHT_BLOCKED"

    # Configuration errors
    CONFIG_INVALID = "ERR_CFG_INVALID"
    CONFIG_API_KEY_MISSING = "ERR_CFG_API_KEY_MISSING"
    CONFIG_API_KEY_INVALID = "ERR_CFG_API_KEY_INVALID"
    CONFIG_MODEL_NOT_FOUND = "ERR_CFG_MODEL_NOT_FOUND"

    # Validation errors
    VALIDATION_FAILED = "ERR_VAL_FAILED"
    VALIDATION_FIELD_REQUIRED = "ERR_VAL_REQUIRED"
    VALIDATION_FIELD_INVALID = "ERR_VAL_INVALID"
    VALIDATION_OUT_OF_RANGE = "ERR_VAL_RANGE"

    # Service errors
    SERVICE_OPENAI_ERROR = "ERR_SVC_OPENAI"
    SERVICE_OLLAMA_ERROR = "ERR_SVC_OLLAMA"
    SERVICE_COHERE_ERROR = "ERR_SVC_COHERE"
    SERVICE_EMBEDDING_ERROR = "ERR_SVC_EMBEDDING"

    # Database errors
    DATABASE_CONNECTION_FAILED = "ERR_DB_CONNECTION"
    DATABASE_QUERY_FAILED = "ERR_DB_QUERY"
    DATABASE_INTEGRITY_ERROR = "ERR_DB_INTEGRITY"


# User-friendly messages for each error code
ERROR_MESSAGES: Dict[ErrorCode, str] = {
    # General errors
    ErrorCode.INTERNAL_ERROR: "An unexpected error occurred. Please try again or contact support if the problem persists.",
    ErrorCode.RATE_LIMITED: "Too many requests. Please wait a moment and try again.",
    ErrorCode.SERVICE_UNAVAILABLE: "The service is temporarily unavailable. Please try again later.",
    ErrorCode.REQUEST_TIMEOUT: "The request took too long to complete. Please try again.",

    # Document errors
    ErrorCode.DOCUMENT_NOT_FOUND: "The requested document could not be found.",
    ErrorCode.DOCUMENT_FILE_MISSING: "The document file is no longer available on the server.",
    ErrorCode.DOCUMENT_UPLOAD_FAILED: "Failed to upload the document. Please check the file and try again.",
    ErrorCode.DOCUMENT_DUPLICATE: "A document with this content already exists.",
    ErrorCode.DOCUMENT_TOO_LARGE: "The file is too large. Maximum size is 100MB.",
    ErrorCode.DOCUMENT_UNSUPPORTED_TYPE: "This file type is not supported. Please upload PDF, TXT, CSV, Excel, Word, JSON, or Markdown files.",
    ErrorCode.DOCUMENT_PARSE_ERROR: "Failed to read the document content. The file may be corrupted or in an unsupported format.",
    ErrorCode.DOCUMENT_EMBEDDING_FAILED: "Failed to process the document for search. The document was saved but may not appear in search results.",

    # Collection errors
    ErrorCode.COLLECTION_NOT_FOUND: "The requested collection could not be found.",
    ErrorCode.COLLECTION_DELETE_FAILED: "Failed to delete the collection. Please try again.",
    ErrorCode.COLLECTION_DUPLICATE: "A collection with this name already exists.",

    # Chat errors
    ErrorCode.CHAT_CONVERSATION_NOT_FOUND: "The conversation could not be found.",
    ErrorCode.CHAT_MESSAGE_EMPTY: "Please enter a message.",
    ErrorCode.CHAT_PROCESSING_FAILED: "Failed to process your message. Please try again.",
    ErrorCode.CHAT_BLOCKED: "Your request was blocked for security reasons. Please modify your message and try again.",

    # Configuration errors
    ErrorCode.CONFIG_INVALID: "Invalid configuration. Please check your settings.",
    ErrorCode.CONFIG_API_KEY_MISSING: "API key is not configured. Please add your API key in Settings.",
    ErrorCode.CONFIG_API_KEY_INVALID: "The API key is invalid. Please check and update your API key in Settings.",
    ErrorCode.CONFIG_MODEL_NOT_FOUND: "The selected model is not available. Please choose a different model.",

    # Validation errors
    ErrorCode.VALIDATION_FAILED: "The provided data is invalid. Please check your input and try again.",
    ErrorCode.VALIDATION_FIELD_REQUIRED: "A required field is missing.",
    ErrorCode.VALIDATION_FIELD_INVALID: "One or more fields contain invalid values.",
    ErrorCode.VALIDATION_OUT_OF_RANGE: "A value is outside the allowed range.",

    # Service errors
    ErrorCode.SERVICE_OPENAI_ERROR: "Failed to connect to OpenAI. Please check your API key and try again.",
    ErrorCode.SERVICE_OLLAMA_ERROR: "Failed to connect to Ollama. Please ensure Ollama is running.",
    ErrorCode.SERVICE_COHERE_ERROR: "Failed to connect to Cohere. Please check your API key.",
    ErrorCode.SERVICE_EMBEDDING_ERROR: "Failed to generate embeddings. Please check your embedding model configuration.",

    # Database errors
    ErrorCode.DATABASE_CONNECTION_FAILED: "Unable to connect to the database. Please try again later.",
    ErrorCode.DATABASE_QUERY_FAILED: "A database error occurred. Please try again.",
    ErrorCode.DATABASE_INTEGRITY_ERROR: "A data integrity error occurred. The operation could not be completed.",
}


class ErrorResponse(BaseModel):
    """Standardized error response model."""
    error: bool = True
    code: str
    message: str
    detail: Optional[str] = None
    request_id: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "error": True,
                "code": "ERR_DOC_NOT_FOUND",
                "message": "The requested document could not be found.",
                "detail": "Document with ID 'abc123' does not exist.",
                "request_id": "req-xyz-789"
            }
        }


def error_response(
    code: ErrorCode,
    detail: Optional[str] = None,
    request_id: Optional[str] = None,
    custom_message: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a standardized error response dictionary.

    Args:
        code: The error code from ErrorCode enum
        detail: Optional detailed information (shown to user)
        request_id: Optional request ID for tracking
        custom_message: Optional custom user-friendly message (overrides default)

    Returns:
        Dictionary suitable for JSON response
    """
    return {
        "error": True,
        "code": code.value,
        "message": custom_message or ERROR_MESSAGES.get(code, "An error occurred."),
        "detail": detail,
        "request_id": request_id
    }


class AppError(HTTPException):
    """
    Base application error class that extends HTTPException.

    Provides standardized error responses with error codes,
    user-friendly messages, and optional detailed information.
    """

    def __init__(
        self,
        error_code: ErrorCode,
        status_code: int = 400,
        detail: Optional[str] = None,
        log_message: Optional[str] = None,
        log_level: int = logging.WARNING,
        headers: Optional[Dict[str, str]] = None
    ):
        """
        Initialize the application error.

        Args:
            error_code: The standardized error code
            status_code: HTTP status code (default 400)
            detail: Optional detailed information for the user
            log_message: Optional message to log (includes technical details)
            log_level: Logging level (default WARNING)
            headers: Optional HTTP headers
        """
        self.error_code = error_code
        self.user_message = ERROR_MESSAGES.get(error_code, "An error occurred.")

        # Create the response detail
        response_detail = error_response(error_code, detail)

        # Log the error server-side with technical details
        if log_message:
            logger.log(log_level, f"[{error_code.value}] {log_message}")

        super().__init__(
            status_code=status_code,
            detail=response_detail,
            headers=headers
        )


class NotFoundError(AppError):
    """Error for resource not found (404)."""

    def __init__(
        self,
        resource_type: str,
        resource_id: Optional[str] = None,
        error_code: Optional[ErrorCode] = None
    ):
        # Determine the appropriate error code based on resource type
        if error_code is None:
            error_code = {
                "document": ErrorCode.DOCUMENT_NOT_FOUND,
                "collection": ErrorCode.COLLECTION_NOT_FOUND,
                "conversation": ErrorCode.CHAT_CONVERSATION_NOT_FOUND,
            }.get(resource_type.lower(), ErrorCode.DOCUMENT_NOT_FOUND)

        detail = f"{resource_type} with ID '{resource_id}' not found." if resource_id else None

        super().__init__(
            error_code=error_code,
            status_code=404,
            detail=detail,
            log_message=f"{resource_type} not found: {resource_id}"
        )


class ValidationError(AppError):
    """Error for validation failures (400)."""

    def __init__(
        self,
        field: Optional[str] = None,
        message: Optional[str] = None,
        error_code: ErrorCode = ErrorCode.VALIDATION_FAILED
    ):
        detail = f"Invalid value for '{field}': {message}" if field and message else message

        super().__init__(
            error_code=error_code,
            status_code=400,
            detail=detail,
            log_message=f"Validation error: {field}={message}" if field else message
        )


class ServiceError(AppError):
    """Error for external service failures (502/503)."""

    def __init__(
        self,
        service_name: str,
        original_error: Optional[Exception] = None,
        error_code: Optional[ErrorCode] = None
    ):
        # Determine the appropriate error code based on service name
        if error_code is None:
            error_code = {
                "openai": ErrorCode.SERVICE_OPENAI_ERROR,
                "ollama": ErrorCode.SERVICE_OLLAMA_ERROR,
                "cohere": ErrorCode.SERVICE_COHERE_ERROR,
                "embedding": ErrorCode.SERVICE_EMBEDDING_ERROR,
            }.get(service_name.lower(), ErrorCode.SERVICE_UNAVAILABLE)

        # Log the original error details server-side
        log_msg = f"Service '{service_name}' error"
        if original_error:
            log_msg += f": {type(original_error).__name__}: {str(original_error)}"

        super().__init__(
            error_code=error_code,
            status_code=502,
            detail=f"Unable to connect to {service_name}.",
            log_message=log_msg,
            log_level=logging.ERROR
        )


class DatabaseError(AppError):
    """Error for database failures (500)."""

    def __init__(
        self,
        operation: str,
        original_error: Optional[Exception] = None,
        error_code: ErrorCode = ErrorCode.DATABASE_QUERY_FAILED
    ):
        # Log the full database error server-side only
        log_msg = f"Database error during {operation}"
        if original_error:
            log_msg += f": {type(original_error).__name__}: {str(original_error)}"
            # Log full traceback at debug level
            logger.debug(f"Database error traceback:\n{traceback.format_exc()}")

        super().__init__(
            error_code=error_code,
            status_code=500,
            detail=f"Database operation failed: {operation}",
            log_message=log_msg,
            log_level=logging.ERROR
        )


class ConfigurationError(AppError):
    """Error for configuration issues (400/500)."""

    def __init__(
        self,
        setting: str,
        issue: str,
        error_code: ErrorCode = ErrorCode.CONFIG_INVALID
    ):
        super().__init__(
            error_code=error_code,
            status_code=400,
            detail=f"Configuration issue with '{setting}': {issue}",
            log_message=f"Configuration error: {setting} - {issue}"
        )


def raise_api_error(
    error_code: ErrorCode,
    status_code: int = 400,
    detail: Optional[str] = None,
    log_message: Optional[str] = None,
    **context_kwargs
) -> None:
    """
    Helper function to raise a standardized API error.

    Args:
        error_code: The standardized error code
        status_code: HTTP status code
        detail: Optional user-facing detail message
        log_message: Optional technical message for server logs
        **context_kwargs: Additional context to include in log message

    Raises:
        AppError: Always raises this exception
    """
    # Build log message with context
    if context_kwargs:
        context_str = ", ".join(f"{k}={v}" for k, v in context_kwargs.items())
        full_log_msg = f"{log_message or 'Error occurred'} [{context_str}]"
    else:
        full_log_msg = log_message

    raise AppError(
        error_code=error_code,
        status_code=status_code,
        detail=detail,
        log_message=full_log_msg
    )


def handle_exception(
    exc: Exception,
    context: str = "processing request",
    default_code: ErrorCode = ErrorCode.INTERNAL_ERROR,
    request: Optional[Request] = None
) -> AppError:
    """
    Convert an unknown exception to a standardized AppError.

    This function logs the full stack trace server-side while
    returning a user-friendly error message.

    Args:
        exc: The original exception
        context: Description of what was happening when error occurred
        default_code: Default error code if not otherwise determined
        request: Optional Request for extracting request_id

    Returns:
        AppError suitable for raising
    """
    # Get request ID if available
    request_id = None
    if request:
        request_id = getattr(request.state, "request_id", None)

    # Log the full traceback server-side
    logger.error(
        f"Unhandled exception during {context}: {type(exc).__name__}: {str(exc)}",
        extra={"request_id": request_id, "traceback": traceback.format_exc()}
    )
    logger.debug(f"Full traceback:\n{traceback.format_exc()}")

    # Map known exception types to appropriate error codes
    error_code = default_code
    status_code = 500

    # Check for specific exception types
    exc_type = type(exc).__name__
    exc_str = str(exc).lower()

    # Database errors - check both type name and exception message
    if "psycopg2" in exc_type.lower() or "sqlalchemy" in exc_type.lower() or "psycopg2" in exc_str:
        error_code = ErrorCode.DATABASE_QUERY_FAILED
        if "connection" in exc_str or "operational" in exc_str:
            error_code = ErrorCode.DATABASE_CONNECTION_FAILED
        elif "integrity" in exc_str or "unique" in exc_str or "duplicate" in exc_str:
            error_code = ErrorCode.DATABASE_INTEGRITY_ERROR

    # OpenAI errors
    elif "openai" in exc_type.lower() or "openai" in exc_str:
        error_code = ErrorCode.SERVICE_OPENAI_ERROR
        status_code = 502
        if "401" in exc_str or "invalid" in exc_str or "api_key" in exc_str:
            error_code = ErrorCode.CONFIG_API_KEY_INVALID
            status_code = 400

    # Ollama errors
    elif "ollama" in exc_str or "11434" in exc_str:
        error_code = ErrorCode.SERVICE_OLLAMA_ERROR
        status_code = 502

    # Cohere errors
    elif "cohere" in exc_str:
        error_code = ErrorCode.SERVICE_COHERE_ERROR
        status_code = 502

    # File not found
    elif isinstance(exc, FileNotFoundError):
        error_code = ErrorCode.DOCUMENT_FILE_MISSING
        status_code = 404

    # Permission errors
    elif isinstance(exc, PermissionError):
        error_code = ErrorCode.INTERNAL_ERROR
        status_code = 500

    # Timeout errors
    elif "timeout" in exc_str or "timed out" in exc_str:
        error_code = ErrorCode.REQUEST_TIMEOUT
        status_code = 504

    # Value errors (validation)
    elif isinstance(exc, ValueError):
        error_code = ErrorCode.VALIDATION_FAILED
        status_code = 400

    return AppError(
        error_code=error_code,
        status_code=status_code,
        detail=f"Error while {context}. Please try again.",
        log_message=f"Unhandled {exc_type} during {context}: {str(exc)}"
    )


async def app_exception_handler(request: Request, exc: AppError) -> JSONResponse:
    """
    FastAPI exception handler for AppError exceptions.

    Register this handler in your FastAPI app:
        app.add_exception_handler(AppError, app_exception_handler)

    Args:
        request: The FastAPI request
        exc: The AppError exception

    Returns:
        JSONResponse with standardized error format
    """
    # Get request ID from request state
    request_id = getattr(request.state, "request_id", None)

    # The detail is already formatted by AppError
    response_body = exc.detail
    if isinstance(response_body, dict):
        response_body["request_id"] = request_id

    return JSONResponse(
        status_code=exc.status_code,
        content=response_body,
        headers=exc.headers
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    FastAPI exception handler for all unhandled exceptions.

    Register this handler in your FastAPI app:
        app.add_exception_handler(Exception, generic_exception_handler)

    Args:
        request: The FastAPI request
        exc: The unhandled exception

    Returns:
        JSONResponse with standardized error format
    """
    # Get request ID from request state
    request_id = getattr(request.state, "request_id", None)

    # Log the full exception server-side
    logger.error(
        f"Unhandled exception: {type(exc).__name__}: {str(exc)}",
        extra={
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
            "traceback": traceback.format_exc()
        }
    )

    # Return a user-friendly error
    return JSONResponse(
        status_code=500,
        content=error_response(
            ErrorCode.INTERNAL_ERROR,
            request_id=request_id
        )
    )


# Convenience function to check if an HTTPException is already an AppError
def is_app_error(exc: Exception) -> bool:
    """Check if an exception is already a standardized AppError."""
    return isinstance(exc, AppError)


# Helper for re-raising HTTPException as-is vs wrapping in AppError
def wrap_or_reraise(exc: Exception, context: str = "processing request") -> None:
    """
    Either re-raise an HTTPException as-is, or wrap unknown exceptions.

    Usage:
        except Exception as e:
            wrap_or_reraise(e, context="uploading document")
    """
    if isinstance(exc, HTTPException):
        raise exc
    raise handle_exception(exc, context)
