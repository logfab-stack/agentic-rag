"""
Database configuration and connection management for PostgreSQL with pgvector.
Supports both async (for FastAPI) and sync (for scripts/migrations) operations.

Feature #322: Now uses centralized configuration from core.config
"""

import os
import logging
from typing import AsyncGenerator
from sqlalchemy import create_engine, text, pool
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

# Import Base from db_models (defined there to avoid circular imports)
from models.db_models import Base

# Import models to register them with Base.metadata before create_all()
# This ensures all tables are created during initialization
# NOTE: DocumentEmbedding import is handled dynamically in init_db() based on pgvector availability
DocumentEmbedding = None

# Global flag to track pgvector availability
_pgvector_available = False

# Feature #322: Import from centralized config
from core.config import settings

# Database URLs from centralized settings
DATABASE_URL = settings.DATABASE_URL
DATABASE_SYNC_URL = settings.DATABASE_SYNC_URL

# Create async engine for FastAPI
async_engine = create_async_engine(
    DATABASE_URL,
    poolclass=pool.NullPool,  # Use NullPool for async to avoid QueuePool issues
    pool_pre_ping=True,
    echo=settings.DEBUG and False  # Enable SQL logging only if explicitly needed
)

# Create sync engine for scripts and migrations
# Feature #322: Pool settings from centralized config
engine = create_engine(
    DATABASE_SYNC_URL,
    poolclass=pool.QueuePool,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_pre_ping=True,
    echo=False
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Create sync session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Async dependency function to get database session for FastAPI.
    Usage in FastAPI endpoints:
        async def my_endpoint(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"Database session error: {e}")
            raise
        finally:
            await session.close()


def get_db_sync() -> Session:
    """
    Synchronous database session for scripts and migrations.
    Use this in a context manager.
    """
    db = SessionLocal()
    try:
        return db
    finally:
        db.close()


def run_migrations() -> bool:
    """
    Run Alembic migrations programmatically (Feature #347).

    This runs 'alembic upgrade head' to apply any pending migrations,
    ensuring DB triggers, functions, and schema changes are always applied.

    Handles first-run scenarios:
    - Fresh DB (no tables): migrations will create everything from scratch
    - Existing DB without alembic_version: stamps current state to avoid re-running old migrations

    Returns:
        True if migrations ran successfully, False otherwise
    """
    import os
    from pathlib import Path
    from alembic.config import Config
    from alembic import command
    from sqlalchemy import inspect as sqlalchemy_inspect

    backend_dir = Path(__file__).parent.parent
    alembic_ini = backend_dir / "alembic.ini"

    if not alembic_ini.exists():
        logger.warning(f"alembic.ini not found at {alembic_ini} - skipping migrations")
        return False

    try:
        # Check if alembic_version table exists (indicates previous migration history)
        inspector = sqlalchemy_inspect(engine)
        existing_tables = inspector.get_table_names()
        has_alembic_version = "alembic_version" in existing_tables
        has_application_tables = "documents" in existing_tables

        # Configure Alembic
        alembic_cfg = Config(str(alembic_ini))
        alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_SYNC_URL)

        if has_application_tables and not has_alembic_version:
            # Existing DB created with create_all() but never had migrations run.
            # Stamp to head so alembic doesn't try to re-create existing tables.
            logger.info("Existing database without migration history detected - stamping to head")
            command.stamp(alembic_cfg, "head")
            logger.info("Migration history stamped to head successfully")
            return True

        # Run upgrade to head (works for both fresh DB and DBs with migration history)
        logger.info("Running Alembic migrations (upgrade head)...")
        command.upgrade(alembic_cfg, "head")
        logger.info("Alembic migrations completed successfully")
        return True

    except Exception as e:
        logger.error(f"Alembic migration failed: {e}")
        logger.error("The application will continue with create_all() as fallback.")
        logger.error("To debug, run manually: cd backend && alembic upgrade head")
        return False


