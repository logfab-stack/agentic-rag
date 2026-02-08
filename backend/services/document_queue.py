"""
Document Processing Queue Service

Feature #330: Background document processing with async queue
Feature #337: Prevent concurrent document processing from blocking backend

This service provides:
- Async queue for document processing
- Background worker that processes documents one at a time
- Status tracking and error handling
- Queue statistics endpoint
- Global semaphore to limit concurrent Agentic Splitter operations (Feature #337)

The queue allows document uploads to return immediately without waiting
for potentially slow processing (chunking, embedding generation).

Feature #337: Added processing semaphore to ensure only 1 document is processed
at a time, preventing multiple concurrent LLM calls from overwhelming the backend.
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Callable, Awaitable
from pathlib import Path
from enum import Enum

from core.logging_config import get_logger

logger = get_logger(__name__)

# Feature #337: Global semaphore to limit concurrent document processing
# This prevents multiple Agentic Splitter operations from running in parallel
# and overwhelming the backend with LLM calls
_processing_semaphore: Optional[asyncio.Semaphore] = None
_MAX_CONCURRENT_PROCESSING = 1  # Process only 1 document at a time


def get_processing_semaphore() -> asyncio.Semaphore:
    """
    Get the global processing semaphore.

    Feature #337: This semaphore limits concurrent document processing to 1,
    preventing the Agentic Splitter from making too many parallel LLM calls.

    The semaphore is created lazily to ensure it's created in the right event loop.
    """
    global _processing_semaphore
    if _processing_semaphore is None:
        _processing_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_PROCESSING)
        logger.info(f"[Feature #337] Created processing semaphore (max_concurrent={_MAX_CONCURRENT_PROCESSING})")
    return _processing_semaphore


async def acquire_processing_slot(timeout: float = 300.0) -> bool:
    """
    Acquire a processing slot from the global semaphore.

    Feature #337: Use this to ensure only one document is processed at a time.

    Args:
        timeout: Maximum time to wait for a slot (default 5 minutes)

    Returns:
        True if slot acquired, False if timeout
    """
    semaphore = get_processing_semaphore()
    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=timeout)
        logger.debug("[Feature #337] Acquired processing slot")
        return True
    except asyncio.TimeoutError:
        logger.warning(f"[Feature #337] Timeout waiting for processing slot ({timeout}s)")
        return False


def release_processing_slot() -> None:
    """
    Release a processing slot back to the global semaphore.

    Feature #337: Call this after document processing is complete.
    """
    global _processing_semaphore
    if _processing_semaphore is not None:
        _processing_semaphore.release()
        logger.debug("[Feature #337] Released processing slot")


async def with_processing_slot(
    func: Callable[[], Awaitable[Any]],
    timeout: float = 300.0
) -> Any:
    """
    Execute a function while holding the processing semaphore.

    Feature #337: Ensures only one document processing operation runs at a time.

    Args:
        func: Async function to execute
        timeout: Maximum time to wait for a slot

    Returns:
        Result of the function

    Raises:
        TimeoutError: If slot couldn't be acquired within timeout
    """
    if not await acquire_processing_slot(timeout):
        raise TimeoutError(f"Could not acquire processing slot within {timeout}s")

    try:
        return await func()
    finally:
        release_processing_slot()


class QueueItemStatus(str, Enum):
    """Status of a queue item."""
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class QueueItem:
    """Represents a document in the processing queue."""
    document_id: str
    file_path: str
    mime_type: str
    document_title: str
    document_type: str  # 'structured' or 'unstructured'
    collection_id: Optional[str] = None
    status: QueueItemStatus = QueueItemStatus.QUEUED
    queued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "document_id": self.document_id,
            "file_path": self.file_path,
            "mime_type": self.mime_type,
            "document_title": self.document_title,
            "document_type": self.document_type,
            "collection_id": self.collection_id,
            "status": self.status.value,
            "queued_at": self.queued_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error_message": self.error_message,
            "result": self.result,
        }


class DocumentProcessingQueue:
    """
    Async queue for document processing.

    Implements a simple in-memory queue with a single background worker.
    Documents are processed one at a time to avoid overwhelming the system
    with concurrent embedding generation.
    """

    def __init__(self, max_queue_size: int = 100):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self._items: Dict[str, QueueItem] = {}  # Track all items by document_id
        self._processing: Optional[QueueItem] = None  # Currently processing item
        self._worker_task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._max_queue_size = max_queue_size

        # Statistics
        self._total_processed: int = 0
        self._total_failed: int = 0
        self._total_time_ms: int = 0
        self._started_at: Optional[datetime] = None

        logger.info(f"[Feature #330] DocumentProcessingQueue initialized (max_size={max_queue_size})")

    async def start(self) -> None:
        """Start the background worker."""
        if self._running:
            logger.warning("[Feature #330] Queue worker already running")
            return

        self._running = True
        self._started_at = datetime.now(timezone.utc)
        self._worker_task = asyncio.create_task(self._worker())
        logger.info("[Feature #330] Document processing queue started")

    async def stop(self) -> None:
        """Stop the background worker gracefully."""
        if not self._running:
            return

        self._running = False

        # Cancel worker task if it exists
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

        logger.info(f"[Feature #330] Document processing queue stopped (processed={self._total_processed}, failed={self._total_failed})")

    async def enqueue(self, item: QueueItem) -> bool:
        """
        Add a document to the processing queue.

        Returns True if successfully queued, False if queue is full.
        """
        if self._queue.full():
            logger.warning(f"[Feature #330] Queue is full, cannot enqueue document {item.document_id}")
            return False

        self._items[item.document_id] = item
        await self._queue.put(item)
        logger.info(f"[Feature #330] Enqueued document {item.document_id} (queue_size={self._queue.qsize()})")
        return True

    def get_item_status(self, document_id: str) -> Optional[QueueItem]:
        """Get the status of a queued item by document ID."""
        return self._items.get(document_id)

    def get_queue_status(self) -> Dict[str, Any]:
        """Get overall queue status."""
        queued_items = [item for item in self._items.values() if item.status == QueueItemStatus.QUEUED]
        processing_items = [item for item in self._items.values() if item.status == QueueItemStatus.PROCESSING]
        completed_items = [item for item in self._items.values() if item.status == QueueItemStatus.COMPLETED]
        failed_items = [item for item in self._items.values() if item.status == QueueItemStatus.FAILED]

        avg_time_ms = self._total_time_ms // self._total_processed if self._total_processed > 0 else 0

        return {
            "running": self._running,
            "queue_size": self._queue.qsize(),
            "max_queue_size": self._max_queue_size,
            "queued_count": len(queued_items),
            "processing_count": len(processing_items),
            "completed_count": len(completed_items),
            "failed_count": len(failed_items),
            "total_processed": self._total_processed,
            "total_failed": self._total_failed,
            "average_processing_time_ms": avg_time_ms,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "current_item": self._processing.to_dict() if self._processing else None,
            "queued_items": [item.to_dict() for item in queued_items],
        }

    async def _worker(self) -> None:
        """Background worker that processes documents from the queue."""
        logger.info("[Feature #330] Queue worker started")

        while self._running:
            try:
                # Wait for an item with timeout to allow graceful shutdown
                try:
                    item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                self._processing = item
                item.status = QueueItemStatus.PROCESSING
                item.started_at = datetime.now(timezone.utc)

                logger.info(f"[Feature #330] Processing document {item.document_id} ({item.document_title})")

                start_time = time.time()

                try:
                    # Update document status to 'processing' in database
                    await self._update_document_status(item.document_id, 'processing')

                    # Feature #337: Acquire processing semaphore before processing
                    # This ensures only 1 document is processed at a time, even if
                    # other code paths (like Telegram) also use the semaphore
                    if not await acquire_processing_slot(timeout=600.0):
                        raise TimeoutError("Could not acquire processing slot - system may be overloaded")

                    try:
                        # Process the document
                        result = await self._process_document(item)
                    finally:
                        # Always release the slot after processing
                        release_processing_slot()

                    # Mark as completed
                    item.status = QueueItemStatus.COMPLETED
                    item.completed_at = datetime.now(timezone.utc)
                    item.result = result
                    self._total_processed += 1

                    # Update document status to 'ready' (or 'embedding_failed' if failed)
                    final_status = result.get('final_status', 'ready')
                    await self._update_document_status(item.document_id, final_status)

                    processing_time = int((time.time() - start_time) * 1000)
                    self._total_time_ms += processing_time

                    logger.info(f"[Feature #330] Completed processing document {item.document_id} in {processing_time}ms")

                except Exception as e:
                    # Mark as failed
                    item.status = QueueItemStatus.FAILED
                    item.completed_at = datetime.now(timezone.utc)
                    item.error_message = str(e)
                    self._total_failed += 1

                    # Update document status to 'embedding_failed'
                    await self._update_document_status(item.document_id, 'embedding_failed', error_message=str(e))

                    logger.error(f"[Feature #330] Failed to process document {item.document_id}: {e}")

                finally:
                    self._processing = None
                    self._queue.task_done()

            except asyncio.CancelledError:
                logger.info("[Feature #330] Queue worker cancelled")
                break
            except Exception as e:
                logger.error(f"[Feature #330] Queue worker error: {e}")
                # Continue processing other items

        logger.info("[Feature #330] Queue worker stopped")

    async def _update_document_status(
        self,
        document_id: str,
        status: str,
        error_message: Optional[str] = None
    ) -> None:
        """Update document status in the database."""
        try:
            from core.database import get_db
            from core.store_postgres import DocumentStorePostgres
            from models.document import DocumentUpdate

            async for session in get_db():
                store = DocumentStorePostgres(session)

                update_data = {"status": status}
                if error_message:
                    # Append error to comment
                    doc = await store.get(document_id)
                    if doc:
                        existing_comment = doc.comment or ""
                        update_data["comment"] = f"{existing_comment}\n\n⚠️ Processing error: {error_message}".strip()

                await store.update(document_id, DocumentUpdate(**update_data))
                await session.commit()
                logger.debug(f"[Feature #330] Updated document {document_id} status to '{status}'")
                break  # Only need one session

        except Exception as e:
            logger.error(f"[Feature #330] Failed to update document status: {e}")

    async def _process_document(self, item: QueueItem) -> Dict[str, Any]:
        """
        Process a document (chunking, embedding generation).

        This is the actual document processing logic, extracted from the upload endpoint.
        """
        result = {
            "document_id": item.document_id,
            "chunks_created": 0,
            "embedding_status": "skipped",
            "warnings": [],
            "final_status": "ready"
        }

        try:
            from core.database import get_db
            from core.store_postgres import DocumentStorePostgres, DocumentRowsStorePostgres
            # Feature #333: Use async wrappers to prevent blocking event loop
            from api.documents import parse_structured_data_async, process_unstructured_document
            from models.document import DocumentUpdate
            from models.db_models import DOCUMENT_STATUS_READY, DOCUMENT_STATUS_EMBEDDING_FAILED
            from core.store import settings_store
            import json
            import time

            file_path = Path(item.file_path)

            async for session in get_db():
                document_store = DocumentStorePostgres(session)
                document_rows_store = DocumentRowsStorePostgres(session)

                if item.document_type == "structured":
                    # Process structured data (CSV, Excel, JSON)
                    try:
                        # Feature #333: Use async wrapper to prevent blocking event loop
                        rows, schema = await parse_structured_data_async(file_path, item.mime_type)
                        if rows:
                            await document_rows_store.add_rows(item.document_id, rows, schema)
                            schema_json = json.dumps(schema)
                            update_data = DocumentUpdate(schema_info=schema_json, status=DOCUMENT_STATUS_READY)
                            await document_store.update(item.document_id, update_data)
                            await session.commit()
                            logger.info(f"[Feature #330] Stored {len(rows)} rows for document {item.document_id}")
                            result["rows_stored"] = len(rows)
                        else:
                            update_data = DocumentUpdate(status=DOCUMENT_STATUS_READY)
                            await document_store.update(item.document_id, update_data)
                            await session.commit()

                        result["embedding_status"] = "skipped"  # Structured data doesn't get embeddings
                        result["final_status"] = "ready"

                    except Exception as e:
                        logger.error(f"[Feature #330] Error processing structured data: {e}")
                        result["warnings"].append(f"Error processing structured data: {str(e)}")
                        result["final_status"] = "ready"  # Still mark as ready, just without rows

                else:
                    # Process unstructured data (PDF, TXT, Word, Markdown)
                    embedding_start_time = time.time()
                    embedding_model_for_audit = settings_store.get('embedding_source', 'openai:text-embedding-3-small')

                    try:
                        num_chunks, warning_msg, embedding_model_used = await process_unstructured_document(
                            item.document_id,
                            file_path,
                            item.mime_type,
                            item.document_title,
                            document_rows_store=document_rows_store
                        )

                        result["chunks_created"] = num_chunks

                        if num_chunks > 0:
                            logger.info(f"[Feature #330] Created {num_chunks} embeddings for document {item.document_id}")

                            if warning_msg:
                                result["warnings"].append(warning_msg)
                                result["embedding_status"] = "partial"
                            else:
                                result["embedding_status"] = "success"

                            # Update document status
                            update_data = DocumentUpdate(
                                status=DOCUMENT_STATUS_READY,
                                embedding_model=embedding_model_used
                            )
                            await document_store.update(item.document_id, update_data)
                            await session.commit()
                            result["final_status"] = "ready"

                        else:
                            # No embeddings created
                            warning = warning_msg or "No embeddings could be generated"
                            result["warnings"].append(warning)
                            result["embedding_status"] = "failed"
                            result["final_status"] = "embedding_failed"

                            # Get existing comment and append warning
                            doc = await document_store.get(item.document_id)
                            existing_comment = doc.comment or "" if doc else ""

                            update_data = DocumentUpdate(
                                comment=f"{existing_comment}\n\n⚠️ WARNING: {warning}".strip(),
                                status=DOCUMENT_STATUS_EMBEDDING_FAILED
                            )
                            await document_store.update(item.document_id, update_data)
                            await session.commit()

                    except Exception as e:
                        error_msg = f"Embedding generation failed: {str(e)}"
                        result["warnings"].append(error_msg)
                        result["embedding_status"] = "failed"
                        result["final_status"] = "embedding_failed"

                        # Update document with error
                        doc = await document_store.get(item.document_id)
                        existing_comment = doc.comment or "" if doc else ""

                        update_data = DocumentUpdate(
                            comment=f"{existing_comment}\n\n⚠️ ERROR: {error_msg}".strip(),
                            status=DOCUMENT_STATUS_EMBEDDING_FAILED
                        )
                        await document_store.update(item.document_id, update_data)
                        await session.commit()

                        logger.error(f"[Feature #330] Error processing unstructured document: {e}")

                break  # Only need one session

        except Exception as e:
            logger.error(f"[Feature #330] Failed to process document {item.document_id}: {e}")
            result["warnings"].append(str(e))
            result["final_status"] = "embedding_failed"
            raise

        return result


# Global queue instance
_document_queue: Optional[DocumentProcessingQueue] = None


def get_document_queue() -> DocumentProcessingQueue:
    """
    Get the global document processing queue.

    Note: The queue must be initialized via init_document_queue() at app startup
    for the worker to be running. If called before initialization, a new queue
    is created and the worker is started automatically.
    """
    global _document_queue
    if _document_queue is None:
        logger.info("[Feature #330] Creating document processing queue on first access")
        _document_queue = DocumentProcessingQueue()
        # Start the queue worker immediately
        # Since this is called from a sync context, we need to schedule the async start
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If event loop is running, create a task
                asyncio.create_task(_document_queue.start())
            else:
                # If no event loop, run synchronously
                loop.run_until_complete(_document_queue.start())
        except RuntimeError:
            # No event loop available - the caller will need to start the queue
            logger.warning("[Feature #330] Could not auto-start queue worker - no event loop")
    return _document_queue


async def init_document_queue() -> DocumentProcessingQueue:
    """Initialize and start the document processing queue."""
    global _document_queue
    if _document_queue is None:
        _document_queue = DocumentProcessingQueue()
    if not _document_queue._running:
        await _document_queue.start()
    return _document_queue


async def stop_document_queue() -> None:
    """Stop the document processing queue."""
    global _document_queue
    if _document_queue is not None:
        await _document_queue.stop()
