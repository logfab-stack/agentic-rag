"""
Re-embedding operations + model tracking endpoints.

Feature #353: Refactored from admin_maintenance.py.
"""

import logging
import os
import time
from datetime import datetime
from typing import Dict, Any, Optional, List

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.store import settings_store, embedding_store

from ._shared import (
    OperationResult,
    reembed_progress,
    _format_size,
    _format_duration,
    utc_now,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ==================== Local Models ====================

class ReembedResult(BaseModel):
    """Result from re-embedding operation."""
    success: bool
    message: str
    total_documents: int
    processed: int
    successful: int
    failed: int
    failed_documents: List[Dict[str, Any]]
    duration_ms: int
    new_embedding_model: str


class ReembedProgress(BaseModel):
    """Progress information for re-embedding operation."""
    total_documents: int
    processed: int
    successful: int
    failed: int
    current_document: Optional[str] = None
    estimated_time_remaining_ms: Optional[int] = None


class EmbeddingModelBackfillResult(BaseModel):
    """Result from backfilling embedding_model column."""
    success: bool
    total_documents: int
    backfilled: int
    skipped: int  # Structured documents that don't have embeddings
    failed: int
    message: str
    details: List[Dict[str, Any]] = []


class DocumentModelMismatch(BaseModel):
    """Document with mismatched embedding model."""
    id: str
    title: str
    document_embedding_model: Optional[str]  # Model stored on document
    chunk_embedding_source: Optional[str]  # Model from first chunk metadata
    status: str  # 'mismatch', 'missing_on_document', 'unknown', 'ok'


class ModelMismatchResult(BaseModel):
    """Result from checking for model mismatches."""
    success: bool
    current_configured_model: str
    documents_needing_reembed: int
    documents_with_mismatch: List[DocumentModelMismatch]
    message: str


# ==================== Endpoints ====================

@router.post("/reembed-all", response_model=ReembedResult)
async def reembed_all_documents():
    """
    Re-embed all documents with the current embedding model.

    This operation:
    1. Fetches all unstructured documents (text-based, not tabular data)
    2. Deletes existing embeddings for each document
    3. Re-generates embeddings using the current embedding model setting
    4. Updates document metadata with new embedding_source

    Use this when:
    - The embedding model has been changed in Settings
    - You need to regenerate embeddings due to corruption
    - Switching between OpenAI and Ollama embedding models

    WARNING: This operation can take several minutes for large document collections.
    It is recommended to backup your data first.

    Progress can be monitored via GET /api/admin/maintenance/reembed-progress
    """
    start_time = datetime.now()

    # Import required modules
    from models.db_models import DBDocument
    from core.database import SessionLocal
    # Feature #268: Using generate_embeddings_for_reembed instead of process_unstructured_document
    # The new function generates embeddings WITHOUT storing them, allowing atomic transactions

    # Get the current embedding model from settings
    embedding_model = settings_store.get('embedding_model', 'text-embedding-3-small')

    # Track results
    total_documents = 0
    processed = 0
    successful = 0
    failed = 0
    failed_documents = []

    try:
        # Get all unstructured documents (text-based, not tabular)
        db = SessionLocal()
        try:
            # Tabular types don't get embeddings
            tabular_types = ['text/csv', 'application/vnd.ms-excel',
                            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                            'application/json']

            documents = db.query(DBDocument).filter(
                ~DBDocument.mime_type.in_(tabular_types)
            ).all()

            total_documents = len(documents)

            # Feature #189: Initialize progress tracking
            reembed_progress.reset(total_documents)

            logger.info(f"[Feature #187/189] Starting re-embed operation for {total_documents} documents")
            logger.info(f"[Feature #187/189] Target embedding model: {embedding_model}")

            if total_documents == 0:
                reembed_progress.complete(success=True)
                end_time = datetime.now()
                duration_ms = int((end_time - start_time).total_seconds() * 1000)
                return ReembedResult(
                    success=True,
                    message="No documents to re-embed",
                    total_documents=0,
                    processed=0,
                    successful=0,
                    failed=0,
                    failed_documents=[],
                    duration_ms=duration_ms,
                    new_embedding_model=embedding_model
                )

            # Import document status constants for Feature #251
            from models.db_models import EMBEDDING_STATUS_READY, EMBEDDING_STATUS_PROCESSING, EMBEDDING_STATUS_FAILED

            # Process each document
            for doc in documents:
                doc_start_time = time.time()
                processed += 1

                # Feature #189: Update progress - start processing document
                reembed_progress.start_document(doc.id, doc.title)

                logger.info(f"[Feature #187/189] Processing document {processed}/{total_documents}: {doc.title} (id: {doc.id})")

                # [Feature #251] Set document status to 'processing' before starting re-embed
                try:
                    doc.embedding_status = EMBEDDING_STATUS_PROCESSING
                    db.commit()
                    logger.info(f"[Feature #251] Set document {doc.id} status to 'processing'")
                except Exception as status_error:
                    logger.warning(f"[Feature #251] Could not set processing status: {status_error}")

                try:
                    # Feature #253: Check if file exists using file_path (preferred) or url (fallback)
                    file_path = doc.file_path or doc.url
                    if not file_path or not os.path.exists(file_path):
                        logger.warning(f"[Feature #187/189] File not found for document {doc.id}: {file_path}")
                        # [Feature #251] Mark document as embedding_failed when file not found
                        doc.embedding_status = EMBEDDING_STATUS_FAILED
                        db.commit()
                        logger.error(f"[Feature #251] Set document {doc.id} status to 'embedding_failed' (file not found)")
                        failed += 1
                        failed_documents.append({
                            "id": doc.id,
                            "title": doc.title,
                            "error": f"File not found: {file_path}",
                            "embedding_status": "embedding_failed"
                        })
                        doc_elapsed_ms = (time.time() - doc_start_time) * 1000
                        reembed_progress.finish_document(success=False, elapsed_ms=doc_elapsed_ms)
                        continue

                    # [Feature #268] ATOMIC TRANSACTION STRATEGY: Generate embeddings first, then
                    # atomically DELETE old + INSERT new in a single database transaction.
                    # This provides ACID guarantees - if anything fails, old embeddings are preserved.

                    # Step 0: Create backup in embeddings_backup table (Feature #250 - still useful for disaster recovery)
                    backup_count = embedding_store.backup_embeddings_to_table(str(doc.id), reason="reembed")
                    logger.info(f"[Feature #250/268] Backed up {backup_count} embeddings to backup table for document {doc.id}")

                    # Step 1: Generate new embeddings WITHOUT storing them (Feature #268)
                    from pathlib import Path
                    from api.documents import generate_embeddings_for_reembed

                    reembed_failed = False
                    reembed_error = None
                    embedding_model_used = None
                    num_chunks = 0

                    logger.info(f"[Feature #268] PHASE 1: Generating embeddings for document {doc.id}")

                    try:
                        chunk_data, warning, embedding_model_used = await generate_embeddings_for_reembed(
                            document_id=doc.id,
                            file_path=Path(file_path),
                            mime_type=doc.mime_type,
                            document_title=doc.title
                        )

                        if not chunk_data:
                            reembed_failed = True
                            reembed_error = warning or "No chunks generated"
                        else:
                            num_chunks = len(chunk_data)
                            logger.info(f"[Feature #268] Generated {num_chunks} embeddings for document {doc.id}")

                    except Exception as gen_error:
                        reembed_failed = True
                        reembed_error = str(gen_error)
                        chunk_data = []

                    # Step 2: If embedding generation failed, keep old embeddings (no transaction needed)
                    if reembed_failed:
                        logger.error(f"[Feature #268] Embedding generation FAILED for document {doc.id}: {reembed_error}")
                        logger.info(f"[Feature #268] Old embeddings preserved (no transaction started)")

                        doc.embedding_status = EMBEDDING_STATUS_FAILED
                        db.commit()

                        failed += 1
                        failed_documents.append({
                            "id": doc.id,
                            "title": doc.title,
                            "error": reembed_error,
                            "rollback": "Old embeddings preserved (generation failed before transaction)",
                            "embedding_status": "embedding_failed"
                        })
                        doc_elapsed_ms = (time.time() - doc_start_time) * 1000
                        reembed_progress.finish_document(success=False, elapsed_ms=doc_elapsed_ms)
                        continue

                    # Step 3: Atomically replace old embeddings with new ones (Feature #268)
                    logger.info(f"[Feature #268] PHASE 2: Atomic transaction - DELETE old + INSERT new")

                    tx_result = embedding_store.atomic_reembed_document(
                        document_id=str(doc.id),
                        new_chunks=chunk_data,
                        embedding_source=embedding_model_used or "unknown"
                    )

                    if not tx_result["success"]:
                        # Transaction rolled back - old embeddings preserved
                        logger.error(f"[Feature #268] TRANSACTION ROLLBACK for document {doc.id}: {tx_result.get('error')}")

                        doc.embedding_status = EMBEDDING_STATUS_FAILED
                        db.commit()

                        failed += 1
                        failed_documents.append({
                            "id": doc.id,
                            "title": doc.title,
                            "error": tx_result.get("error", "Transaction failed"),
                            "rollback": f"Transaction rolled back - old embeddings preserved",
                            "transaction_action": tx_result.get("transaction_action"),
                            "embedding_status": "embedding_failed"
                        })
                        doc_elapsed_ms = (time.time() - doc_start_time) * 1000
                        reembed_progress.finish_document(success=False, elapsed_ms=doc_elapsed_ms)
                        logger.info(f"[Feature #268] TRANSACTION ROLLBACK COMPLETE for document {doc.id}")
                        continue

                    # Transaction committed successfully
                    logger.info(f"[Feature #268] TRANSACTION COMMIT for document {doc.id}: "
                               f"deleted={tx_result['deleted_count']}, inserted={tx_result['inserted_count']}")

                    # [Feature #251] POST RE-EMBED VERIFICATION
                    verification = embedding_store.verify_document_embeddings(str(doc.id), expected_count=num_chunks)
                    logger.info(f"[Feature #251/268] Post re-embed verification: {verification['message']}")

                    if not verification["success"]:
                        # Verification failed but transaction already committed
                        # Try to restore from backup (Feature #250)
                        logger.error(f"[Feature #268] VERIFICATION FAILED after commit: {verification['message']}")

                        if backup_count > 0:
                            logger.info(f"[Feature #268] Attempting emergency restore from backup table")
                            restored = embedding_store.restore_embeddings_from_backup(str(doc.id))
                            if restored > 0:
                                logger.info(f"[Feature #268] Emergency restored {restored} embeddings from backup")
                                doc.embedding_status = EMBEDDING_STATUS_READY
                            else:
                                doc.embedding_status = EMBEDDING_STATUS_FAILED
                        else:
                            doc.embedding_status = EMBEDDING_STATUS_FAILED

                        db.commit()

                        failed += 1
                        failed_documents.append({
                            "id": doc.id,
                            "title": doc.title,
                            "error": f"Verification failed: {verification['message']}",
                            "embedding_status": doc.embedding_status
                        })
                        doc_elapsed_ms = (time.time() - doc_start_time) * 1000
                        reembed_progress.finish_document(success=False, elapsed_ms=doc_elapsed_ms)
                        continue

                    # Success! Clean up backup
                    backup_deleted = embedding_store.delete_backup_for_document(str(doc.id))
                    logger.info(f"[Feature #250/268] Deleted {backup_deleted} backup entries for document {doc.id}")

                    # Update BM25 index for hybrid search (Feature #186)
                    try:
                        from services.bm25_service import bm25_service
                        # Delete old BM25 entries and add new ones
                        bm25_service.delete_document(str(doc.id))
                        bm25_stored = bm25_service.add_chunks(str(doc.id), chunk_data)
                        logger.info(f"[Feature #186/268] Updated BM25 index: {bm25_stored} chunks for document {doc.id}")
                    except Exception as bm25_error:
                        logger.warning(f"[Feature #186/268] Failed to update BM25 index: {bm25_error}")

                    successful += 1
                    logger.info(f"[Feature #268] Successfully re-embedded document {doc.id}: "
                               f"{num_chunks} chunks (transaction: {tx_result['transaction_action']})")

                    # [Feature #251] Set document status to 'ready'
                    doc.embedding_status = EMBEDDING_STATUS_READY

                    # [Feature #259] Update embedding_model
                    if embedding_model_used:
                        doc.embedding_model = embedding_model_used
                        logger.info(f"[Feature #259/268] Set document {doc.id} embedding_model to '{embedding_model_used}'")

                    # [Feature #234] Update document timestamp
                    doc.updated_at = utc_now()
                    db.commit()
                    logger.debug(f"[Feature #234/251/259/268] Updated document {doc.id} timestamp, status and embedding_model")

                    doc_elapsed_ms = (time.time() - doc_start_time) * 1000
                    reembed_progress.finish_document(success=True, chunks=num_chunks, elapsed_ms=doc_elapsed_ms)

                except Exception as doc_error:
                    # [Feature #268] Unexpected error - try to restore from backup table
                    failed += 1
                    error_msg = str(doc_error)
                    logger.error(f"[Feature #268] Unexpected error processing document {doc.id}: {error_msg}")

                    # Try to restore from backup table (Feature #250/268)
                    doc_status = EMBEDDING_STATUS_FAILED
                    try:
                        if 'backup_count' in locals() and backup_count > 0:
                            logger.info(f"[Feature #268] EMERGENCY RESTORE - Attempting to restore from backup table for document {doc.id}")
                            restored_count = embedding_store.restore_embeddings_from_backup(str(doc.id))
                            logger.info(f"[Feature #268] Emergency restored {restored_count} embeddings from backup for document {doc.id}")
                            error_msg += " (original embeddings restored from backup table)"
                            if restored_count > 0:
                                doc_status = EMBEDDING_STATUS_READY
                    except Exception as restore_error:
                        logger.error(f"[Feature #268] Failed to restore from backup: {restore_error}")
                        error_msg += f" (WARNING: backup restore failed: {restore_error})"

                    # [Feature #251/268] Update document status based on recovery outcome
                    try:
                        doc.embedding_status = doc_status
                        db.commit()
                        logger.info(f"[Feature #268] Set document {doc.id} status to '{doc_status}' after exception")
                    except Exception as status_err:
                        logger.error(f"[Feature #251] Failed to update status: {status_err}")

                    failed_documents.append({
                        "id": doc.id,
                        "title": doc.title,
                        "error": error_msg,
                        "embedding_status": doc_status
                    })
                    doc_elapsed_ms = (time.time() - doc_start_time) * 1000
                    reembed_progress.finish_document(success=False, elapsed_ms=doc_elapsed_ms)

        finally:
            db.close()

    except Exception as e:
        logger.error(f"[Feature #187/189] Fatal error during re-embed operation: {e}")
        reembed_progress.complete(success=False, error_message=str(e))
        end_time = datetime.now()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)
        return ReembedResult(
            success=False,
            message=f"Re-embedding failed: {str(e)}",
            total_documents=total_documents,
            processed=processed,
            successful=successful,
            failed=failed,
            failed_documents=failed_documents,
            duration_ms=duration_ms,
            new_embedding_model=embedding_model
        )

    end_time = datetime.now()
    duration_ms = int((end_time - start_time).total_seconds() * 1000)

    # Determine success status
    all_succeeded = failed == 0 and successful == total_documents

    if all_succeeded:
        message = f"Successfully re-embedded all {total_documents} documents with {embedding_model}"
    elif successful > 0:
        message = f"Re-embedded {successful}/{total_documents} documents. {failed} failed."
    else:
        message = f"Failed to re-embed any documents. {failed} errors occurred."

    # Feature #189: Mark progress as complete
    reembed_progress.complete(success=(all_succeeded or successful > 0))

    logger.info(f"[Feature #187/189] Re-embed operation completed: {message}")
    logger.info(f"[Feature #187/189] Duration: {duration_ms}ms")

    return ReembedResult(
        success=all_succeeded or successful > 0,
        message=message,
        total_documents=total_documents,
        processed=processed,
        successful=successful,
        failed=failed,
        failed_documents=failed_documents,
        duration_ms=duration_ms,
        new_embedding_model=embedding_model
    )


