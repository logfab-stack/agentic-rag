"""
Dashboard metrics + response cache endpoints.

Feature #353: Refactored from admin_maintenance.py.
"""

import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from core.database import async_engine
from core.store import settings_store

from ._shared import get_table_row_counts, get_database_size

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/cache/clear")
async def clear_response_cache():
    """
    Feature #352: Clear all cached responses.

    Manually invalidates the entire response cache.
    Returns the number of entries deleted.
    """
    try:
        from services.response_cache_service import response_cache_service
        count = response_cache_service.invalidate_all()
        return {"success": True, "entries_deleted": count}
    except Exception as e:
        logger.error(f"[Feature #352] Error clearing response cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cache/stats")
async def get_cache_stats():
    """
    Feature #352: Get response cache statistics.

    Returns total entries, hit counts, and other cache metrics.
    """
    try:
        from services.response_cache_service import response_cache_service
        stats = await response_cache_service.get_stats()
        return stats
    except Exception as e:
        logger.error(f"[Feature #352] Error getting cache stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dashboard")
async def get_dashboard():
    """
    Feature #355: System Dashboard with Key Metrics.

    Aggregates all key metrics into a single response for the dashboard UI:
    - Document counts (total, structured, unstructured, with embeddings)
    - Chunk and BM25 index counts
    - Conversation and message counts
    - Database storage size
    - Active model configuration
    - Response feedback statistics
    - System resource usage (memory, disk)
    - Embedding coverage percentage
    """
    import psutil
    import shutil

    try:
        # 1. Table row counts (reuse existing helper)
        table_counts = await get_table_row_counts()

        # 2. Document type breakdown
        doc_total = table_counts.get("documents", 0)
        unstructured_count = 0
        structured_count = 0
        with_embeddings_count = 0

        try:
            async with async_engine.connect() as conn:
                # Count by document type
                result = await conn.execute(text(
                    "SELECT document_type, COUNT(*) FROM documents GROUP BY document_type"
                ))
                for row in result.fetchall():
                    dtype = (row[0] or "").lower()
                    if dtype in ("unstructured", "text"):
                        unstructured_count += row[1]
                    elif dtype in ("structured", "tabular"):
                        structured_count += row[1]
                    else:
                        unstructured_count += row[1]

                # Count documents that have embeddings (chunk_count > 0)
                result = await conn.execute(text(
                    "SELECT COUNT(*) FROM documents WHERE chunk_count > 0"
                ))
                row = result.fetchone()
                with_embeddings_count = row[0] if row else 0
        except Exception as e:
            logger.warning(f"[Feature #355] Error getting document breakdown: {e}")

        # 3. Chunk count from document_embeddings
        chunk_total = table_counts.get("document_embeddings", 0)

        # 4. BM25 index count
        bm25_indexed = 0
        try:
            from services.bm25_service import bm25_service
            if hasattr(bm25_service, 'get_index_count'):
                bm25_indexed = bm25_service.get_index_count()
            elif hasattr(bm25_service, 'document_count'):
                bm25_indexed = bm25_service.document_count
        except Exception:
            pass

        # 5. Database size (reuse existing helper)
        db_size_info = await get_database_size()

        # 6. Active models from settings
        llm_model = settings_store.get("llm_model", "gpt-4o")
        embedding_model = settings_store.get("embedding_model", "text-embedding-3-small")
        chunking_model = settings_store.get("chunking_llm_model", "")

        # 7. Response feedback stats
        feedback_total = 0
        feedback_positive = 0
        feedback_negative = 0
        try:
            async with async_engine.connect() as conn:
                result = await conn.execute(text(
                    "SELECT COUNT(*), "
                    "COALESCE(SUM(CASE WHEN rating > 0 THEN 1 ELSE 0 END), 0), "
                    "COALESCE(SUM(CASE WHEN rating < 0 THEN 1 ELSE 0 END), 0) "
                    "FROM response_feedback"
                ))
                row = result.fetchone()
                if row:
                    feedback_total = row[0] or 0
                    feedback_positive = row[1] or 0
                    feedback_negative = row[2] or 0
        except Exception as e:
            logger.warning(f"[Feature #355] Error getting feedback stats: {e}")

        positive_rate = round((feedback_positive / feedback_total * 100), 1) if feedback_total > 0 else 0.0

        # 8. System metrics
        process = psutil.Process()
        memory_info = process.memory_info()
        memory_mb = round(memory_info.rss / (1024 * 1024), 1)
        memory_percent = round(psutil.virtual_memory().percent, 1)
        disk_usage = shutil.disk_usage("/")
        disk_percent = round(disk_usage.used / disk_usage.total * 100, 1)

        # 9. Embedding coverage
        total_unstructured = unstructured_count if unstructured_count > 0 else max(doc_total - structured_count, 0)
        coverage_percent = round((with_embeddings_count / total_unstructured * 100), 1) if total_unstructured > 0 else 0.0

        # 10. Response cache stats (Feature #352)
        cache_stats = {"total_entries": 0, "total_hits": 0, "avg_hits": 0, "oldest_entry": None, "expired_entries": 0}
        try:
            from services.response_cache_service import response_cache_service
            cache_stats = await response_cache_service.get_stats()
        except Exception as e:
            logger.warning(f"[Feature #352] Error getting cache stats for dashboard: {e}")

        return {
            "documents": {
                "total": doc_total,
                "unstructured": unstructured_count,
                "structured": structured_count,
                "with_embeddings": with_embeddings_count
            },
            "chunks": {
                "total": chunk_total,
                "bm25_indexed": bm25_indexed
            },
            "conversations": {
                "total": table_counts.get("conversations", 0),
                "messages": table_counts.get("messages", 0)
            },
            "storage": {
                "db_size": db_size_info.get("database_size_pretty", "Unknown"),
                "db_size_bytes": db_size_info.get("database_size_bytes", 0)
            },
            "models": {
                "llm": llm_model,
                "embedding": embedding_model,
                "chunking": chunking_model or llm_model
            },
            "feedback": {
                "total": feedback_total,
                "positive": feedback_positive,
                "negative": feedback_negative,
                "positive_rate": positive_rate
            },
            "system": {
                "memory_mb": memory_mb,
                "memory_percent": memory_percent,
                "disk_percent": disk_percent
            },
            "embedding_coverage": {
                "total_unstructured": total_unstructured,
                "with_embeddings": with_embeddings_count,
                "percent": coverage_percent
            },
            "cache": cache_stats
        }

    except Exception as e:
        logger.error(f"[Feature #355] Dashboard error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load dashboard: {str(e)}")
