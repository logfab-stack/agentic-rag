"""
Agentic RAG System - Backend Entry Point

An intelligent document assistant that handles both unstructured text (PDF, TXT, Word, Markdown)
via semantic vector search and structured tabular data (CSV, Excel, JSON) via SQL queries.

Feature #229: Added support for broad/listing queries with high top_k retrieval.
Feature #252: Added cascade delete audit logging for embeddings.
Feature #321: Structured logging with request tracing.
Feature #322: Environment-based configuration with startup validation.
Feature #324: API rate limiting to prevent abuse in production.
Feature #327: Standardized error handling with user-friendly messages and error codes.
Feature #330: Background document processing with async queue.
Feature #338: Fix min_relevance_threshold validation range (0.0-0.9).
Feature #339: Fix min_relevance_threshold validation range mismatch (comments + force reload).
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
import sys

# Feature #322: Import configuration FIRST for centralized settings
from core.config import settings, init_settings, ConfigValidationError

# Import and configure structured logging BEFORE any other logging calls
from core.logging_config import setup_logging, get_logger

# Configure structured logging with request tracing
# Log level is now from centralized settings (Feature #322)
setup_logging(
    log_level=settings.LOG_LEVEL,
    log_to_file=settings.LOG_TO_FILE,
    log_to_console=True,
    json_format=settings.LOG_FORMAT == "json",  # JSON format for production
    console_colors=not settings.is_production,  # Colors only in development
)

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events."""
    logger.info("Starting Agentic RAG System...")
    logger.info("=" * 80)

    # Feature #322: Validate configuration on startup
    try:
        init_settings(validate=True)
        logger.info(f"✅ Configuration validated (environment: {settings.ENVIRONMENT.value})")
    except ConfigValidationError as e:
        logger.error("=" * 80)
        logger.error("❌ CONFIGURATION ERROR")
        logger.error("=" * 80)
        logger.error(str(e))
        logger.error("")
        logger.error("Please check your environment variables and .env file.")
        logger.error("See .env.example for the complete list of configuration options.")
        logger.error("=" * 80)
        # In production, fail hard on config errors
        if settings.is_production:
            raise RuntimeError(f"Configuration validation failed: {e}")
        else:
            logger.warning("Continuing with invalid configuration (development mode only)")

    # Initialize PostgreSQL database with pgvector
    db_initialized = False
    try:
        from core.database import init_db, test_connection, check_pgvector, run_migrations
        from core.dependencies import set_postgres_available

        # Test connection first
        if not test_connection():
            logger.error("=" * 80)
            logger.error("❌ CRITICAL ERROR: PostgreSQL connection failed")
            logger.error("=" * 80)
            logger.error("The application requires a working PostgreSQL connection.")
            logger.error("Please ensure:")
            logger.error("  1. PostgreSQL is running (e.g., brew services start postgresql)")
            logger.error("  2. Database 'agentic_rag' exists")
            logger.error("  3. Connection string is correct in DATABASE_URL")
            logger.error("  4. User 'postgres' has appropriate permissions")
            logger.error("=" * 80)
            raise RuntimeError("PostgreSQL connection failed - cannot start application")

        logger.info("✅ PostgreSQL connection successful")

        # Check pgvector extension
        if check_pgvector():
            logger.info("✅ pgvector extension is available")
        else:
            logger.warning("⚠️  pgvector extension not found - will be created on first use")

        # Feature #347: Run Alembic migrations before create_all()
        if settings.SKIP_MIGRATIONS:
            logger.info("⏭️  Skipping Alembic migrations (SKIP_MIGRATIONS=true)")
        else:
            migration_ok = run_migrations()
            if migration_ok:
                logger.info("✅ Alembic migrations applied successfully")
            else:
                logger.warning("⚠️  Alembic migrations failed or skipped - falling back to create_all()")

        # Initialize database (this will now fail loudly if tables can't be created)
        db_initialized = await init_db()

        if db_initialized:
            logger.info("=" * 80)
            logger.info("✅ Database initialized successfully - Application ready")
            logger.info("=" * 80)
            set_postgres_available(True)
        else:
            # This should not happen anymore as init_db() raises RuntimeError on failure
            logger.error("Database initialization returned False unexpectedly")
            raise RuntimeError("Database initialization failed without raising an exception")

    except RuntimeError as e:
        # RuntimeError indicates a critical failure that should stop the application
        logger.error(f"=" * 80)
        logger.error(f"❌ FATAL ERROR: {e}")
        logger.error(f"=" * 80)
        logger.error("APPLICATION STARTUP ABORTED")
        logger.error("The application cannot function without a working database.")
        logger.error("Please fix the database issues and restart the application.")
        logger.error(f"=" * 80)
        # Re-raise to prevent the application from starting
        raise
    except Exception as e:
        # Unexpected errors should also fail loudly
        logger.error(f"=" * 80)
        logger.error(f"❌ UNEXPECTED ERROR during database initialization: {e}")
        logger.error(f"=" * 80)
        logger.error("APPLICATION STARTUP ABORTED")
        import traceback
        logger.error(traceback.format_exc())
        logger.error(f"=" * 80)
        raise

    # Feature #348: Post-startup health check with auto-fix
    try:
        from services.startup_health import run_startup_health_check
        health_report = run_startup_health_check()
        if health_report.issues_found == 0:
            logger.info("✅ Startup health check: all checks passed")
        elif health_report.issues_fixed == health_report.issues_found:
            logger.info(f"✅ Startup health check: {health_report.issues_fixed} issues auto-fixed")
        else:
            unfixed = health_report.issues_found - health_report.issues_fixed
            logger.warning(f"⚠️  Startup health check: {unfixed} issue(s) require attention")
    except Exception as e:
        logger.warning(f"⚠️  Startup health check skipped: {e}")

    # Feature #253: Validate document file paths on startup
    try:
        from core.database import SessionLocal
        from models.db_models import DBDocument
        import os

        with SessionLocal() as db:
            documents = db.query(DBDocument).all()
            total_docs = len(documents)
            missing_files = []
            missing_paths = []

            for doc in documents:
                file_path = doc.file_path or doc.url
                if file_path:
                    if not os.path.exists(file_path):
                        missing_files.append({
                            "id": doc.id[:8],
                            "title": doc.title[:30],
                            "path": file_path
                        })
                else:
                    missing_paths.append({
                        "id": doc.id[:8],
                        "title": doc.title[:30]
                    })

            if missing_files or missing_paths:
                logger.warning(f"[Feature #253] Document file validation:")
                logger.warning(f"  Total documents: {total_docs}")
                logger.warning(f"  Missing file_path in DB: {len(missing_paths)}")
                logger.warning(f"  Files not found on disk: {len(missing_files)}")
                for mf in missing_files[:5]:  # Show first 5
                    logger.warning(f"    - {mf['id']}... ({mf['title']}): {mf['path']}")
                if len(missing_files) > 5:
                    logger.warning(f"    ... and {len(missing_files) - 5} more")
            else:
                logger.info(f"[Feature #253] ✅ All {total_docs} documents have valid file paths")

    except Exception as e:
        logger.warning(f"[Feature #253] ⚠️  File path validation skipped: {e}")

    # Initialize backup scheduler (Feature #221)
    backup_scheduler = None
    try:
        from services.backup_scheduler import init_backup_scheduler
        backup_scheduler = init_backup_scheduler()
        logger.info("✅ Automatic backup scheduler initialized")
    except Exception as e:
        logger.warning(f"⚠️  Backup scheduler initialization failed: {e}")

    # Initialize file integrity scheduler (Feature #293)
    file_integrity_scheduler = None
    try:
        from services.file_integrity_scheduler import init_file_integrity_scheduler
        file_integrity_scheduler = init_file_integrity_scheduler()
        logger.info("✅ File integrity scheduler initialized")
    except Exception as e:
        logger.warning(f"⚠️  File integrity scheduler initialization failed: {e}")

    # Initialize document processing queue (Feature #330)
    document_queue = None
    try:
        from services.document_queue import init_document_queue
        document_queue = await init_document_queue()
        logger.info("✅ Document processing queue initialized")
    except Exception as e:
        logger.warning(f"⚠️  Document processing queue initialization failed: {e}")

    # Startup: Initialize database, load models, etc.
    yield

    # Shutdown: Cleanup resources
    logger.info("Shutting down Agentic RAG System...")

    # Stop file integrity scheduler (Feature #293)
    if file_integrity_scheduler:
        try:
            file_integrity_scheduler.stop()
            logger.info("✅ File integrity scheduler stopped")
        except Exception as e:
            logger.warning(f"⚠️  Failed to stop file integrity scheduler: {e}")

    # Stop backup scheduler
    if backup_scheduler:
        try:
            backup_scheduler.stop()
            logger.info("✅ Backup scheduler stopped")
        except Exception as e:
            logger.warning(f"⚠️  Failed to stop backup scheduler: {e}")

    # Stop document processing queue (Feature #330)
    if document_queue:
        try:
            from services.document_queue import stop_document_queue
            await stop_document_queue()
            logger.info("✅ Document processing queue stopped")
        except Exception as e:
            logger.warning(f"⚠️  Failed to stop document processing queue: {e}")


