"""
Delete audit + retention policy endpoints.

Feature #353: Refactored from admin_maintenance.py.
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional, List

from fastapi import APIRouter
from pydantic import BaseModel

from ._shared import OperationResult

logger = logging.getLogger(__name__)
router = APIRouter()


# ==================== Local Models ====================

class EmbeddingDeleteAuditEntry(BaseModel):
    """Response model for embedding delete audit entry."""
    id: int
    document_id: str
    chunk_count: int
    deleted_at: str
    source: str
    user_action: Optional[str] = None
    context: Optional[str] = None
    api_endpoint: Optional[str] = None


class EmbeddingDeleteAuditResponse(BaseModel):
    """Response model for embedding delete audit list."""
    success: bool
    total_entries: int
    entries: List[Dict[str, Any]]
    summary: Dict[str, Any]


class BulkDeleteAlertResponse(BaseModel):
    """Response model for bulk delete alert check."""
    has_alerts: bool
    alerts: List[Dict[str, Any]]
    threshold: int
    timeframe_hours: int


class AuditRetentionResponse(BaseModel):
    """Response model for audit retention cleanup."""
    success: bool
    operation: str
    message: str
    deleted_count: int
    oldest_remaining: Optional[datetime] = None
    retention_days: int


# ==================== Endpoints ====================

@router.get("/embedding-delete-audit", response_model=EmbeddingDeleteAuditResponse)
async def get_embedding_delete_audit(
    limit: int = 100,
    offset: int = 0,
    document_id: Optional[str] = None,
    source: Optional[str] = None,
    hours: Optional[int] = 24
):
    """
    Get recent embedding deletion audit entries (Feature #252).

    This endpoint provides visibility into all embedding deletions,
    helping diagnose unexpected data loss.

    Args:
        limit: Maximum number of entries to return (default: 100)
        offset: Number of entries to skip (default: 0)
        document_id: Filter by specific document ID (optional)
        source: Filter by deletion source (optional)
        hours: Filter entries from last N hours (default: 24)

    Returns:
        List of audit entries with summary statistics
    """
    try:
        from core.database import SessionLocal
        from sqlalchemy import text as sa_text

        with SessionLocal() as session:
            # Check if table exists
            result = session.execute(sa_text("""
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'audit_embeddings_delete'
            """))
            if result.rowcount == 0:
                return EmbeddingDeleteAuditResponse(
                    success=False,
                    total_entries=0,
                    entries=[],
                    summary={"error": "Audit table not created. Run migration 011."}
                )

            # Build query with filters
            where_clauses = []
            params = {"limit": limit, "offset": offset}

            if hours:
                where_clauses.append("deleted_at >= NOW() - INTERVAL ':hours hours'")
                params["hours"] = hours

            if document_id:
                where_clauses.append("document_id = :document_id")
                params["document_id"] = document_id

            if source:
                where_clauses.append("source = :source")
                params["source"] = source

            where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

            # Get total count
            count_query = f"""
                SELECT COUNT(*) FROM audit_embeddings_delete
                {where_sql.replace(':hours hours', f'{hours} hours')}
            """
            count_result = session.execute(sa_text(count_query), params)
            total_count = count_result.scalar() or 0

            # Get audit entries
            query = f"""
                SELECT
                    id, document_id, chunk_count, deleted_at,
                    source, user_action, context, api_endpoint
                FROM audit_embeddings_delete
                {where_sql.replace(':hours hours', f'{hours} hours')}
                ORDER BY deleted_at DESC
                LIMIT :limit OFFSET :offset
            """
            result = session.execute(sa_text(query), params)
            entries = [
                {
                    "id": row[0],
                    "document_id": row[1],
                    "chunk_count": row[2],
                    "deleted_at": row[3].isoformat() if row[3] else None,
                    "source": row[4],
                    "user_action": row[5],
                    "context": row[6],
                    "api_endpoint": row[7]
                }
                for row in result.fetchall()
            ]

            # Get summary statistics
            summary_query = f"""
                SELECT
                    source,
                    COUNT(*) as entry_count,
                    SUM(chunk_count) as total_chunks,
                    COUNT(DISTINCT document_id) as documents_affected
                FROM audit_embeddings_delete
                {where_sql.replace(':hours hours', f'{hours} hours')}
                GROUP BY source
                ORDER BY total_chunks DESC
            """
            summary_result = session.execute(sa_text(summary_query), params)
            by_source = {
                row[0]: {
                    "entry_count": row[1],
                    "total_chunks": row[2],
                    "documents_affected": row[3]
                }
                for row in summary_result.fetchall()
            }

            # Total chunks deleted
            total_chunks = sum(s["total_chunks"] for s in by_source.values())
            total_documents = len(set(e["document_id"] for e in entries))

            summary = {
                "total_entries": total_count,
                "total_chunks_deleted": total_chunks,
                "total_documents_affected": total_documents,
                "by_source": by_source,
                "timeframe_hours": hours
            }

            logger.info(f"[Feature #252] Retrieved {len(entries)} audit entries (total: {total_count})")

            return EmbeddingDeleteAuditResponse(
                success=True,
                total_entries=total_count,
                entries=entries,
                summary=summary
            )

    except Exception as e:
        logger.error(f"[Feature #252] Error getting embedding delete audit: {e}")
        return EmbeddingDeleteAuditResponse(
            success=False,
            total_entries=0,
            entries=[],
            summary={"error": str(e)}
        )


@router.get("/embedding-delete-alerts", response_model=BulkDeleteAlertResponse)
async def check_bulk_delete_alerts(
    threshold: int = 100,
    timeframe_hours: int = 1
):
    """
    Check for bulk deletion alerts (Feature #252).

    Alerts are generated when more than N embeddings are deleted
    without a corresponding re-embed operation within the timeframe.

    Args:
        threshold: Alert if more than this many embeddings deleted (default: 100)
        timeframe_hours: Check deletions within this timeframe (default: 1 hour)

    Returns:
        Alert status and details
    """
    try:
        from core.database import SessionLocal
        from sqlalchemy import text as sa_text

        with SessionLocal() as session:
            # Check if table exists
            result = session.execute(sa_text("""
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'audit_embeddings_delete'
            """))
            if result.rowcount == 0:
                return BulkDeleteAlertResponse(
                    has_alerts=False,
                    alerts=[],
                    threshold=threshold,
                    timeframe_hours=timeframe_hours
                )

            # Find documents with bulk deletions that weren't re-embeds
            query = sa_text(f"""
                WITH recent_deletes AS (
                    SELECT
                        document_id,
                        SUM(chunk_count) as total_deleted,
                        MIN(deleted_at) as first_delete,
                        MAX(deleted_at) as last_delete,
                        ARRAY_AGG(DISTINCT source) as sources
                    FROM audit_embeddings_delete
                    WHERE deleted_at >= NOW() - INTERVAL '{timeframe_hours} hours'
                    GROUP BY document_id
                    HAVING SUM(chunk_count) > :threshold
                )
                SELECT
                    rd.document_id,
                    rd.total_deleted,
                    rd.first_delete,
                    rd.last_delete,
                    rd.sources,
                    d.title as document_title,
                    COALESCE(
                        (SELECT COUNT(*) FROM document_embeddings de
                         WHERE de.document_id = rd.document_id
                         AND de.status = 'active'),
                        0
                    ) as current_embeddings
                FROM recent_deletes rd
                LEFT JOIN documents d ON d.id = rd.document_id
                WHERE NOT ('reembed' = ANY(rd.sources) AND array_length(rd.sources, 1) = 1)
                ORDER BY rd.total_deleted DESC
            """)

            result = session.execute(query, {"threshold": threshold})
            alerts = []

            for row in result.fetchall():
                document_id = row[0]
                total_deleted = row[1]
                first_delete = row[2]
                last_delete = row[3]
                sources = row[4] if row[4] else []
                document_title = row[5]
                current_embeddings = row[6]

                # Check if this looks suspicious
                is_suspicious = (
                    'reembed' not in sources and
                    current_embeddings == 0 and
                    total_deleted > threshold
                )

                alerts.append({
                    "document_id": document_id,
                    "document_title": document_title,
                    "total_deleted": total_deleted,
                    "current_embeddings": current_embeddings,
                    "first_delete": first_delete.isoformat() if first_delete else None,
                    "last_delete": last_delete.isoformat() if last_delete else None,
                    "sources": list(sources),
                    "is_suspicious": is_suspicious,
                    "reason": "Large deletion without re-embed, document has no embeddings" if is_suspicious else "Bulk deletion detected"
                })

            has_alerts = len(alerts) > 0

            if has_alerts:
                logger.warning(f"[Feature #252] ALERT: {len(alerts)} bulk deletion events detected exceeding threshold of {threshold}")

            return BulkDeleteAlertResponse(
                has_alerts=has_alerts,
                alerts=alerts,
                threshold=threshold,
                timeframe_hours=timeframe_hours
            )

    except Exception as e:
        logger.error(f"[Feature #252] Error checking bulk delete alerts: {e}")
        return BulkDeleteAlertResponse(
            has_alerts=False,
            alerts=[{"error": str(e)}],
            threshold=threshold,
            timeframe_hours=timeframe_hours
        )


@router.post("/log-embedding-delete", response_model=OperationResult)
async def log_embedding_delete_manual(
    document_id: str,
    chunk_count: int,
    source: str,
    user_action: Optional[str] = None,
    api_endpoint: Optional[str] = None
):
    """
    Manually log an embedding deletion (Feature #252).

    This endpoint allows the application to log embedding deletions
    with more context than the PostgreSQL trigger can provide.

    Call this from API endpoints that delete embeddings to provide
    better audit trails.

    Args:
        document_id: The document ID whose embeddings were deleted
        chunk_count: Number of chunks deleted
        source: Source of deletion (manual, reembed, document_delete, etc.)
        user_action: Description of the user action (optional)
        api_endpoint: API endpoint that triggered the deletion (optional)

    Returns:
        OperationResult with success status
    """
    try:
        from core.database import SessionLocal
        from sqlalchemy import text as sa_text

        with SessionLocal() as session:
            # Check if table exists
            result = session.execute(sa_text("""
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'audit_embeddings_delete'
            """))
            if result.rowcount == 0:
                return OperationResult(
                    success=False,
                    operation="log_embedding_delete",
                    message="Audit table not created. Run migration 011."
                )

            # Insert audit entry
            session.execute(sa_text("""
                INSERT INTO audit_embeddings_delete (
                    document_id, chunk_count, deleted_at, source,
                    user_action, api_endpoint
                ) VALUES (
                    :document_id, :chunk_count, NOW(), :source,
                    :user_action, :api_endpoint
                )
            """), {
                "document_id": document_id,
                "chunk_count": chunk_count,
                "source": source,
                "user_action": user_action,
                "api_endpoint": api_endpoint
            })
            session.commit()

            logger.info(f"[Feature #252] Logged embedding deletion: doc={document_id}, chunks={chunk_count}, source={source}")

            return OperationResult(
                success=True,
                operation="log_embedding_delete",
                message=f"Logged deletion of {chunk_count} embeddings for document {document_id}",
                details={
                    "document_id": document_id,
                    "chunk_count": chunk_count,
                    "source": source
                }
            )

    except Exception as e:
        logger.error(f"[Feature #252] Error logging embedding delete: {e}")
        return OperationResult(
            success=False,
            operation="log_embedding_delete",
            message=f"Failed to log deletion: {str(e)}"
        )


@router.post("/aggregate-audit-logs", response_model=OperationResult)
async def aggregate_audit_logs(
    interval_minutes: int = 5
):
    """
    Aggregate old audit log entries (Feature #252).

    This consolidates multiple single-row audit entries (from the trigger)
    into summary entries to reduce audit log size while preserving history.

    Args:
        interval_minutes: Aggregate entries older than this many minutes (default: 5)

    Returns:
        OperationResult with aggregation stats
    """
    try:
        from core.database import SessionLocal
        from sqlalchemy import text as sa_text

        with SessionLocal() as session:
            # Check if function exists
            result = session.execute(sa_text("""
                SELECT 1 FROM pg_proc
                WHERE proname = 'aggregate_audit_embedding_deletes'
            """))
            if result.rowcount == 0:
                return OperationResult(
                    success=False,
                    operation="aggregate_audit_logs",
                    message="Aggregation function not created. Run migration 011."
                )

            # Call the aggregation function
            result = session.execute(sa_text(f"""
                SELECT * FROM aggregate_audit_embedding_deletes(INTERVAL '{interval_minutes} minutes')
            """))
            row = result.fetchone()
            session.commit()

            aggregated_count = row[0] if row else 0
            documents_affected = row[1] if row else 0

            logger.info(f"[Feature #252] Aggregated {aggregated_count} audit entries for {documents_affected} documents")

            return OperationResult(
                success=True,
                operation="aggregate_audit_logs",
                message=f"Aggregated {aggregated_count} entries for {documents_affected} documents",
                details={
                    "aggregated_count": aggregated_count,
                    "documents_affected": documents_affected,
                    "interval_minutes": interval_minutes
                }
            )

    except Exception as e:
        logger.error(f"[Feature #252] Error aggregating audit logs: {e}")
        return OperationResult(
            success=False,
            operation="aggregate_audit_logs",
            message=f"Aggregation failed: {str(e)}"
        )


@router.post("/audit-retention-cleanup", response_model=AuditRetentionResponse)
async def cleanup_audit_retention(
    retention_days: int = 30
):
    """
    Apply retention policy to audit_embeddings_delete table (Feature #266).

    Deletes audit records older than the specified number of days.
    Default retention is 30 days.

    Args:
        retention_days: Number of days to retain audit records (default: 30)

    Returns:
        AuditRetentionResponse with cleanup statistics
    """
    try:
        from core.database import SessionLocal
        from sqlalchemy import text as sa_text

        # Validate retention_days
        if retention_days < 1:
            return AuditRetentionResponse(
                success=False,
                operation="audit_retention_cleanup",
                message="retention_days must be at least 1",
                deleted_count=0,
                retention_days=retention_days
            )

        if retention_days > 365:
            return AuditRetentionResponse(
                success=False,
                operation="audit_retention_cleanup",
                message="retention_days cannot exceed 365",
                deleted_count=0,
                retention_days=retention_days
            )

        with SessionLocal() as session:
            # Check if table exists
            result = session.execute(sa_text("""
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'audit_embeddings_delete'
            """))
            if result.rowcount == 0:
                return AuditRetentionResponse(
                    success=False,
                    operation="audit_retention_cleanup",
                    message="audit_embeddings_delete table not found. Run migration 011.",
                    deleted_count=0,
                    retention_days=retention_days
                )

            # Check if function exists
            result = session.execute(sa_text("""
                SELECT 1 FROM pg_proc
                WHERE proname = 'cleanup_audit_retention'
            """))
            if result.rowcount == 0:
                # Fall back to direct SQL if function not available
                logger.info(f"[Feature #266] Using direct SQL for retention cleanup (function not found)")
                cutoff_result = session.execute(sa_text(f"""
                    DELETE FROM audit_embeddings_delete
                    WHERE deleted_at < NOW() - INTERVAL '{retention_days} days'
                    RETURNING id
                """))
                deleted_count = cutoff_result.rowcount

                # Get oldest remaining
                oldest_result = session.execute(sa_text("""
                    SELECT MIN(deleted_at) FROM audit_embeddings_delete
                """))
                oldest_row = oldest_result.fetchone()
                oldest_remaining = oldest_row[0] if oldest_row and oldest_row[0] else None

                session.commit()
            else:
                # Use the retention function
                result = session.execute(sa_text(f"""
                    SELECT * FROM cleanup_audit_retention({retention_days})
                """))
                row = result.fetchone()
                session.commit()

                deleted_count = row[0] if row else 0
                oldest_remaining = row[1] if row else None

            logger.info(f"[Feature #266] Retention cleanup complete: deleted {deleted_count} records older than {retention_days} days")

            return AuditRetentionResponse(
                success=True,
                operation="audit_retention_cleanup",
                message=f"Deleted {deleted_count} audit records older than {retention_days} days",
                deleted_count=deleted_count,
                oldest_remaining=oldest_remaining,
                retention_days=retention_days
            )

    except Exception as e:
        logger.error(f"[Feature #266] Error in retention cleanup: {e}")
        return AuditRetentionResponse(
            success=False,
            operation="audit_retention_cleanup",
            message=f"Retention cleanup failed: {str(e)}",
            deleted_count=0,
            retention_days=retention_days
        )


@router.get("/audit-retention-stats")
async def get_audit_retention_stats():
    """
    Get statistics about audit_embeddings_delete records for retention planning (Feature #266).

    Returns count of records by age bracket to help decide on retention policy.
    """
    try:
        from core.database import SessionLocal
        from sqlalchemy import text as sa_text

        with SessionLocal() as session:
            # Check if table exists
            result = session.execute(sa_text("""
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'audit_embeddings_delete'
            """))
            if result.rowcount == 0:
                return {
                    "success": False,
                    "message": "audit_embeddings_delete table not found"
                }

            # Get age distribution
            result = session.execute(sa_text("""
                SELECT
                    COUNT(*) FILTER (WHERE deleted_at >= NOW() - INTERVAL '1 day') as last_day,
                    COUNT(*) FILTER (WHERE deleted_at >= NOW() - INTERVAL '7 days') as last_week,
                    COUNT(*) FILTER (WHERE deleted_at >= NOW() - INTERVAL '30 days') as last_30_days,
                    COUNT(*) FILTER (WHERE deleted_at < NOW() - INTERVAL '30 days') as older_than_30_days,
                    COUNT(*) as total,
                    MIN(deleted_at) as oldest_record,
                    MAX(deleted_at) as newest_record,
                    SUM(chunk_count) as total_chunks_logged
                FROM audit_embeddings_delete
            """))
            row = result.fetchone()

            return {
                "success": True,
                "stats": {
                    "last_day": row[0] or 0,
                    "last_week": row[1] or 0,
                    "last_30_days": row[2] or 0,
                    "older_than_30_days": row[3] or 0,
                    "total": row[4] or 0,
                    "oldest_record": row[5].isoformat() if row[5] else None,
                    "newest_record": row[6].isoformat() if row[6] else None,
                    "total_chunks_logged": row[7] or 0
                },
                "recommendation": {
                    "records_to_delete_at_30_days": row[3] or 0,
                    "default_retention_days": 30
                }
            }

    except Exception as e:
        logger.error(f"[Feature #266] Error getting retention stats: {e}")
        return {
            "success": False,
            "message": f"Error: {str(e)}"
        }