async def init_db():
    """
    Initialize the database asynchronously:
    - Try to create pgvector extension (optional - logs warning if fails)
    - Create all tables (required - always done regardless of pgvector status)
    - Validate that all required tables exist after creation

    Returns:
        bool: True if database tables were created successfully, False otherwise

    Raises:
        RuntimeError: If tables cannot be created or validated (fails loudly)
    """
    global _pgvector_available, DocumentEmbedding

    # Try to enable pgvector extension (optional)
    try:
        async with async_engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            _pgvector_available = True
            logger.info("pgvector extension enabled - vector search will be available")

            # Only import and register DocumentEmbedding, UserNote, and MessageEmbedding if pgvector is available
            try:
                from models.embedding import DocumentEmbedding as DE
                from models.user_note import UserNote as UN
                from models.message_embedding import MessageEmbedding as ME
                DocumentEmbedding = DE
                logger.info("DocumentEmbedding model registered - vector storage will be available")
                logger.info("UserNote model registered - user notes with embeddings will be available")
                logger.info("MessageEmbedding model registered - chat history search will be available")
            except ImportError as import_err:
                logger.warning(f"Could not import pgvector-dependent models: {import_err}")
                DocumentEmbedding = None
                _pgvector_available = False
    except Exception as e:
        _pgvector_available = False
        DocumentEmbedding = None
        logger.warning(
            f"pgvector extension not available: {e}. "
            "Vector search will not work, but document persistence will function normally."
        )

    # Always create application tables (these don't require pgvector)
    try:
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"❌ CRITICAL ERROR: Failed to create database tables: {e}")
        logger.error("=" * 80)
        logger.error("DATABASE INITIALIZATION FAILED")
        logger.error("The application cannot function without database tables.")
        logger.error("Please check:")
        logger.error("  1. PostgreSQL is running and accessible")
        logger.error("  2. Database user has CREATE TABLE permissions")
        logger.error("  3. Database 'agentic_rag' exists")
        logger.error("  4. pgvector extension is installed (for document_embeddings table)")
        logger.error("=" * 80)
        raise RuntimeError(f"Database table creation failed: {e}")

    # Validate that all required tables exist
    # Note: document_embeddings is only required if pgvector is available
    required_tables = [
        'collections',
        'documents',
        'document_rows',
        'conversations',
        'messages',
        'settings',
        'whatsapp_users',
        'whatsapp_messages'
    ]

    if _pgvector_available:
        required_tables.append('document_embeddings')
        required_tables.append('user_notes')
        required_tables.append('chunk_feedback')
        required_tables.append('message_embeddings')  # Feature #161 - Chat history search

    try:
        from sqlalchemy import inspect as sqlalchemy_inspect

        # Use sync engine for inspection (async inspect not straightforward)
        inspector = sqlalchemy_inspect(engine)
        existing_tables = inspector.get_table_names()

        missing_tables = [t for t in required_tables if t not in existing_tables]

        if missing_tables:
            logger.error(f"❌ CRITICAL ERROR: Required tables are missing: {missing_tables}")
            logger.error("=" * 80)
            logger.error("TABLE VALIDATION FAILED")
            logger.error(f"Expected tables: {', '.join(required_tables)}")
            logger.error(f"Found tables: {', '.join(existing_tables)}")
            logger.error(f"Missing tables: {', '.join(missing_tables)}")
            logger.error("")
            logger.error("This usually means:")
            logger.error("  - pgvector extension is not installed (for document_embeddings)")
            logger.error("  - Database permissions are insufficient")
            logger.error("  - SQLAlchemy models are not properly registered")
            logger.error("=" * 80)
            raise RuntimeError(f"Required tables missing: {missing_tables}")

        logger.info(f"✅ All required tables validated: {', '.join(sorted(existing_tables))}")

        # Extra validation: Verify document_embeddings table is accessible (only if pgvector is available)
        if _pgvector_available:
            try:
                async with async_engine.connect() as conn:
                    await conn.execute(text("SELECT 1 FROM document_embeddings LIMIT 1"))
                logger.info("✅ document_embeddings table is accessible")
            except Exception as e:
                logger.error(f"❌ document_embeddings table exists but is not accessible: {e}")
                logger.error("This may indicate a pgvector configuration issue.")
                raise RuntimeError(f"document_embeddings table not accessible: {e}")
        else:
            logger.info("⚠️  pgvector not available - skipping document_embeddings validation")

        return True

    except RuntimeError:
        # Re-raise RuntimeError (already logged)
        raise
    except Exception as e:
        logger.error(f"❌ CRITICAL ERROR: Failed to validate tables: {e}")
        logger.error("=" * 80)
        logger.error("TABLE VALIDATION FAILED")
        logger.error("Could not verify that required tables exist.")
        logger.error("=" * 80)
        raise RuntimeError(f"Table validation failed: {e}")