@router.get("/reembed-progress")
async def get_reembed_progress():
    """
    Get the current progress of the re-embedding operation.

    Feature #189: Real-time progress tracking for re-embed operations.

    Returns:
    - status: "idle" | "in_progress" | "completed" | "failed"
    - total_documents: Total documents to process
    - processed: Number of documents processed so far
    - successful: Number of documents successfully re-embedded
    - failed: Number of documents that failed
    - current_document_name: Name of document currently being processed
    - current_document_id: ID of document currently being processed
    - chunks_generated: Total chunks generated so far
    - elapsed_ms: Time elapsed since operation started
    - elapsed_pretty: Human-readable elapsed time
    - eta_ms: Estimated time remaining in milliseconds
    - eta_pretty: Human-readable estimated time remaining
    - percentage: Percentage complete (0-100)
    - error_message: Error message if status is "failed"

    Poll this endpoint every 1-2 seconds during re-embed operations.
    """
    return reembed_progress.get_progress()


@router.get("/reembed-success-rate")
async def get_reembed_success_rate(db: AsyncSession = Depends(get_db)):
    """
    Feature #297: Get re-embedding success rate metrics.

    Returns statistics about re-embed operation success rate, including:
    - total_attempts: Total number of re-embed attempts
    - successful: Number of successful re-embeds
    - failed: Number of failed re-embeds (where verification failed)
    - success_rate: Percentage of successful re-embeds
    - by_status: Breakdown of documents by current status
    - verification_failed_documents: List of documents that failed verification

    Use this endpoint to monitor the health of re-embedding operations.
    """
    from services.document_audit_service import get_reembed_success_rate

    try:
        stats = await get_reembed_success_rate(db)
        return {
            "success": True,
            **stats
        }
    except Exception as e:
        logger.error(f"[Feature #297] Error getting re-embed success rate: {e}")
        return {
            "success": False,
            "error": str(e),
            "total_attempts": 0,
            "successful": 0,
            "failed": 0,
            "success_rate": 0.0
        }


