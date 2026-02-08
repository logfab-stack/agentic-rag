"""
Document Audit Logging Service

Feature #267: Add detailed audit logging for document operations

Provides functions to log document lifecycle events:
- document_uploaded: Document was uploaded to the system
- embedding_started: Embedding generation started
- embedding_completed: Embedding generation completed successfully
- embedding_failed: Embedding generation failed
- document_deleted: Document was deleted
- document_re_embed_started: Re-embedding operation started
- document_re_embed_completed: Re-embedding operation completed

Each log entry includes metadata: document_id, document_name, file_size,
chunk_count, model_used, duration_ms.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from models.db_models import DBAuditLog

logger = logging.getLogger(__name__)

# Document audit action constants
AUDIT_ACTION_DOCUMENT_UPLOADED = "document_uploaded"
AUDIT_ACTION_EMBEDDING_STARTED = "embedding_started"
AUDIT_ACTION_EMBEDDING_COMPLETED = "embedding_completed"
AUDIT_ACTION_EMBEDDING_FAILED = "embedding_failed"
AUDIT_ACTION_DOCUMENT_DELETED = "document_deleted"
AUDIT_ACTION_DOCUMENT_RE_EMBED_STARTED = "document_re_embed_started"
AUDIT_ACTION_DOCUMENT_RE_EMBED_COMPLETED = "document_re_embed_completed"

# Status constants
AUDIT_STATUS_COMPLETED = "completed"
AUDIT_STATUS_FAILED = "failed"
AUDIT_STATUS_INITIATED = "initiated"
AUDIT_STATUS_IN_PROGRESS = "in_progress"


async def log_document_event(
    db: AsyncSession,
    action: str,
    status: str,
    document_id: Optional[str] = None,
    document_name: Optional[str] = None,
    file_size: Optional[int] = None,
    chunk_count: Optional[int] = None,
    model_used: Optional[str] = None,
    duration_ms: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None
) -> int:
    """
    Log a document lifecycle event to the audit log.

    Args:
        db: Database session
        action: The action being performed (use AUDIT_ACTION_* constants)
        status: Status of the action (use AUDIT_STATUS_* constants)
        document_id: UUID of the document
        document_name: Document title
        file_size: File size in bytes
        chunk_count: Number of chunks/embeddings generated
        model_used: Embedding model used
        duration_ms: Operation duration in milliseconds
        details: Additional JSON-serializable details
        ip_address: Client IP address
        user_agent: Browser user agent

    Returns:
        The ID of the created audit log entry
    """
    try:
        details_json = json.dumps(details) if details else None

        result = await db.execute(
            text("""
                INSERT INTO audit_log (
                    action, status, details, ip_address, user_agent,
                    document_id, document_name, file_size, chunk_count,
                    model_used, duration_ms, created_at
                ) VALUES (
                    :action, :status, :details, :ip_address, :user_agent,
                    :document_id, :document_name, :file_size, :chunk_count,
                    :model_used, :duration_ms, NOW()
                )
                RETURNING id
            """),
            {
                "action": action,
                "status": status,
                "details": details_json,
                "ip_address": ip_address,
                "user_agent": user_agent,
                "document_id": document_id,
                "document_name": document_name,
                "file_size": file_size,
                "chunk_count": chunk_count,
                "model_used": model_used,
                "duration_ms": duration_ms
            }
        )
        row = result.fetchone()
        audit_id = row[0] if row else None

        logger.info(
            f"[Audit] {action} - {status} - doc:{document_id} - "
            f"name:{document_name} - chunks:{chunk_count} - model:{model_used}"
        )
        return audit_id

    except Exception as e:
        logger.error(f"Failed to log document event: {e}")
        # Don't raise - audit logging should not break main flow
        return None


async def log_document_uploaded(
    db: AsyncSession,
    document_id: str,
    document_name: str,
    file_size: int,
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None
) -> int:
    """Log that a document was uploaded."""
    return await log_document_event(
        db=db,
        action=AUDIT_ACTION_DOCUMENT_UPLOADED,
        status=AUDIT_STATUS_COMPLETED,
        document_id=document_id,
        document_name=document_name,
        file_size=file_size,
        details=details,
        ip_address=ip_address,
        user_agent=user_agent
    )


async def log_embedding_started(
    db: AsyncSession,
    document_id: str,
    document_name: str,
    model_used: str,
    file_size: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None
) -> int:
    """Log that embedding generation has started for a document."""
    return await log_document_event(
        db=db,
        action=AUDIT_ACTION_EMBEDDING_STARTED,
        status=AUDIT_STATUS_IN_PROGRESS,
        document_id=document_id,
        document_name=document_name,
        model_used=model_used,
        file_size=file_size,
        details=details
    )


async def log_embedding_completed(
    db: AsyncSession,
    document_id: str,
    document_name: str,
    chunk_count: int,
    model_used: str,
    duration_ms: int,
    file_size: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None
) -> int:
    """Log that embedding generation completed successfully."""
    return await log_document_event(
        db=db,
        action=AUDIT_ACTION_EMBEDDING_COMPLETED,
        status=AUDIT_STATUS_COMPLETED,
        document_id=document_id,
        document_name=document_name,
        chunk_count=chunk_count,
        model_used=model_used,
        duration_ms=duration_ms,
        file_size=file_size,
        details=details
    )


async def log_embedding_failed(
    db: AsyncSession,
    document_id: str,
    document_name: str,
    model_used: str,
    duration_ms: Optional[int] = None,
    error_message: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None
) -> int:
    """Log that embedding generation failed."""
    if details is None:
        details = {}
    if error_message:
        details["error"] = error_message

    return await log_document_event(
        db=db,
        action=AUDIT_ACTION_EMBEDDING_FAILED,
        status=AUDIT_STATUS_FAILED,
        document_id=document_id,
        document_name=document_name,
        model_used=model_used,
        duration_ms=duration_ms,
        details=details
    )


async def log_document_deleted(
    db: AsyncSession,
    document_id: str,
    document_name: str,
    chunk_count: Optional[int] = None,
    file_size: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None
) -> int:
    """Log that a document was deleted."""
    return await log_document_event(
        db=db,
        action=AUDIT_ACTION_DOCUMENT_DELETED,
        status=AUDIT_STATUS_COMPLETED,
        document_id=document_id,
        document_name=document_name,
        chunk_count=chunk_count,
        file_size=file_size,
        details=details,
        ip_address=ip_address,
        user_agent=user_agent
    )


async def log_re_embed_started(
    db: AsyncSession,
    document_id: str,
    document_name: str,
    model_used: str,
    details: Optional[Dict[str, Any]] = None
) -> int:
    """Log that re-embedding has started for a document."""
    return await log_document_event(
        db=db,
        action=AUDIT_ACTION_DOCUMENT_RE_EMBED_STARTED,
        status=AUDIT_STATUS_IN_PROGRESS,
        document_id=document_id,
        document_name=document_name,
        model_used=model_used,
        details=details
    )


async def log_re_embed_completed(
    db: AsyncSession,
    document_id: str,
    document_name: str,
    chunk_count: int,
    model_used: str,
    duration_ms: int,
    details: Optional[Dict[str, Any]] = None
) -> int:
    """Log that re-embedding completed successfully."""
    return await log_document_event(
        db=db,
        action=AUDIT_ACTION_DOCUMENT_RE_EMBED_COMPLETED,
        status=AUDIT_STATUS_COMPLETED,
        document_id=document_id,
        document_name=document_name,
        chunk_count=chunk_count,
        model_used=model_used,
        duration_ms=duration_ms,
        details=details
    )


async def get_document_history(
    db: AsyncSession,
    document_id: str,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Get the audit history for a specific document.

    Args:
        db: Database session
        document_id: UUID of the document
        limit: Maximum number of entries to return

    Returns:
        List of audit log entries for the document, newest first
    """
    result = await db.execute(
        text("""
            SELECT
                id, action, status, details, ip_address, user_agent,
                document_id, document_name, file_size, chunk_count,
                model_used, duration_ms, created_at
            FROM audit_log
            WHERE document_id = :document_id
            ORDER BY created_at DESC
            LIMIT :limit
        """),
        {"document_id": document_id, "limit": limit}
    )
    rows = result.fetchall()

    return [
        {
            "id": row[0],
            "action": row[1],
            "status": row[2],
            "details": json.loads(row[3]) if row[3] else None,
            "ip_address": row[4],
            "user_agent": row[5],
            "document_id": row[6],
            "document_name": row[7],
            "file_size": row[8],
            "chunk_count": row[9],
            "model_used": row[10],
            "duration_ms": row[11],
            "created_at": row[12].isoformat() if row[12] else None
        }
        for row in rows
    ]


