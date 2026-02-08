"""
Configuration module for the Agentic RAG System.

Feature #322: Environment-based configuration

This module provides centralized configuration management using environment variables
with validation on startup. All configuration is loaded from environment variables
with sensible defaults for development.

Usage:
    from core.config import settings

    # Access configuration values
    print(settings.DATABASE_URL)
    print(settings.is_production)

Environment Variables:
    See .env.example for the complete list of supported environment variables.
"""

import os
import sys
import logging
from typing import Optional, List
from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path
from functools import lru_cache

logger = logging.getLogger(__name__)


class Environment(str, Enum):
    """Application environment types."""
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TESTING = "testing"


def _get_bool(value: str, default: bool = False) -> bool:
    """Convert string to boolean."""
    if not value:
        return default
    return value.lower() in ("true", "1", "yes", "on")


def _get_int(value: str, default: int) -> int:
    """Convert string to integer."""
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_list(value: str, default: Optional[List[str]] = None) -> List[str]:
    """Convert comma-separated string to list."""
    if not value:
        return default or []
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass
class Settings:
    """
    Application settings loaded from environment variables.

    All sensitive values (API keys, database credentials) should be provided
    via environment variables, not hardcoded in the code.
    """

    # ==========================================================================
    # ENVIRONMENT
    # ==========================================================================
    ENVIRONMENT: Environment = field(default_factory=lambda: Environment(
        os.getenv("ENVIRONMENT", "development")
    ))
    DEBUG: bool = field(default_factory=lambda: _get_bool(
        os.getenv("DEBUG", "true")
    ))

    # ==========================================================================
    # DATABASE CONFIGURATION
    # ==========================================================================
    DATABASE_URL: str = field(default_factory=lambda: os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/agentic_rag"
    ))
    DATABASE_SYNC_URL: str = field(default_factory=lambda: os.getenv(
        "DATABASE_SYNC_URL",
        "postgresql://postgres:postgres@localhost:5432/agentic_rag"
    ))
    DATABASE_POOL_SIZE: int = field(default_factory=lambda: _get_int(
        os.getenv("DATABASE_POOL_SIZE", "5"), 5
    ))
    DATABASE_MAX_OVERFLOW: int = field(default_factory=lambda: _get_int(
        os.getenv("DATABASE_MAX_OVERFLOW", "10"), 10
    ))

    # ==========================================================================
    # SERVER CONFIGURATION
    # ==========================================================================
    HOST: str = field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    PORT: int = field(default_factory=lambda: _get_int(
        os.getenv("PORT", "8000"), 8000
    ))
    WORKERS: int = field(default_factory=lambda: _get_int(
        os.getenv("WORKERS", "1"), 1
    ))

    # ==========================================================================
    # CORS CONFIGURATION
    # ==========================================================================
    CORS_ORIGINS: List[str] = field(default_factory=lambda: _get_list(
        os.getenv("CORS_ORIGINS", ""),
        # Default CORS origins for development
        [f"http://localhost:{p}" for p in range(3000, 3021)] +
        [f"http://127.0.0.1:{p}" for p in range(3000, 3021)] +
        ["http://localhost:5173", "http://127.0.0.1:5173"]
    ))

    # ==========================================================================
    # API KEYS (Sensitive - NEVER commit to source control)
    # ==========================================================================
    # These are OPTIONAL here - they can also be configured via the UI
    OPENAI_API_KEY: str = field(default_factory=lambda: os.getenv(
        "OPENAI_API_KEY", ""
    ))
    COHERE_API_KEY: str = field(default_factory=lambda: os.getenv(
        "COHERE_API_KEY", ""
    ))
    OPENROUTER_API_KEY: str = field(default_factory=lambda: os.getenv(
        "OPENROUTER_API_KEY", ""
    ))

    # ==========================================================================
    # MODEL CONFIGURATION
    # ==========================================================================
    DEFAULT_LLM_MODEL: str = field(default_factory=lambda: os.getenv(
        "DEFAULT_LLM_MODEL", "gpt-4o"
    ))
    DEFAULT_EMBEDDING_MODEL: str = field(default_factory=lambda: os.getenv(
        "DEFAULT_EMBEDDING_MODEL", "text-embedding-3-small"
    ))
    DEFAULT_RERANKER: str = field(default_factory=lambda: os.getenv(
        "DEFAULT_RERANKER", "cohere"
    ))

    # ==========================================================================
    # OLLAMA CONFIGURATION
    # ==========================================================================
    OLLAMA_BASE_URL: str = field(default_factory=lambda: os.getenv(
        "OLLAMA_BASE_URL", "http://localhost:11434"
    ))

    # ==========================================================================
    # FILE UPLOAD CONFIGURATION
    # ==========================================================================
    MAX_FILE_SIZE_MB: int = field(default_factory=lambda: _get_int(
        os.getenv("MAX_FILE_SIZE_MB", "100"), 100
    ))
    UPLOAD_DIR: str = field(default_factory=lambda: os.getenv(
        "UPLOAD_DIR", "./uploads"
    ))

    # ==========================================================================
    # BACKUP CONFIGURATION
    # ==========================================================================
    BACKUPS_DIR: str = field(default_factory=lambda: os.getenv(
        "BACKUPS_DIR", "./automatic_backups"
    ))
    BACKUP_RETENTION_DAYS: int = field(default_factory=lambda: _get_int(
        os.getenv("BACKUP_RETENTION_DAYS", "7"), 7
    ))
    WEEKLY_BACKUP_RETENTION: int = field(default_factory=lambda: _get_int(
        os.getenv("WEEKLY_BACKUP_RETENTION", "4"), 4
    ))

    # ==========================================================================
    # LOGGING CONFIGURATION
    # ==========================================================================
    LOG_LEVEL: str = field(default_factory=lambda: os.getenv(
        "LOG_LEVEL", "INFO"
    ))
    LOG_FORMAT: str = field(default_factory=lambda: os.getenv(
        "LOG_FORMAT", "json"  # "json" for production, "text" for development
    ))
    LOG_TO_FILE: bool = field(default_factory=lambda: _get_bool(
        os.getenv("LOG_TO_FILE", "true")
    ))
    LOG_DIR: str = field(default_factory=lambda: os.getenv(
        "LOG_DIR", "./logs"
    ))

    # ==========================================================================
    # SECURITY CONFIGURATION
    # ==========================================================================
    SECRET_KEY: str = field(default_factory=lambda: os.getenv(
        "SECRET_KEY", "dev-secret-key-change-in-production"
    ))

    # ==========================================================================
    # TELEGRAM CONFIGURATION
    # ==========================================================================
    TELEGRAM_BOT_TOKEN: str = field(default_factory=lambda: os.getenv(
        "TELEGRAM_BOT_TOKEN", ""
    ))
    TELEGRAM_WEBHOOK_URL: str = field(default_factory=lambda: os.getenv(
        "TELEGRAM_WEBHOOK_URL", ""
    ))

    # ==========================================================================
    # TWILIO/WHATSAPP CONFIGURATION
    # ==========================================================================
    TWILIO_ACCOUNT_SID: str = field(default_factory=lambda: os.getenv(
        "TWILIO_ACCOUNT_SID", ""
    ))
    TWILIO_AUTH_TOKEN: str = field(default_factory=lambda: os.getenv(
        "TWILIO_AUTH_TOKEN", ""
    ))
    TWILIO_WHATSAPP_NUMBER: str = field(default_factory=lambda: os.getenv(
        "TWILIO_WHATSAPP_NUMBER", ""
    ))

    # ==========================================================================
    # RAG CONFIGURATION
    # ==========================================================================
    DEFAULT_TOP_K: int = field(default_factory=lambda: _get_int(
        os.getenv("DEFAULT_TOP_K", "10"), 10
    ))
    MIN_RELEVANCE_THRESHOLD: float = field(default_factory=lambda: float(
        os.getenv("MIN_RELEVANCE_THRESHOLD", "0.4")
    ))
    STRICT_RELEVANCE_THRESHOLD: float = field(default_factory=lambda: float(
        os.getenv("STRICT_RELEVANCE_THRESHOLD", "0.6")
    ))

    # ==========================================================================
    # MIGRATION CONFIGURATION (Feature #347)
    # ==========================================================================
    # Skip automatic Alembic migrations on startup (for development/debugging)
    SKIP_MIGRATIONS: bool = field(default_factory=lambda: _get_bool(
        os.getenv("SKIP_MIGRATIONS", "false")
    ))

    # ==========================================================================
    # CHUNKING CONFIGURATION (Feature #331)
    # ==========================================================================
    # Timeout for agentic splitter in seconds (default 5 minutes)
    # If chunking takes longer than this, falls back to RecursiveCharacterTextSplitter
    AGENTIC_SPLITTER_TIMEOUT_SECONDS: int = field(default_factory=lambda: _get_int(
        os.getenv("AGENTIC_SPLITTER_TIMEOUT_SECONDS", "300"), 300
    ))

    # ==========================================================================
    # PERFORMANCE CONFIGURATION
    # ==========================================================================
    SLOW_REQUEST_THRESHOLD_MS: float = field(default_factory=lambda: float(
        os.getenv("SLOW_REQUEST_THRESHOLD_MS", "1000.0")
    ))

    # ==========================================================================
    # RATE LIMITING CONFIGURATION (Feature #324)
    # ==========================================================================
    RATE_LIMIT_ENABLED: bool = field(default_factory=lambda: _get_bool(
        os.getenv("RATE_LIMIT_ENABLED", "true")
    ))
    # Default rate limit for general endpoints (requests/minute)
    RATE_LIMIT_DEFAULT: str = field(default_factory=lambda: os.getenv(
        "RATE_LIMIT_DEFAULT", "100/minute"
    ))
    # Rate limit for chat endpoints (requests/minute) - lower due to LLM costs
    RATE_LIMIT_CHAT: str = field(default_factory=lambda: os.getenv(
        "RATE_LIMIT_CHAT", "60/minute"
    ))
    # Rate limit for upload endpoints (requests/minute) - lower due to processing costs
    RATE_LIMIT_UPLOAD: str = field(default_factory=lambda: os.getenv(
        "RATE_LIMIT_UPLOAD", "10/minute"
    ))
    # Rate limit for health check endpoints - higher for monitoring
    RATE_LIMIT_HEALTH: str = field(default_factory=lambda: os.getenv(
        "RATE_LIMIT_HEALTH", "300/minute"
    ))
    # Comma-separated list of IPs to whitelist from rate limiting
    RATE_LIMIT_WHITELIST: List[str] = field(default_factory=lambda: _get_list(
        os.getenv("RATE_LIMIT_WHITELIST", "127.0.0.1,localhost"),
        ["127.0.0.1", "localhost"]
    ))

    # ==========================================================================
    # SSL/TLS CONFIGURATION (Feature #326)
    # ==========================================================================
    # Enable HTTPS mode (for when running behind a reverse proxy with SSL)
    SSL_ENABLED: bool = field(default_factory=lambda: _get_bool(
        os.getenv("SSL_ENABLED", "false")
    ))
    # SSL certificate file path (optional - for direct uvicorn SSL)
    SSL_CERTFILE: str = field(default_factory=lambda: os.getenv(
        "SSL_CERTFILE", ""
    ))
    # SSL key file path (optional - for direct uvicorn SSL)
    SSL_KEYFILE: str = field(default_factory=lambda: os.getenv(
        "SSL_KEYFILE", ""
    ))
    # Force HTTPS redirect (only when behind reverse proxy)
    FORCE_HTTPS: bool = field(default_factory=lambda: _get_bool(
        os.getenv("FORCE_HTTPS", "false")
    ))

    # ==========================================================================
    # SECURITY HEADERS CONFIGURATION (Feature #326)
    # ==========================================================================
    # Enable security headers middleware
    SECURITY_HEADERS_ENABLED: bool = field(default_factory=lambda: _get_bool(
        os.getenv("SECURITY_HEADERS_ENABLED", "true")
    ))
    # Content Security Policy - comma-separated directives
    # Default is restrictive but allows inline styles and scripts from same origin
    CSP_DIRECTIVES: str = field(default_factory=lambda: os.getenv(
        "CSP_DIRECTIVES",
        "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' ws: wss: https://api.openai.com https://api.cohere.com https://openrouter.ai; frame-ancestors 'self'"
    ))
    # HSTS max-age in seconds (default 1 year)
    HSTS_MAX_AGE: int = field(default_factory=lambda: _get_int(
        os.getenv("HSTS_MAX_AGE", "31536000"), 31536000
    ))
    # Include subdomains in HSTS
    HSTS_INCLUDE_SUBDOMAINS: bool = field(default_factory=lambda: _get_bool(
        os.getenv("HSTS_INCLUDE_SUBDOMAINS", "true")
    ))
    # HSTS preload flag (only enable if domain is on HSTS preload list)
    HSTS_PRELOAD: bool = field(default_factory=lambda: _get_bool(
        os.getenv("HSTS_PRELOAD", "false")
    ))
    # X-Frame-Options (DENY, SAMEORIGIN, or ALLOW-FROM uri)
    X_FRAME_OPTIONS: str = field(default_factory=lambda: os.getenv(
        "X_FRAME_OPTIONS", "SAMEORIGIN"
    ))
    # X-Content-Type-Options (nosniff)
    X_CONTENT_TYPE_OPTIONS: str = field(default_factory=lambda: os.getenv(
        "X_CONTENT_TYPE_OPTIONS", "nosniff"
    ))
    # X-XSS-Protection (1; mode=block)
    X_XSS_PROTECTION: str = field(default_factory=lambda: os.getenv(
        "X_XSS_PROTECTION", "1; mode=block"
    ))
    # Referrer-Policy
    REFERRER_POLICY: str = field(default_factory=lambda: os.getenv(
        "REFERRER_POLICY", "strict-origin-when-cross-origin"
    ))
    # Permissions-Policy (formerly Feature-Policy)
    PERMISSIONS_POLICY: str = field(default_factory=lambda: os.getenv(
        "PERMISSIONS_POLICY",
        "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()"
    ))

    # ==========================================================================
    # COMPUTED PROPERTIES
    # ==========================================================================
    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.ENVIRONMENT == Environment.PRODUCTION

    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.ENVIRONMENT == Environment.DEVELOPMENT

    @property
    def is_testing(self) -> bool:
        """Check if running in testing environment."""
        return self.ENVIRONMENT == Environment.TESTING

    @property
    def max_file_size_bytes(self) -> int:
        """Get max file size in bytes."""
        return self.MAX_FILE_SIZE_MB * 1024 * 1024

    @property
    def upload_path(self) -> Path:
        """Get absolute upload directory path."""
        path = Path(self.UPLOAD_DIR)
        if not path.is_absolute():
            # Relative to backend directory
            backend_dir = Path(__file__).parent.parent
            path = backend_dir / path
        return path

    @property
    def backups_path(self) -> Path:
        """Get absolute backups directory path."""
        path = Path(self.BACKUPS_DIR)
        if not path.is_absolute():
            backend_dir = Path(__file__).parent.parent
            path = backend_dir / path
        return path

    @property
    def logs_path(self) -> Path:
        """Get absolute logs directory path."""
        path = Path(self.LOG_DIR)
        if not path.is_absolute():
            backend_dir = Path(__file__).parent.parent
            path = backend_dir / path
        return path


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""
    pass


