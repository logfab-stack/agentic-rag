"""
Shared models, helpers, state, and utilities for admin maintenance modules.

Extracted from admin_maintenance.py during Feature #353 refactor.
"""

import hashlib
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from pydantic import BaseModel
from sqlalchemy import text

from core.database import async_engine
from core.store import settings_store, embedding_store

logger = logging.getLogger(__name__)


# ==================== Re-embed Progress State (Feature #189) ====================

class ReembedProgressState:
    """Thread-safe state tracker for re-embed operations."""

    def __init__(self):
        self._lock = threading.Lock()
        self._status = "idle"  # idle, in_progress, completed, failed
        self._total_documents = 0
        self._processed = 0
        self._successful = 0
        self._failed = 0
        self._current_document_name: Optional[str] = None
        self._current_document_id: Optional[int] = None
        self._chunks_generated = 0
        self._start_time: Optional[float] = None
        self._end_time: Optional[float] = None
        self._error_message: Optional[str] = None
        self._avg_time_per_doc_ms: float = 0  # Running average for ETA calculation

    def reset(self, total_documents: int):
        """Reset state for a new operation."""
        with self._lock:
            self._status = "in_progress"
            self._total_documents = total_documents
            self._processed = 0
            self._successful = 0
            self._failed = 0
            self._current_document_name = None
            self._current_document_id = None
            self._chunks_generated = 0
            self._start_time = time.time()
            self._end_time = None
            self._error_message = None
            self._avg_time_per_doc_ms = 0

    def start_document(self, doc_id: int, doc_name: str):
        """Mark a document as being processed."""
        with self._lock:
            self._current_document_id = doc_id
            self._current_document_name = doc_name

    def finish_document(self, success: bool, chunks: int = 0, elapsed_ms: float = 0):
        """Mark a document as finished processing."""
        with self._lock:
            self._processed += 1
            if success:
                self._successful += 1
                self._chunks_generated += chunks
            else:
                self._failed += 1

            # Update running average for ETA
            if elapsed_ms > 0 and self._processed > 0:
                # Weighted moving average
                if self._avg_time_per_doc_ms == 0:
                    self._avg_time_per_doc_ms = elapsed_ms
                else:
                    self._avg_time_per_doc_ms = (self._avg_time_per_doc_ms * 0.7) + (elapsed_ms * 0.3)

    def complete(self, success: bool, error_message: Optional[str] = None):
        """Mark the operation as complete."""
        with self._lock:
            self._status = "completed" if success else "failed"
            self._end_time = time.time()
            self._current_document_name = None
            self._current_document_id = None
            self._error_message = error_message

    def get_progress(self) -> Dict[str, Any]:
        """Get current progress as a dictionary."""
        with self._lock:
            elapsed_ms = 0
            eta_ms = None

            if self._start_time:
                elapsed_ms = int((time.time() - self._start_time) * 1000)

                # Calculate ETA based on average time per document
                remaining_docs = self._total_documents - self._processed
                if remaining_docs > 0 and self._avg_time_per_doc_ms > 0:
                    eta_ms = int(remaining_docs * self._avg_time_per_doc_ms)

            percentage = 0
            if self._total_documents > 0:
                percentage = round((self._processed / self._total_documents) * 100, 1)

            return {
                "status": self._status,
                "total_documents": self._total_documents,
                "processed": self._processed,
                "successful": self._successful,
                "failed": self._failed,
                "current_document_name": self._current_document_name,
                "current_document_id": self._current_document_id,
                "chunks_generated": self._chunks_generated,
                "elapsed_ms": elapsed_ms,
                "elapsed_pretty": _format_duration(elapsed_ms) if elapsed_ms > 0 else "0s",
                "eta_ms": eta_ms,
                "eta_pretty": _format_duration(eta_ms) if eta_ms else None,
                "percentage": percentage,
                "error_message": self._error_message
            }