# Create FastAPI application
app = FastAPI(
    title="Agentic RAG System",
    description="""
    An intelligent document assistant that handles:
    - **Unstructured text** (PDF, TXT, Word, Markdown) via semantic vector search
    - **Structured tabular data** (CSV, Excel, JSON) via SQL queries

    Features:
    - Document upload and management
    - Collection-based organization
    - AI-powered chat with tool selection
    - Vector search with re-ranking
    - SQL analysis for tabular data
    - Bilingual support (English/Italian)
    """,
    version="0.1.0",
    lifespan=lifespan
)

# Feature #321: Add request tracing middleware
# Note: Middleware is added in reverse order - last added is first executed
from core.middleware import RequestTracingMiddleware, PerformanceLoggingMiddleware, SecurityHeadersMiddleware

# Feature #324: Rate limiting
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from core.rate_limit import limiter, rate_limit_exceeded_handler

# Feature #327: Standardized error handling
from core.errors import AppError, app_exception_handler, generic_exception_handler

# Feature #324: Setup rate limiting
# Attach limiter state to the app so it can track request counts
app.state.limiter = limiter
# Register custom exception handler for rate limit exceeded errors
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# Feature #327: Register standardized error handlers
# AppError handler for our custom exceptions
app.add_exception_handler(AppError, app_exception_handler)
# Generic handler for all unhandled exceptions (catch-all, provides user-friendly message)
app.add_exception_handler(Exception, generic_exception_handler)
logger.info("✅ Standardized error handling enabled (Feature #327)")