@router.get("/reembed-estimate")
async def estimate_reembed_time():
    """
    Estimate the time required to re-embed all documents.

    Returns an estimate based on:
    - Number of documents
    - Total file size
    - Current embedding model

    This is useful for showing users an estimated duration before starting.
    """
    from models.db_models import DBDocument
    from core.database import SessionLocal

    # Get current embedding model
    embedding_model = settings_store.get('embedding_model', 'text-embedding-3-small')

    try:
        db = SessionLocal()
        try:
            # Tabular types don't get embeddings
            tabular_types = ['text/csv', 'application/vnd.ms-excel',
                            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                            'application/json']

            documents = db.query(DBDocument).filter(
                ~DBDocument.mime_type.in_(tabular_types)
            ).all()

            total_documents = len(documents)
            total_size_bytes = 0

            for doc in documents:
                # Feature #253: Use file_path (preferred) or url (fallback) for file size calculation
                fp = doc.file_path or doc.url
                if fp and os.path.exists(fp):
                    total_size_bytes += os.path.getsize(fp)

            # Estimate time based on:
            # - ~5 seconds per document for chunking and processing
            # - ~2 seconds per MB for embedding generation
            # - Varies by model (Ollama is slower than OpenAI)

            base_time_per_doc_ms = 5000  # 5 seconds base
            time_per_mb_ms = 2000  # 2 seconds per MB

            if embedding_model.startswith('ollama:'):
                # Ollama is typically slower
                base_time_per_doc_ms *= 2
                time_per_mb_ms *= 2

            estimated_ms = (
                total_documents * base_time_per_doc_ms +
                (total_size_bytes / (1024 * 1024)) * time_per_mb_ms
            )

            # Get current embedding counts per document
            embedding_counts = {}
            for doc in documents:
                count = embedding_store.get_embedding_count_for_document(doc.id)
                embedding_counts[doc.id] = count

            total_existing_embeddings = sum(embedding_counts.values())

            return {
                "total_documents": total_documents,
                "total_size_bytes": total_size_bytes,
                "total_size_pretty": _format_size(total_size_bytes),
                "estimated_duration_ms": int(estimated_ms),
                "estimated_duration_pretty": _format_duration(int(estimated_ms)),
                "current_embedding_model": embedding_model,
                "total_existing_embeddings": total_existing_embeddings,
                "warning": "Changing embedding models requires re-processing all documents. This operation cannot be undone."
            }

        finally:
            db.close()

    except Exception as e:
        logger.error(f"[Feature #187] Error estimating re-embed time: {e}")
        return {
            "total_documents": 0,
            "total_size_bytes": 0,
            "total_size_pretty": "0 B",
            "estimated_duration_ms": 0,
            "estimated_duration_pretty": "Unknown",
            "current_embedding_model": embedding_model,
            "total_existing_embeddings": 0,
            "error": str(e)
        }


