"""
Core DB maintenance endpoints: health, vacuum, orphans, indexes, BM25, backup.

Feature #353: Refactored from admin_maintenance.py.
"""

import asyncio
import os
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from core.database import async_engine
from core.dependencies import get_conversation_store, get_message_store, get_document_store, get_collection_store
from core.store import embedding_store
from core.store_postgres import ConversationStorePostgres, MessageStorePostgres

from ._shared import (
    OperationResult,
    HealthCheckResult,
    ConversationCleanupRequest,
    run_maintenance_query,
    get_table_row_counts,
    get_database_size,
    get_index_info,
    _format_size,
    utc_now,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health", response_model=HealthCheckResult)
async def health_check():
    """
    Comprehensive health check with database statistics.

    Returns:
    - Database connection status
    - Table row counts
    - Database and table sizes
    - Index information
    - Embedding statistics
    - pgvector availability
    """
    start_time = datetime.now()

    try:
        # Test database connection
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        raise HTTPException(status_code=500, detail=f"Database connection failed: {e}")

    # Check pgvector
    pgvector_available = False
    try:
        async with async_engine.connect() as conn:
            result = await conn.execute(
                text("SELECT * FROM pg_extension WHERE extname = 'vector'")
            )
            pgvector_available = result.rowcount > 0
    except Exception:
        pass

    # Get statistics
    table_counts = await get_table_row_counts()
    db_size = await get_database_size()
    indexes = await get_index_info()

    # Get embedding statistics
    try:
        embedding_stats = embedding_store.get_integrity_stats()
    except Exception as e:
        embedding_stats = {"error": str(e)}

    # Calculate storage info
    uploads_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'uploads')
    uploads_size = 0
    uploads_count = 0
    if os.path.exists(uploads_dir):
        for f in os.listdir(uploads_dir):
            fp = os.path.join(uploads_dir, f)
            if os.path.isfile(fp):
                uploads_size += os.path.getsize(fp)
                uploads_count += 1

    storage_info = {
        "uploads_directory": uploads_dir,
        "uploads_count": uploads_count,
        "uploads_size_bytes": uploads_size,
        "uploads_size_pretty": _format_size(uploads_size)
    }

    end_time = datetime.now()
    duration_ms = int((end_time - start_time).total_seconds() * 1000)

    return HealthCheckResult(
        status="healthy",
        database={
            "status": db_status,
            "check_duration_ms": duration_ms,
            **db_size
        },
        tables=table_counts,
        storage=storage_info,
        embeddings=embedding_stats,
        indexes=indexes,
        pgvector_available=pgvector_available
    )


@router.post("/vacuum-analyze", response_model=OperationResult)
async def vacuum_analyze():
    """
    Run VACUUM ANALYZE on all application tables.

    This optimizes PostgreSQL storage and updates statistics for the query planner.
    """
    start_time = datetime.now()

    tables = [
        'documents', 'collections', 'conversations', 'messages',
        'document_rows', 'document_embeddings', 'user_notes',
        'whatsapp_users', 'whatsapp_messages', 'chunk_feedback',
        'message_embeddings', 'settings'
    ]

    results = []
    errors = []

    # VACUUM requires autocommit mode, use sync engine
    from sqlalchemy import create_engine
    from core.database import DATABASE_SYNC_URL

    try:
        # Create a connection with autocommit for VACUUM
        vacuum_engine = create_engine(DATABASE_SYNC_URL, isolation_level="AUTOCOMMIT")

        with vacuum_engine.connect() as conn:
            for table in tables:
                try:
                    conn.execute(text(f"VACUUM ANALYZE {table}"))
                    results.append({"table": table, "status": "success"})
                except Exception as e:
                    error_str = str(e)
                    if "does not exist" in error_str:
                        results.append({"table": table, "status": "skipped", "reason": "table not found"})
                    else:
                        errors.append({"table": table, "error": error_str})

        vacuum_engine.dispose()

    except Exception as e:
        logger.error(f"VACUUM ANALYZE failed: {e}")
        raise HTTPException(status_code=500, detail=f"VACUUM ANALYZE failed: {e}")

    end_time = datetime.now()
    duration_ms = int((end_time - start_time).total_seconds() * 1000)

    success = len(errors) == 0

    return OperationResult(
        success=success,
        operation="vacuum_analyze",
        message=f"VACUUM ANALYZE completed on {len(results)} tables" + (f" with {len(errors)} errors" if errors else ""),
        details={
            "tables_processed": results,
            "errors": errors
        },
        duration_ms=duration_ms
    )