# Feature #322: Configure CORS using settings
# In production, use CORS_ORIGINS from environment; in development, allow all localhost ports
# Feature #326: CORS configuration with stricter production settings
cors_allow_methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"] if settings.is_production else ["*"]
cors_allow_headers = ["Content-Type", "Authorization", "X-Request-ID", "Accept", "Origin", "X-Requested-With"] if settings.is_production else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=cors_allow_methods,
    allow_headers=cors_allow_headers,
    expose_headers=["X-Request-ID"],  # Allow clients to read request ID
)

# Feature #326: Add security headers middleware (CSP, HSTS, X-Frame-Options, etc.)
if settings.SECURITY_HEADERS_ENABLED:
    app.add_middleware(
        SecurityHeadersMiddleware,
        ssl_enabled=settings.SSL_ENABLED,
        force_https=settings.FORCE_HTTPS,
        csp_directives=settings.CSP_DIRECTIVES,
        hsts_max_age=settings.HSTS_MAX_AGE,
        hsts_include_subdomains=settings.HSTS_INCLUDE_SUBDOMAINS,
        hsts_preload=settings.HSTS_PRELOAD,
        x_frame_options=settings.X_FRAME_OPTIONS,
        x_content_type_options=settings.X_CONTENT_TYPE_OPTIONS,
        x_xss_protection=settings.X_XSS_PROTECTION,
        referrer_policy=settings.REFERRER_POLICY,
        permissions_policy=settings.PERMISSIONS_POLICY,
    )
    logger.info(f"✅ Security headers middleware enabled (SSL: {settings.SSL_ENABLED})")

