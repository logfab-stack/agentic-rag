"""
Agentic RAG System - Backend Entry Point

An intelligent document assistant that handles both unstructured text (PDF, TXT, Word, Markdown)
via semantic vector search and structured tabular data (CSV, Excel, JSON) via SQL queries.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events."""
    logger.info("Starting Agentic RAG System...")
    logger.info("=" * 80)

    # Initialize PostgreSQL database with pgvector
    db_initialized = False
    try:
        from core.database import init_db, test_connection, check_pgvector, run_migrations
        from core.dependencies import set_postgres_available
        from core.config import settings as app_settings

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
        if app_settings.SKIP_MIGRATIONS:
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

    # Startup: Initialize database, load models, etc.
    yield
    # Shutdown: Cleanup resources
    logger.info("Shutting down Agentic RAG System...")


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

# Configure CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", "http://localhost:3001", "http://localhost:3002",
        "http://localhost:3003", "http://localhost:3004", "http://localhost:3005",
        "http://localhost:3006", "http://localhost:3007", "http://localhost:3008",
        "http://localhost:3009", "http://localhost:3010", "http://localhost:3011",
        "http://localhost:3012", "http://localhost:3013", "http://localhost:3014",
        "http://localhost:3015", "http://localhost:3016", "http://localhost:3017",
        "http://localhost:3018", "http://localhost:3019", "http://localhost:3020",
        "http://localhost:5173",
        "http://127.0.0.1:3000", "http://127.0.0.1:3001", "http://127.0.0.1:3002",
        "http://127.0.0.1:3003", "http://127.0.0.1:3004", "http://127.0.0.1:3005",
        "http://127.0.0.1:3006", "http://127.0.0.1:3007", "http://127.0.0.1:3008",
        "http://127.0.0.1:3009", "http://127.0.0.1:3010", "http://127.0.0.1:3011",
        "http://127.0.0.1:3012", "http://127.0.0.1:3013", "http://127.0.0.1:3014",
        "http://127.0.0.1:3015", "http://127.0.0.1:3016", "http://127.0.0.1:3017",
        "http://127.0.0.1:3018", "http://127.0.0.1:3019", "http://127.0.0.1:3020",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Agentic RAG System",
        "version": "0.1.0",
        "description": "Intelligent document assistant with vector search and SQL analysis",
        "docs": "/docs",
        "health": "/api/health"
    }


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    # Get embedding store backend info
    try:
        from core.store import embedding_store
        embedding_backend = embedding_store.storage_backend
        embedding_chunks = embedding_store.get_chunk_count()
    except Exception:
        embedding_backend = "unknown"
        embedding_chunks = 0

    return {
        "status": "healthy",
        "service": "Agentic RAG System",
        "version": "0.1.0",
        "embedding_storage": embedding_backend,
        "embedding_chunks": embedding_chunks,
        "persistent_storage": embedding_backend in ("postgresql", "sqlite")
    }


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

# Include routers
app.include_router(documents_router, prefix="/api/documents", tags=["Documents"])
app.include_router(conversations_router, prefix="/api/conversations", tags=["Conversations"])
app.include_router(chat_router, prefix="/api/chat", tags=["Chat"])
app.include_router(collections_router, prefix="/api/collections", tags=["Collections"])
app.include_router(settings_router, prefix="/api/settings", tags=["Settings"])
app.include_router(backup_router, prefix="/api/backup", tags=["Backup"])
app.include_router(export_router, prefix="/api/export", tags=["Export"])

# TODO: Add remaining routers as they are implemented
# app.include_router(collections.router, prefix="/api/collections", tags=["Collections"])
# app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
# app.include_router(settings.router, prefix="/api/settings", tags=["Settings"])
# app.include_router(export.router, prefix="/api/export", tags=["Export"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