@router.post("/cleanup-orphans", response_model=OperationResult)
async def cleanup_orphans():
    """
    Remove orphan embeddings and chunks without parent documents.

    Cleans up:
    - document_embeddings where document_id doesn't exist in documents
    - document_rows where dataset_id doesn't exist in documents
    - message_embeddings where message_id doesn't exist in messages
    - chunk_feedback where chunk_id doesn't exist in document_embeddings
    - user_notes where document_id no longer exists

    Each cleanup operation runs in its own transaction to ensure that
    failures in one don't affect others.
    """
    start_time = datetime.now()

    cleanup_results = []
    total_deleted = 0

    # Cleanup orphan document embeddings
    try:
        async with async_engine.begin() as conn:
            result = await conn.execute(text("""
                DELETE FROM document_embeddings
                WHERE document_id NOT IN (SELECT id FROM documents)
            """))
            embeddings_deleted = result.rowcount
            cleanup_results.append({
                "type": "document_embeddings",
                "deleted": embeddings_deleted
            })
            total_deleted += embeddings_deleted
    except Exception as e:
        cleanup_results.append({
            "type": "document_embeddings",
            "error": str(e)
        })

    # Cleanup orphan document rows
    # Note: document_rows uses 'dataset_id' (VARCHAR) to reference documents.id
    try:
        async with async_engine.begin() as conn:
            result = await conn.execute(text("""
                DELETE FROM document_rows
                WHERE dataset_id NOT IN (SELECT id FROM documents)
            """))
            rows_deleted = result.rowcount
            cleanup_results.append({
                "type": "document_rows",
                "deleted": rows_deleted
            })
            total_deleted += rows_deleted
    except Exception as e:
        cleanup_results.append({
            "type": "document_rows",
            "error": str(e)
        })

    # Cleanup orphan message embeddings
    try:
        async with async_engine.begin() as conn:
            result = await conn.execute(text("""
                DELETE FROM message_embeddings
                WHERE message_id NOT IN (SELECT id FROM messages)
            """))
            msg_embeddings_deleted = result.rowcount
            cleanup_results.append({
                "type": "message_embeddings",
                "deleted": msg_embeddings_deleted
            })
            total_deleted += msg_embeddings_deleted
    except Exception as e:
        cleanup_results.append({
            "type": "message_embeddings",
            "error": str(e)
        })

    # Cleanup orphan chunk feedback
    # Note: chunk_feedback.chunk_id references document_embeddings.chunk_id (both VARCHAR)
    try:
        async with async_engine.begin() as conn:
            result = await conn.execute(text("""
                DELETE FROM chunk_feedback
                WHERE chunk_id NOT IN (SELECT chunk_id FROM document_embeddings)
            """))
            feedback_deleted = result.rowcount
            cleanup_results.append({
                "type": "chunk_feedback",
                "deleted": feedback_deleted
            })
            total_deleted += feedback_deleted
    except Exception as e:
        cleanup_results.append({
            "type": "chunk_feedback",
            "error": str(e)
        })

    # Cleanup orphan user notes (where document_id no longer exists)
    try:
        async with async_engine.begin() as conn:
            result = await conn.execute(text("""
                DELETE FROM user_notes
                WHERE document_id IS NOT NULL
                AND document_id NOT IN (SELECT id FROM documents)
            """))
            notes_deleted = result.rowcount
            cleanup_results.append({
                "type": "user_notes",
                "deleted": notes_deleted
            })
            total_deleted += notes_deleted
    except Exception as e:
        cleanup_results.append({
            "type": "user_notes",
            "error": str(e)
        })

    end_time = datetime.now()
    duration_ms = int((end_time - start_time).total_seconds() * 1000)

    return OperationResult(
        success=True,
        operation="cleanup_orphans",
        message=f"Cleanup completed. Removed {total_deleted} orphan records.",
        details={
            "total_deleted": total_deleted,
            "cleanup_results": cleanup_results
        },
        duration_ms=duration_ms
    )