# Global progress state instance
reembed_progress = ReembedProgressState()


def utc_now() -> datetime:
    """Return current UTC time with timezone info."""
    return datetime.now(timezone.utc)


# ==================== Response Models ====================

class OperationResult(BaseModel):
    """Standard result for maintenance operations."""
    success: bool
    operation: str = ""
    message: str
    details: Optional[Dict[str, Any]] = None
    duration_ms: Optional[int] = None


class HealthCheckResult(BaseModel):
    """Health check with database statistics."""
    status: str
    database: Dict[str, Any]
    tables: Dict[str, int]
    storage: Dict[str, Any]
    embeddings: Dict[str, Any]
    indexes: List[Dict[str, Any]]
    pgvector_available: bool


class ConversationCleanupRequest(BaseModel):
    """Request model for conversation cleanup."""
    older_than_days: int = 30


class DocumentRepairReport(BaseModel):
    """
    Response model for document repair endpoint.
    Feature #272: Document repair endpoint.
    """
    success: bool
    document_id: str
    document_title: Optional[str] = None
    actions_taken: List[str]
    status_before: Optional[str] = None
    status_after: Optional[str] = None
    file_path_before: Optional[str] = None
    file_path_after: Optional[str] = None
    file_found: bool = False
    file_found_at: Optional[str] = None
    embeddings_count: int = 0
    orphaned_embeddings_cleaned: int = 0
    errors: List[str] = []
    duration_ms: int = 0


# ==================== Helper Functions ====================

async def run_maintenance_query(query: str, description: str) -> Dict[str, Any]:
    """Run a maintenance query and return timing info."""
    start_time = datetime.now()
    try:
        async with async_engine.begin() as conn:
            await conn.execute(text(query))
        end_time = datetime.now()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)
        return {
            "success": True,
            "description": description,
            "duration_ms": duration_ms
        }
    except Exception as e:
        logger.error(f"Maintenance query failed ({description}): {e}")
        return {
            "success": False,
            "description": description,
            "error": str(e)
        }


async def get_table_row_counts() -> Dict[str, int]:
    """Get row counts for all application tables."""
    tables = [
        'documents', 'collections', 'conversations', 'messages',
        'document_rows', 'document_embeddings', 'user_notes',
        'whatsapp_users', 'whatsapp_messages', 'chunk_feedback',
        'message_embeddings', 'settings'
    ]
    counts = {}

    async with async_engine.connect() as conn:
        for table in tables:
            try:
                result = await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                row = result.fetchone()
                counts[table] = row[0] if row else 0
            except Exception:
                counts[table] = -1  # Table doesn't exist or error

    return counts


async def get_database_size() -> Dict[str, Any]:
    """Get database size information."""
    async with async_engine.connect() as conn:
        try:
            # Get database size
            result = await conn.execute(text("""
                SELECT pg_database_size(current_database()) as size,
                       pg_size_pretty(pg_database_size(current_database())) as size_pretty
            """))
            row = result.fetchone()
            db_size = row[0] if row else 0
            db_size_pretty = row[1] if row else "0 B"

            # Get table sizes
            result = await conn.execute(text("""
                SELECT relname as table_name,
                       pg_total_relation_size(C.oid) as size,
                       pg_size_pretty(pg_total_relation_size(C.oid)) as size_pretty
                FROM pg_class C
                LEFT JOIN pg_namespace N ON (N.oid = C.relnamespace)
                WHERE nspname = 'public' AND relkind = 'r'
                ORDER BY pg_total_relation_size(C.oid) DESC
                LIMIT 10
            """))
            table_sizes = [
                {"table": row[0], "size_bytes": row[1], "size_pretty": row[2]}
                for row in result.fetchall()
            ]

            return {
                "database_size_bytes": db_size,
                "database_size_pretty": db_size_pretty,
                "largest_tables": table_sizes
            }
        except Exception as e:
            logger.error(f"Failed to get database size: {e}")
            return {
                "database_size_bytes": 0,
                "database_size_pretty": "Unknown",
                "largest_tables": [],
                "error": str(e)
            }


