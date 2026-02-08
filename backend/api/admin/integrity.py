"""
Orphaned docs, DB health check, document repair, file integrity endpoints.

Feature #353: Refactored from admin_maintenance.py.
"""

import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from core.database import async_engine
from core.store import embedding_store

from ._shared import (
    OperationResult,
    DocumentRepairReport,
    _check_file_exists,
    _compute_file_hash,
    _search_file_by_hash,
    _search_file_by_pattern,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ==================== Local Models ====================

class OrphanedDocument(BaseModel):
    """Model for an orphaned document (file missing on disk)."""
    id: str
    title: str
    original_filename: str
    file_path: Optional[str]
    file_size: int
    document_type: str
    collection_id: Optional[str]
    created_at: datetime
    file_status: str


class OrphanedDocumentsResponse(BaseModel):
    """Response model for orphaned documents detection."""
    success: bool
    total_documents: int
    orphaned_count: int
    orphaned_documents: List[OrphanedDocument]
    scan_duration_ms: int


class OrphanedDocumentsCleanupRequest(BaseModel):
    """Request model for cleaning up orphaned documents."""
    document_ids: List[str]
    action: str = "delete"  # "delete" or "mark_missing"


class OrphanedDocumentsCleanupResponse(BaseModel):
    """Response model for orphaned documents cleanup."""
    success: bool
    action: str
    processed_count: int
    failed_count: int
    details: Dict[str, Any]


class DatabaseHealthIssue(BaseModel):
    """Individual database health issue found."""
    issue_type: str  # orphaned_embedding, missing_embeddings, missing_file, fk_violation
    severity: str  # critical, warning, info
    count: int
    description: str
    affected_items: List[Dict[str, Any]] = []  # Limited list for preview
    suggested_fix: str
    auto_fixable: bool


class DatabaseHealthReport(BaseModel):
    """Complete database health report."""
    status: str  # healthy, warning, critical
    scan_timestamp: str
    scan_duration_ms: int
    total_issues_found: int
    issues: List[DatabaseHealthIssue]
    summary: Dict[str, Any]


class DatabaseHealthFixRequest(BaseModel):
    """Request to auto-fix database health issues."""
    fix_types: List[str] = []  # List of issue_types to fix: orphaned_embeddings, orphaned_rows, etc.
    dry_run: bool = True  # If True, only report what would be fixed without actually fixing


class DatabaseHealthFixResponse(BaseModel):
    """Response from auto-fix operation."""
    success: bool
    dry_run: bool
    fixes_applied: List[Dict[str, Any]]
    total_fixed: int
    errors: List[str]
    duration_ms: int


class FileIntegritySchedulerStatus(BaseModel):
    """Response model for file integrity scheduler status."""
    enabled: bool
    check_interval_hours: int
    last_check_time: Optional[str] = None
    last_check_status: str
    last_check_error: Optional[str] = None
    next_check_time: Optional[str] = None
    check_in_progress: bool
    last_check_stats: Optional[dict] = None


class FileIntegrityCheckResult(BaseModel):
    """Response model for file integrity check results."""
    success: bool
    message: str
    stats: Optional[dict] = None
    error: Optional[str] = None


# ==================== Endpoints ====================

@router.get("/orphaned-documents", response_model=OrphanedDocumentsResponse)
async def get_orphaned_documents():
    """
    Detect orphaned documents (DB records with missing files on disk).

    Feature #254: Orphaned record detection and cleanup.

    Scans all documents in the database and checks if their corresponding
    files exist on disk. Returns a list of orphaned documents.

    Returns:
        OrphanedDocumentsResponse with list of orphaned documents
    """
    start_time = time.time()

    try:
        from core.database import SessionLocal
        from models.db_models import DBDocument
        from sqlalchemy import select

        orphaned_documents = []
        total_documents = 0

        with SessionLocal() as session:
            # Query all documents
            stmt = select(DBDocument)
            result = session.execute(stmt)
            documents = result.scalars().all()
            total_documents = len(documents)

            logger.info(f"[Feature #254] Scanning {total_documents} documents for orphaned records...")

            for doc in documents:
                # Check file existence using file_path or url
                file_path = doc.file_path or doc.url
                file_exists = _check_file_exists(file_path)

                if not file_exists:
                    orphaned_documents.append(OrphanedDocument(
                        id=doc.id,
                        title=doc.title,
                        original_filename=doc.original_filename,
                        file_path=file_path,
                        file_size=doc.file_size,
                        document_type=doc.document_type,
                        collection_id=doc.collection_id,
                        created_at=doc.created_at,
                        file_status=getattr(doc, 'file_status', 'ok')
                    ))
                    logger.warning(f"[Feature #254] Orphaned document found: {doc.id} - {doc.title} (file: {file_path})")

        duration_ms = int((time.time() - start_time) * 1000)

        logger.info(f"[Feature #254] Scan complete: {len(orphaned_documents)}/{total_documents} orphaned documents found in {duration_ms}ms")

        return OrphanedDocumentsResponse(
            success=True,
            total_documents=total_documents,
            orphaned_count=len(orphaned_documents),
            orphaned_documents=orphaned_documents,
            scan_duration_ms=duration_ms
        )

    except Exception as e:
        logger.error(f"[Feature #254] Error scanning for orphaned documents: {e}")
        raise HTTPException(status_code=500, detail=f"Error scanning for orphaned documents: {str(e)}")


@router.post("/orphaned-documents/cleanup", response_model=OrphanedDocumentsCleanupResponse)
async def cleanup_orphaned_documents(request: OrphanedDocumentsCleanupRequest):
    """
    Clean up orphaned documents by deleting or marking them.

    Feature #254: Orphaned record detection and cleanup.

    Args:
        request: Contains document_ids and action ("delete" or "mark_missing")

    Returns:
        OrphanedDocumentsCleanupResponse with cleanup results
    """
    try:
        from core.database import SessionLocal
        from models.db_models import DBDocument, DBDocumentRow, FILE_STATUS_MISSING
        from models.embedding import DocumentEmbedding
        from sqlalchemy import select, delete, update

        processed_count = 0
        failed_count = 0
        deleted_documents = []
        marked_documents = []
        errors = []

        with SessionLocal() as session:
            for doc_id in request.document_ids:
                try:
                    # Find the document
                    stmt = select(DBDocument).where(DBDocument.id == doc_id)
                    result = session.execute(stmt)
                    doc = result.scalar_one_or_none()

                    if not doc:
                        errors.append(f"Document {doc_id} not found")
                        failed_count += 1
                        continue

                    # Verify the file is actually missing
                    file_path = doc.file_path or doc.url
                    if _check_file_exists(file_path):
                        errors.append(f"Document {doc_id} file exists on disk, not orphaned")
                        failed_count += 1
                        continue

                    if request.action == "delete":
                        # Delete related document_rows
                        delete_rows = delete(DBDocumentRow).where(DBDocumentRow.dataset_id == doc_id)
                        rows_result = session.execute(delete_rows)
                        deleted_rows = rows_result.rowcount

                        # Delete related embeddings
                        delete_embeddings = delete(DocumentEmbedding).where(DocumentEmbedding.document_id == doc_id)
                        embeddings_result = session.execute(delete_embeddings)
                        deleted_embeddings = embeddings_result.rowcount

                        # Delete the document
                        delete_doc = delete(DBDocument).where(DBDocument.id == doc_id)
                        session.execute(delete_doc)

                        deleted_documents.append({
                            "id": doc_id,
                            "title": doc.title,
                            "deleted_rows": deleted_rows,
                            "deleted_embeddings": deleted_embeddings
                        })
                        logger.info(f"[Feature #254] Deleted orphaned document: {doc_id} - {doc.title}")
                        processed_count += 1

                    elif request.action == "mark_missing":
                        # Update file_status to 'file_missing'
                        update_stmt = update(DBDocument).where(DBDocument.id == doc_id).values(
                            file_status=FILE_STATUS_MISSING
                        )
                        session.execute(update_stmt)

                        marked_documents.append({
                            "id": doc_id,
                            "title": doc.title
                        })
                        logger.info(f"[Feature #254] Marked document as file_missing: {doc_id} - {doc.title}")
                        processed_count += 1
                    else:
                        errors.append(f"Unknown action: {request.action}")
                        failed_count += 1
                        continue

                except Exception as e:
                    errors.append(f"Error processing document {doc_id}: {str(e)}")
                    failed_count += 1
                    logger.error(f"[Feature #254] Error processing document {doc_id}: {e}")

            # Commit all changes
            session.commit()

        return OrphanedDocumentsCleanupResponse(
            success=failed_count == 0,
            action=request.action,
            processed_count=processed_count,
            failed_count=failed_count,
            details={
                "deleted_documents": deleted_documents if request.action == "delete" else [],
                "marked_documents": marked_documents if request.action == "mark_missing" else [],
                "errors": errors
            }
        )

    except Exception as e:
        logger.error(f"[Feature #254] Error cleaning up orphaned documents: {e}")
        raise HTTPException(status_code=500, detail=f"Error cleaning up orphaned documents: {str(e)}")


@router.post("/orphaned-documents/mark-all-missing", response_model=OperationResult)
async def mark_all_orphaned_as_missing():
    """
    Scan all documents and mark orphaned ones as 'file_missing'.

    Feature #254: Orphaned record detection and cleanup.

    This is a convenience endpoint that scans all documents and automatically
    marks any with missing files as 'file_missing' status.

    Returns:
        OperationResult with count of documents marked
    """
    start_time = time.time()

    try:
        from core.database import SessionLocal
        from models.db_models import DBDocument, FILE_STATUS_MISSING, FILE_STATUS_OK
        from sqlalchemy import select, update

        marked_count = 0
        restored_count = 0

        with SessionLocal() as session:
            # Query all documents
            stmt = select(DBDocument)
            result = session.execute(stmt)
            documents = result.scalars().all()

            for doc in documents:
                file_path = doc.file_path or doc.url
                file_exists = _check_file_exists(file_path)
                current_status = getattr(doc, 'file_status', 'ok')

                if not file_exists and current_status != FILE_STATUS_MISSING:
                    # Mark as missing
                    update_stmt = update(DBDocument).where(DBDocument.id == doc.id).values(
                        file_status=FILE_STATUS_MISSING
                    )
                    session.execute(update_stmt)
                    marked_count += 1
                    logger.info(f"[Feature #254] Marked as file_missing: {doc.id} - {doc.title}")

                elif file_exists and current_status == FILE_STATUS_MISSING:
                    # Restore status to OK (file was restored)
                    update_stmt = update(DBDocument).where(DBDocument.id == doc.id).values(
                        file_status=FILE_STATUS_OK
                    )
                    session.execute(update_stmt)
                    restored_count += 1
                    logger.info(f"[Feature #254] Restored status to ok: {doc.id} - {doc.title}")

            session.commit()

        duration_ms = int((time.time() - start_time) * 1000)

        return OperationResult(
            success=True,
            operation="mark_all_orphaned_as_missing",
            message=f"Marked {marked_count} documents as file_missing, restored {restored_count} documents",
            details={
                "marked_count": marked_count,
                "restored_count": restored_count,
                "total_scanned": len(documents)
            },
            duration_ms=duration_ms
        )

    except Exception as e:
        logger.error(f"[Feature #254] Error marking orphaned documents: {e}")
        return OperationResult(
            success=False,
            operation="mark_all_orphaned_as_missing",
            message=f"Error: {str(e)}"
        )


@router.get("/db-health", response_model=DatabaseHealthReport)
async def database_health_check():
    """
    Feature #271: Comprehensive database integrity health check.

    Checks for:
    1. Orphaned embeddings (embeddings referencing non-existent documents)
    2. Documents without embeddings (unstructured docs that should have embeddings)
    3. Documents with missing files on disk
    4. Foreign key constraint violations
    5. Data consistency issues

    Returns a detailed health report with issues found and suggested fixes.
    """
    start_time = time.time()
    issues = []

    try:
        from core.database import SessionLocal
        from models.db_models import DBDocument, DBDocumentRow, DOCUMENT_STATUS_READY, FILE_STATUS_OK
        from models.embedding import DocumentEmbedding
        from sqlalchemy import select, func as sql_func, and_, or_

        with SessionLocal() as session:
            # ==================== Check 1: Orphaned Embeddings ====================
            logger.info("[Feature #271] Checking for orphaned embeddings...")

            orphaned_embeddings_query = text("""
                SELECT de.document_id, COUNT(*) as count
                FROM document_embeddings de
                LEFT JOIN documents d ON de.document_id = d.id
                WHERE d.id IS NULL
                GROUP BY de.document_id
            """)
            result = session.execute(orphaned_embeddings_query)
            orphaned_embeddings = result.fetchall()

            if orphaned_embeddings:
                total_orphaned = sum(row[1] for row in orphaned_embeddings)
                affected_items = [
                    {"document_id": row[0], "embedding_count": row[1]}
                    for row in orphaned_embeddings[:10]
                ]
                issues.append(DatabaseHealthIssue(
                    issue_type="orphaned_embeddings",
                    severity="critical",
                    count=total_orphaned,
                    description=f"Found {total_orphaned} embeddings referencing {len(orphaned_embeddings)} non-existent documents",
                    affected_items=affected_items,
                    suggested_fix="Run cleanup-orphans endpoint or use auto-fix to delete orphaned embeddings",
                    auto_fixable=True
                ))

            # ==================== Check 2: Orphaned Document Rows ====================
            logger.info("[Feature #271] Checking for orphaned document rows...")

            orphaned_rows_query = text("""
                SELECT dr.dataset_id, COUNT(*) as count
                FROM document_rows dr
                LEFT JOIN documents d ON dr.dataset_id = d.id
                WHERE d.id IS NULL
                GROUP BY dr.dataset_id
            """)
            result = session.execute(orphaned_rows_query)
            orphaned_rows = result.fetchall()

            if orphaned_rows:
                total_orphaned_rows = sum(row[1] for row in orphaned_rows)
                affected_items = [
                    {"document_id": row[0], "row_count": row[1]}
                    for row in orphaned_rows[:10]
                ]
                issues.append(DatabaseHealthIssue(
                    issue_type="orphaned_rows",
                    severity="warning",
                    count=total_orphaned_rows,
                    description=f"Found {total_orphaned_rows} document rows referencing {len(orphaned_rows)} non-existent documents",
                    affected_items=affected_items,
                    suggested_fix="Run cleanup-orphans endpoint or use auto-fix to delete orphaned rows",
                    auto_fixable=True
                ))

            # ==================== Check 3: Documents Without Embeddings ====================
            logger.info("[Feature #271] Checking for documents without embeddings...")

            missing_embeddings_query = text("""
                SELECT d.id, d.title, d.document_type, d.status, d.chunk_count
                FROM documents d
                LEFT JOIN document_embeddings de ON d.id = de.document_id
                WHERE d.document_type = 'unstructured'
                AND d.status = 'ready'
                AND de.id IS NULL
            """)
            result = session.execute(missing_embeddings_query)
            docs_without_embeddings = result.fetchall()

            if docs_without_embeddings:
                affected_items = [
                    {
                        "document_id": row[0],
                        "title": row[1],
                        "document_type": row[2],
                        "status": row[3],
                        "chunk_count": row[4]
                    }
                    for row in docs_without_embeddings[:10]
                ]
                issues.append(DatabaseHealthIssue(
                    issue_type="missing_embeddings",
                    severity="critical",
                    count=len(docs_without_embeddings),
                    description=f"Found {len(docs_without_embeddings)} unstructured documents with status 'ready' but no embeddings",
                    affected_items=affected_items,
                    suggested_fix="Re-embed these documents using the Re-embed All button or update their status to 'embedding_failed'",
                    auto_fixable=False
                ))

            # ==================== Check 4: Documents With Missing Files ====================
            logger.info("[Feature #271] Checking for documents with missing files...")

            stmt = select(DBDocument).where(DBDocument.file_status != FILE_STATUS_OK)
            result = session.execute(stmt)
            docs_missing_files = result.scalars().all()

            stmt_ok = select(DBDocument).where(DBDocument.file_status == FILE_STATUS_OK)
            result_ok = session.execute(stmt_ok)
            docs_with_ok_status = result_ok.scalars().all()

            newly_missing = []
            for doc in docs_with_ok_status:
                file_path = doc.file_path or doc.url
                if not _check_file_exists(file_path):
                    newly_missing.append(doc)

            total_missing = len(docs_missing_files) + len(newly_missing)

            if total_missing > 0:
                affected_items = []
                for doc in docs_missing_files[:5]:
                    affected_items.append({
                        "document_id": doc.id,
                        "title": doc.title,
                        "file_path": doc.file_path or doc.url,
                        "file_status": doc.file_status,
                        "already_marked": True
                    })
                for doc in newly_missing[:5]:
                    affected_items.append({
                        "document_id": doc.id,
                        "title": doc.title,
                        "file_path": doc.file_path or doc.url,
                        "file_status": doc.file_status,
                        "already_marked": False
                    })

                issues.append(DatabaseHealthIssue(
                    issue_type="missing_files",
                    severity="warning",
                    count=total_missing,
                    description=f"Found {total_missing} documents with missing files ({len(docs_missing_files)} already marked, {len(newly_missing)} newly detected)",
                    affected_items=affected_items[:10],
                    suggested_fix="Use orphaned-documents/mark-all-missing to update file_status, or delete the documents",
                    auto_fixable=True
                ))

            # ==================== Check 5: Chunk Count Mismatch ====================
            logger.info("[Feature #271] Checking for chunk count mismatches...")

            # Feature #361: Filter by status='active' to match what chunk_count triggers track
            chunk_count_query = text("""
                SELECT d.id, d.title, d.chunk_count, COUNT(de.id) as actual_count
                FROM documents d
                LEFT JOIN document_embeddings de ON d.id = de.document_id
                    AND (de.status = 'active' OR de.status IS NULL)
                WHERE d.document_type = 'unstructured'
                GROUP BY d.id, d.title, d.chunk_count
                HAVING d.chunk_count != COUNT(de.id)
            """)
            result = session.execute(chunk_count_query)
            chunk_mismatches = result.fetchall()

            if chunk_mismatches:
                affected_items = [
                    {
                        "document_id": row[0],
                        "title": row[1],
                        "stored_chunk_count": row[2],
                        "actual_embedding_count": row[3]
                    }
                    for row in chunk_mismatches[:10]
                ]
                issues.append(DatabaseHealthIssue(
                    issue_type="chunk_count_mismatch",
                    severity="info",
                    count=len(chunk_mismatches),
                    description=f"Found {len(chunk_mismatches)} documents with mismatched chunk counts",
                    affected_items=affected_items,
                    suggested_fix="Auto-fix can update chunk_count column to match actual embedding count",
                    auto_fixable=True
                ))

            # ==================== Check 6: Orphaned Message Embeddings ====================
            logger.info("[Feature #271] Checking for orphaned message embeddings...")

            orphaned_msg_query = text("""
                SELECT me.message_id, COUNT(*) as count
                FROM message_embeddings me
                LEFT JOIN messages m ON me.message_id = m.id
                WHERE m.id IS NULL
                GROUP BY me.message_id
            """)
            result = session.execute(orphaned_msg_query)
            orphaned_msg_embeddings = result.fetchall()

            if orphaned_msg_embeddings:
                total_orphaned_msg = sum(row[1] for row in orphaned_msg_embeddings)
                issues.append(DatabaseHealthIssue(
                    issue_type="orphaned_message_embeddings",
                    severity="warning",
                    count=total_orphaned_msg,
                    description=f"Found {total_orphaned_msg} message embeddings referencing non-existent messages",
                    affected_items=[{"message_id": row[0], "count": row[1]} for row in orphaned_msg_embeddings[:10]],
                    suggested_fix="Run cleanup-orphans endpoint to delete orphaned message embeddings",
                    auto_fixable=True
                ))

            # ==================== Check 7: Orphaned Chunk Feedback ====================
            logger.info("[Feature #271] Checking for orphaned chunk feedback...")

            orphaned_feedback_query = text("""
                SELECT cf.chunk_id, COUNT(*) as count
                FROM chunk_feedback cf
                LEFT JOIN document_embeddings de ON cf.chunk_id = de.chunk_id
                WHERE de.chunk_id IS NULL
                GROUP BY cf.chunk_id
            """)
            result = session.execute(orphaned_feedback_query)
            orphaned_feedback = result.fetchall()

            if orphaned_feedback:
                total_orphaned_fb = sum(row[1] for row in orphaned_feedback)
                issues.append(DatabaseHealthIssue(
                    issue_type="orphaned_chunk_feedback",
                    severity="info",
                    count=total_orphaned_fb,
                    description=f"Found {total_orphaned_fb} chunk feedback records referencing non-existent embeddings",
                    affected_items=[{"chunk_id": row[0], "count": row[1]} for row in orphaned_feedback[:10]],
                    suggested_fix="Run cleanup-orphans endpoint to delete orphaned feedback records",
                    auto_fixable=True
                ))

            # ==================== Check 8: Conversations Without Messages ====================
            logger.info("[Feature #271] Checking for empty conversations...")

            empty_convs_query = text("""
                SELECT c.id, c.title, c.created_at
                FROM conversations c
                LEFT JOIN messages m ON c.id = m.conversation_id
                WHERE m.id IS NULL
            """)
            result = session.execute(empty_convs_query)
            empty_conversations = result.fetchall()

            if empty_conversations:
                affected_items = [
                    {
                        "conversation_id": row[0],
                        "title": row[1],
                        "created_at": row[2].isoformat() if row[2] else None
                    }
                    for row in empty_conversations[:10]
                ]
                issues.append(DatabaseHealthIssue(
                    issue_type="empty_conversations",
                    severity="info",
                    count=len(empty_conversations),
                    description=f"Found {len(empty_conversations)} conversations without any messages",
                    affected_items=affected_items,
                    suggested_fix="These can be cleaned up by deleting empty conversations",
                    auto_fixable=True
                ))

            # ==================== Generate Summary ====================
            total_issues = sum(issue.count for issue in issues)
            critical_count = sum(1 for issue in issues if issue.severity == "critical")
            warning_count = sum(1 for issue in issues if issue.severity == "warning")
            info_count = sum(1 for issue in issues if issue.severity == "info")

            # Determine overall status
            if critical_count > 0:
                overall_status = "critical"
            elif warning_count > 0:
                overall_status = "warning"
            elif total_issues > 0:
                overall_status = "info"
            else:
                overall_status = "healthy"

            # Get counts for summary
            doc_count_result = session.execute(text("SELECT COUNT(*) FROM documents"))
            total_documents = doc_count_result.scalar()

            embedding_count_result = session.execute(text("SELECT COUNT(*) FROM document_embeddings"))
            total_embeddings = embedding_count_result.scalar()

            conv_count_result = session.execute(text("SELECT COUNT(*) FROM conversations"))
            total_conversations = conv_count_result.scalar()

            summary = {
                "total_documents": total_documents,
                "total_embeddings": total_embeddings,
                "total_conversations": total_conversations,
                "critical_issues": critical_count,
                "warning_issues": warning_count,
                "info_issues": info_count,
                "auto_fixable_issues": sum(1 for issue in issues if issue.auto_fixable)
            }

        duration_ms = int((time.time() - start_time) * 1000)

        logger.info(f"[Feature #271] Health check complete: {overall_status}, {len(issues)} issue types, {total_issues} total issues in {duration_ms}ms")

        return DatabaseHealthReport(
            status=overall_status,
            scan_timestamp=datetime.now(timezone.utc).isoformat(),
            scan_duration_ms=duration_ms,
            total_issues_found=total_issues,
            issues=issues,
            summary=summary
        )

    except Exception as e:
        logger.error(f"[Feature #271] Health check failed: {e}")
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")


@router.post("/db-health/fix", response_model=DatabaseHealthFixResponse)
async def database_health_fix(request: DatabaseHealthFixRequest):
    """
    Feature #271: Auto-fix database health issues.

    Supports fixing:
    - orphaned_embeddings: Delete embeddings referencing non-existent documents
    - orphaned_rows: Delete document rows referencing non-existent documents
    - orphaned_message_embeddings: Delete message embeddings referencing non-existent messages
    - orphaned_chunk_feedback: Delete chunk feedback referencing non-existent embeddings
    - chunk_count_mismatch: Update chunk_count column to match actual embedding count
    - empty_conversations: Delete conversations without any messages
    - missing_files: Mark documents with missing files as 'file_missing' status

    Args:
        request: DatabaseHealthFixRequest with fix_types list and dry_run flag

    Returns:
        DatabaseHealthFixResponse with details of fixes applied
    """
    start_time = time.time()
    fixes_applied = []
    errors = []
    total_fixed = 0

    try:
        from core.database import SessionLocal
        from models.db_models import DBDocument, FILE_STATUS_MISSING
        from sqlalchemy import text as sql_text, update, select

        with SessionLocal() as session:
            # Fix orphaned embeddings
            if "orphaned_embeddings" in request.fix_types:
                logger.info(f"[Feature #271] {'[DRY-RUN] ' if request.dry_run else ''}Fixing orphaned embeddings...")

                count_query = sql_text("""
                    SELECT COUNT(*) FROM document_embeddings de
                    LEFT JOIN documents d ON de.document_id = d.id
                    WHERE d.id IS NULL
                """)
                count_result = session.execute(count_query)
                count = count_result.scalar()

                if count > 0:
                    if not request.dry_run:
                        delete_query = sql_text("""
                            DELETE FROM document_embeddings
                            WHERE document_id NOT IN (SELECT id FROM documents)
                        """)
                        session.execute(delete_query)

                    fixes_applied.append({
                        "fix_type": "orphaned_embeddings",
                        "fixed_count": count,
                        "dry_run": request.dry_run
                    })
                    total_fixed += count

            # Fix orphaned rows
            if "orphaned_rows" in request.fix_types:
                logger.info(f"[Feature #271] {'[DRY-RUN] ' if request.dry_run else ''}Fixing orphaned rows...")

                count_query = sql_text("""
                    SELECT COUNT(*) FROM document_rows dr
                    LEFT JOIN documents d ON dr.dataset_id = d.id
                    WHERE d.id IS NULL
                """)
                count_result = session.execute(count_query)
                count = count_result.scalar()

                if count > 0:
                    if not request.dry_run:
                        delete_query = sql_text("""
                            DELETE FROM document_rows
                            WHERE dataset_id NOT IN (SELECT id FROM documents)
                        """)
                        session.execute(delete_query)

                    fixes_applied.append({
                        "fix_type": "orphaned_rows",
                        "fixed_count": count,
                        "dry_run": request.dry_run
                    })
                    total_fixed += count

            # Fix orphaned message embeddings
            if "orphaned_message_embeddings" in request.fix_types:
                logger.info(f"[Feature #271] {'[DRY-RUN] ' if request.dry_run else ''}Fixing orphaned message embeddings...")

                count_query = sql_text("""
                    SELECT COUNT(*) FROM message_embeddings me
                    LEFT JOIN messages m ON me.message_id = m.id
                    WHERE m.id IS NULL
                """)
                count_result = session.execute(count_query)
                count = count_result.scalar()

                if count > 0:
                    if not request.dry_run:
                        delete_query = sql_text("""
                            DELETE FROM message_embeddings
                            WHERE message_id NOT IN (SELECT id FROM messages)
                        """)
                        session.execute(delete_query)

                    fixes_applied.append({
                        "fix_type": "orphaned_message_embeddings",
                        "fixed_count": count,
                        "dry_run": request.dry_run
                    })
                    total_fixed += count

            # Fix orphaned chunk feedback
            if "orphaned_chunk_feedback" in request.fix_types:
                logger.info(f"[Feature #271] {'[DRY-RUN] ' if request.dry_run else ''}Fixing orphaned chunk feedback...")

                count_query = sql_text("""
                    SELECT COUNT(*) FROM chunk_feedback cf
                    LEFT JOIN document_embeddings de ON cf.chunk_id = de.chunk_id
                    WHERE de.chunk_id IS NULL
                """)
                count_result = session.execute(count_query)
                count = count_result.scalar()

                if count > 0:
                    if not request.dry_run:
                        delete_query = sql_text("""
                            DELETE FROM chunk_feedback
                            WHERE chunk_id NOT IN (SELECT chunk_id FROM document_embeddings)
                        """)
                        session.execute(delete_query)

                    fixes_applied.append({
                        "fix_type": "orphaned_chunk_feedback",
                        "fixed_count": count,
                        "dry_run": request.dry_run
                    })
                    total_fixed += count

            # Fix chunk count mismatches
            if "chunk_count_mismatch" in request.fix_types:
                logger.info(f"[Feature #271] {'[DRY-RUN] ' if request.dry_run else ''}Fixing chunk count mismatches...")

                # Feature #361: Filter by status='active' to match what triggers track
                mismatch_query = sql_text("""
                    SELECT d.id, COUNT(de.id) as actual_count
                    FROM documents d
                    LEFT JOIN document_embeddings de ON d.id = de.document_id
                        AND (de.status = 'active' OR de.status IS NULL)
                    WHERE d.document_type = 'unstructured'
                    GROUP BY d.id
                    HAVING d.chunk_count != COUNT(de.id)
                """)
                result = session.execute(mismatch_query)
                mismatches = result.fetchall()

                count = len(mismatches)
                if count > 0:
                    if not request.dry_run:
                        # Feature #361: Use single bulk UPDATE for efficiency and reliability
                        bulk_update = sql_text("""
                            UPDATE documents d
                            SET chunk_count = sub.actual_count
                            FROM (
                                SELECT d2.id, COUNT(de.id) as actual_count
                                FROM documents d2
                                LEFT JOIN document_embeddings de ON d2.id = de.document_id
                                    AND (de.status = 'active' OR de.status IS NULL)
                                WHERE d2.document_type = 'unstructured'
                                GROUP BY d2.id
                                HAVING d2.chunk_count != COUNT(de.id)
                            ) sub
                            WHERE d.id = sub.id
                        """)
                        session.execute(bulk_update)
                        logger.info(f"[Feature #361] Applied chunk_count fix for {count} documents")

                    fixes_applied.append({
                        "fix_type": "chunk_count_mismatch",
                        "fixed_count": count,
                        "dry_run": request.dry_run
                    })
                    total_fixed += count

            # Fix empty conversations
            if "empty_conversations" in request.fix_types:
                logger.info(f"[Feature #271] {'[DRY-RUN] ' if request.dry_run else ''}Fixing empty conversations...")

                count_query = sql_text("""
                    SELECT COUNT(*) FROM conversations c
                    LEFT JOIN messages m ON c.id = m.conversation_id
                    WHERE m.id IS NULL
                """)
                count_result = session.execute(count_query)
                count = count_result.scalar()

                if count > 0:
                    if not request.dry_run:
                        delete_query = sql_text("""
                            DELETE FROM conversations
                            WHERE id NOT IN (SELECT DISTINCT conversation_id FROM messages)
                        """)
                        session.execute(delete_query)

                    fixes_applied.append({
                        "fix_type": "empty_conversations",
                        "fixed_count": count,
                        "dry_run": request.dry_run
                    })
                    total_fixed += count

            # Fix missing files (mark as file_missing)
            if "missing_files" in request.fix_types:
                logger.info(f"[Feature #271] {'[DRY-RUN] ' if request.dry_run else ''}Marking documents with missing files...")

                # Get all documents with 'ok' file_status
                stmt = select(DBDocument).where(DBDocument.file_status == 'ok')
                result = session.execute(stmt)
                docs = result.scalars().all()

                count = 0
                for doc in docs:
                    file_path = doc.file_path or doc.url
                    if not _check_file_exists(file_path):
                        count += 1
                        if not request.dry_run:
                            doc.file_status = FILE_STATUS_MISSING

                if count > 0:
                    fixes_applied.append({
                        "fix_type": "missing_files",
                        "fixed_count": count,
                        "dry_run": request.dry_run
                    })
                    total_fixed += count

            # Commit changes if not dry run
            if not request.dry_run:
                session.commit()
                logger.info(f"[Feature #271] Auto-fix committed: {total_fixed} issues fixed")
            else:
                session.rollback()
                logger.info(f"[Feature #271] Dry-run complete: {total_fixed} issues would be fixed")

        duration_ms = int((time.time() - start_time) * 1000)

        return DatabaseHealthFixResponse(
            success=True,
            dry_run=request.dry_run,
            fixes_applied=fixes_applied,
            total_fixed=total_fixed,
            errors=errors,
            duration_ms=duration_ms
        )

    except Exception as e:
        logger.error(f"[Feature #271] Auto-fix failed: {e}")
        errors.append(str(e))
        duration_ms = int((time.time() - start_time) * 1000)
        return DatabaseHealthFixResponse(
            success=False,
            dry_run=request.dry_run,
            fixes_applied=fixes_applied,
            total_fixed=total_fixed,
            errors=errors,
            duration_ms=duration_ms
        )


@router.post("/documents/{document_id}/repair", response_model=DocumentRepairReport)
async def repair_document(document_id: str):
    """
    Repair a document by re-linking files, cleaning up orphaned data, and resetting status.

    Feature #272: Document repair endpoint.

    This endpoint helps recover documents from inconsistent states by:
    1. Searching for the file in uploads folder by content_hash or filename pattern
    2. Updating file_path if file is found at a different location
    3. Setting status to 'file_missing' if file cannot be found
    4. Cleaning up orphaned embeddings if document doesn't exist
    5. Resetting status to 'ready' if file and embeddings exist

    Args:
        document_id: The ID of the document to repair

    Returns:
        DocumentRepairReport with actions taken and repair results
    """
    start_time = time.time()

    actions_taken = []
    errors = []

    try:
        from core.database import SessionLocal
        from models.db_models import (
            DBDocument,
            FILE_STATUS_OK,
            FILE_STATUS_MISSING,
            DOCUMENT_STATUS_READY,
            DOCUMENT_STATUS_FILE_MISSING,
            EMBEDDING_STATUS_READY
        )
        from models.embedding import DocumentEmbedding
        from sqlalchemy import select, update, delete, func

        # Get backend and uploads directories
        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        uploads_dir = os.path.join(backend_dir, 'uploads')

        with SessionLocal() as session:
            # Step 1: Find the document
            stmt = select(DBDocument).where(DBDocument.id == document_id)
            result = session.execute(stmt)
            doc = result.scalar_one_or_none()

            if not doc:
                # Document doesn't exist - check for orphaned embeddings
                logger.warning(f"[Feature #272] Document {document_id} not found - checking for orphaned embeddings")

                # Count and delete orphaned embeddings
                count_stmt = select(func.count()).select_from(DocumentEmbedding).where(
                    DocumentEmbedding.document_id == document_id
                )
                count_result = session.execute(count_stmt)
                orphan_count = count_result.scalar() or 0

                if orphan_count > 0:
                    delete_stmt = delete(DocumentEmbedding).where(
                        DocumentEmbedding.document_id == document_id
                    )
                    session.execute(delete_stmt)
                    session.commit()
                    actions_taken.append(f"Deleted {orphan_count} orphaned embeddings for non-existent document")
                    logger.info(f"[Feature #272] Deleted {orphan_count} orphaned embeddings for document {document_id}")

                duration_ms = int((time.time() - start_time) * 1000)
                return DocumentRepairReport(
                    success=orphan_count > 0,
                    document_id=document_id,
                    document_title=None,
                    actions_taken=actions_taken if actions_taken else ["Document not found, no orphaned data to clean"],
                    status_before=None,
                    status_after=None,
                    file_found=False,
                    embeddings_count=0,
                    orphaned_embeddings_cleaned=orphan_count,
                    errors=["Document not found in database"] if orphan_count == 0 else [],
                    duration_ms=duration_ms
                )

            # Document exists - proceed with repair
            logger.info(f"[Feature #272] Starting repair for document {document_id}: {doc.title}")

            status_before = doc.status
            file_path_before = doc.file_path or doc.url
            file_found = False
            file_found_at = None

            # Step 2: Check current file path
            current_file_path = doc.file_path or doc.url
            current_file_exists = _check_file_exists(current_file_path)

            if current_file_exists:
                file_found = True
                file_found_at = current_file_path
                actions_taken.append("File exists at current path")
                logger.info(f"[Feature #272] File exists at current path: {current_file_path}")
            else:
                # Step 3: Search for file by content hash
                if doc.content_hash:
                    found_path = _search_file_by_hash(uploads_dir, doc.content_hash)
                    if found_path:
                        file_found = True
                        file_found_at = found_path

                        # Update file_path in DB
                        # Store relative path
                        relative_path = os.path.relpath(found_path, backend_dir)
                        update_stmt = update(DBDocument).where(DBDocument.id == document_id).values(
                            file_path=relative_path,
                            url=relative_path  # Also update url for backwards compatibility
                        )
                        session.execute(update_stmt)
                        actions_taken.append(f"Found file by content hash, updated path: {relative_path}")
                        logger.info(f"[Feature #272] Found file by content hash at: {found_path}")

                # Step 4: Search by filename pattern if not found by hash
                if not file_found:
                    found_path = _search_file_by_pattern(uploads_dir, doc.original_filename, document_id)
                    if found_path:
                        # Verify with hash if available
                        if doc.content_hash:
                            computed_hash = _compute_file_hash(found_path)
                            if computed_hash == doc.content_hash:
                                file_found = True
                                file_found_at = found_path

                                relative_path = os.path.relpath(found_path, backend_dir)
                                update_stmt = update(DBDocument).where(DBDocument.id == document_id).values(
                                    file_path=relative_path,
                                    url=relative_path
                                )
                                session.execute(update_stmt)
                                actions_taken.append(f"Found file by pattern (hash verified), updated path: {relative_path}")
                                logger.info(f"[Feature #272] Found file by pattern at: {found_path}")
                            else:
                                actions_taken.append(f"Found potential file at {found_path} but hash mismatch")
                        else:
                            # No hash to verify - accept with warning
                            file_found = True
                            file_found_at = found_path

                            relative_path = os.path.relpath(found_path, backend_dir)
                            update_stmt = update(DBDocument).where(DBDocument.id == document_id).values(
                                file_path=relative_path,
                                url=relative_path
                            )
                            session.execute(update_stmt)
                            actions_taken.append(f"Found file by pattern (no hash to verify), updated path: {relative_path}")
                            logger.warning(f"[Feature #272] Found file by pattern (no hash verification): {found_path}")

            # Step 5: Get embedding count
            emb_count_stmt = select(func.count()).select_from(DocumentEmbedding).where(
                DocumentEmbedding.document_id == document_id
            )
            emb_count_result = session.execute(emb_count_stmt)
            embeddings_count = emb_count_result.scalar() or 0

            # Step 6: Determine and update status
            file_path_after = file_path_before
            status_after = status_before

            if file_found:
                # File exists - update file_status to OK
                update_stmt = update(DBDocument).where(DBDocument.id == document_id).values(
                    file_status=FILE_STATUS_OK
                )
                session.execute(update_stmt)

                if embeddings_count > 0:
                    # File and embeddings exist - set status to ready
                    update_stmt = update(DBDocument).where(DBDocument.id == document_id).values(
                        status=DOCUMENT_STATUS_READY,
                        embedding_status=EMBEDDING_STATUS_READY
                    )
                    session.execute(update_stmt)
                    status_after = DOCUMENT_STATUS_READY
                    actions_taken.append(f"Reset status to 'ready' (file exists, {embeddings_count} embeddings)")
                    logger.info(f"[Feature #272] Document {document_id} status reset to ready")
                else:
                    # File exists but no embeddings - may need re-embedding
                    actions_taken.append(f"File exists but no embeddings found - may need re-embedding")
                    logger.warning(f"[Feature #272] Document {document_id} has file but no embeddings")

                # Get updated file_path
                refresh_stmt = select(DBDocument.file_path, DBDocument.url).where(DBDocument.id == document_id)
                refresh_result = session.execute(refresh_stmt)
                row = refresh_result.first()
                if row:
                    file_path_after = row.file_path or row.url
            else:
                # File not found - set status to file_missing
                update_stmt = update(DBDocument).where(DBDocument.id == document_id).values(
                    file_status=FILE_STATUS_MISSING,
                    status=DOCUMENT_STATUS_FILE_MISSING
                )
                session.execute(update_stmt)
                status_after = DOCUMENT_STATUS_FILE_MISSING
                actions_taken.append("File not found - status set to 'file_missing'")
                logger.warning(f"[Feature #272] Document {document_id} file not found, marked as missing")

            # Commit all changes
            session.commit()

            duration_ms = int((time.time() - start_time) * 1000)

            return DocumentRepairReport(
                success=True,
                document_id=document_id,
                document_title=doc.title,
                actions_taken=actions_taken,
                status_before=status_before,
                status_after=status_after,
                file_path_before=file_path_before,
                file_path_after=file_path_after,
                file_found=file_found,
                file_found_at=file_found_at,
                embeddings_count=embeddings_count,
                orphaned_embeddings_cleaned=0,
                errors=errors,
                duration_ms=duration_ms
            )

    except Exception as e:
        logger.error(f"[Feature #272] Error repairing document {document_id}: {e}")
        duration_ms = int((time.time() - start_time) * 1000)
        return DocumentRepairReport(
            success=False,
            document_id=document_id,
            actions_taken=actions_taken,
            errors=[str(e)],
            duration_ms=duration_ms
        )


# ============================================================================
# File Integrity Scheduler (Feature #293)
# ============================================================================

@router.get("/file-integrity/status", response_model=FileIntegritySchedulerStatus)
async def get_file_integrity_scheduler_status():
    """
    Feature #293: Get file integrity scheduler status.

    Returns the current status of the periodic file integrity check,
    including last check time, results, and next scheduled check.
    """
    try:
        from services.file_integrity_scheduler import get_file_integrity_scheduler

        scheduler = get_file_integrity_scheduler()
        status = scheduler.get_status()

        return FileIntegritySchedulerStatus(
            enabled=status["enabled"],
            check_interval_hours=status["check_interval_hours"],
            last_check_time=status["last_check_time"],
            last_check_status=status["last_check_status"],
            last_check_error=status["last_check_error"],
            next_check_time=status["next_check_time"],
            check_in_progress=status["check_in_progress"],
            last_check_stats=status["last_check_stats"],
        )

    except Exception as e:
        logger.error(f"[Feature #293] Error getting file integrity scheduler status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/file-integrity/run-now", response_model=FileIntegrityCheckResult)
async def run_file_integrity_check_now():
    """
    Feature #293: Run file integrity check immediately.

    Triggers an immediate scan of all documents to check file existence
    and update status for any missing files.
    """
    try:
        from services.file_integrity_scheduler import get_file_integrity_scheduler

        scheduler = get_file_integrity_scheduler()
        result = scheduler.run_now()

        if result["success"]:
            return FileIntegrityCheckResult(
                success=True,
                message=result["message"],
                stats=result.get("stats"),
            )
        else:
            return FileIntegrityCheckResult(
                success=False,
                message="File integrity check failed",
                error=result.get("error"),
            )

    except Exception as e:
        logger.error(f"[Feature #293] Error running file integrity check: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/file-integrity/enable")
async def enable_file_integrity_scheduler(interval_hours: int = 6):
    """
    Feature #293: Enable file integrity scheduler.

    Args:
        interval_hours: How often to run checks (1-24 hours, default 6)
    """
    try:
        from services.file_integrity_scheduler import get_file_integrity_scheduler

        if interval_hours < 1 or interval_hours > 24:
            raise HTTPException(
                status_code=400,
                detail="Interval must be between 1 and 24 hours"
            )

        scheduler = get_file_integrity_scheduler()
        scheduler.enable(interval_hours=interval_hours)

        return {
            "success": True,
            "message": f"File integrity checks enabled (every {interval_hours} hours)"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Feature #293] Error enabling file integrity scheduler: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/file-integrity/disable")
async def disable_file_integrity_scheduler():
    """
    Feature #293: Disable file integrity scheduler.

    Stops periodic file integrity checks. Manual checks can still be triggered.
    """
    try:
        from services.file_integrity_scheduler import get_file_integrity_scheduler

        scheduler = get_file_integrity_scheduler()
        scheduler.disable()

        return {
            "success": True,
            "message": "File integrity checks disabled"
        }

    except Exception as e:
        logger.error(f"[Feature #293] Error disabling file integrity scheduler: {e}")
        raise HTTPException(status_code=500, detail=str(e))
