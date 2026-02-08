"""
Pre-Destructive Backup Service for Agentic RAG System (Feature #213, #222)

Automatically creates a backup before any destructive database operation.
This ensures users can always recover from accidental deletions.

Feature #213: Core pre-destructive backup functionality
Feature #222: Retention policy (keep last 5 backups) and restore capability

Destructive operations that trigger backup:
- POST /api/settings/reset-database
- DELETE /api/documents (bulk operations)
- DELETE /api/collections/{id} (when cascade affects documents)

Usage:
    from services.pre_destructive_backup import create_pre_destructive_backup

    # Before destructive operation
    backup_result = await create_pre_destructive_backup(
        operation="reset-database",
        require_backup=True  # Will block if backup fails
    )

    if not backup_result['success']:
        raise HTTPException(status_code=500, detail=backup_result['error'])

    # Proceed with destructive operation
"""

import os
import json
import logging
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from core.store import settings_store

logger = logging.getLogger(__name__)

# Configuration
BACKEND_DIR = Path(__file__).parent.parent
PRE_DELETE_BACKUPS_DIR = BACKEND_DIR / "backups" / "pre-delete"
MAX_PRE_DELETE_BACKUPS = 5  # Feature #222: Keep only last 5 auto-backups


def _ensure_pre_delete_dir():
    """Ensure the pre-delete backups directory exists."""
    PRE_DELETE_BACKUPS_DIR.mkdir(parents=True, exist_ok=True)


def _get_backup_timestamp() -> str:
    """Generate timestamp string for backup folder name."""
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def _sanitize_operation_name(operation: str) -> str:
    """Sanitize operation name for use in folder name."""
    return operation.replace("/", "_").replace(" ", "_").lower()