@router.post("/backfill-embedding-models", response_model=EmbeddingModelBackfillResult)
async def backfill_embedding_models():
    """
    Feature #259: Backfill embedding_model column for existing documents.

    For each unstructured document that has NULL embedding_model:
    1. Query its embeddings to get the embedding_source from metadata
    2. Update the document's embedding_model field

    Structured documents (CSV, Excel, JSON) are skipped as they don't have embeddings.
    """
    logger.info("[Feature #259] Starting embedding model backfill operation")

    try:
        from core.database import SessionLocal
        from models.db_models import DBDocument

        db = SessionLocal()
        try:
            # Get all documents with NULL embedding_model
            documents = db.query(DBDocument).filter(
                DBDocument.embedding_model.is_(None)
            ).all()

            total = len(documents)
            backfilled = 0
            skipped = 0
            failed = 0
            details = []

            # Tabular types that don't have embeddings
            tabular_types = [
                'text/csv',
                'application/vnd.ms-excel',
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'application/json'
            ]

            for doc in documents:
                # Skip structured documents
                if doc.mime_type in tabular_types or doc.document_type == 'structured':
                    skipped += 1
                    logger.debug(f"[Feature #259] Skipping structured document {doc.id}")
                    continue

                # Get first embedding for this document to check metadata
                try:
                    chunks = embedding_store.get_chunks(doc.id)
                    if chunks and len(chunks) > 0:
                        # Get embedding_source from first chunk's metadata
                        metadata = chunks[0].get('metadata', {})
                        embedding_source = metadata.get('embedding_source')

                        if embedding_source:
                            doc.embedding_model = embedding_source
                            backfilled += 1
                            details.append({
                                "id": doc.id,
                                "title": doc.title,
                                "embedding_model": embedding_source,
                                "status": "backfilled"
                            })
                            logger.info(f"[Feature #259] Backfilled document {doc.id} with model '{embedding_source}'")
                        else:
                            # Embeddings exist but no source metadata
                            doc.embedding_model = 'unknown'
                            backfilled += 1
                            details.append({
                                "id": doc.id,
                                "title": doc.title,
                                "embedding_model": "unknown",
                                "status": "backfilled_unknown"
                            })
                            logger.warning(f"[Feature #259] Document {doc.id} has embeddings but no source metadata, set to 'unknown'")
                    else:
                        # No embeddings found
                        skipped += 1
                        details.append({
                            "id": doc.id,
                            "title": doc.title,
                            "status": "no_embeddings"
                        })
                        logger.debug(f"[Feature #259] Document {doc.id} has no embeddings, skipping")

                except Exception as e:
                    failed += 1
                    details.append({
                        "id": doc.id,
                        "title": doc.title,
                        "status": "failed",
                        "error": str(e)
                    })
                    logger.error(f"[Feature #259] Failed to backfill document {doc.id}: {e}")

            db.commit()
            logger.info(f"[Feature #259] Backfill complete: {backfilled} backfilled, {skipped} skipped, {failed} failed")

            return EmbeddingModelBackfillResult(
                success=True,
                total_documents=total,
                backfilled=backfilled,
                skipped=skipped,
                failed=failed,
                message=f"Backfilled {backfilled} documents, skipped {skipped}, failed {failed}",
                details=details[:50]  # Limit details to first 50
            )

        finally:
            db.close()

    except Exception as e:
        logger.error(f"[Feature #259] Error during backfill: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to backfill embedding models: {str(e)}"
        )