async def get_recent_document_events(
    db: AsyncSession,
    limit: int = 100,
    action_filter: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get recent document-related audit events.

    Args:
        db: Database session
        limit: Maximum number of entries to return
        action_filter: Optional action to filter by

    Returns:
        List of audit log entries, newest first
    """
    if action_filter:
        result = await db.execute(
            text("""
                SELECT
                    id, action, status, details, ip_address, user_agent,
                    document_id, document_name, file_size, chunk_count,
                    model_used, duration_ms, created_at
                FROM audit_log
                WHERE action = :action
                  AND document_id IS NOT NULL
                ORDER BY created_at DESC
                LIMIT :limit
            """),
            {"action": action_filter, "limit": limit}
        )
    else:
        result = await db.execute(
            text("""
                SELECT
                    id, action, status, details, ip_address, user_agent,
                    document_id, document_name, file_size, chunk_count,
                    model_used, duration_ms, created_at
                FROM audit_log
                WHERE document_id IS NOT NULL
                ORDER BY created_at DESC
                LIMIT :limit
            """),
            {"limit": limit}
        )

    rows = result.fetchall()

    return [
        {
            "id": row[0],
            "action": row[1],
            "status": row[2],
            "details": json.loads(row[3]) if row[3] else None,
            "ip_address": row[4],
            "user_agent": row[5],
            "document_id": row[6],
            "document_name": row[7],
            "file_size": row[8],
            "chunk_count": row[9],
            "model_used": row[10],
            "duration_ms": row[11],
            "created_at": row[12].isoformat() if row[12] else None
        }
        for row in rows
    ]


async def get_document_audit_stats(db: AsyncSession) -> Dict[str, Any]:
    """
    Get statistics about document audit events.

    Returns:
        Dictionary with counts of different event types
    """
    result = await db.execute(
        text("""
            SELECT action, COUNT(*) as count
            FROM audit_log
            WHERE document_id IS NOT NULL
            GROUP BY action
            ORDER BY count DESC
        """)
    )
    rows = result.fetchall()

    stats = {row[0]: row[1] for row in rows}

    # Get total duration for embedding operations
    result = await db.execute(
        text("""
            SELECT
                SUM(duration_ms) as total_duration,
                SUM(chunk_count) as total_chunks,
                COUNT(*) as total_operations
            FROM audit_log
            WHERE action IN ('embedding_completed', 'document_re_embed_completed')
        """)
    )
    row = result.fetchone()

    return {
        "event_counts": stats,
        "embedding_stats": {
            "total_duration_ms": row[0] if row[0] else 0,
            "total_chunks_generated": row[1] if row[1] else 0,
            "total_operations": row[2] if row[2] else 0
        }
    }


async def get_reembed_success_rate(db: AsyncSession) -> Dict[str, Any]:
    """
    Feature #297: Get re-embedding success rate metrics.

    Calculates success rate by comparing re_embed_started events with
    re_embed_completed events. A started event without a corresponding
    completed event indicates a failure.

    Returns:
        Dictionary with:
        - total_attempts: Total number of re-embed attempts
        - successful: Number of successful re-embeds
        - failed: Number of failed re-embeds
        - success_rate: Percentage of successful re-embeds
        - by_status: Breakdown of documents by current status
        - recent_failures: List of recent failed re-embeds
    """
    # Count re-embed started and completed events
    result = await db.execute(
        text("""
            WITH reembed_events AS (
                SELECT
                    document_id,
                    action,
                    created_at,
                    ROW_NUMBER() OVER (PARTITION BY document_id, action ORDER BY created_at DESC) as rn
                FROM audit_log
                WHERE action IN ('document_re_embed_started', 'document_re_embed_completed')
            )
            SELECT action, COUNT(*) as count
            FROM reembed_events
            GROUP BY action
        """)
    )
    rows = result.fetchall()
    event_counts = {row[0]: row[1] for row in rows}

    started = event_counts.get("document_re_embed_started", 0)
    completed = event_counts.get("document_re_embed_completed", 0)

    # Calculate success rate
    if started > 0:
        # Note: More completed than started can happen if events are logged differently
        # Use min to avoid > 100% rate
        successful = min(completed, started)
        failed = started - successful
        success_rate = round((successful / started) * 100, 2)
    else:
        successful = 0
        failed = 0
        success_rate = 100.0  # No attempts = 100% by default

    # Get breakdown of documents by verification status
    result = await db.execute(
        text("""
            SELECT status, COUNT(*) as count
            FROM documents
            WHERE status IN ('verification_failed', 'embedding_failed', 'ready')
            GROUP BY status
        """)
    )
    rows = result.fetchall()
    by_status = {row[0]: row[1] for row in rows}

    # Get documents with verification_failed status
    result = await db.execute(
        text("""
            SELECT id, title, comment, updated_at
            FROM documents
            WHERE status = 'verification_failed'
            ORDER BY updated_at DESC
            LIMIT 10
        """)
    )
    rows = result.fetchall()
    verification_failed_docs = [
        {
            "document_id": row[0],
            "title": row[1],
            "comment": row[2],
            "updated_at": row[3].isoformat() if row[3] else None
        }
        for row in rows
    ]

    return {
        "total_attempts": started,
        "successful": successful,
        "failed": failed,
        "success_rate": success_rate,
        "by_status": {
            "ready": by_status.get("ready", 0),
            "embedding_failed": by_status.get("embedding_failed", 0),
            "verification_failed": by_status.get("verification_failed", 0)
        },
        "verification_failed_documents": verification_failed_docs
    }