def init_db_sync():
    """
    Initialize the database synchronously (for scripts):
    - Try to create pgvector extension (optional - logs warning if fails)
    - Create all tables (required - always done regardless of pgvector status)
    - Validate that all required tables exist after creation

    Returns:
        bool: True if database tables were created successfully, False otherwise

    Raises:
        RuntimeError: If tables cannot be created or validated (fails loudly)
    """
    global _pgvector_available, DocumentEmbedding

    # Try to enable pgvector extension (optional)
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
            _pgvector_available = True
            logger.info("pgvector extension enabled (sync) - vector search will be available")

            # Only import and register DocumentEmbedding, UserNote, and MessageEmbedding if pgvector is available
            try:
                from models.embedding import DocumentEmbedding as DE
                from models.user_note import UserNote as UN
                from models.message_embedding import MessageEmbedding as ME
                DocumentEmbedding = DE
                logger.info("DocumentEmbedding model registered (sync) - vector storage will be available")
                logger.info("UserNote model registered (sync) - user notes with embeddings will be available")
                logger.info("MessageEmbedding model registered (sync) - chat history search will be available")
            except ImportError as import_err:
                logger.warning(f"Could not import pgvector-dependent models (sync): {import_err}")
                DocumentEmbedding = None
                _pgvector_available = False
    except Exception as e:
        _pgvector_available = False
        DocumentEmbedding = None
        logger.warning(
            f"pgvector extension not available (sync): {e}. "
            "Vector search will not work, but document persistence will function normally."
        )

    # Always create application tables (these don't require pgvector)
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully (sync)")
    except Exception as e:
        logger.error(f"❌ CRITICAL ERROR: Failed to create database tables (sync): {e}")
        logger.error("=" * 80)
        logger.error("DATABASE INITIALIZATION FAILED")
        logger.error("The application cannot function without database tables.")
        logger.error("Please check:")
        logger.error("  1. PostgreSQL is running and accessible")
        logger.error("  2. Database user has CREATE TABLE permissions")
        logger.error("  3. Database 'agentic_rag' exists")
        logger.error("  4. pgvector extension is installed (for document_embeddings table)")
        logger.error("=" * 80)
        raise RuntimeError(f"Database table creation failed: {e}")

    # Validate that all required tables exist
    # Note: document_embeddings is only required if pgvector is available
    required_tables = [
        'collections',
        'documents',
        'document_rows',
        'conversations',
        'messages',
        'settings',
        'whatsapp_users',
        'whatsapp_messages'
    ]

    if _pgvector_available:
        required_tables.append('document_embeddings')
        required_tables.append('user_notes')
        required_tables.append('chunk_feedback')
        required_tables.append('message_embeddings')  # Feature #161 - Chat history search

    try:
        from sqlalchemy import inspect as sqlalchemy_inspect

        inspector = sqlalchemy_inspect(engine)
        existing_tables = inspector.get_table_names()

        missing_tables = [t for t in required_tables if t not in existing_tables]

        if missing_tables:
            logger.error(f"❌ CRITICAL ERROR: Required tables are missing: {missing_tables}")
            logger.error("=" * 80)
            logger.error("TABLE VALIDATION FAILED")
            logger.error(f"Expected tables: {', '.join(required_tables)}")
            logger.error(f"Found tables: {', '.join(existing_tables)}")
            logger.error(f"Missing tables: {', '.join(missing_tables)}")
            logger.error("")
            logger.error("This usually means:")
            logger.error("  - pgvector extension is not installed (for document_embeddings)")
            logger.error("  - Database permissions are insufficient")
            logger.error("  - SQLAlchemy models are not properly registered")
            logger.error("=" * 80)
            raise RuntimeError(f"Required tables missing: {missing_tables}")

        logger.info(f"✅ All required tables validated: {', '.join(sorted(existing_tables))}")

        # Extra validation: Verify document_embeddings table is accessible (only if pgvector is available)
        if _pgvector_available:
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1 FROM document_embeddings LIMIT 1"))
                logger.info("✅ document_embeddings table is accessible (sync)")
            except Exception as e:
                logger.error(f"❌ document_embeddings table exists but is not accessible: {e}")
                logger.error("This may indicate a pgvector configuration issue.")
                raise RuntimeError(f"document_embeddings table not accessible: {e}")
        else:
            logger.info("⚠️  pgvector not available - skipping document_embeddings validation (sync)")

        return True

    except RuntimeError:
        # Re-raise RuntimeError (already logged)
        raise
    except Exception as e:
        logger.error(f"❌ CRITICAL ERROR: Failed to validate tables (sync): {e}")
        logger.error("=" * 80)
        logger.error("TABLE VALIDATION FAILED")
        logger.error("Could not verify that required tables exist.")
        logger.error("=" * 80)
        raise RuntimeError(f"Table validation failed: {e}")


def test_connection() -> bool:
    """Test if database connection is working."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            return True
    except Exception as e:
        logger.error(f"Database connection test failed: {e}")
        return False


def check_pgvector() -> bool:
    """Check if pgvector extension is available."""
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT * FROM pg_extension WHERE extname = 'vector'")
            )
            return result.rowcount > 0
    except Exception as e:
        logger.error(f"Failed to check pgvector extension: {e}")
        return False


def is_pgvector_available() -> bool:
    """
    Return the cached pgvector availability status.
    This flag is set during init_db() or init_db_sync().
    Use this to check if vector operations are available before attempting them.
    """
    return _pgvector_available


async def close_db():
    """
    Close database connections.
    Call this on application shutdown.
    """
    try:
        await async_engine.dispose()
        engine.dispose()
        logger.info("Database connections closed")
    except Exception as e:
        logger.error(f"Error closing database connections: {e}")
        raise
