"""
Automatic Backup Scheduler Service (Feature #221)

Implements scheduled automatic backups with:
- Daily backups at configurable time (default 2:00 AM)
- pg_dump for complete database backup
- File backup for uploaded documents
- Rotation policy: 7 daily + 4 weekly backups
- Status tracking and configuration via settings

Usage:
    from services.backup_scheduler import BackupScheduler

    scheduler = BackupScheduler()
    scheduler.start()  # Start the scheduler
    scheduler.stop()   # Stop the scheduler
"""

import os
import sys
import json
import shutil
import subprocess
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from threading import Lock

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

logger = logging.getLogger(__name__)

# Feature #322: Import centralized configuration
from core.config import settings

# Configuration - now uses centralized settings where possible
BACKUPS_DIR = settings.backups_path
UPLOADS_DIR = settings.upload_path
DEFAULT_BACKUP_HOUR = 2  # 2:00 AM
DEFAULT_BACKUP_MINUTE = 0
DAILY_RETENTION = settings.BACKUP_RETENTION_DAYS  # Keep daily backups
WEEKLY_RETENTION = settings.WEEKLY_BACKUP_RETENTION  # Keep weekly backups (on Sundays)

# Database connection settings from centralized config
DATABASE_URL = settings.DATABASE_SYNC_URL


def _parse_database_url(url: str) -> Dict[str, str]:
    """Parse DATABASE_URL into components for pg_dump."""
    # Format: postgresql://user:password@host:port/database
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return {
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 5432),
        "user": parsed.username or "postgres",
        "password": parsed.password or "",
        "database": parsed.path.lstrip("/") or "agentic_rag",
    }