# Feature #321: Add request tracing middleware (generates request IDs, logs request lifecycle)
app.add_middleware(RequestTracingMiddleware)

# Feature #321: Add performance logging middleware (logs slow requests)
# Feature #322: Threshold is now configurable via SLOW_REQUEST_THRESHOLD_MS
app.add_middleware(PerformanceLoggingMiddleware, slow_request_threshold_ms=settings.SLOW_REQUEST_THRESHOLD_MS)


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Agentic RAG System",
        "version": "0.1.0",
        "description": "Intelligent document assistant with vector search and SQL analysis",
        "docs": "/docs",
        "health": "/api/health",
        # Feature #322: Include environment in response
        "environment": settings.ENVIRONMENT.value,
        "debug": settings.DEBUG
    }


@app.get("/api/health")
@limiter.limit(settings.RATE_LIMIT_HEALTH)  # Feature #324: Rate limit health endpoint (default 300/minute)
async def health_check(request: Request):
    """
    Comprehensive health check endpoint for production deployment.

    Feature #320: Returns detailed health status including:
    - PostgreSQL connectivity and response time
    - Ollama availability (if used as LLM provider)
    - Embedding service status
    - Memory and disk usage metrics

    Returns:
        Health status with component-level details
    """
    import time
    import psutil
    import httpx

    health_status = {
        "status": "healthy",
        "service": "Agentic RAG System",
        "version": "0.1.0",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "components": {},
        "metrics": {}
    }

    # 1. Check PostgreSQL connection
    try:
        from core.database import test_connection, is_pgvector_available
        start_time = time.time()
        pg_healthy = test_connection()
        pg_latency = round((time.time() - start_time) * 1000, 2)  # ms

        health_status["components"]["postgresql"] = {
            "status": "healthy" if pg_healthy else "unhealthy",
            "latency_ms": pg_latency,
            "pgvector_available": is_pgvector_available()
        }

        if not pg_healthy:
            health_status["status"] = "degraded"
    except Exception as e:
        health_status["components"]["postgresql"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health_status["status"] = "unhealthy"

    # 2. Check embedding store
    try:
        from core.store import embedding_store
        embedding_backend = embedding_store.storage_backend
        embedding_chunks = embedding_store.get_chunk_count()

        health_status["components"]["embedding_store"] = {
            "status": "healthy",
            "backend": embedding_backend,
            "chunk_count": embedding_chunks,
            "persistent": embedding_backend in ("postgresql", "sqlite")
        }
    except Exception as e:
        health_status["components"]["embedding_store"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health_status["status"] = "degraded"

    # 3. Check Ollama availability (if configured)
    try:
        from core.store import settings_store
        llm_model = settings_store.get('llm_model', '')
        embedding_model = settings_store.get('embedding_model', '')

        uses_ollama = (
            llm_model.startswith('ollama:') or
            embedding_model.startswith('ollama:')
        )

        if uses_ollama:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    start_time = time.time()
                    response = await client.get("http://localhost:11434/api/version")
                    ollama_latency = round((time.time() - start_time) * 1000, 2)

                    if response.status_code == 200:
                        version_data = response.json()
                        health_status["components"]["ollama"] = {
                            "status": "healthy",
                            "version": version_data.get("version", "unknown"),
                            "latency_ms": ollama_latency
                        }
                    else:
                        health_status["components"]["ollama"] = {
                            "status": "unhealthy",
                            "error": f"HTTP {response.status_code}"
                        }
                        health_status["status"] = "degraded"
            except httpx.ConnectError:
                health_status["components"]["ollama"] = {
                    "status": "unhealthy",
                    "error": "Connection refused - Ollama not running"
                }
                health_status["status"] = "degraded"
            except Exception as e:
                health_status["components"]["ollama"] = {
                    "status": "unhealthy",
                    "error": str(e)
                }
                health_status["status"] = "degraded"
        else:
            health_status["components"]["ollama"] = {
                "status": "not_configured",
                "message": "Ollama not used - using OpenAI/OpenRouter"
            }
    except Exception as e:
        health_status["components"]["ollama"] = {
            "status": "unknown",
            "error": str(e)
        }

    # 4. Check embedding model availability
    try:
        from core.store import settings_store
        embedding_model = settings_store.get('embedding_model', 'text-embedding-3-small')

        if embedding_model.startswith('ollama:'):
            # Ollama embedding - check was already done above
            if "ollama" in health_status["components"]:
                ollama_status = health_status["components"]["ollama"]["status"]
                health_status["components"]["embedding_model"] = {
                    "status": ollama_status,
                    "model": embedding_model,
                    "provider": "ollama"
                }
        elif embedding_model.startswith('openrouter:'):
            # OpenRouter embedding
            api_key = settings_store.get('openrouter_api_key', '')
            health_status["components"]["embedding_model"] = {
                "status": "healthy" if api_key and len(api_key) > 10 else "unconfigured",
                "model": embedding_model,
                "provider": "openrouter",
                "api_key_set": bool(api_key and len(api_key) > 10)
            }
        else:
            # OpenAI embedding
            api_key = settings_store.get('openai_api_key', '')
            health_status["components"]["embedding_model"] = {
                "status": "healthy" if api_key and len(api_key) > 10 else "unconfigured",
                "model": embedding_model,
                "provider": "openai",
                "api_key_set": bool(api_key and len(api_key) > 10)
            }
    except Exception as e:
        health_status["components"]["embedding_model"] = {
            "status": "unknown",
            "error": str(e)
        }

    # 5. Memory usage metrics
    try:
        process = psutil.Process()
        memory_info = process.memory_info()

        health_status["metrics"]["memory"] = {
            "rss_mb": round(memory_info.rss / (1024 * 1024), 2),
            "vms_mb": round(memory_info.vms / (1024 * 1024), 2),
            "percent": round(process.memory_percent(), 2)
        }

        # System memory
        system_memory = psutil.virtual_memory()
        health_status["metrics"]["system_memory"] = {
            "total_gb": round(system_memory.total / (1024 ** 3), 2),
            "available_gb": round(system_memory.available / (1024 ** 3), 2),
            "percent_used": system_memory.percent
        }
    except Exception as e:
        health_status["metrics"]["memory"] = {"error": str(e)}

    # 6. Disk usage metrics
    try:
        # Check disk where uploads are stored
        import os
        upload_path = os.path.join(os.path.dirname(__file__), "uploads")
        if not os.path.exists(upload_path):
            upload_path = "/"

        disk_usage = psutil.disk_usage(upload_path)
        health_status["metrics"]["disk"] = {
            "total_gb": round(disk_usage.total / (1024 ** 3), 2),
            "used_gb": round(disk_usage.used / (1024 ** 3), 2),
            "free_gb": round(disk_usage.free / (1024 ** 3), 2),
            "percent_used": disk_usage.percent
        }

        # Warn if disk is getting full
        if disk_usage.percent > 90:
            health_status["status"] = "degraded" if health_status["status"] == "healthy" else health_status["status"]
            health_status["metrics"]["disk"]["warning"] = "Disk usage above 90%"
    except Exception as e:
        health_status["metrics"]["disk"] = {"error": str(e)}

    # Feature #348: Include startup health check results
    try:
        from services.startup_health import get_last_report
        startup_report = get_last_report()
        if startup_report:
            health_status["startup_health"] = startup_report
    except Exception:
        pass

    # Feature #350: Include response feedback summary
    try:
        from models.response_feedback import ResponseFeedback
        from sqlalchemy import func as sa_func, case as sa_case, select as sa_select
        from core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                sa_select(
                    sa_func.count(ResponseFeedback.id).label("total"),
                    sa_func.sum(sa_case((ResponseFeedback.rating > 0, 1), else_=0)).label("positive"),
                    sa_func.sum(sa_case((ResponseFeedback.rating < 0, 1), else_=0)).label("negative"),
                )
            )
            row = result.first()
            rf_total = row.total or 0
            rf_positive = int(row.positive or 0)
            rf_negative = int(row.negative or 0)
            health_status["response_feedback"] = {
                "total": rf_total,
                "positive": rf_positive,
                "negative": rf_negative,
                "positive_rate": round((rf_positive / rf_total * 100), 1) if rf_total > 0 else 0.0,
            }
    except Exception:
        pass

    # Legacy fields for backwards compatibility
    health_status["embedding_storage"] = health_status["components"].get("embedding_store", {}).get("backend", "unknown")
    health_status["embedding_chunks"] = health_status["components"].get("embedding_store", {}).get("chunk_count", 0)
    health_status["persistent_storage"] = health_status["components"].get("embedding_store", {}).get("persistent", False)

    return health_status


@app.get("/api/ready")
@limiter.limit(settings.RATE_LIMIT_HEALTH)  # Feature #324: Rate limit readiness endpoint
async def readiness_check(request: Request):
    """
    Kubernetes readiness probe endpoint.

    Feature #320: Returns 200 OK only when the application is ready to serve requests.
    Returns 503 Service Unavailable if critical dependencies are not ready.

    Critical dependencies for readiness:
    - PostgreSQL connection must be healthy
    - Embedding store must be accessible

    Returns:
        200: {"ready": true} if all critical dependencies are ready
        503: {"ready": false, "reason": "..."} if not ready
    """
    from fastapi.responses import JSONResponse

    # Check PostgreSQL connection (critical)
    try:
        from core.database import test_connection
        if not test_connection():
            return JSONResponse(
                status_code=503,
                content={"ready": False, "reason": "PostgreSQL connection failed"}
            )
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"ready": False, "reason": f"PostgreSQL check failed: {str(e)}"}
        )

    # Check embedding store (critical)
    try:
        from core.store import embedding_store
        # Just verify we can access the store
        _ = embedding_store.storage_backend
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"ready": False, "reason": f"Embedding store unavailable: {str(e)}"}
        )

    return {"ready": True}


