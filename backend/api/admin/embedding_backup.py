"""
Embedding backup/restore endpoints.

Feature #353: Refactored from admin_maintenance.py.
"""

import logging
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from core.store import embedding_store

from ._shared import OperationResult

logger = logging.getLogger(__name__)
router = APIRouter()


# ==================== Local Models ====================

class RestoreFromBackupRequest(BaseModel):
    """Request model for manual restore from backup."""
    document_id: str


class DeleteBackupRequest(BaseModel):
    """Request model for deleting a backup."""
    document_id: str


class CleanupOldBackupsRequest(BaseModel):
    """Request model for cleaning up old backups."""
    days: int = 7


# ==================== Endpoints ====================

@router.get("/backup-stats")
async def get_backup_stats():
    """
    Get statistics about embedding backups (Feature #250).

    Returns information about all backups in the embeddings_backup table:
    - Total number of backups
    - Number of documents with backups
    - Oldest and newest backup timestamps
    """
    return embedding_store.get_backup_stats()


@router.get("/backup-stats/{document_id}")
async def get_backup_stats_for_document(document_id: str):
    """
    Get backup statistics for a specific document (Feature #250).

    Args:
        document_id: The document ID to get backup stats for

    Returns:
        Backup information for the specified document
    """
    return embedding_store.get_backup_stats(document_id)


@router.get("/backups")
async def list_backups():
    """
    List all documents with backups (Feature #250).

    Returns a list of all documents that have backup entries in the
    embeddings_backup table, along with backup counts and timestamps.
    """
    backups = embedding_store.list_documents_with_backups()
    return {
        "success": True,
        "total_documents": len(set(b["document_id"] for b in backups)),
        "backups": backups
    }


@router.post("/restore-from-backup", response_model=OperationResult)
async def restore_from_backup(request: RestoreFromBackupRequest):
    """
    Manually restore embeddings from backup (Feature #250).

    This endpoint allows manual restoration of embeddings from the backup table.
    Use this if:
    - A re-embed operation failed and automatic restore didn't work
    - You need to recover embeddings after manual intervention
    - Testing backup/restore functionality

    WARNING: This will DELETE all current embeddings for the document and
    replace them with the backup. Use with caution.

    Args:
        document_id: The document ID to restore from backup

    Returns:
        OperationResult with restore status
    """
    start_time = datetime.now()

    document_id = request.document_id

    # Check if backup exists
    if not embedding_store.has_backup_for_document(document_id):
        return OperationResult(
            success=False,
            operation="restore_from_backup",
            message=f"No backup found for document {document_id}",
            duration_ms=0
        )

    try:
        # Restore from backup
        restored_count = embedding_store.restore_embeddings_from_backup(document_id)

        if restored_count == 0:
            return OperationResult(
                success=False,
                operation="restore_from_backup",
                message=f"Failed to restore embeddings for document {document_id}",
                duration_ms=int((datetime.now() - start_time).total_seconds() * 1000)
            )

        end_time = datetime.now()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        logger.info(f"[Feature #250] Manually restored {restored_count} embeddings for document {document_id}")

        return OperationResult(
            success=True,
            operation="restore_from_backup",
            message=f"Successfully restored {restored_count} embeddings for document {document_id}",
            details={
                "document_id": document_id,
                "embeddings_restored": restored_count
            },
            duration_ms=duration_ms
        )

    except Exception as e:
        logger.error(f"[Feature #250] Error restoring from backup: {e}")
        return OperationResult(
            success=False,
            operation="restore_from_backup",
            message=f"Restore failed: {str(e)}",
            duration_ms=int((datetime.now() - start_time).total_seconds() * 1000)
        )


@router.post("/delete-backup", response_model=OperationResult)
async def delete_backup(request: DeleteBackupRequest):
    """
    Delete backup for a document (Feature #250).

    This endpoint manually deletes the backup for a specific document.
    Use this to clean up backups that are no longer needed.

    Args:
        document_id: The document ID to delete backup for

    Returns:
        OperationResult with deletion status
    """
    start_time = datetime.now()
    document_id = request.document_id

    try:
        deleted_count = embedding_store.delete_backup_for_document(document_id)

        end_time = datetime.now()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        if deleted_count > 0:
            return OperationResult(
                success=True,
                operation="delete_backup",
                message=f"Deleted {deleted_count} backup entries for document {document_id}",
                details={
                    "document_id": document_id,
                    "entries_deleted": deleted_count
                },
                duration_ms=duration_ms
            )
        else:
            return OperationResult(
                success=True,
                operation="delete_backup",
                message=f"No backup found for document {document_id}",
                details={"document_id": document_id},
                duration_ms=duration_ms
            )

    except Exception as e:
        logger.error(f"[Feature #250] Error deleting backup: {e}")
        return OperationResult(
            success=False,
            operation="delete_backup",
            message=f"Delete failed: {str(e)}",
            duration_ms=int((datetime.now() - start_time).total_seconds() * 1000)
        )


@router.post("/cleanup-old-backups", response_model=OperationResult)
async def cleanup_old_backups(request: CleanupOldBackupsRequest):
    """
    Clean up old backups (Feature #250).

    Deletes all backups older than the specified number of days.
    Default is 7 days.

    Args:
        days: Number of days after which backups are considered stale (default: 7)

    Returns:
        OperationResult with cleanup status
    """
    start_time = datetime.now()

    if request.days < 1:
        return OperationResult(
            success=False,
            operation="cleanup_old_backups",
            message="Days must be at least 1",
            duration_ms=0
        )

    try:
        deleted_count = embedding_store.cleanup_old_backups(request.days)

        end_time = datetime.now()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        return OperationResult(
            success=True,
            operation="cleanup_old_backups",
            message=f"Cleaned up {deleted_count} old backups (older than {request.days} days)",
            details={
                "days_threshold": request.days,
                "backups_deleted": deleted_count
            },
            duration_ms=duration_ms
        )

    except Exception as e:
        logger.error(f"[Feature #250] Error cleaning up old backups: {e}")
        return OperationResult(
            success=False,
            operation="cleanup_old_backups",
            message=f"Cleanup failed: {str(e)}",
            duration_ms=int((datetime.now() - start_time).total_seconds() * 1000)
        )