@router.post("/rebuild-indexes", response_model=OperationResult)
async def rebuild_indexes():
    """
    Rebuild database indexes including pgvector indexes.

    This can improve query performance, especially for vector searches.
    """
    start_time = datetime.now()

    results = []
    errors = []

    # Get all indexes to rebuild
    async with async_engine.connect() as conn:
        try:
            result = await conn.execute(text("""
                SELECT indexname FROM pg_indexes
                WHERE schemaname = 'public'
            """))
            index_names = [row[0] for row in result.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get indexes: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get indexes: {e}")

    # Rebuild indexes using sync engine with autocommit
    from sqlalchemy import create_engine
    from core.database import DATABASE_SYNC_URL

    try:
        rebuild_engine = create_engine(DATABASE_SYNC_URL, isolation_level="AUTOCOMMIT")

        with rebuild_engine.connect() as conn:
            for idx_name in index_names:
                try:
                    conn.execute(text(f"REINDEX INDEX {idx_name}"))
                    results.append({"index": idx_name, "status": "success"})
                except Exception as e:
                    errors.append({"index": idx_name, "error": str(e)})

        rebuild_engine.dispose()

    except Exception as e:
        logger.error(f"Index rebuild failed: {e}")
        raise HTTPException(status_code=500, detail=f"Index rebuild failed: {e}")

    end_time = datetime.now()
    duration_ms = int((end_time - start_time).total_seconds() * 1000)

    success = len(errors) == 0

    return OperationResult(
        success=success,
        operation="rebuild_indexes",
        message=f"Rebuilt {len(results)} indexes" + (f" with {len(errors)} errors" if errors else ""),
        details={
            "indexes_rebuilt": results,
            "errors": errors
        },
        duration_ms=duration_ms
    )


@router.post("/reset-embeddings", response_model=OperationResult)
async def reset_embeddings():
    """
    Reset all embeddings by dropping vector indexes and truncating the embeddings table.

    Feature #228: Clean reset of embeddings for re-embedding.

    This operation:
    1. Drops HNSW vector index (if exists)
    2. Drops IVFFlat vector index (if exists)
    3. Drops any other embedding indexes
    4. Truncates document_embeddings table

    Use this before calling /reembed-all to ensure a clean slate.

    WARNING: This operation is irreversible. All existing embeddings will be lost.
    """
    start_time = datetime.now()

    results = []
    errors = []

    # Use sync engine with autocommit for DDL operations
    from sqlalchemy import create_engine
    from core.database import DATABASE_SYNC_URL

    try:
        reset_engine = create_engine(DATABASE_SYNC_URL, isolation_level="AUTOCOMMIT")

        with reset_engine.connect() as conn:
            # Drop HNSW index if exists
            try:
                conn.execute(text("DROP INDEX IF EXISTS idx_document_embeddings_embedding_hnsw"))
                results.append({"operation": "drop_hnsw_index", "status": "success"})
                logger.info("[Feature #228] Dropped HNSW index")
            except Exception as e:
                errors.append({"operation": "drop_hnsw_index", "error": str(e)})
                logger.error(f"[Feature #228] Failed to drop HNSW index: {e}")

            # Drop IVFFlat index if exists
            try:
                conn.execute(text("DROP INDEX IF EXISTS idx_document_embeddings_embedding_ivfflat"))
                results.append({"operation": "drop_ivfflat_index", "status": "success"})
                logger.info("[Feature #228] Dropped IVFFlat index")
            except Exception as e:
                errors.append({"operation": "drop_ivfflat_index", "error": str(e)})
                logger.error(f"[Feature #228] Failed to drop IVFFlat index: {e}")

            # Drop general embedding index if exists
            try:
                conn.execute(text("DROP INDEX IF EXISTS ix_document_embeddings_embedding"))
                results.append({"operation": "drop_embedding_index", "status": "success"})
                logger.info("[Feature #228] Dropped general embedding index")
            except Exception as e:
                errors.append({"operation": "drop_embedding_index", "error": str(e)})
                logger.error(f"[Feature #228] Failed to drop general embedding index: {e}")

            # Truncate document_embeddings table
            try:
                conn.execute(text("TRUNCATE document_embeddings"))
                results.append({"operation": "truncate_embeddings", "status": "success"})
                logger.info("[Feature #228] Truncated document_embeddings table")
            except Exception as e:
                errors.append({"operation": "truncate_embeddings", "error": str(e)})
                logger.error(f"[Feature #228] Failed to truncate document_embeddings: {e}")

        reset_engine.dispose()

    except Exception as e:
        logger.error(f"[Feature #228] Reset embeddings failed: {e}")
        raise HTTPException(status_code=500, detail=f"Reset embeddings failed: {e}")

    end_time = datetime.now()
    duration_ms = int((end_time - start_time).total_seconds() * 1000)

    success = len(errors) == 0 or any(r.get("operation") == "truncate_embeddings" and r.get("status") == "success" for r in results)

    return OperationResult(
        success=success,
        operation="reset_embeddings",
        message=f"Reset embeddings completed with {len(results)} operations" + (f" and {len(errors)} errors" if errors else ""),
        details={
            "operations": results,
            "errors": errors
        },
        duration_ms=duration_ms
    )


@router.post("/rebuild-bm25", response_model=OperationResult)
async def rebuild_bm25_index():
    """
    Rebuild the BM25 keyword search index from existing embeddings.

    Feature #186: Hybrid Search support.

    This is useful when:
    - The BM25 index is out of sync with the embedding store
    - After restoring from a backup
    - Initial setup for existing documents

    The BM25 index enables hybrid search that combines:
    - Vector search: Semantic similarity (good for meaning/concepts)
    - BM25 search: Keyword matching (good for acronyms, technical terms like "GMDSS")
    """
    start_time = datetime.now()

    try:
        from services.bm25_service import bm25_service

        # Get BM25 stats before rebuild
        stats_before = bm25_service.get_stats()

        # Rebuild the index from embedding store
        loop = asyncio.get_event_loop()
        chunks_indexed = await loop.run_in_executor(
            None,
            bm25_service.rebuild_from_embedding_store
        )

        # Get BM25 stats after rebuild
        stats_after = bm25_service.get_stats()

        end_time = datetime.now()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        return OperationResult(
            success=True,
            operation="rebuild_bm25_index",
            message=f"Successfully rebuilt BM25 index with {chunks_indexed} chunks",
            details={
                "chunks_indexed": chunks_indexed,
                "documents_indexed": stats_after.get("total_documents", 0),
                "before": stats_before,
                "after": stats_after
            },
            duration_ms=duration_ms
        )

    except Exception as e:
        logger.error(f"BM25 index rebuild failed: {e}")
        end_time = datetime.now()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        return OperationResult(
            success=False,
            operation="rebuild_bm25_index",
            message=f"BM25 index rebuild failed: {str(e)}",
            details={"error": str(e)},
            duration_ms=duration_ms
        )


@router.get("/bm25-stats")
async def get_bm25_stats():
    """
    Get statistics about the BM25 keyword search index.

    Feature #186: Hybrid Search support.

    Returns information about:
    - Whether the index is initialized
    - Number of chunks indexed
    - Number of documents indexed
    - Whether the index file exists
    """
    try:
        from services.bm25_service import bm25_service
        stats = bm25_service.get_stats()
        return {
            "success": True,
            **stats
        }
    except Exception as e:
        logger.error(f"Failed to get BM25 stats: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.post("/cleanup-conversations", response_model=OperationResult)
async def cleanup_conversations(request: ConversationCleanupRequest):
    """
    Delete conversations older than specified days.

    Args:
        older_than_days: Delete conversations older than this many days (default: 30)
    """
    start_time = datetime.now()

    if request.older_than_days < 1:
        raise HTTPException(status_code=400, detail="older_than_days must be at least 1")

    cutoff_date = utc_now() - timedelta(days=request.older_than_days)

    async with async_engine.begin() as conn:
        # First, delete messages belonging to old conversations
        try:
            msg_result = await conn.execute(text("""
                DELETE FROM messages
                WHERE conversation_id IN (
                    SELECT id FROM conversations
                    WHERE created_at < :cutoff_date
                )
            """), {"cutoff_date": cutoff_date})
            messages_deleted = msg_result.rowcount
        except Exception as e:
            logger.error(f"Failed to delete messages: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to delete messages: {e}")

        # Delete message embeddings for old conversations
        try:
            await conn.execute(text("""
                DELETE FROM message_embeddings
                WHERE message_id NOT IN (SELECT id FROM messages)
            """))
        except Exception:
            pass  # Table might not exist

        # Then delete the conversations
        try:
            conv_result = await conn.execute(text("""
                DELETE FROM conversations
                WHERE created_at < :cutoff_date
            """), {"cutoff_date": cutoff_date})
            conversations_deleted = conv_result.rowcount
        except Exception as e:
            logger.error(f"Failed to delete conversations: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to delete conversations: {e}")

    end_time = datetime.now()
    duration_ms = int((end_time - start_time).total_seconds() * 1000)

    return OperationResult(
        success=True,
        operation="cleanup_conversations",
        message=f"Deleted {conversations_deleted} conversations and {messages_deleted} messages older than {request.older_than_days} days.",
        details={
            "cutoff_date": cutoff_date.isoformat(),
            "older_than_days": request.older_than_days,
            "conversations_deleted": conversations_deleted,
            "messages_deleted": messages_deleted
        },
        duration_ms=duration_ms
    )


@router.post("/backup", response_class=StreamingResponse)
async def manual_backup(
    document_store_pg=Depends(get_document_store),
    collection_store_pg=Depends(get_collection_store),
    conversation_store_pg: ConversationStorePostgres = Depends(get_conversation_store),
    message_store_pg: MessageStorePostgres = Depends(get_message_store)
):
    """
    Create a manual backup of all data.

    Returns a ZIP file containing:
    - manifest.json: Backup metadata
    - documents.json: All document metadata
    - collections.json: All collections
    - conversations.json: All conversations with messages
    - settings.json: Non-sensitive settings
    - files/: Directory with all uploaded files
    """
    # This is essentially the same as the backup API, but placed here for convenience
    from api.backup import create_backup
    return await create_backup(
        document_store_pg=document_store_pg,
        collection_store_pg=collection_store_pg,
        conversation_store_pg=conversation_store_pg,
        message_store_pg=message_store_pg
    )