@app.get("/api/live")
@limiter.limit(settings.RATE_LIMIT_HEALTH)  # Feature #324: Rate limit liveness endpoint
async def liveness_check(request: Request):
    """
    Kubernetes liveness probe endpoint.

    Feature #320: Returns 200 OK if the application process is alive.
    This is a simple check that doesn't verify external dependencies.

    Returns:
        200: {"alive": true} always (if the process is running)
    """
    return {"alive": True}


@app.get("/api/embeddings/health-check")
async def embedding_health_check():
    """
    Check if the configured embedding model is reachable and functional.

    Tests the embedding model by generating a small test embedding.
    Returns availability status for both Ollama and OpenAI embedding models.

    This should be called BEFORE starting a document upload to warn the user
    if embeddings won't be generated.
    """
    import httpx
    from core.store import settings_store

    embedding_model = settings_store.get('embedding_model', 'text-embedding-3-small')

    result = {
        "available": False,
        "model": embedding_model,
        "provider": "unknown",
        "message": "",
    }

    try:
        if embedding_model.startswith("ollama:"):
            # Ollama embedding model
            ollama_model_name = embedding_model.replace("ollama:", "")
            result["provider"] = "ollama"

            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(
                        "http://localhost:11434/api/embeddings",
                        json={"model": ollama_model_name, "prompt": "test"}
                    )

                    if response.status_code == 200:
                        data = response.json()
                        embedding = data.get("embedding", [])
                        if embedding and len(embedding) > 0:
                            result["available"] = True
                            result["message"] = f"Ollama embedding model '{ollama_model_name}' is available ({len(embedding)} dimensions)"
                        else:
                            result["message"] = f"Ollama model '{ollama_model_name}' returned empty embeddings"
                    else:
                        result["message"] = f"Ollama model '{ollama_model_name}' returned error: {response.status_code}"
            except httpx.ConnectError:
                result["message"] = "Ollama is not running. Please start Ollama to use local embedding models."
            except httpx.TimeoutException:
                result["message"] = "Connection to Ollama timed out."

        elif embedding_model.startswith("openrouter:"):
            # Feature #302: OpenRouter embedding model
            openrouter_model_name = embedding_model[11:]  # Remove 'openrouter:' prefix
            result["provider"] = "openrouter"
            api_key = settings_store.get('openrouter_api_key')

            if not api_key or len(api_key) < 10:
                result["message"] = "OpenRouter API key not configured. Please add your API key in Settings."
            else:
                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        response = await client.post(
                            "https://openrouter.ai/api/v1/embeddings",
                            headers={
                                "Authorization": f"Bearer {api_key}",
                                "Content-Type": "application/json",
                                "HTTP-Referer": "http://localhost:3009",
                                "X-Title": "Agentic RAG System"
                            },
                            json={
                                "model": openrouter_model_name,
                                "input": ["test"]
                            }
                        )

                        if response.status_code == 200:
                            data = response.json()
                            embeddings = data.get("data", [])
                            if embeddings and len(embeddings) > 0:
                                dim = len(embeddings[0].get("embedding", []))
                                result["available"] = True
                                result["message"] = f"OpenRouter embedding model '{openrouter_model_name}' is available ({dim} dimensions)"
                            else:
                                result["message"] = f"OpenRouter model '{openrouter_model_name}' returned empty response"
                        elif response.status_code == 401:
                            result["message"] = "Invalid OpenRouter API key. Please update your API key in Settings."
                        elif response.status_code == 404:
                            result["message"] = f"Embedding model '{openrouter_model_name}' not found on OpenRouter."
                        else:
                            result["message"] = f"OpenRouter error ({response.status_code}): {response.text[:200]}"
                except httpx.ConnectError:
                    result["message"] = "Cannot connect to OpenRouter API."
                except httpx.TimeoutException:
                    result["message"] = "Connection to OpenRouter timed out."
                except Exception as e:
                    result["message"] = f"OpenRouter error: {str(e)}"

        else:
            # OpenAI embedding model
            result["provider"] = "openai"
            api_key = settings_store.get('openai_api_key')

            if not api_key or len(api_key) < 10:
                result["message"] = "OpenAI API key not configured. Please add your API key in Settings."
            else:
                try:
                    from openai import OpenAI
                    client = OpenAI(api_key=api_key)
                    response = client.embeddings.create(
                        model=embedding_model,
                        input=["test"]
                    )

                    if response.data and len(response.data) > 0:
                        dim = len(response.data[0].embedding)
                        result["available"] = True
                        result["message"] = f"OpenAI embedding model '{embedding_model}' is available ({dim} dimensions)"
                    else:
                        result["message"] = f"OpenAI model '{embedding_model}' returned empty response"

                except Exception as e:
                    error_str = str(e)
                    if "401" in error_str or "invalid" in error_str.lower():
                        result["message"] = "Invalid OpenAI API key. Please update your API key in Settings."
                    elif "404" in error_str or "not found" in error_str.lower():
                        result["message"] = f"Embedding model '{embedding_model}' not found. Please select a valid model."
                    else:
                        result["message"] = f"OpenAI error: {error_str}"

    except Exception as e:
        logger.error(f"Error checking embedding health: {e}")
        result["message"] = f"Error checking embedding model: {str(e)}"

    return result


