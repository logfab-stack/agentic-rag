"""
File Integrity Scheduler Service (Feature #293)

Implements scheduled background job to periodically check all documents
for file integrity and mark missing files.

Features:
- Periodic scan of all documents (default: every 6 hours)
- Checks if file exists on disk
- Updates status to 'file_missing' for orphaned records
- Restores status to 'ok' if file reappears
- Status tracking and configuration via settings

Usage:
    from services.file_integrity_scheduler import init_file_integrity_scheduler

    scheduler = init_file_integrity_scheduler()
    scheduler.start()
"""

import os
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from threading import Lock

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

logger = logging.getLogger(__name__)

# Default interval in hours
DEFAULT_CHECK_INTERVAL_HOURS = 6


class FileIntegrityScheduler:
    """
    Manages scheduled file integrity checks for all documents.

    Features:
    - Configurable check interval (default: 6 hours)
    - Scans all documents and verifies file existence
    - Updates file_status in database
    - Status tracking
    """

    _instance: Optional['FileIntegrityScheduler'] = None
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
        self._job_id = "file_integrity_check"
        self._enabled = True  # Enabled by default
        self._check_interval_hours = DEFAULT_CHECK_INTERVAL_HOURS
        self._last_check_time: Optional[datetime] = None
        self._last_check_status: str = "never"
        self._last_check_error: Optional[str] = None
        self._next_check_time: Optional[datetime] = None
        self._check_in_progress = False
        self._last_check_stats: Dict[str, Any] = {}

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
        logger.info("[Feature #293] FileIntegrityScheduler initialized")

    def _load_settings(self):
        """Load file integrity check settings from settings store."""
        try:
            from core.store import settings_store
            self._enabled = settings_store.get("file_integrity_check_enabled", True)
            self._check_interval_hours = settings_store.get(
                "file_integrity_check_interval_hours",
                DEFAULT_CHECK_INTERVAL_HOURS
            )

            # Load last check info
            last_check_str = settings_store.get("file_integrity_last_check_time")
            if last_check_str:
                try:
                    self._last_check_time = datetime.fromisoformat(last_check_str)
                except (ValueError, TypeError):
                    pass

            self._last_check_status = settings_store.get("file_integrity_last_check_status", "never")
            self._last_check_error = settings_store.get("file_integrity_last_check_error")

            logger.info(f"[Feature #293] File integrity settings loaded: enabled={self._enabled}, interval={self._check_interval_hours}h")
        except Exception as e:
            logger.error(f"[Feature #293] Failed to load file integrity settings: {e}")

    def _save_settings(self):
        """Save file integrity check settings to settings store."""
        try:
            from core.store import settings_store
            settings_store.set("file_integrity_check_enabled", self._enabled)
            settings_store.set("file_integrity_check_interval_hours", self._check_interval_hours)

            if self._last_check_time:
                settings_store.set("file_integrity_last_check_time", self._last_check_time.isoformat())

            settings_store.set("file_integrity_last_check_status", self._last_check_status)
            settings_store.set("file_integrity_last_check_error", self._last_check_error)
        except Exception as e:
            logger.error(f"[Feature #293] Failed to save file integrity settings: {e}")

    def _on_job_executed(self, event):
        """Handle successful job execution."""
        if event.job_id == self._job_id:
            self._last_check_time = datetime.now(timezone.utc)
            self._last_check_status = "success"
            self._last_check_error = None
            self._update_next_check_time()
            self._save_settings()
            logger.info("[Feature #293] File integrity check completed successfully")

    def _on_job_error(self, event):
        """Handle job execution error."""
        if event.job_id == self._job_id:
            self._last_check_time = datetime.now(timezone.utc)
            self._last_check_status = "failed"
            self._last_check_error = str(event.exception) if event.exception else "Unknown error"
            self._update_next_check_time()
            self._save_settings()
            logger.error(f"[Feature #293] File integrity check failed: {self._last_check_error}")

    def _update_next_check_time(self):
        """Update the next scheduled check time."""
        job = self._scheduler.get_job(self._job_id)
        if job:
            self._next_check_time = job.next_run_time
        else:
            self._next_check_time = None

    def start(self):
        """Start the scheduler."""
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("[Feature #293] FileIntegrityScheduler started")

        if self._enabled:
            self._schedule_check()

    def stop(self):
        """Stop the scheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("[Feature #293] FileIntegrityScheduler stopped")

    def _schedule_check(self):
        """Schedule the file integrity check job."""
        # Remove existing job if any
        if self._scheduler.get_job(self._job_id):
            self._scheduler.remove_job(self._job_id)

        # Add new job with configured interval
        trigger = IntervalTrigger(hours=self._check_interval_hours)

        self._scheduler.add_job(
            self._run_check,
            trigger=trigger,
            id=self._job_id,
            name="File Integrity Check",
            replace_existing=True
        )

        self._update_next_check_time()
        logger.info(f"[Feature #293] File integrity check scheduled every {self._check_interval_hours} hours")

    def enable(self, interval_hours: int = None):
        """Enable file integrity checks."""
        if interval_hours is not None:
            self._check_interval_hours = max(1, min(24, interval_hours))

        self._enabled = True
        self._save_settings()

        if self._scheduler.running:
            self._schedule_check()

        logger.info(f"[Feature #293] File integrity checks enabled (every {self._check_interval_hours}h)")

    def disable(self):
        """Disable file integrity checks."""
        self._enabled = False
        self._save_settings()

        # Remove scheduled job
        if self._scheduler.get_job(self._job_id):
            self._scheduler.remove_job(self._job_id)
            self._next_check_time = None

        logger.info("[Feature #293] File integrity checks disabled")

    def get_status(self) -> Dict[str, Any]:
        """Get current file integrity scheduler status."""
        return {
            "enabled": self._enabled,
            "check_interval_hours": self._check_interval_hours,
            "last_check_time": self._last_check_time.isoformat() if self._last_check_time else None,
            "last_check_status": self._last_check_status,
            "last_check_error": self._last_check_error,
            "next_check_time": self._next_check_time.isoformat() if self._next_check_time else None,
            "check_in_progress": self._check_in_progress,
            "last_check_stats": self._last_check_stats,
        }

    def run_now(self) -> Dict[str, Any]:
        """Run a file integrity check immediately (manual trigger)."""
        if self._check_in_progress:
            return {
                "success": False,
                "error": "A file integrity check is already in progress"
            }

        try:
            result = self._run_check()
            return {
                "success": True,
                "stats": result,
                "message": "File integrity check completed successfully"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def _run_check(self) -> Dict[str, Any]:
        """
        Execute the file integrity check operation.

        Scans all documents and:
        - Marks missing files as 'file_missing'
        - Restores 'ok' status for files that reappear

        Returns:
            Dict with check results
        """
        self._check_in_progress = True

        try:
            from core.database import SessionLocal
            from models.db_models import DBDocument, FILE_STATUS_MISSING, FILE_STATUS_OK

            logger.info("[Feature #293] Starting file integrity check...")

            stats = {
                "total_documents": 0,
                "files_checked": 0,
                "files_ok": 0,
                "files_missing": 0,
                "files_restored": 0,
                "status_unchanged": 0,
                "errors": [],
            }

            with SessionLocal() as session:
                documents = session.query(DBDocument).all()
                stats["total_documents"] = len(documents)

                for doc in documents:
                    try:
                        # Get file path
                        file_path = doc.file_path or doc.url
                        if not file_path:
                            # Structured data (CSV, JSON, Excel) - no file to check
                            stats["status_unchanged"] += 1
                            continue

                        stats["files_checked"] += 1
                        current_status = getattr(doc, 'file_status', 'ok')
                        file_exists = os.path.exists(file_path)

                        if file_exists:
                            stats["files_ok"] += 1
                            # File exists - ensure status is 'ok'
                            if current_status == FILE_STATUS_MISSING:
                                doc.file_status = FILE_STATUS_OK
                                stats["files_restored"] += 1
                                logger.info(f"[Feature #293] File restored: {doc.id[:8]}... ({doc.title[:30]})")
                        else:
                            stats["files_missing"] += 1
                            # File missing - update status
                            if current_status != FILE_STATUS_MISSING:
                                doc.file_status = FILE_STATUS_MISSING
                                logger.warning(f"[Feature #293] File missing: {doc.id[:8]}... ({doc.title[:30]}) - {file_path}")
                    except Exception as e:
                        stats["errors"].append(f"Error checking {doc.id}: {str(e)}")
                        logger.error(f"[Feature #293] Error checking document {doc.id}: {e}")

                # Commit all status updates
                session.commit()

            # Update scheduler stats
            self._last_check_stats = stats
            self._last_check_time = datetime.now(timezone.utc)
            self._last_check_status = "success"
            self._last_check_error = None
            self._save_settings()

            logger.info(f"[Feature #293] File integrity check complete: "
                       f"{stats['total_documents']} docs, "
                       f"{stats['files_ok']} ok, "
                       f"{stats['files_missing']} missing, "
                       f"{stats['files_restored']} restored")

            return stats

        except Exception as e:
            logger.error(f"[Feature #293] File integrity check failed: {e}")
            self._last_check_time = datetime.now(timezone.utc)
            self._last_check_status = "failed"
            self._last_check_error = str(e)
            self._save_settings()
            raise
        finally:
            self._check_in_progress = False


# Global scheduler instance
_scheduler: Optional[FileIntegrityScheduler] = None


def get_file_integrity_scheduler() -> FileIntegrityScheduler:
    """Get or create the global file integrity scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = FileIntegrityScheduler()
    return _scheduler


def init_file_integrity_scheduler():
    """Initialize and start the file integrity scheduler."""
    scheduler = get_file_integrity_scheduler()
    scheduler.start()
    return scheduler