async def get_index_info() -> List[Dict[str, Any]]:
    """Get information about database indexes."""
    async with async_engine.connect() as conn:
        try:
            result = await conn.execute(text("""
                SELECT
                    indexname,
                    tablename,
                    pg_size_pretty(pg_relation_size(indexrelid::regclass)) as size,
                    pg_relation_size(indexrelid::regclass) as size_bytes,
                    idx_scan as scans,
                    idx_tup_read as tuples_read
                FROM pg_stat_user_indexes
                JOIN pg_indexes ON pg_stat_user_indexes.indexrelname = pg_indexes.indexname
                    AND pg_stat_user_indexes.schemaname = pg_indexes.schemaname
                WHERE pg_stat_user_indexes.schemaname = 'public'
                ORDER BY pg_relation_size(indexrelid::regclass) DESC
                LIMIT 20
            """))
            return [
                {
                    "name": row[0],
                    "table": row[1],
                    "size_pretty": row[2],
                    "size_bytes": row[3],
                    "scans": row[4],
                    "tuples_read": row[5]
                }
                for row in result.fetchall()
            ]
        except Exception as e:
            logger.error(f"Failed to get index info: {e}")
            return []


# ==================== File/Format Helpers ====================

def _format_size(size_bytes: int) -> str:
    """Format bytes as human-readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def _format_duration(ms: int) -> str:
    """Format milliseconds as human-readable duration."""
    if ms < 1000:
        return f"{ms}ms"
    elif ms < 60000:
        return f"{ms / 1000:.1f} seconds"
    elif ms < 3600000:
        minutes = ms / 60000
        return f"{minutes:.1f} minutes"
    else:
        hours = ms / 3600000
        return f"{hours:.1f} hours"


def _check_file_exists(file_path: Optional[str]) -> bool:
    """Check if a file exists on disk.

    Args:
        file_path: Path to the file (can be absolute or relative)

    Returns:
        True if file exists, False otherwise
    """
    if not file_path:
        return False

    # Get backend directory for relative paths
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    # Handle both absolute and relative paths
    if os.path.isabs(file_path):
        full_path = file_path
    else:
        full_path = os.path.join(backend_dir, file_path)

    return os.path.exists(full_path) and os.path.isfile(full_path)


def _compute_file_hash(file_path: str) -> Optional[str]:
    """Compute SHA-256 hash of a file."""
    try:
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except Exception:
        return None


def _search_file_by_hash(uploads_dir: str, content_hash: str) -> Optional[str]:
    """Search for a file in uploads directory by content hash."""
    if not content_hash or not os.path.isdir(uploads_dir):
        return None

    for filename in os.listdir(uploads_dir):
        file_path = os.path.join(uploads_dir, filename)
        if os.path.isfile(file_path):
            file_hash = _compute_file_hash(file_path)
            if file_hash == content_hash:
                return file_path
    return None


def _search_file_by_pattern(uploads_dir: str, original_filename: str, document_id: str) -> Optional[str]:
    """
    Search for a file by filename pattern.

    Looks for:
    1. Files containing the document ID
    2. Files with matching extension to original filename
    """
    if not os.path.isdir(uploads_dir):
        return None

    # Get original extension
    _, ext = os.path.splitext(original_filename) if original_filename else ('', '')

    for filename in os.listdir(uploads_dir):
        file_path = os.path.join(uploads_dir, filename)
        if not os.path.isfile(file_path):
            continue

        # Check if filename contains the document ID
        if str(document_id) in filename:
            return file_path

        # Check for files with matching extension that might be orphaned
        if ext and filename.endswith(ext):
            # This is a weak match - use hash comparison for confirmation
            pass

    return None