@app.get("/api/embeddings/integrity")
async def embedding_integrity():
    """
    Check embedding integrity statistics.

    Returns validation stats showing valid/invalid embeddings,
    dimension consistency, and reasons for any invalid embeddings.
    """
    try:
        from core.store import embedding_store
        stats = embedding_store.get_integrity_stats()

        return {
            "status": "ok" if stats["invalid_chunks"] == 0 else "warning",
            "storage_backend": embedding_store.storage_backend,
            **stats
        }
    except Exception as e:
        logger.error(f"Error getting embedding integrity stats: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


# Import API routers
from api.documents import router as documents_router
from api.conversations import router as conversations_router
from api.chat import router as chat_router
from api.collections import router as collections_router
from api.settings import router as settings_router
from api.backup import router as backup_router
from api.export import router as export_router
from api.whatsapp import router as whatsapp_router
from api.whatsapp_admin import router as whatsapp_admin_router
from api.notes import router as notes_router
from api.feedback import router as feedback_router
from api.ngrok import router as ngrok_router
from api.admin import router as admin_maintenance_router
from api.telegram import router as telegram_router
from api.telegram_admin import router as telegram_admin_router
from api.security import router as security_router
from api.response_feedback import router as response_feedback_router

# Include routers
app.include_router(documents_router, prefix="/api/documents", tags=["Documents"])
app.include_router(conversations_router, prefix="/api/conversations", tags=["Conversations"])
app.include_router(chat_router, prefix="/api/chat", tags=["Chat"])
app.include_router(collections_router, prefix="/api/collections", tags=["Collections"])
app.include_router(settings_router, prefix="/api/settings", tags=["Settings"])
app.include_router(backup_router, prefix="/api/backup", tags=["Backup"])
app.include_router(export_router, prefix="/api/export", tags=["Export"])
app.include_router(whatsapp_router, prefix="/api/whatsapp", tags=["WhatsApp"])
app.include_router(whatsapp_admin_router, prefix="/api/whatsapp/admin", tags=["WhatsApp Admin"])
app.include_router(notes_router, prefix="/api/notes", tags=["Notes"])
app.include_router(feedback_router, prefix="/api/feedback", tags=["Feedback"])
app.include_router(ngrok_router, prefix="/api/ngrok", tags=["Ngrok"])
app.include_router(admin_maintenance_router, prefix="/api/admin/maintenance", tags=["Admin Maintenance"])
app.include_router(telegram_router, prefix="/api/telegram", tags=["Telegram"])
app.include_router(telegram_admin_router, prefix="/api/telegram/admin", tags=["Telegram Admin"])
app.include_router(security_router, prefix="/api/security", tags=["Security"])
app.include_router(response_feedback_router, prefix="/api/response-feedback", tags=["Response Feedback"])

# TODO: Add remaining routers as they are implemented
# app.include_router(collections.router, prefix="/api/collections", tags=["Collections"])
# app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
# app.include_router(settings.router, prefix="/api/settings", tags=["Settings"])
# app.include_router(export.router, prefix="/api/export", tags=["Export"])


if __name__ == "__main__":
    import uvicorn
    # Feature #322: Use settings for host, port, and reload (debug-based)
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        workers=settings.WORKERS if not settings.DEBUG else 1  # Single worker in debug mode
    )
