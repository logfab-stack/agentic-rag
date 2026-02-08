"""
Soft delete migration & cleanup endpoints.

Feature #353: Refactored from admin_maintenance.py.
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from sqlalchemy import text

from core.store import embedding_store

from ._shared import OperationResult

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/apply-soft-delete-migration", response_model=OperationResult)
async def apply_soft_delete_migration():
    """
    Apply the soft delete migration (Feature #249) to add status column to document_embeddings.

    This is a one-time operation to add:
    - status column (active, pending_delete, archived) with default 'active'
    - pending_delete_at timestamp for cleanup scheduling
    - Indexes for efficient filtering

    Safe to run multiple times - will skip if columns already exist.
    """
    start_time = datetime.now()

    try:
        from core.database import SessionLocal

        db = SessionLocal()
        try:
            # Check if columns already exist
            result = db.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'document_embeddings'
                AND column_name IN ('status', 'pending_delete_at')
            """))
            existing_columns = [row[0] for row in result]

            operations_performed = []

            # Add status column if not exists
            if 'status' not in existing_columns:
                db.execute(text("""
                    ALTER TABLE document_embeddings
                    ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'active'
                """))
                operations_performed.append("Added status column")
                logger.info("[Feature #249] Added status column to document_embeddings")
            else:
                operations_performed.append("status column already exists")

            # Add pending_delete_at column if not exists
            if 'pending_delete_at' not in existing_columns:
                db.execute(text("""
                    ALTER TABLE document_embeddings
                    ADD COLUMN pending_delete_at TIMESTAMP WITH TIME ZONE NULL
                """))
                operations_performed.append("Added pending_delete_at column")
                logger.info("[Feature #249] Added pending_delete_at column to document_embeddings")
            else:
                operations_performed.append("pending_delete_at column already exists")

            # Create index on status if not exists
            result = db.execute(text("""
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'ix_document_embeddings_status'
            """))
            if result.rowcount == 0:
                db.execute(text("""
                    CREATE INDEX ix_document_embeddings_status
                    ON document_embeddings(status)
                """))
                operations_performed.append("Created status index")
                logger.info("[Feature #249] Created index ix_document_embeddings_status")
            else:
                operations_performed.append("status index already exists")

            # Create partial index for pending cleanup if not exists
            result = db.execute(text("""
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'ix_document_embeddings_pending_cleanup'
            """))
            if result.rowcount == 0:
                db.execute(text("""
                    CREATE INDEX ix_document_embeddings_pending_cleanup
                    ON document_embeddings(pending_delete_at)
                    WHERE status = 'pending_delete' AND pending_delete_at IS NOT NULL
                """))
                operations_performed.append("Created pending cleanup partial index")
                logger.info("[Feature #249] Created partial index for pending_delete cleanup")
            else:
                operations_performed.append("pending cleanup index already exists")

            db.commit()

            end_time = datetime.now()
            duration_ms = int((end_time - start_time).total_seconds() * 1000)

            return OperationResult(
                success=True,
                message=f"Feature #249 soft delete migration applied: {', '.join(operations_performed)}",
                duration_ms=duration_ms
            )

        finally:
            db.close()

    except Exception as e:
        logger.error(f"[Feature #249] Error applying soft delete migration: {e}")
        end_time = datetime.now()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)
        return OperationResult(
            success=False,
            message=f"Migration failed: {str(e)}",
            duration_ms=duration_ms
        )


@router.post("/cleanup-stale-pending-delete", response_model=OperationResult)
async def cleanup_stale_pending_delete():
    """
    Cleanup stale pending_delete embeddings (Feature #249).

    Permanently deletes embeddings that have been in pending_delete status
    for more than 24 hours. This is a safety cleanup for:
    - Aborted re-embed operations
    - System crashes during re-embed
    - Orphaned pending_delete rows

    Safe to run periodically (e.g., daily cron job or manual cleanup).
    """
    start_time = datetime.now()

    try:
        from core.database import SessionLocal

        db = SessionLocal()
        try:
            # Check if status column exists (migration may not have run yet)
            result = db.execute(text("""
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'document_embeddings' AND column_name = 'status'
            """))
            if result.rowcount == 0:
                return OperationResult(
                    success=False,
                    message="Soft delete migration not applied yet. Run /apply-soft-delete-migration first.",
                    duration_ms=0
                )

            # Delete stale pending_delete rows (older than 24 hours)
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)

            result = db.execute(text("""
                DELETE FROM document_embeddings
                WHERE status = 'pending_delete'
                AND pending_delete_at IS NOT NULL
                AND pending_delete_at < :cutoff_time
                RETURNING id
            """), {"cutoff_time": cutoff_time})

            deleted_count = result.rowcount
            db.commit()

            end_time = datetime.now()
            duration_ms = int((end_time - start_time).total_seconds() * 1000)

            if deleted_count > 0:
                logger.info(f"[Feature #249] Cleaned up {deleted_count} stale pending_delete embeddings")
                message = f"Cleaned up {deleted_count} stale pending_delete embeddings (older than 24h)"
            else:
                message = "No stale pending_delete embeddings found"

            return OperationResult(
                success=True,
                message=message,
                duration_ms=duration_ms
            )

        finally:
            db.close()

    except Exception as e:
        logger.error(f"[Feature #249] Error cleaning up stale pending_delete embeddings: {e}")
        end_time = datetime.now()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)
        return OperationResult(
            success=False,
            message=f"Cleanup failed: {str(e)}",
            duration_ms=duration_ms
        )


@router.get("/soft-delete-stats")
async def get_soft_delete_stats():
    """
    Get statistics about embedding soft delete status (Feature #249).

    Returns counts of embeddings by status (active, pending_delete, archived)
    and any stale pending_delete rows that are due for cleanup.
    """
    try:
        from core.database import SessionLocal

        db = SessionLocal()
        try:
            # Check if status column exists
            result = db.execute(text("""
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'document_embeddings' AND column_name = 'status'
            """))
            if result.rowcount == 0:
                return {
                    "migration_applied": False,
                    "message": "Soft delete migration not applied yet",
                    "total_embeddings": embedding_store.get_chunk_count()
                }

            # Get counts by status
            result = db.execute(text("""
                SELECT status, COUNT(*) as count
                FROM document_embeddings
                GROUP BY status
            """))
            status_counts = {row[0]: row[1] for row in result}

            # Get count of stale pending_delete (older than 24h)
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
            result = db.execute(text("""
                SELECT COUNT(*) FROM document_embeddings
                WHERE status = 'pending_delete'
                AND pending_delete_at IS NOT NULL
                AND pending_delete_at < :cutoff_time
            """), {"cutoff_time": cutoff_time})
            stale_count = result.scalar() or 0

            return {
                "migration_applied": True,
                "status_counts": status_counts,
                "active": status_counts.get("active", 0),
                "pending_delete": status_counts.get("pending_delete", 0),
                "archived": status_counts.get("archived", 0),
                "stale_pending_delete_count": stale_count,
                "stale_pending_delete_message": f"{stale_count} embeddings ready for cleanup (>24h old)" if stale_count > 0 else "No stale embeddings"
            }

        finally:
            db.close()

    except Exception as e:
        logger.error(f"[Feature #249] Error getting soft delete stats: {e}")
        return {
            "error": str(e),
            "migration_applied": False
        }