@router.get("/documents-needing-reembed", response_model=ModelMismatchResult)
async def get_documents_needing_reembed():
    """
    Feature #259: List documents that may need re-embedding.

    Returns documents where:
    1. embedding_model is NULL (unknown what model was used)
    2. embedding_model doesn't match current configured model
    3. embedding_model is 'unknown'

    Use this to identify documents that should be re-embedded after changing
    the embedding model in settings.
    """
    logger.info("[Feature #259] Checking for documents needing re-embed")

    try:
        from core.database import SessionLocal
        from models.db_models import DBDocument

        # Get current configured embedding model
        current_model = settings_store.get('embedding_model') or 'text-embedding-3-small'
        # Normalize: add openai: prefix if not an ollama model
        if not current_model.startswith('ollama:') and not current_model.startswith('openai:'):
            normalized_current = f"openai:{current_model}"
        else:
            normalized_current = current_model

        logger.info(f"[Feature #259] Current configured model: {current_model} (normalized: {normalized_current})")

        db = SessionLocal()
        try:
            # Tabular types that don't have embeddings
            tabular_types = [
                'text/csv',
                'application/vnd.ms-excel',
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'application/json'
            ]

            # Get all unstructured documents
            documents = db.query(DBDocument).filter(
                ~DBDocument.mime_type.in_(tabular_types)
            ).all()

            documents_with_mismatch = []

            for doc in documents:
                mismatch_status = 'ok'

                if doc.embedding_model is None:
                    # Document doesn't have embedding_model set
                    # Check embeddings for the actual model used
                    chunks = embedding_store.get_chunks(doc.id)
                    if chunks and len(chunks) > 0:
                        metadata = chunks[0].get('metadata', {})
                        chunk_source = metadata.get('embedding_source')

                        if chunk_source:
                            # Compare with current model
                            if chunk_source != normalized_current:
                                mismatch_status = 'mismatch'
                            else:
                                mismatch_status = 'missing_on_document'  # Just needs backfill
                        else:
                            mismatch_status = 'unknown'

                        documents_with_mismatch.append(DocumentModelMismatch(
                            id=doc.id,
                            title=doc.title,
                            document_embedding_model=doc.embedding_model,
                            chunk_embedding_source=chunk_source,
                            status=mismatch_status
                        ))
                    else:
                        # No embeddings at all
                        documents_with_mismatch.append(DocumentModelMismatch(
                            id=doc.id,
                            title=doc.title,
                            document_embedding_model=None,
                            chunk_embedding_source=None,
                            status='no_embeddings'
                        ))

                elif doc.embedding_model == 'unknown':
                    documents_with_mismatch.append(DocumentModelMismatch(
                        id=doc.id,
                        title=doc.title,
                        document_embedding_model=doc.embedding_model,
                        chunk_embedding_source=None,
                        status='unknown'
                    ))

                elif doc.embedding_model != normalized_current:
                    # Model mismatch - document was embedded with different model
                    documents_with_mismatch.append(DocumentModelMismatch(
                        id=doc.id,
                        title=doc.title,
                        document_embedding_model=doc.embedding_model,
                        chunk_embedding_source=None,
                        status='mismatch'
                    ))

            # Filter to only show documents that actually need attention
            needs_attention = [d for d in documents_with_mismatch if d.status != 'ok']

            return ModelMismatchResult(
                success=True,
                current_configured_model=normalized_current,
                documents_needing_reembed=len([d for d in needs_attention if d.status == 'mismatch']),
                documents_with_mismatch=needs_attention,
                message=f"Found {len(needs_attention)} documents that may need attention"
            )

        finally:
            db.close()

    except Exception as e:
        logger.error(f"[Feature #259] Error checking documents: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to check documents: {str(e)}"
        )