async def create_pre_destructive_backup(
    operation: str,
    require_backup: Optional[bool] = None,
    details: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create a backup before a destructive operation.

    Args:
        operation: Name of the operation (e.g., "reset-database", "bulk-delete", "cascade-delete")
        require_backup: Whether backup is required. If None, uses setting 'require_backup_before_delete'
        details: Optional dict with additional context (e.g., document_ids being deleted)

    Returns:
        Dict with:
            - success: bool - Whether backup was created successfully
            - backup_path: str - Path to backup folder (if successful)
            - error: str - Error message (if failed)
            - skipped: bool - True if backup was skipped (not required)
    """
    logger.info(f"[Feature #213] Pre-destructive backup requested for operation: {operation}")

    # Check if backup is required
    if require_backup is None:
        require_backup = settings_store.get('require_backup_before_delete', True)
        # Handle string 'true'/'false' from settings
        if isinstance(require_backup, str):
            require_backup = require_backup.lower() == 'true'

    if not require_backup:
        logger.info(f"[Feature #213] Backup skipped (not required) for operation: {operation}")
        return {
            'success': True,
            'backup_path': None,
            'error': None,
            'skipped': True
        }

    try:
        _ensure_pre_delete_dir()

        # Create backup folder with descriptive name
        timestamp = _get_backup_timestamp()
        sanitized_op = _sanitize_operation_name(operation)
        backup_folder_name = f"{timestamp}_{sanitized_op}"
        backup_path = PRE_DELETE_BACKUPS_DIR / backup_folder_name
        backup_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"[Feature #213] Creating pre-destructive backup in: {backup_path}")

        # Import and use the existing backup utility
        from utils.backup import (
            _export_documents,
            _export_document_rows,
            _export_collections,
            _export_embeddings,
            _copy_uploads,
            _serialize_datetime
        )
        from core.database import engine, init_db_sync
        from sqlalchemy.orm import Session

        # Initialize database
        init_db_sync()

        with Session(engine) as session:
            # Export database tables to JSON
            logger.info("[Feature #213] Exporting database tables...")

            # Documents
            documents = _export_documents(session)
            docs_file = backup_path / "documents.json"
            with open(docs_file, 'w', encoding='utf-8') as f:
                json.dump(documents, f, default=_serialize_datetime, indent=2)
            logger.info(f"[Feature #213]   - Exported {len(documents)} documents")

            # Document rows
            rows = _export_document_rows(session)
            rows_file = backup_path / "document_rows.json"
            with open(rows_file, 'w', encoding='utf-8') as f:
                json.dump(rows, f, default=_serialize_datetime, indent=2)
            logger.info(f"[Feature #213]   - Exported {len(rows)} document rows")

            # Collections
            collections = _export_collections(session)
            cols_file = backup_path / "collections.json"
            with open(cols_file, 'w', encoding='utf-8') as f:
                json.dump(collections, f, default=_serialize_datetime, indent=2)
            logger.info(f"[Feature #213]   - Exported {len(collections)} collections")

            # Embeddings (metadata only)
            embeddings = _export_embeddings(session)
            emb_file = backup_path / "embeddings_metadata.json"
            with open(emb_file, 'w', encoding='utf-8') as f:
                json.dump(embeddings, f, default=_serialize_datetime, indent=2)
            logger.info(f"[Feature #213]   - Exported {len(embeddings)} embedding metadata records")

        # Copy uploaded files
        logger.info("[Feature #213] Copying uploaded files...")
        file_stats = _copy_uploads(backup_path)
        logger.info(f"[Feature #213]   - Copied {file_stats['files_copied']} files ({file_stats['total_bytes']:,} bytes)")

        # Save backup metadata with operation info
        metadata = {
            'timestamp': timestamp,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'reason': f"Pre-destructive backup before: {operation}",
            'operation': operation,
            'operation_details': details,
            'documents_count': len(documents),
            'rows_count': len(rows),
            'collections_count': len(collections),
            'embeddings_count': len(embeddings),
            'files_count': file_stats['files_copied'],
            'total_file_bytes': file_stats['total_bytes'],
            'failed_files': file_stats['failed_files'],
            'is_pre_destructive': True,
        }

        metadata_file = backup_path / "backup_metadata.json"
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"[Feature #213] ============================================")
        logger.info(f"[Feature #213] PRE-DESTRUCTIVE BACKUP COMPLETE")
        logger.info(f"[Feature #213] Operation: {operation}")
        logger.info(f"[Feature #213] Path: {backup_path}")
        logger.info(f"[Feature #213] Documents: {len(documents)}, Collections: {len(collections)}")
        logger.info(f"[Feature #213] ============================================")

        # Feature #222: Cleanup old backups, keeping only the last 5
        cleanup_result = cleanup_old_backups(MAX_PRE_DELETE_BACKUPS)
        if cleanup_result['deleted'] > 0:
            logger.info(f"[Feature #222] Cleaned up {cleanup_result['deleted']} old backups")

        return {
            'success': True,
            'backup_path': str(backup_path),
            'error': None,
            'skipped': False,
            'metadata': metadata,
            'cleanup': cleanup_result  # Feature #222: Include cleanup info
        }

    except Exception as e:
        error_msg = f"Pre-destructive backup failed: {str(e)}"
        logger.error(f"[Feature #213] {error_msg}")

        return {
            'success': False,
            'backup_path': None,
            'error': error_msg,
            'skipped': False
        }


def list_pre_destructive_backups() -> list:
    """
    List all pre-destructive backups.

    Returns:
        List of backup metadata dicts sorted by timestamp (newest first)
    """
    backups = []

    if not PRE_DELETE_BACKUPS_DIR.exists():
        return backups

    for backup_dir in sorted(PRE_DELETE_BACKUPS_DIR.iterdir(), reverse=True):
        if not backup_dir.is_dir():
            continue

        metadata_file = backup_dir / "backup_metadata.json"
        if metadata_file.exists():
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                metadata['path'] = str(backup_dir)
                backups.append(metadata)
            except Exception as e:
                logger.warning(f"Could not read metadata for {backup_dir.name}: {e}")
                backups.append({
                    'timestamp': backup_dir.name,
                    'path': str(backup_dir),
                    'error': str(e)
                })
        else:
            backups.append({
                'timestamp': backup_dir.name,
                'path': str(backup_dir),
                'metadata_missing': True
            })

    return backups


def cleanup_old_backups(max_backups: int = MAX_PRE_DELETE_BACKUPS) -> Dict[str, Any]:
    """
    Feature #222: Remove old backups, keeping only the most recent ones.

    Args:
        max_backups: Maximum number of backups to keep (default: 5)

    Returns:
        Dict with cleanup results:
            - success: bool
            - kept: int - number of backups kept
            - deleted: int - number of backups deleted
            - deleted_paths: list - paths of deleted backups
    """
    logger.info(f"[Feature #222] Running backup cleanup, keeping last {max_backups} backups")

    if not PRE_DELETE_BACKUPS_DIR.exists():
        return {
            'success': True,
            'kept': 0,
            'deleted': 0,
            'deleted_paths': []
        }

    # Get all backup directories sorted by name (timestamp-based, newest first)
    backup_dirs = sorted(
        [d for d in PRE_DELETE_BACKUPS_DIR.iterdir() if d.is_dir()],
        reverse=True  # Newest first (lexicographic sort works for YYYY-MM-DD format)
    )

    deleted_paths = []

    # Keep the first max_backups, delete the rest
    for backup_dir in backup_dirs[max_backups:]:
        try:
            shutil.rmtree(backup_dir)
            deleted_paths.append(str(backup_dir))
            logger.info(f"[Feature #222] Deleted old backup: {backup_dir.name}")
        except Exception as e:
            logger.error(f"[Feature #222] Failed to delete backup {backup_dir.name}: {e}")

    result = {
        'success': True,
        'kept': min(len(backup_dirs), max_backups),
        'deleted': len(deleted_paths),
        'deleted_paths': deleted_paths
    }

    logger.info(f"[Feature #222] Cleanup complete: kept {result['kept']}, deleted {result['deleted']}")
    return result


async def restore_from_pre_destructive_backup(backup_path: str) -> Dict[str, Any]:
    """
    Feature #222: Restore data from a pre-destructive backup (Undo operation).

    This restores documents, collections, and files from a pre-destructive backup.
    Note: This does NOT restore embeddings - they need to be regenerated.

    Args:
        backup_path: Path to the backup directory

    Returns:
        Dict with restore results:
            - success: bool
            - message: str
            - documents_restored: int
            - collections_restored: int
            - files_restored: int
            - error: str (if failed)
    """
    logger.info(f"[Feature #222] Starting restore from backup: {backup_path}")

    backup_dir = Path(backup_path)

    if not backup_dir.exists():
        return {
            'success': False,
            'error': f"Backup directory not found: {backup_path}",
            'documents_restored': 0,
            'collections_restored': 0,
            'files_restored': 0
        }

    try:
        from core.database import SessionLocal
        from models.db_models import DBDocument, DBCollection, DBDocumentRow
        from sqlalchemy import text

        documents_restored = 0
        collections_restored = 0
        files_restored = 0

        db = SessionLocal()

        try:
            # 1. Restore collections first (documents reference them)
            collections_file = backup_dir / "collections.json"
            if collections_file.exists():
                with open(collections_file, 'r', encoding='utf-8') as f:
                    collections_data = json.load(f)

                for col in collections_data:
                    # Check if collection already exists
                    existing = db.query(DBCollection).filter(DBCollection.id == col['id']).first()
                    if not existing:
                        db.execute(
                            text("""
                                INSERT INTO collections (id, name, description, created_at, updated_at)
                                VALUES (:id, :name, :description, :created_at, :updated_at)
                                ON CONFLICT (id) DO NOTHING
                            """),
                            {
                                'id': col['id'],
                                'name': col['name'],
                                'description': col.get('description'),
                                'created_at': col.get('created_at'),
                                'updated_at': col.get('updated_at')
                            }
                        )
                        collections_restored += 1

                logger.info(f"[Feature #222] Restored {collections_restored} collections")

            # 2. Restore documents
            documents_file = backup_dir / "documents.json"
            if documents_file.exists():
                with open(documents_file, 'r', encoding='utf-8') as f:
                    documents_data = json.load(f)

                for doc in documents_data:
                    # Check if document already exists
                    existing = db.query(DBDocument).filter(DBDocument.id == doc['id']).first()
                    if not existing:
                        db.execute(
                            text("""
                                INSERT INTO documents (id, title, comment, original_filename, mime_type,
                                                     file_size, document_type, collection_id, content_hash,
                                                     schema_info, created_at, updated_at)
                                VALUES (:id, :title, :comment, :original_filename, :mime_type,
                                       :file_size, :document_type, :collection_id, :content_hash,
                                       :schema_info, :created_at, :updated_at)
                                ON CONFLICT (id) DO NOTHING
                            """),
                            {
                                'id': doc['id'],
                                'title': doc['title'],
                                'comment': doc.get('comment'),
                                'original_filename': doc['original_filename'],
                                'mime_type': doc['mime_type'],
                                'file_size': doc['file_size'],
                                'document_type': doc.get('document_type', 'unstructured'),
                                'collection_id': doc.get('collection_id'),
                                'content_hash': doc.get('content_hash'),
                                'schema_info': json.dumps(doc.get('schema_info')) if doc.get('schema_info') else None,
                                'created_at': doc.get('created_at'),
                                'updated_at': doc.get('updated_at')
                            }
                        )
                        documents_restored += 1

                logger.info(f"[Feature #222] Restored {documents_restored} documents")

            # 3. Restore document rows (for structured data)
            rows_file = backup_dir / "document_rows.json"
            if rows_file.exists():
                with open(rows_file, 'r', encoding='utf-8') as f:
                    rows_data = json.load(f)

                rows_restored = 0
                for row in rows_data:
                    # Handle both old format (document_id, row_number, data) and
                    # new format (dataset_id, row_data)
                    dataset_id = row.get('dataset_id') or row.get('document_id')
                    row_data = row.get('row_data') or row.get('data')

                    db.execute(
                        text("""
                            INSERT INTO document_rows (id, dataset_id, row_data, created_at)
                            VALUES (:id, :dataset_id, :row_data, :created_at)
                            ON CONFLICT (id) DO NOTHING
                        """),
                        {
                            'id': row['id'],
                            'dataset_id': dataset_id,
                            'row_data': json.dumps(row_data) if isinstance(row_data, dict) else row_data,
                            'created_at': row.get('created_at')
                        }
                    )
                    rows_restored += 1

                logger.info(f"[Feature #222] Restored {rows_restored} document rows")

            db.commit()

            # 4. Restore uploaded files
            uploads_backup = backup_dir / "uploads"
            if uploads_backup.exists():
                uploads_dir = BACKEND_DIR / "uploads"
                uploads_dir.mkdir(parents=True, exist_ok=True)

                for file_path in uploads_backup.iterdir():
                    if file_path.is_file():
                        dest_path = uploads_dir / file_path.name
                        if not dest_path.exists():
                            shutil.copy2(file_path, dest_path)
                            files_restored += 1

                logger.info(f"[Feature #222] Restored {files_restored} files")

            result = {
                'success': True,
                'message': f"Restored {documents_restored} documents, {collections_restored} collections, {files_restored} files",
                'documents_restored': documents_restored,
                'collections_restored': collections_restored,
                'files_restored': files_restored,
                'note': 'Embeddings need to be regenerated for restored documents'
            }

            logger.info(f"[Feature #222] ============================================")
            logger.info(f"[Feature #222] RESTORE COMPLETE")
            logger.info(f"[Feature #222] Documents: {documents_restored}, Collections: {collections_restored}, Files: {files_restored}")
            logger.info(f"[Feature #222] ============================================")

            return result

        except Exception as e:
            db.rollback()
            raise e
        finally:
            db.close()

    except Exception as e:
        error_msg = f"Restore failed: {str(e)}"
        logger.error(f"[Feature #222] {error_msg}")
        return {
            'success': False,
            'error': error_msg,
            'documents_restored': 0,
            'collections_restored': 0,
            'files_restored': 0
        }