class BackupScheduler:
    """
    Manages automatic scheduled backups with rotation policy.

    Features:
    - Configurable backup time (hour, minute)
    - pg_dump for database backup
    - File copy for uploads
    - 7 daily + 4 weekly backup rotation
    - Status tracking
    """

    _instance: Optional['BackupScheduler'] = None
    _lock = Lock()

    def __new__(cls):
        """Singleton pattern to ensure only one scheduler instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._scheduler = BackgroundScheduler(timezone="UTC")
        self._job_id = "automatic_backup"
        self._enabled = False
        self._backup_hour = DEFAULT_BACKUP_HOUR
        self._backup_minute = DEFAULT_BACKUP_MINUTE
        self._last_backup_time: Optional[datetime] = None
        self._last_backup_status: str = "never"
        self._last_backup_error: Optional[str] = None
        self._next_backup_time: Optional[datetime] = None
        self._backup_in_progress = False

        # Add event listeners
        self._scheduler.add_listener(
            self._on_job_executed,
            EVENT_JOB_EXECUTED
        )
        self._scheduler.add_listener(
            self._on_job_error,
            EVENT_JOB_ERROR
        )

        # Load settings from store
        self._load_settings()

        self._initialized = True
        logger.info("BackupScheduler initialized")

    def _load_settings(self):
        """Load backup settings from settings store."""
        try:
            from core.store import settings_store
            self._enabled = settings_store.get("auto_backup_enabled", False)
            self._backup_hour = settings_store.get("auto_backup_hour", DEFAULT_BACKUP_HOUR)
            self._backup_minute = settings_store.get("auto_backup_minute", DEFAULT_BACKUP_MINUTE)

            # Load last backup info
            last_backup_str = settings_store.get("auto_backup_last_time")
            if last_backup_str:
                try:
                    self._last_backup_time = datetime.fromisoformat(last_backup_str)
                except (ValueError, TypeError):
                    pass

            self._last_backup_status = settings_store.get("auto_backup_last_status", "never")
            self._last_backup_error = settings_store.get("auto_backup_last_error")

            logger.info(f"Backup settings loaded: enabled={self._enabled}, hour={self._backup_hour}, minute={self._backup_minute}")
        except Exception as e:
            logger.error(f"Failed to load backup settings: {e}")

    def _save_settings(self):
        """Save backup settings to settings store."""
        try:
            from core.store import settings_store
            settings_store.set("auto_backup_enabled", self._enabled)
            settings_store.set("auto_backup_hour", self._backup_hour)
            settings_store.set("auto_backup_minute", self._backup_minute)

            if self._last_backup_time:
                settings_store.set("auto_backup_last_time", self._last_backup_time.isoformat())

            settings_store.set("auto_backup_last_status", self._last_backup_status)
            settings_store.set("auto_backup_last_error", self._last_backup_error)
        except Exception as e:
            logger.error(f"Failed to save backup settings: {e}")

    def _on_job_executed(self, event):
        """Handle successful job execution."""
        if event.job_id == self._job_id:
            self._last_backup_time = datetime.now(timezone.utc)
            self._last_backup_status = "success"
            self._last_backup_error = None
            self._update_next_backup_time()
            self._save_settings()
            logger.info("Automatic backup completed successfully")

    def _on_job_error(self, event):
        """Handle job execution error."""
        if event.job_id == self._job_id:
            self._last_backup_time = datetime.now(timezone.utc)
            self._last_backup_status = "failed"
            self._last_backup_error = str(event.exception) if event.exception else "Unknown error"
            self._update_next_backup_time()
            self._save_settings()
            logger.error(f"Automatic backup failed: {self._last_backup_error}")

    def _update_next_backup_time(self):
        """Update the next scheduled backup time."""
        job = self._scheduler.get_job(self._job_id)
        if job:
            self._next_backup_time = job.next_run_time
        else:
            self._next_backup_time = None

    def start(self):
        """Start the scheduler."""
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("BackupScheduler started")

        if self._enabled:
            self._schedule_backup()

    def stop(self):
        """Stop the scheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("BackupScheduler stopped")

    def _schedule_backup(self):
        """Schedule the backup job."""
        # Remove existing job if any
        if self._scheduler.get_job(self._job_id):
            self._scheduler.remove_job(self._job_id)

        # Add new job with configured time
        trigger = CronTrigger(
            hour=self._backup_hour,
            minute=self._backup_minute,
            timezone="UTC"
        )

        self._scheduler.add_job(
            self._run_backup,
            trigger=trigger,
            id=self._job_id,
            name="Automatic Daily Backup",
            replace_existing=True
        )

        self._update_next_backup_time()
        logger.info(f"Backup scheduled at {self._backup_hour:02d}:{self._backup_minute:02d} UTC")

    def enable(self, hour: int = None, minute: int = None):
        """Enable automatic backups."""
        if hour is not None:
            self._backup_hour = max(0, min(23, hour))
        if minute is not None:
            self._backup_minute = max(0, min(59, minute))

        self._enabled = True
        self._save_settings()

        if self._scheduler.running:
            self._schedule_backup()

        logger.info(f"Automatic backups enabled at {self._backup_hour:02d}:{self._backup_minute:02d} UTC")

    def disable(self):
        """Disable automatic backups."""
        self._enabled = False
        self._save_settings()

        # Remove scheduled job
        if self._scheduler.get_job(self._job_id):
            self._scheduler.remove_job(self._job_id)
            self._next_backup_time = None

        logger.info("Automatic backups disabled")

    def get_status(self) -> Dict[str, Any]:
        """Get current backup scheduler status."""
        return {
            "enabled": self._enabled,
            "backup_hour": self._backup_hour,
            "backup_minute": self._backup_minute,
            "backup_time_formatted": f"{self._backup_hour:02d}:{self._backup_minute:02d} UTC",
            "last_backup_time": self._last_backup_time.isoformat() if self._last_backup_time else None,
            "last_backup_status": self._last_backup_status,
            "last_backup_error": self._last_backup_error,
            "next_backup_time": self._next_backup_time.isoformat() if self._next_backup_time else None,
            "backup_in_progress": self._backup_in_progress,
            "daily_retention": DAILY_RETENTION,
            "weekly_retention": WEEKLY_RETENTION,
            "backups_dir": str(BACKUPS_DIR),
        }

    def run_now(self) -> Dict[str, Any]:
        """Run a backup immediately (manual trigger)."""
        if self._backup_in_progress:
            return {
                "success": False,
                "error": "A backup is already in progress"
            }

        try:
            result = self._run_backup()
            return {
                "success": True,
                "backup_path": result.get("backup_path"),
                "message": "Backup completed successfully"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def _run_backup(self) -> Dict[str, Any]:
        """
        Execute the backup operation.

        Creates a timestamped backup folder containing:
        - database.sql: pg_dump of the entire database
        - uploads/: Copy of all uploaded files
        - metadata.json: Backup information

        Returns:
            Dict with backup results
        """
        self._backup_in_progress = True
        backup_path = None

        try:
            # Create backup directory
            BACKUPS_DIR.mkdir(parents=True, exist_ok=True)

            # Generate timestamp for this backup
            now = datetime.now(timezone.utc)
            timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
            is_sunday = now.weekday() == 6  # Sunday

            # Create backup folder
            backup_path = BACKUPS_DIR / timestamp
            backup_path.mkdir(parents=True, exist_ok=True)

            logger.info(f"Starting automatic backup: {backup_path}")

            # Step 1: Database backup using pg_dump
            db_backup_result = self._backup_database(backup_path)

            # Step 2: Backup uploaded files
            files_backup_result = self._backup_files(backup_path)

            # Step 3: Save backup metadata
            metadata = {
                "timestamp": timestamp,
                "created_at": now.isoformat(),
                "is_weekly": is_sunday,
                "database": db_backup_result,
                "files": files_backup_result,
            }

            metadata_file = backup_path / "backup_metadata.json"
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)

            # Step 4: Apply rotation policy
            self._apply_rotation()

            # Update status
            self._last_backup_time = now
            self._last_backup_status = "success"
            self._last_backup_error = None
            self._save_settings()

            logger.info(f"Automatic backup completed: {backup_path}")

            return {
                "success": True,
                "backup_path": str(backup_path),
                "metadata": metadata
            }

        except Exception as e:
            logger.error(f"Backup failed: {e}")
            self._last_backup_time = datetime.now(timezone.utc)
            self._last_backup_status = "failed"
            self._last_backup_error = str(e)
            self._save_settings()

            # Clean up partial backup
            if backup_path and backup_path.exists():
                try:
                    shutil.rmtree(backup_path)
                except Exception:
                    pass

            raise
        finally:
            self._backup_in_progress = False

    def _backup_database(self, backup_path: Path) -> Dict[str, Any]:
        """
        Backup database using pg_dump.

        Returns:
            Dict with database backup details
        """
        db_file = backup_path / "database.sql"

        try:
            # Parse database URL
            db_config = _parse_database_url(DATABASE_URL)

            # Set up environment for pg_dump (password via PGPASSWORD)
            env = os.environ.copy()
            if db_config["password"]:
                env["PGPASSWORD"] = db_config["password"]

            # Run pg_dump
            cmd = [
                "pg_dump",
                "-h", db_config["host"],
                "-p", db_config["port"],
                "-U", db_config["user"],
                "-d", db_config["database"],
                "-f", str(db_file),
                "--no-password",  # We use PGPASSWORD env var
                "--verbose",
            ]

            logger.info(f"Running pg_dump: {' '.join(cmd[:4])}...")

            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=600  # 10 minute timeout
            )

            if result.returncode != 0:
                raise RuntimeError(f"pg_dump failed: {result.stderr}")

            # Get file size
            file_size = db_file.stat().st_size if db_file.exists() else 0

            return {
                "success": True,
                "file": str(db_file),
                "size_bytes": file_size,
                "size_human": self._format_size(file_size),
            }

        except FileNotFoundError:
            # pg_dump not found - try alternative approach
            logger.warning("pg_dump not found, using application-level backup")
            return self._backup_database_app_level(backup_path)
        except subprocess.TimeoutExpired:
            raise RuntimeError("Database backup timed out after 10 minutes")
        except Exception as e:
            logger.error(f"Database backup failed: {e}")
            raise

    def _backup_database_app_level(self, backup_path: Path) -> Dict[str, Any]:
        """
        Fallback: Application-level database backup using SQLAlchemy.

        Used when pg_dump is not available.
        """
        from sqlalchemy import select, text
        from sqlalchemy.orm import Session
        from core.database import engine
        from models.db_models import DBDocument, DBDocumentRow, DBCollection

        data = {
            "documents": [],
            "document_rows": [],
            "collections": [],
            "conversations": [],
            "messages": [],
        }

        def serialize_datetime(obj):
            if hasattr(obj, 'isoformat'):
                return obj.isoformat()
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

        with Session(engine) as session:
            # Export documents
            stmt = select(DBDocument)
            result = session.execute(stmt)
            for doc in result.scalars().all():
                data["documents"].append({
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
                    'created_at': doc.created_at.isoformat() if doc.created_at else None,
                    'updated_at': doc.updated_at.isoformat() if doc.updated_at else None,
                })

            # Export document rows
            stmt = select(DBDocumentRow)
            result = session.execute(stmt)
            for row in result.scalars().all():
                data["document_rows"].append({
                    'id': row.id,
                    'dataset_id': row.dataset_id,
                    'row_data': row.row_data,
                    'created_at': row.created_at.isoformat() if row.created_at else None,
                })

            # Export collections
            stmt = select(DBCollection)
            result = session.execute(stmt)
            for col in result.scalars().all():
                data["collections"].append({
                    'id': col.id,
                    'name': col.name,
                    'description': col.description,
                    'created_at': col.created_at.isoformat() if col.created_at else None,
                    'updated_at': col.updated_at.isoformat() if col.updated_at else None,
                })

            # Export conversations
            try:
                result = session.execute(text("SELECT id, title, created_at, updated_at FROM conversations"))
                for row in result.fetchall():
                    data["conversations"].append({
                        'id': row[0],
                        'title': row[1],
                        'created_at': row[2].isoformat() if row[2] else None,
                        'updated_at': row[3].isoformat() if row[3] else None,
                    })
            except Exception as e:
                logger.warning(f"Could not export conversations: {e}")

            # Export messages
            try:
                result = session.execute(text("SELECT id, conversation_id, role, content, tool_used, tool_details, response_source, created_at FROM messages"))
                for row in result.fetchall():
                    data["messages"].append({
                        'id': row[0],
                        'conversation_id': row[1],
                        'role': row[2],
                        'content': row[3],
                        'tool_used': row[4],
                        'tool_details': row[5],
                        'response_source': row[6],
                        'created_at': row[7].isoformat() if row[7] else None,
                    })
            except Exception as e:
                logger.warning(f"Could not export messages: {e}")

        # Save to JSON file
        db_file = backup_path / "database.json"
        with open(db_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, default=serialize_datetime, indent=2)

        file_size = db_file.stat().st_size

        return {
            "success": True,
            "file": str(db_file),
            "format": "json",
            "size_bytes": file_size,
            "size_human": self._format_size(file_size),
            "note": "Application-level backup (pg_dump not available)"
        }

    def _backup_files(self, backup_path: Path) -> Dict[str, Any]:
        """
        Backup all uploaded files.

        Returns:
            Dict with file backup details
        """
        uploads_backup = backup_path / "uploads"
        uploads_backup.mkdir(parents=True, exist_ok=True)

        stats = {
            "success": True,
            "files_copied": 0,
            "total_bytes": 0,
            "failed_files": []
        }

        if not UPLOADS_DIR.exists():
            logger.info("Uploads directory does not exist, skipping file backup")
            return stats

        for file_path in UPLOADS_DIR.iterdir():
            if file_path.is_file():
                try:
                    dest = uploads_backup / file_path.name
                    shutil.copy2(file_path, dest)
                    stats["files_copied"] += 1
                    stats["total_bytes"] += file_path.stat().st_size
                except Exception as e:
                    logger.error(f"Failed to copy {file_path.name}: {e}")
                    stats["failed_files"].append(str(file_path.name))

        stats["size_human"] = self._format_size(stats["total_bytes"])

        return stats

    def _apply_rotation(self):
        """
        Apply backup rotation policy:
        - Keep last 7 daily backups
        - Keep last 4 weekly (Sunday) backups
        """
        if not BACKUPS_DIR.exists():
            return

        # Get all backup directories sorted by name (timestamp)
        backup_dirs = sorted([
            d for d in BACKUPS_DIR.iterdir()
            if d.is_dir() and d.name[0].isdigit()
        ], key=lambda x: x.name, reverse=True)

        if not backup_dirs:
            return

        # Separate weekly and daily backups
        weekly_backups = []
        daily_backups = []

        for backup_dir in backup_dirs:
            metadata_file = backup_dir / "backup_metadata.json"
            if metadata_file.exists():
                try:
                    with open(metadata_file, 'r') as f:
                        metadata = json.load(f)
                    if metadata.get("is_weekly"):
                        weekly_backups.append(backup_dir)
                    else:
                        daily_backups.append(backup_dir)
                except Exception:
                    daily_backups.append(backup_dir)
            else:
                daily_backups.append(backup_dir)

        # Apply rotation
        backups_to_delete = []

        # Keep only WEEKLY_RETENTION weekly backups
        backups_to_delete.extend(weekly_backups[WEEKLY_RETENTION:])

        # Keep only DAILY_RETENTION daily backups
        backups_to_delete.extend(daily_backups[DAILY_RETENTION:])

        # Delete old backups
        for old_backup in backups_to_delete:
            try:
                shutil.rmtree(old_backup)
                logger.info(f"Deleted old backup: {old_backup.name}")
            except Exception as e:
                logger.error(f"Failed to delete old backup {old_backup.name}: {e}")

    def list_backups(self) -> List[Dict[str, Any]]:
        """List all automatic backups with their metadata."""
        backups = []

        if not BACKUPS_DIR.exists():
            return backups

        for backup_dir in sorted(BACKUPS_DIR.iterdir(), reverse=True):
            if not backup_dir.is_dir():
                continue

            metadata_file = backup_dir / "backup_metadata.json"
            if metadata_file.exists():
                try:
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                    metadata['path'] = str(backup_dir)
                    metadata['name'] = backup_dir.name

                    # Calculate total size
                    total_size = sum(
                        f.stat().st_size
                        for f in backup_dir.rglob('*')
                        if f.is_file()
                    )
                    metadata['total_size_bytes'] = total_size
                    metadata['total_size_human'] = self._format_size(total_size)

                    backups.append(metadata)
                except Exception as e:
                    logger.warning(f"Could not read metadata for {backup_dir.name}: {e}")
                    backups.append({
                        'name': backup_dir.name,
                        'path': str(backup_dir),
                        'error': str(e)
                    })

        return backups

    @staticmethod
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


# Global scheduler instance
_scheduler: Optional[BackupScheduler] = None


def get_backup_scheduler() -> BackupScheduler:
    """Get or create the global backup scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackupScheduler()
    return _scheduler


def init_backup_scheduler():
    """Initialize and start the backup scheduler."""
    scheduler = get_backup_scheduler()
    scheduler.start()
    return scheduler
