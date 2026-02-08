"""
Rate Limiting Module for the Agentic RAG System.

Feature #324: API Rate Limiting

This module provides rate limiting to prevent API abuse in production.
Uses slowapi library which is built on top of limits.

Features:
- Configurable limits per endpoint category
- IP-based rate limiting with client identification
- Whitelist support for trusted IPs
- Graceful 429 responses with Retry-After header
- Rate limit headers in all responses

Usage:
    from core.rate_limit import limiter, get_rate_limit_key

    @app.get("/api/endpoint")
    @limiter.limit("60/minute")
    async def my_endpoint(request: Request):
        ...

Environment Variables:
    RATE_LIMIT_ENABLED: Enable/disable rate limiting (default: true)
    RATE_LIMIT_DEFAULT: Default limit (default: "100/minute")
    RATE_LIMIT_CHAT: Chat endpoint limit (default: "60/minute")
    RATE_LIMIT_UPLOAD: Upload endpoint limit (default: "10/minute")
    RATE_LIMIT_HEALTH: Health check limit (default: "300/minute")
    RATE_LIMIT_WHITELIST: Comma-separated whitelist IPs (default: "127.0.0.1,localhost")
"""

import logging
from typing import Optional, Callable
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from core.config import settings
from core.logging_config import get_logger

logger = get_logger(__name__)


def get_real_ip(request: Request) -> str:
    """
    Get the real client IP address, considering proxies.

    Checks headers in order:
    1. X-Forwarded-For (first IP in chain)
    2. X-Real-IP
    3. Direct client IP

    Args:
        request: FastAPI Request object

    Returns:
        Client IP address string
    """
    # Check X-Forwarded-For (may have multiple IPs)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # First IP is the original client
        ip = forwarded_for.split(",")[0].strip()
        return ip

    # Check X-Real-IP
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    # Fall back to direct client IP
    return get_remote_address(request)


def get_rate_limit_key(request: Request) -> str:
    """
    Generate a rate limit key based on client IP.

    This function is used by slowapi to identify clients.
    Returns empty string for whitelisted IPs to bypass rate limiting.

    Args:
        request: FastAPI Request object

    Returns:
        Rate limit key (IP address or empty string for whitelisted)
    """
    if not settings.RATE_LIMIT_ENABLED:
        return ""  # Empty key means no rate limiting

    ip = get_real_ip(request)

    # Check whitelist
    if ip in settings.RATE_LIMIT_WHITELIST:
        logger.debug(f"IP {ip} is whitelisted, bypassing rate limit")
        return ""  # Empty key means no rate limiting

    return ip


def get_rate_limit_key_for_chat(request: Request) -> str:
    """
    Generate a rate limit key for chat endpoints.
    Uses stricter identification for expensive operations.
    """
    return get_rate_limit_key(request)


def get_rate_limit_key_for_upload(request: Request) -> str:
    """
    Generate a rate limit key for upload endpoints.
    Uses stricter identification for expensive operations.
    """
    return get_rate_limit_key(request)


# Create the limiter instance
# The default limit applies to all endpoints unless overridden
limiter = Limiter(
    key_func=get_rate_limit_key,
    default_limits=[settings.RATE_LIMIT_DEFAULT] if settings.RATE_LIMIT_ENABLED else [],
    enabled=settings.RATE_LIMIT_ENABLED,
    headers_enabled=True,  # Add rate limit headers to responses
    strategy="fixed-window",  # Fixed time windows for rate limiting
)


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """
    Custom handler for rate limit exceeded errors.

    Returns a JSON response with:
    - 429 Too Many Requests status
    - Retry-After header
    - Clear error message with limit details
    - Request ID for tracking

    Args:
        request: FastAPI Request object
        exc: RateLimitExceeded exception

    Returns:
        JSONResponse with 429 status
    """
    client_ip = get_real_ip(request)
    path = request.url.path

    # Log the rate limit event
    logger.warning(
        f"Rate limit exceeded: {client_ip} on {path}",
        extra={
            "event": "rate_limit_exceeded",
            "client_ip": client_ip,
            "path": path,
            "method": request.method,
            "limit": str(exc.detail),
        }
    )

    # Parse the retry-after from the exception
    # slowapi provides this in the exception detail
    retry_after = 60  # Default to 60 seconds

    # Get request ID if available
    request_id = getattr(request.state, "request_id", None)

    response = JSONResponse(
        status_code=429,
        content={
            "error": "Too Many Requests",
            "message": f"Rate limit exceeded. Please wait before making more requests.",
            "detail": str(exc.detail),
            "retry_after_seconds": retry_after,
            "request_id": request_id,
        },
        headers={
            "Retry-After": str(retry_after),
            "X-RateLimit-Limit": str(exc.detail),
        }
    )

    if request_id:
        response.headers["X-Request-ID"] = request_id

    return response


def get_default_limit() -> str:
    """Get the default rate limit from settings."""
    return settings.RATE_LIMIT_DEFAULT


def get_chat_limit() -> str:
    """Get the chat endpoint rate limit from settings."""
    return settings.RATE_LIMIT_CHAT


def get_upload_limit() -> str:
    """Get the upload endpoint rate limit from settings."""
    return settings.RATE_LIMIT_UPLOAD


def get_health_limit() -> str:
    """Get the health check endpoint rate limit from settings."""
    return settings.RATE_LIMIT_HEALTH


# Pre-configured limiters for different endpoint types
# Usage: @limiter.limit(get_chat_limit())
def chat_limit_decorator():
    """Decorator for chat endpoints with chat-specific rate limit."""
    return limiter.limit(settings.RATE_LIMIT_CHAT, key_func=get_rate_limit_key_for_chat)


def upload_limit_decorator():
    """Decorator for upload endpoints with upload-specific rate limit."""
    return limiter.limit(settings.RATE_LIMIT_UPLOAD, key_func=get_rate_limit_key_for_upload)


def health_limit_decorator():
    """Decorator for health endpoints with health-specific rate limit."""
    return limiter.limit(settings.RATE_LIMIT_HEALTH)


# Log the rate limiting configuration on module load
if settings.RATE_LIMIT_ENABLED:
    logger.info(
        f"[Feature #324] Rate limiting enabled",
        extra={
            "event": "rate_limit_config",
            "default_limit": settings.RATE_LIMIT_DEFAULT,
            "chat_limit": settings.RATE_LIMIT_CHAT,
            "upload_limit": settings.RATE_LIMIT_UPLOAD,
            "health_limit": settings.RATE_LIMIT_HEALTH,
            "whitelist_count": len(settings.RATE_LIMIT_WHITELIST),
        }
    )
else:
    logger.info("[Feature #324] Rate limiting is disabled")