def validate_settings(settings: Settings) -> List[str]:
    """
    Validate configuration settings on startup.

    Returns:
        List of validation warnings (non-critical issues)

    Raises:
        ConfigValidationError: If critical settings are invalid
    """
    errors = []
    warnings = []

    # ==========================================================================
    # CRITICAL VALIDATIONS (will raise error)
    # ==========================================================================

    # Database URL must be set
    if not settings.DATABASE_URL:
        errors.append("DATABASE_URL is required")

    if not settings.DATABASE_SYNC_URL:
        errors.append("DATABASE_SYNC_URL is required")

    # ==========================================================================
    # PRODUCTION-SPECIFIC VALIDATIONS
    # ==========================================================================

    if settings.is_production:
        # Secret key must be changed in production
        if settings.SECRET_KEY == "dev-secret-key-change-in-production":
            errors.append(
                "SECRET_KEY must be changed in production! "
                "Generate a secure key with: python -c 'import secrets; print(secrets.token_hex(32))'"
            )

        # Debug should be off in production
        if settings.DEBUG:
            warnings.append("DEBUG is enabled in production - this may expose sensitive information")

        # Should have at least one LLM API key configured
        if not any([settings.OPENAI_API_KEY, settings.OPENROUTER_API_KEY]):
            warnings.append(
                "No LLM API key configured via environment. "
                "Users will need to configure API keys via the UI."
            )

    # ==========================================================================
    # VALUE RANGE VALIDATIONS
    # ==========================================================================

    if settings.DATABASE_POOL_SIZE < 1:
        warnings.append("DATABASE_POOL_SIZE should be at least 1")

    if settings.DATABASE_MAX_OVERFLOW < 0:
        warnings.append("DATABASE_MAX_OVERFLOW should be non-negative")

    if settings.PORT < 1 or settings.PORT > 65535:
        errors.append(f"PORT must be between 1 and 65535, got {settings.PORT}")

    if settings.MAX_FILE_SIZE_MB < 1:
        warnings.append("MAX_FILE_SIZE_MB should be at least 1")

    if settings.MAX_FILE_SIZE_MB > 500:
        warnings.append("MAX_FILE_SIZE_MB is very large (>500MB) - this may cause memory issues")

    if settings.DEFAULT_TOP_K < 1 or settings.DEFAULT_TOP_K > 100:
        warnings.append("DEFAULT_TOP_K should be between 1 and 100")

    if settings.MIN_RELEVANCE_THRESHOLD < 0 or settings.MIN_RELEVANCE_THRESHOLD > 1:
        warnings.append("MIN_RELEVANCE_THRESHOLD should be between 0 and 1")

    if settings.STRICT_RELEVANCE_THRESHOLD < 0 or settings.STRICT_RELEVANCE_THRESHOLD > 1:
        warnings.append("STRICT_RELEVANCE_THRESHOLD should be between 0 and 1")

    # ==========================================================================
    # LOG RESULTS
    # ==========================================================================

    if errors:
        for error in errors:
            logger.error(f"Configuration error: {error}")
        raise ConfigValidationError(
            f"Configuration validation failed with {len(errors)} error(s):\n" +
            "\n".join(f"  - {e}" for e in errors)
        )

    if warnings:
        for warning in warnings:
            logger.warning(f"Configuration warning: {warning}")

    return warnings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Get the application settings (singleton).

    Settings are cached after first load. Use this function to access
    configuration throughout the application.

    Returns:
        Settings instance with all configuration values
    """
    settings = Settings()
    return settings


def init_settings(validate: bool = True) -> Settings:
    """
    Initialize and validate settings on application startup.

    This should be called early in the application startup process.

    Args:
        validate: Whether to validate settings (default: True)

    Returns:
        Validated Settings instance

    Raises:
        ConfigValidationError: If validation fails
    """
    settings = get_settings()

    # Log environment
    logger.info(f"Environment: {settings.ENVIRONMENT.value}")
    logger.info(f"Debug mode: {settings.DEBUG}")

    if validate:
        warnings = validate_settings(settings)
        if not warnings:
            logger.info("Configuration validation passed")

    return settings


# ==========================================================================
# CONVENIENCE EXPORTS
# ==========================================================================

# Create a module-level settings instance for easy import
# Usage: from core.config import settings
settings = get_settings()


# Export commonly used values at module level for backwards compatibility
DATABASE_URL = settings.DATABASE_URL
DATABASE_SYNC_URL = settings.DATABASE_SYNC_URL
OLLAMA_BASE_URL = settings.OLLAMA_BASE_URL
SECRET_KEY = settings.SECRET_KEY
DEBUG = settings.DEBUG
LOG_LEVEL = settings.LOG_LEVEL
