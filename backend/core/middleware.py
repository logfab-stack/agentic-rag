"""
FastAPI Middleware for Request Tracing and Security

Feature #321: Request ID middleware that:
- Generates unique request IDs for each incoming request
- Propagates request ID through the entire request lifecycle
- Adds request ID to response headers for client-side tracing
- Logs request start/end with timing information

Feature #326: Security headers middleware that:
- Adds Content-Security-Policy (CSP) header
- Adds Strict-Transport-Security (HSTS) header
- Adds X-Frame-Options header
- Adds X-Content-Type-Options header
- Adds X-XSS-Protection header
- Adds Referrer-Policy header
- Adds Permissions-Policy header
- Optionally forces HTTPS redirect

Usage:
    from core.middleware import RequestTracingMiddleware, SecurityHeadersMiddleware
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestTracingMiddleware)
"""

import time
import logging
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from core.logging_config import (
    generate_request_id,
    set_request_id,
    get_request_id,
    get_logger,
)

logger = get_logger(__name__)


class RequestTracingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds request tracing capabilities.

    For each request:
    1. Generates a unique request ID (or uses X-Request-ID header if provided)
    2. Sets the request ID in context for logging
    3. Adds request ID to response headers
    4. Logs request start and completion with timing
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Get or generate request ID
        request_id = request.headers.get("X-Request-ID")
        if not request_id:
            request_id = generate_request_id()

        # Set request ID in context for logging
        set_request_id(request_id)

        # Store request ID in request state for access in route handlers
        request.state.request_id = request_id

        # Record start time
        start_time = time.time()

        # Extract request info for logging
        method = request.method
        path = request.url.path
        query_string = request.url.query
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("User-Agent", "unknown")[:100]  # Truncate long UA strings

        # Log request start
        logger.info(
            f"Request started: {method} {path}",
            extra={
                "event": "request_start",
                "method": method,
                "path": path,
                "query_string": query_string,
                "client_ip": client_ip,
                "user_agent": user_agent,
            }
        )

        # Process the request
        try:
            response = await call_next(request)

            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000

            # Add request ID to response headers
            response.headers["X-Request-ID"] = request_id

            # Log request completion
            log_level = logging.INFO
            if response.status_code >= 500:
                log_level = logging.ERROR
            elif response.status_code >= 400:
                log_level = logging.WARNING

            logger.log(
                log_level,
                f"Request completed: {method} {path} -> {response.status_code} ({duration_ms:.2f}ms)",
                extra={
                    "event": "request_complete",
                    "method": method,
                    "path": path,
                    "status_code": response.status_code,
                    "duration_ms": round(duration_ms, 2),
                    "client_ip": client_ip,
                }
            )

            return response

        except Exception as e:
            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000

            # Log error
            logger.error(
                f"Request failed: {method} {path} - {str(e)[:200]}",
                extra={
                    "event": "request_error",
                    "method": method,
                    "path": path,
                    "duration_ms": round(duration_ms, 2),
                    "error_type": type(e).__name__,
                    "error_message": str(e)[:500],
                    "client_ip": client_ip,
                },
                exc_info=True
            )

            # Re-raise to let FastAPI handle it
            raise

        finally:
            # Clear request ID context
            set_request_id(None)


class PerformanceLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that logs slow requests for performance monitoring.

    Logs a warning for any request that takes longer than the threshold.
    """

    def __init__(self, app: ASGIApp, slow_request_threshold_ms: float = 1000.0):
        super().__init__(app)
        self.slow_request_threshold_ms = slow_request_threshold_ms

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()

        response = await call_next(request)

        duration_ms = (time.time() - start_time) * 1000

        if duration_ms > self.slow_request_threshold_ms:
            logger.warning(
                f"Slow request detected: {request.method} {request.url.path} took {duration_ms:.2f}ms",
                extra={
                    "event": "slow_request",
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round(duration_ms, 2),
                    "threshold_ms": self.slow_request_threshold_ms,
                    "status_code": response.status_code,
                }
            )

        return response


def get_request_id_from_request(request: Request) -> str:
    """
    Get the request ID from a request object.

    Useful in route handlers when you need the request ID.

    Usage:
        @app.get("/api/example")
        async def example(request: Request):
            request_id = get_request_id_from_request(request)
            return {"request_id": request_id}
    """
    if hasattr(request.state, "request_id"):
        return request.state.request_id
    return get_request_id() or "unknown"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Feature #326: Middleware that adds security headers to all responses.

    Security headers added:
    - Content-Security-Policy (CSP): Controls resources the browser can load
    - Strict-Transport-Security (HSTS): Forces HTTPS connections
    - X-Frame-Options: Prevents clickjacking attacks
    - X-Content-Type-Options: Prevents MIME type sniffing
    - X-XSS-Protection: XSS filter (legacy but still useful)
    - Referrer-Policy: Controls referrer information
    - Permissions-Policy: Restricts browser features

    Configuration is loaded from the Settings dataclass.
    """

    def __init__(
        self,
        app: ASGIApp,
        ssl_enabled: bool = False,
        force_https: bool = False,
        csp_directives: str = "",
        hsts_max_age: int = 31536000,
        hsts_include_subdomains: bool = True,
        hsts_preload: bool = False,
        x_frame_options: str = "SAMEORIGIN",
        x_content_type_options: str = "nosniff",
        x_xss_protection: str = "1; mode=block",
        referrer_policy: str = "strict-origin-when-cross-origin",
        permissions_policy: str = "",
    ):
        super().__init__(app)
        self.ssl_enabled = ssl_enabled
        self.force_https = force_https
        self.csp_directives = csp_directives
        self.hsts_max_age = hsts_max_age
        self.hsts_include_subdomains = hsts_include_subdomains
        self.hsts_preload = hsts_preload
        self.x_frame_options = x_frame_options
        self.x_content_type_options = x_content_type_options
        self.x_xss_protection = x_xss_protection
        self.referrer_policy = referrer_policy
        self.permissions_policy = permissions_policy

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Force HTTPS redirect if enabled and request is not HTTPS
        # Check both the scheme and X-Forwarded-Proto header (for reverse proxy)
        if self.force_https and self.ssl_enabled:
            x_forwarded_proto = request.headers.get("X-Forwarded-Proto", "")
            is_https = (
                request.url.scheme == "https" or
                x_forwarded_proto.lower() == "https"
            )
            if not is_https:
                from starlette.responses import RedirectResponse
                https_url = str(request.url).replace("http://", "https://", 1)
                return RedirectResponse(url=https_url, status_code=301)

        # Process the request
        response = await call_next(request)

        # Add security headers
        self._add_security_headers(response, request)

        return response

    def _add_security_headers(self, response: Response, request: Request):
        """Add security headers to the response."""

        # Content-Security-Policy
        if self.csp_directives:
            response.headers["Content-Security-Policy"] = self.csp_directives

        # Strict-Transport-Security (only when SSL is enabled)
        if self.ssl_enabled and self.hsts_max_age > 0:
            hsts_value = f"max-age={self.hsts_max_age}"
            if self.hsts_include_subdomains:
                hsts_value += "; includeSubDomains"
            if self.hsts_preload:
                hsts_value += "; preload"
            response.headers["Strict-Transport-Security"] = hsts_value

        # X-Frame-Options
        if self.x_frame_options:
            response.headers["X-Frame-Options"] = self.x_frame_options

        # X-Content-Type-Options
        if self.x_content_type_options:
            response.headers["X-Content-Type-Options"] = self.x_content_type_options

        # X-XSS-Protection
        if self.x_xss_protection:
            response.headers["X-XSS-Protection"] = self.x_xss_protection

        # Referrer-Policy
        if self.referrer_policy:
            response.headers["Referrer-Policy"] = self.referrer_policy

        # Permissions-Policy (formerly Feature-Policy)
        if self.permissions_policy:
            response.headers["Permissions-Policy"] = self.permissions_policy


class HTTPSRedirectMiddleware(BaseHTTPMiddleware):
    """
    Feature #326: Middleware that redirects HTTP to HTTPS.

    This is a simpler alternative to SecurityHeadersMiddleware when you
    only need HTTPS redirect without all the security headers.

    For production, prefer using SecurityHeadersMiddleware which includes
    HTTPS redirect functionality.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Check both the scheme and X-Forwarded-Proto header
        x_forwarded_proto = request.headers.get("X-Forwarded-Proto", "")
        is_https = (
            request.url.scheme == "https" or
            x_forwarded_proto.lower() == "https"
        )

        if not is_https:
            from starlette.responses import RedirectResponse
            https_url = str(request.url).replace("http://", "https://", 1)
            return RedirectResponse(url=https_url, status_code=301)

        response = await call_next(request)
        return response
