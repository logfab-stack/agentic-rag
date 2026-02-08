"""
Auto Backup Service for Agentic RAG System (Feature #212)

Provides automatic daily backup scheduling with configurable retention.

Features:
- Automatic daily backups at configurable time (default 02:00)
- Configurable retention period (default 7 days)
- Backup manifest with metadata
- API endpoints for status and manual trigger
- Logging and notification on failure

Usage:
    from services.auto_backup_service import auto_backup_service

    # Start the scheduler
    auto_backup_service.start()

    # Get status
    status = auto_backup_service.get_status()

    # Trigger manual backup
    result = auto_backup_service.trigger_backup()

    # Stop the scheduler
    auto_backup_service.stop()
"""

import os
import sys
import json
import shutil
import logging
import threading
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

logger = logging.getLogger(__name__)

# Configuration
AUTO_BACKUPS_DIR = backend_dir / "backups" / "auto"
UPLOADS_DIR = backend_dir / "uploads"


class AutoBackupService:
    """
    Service for automatic daily backups.

    Creates timestamped backups in /backend/backups/auto/ folder.
    Automatically rotates old backups based on retention period.
    """

    def __init__(self):
        self._scheduler_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._is_running = False
        self._last_backup_time: Optional[datetime] = None
        self._last_backup_result: Optional[Dict[str, Any]] = None
        self._next_scheduled_time: Optional[datetime] = None
        self._backup_lock = threading.Lock()

    def _get_settings(self) -> Dict[str, Any]:
        """Get backup settings from settings store."""
        try:
            from core.store import settings_store
            return {
                'enable_auto_backup': settings_store.get('enable_auto_backup', 'false').lower() == 'true',
                'backup_time': settings_store.get('backup_time', '02:00'),
                'backup_retention_days': int(settings_store.get('backup_retention_days', '7'))
            }
        except Exception as e:
            logger.warning(f"Could not load backup settings: {e}")
            return {
                'enable_auto_backup': False,
                'backup_time': '02:00',
                'backup_retention_days': 7
            }

    def _parse_backup_time(self, time_str: str) -> tuple:
        """Parse backup time string (HH:MM) to hour and minute."""
        try:
            parts = time_str.split(':')
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
            return (max(0, min(23, hour)), max(0, min(59, minute)))
        except (ValueError, IndexError):
            return (2, 0)  # Default to 02:00

    def _calculate_next_backup_time(self) -> datetime:
        """Calculate the next scheduled backup time."""
        settings = self._get_settings()
        hour, minute = self._parse_backup_time(settings['backup_time'])

        now = datetime.now()
        next_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # If the scheduled time has already passed today, schedule for tomorrow
        if next_time <= now:
            next_time += timedelta(days=1)

        return next_time

    def _ensure_auto_backups_dir(self):
        """Ensure the auto backups directory exists."""
        AUTO_BACKUPS_DIR.mkdir(parents=True, exist_ok=True)

    def _get_backup_timestamp(self) -> str:
        """Generate timestamp string for backup folder name."""
        return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    def _serialize_datetime(self, obj):
        """JSON serializer for datetime objects."""
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    def _export_documents(self, session) -> List[Dict[str, Any]]:
        """Export all documents from database to list of dicts."""
        from sqlalchemy import select
        from models.db_models import DBDocument

        stmt = select(DBDocument)
        result = session.execute(stmt)
        documents = result.scalars().all()

        exported = []
        for doc in documents:
            exported.append({
                'id': doc.id,
                'title': doc.title,
                'comment': doc.comment,
                'original_filename': doc.original_filename,
                'mime_type': doc.mime_type,
                'file_size': doc.file_size,
                'document_type': doc.document_type,
                'collection_id': doc.collection_id,
                'content_hash': doc.content_hash,
                'schema_info': doc.schema_info,
                'url': doc.url,
                'created_at': doc.created_at,
                'updated_at': doc.updated_at,
            })

        return exported

    def _export_document_rows(self, session) -> List[Dict[str, Any]]:
        """Export all document rows from database to list of dicts."""
        from sqlalchemy import select
        from models.db_models import DBDocumentRow

        stmt = select(DBDocumentRow)
        result = session.execute(stmt)
        rows = result.scalars().all()

        exported = []
        for row in rows:
            exported.append({
                'id': row.id,
                'dataset_id': row.dataset_id,
                'row_data': row.row_data,
                'created_at': row.created_at,
            })

        return exported

    def _export_collections(self, session) -> List[Dict[str, Any]]:
        """Export all collections from database to list of dicts."""
        from sqlalchemy import select
        from models.db_models import DBCollection

        stmt = select(DBCollection)
        result = session.execute(stmt)
        collections = result.scalars().all()

        exported = []
        for col in collections:
            exported.append({
                'id': col.id,
                'name': col.name,
                'description': col.description,
                'created_at': col.created_at,
                'updated_at': col.updated_at,
            })

        return exported

    def _export_embeddings_metadata(self, session) -> List[Dict[str, Any]]:
        """Export document embeddings metadata (without vectors for space efficiency)."""
        try:
            from sqlalchemy import text

            # Query the langchain_pg_embedding table
            result = session.execute(text("""
                SELECT id, document, cmetadata
                FROM langchain_pg_embedding
            """))
            rows = result.fetchall()

            exported = []
            for row in rows:
                exported.append({
                    'id': row.id,
                    'document': row.document,
                    'metadata': row.cmetadata,
                    # Note: embedding vector not included - too large, will be regenerated
                })

            return exported
        except Exception as e:
            logger.warning(f"Could not export embeddings (pgvector may not be available): {e}")
            return []

    def _copy_uploads(self, backup_path: Path) -> Dict[str, Any]:
        """Copy all files from uploads directory to backup folder."""
        uploads_backup = backup_path / "uploads"
        uploads_backup.mkdir(parents=True, exist_ok=True)

        stats = {
            'files_copied': 0,
            'total_bytes': 0,
            'failed_files': []
        }

        if not UPLOADS_DIR.exists():
            logger.info("Uploads directory does not exist, nothing to backup")
            return stats

        for file_path in UPLOADS_DIR.iterdir():
            if file_path.is_file():
                try:
                    dest = uploads_backup / file_path.name
                    shutil.copy2(file_path, dest)
                    stats['files_copied'] += 1
                    stats['total_bytes'] += file_path.stat().st_size
                except Exception as e:
                    logger.error(f"Failed to copy {file_path.name}: {e}")
                    stats['failed_files'].append(str(file_path.name))

        return stats

    def _cleanup_old_backups(self, retention_days: int):
        """Remove backups older than retention period."""
        if not AUTO_BACKUPS_DIR.exists():
            return

        cutoff_date = datetime.now() - timedelta(days=retention_days)
        deleted_count = 0

        for backup_dir in AUTO_BACKUPS_DIR.iterdir():
            if not backup_dir.is_dir():
                continue

            # Parse timestamp from folder name (YYYY-MM-DD_HH-MM-SS)
            try:
                folder_name = backup_dir.name
                backup_date = datetime.strptime(folder_name, "%Y-%m-%d_%H-%M-%S")

                if backup_date < cutoff_date:
                    shutil.rmtree(backup_dir)
                    deleted_count += 1
                    logger.info(f"Deleted old auto-backup: {folder_name}")
            except ValueError:
                # Skip folders that don't match the expected format
                continue
            except Exception as e:
                logger.error(f"Failed to delete old backup {backup_dir.name}: {e}")

        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old auto-backup(s)")

    def create_backup(self, reason: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a full automatic backup.

        Returns:
            Dictionary with backup result including path, timestamp, and statistics
        """
        from sqlalchemy.orm import Session
        from core.database import engine, init_db_sync

        with self._backup_lock:
            timestamp = self._get_backup_timestamp()
            backup_path = AUTO_BACKUPS_DIR / timestamp

            logger.info("=" * 80)
            logger.info("AUTOMATIC BACKUP - Feature #212")
            logger.info("=" * 80)

            if reason:
                logger.info(f"Reason: {reason}")

            result = {
                'success': False,
                'timestamp': timestamp,
                'path': str(backup_path),
                'reason': reason,
                'documents_count': 0,
                'rows_count': 0,
                'collections_count': 0,
                'embeddings_count': 0,
                'files_count': 0,
                'total_file_bytes': 0,
                'error': None,
                'created_at': datetime.now(timezone.utc).isoformat()
            }

            try:
                # Initialize database
                init_db_sync()

                # Create backup directory
                self._ensure_auto_backups_dir()
                backup_path.mkdir(parents=True, exist_ok=True)

                logger.info(f"Creating auto-backup in: {backup_path}")

                with Session(engine) as session:
                    # Export database tables to JSON
                    logger.info("Exporting database tables...")

                    # Documents
                    documents = self._export_documents(session)
                    docs_file = backup_path / "documents.json"
                    with open(docs_file, 'w', encoding='utf-8') as f:
                        json.dump(documents, f, default=self._serialize_datetime, indent=2)
                    result['documents_count'] = len(documents)
                    logger.info(f"  - Exported {len(documents)} documents")

                    # Document rows
                    rows = self._export_document_rows(session)
                    rows_file = backup_path / "document_rows.json"
                    with open(rows_file, 'w', encoding='utf-8') as f:
                        json.dump(rows, f, default=self._serialize_datetime, indent=2)
                    result['rows_count'] = len(rows)
                    logger.info(f"  - Exported {len(rows)} document rows")

                    # Collections
                    collections = self._export_collections(session)
                    cols_file = backup_path / "collections.json"
                    with open(cols_file, 'w', encoding='utf-8') as f:
                        json.dump(collections, f, default=self._serialize_datetime, indent=2)
                    result['collections_count'] = len(collections)
                    logger.info(f"  - Exported {len(collections)} collections")

                    # Embeddings (metadata only)
                    embeddings = self._export_embeddings_metadata(session)
                    emb_file = backup_path / "embeddings_metadata.json"
                    with open(emb_file, 'w', encoding='utf-8') as f:
                        json.dump(embeddings, f, default=self._serialize_datetime, indent=2)
                    result['embeddings_count'] = len(embeddings)
                    logger.info(f"  - Exported {len(embeddings)} embedding metadata records")

                # Copy uploaded files
                logger.info("Copying uploaded files...")
                file_stats = self._copy_uploads(backup_path)
                result['files_count'] = file_stats['files_copied']
                result['total_file_bytes'] = file_stats['total_bytes']
                logger.info(f"  - Copied {file_stats['files_copied']} files ({file_stats['total_bytes']:,} bytes)")

                if file_stats['failed_files']:
                    logger.warning(f"  - Failed to copy: {file_stats['failed_files']}")
                    result['failed_files'] = file_stats['failed_files']

                # Save backup manifest (backup_metadata.json)
                manifest = {
                    'version': '1.0',
                    'type': 'automatic',
                    'timestamp': timestamp,
                    'created_at': result['created_at'],
                    'reason': reason,
                    'documents_count': result['documents_count'],
                    'rows_count': result['rows_count'],
                    'collections_count': result['collections_count'],
                    'embeddings_count': result['embeddings_count'],
                    'files_count': result['files_count'],
                    'total_file_bytes': result['total_file_bytes'],
                    'failed_files': file_stats.get('failed_files', []),
                }

                manifest_file = backup_path / "backup_metadata.json"
                with open(manifest_file, 'w', encoding='utf-8') as f:
                    json.dump(manifest, f, indent=2)

                # Cleanup old backups
                settings = self._get_settings()
                logger.info(f"Cleaning up backups older than {settings['backup_retention_days']} days...")
                self._cleanup_old_backups(settings['backup_retention_days'])

                result['success'] = True
                self._last_backup_time = datetime.now(timezone.utc)
                self._last_backup_result = result

                logger.info("=" * 80)
                logger.info(f"AUTO-BACKUP COMPLETE: {backup_path}")
                logger.info("=" * 80)

            except Exception as e:
                error_msg = str(e)
                logger.error(f"Auto-backup creation failed: {error_msg}")
                result['error'] = error_msg
                result['success'] = False
                self._last_backup_result = result

                # Try to clean up partial backup
                if backup_path.exists():
                    try:
                        shutil.rmtree(backup_path)
                    except Exception:
                        pass

                # Log failure notification
                self._notify_backup_failure(error_msg)

            return result

    def _notify_backup_failure(self, error: str):
        """Log backup failure notification."""
        logger.error("=" * 80)
        logger.error("⚠️  AUTO-BACKUP FAILED")
        logger.error(f"Error: {error}")
        logger.error("Please check the logs and verify backup settings.")
        logger.error("=" * 80)

        # TODO: If webhook URL is configured, send notification
        # This could be extended to support email, Slack, etc.

    def _scheduler_loop(self):
        """Main scheduler loop that runs in a background thread."""
        logger.info("Auto-backup scheduler started")

        while not self._stop_event.is_set():
            settings = self._get_settings()

            if not settings['enable_auto_backup']:
                # Auto-backup is disabled, wait and check again
                self._next_scheduled_time = None
                self._stop_event.wait(60)  # Check every minute
                continue

            # Calculate next backup time
            next_time = self._calculate_next_backup_time()
            self._next_scheduled_time = next_time

            # Calculate wait time in seconds
            now = datetime.now()
            wait_seconds = (next_time - now).total_seconds()

            if wait_seconds > 0:
                logger.info(f"Next auto-backup scheduled for: {next_time.strftime('%Y-%m-%d %H:%M:%S')}")

                # Wait until scheduled time or stop event
                if self._stop_event.wait(min(wait_seconds, 60)):
                    # Stop event was set
                    break

                # If we woke up early, continue loop to recalculate
                if datetime.now() < next_time:
                    continue

            # Time to run backup
            if settings['enable_auto_backup']:
                logger.info("Starting scheduled auto-backup...")
                try:
                    self.create_backup(reason="Scheduled daily auto-backup")
                except Exception as e:
                    logger.error(f"Scheduled backup failed: {e}")

            # After backup, wait a bit before calculating next time
            self._stop_event.wait(60)

    def start(self):
        """Start the background scheduler."""
        if self._is_running:
            logger.warning("Auto-backup scheduler is already running")
            return

        self._stop_event.clear()
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            name="auto-backup-scheduler",
            daemon=True
        )
        self._scheduler_thread.start()
        self._is_running = True
        logger.info("Auto-backup scheduler started")

    def stop(self):
        """Stop the background scheduler."""
        if not self._is_running:
            return

        self._stop_event.set()
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=5)
        self._is_running = False
        self._next_scheduled_time = None
        logger.info("Auto-backup scheduler stopped")

    def trigger_backup(self, reason: Optional[str] = None) -> Dict[str, Any]:
        """
        Manually trigger an immediate backup.

        Args:
            reason: Optional description of why backup is being triggered

        Returns:
            Backup result dictionary
        """
        return self.create_backup(reason=reason or "Manual trigger via API")

    def get_status(self) -> Dict[str, Any]:
        """
        Get current backup scheduler status.

        Returns:
            Status dictionary with scheduler state and backup info
        """
        settings = self._get_settings()

        # List existing auto-backups
        existing_backups = []
        if AUTO_BACKUPS_DIR.exists():
            for backup_dir in sorted(AUTO_BACKUPS_DIR.iterdir(), reverse=True):
                if backup_dir.is_dir():
                    manifest_file = backup_dir / "backup_metadata.json"
                    if manifest_file.exists():
                        try:
                            with open(manifest_file, 'r') as f:
                                manifest = json.load(f)
                            manifest['path'] = str(backup_dir)
                            existing_backups.append(manifest)
                        except Exception:
                            existing_backups.append({
                                'timestamp': backup_dir.name,
                                'path': str(backup_dir),
                                'error': 'Could not read manifest'
                            })

        return {
            'scheduler_running': self._is_running,
            'auto_backup_enabled': settings['enable_auto_backup'],
            'backup_time': settings['backup_time'],
            'backup_retention_days': settings['backup_retention_days'],
            'last_backup_time': self._last_backup_time.isoformat() if self._last_backup_time else None,
            'last_backup_result': self._last_backup_result,
            'next_scheduled_time': self._next_scheduled_time.strftime('%Y-%m-%d %H:%M:%S') if self._next_scheduled_time else None,
            'existing_backups': existing_backups,
            'backup_count': len(existing_backups)
        }

    def list_backups(self) -> List[Dict[str, Any]]:
        """
        List all automatic backups.

        Returns:
            List of backup metadata dictionaries
        """
        backups = []

        if not AUTO_BACKUPS_DIR.exists():
            return backups

        for backup_dir in sorted(AUTO_BACKUPS_DIR.iterdir(), reverse=True):
            if not backup_dir.is_dir():
                continue

            manifest_file = backup_dir / "backup_metadata.json"
            if manifest_file.exists():
                try:
                    with open(manifest_file, 'r', encoding='utf-8') as f:
                        manifest = json.load(f)
                    manifest['path'] = str(backup_dir)
                    backups.append(manifest)
                except Exception as e:
                    logger.warning(f"Could not read manifest for {backup_dir.name}: {e}")
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


# Global singleton instance
auto_backup_service = AutoBackupService()
